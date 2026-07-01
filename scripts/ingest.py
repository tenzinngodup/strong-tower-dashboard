#!/usr/bin/env python3
"""Strong Tower weekly dashboard ingest.

Runs every source in sequence, writes two JSON files:
    data/snapshot.json   — raw inputs (one entry per source, with ok/error)
    data/kpis.json       — computed rollups (what the dashboard renders)

Each source runs in its own try/except so a single broken source cannot
block the rest of the pipeline. Sources that require secrets (Composio,
Blotato, Cloudflare) read them from /opt/data/profiles/strong-tower/.env
via lib.dashboard_lib.

Usage:
    python3 scripts/ingest.py              # run all sources, write both files
    python3 scripts/ingest.py --dry-run    # run + print, don't write
    python3 scripts/ingest.py --only leads_csv   # run one source (for testing)

Exit code: 0 if all sources succeeded, 1 if any source failed.
"""
from __future__ import annotations
import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project layout:
#   strong-tower-dashboard/
#   ├── scripts/
#   │   ├── ingest.py            (this file)
#   │   ├── sources/*.py         (each exports collect() -> dict)
#   │   ├── compute/kpis.py
#   │   └── lib/dashboard_lib.py
#   ├── data/
#   │   ├── snapshot.json        (raw inputs)
#   │   ├── kpis.json            (computed rollups)
#   │   └── SCHEMA.md            (documentation)
#   └── public/                  (static site, Phase 2+)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR  = PROJECT_ROOT / "scripts" / "sources"
COMPUTE_DIR  = PROJECT_ROOT / "scripts" / "compute"
DATA_DIR     = PROJECT_ROOT / "data"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SOURCES = [
    "leads",  # file: scripts/sources/leads.py
    "hubspot",
    "blotato",
    "ga4",
]


def _import_source(name: str):
    """Import a source module by its short name (file is `name.py` in sources/)."""
    return importlib.import_module(f"sources.{name}")


def run(only: list[str] | None = None, dry_run: bool = False) -> dict:
    """Run all (or a subset of) sources and return the combined snapshot dict."""
    snapshot: dict = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources_run": [],
    }
    for name in SOURCES:
        if only and name not in only:
            continue
        snapshot["sources_run"].append(name)
        try:
            mod = _import_source(name)
            result = mod.collect()
        except Exception as e:
            result = {
                "source":     name,
                "ok":         False,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "error":      f"{type(e).__name__}: {e}",
            }
        snapshot[name] = result
    return snapshot


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="print, don't write files")
    p.add_argument("--only",    nargs="+",          help="only run these sources (space-sep)")
    p.add_argument("--print",   choices=["snapshot", "kpis", "both"], default="both")
    args = p.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = run(only=args.only)

    if args.only:
        # Single-source mode: just print, don't compute kpis (they need all sources).
        print(json.dumps(snapshot, indent=2))
        return 0 if all(snapshot.get(n, {}).get("ok") for n in args.only) else 1

    # Compute KPIs from the snapshot. Keep this import inside main() so
    # --only mode doesn't fail when only one source ran.
    from compute.kpis import compute as compute_kpis
    kpis = compute_kpis(snapshot)

    if not args.dry_run:
        (DATA_DIR / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
        (DATA_DIR / "kpis.json").write_text(json.dumps(kpis, indent=2))

        # Also copy kpis.json into public/ so the static site can fetch it
        # from the same origin. (CF Pages serves the public/ directory.)
        public_kpis = PROJECT_ROOT / "public" / "kpis.json"
        public_kpis.write_text(json.dumps(kpis, indent=2))

    if args.print in ("snapshot", "both"):
        print("=" * 60)
        print("SNAPSHOT (raw inputs)")
        print("=" * 60)
        print(json.dumps(snapshot, indent=2))
    if args.print in ("kpis", "both"):
        print()
        print("=" * 60)
        print("KPIS (computed rollups)")
        print("=" * 60)
        print(json.dumps(kpis, indent=2))

    # Summary line for cron logs.
    ok_count   = sum(1 for n in snapshot["sources_run"] if snapshot.get(n, {}).get("ok"))
    fail_count = len(snapshot["sources_run"]) - ok_count
    print()
    print(f"--- summary: {ok_count} ok, {fail_count} failed (of {len(snapshot['sources_run'])} sources) ---")
    for n in snapshot["sources_run"]:
        status = "OK " if snapshot.get(n, {}).get("ok") else "FAIL"
        err    = snapshot.get(n, {}).get("error", "")
        print(f"  [{status}] {n}{(' — ' + err) if err else ''}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
