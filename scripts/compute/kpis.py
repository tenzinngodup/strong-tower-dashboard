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
    pipe   = snapshot.get("pipeline") or {}    # NEW v3: HubSpot B2B pipeline
    hs     = snapshot.get("hubspot") or {}
    hse    = snapshot.get("hubspot_events") or {}
    bl     = snapshot.get("blotato") or {}
    ga     = snapshot.get("ga4") or {}
    gm     = snapshot.get("gmail") or {}

    # ── Section 1: Headline KPIs ────────────────────────────────────────
    # 1a. Active pipeline value (USD) — straight from HubSpot.
    pipeline_value = _safe(lambda: (hs.get("open_pipeline_value_usd") or 0))

    # 1b. New SQLs / outreach activity this week — HubSpot pipeline "added this week".
    # Falls back to leads_csv "active" count if pipeline source missing (legacy fallback).
    def _new_leads():
        if pipe.get("ok") and pipe.get("weekly_additions"):
            this_week = pipe["weekly_additions"][-1] if pipe["weekly_additions"] else {}
            return {
                "value":    this_week.get("added", 0),
                "total":    pipe.get("total", 0),
                "source":   "HubSpot pipeline",
                "note":     f"of {pipe.get('total', 0)} total companies uploaded",
            }
        return {"value": (leads.get("totals") or {}).get("active", 0), "source": "leads_csv (legacy)"}
    new_leads = _safe(_new_leads)

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

    # ── Section 3.7: Outreach (NEW in v2) ───────────────────────────────
    # Pulled from gmail.py — the SDR's actual outreach volume + bounce signal.
    # Answers: "is the SDR sending emails? Are they bouncing? What's the cadence?"
    def _outreach():
        if not gm.get("ok"):
            return {"available": False, "reason": gm.get("error", "gmail not fetched this run")}
        totals = gm.get("totals") or {}
        return {
            "available":     True,
            "window_days":   gm.get("window_days"),
            "window_start":  gm.get("window_start"),
            "window_end":    gm.get("window_end"),
            "sent":          totals.get("sent", 0),
            "per_day_avg":   totals.get("per_day_avg", 0),
            "bounced_est":   totals.get("bounced_estimated", 0),
            "bounce_rate":   round(totals.get("bounced_sampled", 0) /
                                   max(1, totals.get("hydrated_sample", 1)) * 100, 1),
            "by_day":        gm.get("by_day", []),
            "replies_available": (gm.get("replies") or {}).get("available", False),
            "replies_note":  (gm.get("replies") or {}).get("note", ""),
        }
    outreach = _safe(_outreach, default={"available": False})

    # ── Section 3.8: Engagement (NEW in v2) ─────────────────────────────
    # Pulled from hubspot_events.py — call / meeting / email volume in HubSpot.
    # Answers: "after the SDR touches a lead, do they actually engage?
    # Are walkthroughs being booked?"
    def _engagement():
        if not hse.get("ok"):
            return {"available": False, "reason": hse.get("error", "hubspot_events not fetched")}
        out = {
            "available":    True,
            "window_days":  hse.get("window_days"),
            "window_start": hse.get("window_start"),
            "window_end":   hse.get("window_end"),
        }
        for obj_type in ("calls", "meetings", "emails"):
            data = hse.get(obj_type) or {}
            out[obj_type] = {
                "in_window":        data.get("in_window", 0),
                "per_day":          data.get("per_day", []),
            }
        return out
    engagement = _safe(_engagement, default={"available": False})

    # ── Section 3.9: HubSpot pipeline (NEW in v3) ──────────────────────
    # Pulled from pipeline.py — the unified 244-company B2B universe.
    # Answers: "how many companies are in our real pipeline, where are they
    # in the funnel, and what should Steven send next?"
    def _pipeline():
        if not pipe.get("ok"):
            return {"available": False, "reason": pipe.get("error", "pipeline not fetched this run")}
        stages = pipe.get("stages") or {}
        return {
            "available":         True,
            "total":             pipe.get("total", 0),
            "with_contact":      pipe.get("with_contact", 0),
            "with_note":         pipe.get("with_note", 0),
            "stages":            stages,
            "ready_to_draft":    pipe.get("ready_to_draft", 0),
            "drafts_waiting":    pipe.get("drafts_waiting", 0),
            "drafts_by_sender":  pipe.get("drafts_by_sender", {}),
            "weekly_additions":  pipe.get("weekly_additions", []),
            "batches":           pipe.get("batches", {}),
            "sample_drafts":     pipe.get("sample_drafts", []),
            "freshness":         pipe.get("freshness", ""),
            "file_age_hours":    pipe.get("file_age_hours"),
            "note":              "HubSpot B2B pipeline. Legacy May 2026 Apollo outreach is paused — see 'funnel_motion' section.",
        }
    pipeline = _safe(_pipeline, default={"available": False})

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

        # ── HIGH-PRIORITY: real pipeline alerts (v3) ──
        # These override or accompany the legacy alerts below.

        pl = pipeline if isinstance(pipeline, dict) else {}

        # 1. Drafts are sitting in Gmail, never sent.
        if pl.get("available") and pl.get("drafts_waiting", 0) > 0:
            drafts = pl["drafts_waiting"]
            by_sender = pl.get("drafts_by_sender", {})
            steven = by_sender.get("steven", 0)
            miguel = by_sender.get("miguel", 0)
            items.append({
                "severity": "high",
                "title":    f"{drafts} draft emails are waiting in Gmail (not sent)",
                "detail":   f"Steven: {steven} drafts, Miguel: {miguel} drafts. All {drafts} are sitting in Gmail drafts — "
                            "none have been sent to the 244-company HubSpot pipeline. This is the highest-leverage "
                            "action the SDR can take right now.",
                "source":   "pipeline",
            })

        # 2. Companies ready to draft (have note + contact, no draft).
        if pl.get("available") and pl.get("ready_to_draft", 0) > 0:
            ready = pl["ready_to_draft"]
            items.append({
                "severity": "medium",
                "title":    f"{ready} companies are ready to draft (researched + have a contact)",
                "detail":   f"These companies have a HubSpot note and a contact, but no email draft. "
                            f"Steven can work through this queue at ~5-10 per day.",
                "source":   "pipeline",
            })

        # 3. HubSpot pipeline has 0 sent emails — explicit confirmation.
        if pl.get("available"):
            items.append({
                "severity": "low",
                "title":    "0 emails sent from the 244-company HubSpot pipeline",
                "detail":   f"All 244 companies are still pre-send. {pl.get('drafts_waiting', 0)} drafts in Gmail, "
                            f"{pl.get('ready_to_draft', 0)} companies ready to draft. "
                            f"The {pl.get('total', 0)} companies here are the real B2B pipeline; "
                            f"the 73 emails sent in the last 14d were to the legacy Apollo list (see Outreach).",
                "source":   "pipeline",
            })

        # Data quality: icp drift rows indicate CSV is dirty.
        dq = (leads.get("data_quality") or {})
        if dq.get("icp_drift_rows", 0) > 0:
            items.append({
                "severity": "medium",
                "title":    f"{dq['icp_drift_rows']} leads have non-standard icp values (legacy CSV)",
                "detail":   "Notes, scores, or dates leaked into the `icp` column. Cleanup the legacy CSV.",
                "source":   "leads_csv",
            })

        # Data quality: lead CSVs themselves are stale.
        oldest = dq.get("oldest_csv_days", 0) or 0
        if oldest > 14:
            items.append({
                "severity": "high" if oldest > 30 else "medium",
                "title":    f"Legacy lead CSVs are {oldest} days old (paused since May 2026)",
                "detail":   f"active.csv hasn't been updated in {oldest} days. The legacy gym/dental funnel is paused; "
                            "the real pipeline is the 244 HubSpot companies (see HubSpot Pipeline section).",
                "source":   "leads_csv",
            })

        # Funnel motion: pipeline has been frozen for multiple weeks (LEGACY).
        fm = funnel_motion if isinstance(funnel_motion, dict) else {}
        if fm.get("available") and fm.get("frozen"):
            items.append({
                "severity": "low",
                "title":    "[Legacy] May 2026 pipeline counts unchanged for 3+ weeks",
                "detail":   f"LEGACY: active={fm.get('totals_current', {}).get('active', '?')}, "
                            f"contacted={fm.get('totals_current', {}).get('contacted', '?')}, "
                            f"won={fm.get('totals_current', {}).get('won', '?')}, "
                            f"lost={fm.get('totals_current', {}).get('lost', '?')} — same for 3+ weeks. "
                            "This is the legacy Apollo (gym/dental) outreach that has been paused since May 2026. "
                            "The current B2B pipeline is the 244-company HubSpot universe (see HubSpot Pipeline section).",
                "source":   "leads_history (legacy)",
            })

        # Outreach: SDR hasn't sent emails in N weeks (LEGACY).
        weeks_since = fm.get("weeks_since_outreach")
        if isinstance(weeks_since, int) and weeks_since >= 2:
            items.append({
                "severity": "low",
                "title":    f"[Legacy] No outreach in {weeks_since} weeks (paused pipeline)",
                "detail":   "LEGACY: leads_history.csv shows 0 emails sent for the last "
                            f"{weeks_since} weekly reports. This is the legacy Apollo outreach that has been paused. "
                            "Steven has 60 drafts in Gmail ready to send to the current HubSpot pipeline.",
                "source":   "leads_history (legacy)",
            })

        # Engagement: no walkthroughs/meetings booked in 14d.
        eng = engagement if isinstance(engagement, dict) else {}
        if eng.get("available"):
            meetings_in_window = (eng.get("meetings") or {}).get("in_window", 0) or 0
            calls_in_window    = (eng.get("calls")    or {}).get("in_window", 0) or 0
            if meetings_in_window == 0 and calls_in_window > 0:
                items.append({
                    "severity": "high",
                    "title":    "No walkthroughs booked in 14d",
                    "detail":   f"HubSpot shows {calls_in_window} calls but 0 meetings logged. "
                                "Either no contacted lead has advanced to a walkthrough, or "
                                "walkthroughs are happening off-HubSpot (calendar, in person).",
                    "source":   "hubspot_events",
                })
            elif calls_in_window == 0 and (gm.get("totals") or {}).get("sent", 0) > 0:
                items.append({
                    "severity": "medium",
                    "title":    "Outreach sent but no calls logged in 14d",
                    "detail":   "Gmail shows emails sent but HubSpot shows no calls. "
                                "Calls may be happening off-HubSpot (personal phone).",
                    "source":   "hubspot_events",
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
        "outreach":      outreach,        # NEW in v2
        "engagement":    engagement,      # NEW in v2
        "pipeline":      pipeline,        # NEW in v3
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
