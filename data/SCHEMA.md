# Strong Tower Owner Dashboard — Data Schema

The dashboard renders two JSON files written by `scripts/ingest.py`:
- `data/snapshot.json` — raw inputs from each source, with `ok`/`error` flags
- `data/kpis.json` — computed rollups the page renders

This file documents every field, where it comes from, and the staleness contract.

## Sources

| Source key | What it fetches | Auth | Latency budget |
|---|---|---|---|
| `leads` | Local CSVs in `~/workspace/leads/*.csv` | none (filesystem) | < 1s |
| `leads_history` | Weekly pipeline motion log (`leads/email_status.csv`) | none (filesystem) | < 1s |
| `gmail` | SDR sent emails (last 14d) — volume + bounce signal | Composio MCP (`COMPOSIO_API_KEY`) | 35-45s (20 hydrations) |
| `hubspot` | Deals (active + archived), portal metadata | Composio MCP (`COMPOSIO_API_KEY`) | 5-15s |
| `hubspot_events` | Calls / meetings / emails volume, last 14d | Composio MCP (`COMPOSIO_API_KEY`) | 5-10s |
| `blotato` | Last 30d of posts, latest post per platform | REST (`BLOTATO_API_KEY`) | 2-5s |
| `ga4` | 7d sessions, top pages, UTM-source split | Composio MCP → GA4 Data API | 5-10s |

Total ingest budget: ~70s. Each source has its own 60s timeout, so a stuck call
fails its own source instead of blocking the others.

## `snapshot.json` shape

```jsonc
{
  "fetched_at": "2026-07-01T22:50:00+00:00",  // when the ingest started
  "sources_run": ["leads", "hubspot", "blotato", "ga4"],

  "leads": {
    "source": "leads_csv",
    "ok": true,
    "fetched_at": "...",
    "totals": { "reachable": 80, "active": 44, "contacted": 25, "won": 0, "lost": 11 },
    "funnel": { "New": 44, "Contacted": 25, "Walkthrough": 0, "Quoted": 0, "Won": 0 },
    "lost_count": 11,
    "by_icp": { "gym": 10, "dental": 17, ... },
    "contactability": { "phone_pct": 33.3, "email_pct": 27.5, ... },
    "data_quality": { "icp_drift_rows": 12, "icp_drift_sample": [...] }
  },

  "hubspot": {
    "source": "hubspot",
    "ok": true,
    "fetched_at": "...",
    "portal_id": 246063790,
    "totals": {
      "active_deals_returned":  0,
      "archived_deals_seen":    53,
      "open_deals":             0,
      "won_count":              0,
      "won_value_usd":          0.0,
      "lost_count":             0
    },
    "open_pipeline_value_usd": 0.0,
    "by_stage": {},                       // empty when no active deals
    "fetch_status": { "active_list_ok": true, "archived_list_ok": true }
  },

  "blotato": {
    "source": "blotato",
    "ok": true,
    "fetched_at": "...",
    "window_days":  30,
    "totals_30d":   { "instagram": 9, "linkedin": 62 },
    "totals_7d":    { "instagram": 9, "linkedin": 18 },
    "latest_post":  { "instagram": {...}, "linkedin": {...} },
    "cadence_goal": { "instagram": 7, "linkedin": 7 }
  },

  "ga4": {
    "source": "ga4",
    "ok": true,
    "fetched_at": "...",
    "property":   "properties/535249173",
    "window":     "last_7_days",
    "totals":     { "sessions": 21, "screenPageViews": 3 },
    "top_pages":  [ { "pagePath": "/", "sessions": 14 }, ... ],
    "by_source":  { "instagram": 3, "linkedin": 3, "blog": 0, "other": 15 }
  },

  "leads_history": {                                  // NEW in v2
    "source": "leads_history",
    "ok": true,
    "fetched_at": "...",
    "totals_current":   { "active": 45, "contacted": 26, "won": 0, "lost": 11 },
    "this_week_delta":  { "new_active": 0, "new_contacted": 0, "sent": 0, "hubspot_new": 24 },
    "trend_6w":         [ { "date": "2026-06-08", "active": 45, ... }, ... ],
    "staleness":        { "frozen_pipeline": true, "days_since_last": 6, "weeks_since_outreach": 2 }
  },

  "gmail": {                                            // NEW in v2
    "source": "gmail",
    "ok": true,
    "fetched_at": "...",
    "account":            "gmail_deem-ultima",          // steven@strongtowercs.com
    "window_days":        14,
    "totals":             { "sent": 73, "per_day_avg": 5.2, "bounced_estimated": 0, "hydrated_sample": 20 },
    "by_day":             [ { "date": "2026-06-29", "sent": 12 }, ... ],
    "replies":            { "available": false, "note": "v2.1 enhancement" }
  },

  "hubspot_events": {                                   // NEW in v2
    "source": "hubspot_events",
    "ok": true,
    "fetched_at": "...",
    "window_days":  14,
    "calls":     { "in_window": 59, "per_day": [...] },
    "meetings":  { "in_window": 0,  "per_day": [] },
    "emails":    { "in_window": 73, "per_day": [...] }
  }
}
```

