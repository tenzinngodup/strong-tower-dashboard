# Strong Tower Owner Dashboard — Data Schema

The dashboard renders two JSON files written by `scripts/ingest.py`:
- `data/snapshot.json` — raw inputs from each source, with `ok`/`error` flags
- `data/kpis.json` — computed rollups the page renders

This file documents every field, where it comes from, and the staleness contract.

## Sources

| Source key | What it fetches | Auth | Latency budget |
|---|---|---|---|
| `leads` | Local CSVs in `~/workspace/leads/*.csv` (LEGACY May 2026 outreach, paused) | none (filesystem) | < 1s |
| `leads_history` | Weekly pipeline motion log (`leads/email_status.csv`, LEGACY) | none (filesystem) | < 1s |
| `pipeline` | Unified HubSpot B2B pipeline (`leads/pipeline_master.csv`, 244 cos) | none (filesystem) | < 1s |
| `gmail` | SDR sent emails (last 14d) — volume + bounce signal | Composio MCP (`COMPOSIO_API_KEY`) | 35-45s (20 hydrations) |
| `hubspot` | Deals (active + archived), portal metadata | Composio MCP (`COMPOSIO_API_KEY`) | 5-15s |
| `hubspot_events` | Calls / meetings / emails volume, last 14d | Composio MCP (`COMPOSIO_API_KEY`) | 5-10s |
| `phone_call` | Zoom Phone log (245 dials, gross volume + per-day sparkline) | none (filesystem) | < 1s |
| `phone` (NEW v3.1) | Per-company call attribution (`call_to_contact_matches.csv`, 90 cos) | none (filesystem) | < 1s |
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
    "new_leads":          { "value": 0, "total": 244, "source": "HubSpot pipeline", "note": "of 244 total companies uploaded" },  // CHANGED in v3: was a plain number
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
    { "severity": "high",   "title": "64 draft emails are waiting in Gmail (not sent)", "source": "pipeline", "detail": "..." },
    { "severity": "high",   "title": "No walkthroughs booked in 14d",          "source": "hubspot_events", "detail": "..." },
    { "severity": "medium", "title": "56 companies are ready to draft",         "source": "pipeline", "detail": "..." },
    { "severity": "low",    "title": "0 emails sent from the 244-company HubSpot pipeline", "source": "pipeline", "detail": "..." },
    { "severity": "low",    "title": "[Legacy] May 2026 pipeline counts unchanged for 3+ weeks", "source": "leads_history (legacy)", "detail": "..." }
  ],
  "funnel_motion": {                       // NEW in v2
    "available":       true,
    "totals_current":  { "active": 45, "contacted": 26, "won": 0, "lost": 11 },
    "this_week_delta": { "new_active": 0, "new_contacted": 0, "sent": 0, "hubspot_new": 24 },
    "trend":           [ ... ],
    "frozen":          true,
    "days_since_last": 6,
    "weeks_since_outreach": 2,
    "source_label":    "Legacy May 2026 outreach (paused)"
  },
  "outreach": {                            // NEW in v2
    "available":    true,
    "window_days":  14,
    "sent":         73,                     // ⚠️ 73 = legacy Apollo outreach. 0 from HubSpot pipeline (see "pipeline" block).
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
  },
  "pipeline": {                            // NEW in v3 — THE real B2B pipeline
    "available":         true,
    "total":             244,
    "with_contact":      121,
    "with_note":         244,
    "stages":            { "noted": 179, "drafted_not_sent": 60, "contacted": 4, "active": 1, "lost": 0 },
    "ready_to_draft":    56,                // noted + has contact + no draft
    "drafts_waiting":    64,                // 60 steven + 4 miguel, all in Gmail drafts
    "drafts_by_sender":  { "steven": 60, "miguel": 4 },
    "weekly_additions":  [ { "week": "2026-05-25", "added": 0 }, { "week": "2026-06-01", "added": 0 }, ... ],
    "batches":           { "master": 39, "06-12": 21, "06-13": 40, "06-17": 21, "06-18": 123 },
    "sample_drafts":     [ { "company": "...", "subject": "...", "sender": "steven|miguel" } ],
    "freshness":         "1h old"
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
  Labeled "Legacy" — the legacy Apollo outreach (gym/dental) has been
  paused since May 2026. Verified working 2026-07-02.
- **SDR outreach volume** (from Gmail via Composio): sent count,
  per-day bucketing, bounce estimate from hydrated sample of 20 most
  recent. Reply count deferred to v2.1. Verified: 73 sent in 14d.
  ⚠️ **The 73 sent are the LEGACY Apollo outreach, NOT the HubSpot pipeline.**
- **HubSpot engagement events** (calls/meetings/emails): per-day volume
  for the last 14d. Per-event details (duration, disposition) blocked
  on MCP wrapper fix. Verified: 59 calls, 0 meetings, 73 emails.
- **CSV staleness detector** in `leads.py`: flags when the lead CSVs
  haven't been touched in >14 days. Verified working — currently
  reporting 57 days old (high severity, but the CSVs are paused, not broken).

## What we DO have now (added in v3)

- **HubSpot B2B pipeline** (from `leads/pipeline_master.csv`): the 244-company
  B2B universe across 5 HubSpot upload batches, with per-stage counts
  (179 noted, 60 drafted-not-sent, 4 contacted, 1 active, 0 lost),
  weekly additions, batch breakdown, and 5-sample of the 64 drafts
  in Gmail. Built by `scripts/build_pipeline_status.py` in the main
  workspace (NOT in the dashboard repo) — re-run when new batches
  are uploaded or steven's drafts are sent.
- **Three new pipeline action items** auto-generated: "64 drafts waiting
  in Gmail", "56 companies ready to draft", "0 emails sent from the
  244-company HubSpot pipeline". The first is now the top-priority
  action item on the dashboard.
- **Legacy labels** on the previous action items: "Pipeline counts have
  not changed in 3+ weeks" is now downgraded to low and labeled as
  referring to the LEGACY funnel, not the current B2B pipeline.

## What we DO have now (added in v3.1)

- **Per-person outreach attribution** (steven vs heber): the pipeline now splits
  the 244-company universe by WHO did the outreach. Steven contacted 95 of 244
  (39%) via 62 emails + 71 calls + 59 drafts. Heber contacted 0 of 244 (his
  4 drafts go to the legacy list, not the 244-company pipeline). Surfaced in
  the new "Outreach by person" section (`outreach_by_person` kpis block).
- **6-stage vocabulary** for the pipeline:
  `contacted_both` (38), `contacted_email_only` (24), `contacted_call_only` (33),
  `drafted` (4), `noted` (145), `unworked` (0). Replaces the old
  `drafted_not_sent` + `contacted` + `active` vocabulary. Per-stage
  `by_person` counts in `pipeline.by_person`:
  `{steven: {emailed, drafted, called, total_touched}, heber: {...}}`.
- **Per-company phone attribution** (NEW `phone` source): the dashboard
  now shows which HubSpot companies steven actually reached by phone
  (90 unique companies / 115 contacts / 245 matched calls). Built from
  `leads/call_to_contact_matches.csv` via E.164 normalization. 60% match rate.
  Note attribution honesty: `caller_line_owner=heber@minyn.link` (Zoom line
  owner) + `is_steven_call=y` (per user statement that steven was the dialer).
- **3 new kpis blocks**:
  - `outreach_by_person` — stage × person cross-tab
  - `phone_per_company` — top 25 companies by call count
  - `pipeline.by_person` — sub-dict of `pipeline` with the same per-person counts
- **Two new renderers** in `app.js`: `renderOutreachByPerson()` and
  `renderPhonePerCompany()`. The new "Phone — per company" section shows
  a sortable table (Company, Contact, Email, Calls, Connected, First, Last).

## What we DO have now (added in v3.2.1)

**v3.2.1 corrects v3.1 with three fixes to the phone attribution and a new gross-volume section.** Detailed post-mortem in `skills/executive-dashboard/references/v3.2.1-bugfixes.md` and pitfalls #27-#32 in `skills/executive-dashboard/SKILL.md`.

- **Phone match rate corrected: 60% → 82%** (147 calls / 90 cos → 201 calls / 132 cos / 100 unique contacts). The 22pp gap is two real issues:
  1. **51 of 98 v3.1 "unmatched" calls were to 06-18 batch companies** — phone numbers in `scripts/lead-intake-2026-06-18/inbound.csv` (E.164 exact, full numbers), never imported to HubSpot as contact records. `phone.py` now has a 2-tier lookup: HubSpot contacts → `inbound.csv` fallback.
  2. **17 of 147 v3.1 "matched" calls were false positives** — Zoom auto-creates HubSpot contacts named `+150****7770 Auto Zoom Phone` for every number dialed. The v3.2.1 matcher filters by `name.startswith('+')` OR `'Auto Zoom Phone' in name` OR `lifecyclestage == ''`.

- **Steven touched: 39% → 58%** (95 → 143). The 25% milestone is hit by 2x. Stage distribution: 38 contacted_both, 122 contacted_call_only, **0 contacted_email_only** (rolled into "noted" — no steven emails to non-callers), 25 drafted, 97 noted, 0 unworked. Total: 244.

- **Phone Activity section (NEW, `phone_call` source)**: gross Zoom Phone volume. 245 dials / 213 connected / 86.9% rate / 250.8 min talk time / 71s avg / 31 dials last 7d. Source: `scripts/sources/phone_call.py` reads `leads/phone_call_log.csv` columns `call_result`, `call_duration`, `call_date` (NOT the original Zoom export names `result`/`duration`/`date` — see pitfall #32 in the skill).

- **`leads/phone_call_log.csv` schema (v3.2.1, normalized form):**

  | Column | Type | Notes |
  |---|---|---|
  | `call_date` | ISO 8601 timestamp | e.g. `2026-07-02T16:24:11Z`. NOT `date` (the original Zoom name). |
  | `call_result` | string | `Connected` / `Call Failed` / `Canceled`. NOT `result`. |
  | `call_duration` | int | seconds. NOT `duration`. |
  | `to_phone_masked` | string | E.164 with middle 3 digits masked, e.g. `+150****9596`. Asterisks are real `*` bytes (pitfall #29). |
  | `is_steven` | `y` / empty | Per user statement, not derived from Zoom data. |
  | `caller_line_owner` | `heber@minyn.link` | The Zoom line that placed the call. Honest record, even though `is_steven=y`. |
  | `caller_name` | string | Zoom display name. |
  | `direction` | `outbound` / `inbound` | All 245 in our export are outbound. |
  | `from_phone` | E.164 | The line used to call. |

  **The 3- vs 4-digit asterisk count (CRITICAL — pitfall #29):** Zoom's format is `+1AAA****YYYY` where `AAA` is the first 2 digits of the area code (one digit masked by the 3rd `*` in `AAA*`+`***`+`YYYY`), the next 3 digits of the local number are also masked, and `YYYY` is the last 4 digits visible. So `+150****9596` means: area code 50X (503, 504, etc.), 3 masked digits, last 4 = 9596. E.164 exact match is impossible on the masked form — only last-4 + state-tiebreaker matching is viable.

- **`leads/call_to_contact_matches.csv` schema (v3.2.1):**

  | Column | Type | Notes |
  |---|---|---|
  | `call_id` | string | Zoom call ID. |
  | `callee_raw` | string | The masked callee phone number (with `*`s). |
  | `matched_contact_id` | string | HubSpot contact ID, OR empty if matched to company only. |
  | `matched_company_id` | string | HubSpot company ID, OR empty if no match. |
  | `match_method` | enum | `hubspot_e164_exact` / `inbound_e164_exact` / `hubspot_last4` / `inbound_last4` / empty (no match). |
  | `match_confidence` | enum | `high` (E.164 exact) / `medium` (last-4 + state tiebreaker) / `low` (last-4 only) / empty. |

  **Match counter rule:** `total_matched = len(rows where (matched_contact_id OR matched_company_id))` — NOT just contact matches. The 51 inbound-company matches count as attributed even though they have no contact record. v3.1's `total_matched: 147` only counted contact matches; v3.2.1's `total_matched: 201` counts both.

- **`leads/hubspot_contacts_with_phones.csv` (correct column names — pitfall #27):** `contact_phone` and `contact_mobilephone` (NOT `phone`/`mobilephone`). 200 of 353 contacts have phone numbers under `contact_phone`. The filename is a promise, not a fact — `head -1` before assuming the schema.

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
