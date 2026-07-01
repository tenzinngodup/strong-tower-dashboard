"""Strong Tower site analytics via Google Analytics (Composio MCP).

Single source for both GA3 (legacy universal property) and GA4. Right now
Strong Tower's primary property is the GA3 migration at properties/535249173
(MEMORY.md), so we use that. If/when GA4 takes over, swap the constant.

What this source tells the dashboard:
    - total sessions over the last 7 days (matches the biweekly report's metric)
    - top pages by sessions (so the owner can see what's getting traffic)
    - UTM-attributed sessions (instagram / linkedin / blog) — the
      "is social paying off?" signal

Failure isolation: every Composio call is wrapped, so a 401 or rate limit
returns ok=False with a clear message instead of crashing the dashboard.
"""
from __future__ import annotations
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import load_env_value, safe_source_payload  # noqa: E402

COMPOSIO_URL = "https://connect.composio.dev/mcp"

# Strong Tower's GA3 property (migrated from UA, see MEMORY.md).
GA_PROPERTY = "properties/535249173"


def _mcp(name: str, args: dict, api_key: str) -> dict:
    """Single MCP call. Returns the inner text payload parsed as JSON."""
    body = json.dumps({"jsonrpc": "2.0", "method": "tools/call",
                       "params": {"name": name, "arguments": args}, "id": 1}).encode()
    req = urllib.request.Request(COMPOSIO_URL, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-consumer-api-key": api_key,
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode()
    for line in raw.splitlines():
        if line.strip().startswith("data:"):
            t = json.loads(line[5:].strip()).get("result", {}).get("content", [{}])[0].get("text", "{}")
            return json.loads(t)
    raise RuntimeError("no SSE data line in MCP response")


def _open_session(api_key: str) -> str:
    out = _mcp("COMPOSIO_SEARCH_TOOLS", {
        "queries": [{"use_case": "GA4 sessions by page"}],
        "session": {"generate_id": True},
    }, api_key)
    sid = out.get("data", {}).get("session", {}).get("id")
    if not sid:
        raise RuntimeError("no session_id in SEARCH response")
    return sid


def _run_report(sid: str, api_key: str, dimensions: list[str], metrics: list[str],
                limit: int = 10) -> dict:
    """Run a single GA report and return its raw response data dict."""
    out = _mcp("COMPOSIO_MULTI_EXECUTE_TOOL", {
        "tools": [{
            "tool_slug": "GOOGLE_ANALYTICS_RUN_REPORT",
            "arguments": {
                "property": GA_PROPERTY,
                "dateRanges": [{"startDate": "7daysAgo", "endDate": "today"}],
                "dimensions": [{"name": d} for d in dimensions],
                "metrics":    [{"name": m} for m in metrics],
                "limit":      limit,
            },
        }],
        "session_id": sid,
        "sync_response_to_workbench": False,
    }, api_key)
    results = out.get("data", {}).get("results", [])
    if not results:
        raise RuntimeError("no results in GA report")
    return results[0].get("response", {}).get("data", {})


def _parse_ga_rows(data: dict) -> list[dict]:
    """Turn the GA API's header+rows shape into a list of dicts.

    Returns rows in the form:
        [{"pagePath": "/foo", "sessions": "42"}, ...]
    Metric values are always strings (GA's wire format); we cast ints when
    we know it's safe.
    """
    metric_names = [h["name"] for h in data.get("metricHeaders", [])]
    dim_names    = [h["name"] for h in data.get("dimensionHeaders", [])]
    out: list[dict] = []
    for row in data.get("rows", []) or []:
        record: dict = {}
        for i, dim_value in enumerate(row.get("dimensionValues", [])):
            if i < len(dim_names):
                record[dim_names[i]] = dim_value.get("value")
        for i, met_value in enumerate(row.get("metricValues", [])):
            if i < len(metric_names):
                v = met_value.get("value")
                # Cast known-integer metrics.
                if metric_names[i] in ("sessions", "screenPageViews",
                                       "engagedSessions", "totalUsers"):
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        pass
                record[metric_names[i]] = v
        out.append(record)
    return out


def collect() -> dict:
    api_key = load_env_value("COMPOSIO_API_KEY")
    if not api_key:
        return safe_source_payload("ga4", {}, error="COMPOSIO_API_KEY not in .env")

    try:
        sid = _open_session(api_key)

        # 1. Total sessions + pageviews (matches the biweekly report's slide 7).
        totals_data = _run_report(sid, api_key,
                                  dimensions=[],
                                  metrics=["sessions", "screenPageViews"])
        totals_rows = _parse_ga_rows(totals_data)
        totals = totals_rows[0] if totals_rows else {"sessions": 0, "screenPageViews": 0}

        # 2. Top 10 pages by sessions.
        pages_data = _run_report(sid, api_key,
                                 dimensions=["pagePath"],
                                 metrics=["sessions"],
                                 limit=10)
        top_pages = _parse_ga_rows(pages_data)

        # 3. UTM-attributed sessions by source. Strong Tower's UTMs follow
        # `utm_source=instagram|linkedin|blog` per HEARTBEAT.md.
        # GA's `sessionSource` is the closest dimension; filter via a regex.
        utm_data = _run_report(sid, api_key,
                               dimensions=["sessionSource"],
                               metrics=["sessions"],
                               limit=50)
        utm_rows = _parse_ga_rows(utm_data)
        utm_summary = {
            "instagram": 0,
            "linkedin":  0,
            "blog":      0,  # the blog itself is a referrer when UTM is not set
            "other":     0,
        }
        for r in utm_rows:
            src = (r.get("sessionSource") or "").lower()
            sess = r.get("sessions", 0) or 0
            if "instagram" in src:
                utm_summary["instagram"] += sess
            elif "linkedin" in src:
                utm_summary["linkedin"] += sess
            elif src in ("strongtowercs.com", "blog.strongtowercs.com") or "blog" in src:
                utm_summary["blog"] += sess
            else:
                utm_summary["other"] += sess

        return safe_source_payload("ga4", {
            "property":     GA_PROPERTY,
            "window":       "last_7_days",
            "totals": {
                "sessions":       totals.get("sessions", 0),
                "screenPageViews": totals.get("screenPageViews", 0),
            },
            "top_pages":    top_pages,
            "by_source":    utm_summary,
        })
    except Exception as e:
        return safe_source_payload("ga4", {}, error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
