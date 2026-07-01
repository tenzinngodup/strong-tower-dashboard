"""Helpers shared by all dashboard source scripts.

The dashboard's `ingest.py` runs each source in sequence. Each source is
expected to be a Python module in `scripts/sources/` with a `collect()`
function that returns a dict matching this shape:

    {
        "source": "<short_name>",   # e.g. "hubspot", "blotato", "ga4", "leads_csv"
        "ok": True|False,
        "fetched_at": "<iso8601 utc>",
        "error": "<msg>",           # only if ok is False
        ...source-specific fields...
    }

Failure isolation: each source's `collect()` is wrapped in try/except inside
ingest.py, so a single broken source doesn't kill the whole pipeline. Sources
that talk to the network MUST catch their own timeouts and return `ok: False`
with a clear error message — they must NOT raise.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path

# Strong Tower profile secrets live in this file. The dashboard scripts only
# read what they need; they never write back, and they never log the values.
PROFILE_ENV = Path("/opt/data/profiles/strong-tower/.env")

# Project layout (resolved at import time so source scripts can rely on these).
DASHBOARD_ROOT = Path("/opt/data/profiles/strong-tower/workspace/strong-tower-dashboard")
DATA_DIR       = DASHBOARD_ROOT / "data"
SOURCES_DIR    = DASHBOARD_ROOT / "scripts" / "sources"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env_value(key: str, env_path: Path = PROFILE_ENV) -> str | None:
    """Pull a single key out of the profile .env without printing it.

    Supports `KEY=val` and `KEY='val'` (the form used by composio skill).
    Returns None if the key isn't set.
    """
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            v = v.strip()
            # Strip surrounding single or double quotes.
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            return v
    return None


def safe_source_payload(source: str, payload: dict, error: str | None = None) -> dict:
    """Standardize the shape of a source's return value."""
    out = {
        "source":     source,
        "ok":         error is None,
        "fetched_at": now_utc(),
    }
    if error is not None:
        out["error"] = error
    out.update(payload)
    return out
