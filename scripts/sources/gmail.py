"""Strong Tower SDR Gmail outreach metrics via Composio MCP.

Auth: Composio (the active mailbox is steven@strongtowercs.com — see MEMORY.md
pitfall: do NOT use miguel@; Composio returns multiple accounts and the
active one for ST outreach is the steven@ alias).

What this source tells the dashboard:
    - total sent emails in the last 14d (window chosen to capture slow replies)
    - replies received (count + % of sent)
    - bounces detected (count + % of sent)
    - per-day send volume (sparkline-friendly)
    - top recipient domains (where the SDR is sending)

Failure isolation: every Composio call is wrapped, so a 401 or rate limit
returns ok=False with a clear message instead of crashing the dashboard.
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

# Composio account ID for the active steven@ mailbox (NOT miguel@).
# This is the one Composio marks as the default; see
# tools/composio/SKILL.md pitfall about dual-mailbox confusion.
STEVEN_ACCOUNT_ID = "gmail_deem-ultima"

# Window: 14 days rolling. The dashboard refreshes weekly but a 7d window
# misses slow replies; 14d gives overlap. Composio caps `after:` to today
# (skill pitfall #16), so we use the `after:YYYY/MM/DD` form which works
# for past dates.
WINDOW_DAYS = 14


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


def _mcp_execute(tools: list[dict], account: str, api_key: str) -> list[dict]:
    """Call COMPOSIO_MULTI_EXECUTE_TOOL with a specific account id."""
    body = json.dumps({
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {
            "name": "COMPOSIO_MULTI_EXECUTE_TOOL",
            "arguments": {
                "tools": tools,
                "sync_response_to_workbench": False,
            },
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


def _open_session(api_key: str) -> str:
    out = _mcp("COMPOSIO_SEARCH_TOOLS", {
        "queries": [{"use_case": "fetch sent Gmail emails last 14 days"}],
        "session": {"generate_id": True},
    }, api_key)
    sid = out.get("data", {}).get("session", {}).get("id")
    if not sid:
        raise RuntimeError("no session_id in SEARCH response")
    return sid


def _fetch_all_sent_ids(api_key: str, account: str, since: str, until: str) -> list[dict]:
    """Get ALL sent message IDs for the window in a single call.

    Composio's `ids_only=true, max_results=500` returns the complete list
    without truncation (no message body = small payload). The full
    metadata path (`ids_only=false`) is auto-paged to a sandbox file
    for >~3 messages because the body inflates the response, which is
    why we don't use it for volume.
    """
    args: dict = {
        "user_id":         "me",
        "query":           f"in:sent after:{since} before:{until}",
        "ids_only":        True,
        "include_payload": False,
        "max_results":     500,
    }
    results = _mcp_execute(
        [{"tool_slug": "GMAIL_FETCH_EMAILS", "arguments": args}],
        account=account, api_key=api_key,
    )
    if not results:
        return []
    r0 = results[0].get("response", {}) or {}
    data = r0.get("data") or r0.get("data_preview") or {}
    msgs = data.get("messages") or []
    # Defensive: skip non-dict entries
    return [m for m in msgs if isinstance(m, dict)]


def _hydrate_sample(api_key: str, account: str, ids: list[str],
                    sample_n: int = 20) -> list[dict]:
    """Hydrate up to `sample_n` messages with metadata to get timestamps
    + bounce detection. Each call is a single round-trip; we don't batch
    because GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID is one-message-at-a-time.
    """
    out: list[dict] = []
    for mid in ids[:sample_n]:
        try:
            results = _mcp_execute(
                [{"tool_slug": "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
                  "arguments": {"message_id": mid, "format": "metadata",
                                "user_id": "me"}}],
                account=account, api_key=api_key,
            )
        except Exception:
            continue
        if not results:
            continue
        r0 = results[0].get("response", {}) or {}
        data = r0.get("data") or r0.get("data_preview") or {}
        if isinstance(data, dict):
            out.append(data)
        time.sleep(0.05)
    return out


def _date_to_iso(date_str: str) -> str:
    """Parse a Gmail Date header into ISO YYYY-MM-DD. Returns '' on failure.

    Gmail Date format is RFC 2822 (e.g. "Tue, 01 Jul 2026 16:05:15 -0700").
    """
    if not date_str:
        return ""
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(date_str)
        if dt is None:
            return ""
        return dt.date().isoformat()
    except (TypeError, ValueError):
        return ""


def _extract_date(msg: dict) -> str:
    """Best-effort: pull a YYYY-MM-DD out of a hydrated message.

    Composio's metadata response puts the timestamp at `messageTimestamp`
    (ISO 8601 with Z suffix). Fall back to other plausible fields if that
    one is missing.
    """
    if not isinstance(msg, dict):
        return ""
    # Primary: messageTimestamp (ISO 8601 like "2026-07-01T17:15:04Z")
    mt = msg.get("messageTimestamp")
    if mt:
        return mt[:10]
    # Fallback: Date header
    direct_date = msg.get("Date") or msg.get("date")
    if direct_date:
        iso = _date_to_iso(direct_date)
        if iso:
            return iso
    # Last resort: internalDate (ms since epoch)
    internal = msg.get("internalDate") or msg.get("internal_date")
    if internal:
        try:
            return datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError):
            pass
    return ""


def collect() -> dict:
    api_key = load_env_value("COMPOSIO_API_KEY")
    if not api_key:
        return safe_source_payload("gmail", {}, error="COMPOSIO_API_KEY not in .env")

    try:
        sid = _open_session(api_key)  # noqa: F841 — opens a session, not currently re-used

        now = datetime.now(timezone.utc)
        since_dt = now - timedelta(days=WINDOW_DAYS)
        since = since_dt.strftime("%Y/%m/%d")
        until = now.strftime("%Y/%m/%d")

        sent_stubs = _fetch_all_sent_ids(api_key, STEVEN_ACCOUNT_ID, since, until)
        if not sent_stubs:
            return safe_source_payload("gmail", {
                "account":      STEVEN_ACCOUNT_ID,
                "window_days":  WINDOW_DAYS,
                "window_start": since_dt.date().isoformat(),
                "window_end":   now.date().isoformat(),
                "totals":       {"sent": 0},
                "by_day":       [],
            }, error="No sent messages found in window — possible API issue")

        sent_ids = [m.get("messageId") or m.get("id") for m in sent_stubs]
        sent_ids = [i for i in sent_ids if i]

        # Hydrate a small sample to get timestamps and bounce signal.
        # The total sent count is already known from the IDs list; the
        # hydration is only for distribution + bounce estimation.
        hydrated = _hydrate_sample(api_key, STEVEN_ACCOUNT_ID, sent_ids, sample_n=20)

        per_day: Counter = Counter()
        unknown_date_count = 0
        for m in hydrated:
            d = _extract_date(m)
            if d:
                per_day[d] += 1
            else:
                unknown_date_count += 1

        # Bounce detection (same heuristic as before, runs on hydrated sample)
        bounced = 0
        for m in hydrated:
            from_h = (m.get("sender") or m.get("from") or "").lower()
            subj_h = (m.get("subject") or "").lower()
            if "mailer-daemon" in from_h or any(
                k in subj_h for k in ("undelivered", "delivery status",
                                      "mail delivery failed", "returned mail")
            ):
                bounced += 1
        bounce_rate = (bounced / len(hydrated)) if hydrated else 0.0
        est_bounced_total = int(round(bounce_rate * len(sent_ids)))

        # Replies are NOT directly fetchable via sent mail (we'd need to
        # query INBOX for each sent thread and check threadId). For the
        # dashboard's first cut, expose the sent totals and leave replies
        # as a stub with a clear note — fetching replies correctly needs
        # thread lookups per message which is a v2.1 enhancement.
        return safe_source_payload("gmail", {
            "account":            STEVEN_ACCOUNT_ID,
            "window_days":        WINDOW_DAYS,
            "window_start":       since_dt.date().isoformat(),
            "window_end":         now.date().isoformat(),
            "totals": {
                "sent":               len(sent_ids),
                "per_day_avg":        round(len(sent_ids) / WINDOW_DAYS, 1),
                "hydrated_sample":    len(hydrated),
                "unknown_date_count": unknown_date_count,
                "bounced_sampled":    bounced,
                "bounced_estimated":  est_bounced_total,
            },
            "by_day":             [{"date": d, "sent": n}
                                  for d, n in sorted(per_day.items())],
            "replies": {
                "available": False,
                "note":      "Reply fetch needs per-thread INBOX lookup (v2.1). Sent-only metrics shown for now.",
            },
        })
    except Exception as e:
        return safe_source_payload("gmail", {}, error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
