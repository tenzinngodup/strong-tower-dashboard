"""Parse Strong Tower's local lead CSVs.

Source files (read-only):
    /opt/data/profiles/strong-tower/workspace/leads/active.csv
    /opt/data/profiles/strong-tower/workspace/leads/contacted.csv
    /opt/data/profiles/strong-tower/workspace/leads/won.csv
    /opt/data/profiles/strong-tower/workspace/leads/lost.csv

Each file is a stage in the funnel. Sum of file sizes = total reachable leads.

This source is local-only (no network) and always returns ok=True, even if a
file is missing (it just contributes 0 to the funnel). It cannot fail in a way
that should block the dashboard — but it CAN return wrong numbers if the CSV
schema drifts. See the data-quality section in collect() for drift detection.
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

# Make the parent package importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import safe_source_payload  # noqa: E402

LEADS_DIR = Path("/opt/data/profiles/strong-tower/workspace/leads")

# Display order for the funnel chart (Won sits at the end, Lost is reported separately).
FUNNEL_ORDER = ["New", "Contacted", "Walkthrough", "Quoted", "Won"]


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _count_by(leads: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in leads:
        v = (r.get(key) or "").strip()
        if v:
            out[v] = out.get(v, 0) + 1
    return out


def collect() -> dict:
    active    = _read_csv(LEADS_DIR / "active.csv")
    contacted = _read_csv(LEADS_DIR / "contacted.csv")
    won       = _read_csv(LEADS_DIR / "won.csv")
    lost      = _read_csv(LEADS_DIR / "lost.csv")

    # CSV staleness: the lead files are updated manually by the SDR. If they
    # haven't been touched in >14 days, the funnel numbers on the dashboard
    # are showing a stale snapshot. This is a useful signal — the dashboard
    # surfaces it as a high-severity action item.
    from datetime import datetime, timezone
    csv_staleness: dict[str, int] = {}
    for name, rows in (("active", active), ("contacted", contacted),
                       ("won", won), ("lost", lost)):
        path = LEADS_DIR / f"{name}.csv"
        if not path.exists() or not rows:
            csv_staleness[name] = -1  # missing
            continue
        mtime = path.stat().st_mtime
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        csv_staleness[name] = (datetime.now(timezone.utc) - dt).days
    oldest_csv_days = max(d for d in csv_staleness.values() if d >= 0) if any(d >= 0 for d in csv_staleness.values()) else -1
    csvs_stale = oldest_csv_days > 14

    total_reachable = len(active) + len(contacted) + len(won) + len(lost)

    funnel = {label: 0 for label in FUNNEL_ORDER}
    funnel["New"]       = len(active)
    funnel["Contacted"] = len(contacted)
    funnel["Won"]       = len(won)

    by_icp = _count_by(active + contacted, "icp")

    reachable = active + contacted
    with_phone = sum(1 for r in reachable if (r.get("phone") or "").strip())
    with_email = sum(1 for r in reachable if (r.get("email") or "").strip())

    # Data quality: the `icp` column is supposed to hold vertical codes
    # (gym, dental, school, etc.). When notes or dates leak into that column
    # (e.g. "8" from a score, "2026-05-14" from a date), the breakdown is
    # misleading. Flag the rows that look suspicious.
    known_icps = {
        "gym", "dental", "property", "medical", "spa", "fitness",
        "hospitality", "office", "retail", "restaurant", "school",
        "senior", "postcon", "auto", "vet", "coworking", "medspa",
        "property_management", "vct", "gym_fitness",
    }
    drift_rows = [
        {"file": "active.csv",   "icp_value": r.get("icp", "") or "", "business": r.get("business_name", "") or ""}
        for r in active + contacted
        if (r.get("icp") or "").lower() not in known_icps and (r.get("icp") or "")
    ]
    drift_count = len(drift_rows)

    return safe_source_payload("leads_csv", {
        "totals": {
            "reachable": total_reachable,
            "active":    len(active),
            "contacted": len(contacted),
            "won":       len(won),
            "lost":      len(lost),
        },
        "funnel":         funnel,
        "lost_count":     len(lost),
        "by_icp":         by_icp,
        "contactability": {
            "phone_pct":  round(100.0 * with_phone / len(reachable), 1) if reachable else 0.0,
            "email_pct":  round(100.0 * with_email / len(reachable), 1) if reachable else 0.0,
            "with_phone": with_phone,
            "with_email": with_email,
            "total":      len(reachable),
        },
        "data_quality": {
            "icp_drift_rows":  drift_count,
            "icp_drift_sample": drift_rows[:5],  # first 5 for the dashboard "details" view
            "csv_staleness_days":  csv_staleness,
            "oldest_csv_days":     oldest_csv_days,
            "csvs_stale":          csvs_stale,
        },
    })


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
