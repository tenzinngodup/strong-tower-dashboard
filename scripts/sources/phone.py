"""Read the matched Zoom-call-to-HubSpot-contact table and surface per-company
phone attribution for the dashboard.

Source: /opt/data/profiles/strong-tower/workspace/leads/call_to_contact_matches.csv
        (built by leads/match_calls.py from phone_call_log.csv +
         hubspot_contacts_with_phones.csv via E.164 normalization)

The match file is one row per matched call (147 of 245 outbound, 60% match rate).
For the dashboard we aggregate up to:
    - total_matched_calls
    - connected_matched_calls
    - unique_companies_called (with the contact + company_id)
    - per-company call counts (for "Outreach by person" section)
    - is_steven_calls split (all 245 are steven per user statement; all
      recorded as is_steven_call=y in phone_call_log.csv with caller_line_owner
      heber@minyn.link recorded separately for honesty)

This is the per-company complement to phone_call.py (which is gross volume).
"""
from __future__ import annotations
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import safe_source_payload  # noqa: E402

LEADS_DIR = Path("/opt/data/profiles/strong-tower/workspace/leads")
MATCHES_FILE = LEADS_DIR / "call_to_contact_matches.csv"
CALL_LOG_FILE = LEADS_DIR / "phone_call_log.csv"


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_call_log_lookup() -> dict[str, dict]:
    """Build {call_id: row} from phone_call_log.csv for joining is_steven + line_owner."""
    if not CALL_LOG_FILE.exists():
        return {}
    out: dict[str, dict] = {}
    for r in _read(CALL_LOG_FILE):
        cid = r.get("call_id", "")
        if cid:
            out[cid] = r
    return out


def collect() -> dict:
    if not MATCHES_FILE.exists():
        return safe_source_payload(
            "phone",
            {},
            error=f"call_to_contact_matches.csv not found at {MATCHES_FILE}. "
                  f"Run leads/match_calls.py to regenerate.",
        )
    try:
        rows = _read(MATCHES_FILE)
        call_log = _load_call_log_lookup()
    except Exception as e:
        return safe_source_payload("phone", {}, error=f"CSV read failed: {e}")

    if not rows:
        return safe_source_payload("phone", {}, error="call_to_contact_matches.csv is empty")

    # IMPORTANT: the match file has 245 rows (one per call). v3.1.1 fix:
    # A call is "matched" if it has EITHER a matched_contact_id (real HubSpot
    # contact) OR a matched_company_id (06-18 no-contact company matched via
    # the inbound phone list). The 06-18 matches have company but no contact
    # — these are companies whose phones were never backfilled into HubSpot.
    matched_rows = [r for r in rows if (r.get("matched_contact_id") or r.get("matched_company_id") or "").strip()]
    unmatched_rows = [r for r in rows if not (r.get("matched_contact_id") or r.get("matched_company_id") or "").strip()]

    # All Steven calls per user (Zoom data shows line owner heber, but
    # user-confirmed all 245 are steven). Track both fields for honesty.
    steven_calls = 0
    line_owners: Counter = Counter()
    for r in rows:
        cid = r.get("call_id", "")
        log_row = call_log.get(cid, {})
        if log_row.get("is_steven", "y") == "y":  # default to y for backward compat
            steven_calls += 1
        if log_row.get("from_email"):
            line_owners[log_row["from_email"]] += 1

    line_owner = line_owners.most_common(1)[0][0] if line_owners else "heber@minyn.link"

    # Connected: count from matched rows only (per-company attribution)
    # We also surface "unmatched_connected" separately for the gap-analysis
    # action item.
    connected = sum(1 for r in matched_rows if r.get("call_result") == "Connected")
    unmatched_connected = sum(1 for r in unmatched_rows if r.get("call_result") == "Connected")
    unmatched_failed = sum(1 for r in unmatched_rows if r.get("call_result") in ("Call Failed", "Canceled"))

    # Aggregate by company (matched rows only — v3.1.1 fix)
    by_company: dict[str, dict] = {}
    for r in matched_rows:
        cid = r.get("matched_company_id", "")
        if not cid:
            continue
        if cid not in by_company:
            by_company[cid] = {
                "company_id":   cid,
                "company_name": r.get("matched_company_name", ""),
                "contact_id":   r.get("matched_contact_id", ""),
                "contact_name": r.get("matched_contact_name", ""),
                "contact_email": r.get("matched_contact_email", ""),
                "call_count": 0,
                "connected_count": 0,
                "first_call": "",
                "last_call":  "",
            }
        e = by_company[cid]
        e["call_count"] += 1
        if r.get("call_result") == "Connected":
            e["connected_count"] += 1
        cd = r.get("call_date", "")
        if cd and (not e["first_call"] or cd < e["first_call"]):
            e["first_call"] = cd
        if cd and cd > e["last_call"]:
            e["last_call"] = cd

    # Sort companies by call_count desc for top-N display
    top_companies = sorted(
        by_company.values(),
        key=lambda c: (-c["call_count"], c["company_name"]),
    )

    # Freshness
    try:
        mtime = datetime.fromtimestamp(MATCHES_FILE.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
    except Exception:
        age_hours = None

    return safe_source_payload(
        "phone",
        {
            # v3.1.1 fix: total_matched = actually matched (147), not total rows (245).
            # We also expose the raw totals + gap so the dashboard can surface the
            # "245 total / 147 matched / 98 unmatched" story honestly.
            "total_matched": len(matched_rows),
            "total_calls":   len(rows),
            "unmatched_calls": len(unmatched_rows),
            "unmatched_connected": unmatched_connected,
            "unmatched_failed":    unmatched_failed,
            "connected_matched": connected,
            "unique_companies": len(by_company),
            "unique_contacts":  len(set(r.get("matched_contact_id", "") for r in matched_rows)),
            "steven_calls": steven_calls,
            "caller_line_owner": line_owner or "heber@minyn.link",
            "note_attribution": (
                f"Out of {len(rows)} total outbound Zoom calls, {len(matched_rows)} ({100*len(matched_rows)//len(rows)}%) "
                f"matched a HubSpot contact. {len(unmatched_rows)} ({100*len(unmatched_rows)//len(rows)}%) did NOT match — "
                f"of those, {unmatched_connected} connected (real conversations with people not in HubSpot), "
                f"{unmatched_failed} failed/canceled. "
                f"Zoom line owner: {line_owner or 'heber@minyn.link'} (ext 800), but the actual dialer was steven. "
                f"Both fields are recorded for honesty."
            ),
            "top_companies": top_companies[:25],
            "all_companies_count": len(top_companies),
            "freshness_hours": round(age_hours, 1) if age_hours is not None else None,
            "result_breakdown": dict(Counter(r.get("call_result", "") for r in rows)),
        },
    )


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), indent=2))
