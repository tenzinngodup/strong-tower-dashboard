"""Strong Tower HubSpot engagement events: calls, meetings, emails.

Uses the same Composio MCP pattern as hubspot.py (deals), but for the
engagement-event object types. Tells the dashboard:
    - call volume in last 14d
    - meeting volume in last 14d
    - email volume in last 14d
    - per-day distribution for each (sparkline-friendly)

Known limitation: HUBSPOT_READ_APAGE_OF_OBJECTS_BY_TYPE returns only
`hs_createdate` and `hs_object_id` by default in this Composio MCP version.
The `properties` parameter is currently rejected by the wrapper (string
expected, list required), so we don't get per-call duration / disposition
/ outcome yet. The owner gets a useful VOLUME signal; per-call details
are a v2.1 task (or hand-fix the MCP wrapper).

Auth: Composio MCP (existing COMPOSIO_API_KEY from .env).
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import load_env_value, safe_source_payload  # noqa: E402

COMPOSIO_URL = "https://connect.composio.dev/mcp"
HUBSPOT_TOOL = "HUBSPOT_READ_APAGE_OF_OBJECTS_BY_TYPE"

WINDOW_DAYS = 14


def _mcp_execute(tools: list[dict], api_key: str) -> list[dict]:
    body = json.dumps({
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {
            "name": "COMPOSIO_MULTI_EXECUTE_TOOL",
            "arguments": {"tools": tools, "sync_response_to_workbench": False},
        },
        "id": 1,
    }).encode()
    req = urllib.request.Request(COMPOSIO_URL, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-consumer-api-key": api_key,
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode()
    for line in raw.splitlines():
        if line.strip().startswith("data:"):
            env = json.loads(line[5:].strip())
            text = env.get("result", {}).get("content", [{}])[0].get("text", "{}")
            parsed = json.loads(text)
            return parsed.get("data", {}).get("results", [])
    raise RuntimeError("no SSE data in execute response")


def _fetch_all(api_key: str, object_type: str) -> tuple[list[dict], bool]:
    """Paginate through all non-archived events of `object_type` (calls/meetings/emails).

    Returns (list of events, ok flag). Capped at 20 pages × 100 = 2000 to
    avoid runaway. For Strong Tower's volume (~hundreds per month per type)
    this is more than enough.
    """
    events: list[dict] = []
    cursor = None
    ok = True
    for _ in range(20):
        args: dict = {"objectType": object_type, "limit": 100}
        if cursor:
            args["after"] = cursor
        try:
            results = _mcp_execute(
                [{"tool_slug": HUBSPOT_TOOL, "arguments": args}], api_key,
            )
        except Exception:
            ok = False
            break
        if not results:
            break
        r0 = results[0].get("response", {}) or {}
        data = r0.get("data") or r0.get("data_preview") or {}
        if not data.get("successful", True):
            ok = False
            break
        page = data.get("results") or []
        # Defensive: skip non-dict entries (Composio occasionally returns
        # bare strings in result lists)
        page = [e for e in page if isinstance(e, dict)]
        if not page:
            break
        events.extend(page)
        paging = data.get("paging") or {}
        next_pg = paging.get("next") or {}
        cursor = next_pg.get("after")
        if not cursor:
            break
        time.sleep(0.2)
    return events, ok


def _bucket_by_day(events: list[dict], cutoff: datetime) -> tuple[Counter, int]:
    """Return (per-day counts of events with hs_createdate >= cutoff, count_of_in_window)."""
    per_day: Counter = Counter()
    in_window = 0
    for e in events:
        ts = e.get("createdAt") or (e.get("properties") or {}).get("hs_createdate")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if dt < cutoff:
            continue
        per_day[dt.date().isoformat()] += 1
        in_window += 1
    return per_day, in_window


def collect() -> dict:
    api_key = load_env_value("COMPOSIO_API_KEY")
    if not api_key:
        return safe_source_payload("hubspot_events", {}, error="COMPOSIO_API_KEY not in .env")
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=WINDOW_DAYS)

        out: dict = {
            "window_days":  WINDOW_DAYS,
            "window_start": cutoff.date().isoformat(),
            "window_end":   now.date().isoformat(),
        }
        for obj_type in ("calls", "meetings", "emails"):
            events, ok = _fetch_all(api_key, obj_type)
            per_day, in_window = _bucket_by_day(events, cutoff)
            out[obj_type] = {
                "fetched_ok":  ok,
                "total_in_hubspot": len(events),
                "in_window":       in_window,
                "per_day":         [{"date": d, "count": n}
                                    for d, n in sorted(per_day.items())],
            }
            time.sleep(0.2)

        return safe_source_payload("hubspot_events", out)
    except Exception as e:
        return safe_source_payload("hubspot_events", {}, error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
