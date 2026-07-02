"""Read the unified HubSpot pipeline and compute funnel counts + weekly motion.

Source of truth: /opt/data/profiles/strong-tower/workspace/leads/pipeline_master.csv
    Built by scripts/build_pipeline_status.py from:
      - 4 lead-intake contact batches (master, 06-12, 06-13, 06-17)
      - 1 lead-intake companies-only batch (06-18, 123 companies)
      - steven's outreach queue (lead_gen_drafts_log.csv)

This is THE pipeline. The leads/active.csv and leads/contacted.csv files only
contain the legacy May 2026 Apollo outreach (gyms/dental — paused since 5/5).
The pipeline_master.csv contains the current June 2026 B2B HubSpot universe
(244 companies: property managers, GCs, title, senior living).

What the dashboard surfaces from this source:
    - per-stage counts (noted, drafted_not_sent, contacted, active, lost, won)
    - weekly additions (5 batches, mapped to week-of-Monday)
    - draft queue (60 steven, 4 miguel — 0 sent so far)
    - 4-week additions sparkline
    - 179 "ready to draft" backlog (high-severity action item)
    - 64 drafts "ready to send" (high-severity action item)
    - 0 emails actually sent (vs 73 sent in legacy outreach — see gmail.py)

Failure isolation: pipeline_master.csv might be missing (run build_pipeline_status.py).
Each case returns ok=False with a clear error; the dashboard still renders.
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

WORKSPACE = Path("/opt/data/profiles/strong-tower/workspace")
PIPELINE_FILE = WORKSPACE / "leads" / "pipeline_master.csv"

# Batch date mapping. The lead-intake scripts record the upload date in the
# directory name; the master batch came from apollo-portland-master-2026-05-13.tsv.
# If the user adds a new batch, update this map.
BATCH_DATES = {
    "master": "2026-05-13",
    "06-12": "2026-06-12",
    "06-13": "2026-06-13",
    "06-17": "2026-06-17",
    "06-18": "2026-06-18",
}


def _week_of_monday(date_str: str) -> str:
    """Return ISO date of the Monday for the week containing date_str."""
    d = datetime.fromisoformat(date_str).date()
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def _read_pipeline(path: Path) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def collect() -> dict:
    if not PIPELINE_FILE.exists():
        return safe_source_payload(
            "pipeline",
            {},
            error=f"pipeline_master.csv not found at {PIPELINE_FILE}. "
                  f"Run: python3 scripts/build_pipeline_status.py",
        )

    try:
        rows = _read_pipeline(PIPELINE_FILE)
    except Exception as e:
        return safe_source_payload("pipeline", {}, error=f"CSV read failed: {e}")

    # Per-stage counts
    stages = Counter(r["inferred_stage"] for r in rows)
    total = len(rows)

    # Per-person outreach counts (v3.1: who did what)
    by_person = {
        "steven": {
            "emailed":    sum(1 for r in rows if r.get("emailed_by_steven") == "y"),
            "drafted":    sum(1 for r in rows if r.get("drafted_by_steven") == "y"),
            "called":     sum(1 for r in rows if r.get("called_by_steven") == "y"),
            "total_touched": sum(1 for r in rows
                                 if r.get("emailed_by_steven") == "y"
                                 or r.get("drafted_by_steven") == "y"
                                 or r.get("called_by_steven") == "y"),
        },
        "heber": {
            "emailed":    sum(1 for r in rows if r.get("emailed_by_heber") == "y"),
            "drafted":    sum(1 for r in rows if r.get("drafted_by_heber") == "y"),
            "total_touched": sum(1 for r in rows
                                if r.get("emailed_by_heber") == "y"
                                or r.get("drafted_by_heber") == "y"),
        },
    }

    # Per-batch counts (for the weekly sparkline)
    batches = Counter(r["source_batch"] for r in rows)

    # Weekly additions: roll up batches by their upload week
    weekly = defaultdict(int)
    for batch_key, n in batches.items():
        d = BATCH_DATES.get(batch_key)
        if d:
            weekly[_week_of_monday(d)] += n
        else:
            # Unknown batch — log it but don't crash
            weekly[f"unknown_{batch_key}"] += n

    # Sort weekly, fill in 0s for empty weeks (last 6 weeks from today)
    today = datetime.now(timezone.utc).date()
    weeks = []
    for i in range(5, -1, -1):
        monday = today - timedelta(days=today.weekday() + 7 * i)
        iso = monday.isoformat()
        weeks.append({"week": iso, "added": weekly.get(iso, 0)})

    # Draft queue breakdown
    draft_sender = Counter()
    for r in rows:
        if r["drafted"] == "y":
            draft_sender[r["draft_sender"] or "unknown"] += 1

    # Top draft subjects (most recent 5) — show what steven is actually writing about
    drafted_rows = [r for r in rows if r["drafted"] == "y"]
    sample_drafts = []
    for r in drafted_rows[:5]:
        sample_drafts.append({
            "company": r["company"],
            "subject": r["draft_subject"],
            "sender": r["draft_sender"],
        })

    # Companies that have a contact (121) vs just a note (244-121=123 in 06-18)
    with_contact = sum(1 for r in rows if r["hubspot_has_contact"] == "y")
    with_note = sum(1 for r in rows if r["hubspot_has_note"] == "y")
    unworked = sum(1 for r in rows if r["hubspot_has_note"] != "y" and r["hubspot_has_contact"] != "y")

    # Ready to draft = noted but not drafted
    ready_to_draft = sum(1 for r in rows
                        if r["inferred_stage"] == "noted"
                        and r["hubspot_has_contact"] == "y")
    # "Ready to draft" should be noted AND has contact. If no contact, SDR has
    # to research the contact first. Surface this distinction.

    # Pipeline freshness — when was the file last regenerated?
    try:
        mtime = datetime.fromtimestamp(PIPELINE_FILE.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        freshness_human = _humanize_age(age_hours)
    except Exception:
        age_hours = None
        freshness_human = "unknown"

    return safe_source_payload(
        "pipeline",
        {
            "total": total,
            "stages": dict(stages),
            "by_person": by_person,
            "with_contact": with_contact,
            "with_note": with_note,
            "unworked": unworked,
            "ready_to_draft": ready_to_draft,
            "drafts_waiting": sum(draft_sender.values()),
            "drafts_by_sender": dict(draft_sender),
            "weekly_additions": weeks,
            "batches": dict(batches),
            "sample_drafts": sample_drafts,
            "file_age_hours": round(age_hours, 1) if age_hours is not None else None,
            "freshness": freshness_human,
            "batch_dates": BATCH_DATES,
            "note": "HubSpot B2B pipeline (244 cos). Legacy May outreach in leads/active.csv is paused — see leads source.",
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