## `kpis.json` shape

The static page renders from `kpis.json`, NOT from `snapshot.json`. Keeping
the compute layer separate means the page can be redesigned without re-running
all the network sources.

```jsonc
{
  "computed_at": "2026-07-01T22:50:01+00:00",
  "headlines": {
    "pipeline_value_usd": 0.0,            // HubSpot open deals sum
    "new_leads":          44,              // leads_csv "active" count
    "win_rate":           { "value": null, "closed_won": 0, "closed_lost": 0, "note": "no closed deals yet" },
    "blended_cac":        null             // placeholder — spend data not wired
  },
  "marketing": {
    "cadence": {
      "instagram": { "posted_7d": 9, "target_7d": 7, "on_pace": true },
      "linkedin":  { "posted_7d": 18, "target_7d": 7, "on_pace": true }
    },
    "traffic": {
      "sessions_7d":  21,
      "pageviews_7d": 3,
      "by_source_7d": { "instagram": 3, "linkedin": 3, "blog": 0, "other": 15 },
      "top_pages_7d": [ ... ]
    },
    "latest_post": { "instagram": {...}, "linkedin": {...} }
  },
  "sales": {
    "funnel": { "New": 44, "Contacted": 25, "Walkthrough": 0, "Quoted": 0, "Won": 0 }
  },
  "customer": {
    "available": false,
    "won_count": 0,
    "note":      "no closed-won deals yet"
  },
  "actions": [                              // auto-generated
    { "severity": "medium", "title": "12 leads have non-standard icp values", "source": "leads_csv", "detail": "..." },
    { "severity": "high",   "title": "Lead CSVs are 57 days old",              "source": "leads_csv", "detail": "..." },
    { "severity": "high",   "title": "Pipeline counts have not changed in 3+ weeks", "source": "leads_history", "detail": "..." },
    { "severity": "high",   "title": "No walkthroughs booked in 14d",          "source": "hubspot_events", "detail": "..." }
  ],
  "funnel_motion": {                       // NEW in v2
    "available":       true,
    "totals_current":  { "active": 45, "contacted": 26, "won": 0, "lost": 11 },
    "this_week_delta": { "new_active": 0, "new_contacted": 0, "sent": 0, "hubspot_new": 24 },
    "trend":           [ ... ],
    "frozen":          true,
    "days_since_last": 6,
    "weeks_since_outreach": 2
  },
  "outreach": {                            // NEW in v2
    "available":    true,
    "window_days":  14,
    "sent":         73,
    "per_day_avg":  5.2,
    "bounced_est":  0,
    "bounce_rate":  0.0,
    "by_day":       [ ... ],
    "replies_available": false
  },
  "engagement": {                          // NEW in v2
    "available":   true,
    "window_days": 14,
    "calls":     { "in_window": 59, "per_day": [...] },
    "meetings":  { "in_window": 0,  "per_day": [] },
    "emails":    { "in_window": 73, "per_day": [...] }
  }
}
```

