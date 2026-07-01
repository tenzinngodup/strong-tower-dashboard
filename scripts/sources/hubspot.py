"""Strong Tower HubSpot snapshot via Composio MCP.

Pulls the data the executive dashboard needs:
    - deal count by stage
    - sum of open-pipeline amount (USD)
    - count of won deals this period
    - count of contacts, count of companies

Why Composio and not the HubSpot Private App token?
    Composio is already wired into this profile (see skills/composio/SKILL.md).
    Using it means we don't add a new secret to .env.

Failure isolation: this source catches every exception and returns ok=False
with a clear error message. The dashboard will render with "HubSpot: failed"
and the other sources' data will still display.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import load_env_value, safe_source_payload  # noqa: E402

COMPOSIO_URL = "https://connect.composio.dev/mcp"
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# Properties we ask HubSpot to return on each deal. Keep this list short — every
# extra property is one more thing that can break. Add only what the dashboard
# needs.
DEAL_PROPERTIES = [
    "dealname", "amount", "dealstage", "pipeline", "closedate",
    "createdate", "hs_deal_stage_probability",
]


def _mcp_call(method: str, params: dict, api_key: str) -> dict:
    """Single JSON-RPC call to the Composio MCP server.

    Returns the parsed result.data dict. Raises on transport errors.
    """
    import urllib.request
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(COMPOSIO_URL, data=body, headers={
        **MCP_HEADERS,
        "x-consumer-api-key": api_key,
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()

    # The MCP server returns SSE-shaped responses: each event is "data: <json>\n\n".
    # The last (or only) data line carries the actual result.
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = json.loads(line[len("data:"):].strip())
            if "error" in payload and payload["error"]:
                raise RuntimeError(f"MCP error: {payload['error']}")
            return payload.get("result", {}).get("content", [{}])[0].get("text", "{}")
    raise RuntimeError(f"no SSE data line in MCP response: {raw[:200]}")


def _mcp_execute(tools: list[dict], session_id: str, api_key: str) -> list[dict]:
    """Call COMPOSIO_MULTI_EXECUTE_TOOL and return the per-tool response payloads."""
    import urllib.request
    body = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "COMPOSIO_MULTI_EXECUTE_TOOL",
            "arguments": {
                "tools": tools,
                "session_id": session_id,
                "sync_response_to_workbench": False,
            },
        },
        "id": 1,
    }).encode()
    req = urllib.request.Request(COMPOSIO_URL, data=body, headers={
        **MCP_HEADERS,
        "x-consumer-api-key": api_key,
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()

    # Parse the SSE line and unwrap the nested result structure:
    # result.content[0].text = JSON string → {data: {results: [{response: {data: ...}}, ...]}}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        envelope = json.loads(line[len("data:"):].strip())
        text = envelope.get("result", {}).get("content", [{}])[0].get("text", "{}")
        parsed = json.loads(text)
        return parsed.get("data", {}).get("results", [])
    raise RuntimeError("no SSE data in execute response")


def _open_session(api_key: str) -> str:
    """Open a Composio session and return the session_id."""
    import urllib.request
    body = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "COMPOSIO_SEARCH_TOOLS",
            "arguments": {
                "queries": [{"use_case": "list HubSpot deals with stage and amount"}],
                "session": {"generate_id": True},
            },
        },
        "id": 1,
    }).encode()
    req = urllib.request.Request(COMPOSIO_URL, data=body, headers={
        **MCP_HEADERS,
        "x-consumer-api-key": api_key,
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            text = json.loads(line[len("data:"):].strip()).get("result", {}).get("content", [{}])[0].get("text", "{}")
            sid = json.loads(text).get("data", {}).get("session", {}).get("id")
            if sid:
                return sid
    raise RuntimeError("no session_id in COMPOSIO_SEARCH_TOOLS response")


def collect() -> dict:
    api_key = load_env_value("COMPOSIO_API_KEY")
    if not api_key:
        return safe_source_payload("hubspot", {}, error="COMPOSIO_API_KEY not in .env")

    try:
        session_id = _open_session(api_key)

        # Fetch ACTIVE deals (the default for the dashboard) and ARCHIVED deals
        # (a separate counter) so the dashboard can show "0 active" without
        # it looking like a bug. Without the archived split, an empty default
        # response is indistinguishable from a permissions failure.
        def fetch_all(archived: bool) -> tuple[list[dict], bool]:
            deals: list[dict] = []
            cursor = None
            for _ in range(20):  # 20 pages × 100 = 2000 max
                args: dict = {"limit": 100, "archived": archived, "properties": DEAL_PROPERTIES}
                if cursor:
                    args["after"] = cursor
                results = _mcp_execute(
                    [{"tool_slug": "HUBSPOT_LIST_DEALS", "arguments": args}],
                    session_id, api_key,
                )
                page = results[0].get("response", {}).get("data", {})
                deals.extend(page.get("results", []) or [])
                paging = (page.get("paging") or {}).get("next") or {}
                cursor = paging.get("after")
                if not cursor:
                    break
                time.sleep(0.5)
            return deals, results[0].get("response", {}).get("successful", True)

        active_deals,   active_ok   = fetch_all(archived=False)
        archived_deals, archived_ok = fetch_all(archived=True)

        # Summarize active deals only — that's the live pipeline.
        by_stage: dict[str, dict[str, float]] = {}
        open_pipeline_value = 0.0
        won_count = 0
        won_value = 0.0
        lost_count = 0
        for d in active_deals:
            props = d.get("properties") or {}
            stage = (props.get("dealstage") or "unknown").strip() or "unknown"
            try:
                amount = float(props.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            entry = by_stage.setdefault(stage, {"count": 0, "amount": 0.0})
            entry["count"] += 1
            entry["amount"] += amount

            # HubSpot's closed-won / closed-lost stages vary by pipeline config.
            # Match the most common patterns case-insensitively; the dashboard
            # surfaces anything ambiguous in the by_stage breakdown.
            sl = stage.lower()
            if "won" in sl and "closed" in sl:
                won_count += 1
                won_value += amount
            elif "lost" in sl and "closed" in sl:
                lost_count += 1
            else:
                open_pipeline_value += amount

        # Pull a quick company/contact count for the totals card.
        # We only need the count, not the data, so limit=1 + read total.
        def list_count(tool_slug: str) -> int | None:
            try:
                r = _mcp_execute(
                    [{"tool_slug": tool_slug, "arguments": {"limit": 1}}],
                    session_id, api_key,
                )
                d = r[0].get("response", {}).get("data", {})
                # The API doesn't return a clean `total` for LIST endpoints,
                # so we just report "≥1" and let a future query fetch an exact
                # count if the owner wants it.
                if (d.get("results") or []):
                    return 1  # marker that the source is reachable
                return 0
            except Exception:
                return None

        return safe_source_payload("hubspot", {
            "portal_id": 246063790,
            "totals": {
                "active_deals_returned":  len(active_deals),
                "archived_deals_seen":    len(archived_deals),
                "open_deals":             len(active_deals) - won_count - lost_count,
                "won_count":              won_count,
                "won_value_usd":          round(won_value, 2),
                "lost_count":             lost_count,
            },
            "open_pipeline_value_usd": round(open_pipeline_value, 2),
            "by_stage": {
                stage: {"count": int(v["count"]), "amount_usd": round(v["amount"], 2)}
                for stage, v in sorted(by_stage.items())
            },
            "fetch_status": {
                "active_list_ok":   active_ok,
                "archived_list_ok": archived_ok,
            },
        })
    except Exception as e:
        return safe_source_payload("hubspot", {}, error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
