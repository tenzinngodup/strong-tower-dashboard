"""Compute the dashboard's headline KPIs from the per-source snapshots.

This module takes the dict produced by ingest.py (one entry per source) and
returns a small KPI dict the static page renders. The goal is that the
top-of-page numbers are CALCULATED ONCE, here, and the HTML just reads them —
not "the HTML does math against the source data" (which is how dashboards
become unmaintainable).

Failure isolation: every KPI is computed in a try/except and falls back to
`{"value": None, "note": "..."}` so the page always renders, even if one
source is broken.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.dashboard_lib import now_utc  # noqa: E402


def _safe(fn, default=None):
    """Run fn() and return its result, or `default` if it raises."""
    try:
        return fn()
    except Exception as e:
        return {"value": default, "note": f"compute error: {type(e).__name__}: {e}"}


def compute(snapshot: dict) -> dict:
    """Roll up the per-source snapshot into the 5 dashboard sections.

    `snapshot` shape:
        {
            "fetched_at": <iso>,
            "leads_csv": {...},
            "hubspot":   {...},
            "blotato":   {...},
            "ga4":       {...},
        }
    """
    leads  = snapshot.get("leads") or {}
    lh     = snapshot.get("leads_history") or {}
    hs     = snapshot.get("hubspot") or {}
    bl     = snapshot.get("blotato") or {}
    ga     = snapshot.get("ga4") or {}

    # ── Section 1: Headline KPIs ────────────────────────────────────────
    # 1a. Active pipeline value (USD) — straight from HubSpot.
    pipeline_value = _safe(lambda: (hs.get("open_pipeline_value_usd") or 0))

    # 1b. New SQLs / outreach activity this week — leads_csv New count.
    new_leads = _safe(lambda: (leads.get("totals") or {}).get("active", 0))

    # 1c. Win rate over all-time — won / (won + lost) when both > 0.
    # For now, both are 0; the dashboard will show "0% (0/0)" honestly.
    def _win_rate():
        hs_totals = hs.get("totals") or {}
        won = hs_totals.get("won_count", 0) or 0
        lost = hs_totals.get("lost_count", 0) or 0
        closed = won + lost
        if closed == 0:
            return {"value": None, "closed_won": won, "closed_lost": lost, "note": "no closed deals yet"}
        return {"value": round(100.0 * won / closed, 1), "closed_won": won, "closed_lost": lost}
    win_rate = _safe(_win_rate)

    # 1d. Blended CAC — placeholder until we have a "spend" signal.
    # For now, return None with a clear note. The dashboard renders the note
    # instead of a misleading $0.
    blended_cac = _safe(lambda: None)

    # ── Section 2: Marketing ────────────────────────────────────────────
    # Cadence: did we hit the daily target on each channel?
    def _cadence():
        last7 = bl.get("totals_7d") or {}
        goal  = bl.get("cadence_goal") or {"instagram": 7, "linkedin": 7}
        return {
            "instagram": {
                "posted_7d":    last7.get("instagram", 0),
                "target_7d":    goal.get("instagram", 7),
                "on_pace":      (last7.get("instagram", 0) or 0) >= (goal.get("instagram", 7) or 7),
            },
            "linkedin": {
                "posted_7d":    last7.get("linkedin", 0),
                "target_7d":    goal.get("linkedin", 7),
                "on_pace":      (last7.get("linkedin", 0) or 0) >= (goal.get("linkedin", 7) or 7),
            },
        }
    cadence = _safe(_cadence, default={"instagram": {}, "linkedin": {}})

    # Site traffic: total sessions + per-UTM-source split.
    def _traffic():
        totals = ga.get("totals") or {}
        return {
            "sessions_7d":     totals.get("sessions", 0),
            "pageviews_7d":    totals.get("screenPageViews", 0),
            "by_source_7d":    ga.get("by_source", {}),
            "top_pages_7d":    (ga.get("top_pages") or [])[:5],
        }
    traffic = _safe(_traffic, default={"sessions_7d": 0, "pageviews_7d": 0, "by_source_7d": {}, "top_pages_7d": []})

    # ── Section 3: Sales pipeline ───────────────────────────────────────
    def _funnel():
        funnel = leads.get("funnel") or {}
        # Re-order New → Contacted → Walkthrough → Quoted → Won (already in that order in leads.py)
        return funnel
    funnel = _safe(_funnel, default={})

    # ── Section 3.5: Funnel motion (NEW in v2) ─────────────────────────
    # Pulled from leads_history.py — the SDR's weekly pipeline log.
    # Answers: "is the pipeline moving week-over-week, or is it frozen?"
    def _funnel_motion():
        if not lh.get("ok"):
            return {"available": False, "reason": "leads_history not fetched this run"}
        staleness = lh.get("staleness") or {}
        return {
            "available":        True,
            "totals_current":   lh.get("totals_current") or {},
            "this_week_delta":  lh.get("this_week_delta") or {},
            "trend":            lh.get("trend_6w") or [],
            "frozen":           staleness.get("frozen_pipeline", False),
            "days_since_last":  staleness.get("days_since_last"),
            "weeks_since_outreach": staleness.get("weeks_since_outreach"),
        }
    funnel_motion = _safe(_funnel_motion, default={"available": False})

    # ── Section 4: Customer / operations ────────────────────────────────
    # "Active accounts" + MRR come from HubSpot deals. We don't have that
    # field today, so return a "not available" stub that the dashboard
    # renders as a placeholder card.
    def _customer():
        if not hs.get("ok"):
            return {"available": False, "reason": "HubSpot data not fetched this run"}
        won = (hs.get("totals") or {}).get("won_count", 0) or 0
        return {
            "available":      won > 0,  # only meaningful when there are customers
            "won_count":      won,
            "won_value_usd":  (hs.get("totals") or {}).get("won_value_usd", 0),
            "lost_count":     (hs.get("totals") or {}).get("lost_count", 0),
            "active_pipeline": (hs.get("totals") or {}).get("open_deals", 0),
            "note":           None if won > 0 else "no closed-won deals yet",
        }
    customer = _safe(_customer, default={"available": False, "reason": "compute error"})

    # ── Section 5: Action items (auto-generated) ────────────────────────
    def _action_items():
        items: list[dict] = []

        # Data quality: icp drift rows indicate CSV is dirty.
        dq = (leads.get("data_quality") or {})
        if dq.get("icp_drift_rows", 0) > 0:
            items.append({
                "severity": "medium",
                "title":    f"{dq['icp_drift_rows']} leads have non-standard icp values",
                "detail":   "Notes, scores, or dates leaked into the `icp` column. Cleanup the CSV.",
                "source":   "leads_csv",
            })

        # Data quality: lead CSVs themselves are stale.
        oldest = dq.get("oldest_csv_days", 0) or 0
        if oldest > 14:
            items.append({
                "severity": "high" if oldest > 30 else "medium",
                "title":    f"Lead CSVs are {oldest} days old",
                "detail":   f"active.csv hasn't been updated in {oldest} days. The funnel numbers may be misleading.",
                "source":   "leads_csv",
            })

        # Funnel motion: pipeline has been frozen for multiple weeks.
        fm = funnel_motion if isinstance(funnel_motion, dict) else {}
        if fm.get("available") and fm.get("frozen"):
            items.append({
                "severity": "high",
                "title":    "Pipeline counts have not changed in 3+ weeks",
                "detail":   f"active={fm.get('totals_current', {}).get('active', '?')}, "
                            f"contacted={fm.get('totals_current', {}).get('contacted', '?')}, "
                            f"won={fm.get('totals_current', {}).get('won', '?')}, "
                            f"lost={fm.get('totals_current', {}).get('lost', '?')} — same for 3+ weeks. "
                            "Either no outreach happened, or the data isn't being recorded.",
                "source":   "leads_history",
            })

        # Outreach: SDR hasn't sent emails in N weeks.
        weeks_since = fm.get("weeks_since_outreach")
        if isinstance(weeks_since, int) and weeks_since >= 2:
            items.append({
                "severity": "high" if weeks_since >= 4 else "medium",
                "title":    f"SDR has not sent outreach in {weeks_since} weeks",
                "detail":   "leads_history.csv shows 0 emails sent for the last "
                            f"{weeks_since} weekly reports.",
                "source":   "leads_history",
            })

        # Pipeline: stuck deals — if any active deal is old (we don't have
        # createdate in our HubSpot pull yet, so this is a stub for now).
        # Will be filled in once we add `createdate` to DEAL_PROPERTIES.

        # Cadence: any channel behind pace?
        for ch, status in (cadence or {}).items():
            if isinstance(status, dict) and not status.get("on_pace", True):
                items.append({
                    "severity": "low",
                    "title":    f"{ch.title()} below cadence",
                    "detail":   f"{status.get('posted_7d', 0)}/{status.get('target_7d', 7)} posts in the last 7 days",
                    "source":   "blotato",
                })

        # Source failures.
        for source_name, source in snapshot.items():
            if isinstance(source, dict) and source.get("ok") is False:
                items.append({
                    "severity": "high",
                    "title":    f"{source_name} fetch failed",
                    "detail":   source.get("error", "unknown error"),
                    "source":   source_name,
                })

        return items
    actions = _safe(_action_items, default=[])

    return {
        "computed_at": now_utc(),
        "headlines": {
            "pipeline_value_usd": pipeline_value,
            "new_leads":          new_leads,
            "win_rate":           win_rate,
            "blended_cac":        blended_cac,
        },
        "marketing": {
            "cadence":   cadence,
            "traffic":   traffic,
            "latest_post": bl.get("latest_post") or {},
        },
        "sales": {
            "funnel":    funnel,
        },
        "funnel_motion": funnel_motion,   # NEW in v2
        "customer":  customer,
        "actions":   actions,
    }


if __name__ == "__main__":
    # Standalone test: read snapshot.json from disk and print KPIs.
    snap_path = Path(__file__).resolve().parents[2] / "data" / "snapshot.json"
    if not snap_path.exists():
        print(json.dumps({"error": f"missing {snap_path} — run ingest.py first"}))
        sys.exit(1)
    snap = json.loads(snap_path.read_text())
    print(json.dumps(compute(snap), indent=2))