## Staleness rules

| Field | Freshness | What the page does if stale |
|---|---|---|
| Pipeline value, funnel | Weekly | Shows a "Data as of [date]" badge |
| Cadence (IG/LinkedIn) | Updated daily by the underlying cron, dashboard shows last 7d | Same |
| Site sessions | 7d rolling window | Same |
| Latest post | Last published post | Same |

The dashboard is **weekly** by design (Phase 0 decision). The page shows a
"Data as of {fetched_at}" stamp so the owner always knows what they're
looking at.

## What we DON'T have (gaps to know about)

1. **Engagement metrics on social posts** (likes, comments, follower counts) — Blotato's
   `/posts/{id}/analytics` returns `metrics: null`. Real numbers would
   require the Instagram Graph API + LinkedIn Pages API (separate OAuth,
   separate build).
2. **Per-call duration / disposition** — the HubSpot `calls` object has
   `hs_call_duration` and `hs_call_disposition` but the Composio MCP
   wrapper currently rejects the `properties` array parameter on
   `HUBSPOT_READ_APAGE_OF_OBJECTS_BY_TYPE`. Volume is wired (Phase 3);
   per-call details are blocked on the MCP wrapper fix.
3. **Closed deal history details** — we count active + archived; per-deal
   `createdate`/`closedate` is a one-line addition to `DEAL_PROPERTIES`
   in `hubspot.py`.
4. **Spend / CAC** — no ad platform wired in. To get blended CAC, we'd
   need Google Ads or Meta Ads source.
5. **Email reply counts** — we count sent but not replied-to events.
   Real reply detection needs per-thread INBOX lookups (one MCP call per
   sent message) — feasible but ~30s+ of additional ingest time. v2.1.
6. **Companies / contacts count in HubSpot** — the LIST endpoint doesn't
   return a clean total. We can fetch a full export (~1k calls) for an
   exact count, but that's expensive. `>= 1` is what we know right now.

## What we DO have now (added in v2)

- **Funnel motion** (from `leads_history.csv`): weekly pipeline trend
  over 6 weeks, frozen-pipeline detection, weeks-since-outreach signal.
  Verified working 2026-07-02.
- **SDR outreach volume** (from Gmail via Composio): sent count,
  per-day bucketing, bounce estimate from hydrated sample of 20 most
  recent. Reply count deferred to v2.1. Verified: 73 sent in 14d.
- **HubSpot engagement events** (calls/meetings/emails): per-day volume
  for the last 14d. Per-event details (duration, disposition) blocked
  on MCP wrapper fix. Verified: 59 calls, 0 meetings, 73 emails.
- **CSV staleness detector** in `leads.py`: flags when the lead CSVs
  haven't been touched in >14 days. Verified working — currently
  reporting 57 days old (high severity).

## How to add a new KPI

1. Decide which source provides the raw number.
2. If the source already exists, edit the relevant field in
   `scripts/sources/<source>.py::collect()`.
3. If not, copy any existing source, rename, replace the body.
4. Add the source to the `SOURCES = [...]` list in `scripts/ingest.py`.
5. Add a rollup in `scripts/compute/kpis.py::compute()`.
6. The static page (Phase 2) renders from `kpis.json` — no source code
   changes there.

## How to add a new data source

1. Create `scripts/sources/<name>.py` with a `collect() -> dict` function.
2. Follow the `safe_source_payload()` pattern from `lib/dashboard_lib.py`
   so failures are isolated.
3. Add the name to `SOURCES = [...]` in `scripts/ingest.py`.
4. Re-run `python3 scripts/ingest.py` to verify.
