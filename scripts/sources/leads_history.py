"""Read the SDR's weekly pipeline-motion log and compute funnel velocity.

Source: /opt/data/profiles/strong-tower/workspace/leads/email_status.csv

This file is a weekly snapshot the SDR already maintains — it records, for
each week, the cumulative counts (active / contacted / won / lost), the
number of outreach emails sent, and HubSpot new-contact counts. It IS the
real pipeline trend; the leads/active.csv and leads/contacted.csv files
only have the latest snapshot and no per-row dates.

What the dashboard surfaces from this file:
    - weekly deltas (new active, new contacted, won this week, lost this week)
    - 4-6 week trend lines (so the owner can see if the pipeline is moving)
    - sent emails per week (the SDR's actual outreach activity)
    - staleness flag (if the most recent entry is >7 days old, the dashboard
      raises a high-severity action item)
    - "frozen pipeline" flag (if active/contacted/won/lost have not changed
      for >= 3 weeks, the dashboard surfaces it)

Failure isolation: file might be missing or have a new schema. Each case
returns ok=False with a clear error; the dashboard still renders.

This source is local-only and very fast (<100ms). It cannot fail in a way
that should block the dashboard, but the staleness check is genuinely
useful and worth surfacing even when ok=True.
"""
from __future__ import annotations
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import safe_source_payload  # noqa: E402

LEADS_DIR = Path("/opt/data/profiles/strong-tower/workspace/leads")
HISTORY_FILE = LEADS_DIR / "email_status.csv"

# Numeric columns we care about. Anything else is metadata.
NUMERIC_COLS = ["sent", "unique_recipients", "unique_domains",
                "hubspot_new", "active", "contacted", "won", "lost"]


def _read_history(path: Path) -> list[dict]:
    """Read the email_status.csv and return one row per `date` (the latest
    row wins). The SDR's pipeline writes multiple rows per date across
    different re-runs and period windows — we only want the most recent
    value for the dashboard's trend.

    Schema assumption: rows are appended chronologically, so the last row
    with a given `date` is the freshest. We keep it simple: deduplicate
    by date, last-wins (DictReader preserves file order, so the row that
    appears latest in the file overwrites earlier ones in our dict).
    """
    if not path.exists():
        return []
    raw = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    by_date: dict[str, dict] = {}
    for r in raw:
        d = r.get("date", "").strip()
        if not d:
            continue
        by_date[d] = r  # last-wins
    out: list[dict] = []
    for d, r in sorted(by_date.items()):
        row: dict = {"date": d}
        for c in NUMERIC_COLS:
            try:
                row[c] = int(r.get(c) or 0)
            except (TypeError, ValueError):
                row[c] = 0
        out.append(row)
    return out


def _delta_weeks(weeks: list[dict], col: str) -> list[int]:
    """Per-week new (positive) deltas of `col`. For 'sent' / 'hubspot_new' this
    is just the weekly value. For cumulative columns (active/contacted/won/lost)
    it's the change from the prior week. Returns one int per week, aligned
    with `weeks` (first week delta = 0 or the value itself for cumulative).
    """
    out: list[int] = []
    prev = None
    for w in weeks:
        cur = w.get(col, 0)
        if prev is None or col in ("sent", "unique_recipients",
                                   "unique_domains", "hubspot_new"):
            # These are per-week values, not cumulative — emit as-is
            out.append(cur)
        else:
            out.append(max(0, cur - prev))
        prev = cur
    return out


def collect() -> dict:
    rows = _read_history(HISTORY_FILE)
    if not rows:
        return safe_source_payload(
            "leads_history", {},
            error=f"{HISTORY_FILE} missing or empty — pipeline motion unknown",
        )

    latest = rows[-1]
    prior  = rows[-2] if len(rows) >= 2 else None

    # Staleness: how many days since the most recent entry?
    try:
        last_dt = datetime.fromisoformat(latest["date"]).replace(tzinfo=timezone.utc)
        now_dt  = datetime.now(timezone.utc)
        days_since_last = (now_dt - last_dt).days
    except (TypeError, ValueError):
        days_since_last = None
        last_dt = None

    is_stale = days_since_last is not None and days_since_last > 7

    # Frozen-pipeline detection: if the last 3+ weeks have identical
    # cumulative counts, the pipeline isn't moving. This is a high-signal
    # finding the owner will want to act on.
    frozen = False
    if len(rows) >= 4:
        last3 = rows[-3:]
        if all(r["active"]   == last3[0]["active"]   and
               r["contacted"]== last3[0]["contacted"] and
               r["won"]      == last3[0]["won"]      and
               r["lost"]     == last3[0]["lost"]
               for r in last3):
            frozen = True

    # This-week vs prior-week deltas (cumulative columns only)
    def _cumul_delta(col: str) -> int | None:
        if prior is None:
            return None
        return max(0, latest.get(col, 0) - prior.get(col, 0))

    # Trend: send the last 6 weeks (or fewer if we don't have them)
    trend = []
    for w in rows[-6:]:
        trend.append({
            "date":        w["date"],
            "active":      w["active"],
            "contacted":   w["contacted"],
            "won":         w["won"],
            "lost":        w["lost"],
            "sent":        w["sent"],
            "hubspot_new": w["hubspot_new"],
        })

    # Lead source activity: when was the most recent outreach (>0 sent)?
    last_outreach_idx = None
    for i, w in enumerate(rows):
        if w.get("sent", 0) > 0:
            last_outreach_idx = i
    weeks_since_outreach = (len(rows) - 1 - last_outreach_idx) if last_outreach_idx is not None else None

    # Data quality
    quality = {
        "rows_total":    len(rows),
        "first_date":    rows[0]["date"],
        "last_date":     latest["date"],
        "days_since_last": days_since_last,
        "is_stale":      is_stale,
        "frozen_pipeline": frozen,
        "weeks_since_outreach": weeks_since_outreach,
    }

    return safe_source_payload("leads_history", {
        "totals_current": {
            "active":    latest["active"],
            "contacted": latest["contacted"],
            "won":       latest["won"],
            "lost":      latest["lost"],
        },
        "this_week_delta": {
            "new_active":    _cumul_delta("active"),
            "new_contacted": _cumul_delta("contacted"),
            "new_won":       _cumul_delta("won"),
            "new_lost":      _cumul_delta("lost"),
            "sent":          latest.get("sent", 0),
            "hubspot_new":   latest.get("hubspot_new", 0),
        },
        "trend_6w":    trend,
        "staleness":   quality,
        "pipeline_status": "PAUSED — Legacy May 2026 Apollo outreach (gyms/dental). The current B2B pipeline is 244 HubSpot companies, see 'pipeline' source. This file's frozen-pipeline / stale-CSV alerts refer to the LEGACY funnel, not current work.",
        "source_label": "Legacy May 2026 outreach (paused)",
    })


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
