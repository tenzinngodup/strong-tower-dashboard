"""Read the SDR's Zoom Phone call log and compute call-volume stats.

Source: /opt/data/profiles/strong-tower/workspace/leads/phone_call_log.csv
        (a normalized version of the Zoom Phone export)

The log has one row per outbound call. Each record includes:
    date, direction, callee_phone (masked in Zoom export), result, duration,
    wait_time, agent_inferred.

What the dashboard surfaces from this file:
    - Total dials (last 30d, last 7d, today)
    - Connect rate (connected / total)
    - Total talk time
    - Average call length
    - Per-day dial volume (sparkline)
    - Top call result types (Connected, Call Failed, Canceled, etc.)
    - ROUGH ESTIMATE of "leads called": unique callee phone numbers × connect
      rate. We CANNOT match callee numbers to HubSpot companies without
      HubSpot phone numbers (which the dashboard doesn't fetch). The number
      shown is therefore an UPPER BOUND on the "called" count, with a
      large footnote explaining the limitation.

Failure isolation: file might be missing (Zoom export not yet run). Each
case returns ok=False with a clear error; the dashboard still renders.
"""
from __future__ import annotations
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import safe_source_payload  # noqa: E402

LEADS_DIR = Path("/opt/data/profiles/strong-tower/workspace/leads")
CALL_LOG_FILE = LEADS_DIR / "phone_call_log.csv"


def _read_calls(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_duration(s: str) -> int:
    """Parse 'HH:MM:SS' to seconds. Empty/garbage -> 0."""
    if not s or not isinstance(s, str):
        return 0
    s = s.strip()
    if not s:
        return 0
    parts = s.split(":")
    if len(parts) != 3:
        return 0
    try:
        h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
        return h * 3600 + m * 60 + sec
    except (TypeError, ValueError):
        return 0


def collect() -> dict:
    if not CALL_LOG_FILE.exists():
        return safe_source_payload(
            "phone_call",
            {},
            error=f"phone_call_log.csv not found at {CALL_LOG_FILE}. "
                  f"Run the Zoom Phone export → save to that path.",
        )

    try:
        rows = _read_calls(CALL_LOG_FILE)
    except Exception as e:
        return safe_source_payload("phone_call", {}, error=f"CSV read failed: {e}")

    if not rows:
        return safe_source_payload("phone_call", {}, error="phone_call_log.csv is empty")

    # All rows in the Zoom export are outbound; just normalize and aggregate.
    # v3.1.1 fix: phone_call_log.csv uses prefixed column names (call_result,
    # call_duration, call_date) — earlier version expected bare names (result,
    # duration, date) and silently returned 0s.
    results = Counter(r.get("call_result", "") for r in rows)
    total = len(rows)
    connected = results.get("Connected", 0)
    failed = results.get("Call Failed", 0) + results.get("Canceled", 0)

    # Total talk time (only Connected calls have duration > 0 typically)
    total_talk_sec = sum(_parse_duration(r.get("call_duration", "")) for r in rows if r.get("call_result") == "Connected")
    avg_call_sec = round(total_talk_sec / connected) if connected else 0

    # Date range
    dates = sorted(set(r.get("call_date", "")[:10] for r in rows if r.get("call_date")))
    if dates:
        first_date = dates[0]
        last_date = dates[-1]
    else:
        first_date = last_date = ""

    # Per-day volume (last 14d)
    per_day = Counter(r.get("call_date", "")[:10] for r in rows if r.get("call_date"))
    last_14 = []
    today = datetime.now(timezone.utc).date()
    for i in range(13, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        last_14.append({"date": d, "dials": per_day.get(d, 0)})

    # Window-based aggregates (last 7d, last 30d)
    d7_cutoff = (today - timedelta(days=7)).isoformat()
    d30_cutoff = (today - timedelta(days=30)).isoformat()
    last7 = [r for r in rows if (r.get("call_date", "")[:10] or "") >= d7_cutoff]
    last30 = [r for r in rows if (r.get("call_date", "")[:10] or "") >= d30_cutoff]
    last7_connected = sum(1 for r in last7 if r.get("call_result") == "Connected")
    last30_connected = sum(1 for r in last30 if r.get("call_result") == "Connected")

    # Unique callees (using to_phone_masked as the dedup key — masked form is
    # stable per number, so a number dialed twice = 1 unique callee)
    unique_callees = set(r.get("to_phone_masked", "") for r in rows if r.get("to_phone_masked"))
    unique_connected = set(r.get("to_phone_masked", "") for r in rows
                           if r.get("to_phone_masked") and r.get("call_result") == "Connected")

    # Freshness: when was the log last written?
    try:
        mtime = datetime.fromtimestamp(CALL_LOG_FILE.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        freshness = _humanize_age(age_hours)
    except Exception:
        age_hours = None
        freshness = "unknown"

    return safe_source_payload(
        "phone_call",
        {
            "total_dials":        total,
            "connected":          connected,
            "failed":             failed,
            "connect_rate":       round(100.0 * connected / total, 1) if total else 0.0,
            "total_talk_min":     round(total_talk_sec / 60, 1),
            "avg_call_sec":       avg_call_sec,
            "unique_callees":     len(unique_callees),
            "unique_connected":   len(unique_connected),
            "rough_calls_connected_estimate": len(unique_connected),
            "last_7d_dials":      len(last7),
            "last_7d_connected":  last7_connected,
            "last_30d_dials":     len(last30),
            "last_30d_connected": last30_connected,
            "per_day_14d":        last_14,
            "result_breakdown":   dict(results),
            "date_range":         {"first": first_date, "last": last_date},
            "freshness":          freshness,
            "file_age_hours":     round(age_hours, 1) if age_hours is not None else None,
            "note": (
                "Source: Zoom Phone export (manually normalized to phone_call_log.csv). "
                "All 245 outbound calls are from heber@minyn.link (ext 800), NOT a per-agent "
                "phone system — so we cannot attribute calls to steven specifically from Zoom alone. "
                "(Confirmed by user that steven is the actual dialer; recorded as is_steven_call=y "
                "in the log.) Callee phone numbers in the Zoom export are masked to last-4 (e.g. "
                "+150****9596), and the middle 3 digits of the 7-digit local number are also "
                "masked. Matching to HubSpot companies now uses E.164 exact match on the unmasked "
                "portion + a fallback to the 06-18 inbound phone list. See phone.py source for "
                "the per-company attribution. This phone_call.py source shows gross volume only."
            ),
        },
    )


def _humanize_age(hours: float) -> str:
    if hours < 1:
        return f"{int(hours * 60)}m old"
    if hours < 24:
        return f"{int(hours)}h old"
    days = hours / 24
    if days < 30:
        return f"{int(days)}d old"
    return f"{int(days / 30)}mo old"


if __name__ == "__main__":
    out = collect()
    print(json.dumps(out, indent=2))
