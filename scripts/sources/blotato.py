"""Strong Tower social posting cadence via Blotato REST.

What this source CAN tell the dashboard:
    - posts published in the last N days, broken down by platform
    - posting cadence (did we hit the daily IG / daily LinkedIn goal?)
    - most recent post URL per platform (for the "latest content" card)

What this source CANNOT tell the dashboard:
    - follower counts
    - likes, comments, impressions
    - reach / engagement rate

Why: Blotato is a publishing tool, not an analytics tool. The /v2/posts/{id}/analytics
endpoint exists but returns metrics=null (verified 2026-07-01). For real engagement
data the dashboard would need to call the Instagram Graph API and LinkedIn Pages API
directly, which requires separate OAuth flows and is a much bigger build.

For now, "are we posting daily?" is the signal Strong Tower's growth team controls.
Engagement is a Phase 2 concern (or comes from GA4 via UTM attribution).
"""
from __future__ import annotations
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import load_env_value, safe_source_payload  # noqa: E402

BLOTATO_BASE = "https://backend.blotato.com/v2"


def _get(path: str, api_key: str, query: dict | None = None) -> dict:
    url = BLOTATO_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"blotato-api-key": api_key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _parse_post_time(s: str) -> datetime:
    # Blotato returns ISO 8601 with 'Z' suffix. Normalize to UTC.
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def collect() -> dict:
    api_key = load_env_value("BLOTATO_API_KEY")
    if not api_key:
        return safe_source_payload("blotato", {}, error="BLOTATO_API_KEY not in .env")

    try:
        # Pull the last 30 days of posts. The /v2/posts endpoint supports `since`
        # as an ISO timestamp and paginates with `cursor` if more than `limit`.
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        items: list[dict] = []
        cursor = None
        for _ in range(5):  # safety bound: 5 pages × 100 = 500 posts
            q = {"since": since, "limit": 100}
            if cursor:
                q["cursor"] = cursor
            data = _get("/posts", api_key, q)
            items.extend(data.get("items", []) or [])
            cursor = data.get("nextCursor") or data.get("cursor")
            if not cursor:
                break

        # Split by platform. Strong Tower runs two: instagram + linkedin.
        by_platform: dict[str, list[dict]] = {"instagram": [], "linkedin": []}
        for p in items:
            pf = (p.get("platform") or "").lower()
            if pf in by_platform:
                by_platform[pf].append(p)

        # Cadence over the last 7 days (matches the biweekly report's window).
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        last7: dict[str, int] = {"instagram": 0, "linkedin": 0}
        for pf, posts in by_platform.items():
            for p in posts:
                try:
                    if _parse_post_time(p.get("postTime", "")) >= week_ago:
                        last7[pf] += 1
                except (TypeError, ValueError):
                    continue

        # Most recent published post per platform.
        latest: dict[str, dict] = {}
        for pf, posts in by_platform.items():
            published = [p for p in posts if (p.get("state") or {}).get("type") == "published"]
            if not published:
                continue
            published.sort(key=lambda p: p.get("postTime", ""), reverse=True)
            top = published[0]
            latest[pf] = {
                "id":     top.get("id"),
                "time":   top.get("postTime"),
                "url":    (top.get("state") or {}).get("postUrl"),
                "excerpt": (top.get("text") or "")[:140],
            }

        return safe_source_payload("blotato", {
            "window_days":    30,
            "totals_30d":     {pf: len(ps) for pf, ps in by_platform.items()},
            "totals_7d":      last7,
            "latest_post":    latest,
            "cadence_goal":   {"instagram": 7, "linkedin": 7},  # 1/day target over 7 days
        })
    except Exception as e:
        return safe_source_payload("blotato", {}, error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
