# Strong Tower Owner Dashboard — Context Primer

**Last updated:** 2026-07-02
**Audience:** future agent (or Wren) who needs to understand, debug, modify, or extend this dashboard.
**Goal:** get up to speed in 5 minutes, not 30.

This file is the **why** and the **how-it-fits-together**. For the **what** (the implementation), read the code:
- `scripts/ingest.py` — orchestrator
- `scripts/sources/*.py` — one per source, each exports `collect() -> dict`
- `scripts/compute/kpis.py` — rollups
- `public/*.html,*.js,*.css` — the static page

For **operational fixes** ("the page is wrong, what do I do?"), read `RUNBOOK.md`.

---

## 1. What this is, in one sentence

A **static page** at https://strong-tower-dashboard.pages.dev that a **weekly cron** (Mon 7am Pacific) re-populates by calling **7 data sources** (HubSpot deals + events, Blotato, GA4, Gmail, local CSVs), computing rollups into a JSON file, and re-deploying to **Cloudflare Pages** via direct upload (no GitHub OAuth required).

**Owner view:** opens one URL, sees 7 sections with real data + 5+ auto-generated action items.

## 2. Architecture in 10 seconds

```
[ Monday 7am Pacific cron ]
        │
        ▼
  scripts/ingest.py
        │
        ├─ leads           (local CSVs, <1s)
        ├─ leads_history   (SDR weekly log, <1s)
        ├─ gmail           (Composio → steven@, 35-45s, 20 hydrations)
        ├─ hubspot         (Composio → deals, 5-15s)
        ├─ hubspot_events  (Composio → calls/meetings/emails, 5-10s)
        ├─ blotato         (REST, 2-5s)
        └─ ga4             (Composio → GA4, 5-10s)
        │
        ▼
  data/snapshot.json (raw, gitignored)
        │
        ▼
  scripts/compute/kpis.py → data/kpis.json (rollups, gitignored)
        │
        ▼
  public/kpis.json (same-origin copy for the page)
        │
        ▼
  npx wrangler pages deploy public --project-name=strong-tower-dashboard
        │
        ▼
  https://strong-tower-dashboard.pages.dev
```

**Why this shape (and not Workers + KV + auth):** the owner checks weekly, not live. A static page with weekly data is simpler, cheaper ($0/mo), and faster than any real-time stack. v1 was over-engineered; v2 stays static.

## 3. The 10 sources — what they answer, how they fail

| Source | Question it answers | Auth | Wall-clock | Common failure |
|---|---|---|---|---|
| `leads` | "How many leads in the LEGACY May 2026 funnel?" | filesystem | <1s | CSVs untouched for >14d → action item fires (but they're paused) |
| `leads_history` | "Is the LEGACY May pipeline moving week-over-week?" | filesystem | <1s | SDR's weekly log stops being updated |
| `pipeline` | **"What's the real 244-company HubSpot B2B pipeline doing?"** | filesystem | <1s | `pipeline_master.csv` missing → re-run `scripts/build_pipeline_status.py` |
| `gmail` | "Is the SDR sending emails? Any bounces?" | Composio MCP | 35-45s | Wrong Composio account, rate limit. ⚠️ Counts LEGACY outreach, not HubSpot |
| `hubspot` | "What's in the open pipeline?" | Composio MCP | 5-15s | Token rotated, account 403 |
| `hubspot_events` | "After the touch, do leads engage?" | Composio MCP | 5-10s | Same as `hubspot`; per-event details blocked on MCP wrapper fix |
| `phone_call` | "Is the SDR dialing? What's the gross connect rate?" | filesystem | <1s | Zoom export not yet run / stale |
| `phone` (NEW v3.1) | **"Which HubSpot companies did steven actually reach by phone?"** | filesystem | <1s | `call_to_contact_matches.csv` missing → re-run `leads/match_calls.py` |
| `blotato` | "Are we posting on schedule?" | REST | 2-5s | Token expired |
| `ga4` | "Is the site getting traffic?" | Composio MCP | 5-10s | Property deleted, scope revoked |

**Total ingest: ~50s. Each source has 60s timeout. A stuck call fails its own source, not the pipeline.**

**Failure isolation pattern (read this before touching any source):** every source's `collect()` MUST return `safe_source_payload(name, payload, error=...)` and MUST catch every exception. The orchestrator (`ingest.py`) wraps the call too, but the source's own try/except is what makes the failure *informative* (`ok: false` with a clear message, not a stack trace).

**The legacy vs real pipeline distinction is the single most important concept in this dashboard.** Two completely separate lead universes:
- `leads` + `leads_history` = **legacy May 2026 Apollo outreach** (gyms, dental, fitness) — paused since 5/5
- `pipeline` = **current June 2026 HubSpot B2B universe** (property managers, GCs, title, senior living) — 244 companies, 64 drafts waiting in Gmail

**The 73 emails sent in the last 14d are the LEGACY outreach, not the HubSpot pipeline.** Zero emails have been sent to the 244-company HubSpot pipeline.

## 4. The page — 9 sections, in order

1. **Headlines** (4 KPI cards: pipeline, leads, win rate, CAC) — 3 of 4 are deliberately "—" because the data isn't there yet. Don't try to fill them with fake numbers. `new_leads` is now a dict `{value, total, source, note}` (v3) — it shows the weekly additions to the HubSpot pipeline.
2. **HubSpot pipeline** (NEW v3) — **the most important section.** 244 companies, per-stage counts (noted, contacted_both, contacted_email_only, contacted_call_only, drafted, active, lost), weekly additions, draft queue (60 steven + 4 miguel = 64 waiting in Gmail), sample of 5 drafts with subjects. The owner's #1 question — "what should steven be doing right now?" — is answered here.
3. **Outreach by person** (NEW v3.1) — steven vs heber split. Shows: steven emailed/drafted/called counts, heber drafted counts, % of pipeline touched. Heber's drafts go to the LEGACY gym/dental list (not the 244-pipeline). Critical for understanding who is doing what.
4. **Phone — per company** (NEW v3.1, FIXED v3.2.1) — per-company attribution from `call_to_contact_matches.csv`. Top 25 companies by call count with contact name, email, total calls, connected calls, first/last call date. E.164 normalized to match Zoom calls to HubSpot companies. **v3.2.1 match rate: 82% (201/245 calls), 132 unique companies, 100 unique contacts.** v3.1 was 60% (147 calls, 90 cos) — wrong; the 22pp gap was 51 calls to 06-18 batch companies (in `scripts/lead-intake-2026-06-18/inbound.csv`, never imported to HubSpot as contacts) + 17 false-positives against Zoom auto-created contacts (`+150****7770 Auto Zoom Phone`).
5. **Phone activity** (v3.2.1) — gross Zoom Phone volume: total dials, connect rate, per-day sparkline, result breakdown. Companion to section 4 (per-company). **v3.2.1 numbers: 245 dials / 213 connected (86.9%) / 250.8 min talk time / 71s avg / 31 dials last 7d.** Source: `scripts/sources/phone_call.py` reads `leads/phone_call_log.csv` columns `call_result`, `call_duration`, `call_date` (NOT the original Zoom export names `result`/`duration`/`date` — see pitfall #32).
6. **Legacy funnel motion** (NEW v2, now labeled legacy) — weekly pipeline trend from `leads_history.csv`. Surfaces "frozen pipeline" if counts haven't changed for 3+ weeks. Relabeled to make it clear this is the legacy May funnel, not the current B2B pipeline.
4. **Outreach** (NEW v2) — SDR sent email volume from Gmail + bounce signal. ⚠️ This is the LEGACY Apollo outreach, NOT the HubSpot pipeline. Replies not yet wired (v2.1).
5. **Engagement** (NEW v2) — HubSpot calls/meetings/emails volume. **Alerts when calls > 0 but meetings = 0** (the "no walkthroughs booked" signal).
6. **Marketing** — Blotato cadence + GA4 traffic. Unchanged from v1.
7. **Sales pipeline** — funnel chart from `leads.csv` (legacy). Unchanged from v1.
8. **Customer & operations** — gray placeholder until first closed-won deal. Don't add fake MRR.
9. **Action items** — auto-generated, severity-sorted. Top item is now "64 draft emails are waiting in Gmail" (v3).

**Each section has a colored tag** in its header: green (`tag-ok`) = healthy, red (`tag-warn`) = needs attention. Tags are state-driven (frozen pipeline, no walkthroughs, low calls), not aesthetic.

## 5. The data flow contracts

Every source returns:
```python
{
  "source":     "<name>",
  "ok":         True | False,
  "fetched_at": "<iso8601 UTC>",
  "error":      "<msg>",          # only if ok is False
  ...source-specific fields...
}
```

Every source MUST:
- Catch every exception (no raising from `collect()`)
- Return `safe_source_payload(name, payload, error=...)` on failure
- Include `fetched_at` (the dashboard shows "Data as of {ts}")
- Cast numeric strings to int/float at the boundary (GA returns `"21"`, the page wants `21`)

The compute layer (`kpis.py`) reads `snapshot[name]` and returns the 7 dashboard sections. Every KPI is wrapped in `_safe(fn, default)` so a broken computation doesn't kill the whole kpis.json.

## 6. The pitfalls (memorize these — they cost me time during v2 build)

### 6.1 Composio MCP: list args get stringified
When you call `HUBSPOT_READ_APAGE_OF_OBJECTS_BY_TYPE` or `HUBSPOT_SEARCH_CRM_OBJECTS_BY_CRITERIA` via `COMPOSIO_MULTI_EXECUTE_TOOL`, passing a Python list as `properties` (or `filterGroups`) gets serialized as a **string**, which the underlying API rejects with `"Input should be a valid list on parameter 'properties'"`. **Workaround: skip the `properties` argument entirely. Use default response shape (only `hs_createdate` + `hs_object_id`) and filter/bucket client-side.** Per-call details (duration, disposition) are blocked on this until the wrapper is fixed.

### 6.2 Composio MCP: `ids_only=true` is mandatory for volume
With `ids_only=false` + `include_payload=false`, Composio auto-paginates responses with >~3 messages to a sandbox file and returns a **truncated** `data_preview` (3 items only). Pagination breaks. The pattern: **`ids_only=true, max_results=500`** for one call → get all message IDs → then **hydrate 20 most recent individually** with `format=metadata` for timestamps + bounce detection. ~40s total for 73 sent emails.

### 6.3 `gmail` account must be `gmail_deem-ultima` (steven@), not `miguel@`
Composio has 4 active Gmail accounts; the default may not be the SDR's. The right one is hardcoded in `gmail.py:STEVEN_ACCOUNT_ID = "gmail_deem-ultima"`. If you see email counts of 0 or wrong numbers, check this first. The same `miguel@` confusion bit the previous agent — see `MEMORY.md` GMAIL DUAL-MAILBOX entry.

### 6.4 `gmail.py` GMAIL_FETCH_EMAILS date filter pitfall
`query: "in:sent after:YYYY/MM/DD before:YYYY/MM/DD"` works. The Composio skill's warning about date filter capping to "today" is for `in:sent after:DATE` shorthand — use the fully-qualified form.

### 6.5 `cronjob run` silently re-enables paused jobs
Verified 2026-07-01: if you `cronjob pause 1223b798d21f` and then `cronjob run 1223b798d21f`, the job is **enabled after the run** even though the docs imply it stays paused. **Always re-pause after a manual run** if you don't want it firing on schedule. The dashboard cron `1223b798d21f` is currently paused by design.

### 6.6 `cron/jobs.json` edits don't propagate
The scheduler re-reads prompts from the in-memory registry, not from disk. Edit the prompt via `cronjob update --prompt` or `hermes cron edit --prompt`, never by editing `cron/jobs.json`. Backup first.

### 6.7 CF Pages direct-upload is faster than GitHub auto-deploy
`npx wrangler pages deploy public --project-name=X` takes ~5s and works without GitHub OAuth. CF's auto-deploy on git push takes 30-60s (build queue). We use direct upload in the cron. If you later wire GitHub OAuth, change the deploy step in `scripts/refresh_and_deploy.sh` to `git push origin main`.

### 6.8 (OBSOLETE in v3) The lead CSVs in `workspace/leads/*.csv` are the source of truth for the funnel
**REPLACED by 6.8b in v3.** The lead CSVs (active.csv, contacted.csv, won.csv, lost.csv) are now labeled "Legacy May 2026 outreach (paused)" in the dashboard. They were the source of truth for v1/v2, but the real B2B pipeline is the 244-company HubSpot universe tracked in `pipeline_master.csv`. The CSVs have known schema drift (12 rows with non-standard `icp` values, similar drift in `stage`) and haven't been updated since 2026-05-05.

### 6.8b (NEW v3) `leads/pipeline_master.csv` is the real B2B pipeline — and it's the dashboard's primary "what's the funnel doing" source
Built by `scripts/build_pipeline_status.py` in the main workspace (NOT in this dashboard repo). 244 companies, 14 columns, 1 row per HubSpot company. **v3.1 update**: the 6-stage vocabulary is now `{contacted_both, contacted_email_only, contacted_call_only, drafted, noted, unworked}`. Per-person columns added: `emailed_by_heber`, `emailed_by_steven`, `drafted_by_heber`, `drafted_by_steven`, `called_by_steven`, `outreach_type`. The build script reads `leads/contacted_signals.csv` to populate these. **Stage distribution (v3.2.1, 2026-07-02): 38 contacted_both, 122 contacted_call_only, 0 contacted_email_only, 25 drafted, 97 noted. Steven contacted 143 of 244 (58%, 122 called + 62 drafted; some overlap); heber contacted 4 (legacy list, 0 of 244 B2B pipeline).** The 0 contacted_email_only stage is a v3.2.1 side effect: the new `phone.py` attribution recovered 89 companies from `noted` into `contacted_call_only`, and the prior `contacted_email_only` bucket was empty (no steven sends to non-callers).

The dashboard's "HubSpot pipeline" section reads this file. **If you delete or don't regenerate it, the most important section of the dashboard disappears.** The source (`scripts/sources/pipeline.py`) returns `ok: false` with a clear error if the file is missing, telling the operator to re-run the build script.

### 6.9 (OBSOLETE in v3) `leads/email_status.csv` is the SDR's weekly motion log
**RELABELED in v3.** This file is now labeled "Legacy May 2026 outreach (paused)" in the dashboard. It tracks the legacy Apollo gym/dental outreach, not the HubSpot B2B pipeline. The 73 emails sent in 14d (Gmail) match up with this file, NOT with the HubSpot pipeline. The HubSpot pipeline has **0 emails sent** to date (the 64 drafts in Gmail are sitting unsent).

The "Legacy funnel motion" section still reads this file, but it's now third-priority in the page (after the HubSpot pipeline section). Don't delete it — the historical data has value — but don't add new entries to it either (they'd be confusingly mixed with the HubSpot pipeline data).

### 6.10 The HubSpot `calls` object has no duration/disposition yet
Blocked on Composio MCP wrapper (see 6.1). Volume (in-window count) is wired; per-call details are not. Don't try to call `HUBSPOT_READ_CRM_OBJECT_BY_ID` to hydrate — that would be 59+ calls per ingest.

### 6.11 (NEW v3.1) Heber's outreach is to a DIFFERENT lead universe than Steven's
**Per-person attribution pitfall that nearly broke the dashboard in v3.0.** The `lead_gen_drafts_log.csv` mixes drafts from BOTH `miguel@strongtowercs.com` (heber) AND `steven@strongtowercs.com`. But:
- **Steven's 59 drafts** go to the 244-company HubSpot B2B pipeline (PMs, GCs, title, senior living).
- **Heber's 37 drafts** go to the LEGACY gym/dental/fitness/medical list from Apollo (paused May 2026).

When you build pipeline_master.csv and cross-reference by company name or email, the 4 heber drafts that *do* match the 244-pipeline are noise — they're to legacy-list companies that were re-uploaded to HubSpot for some reason, but the outreach is still considered "legacy" (different positioning, different ICP).

**Rule of thumb:** for the 244-company HubSpot pipeline, count steven-only outreach. Heber's outreach is tracked separately and labeled "legacy" in the dashboard. If you conflate them, the dashboard will overstate "drafts waiting" and misattribute the channel/person.

### 6.12 (NEW v3.1) Zoom Phone: line owner ≠ actual dialer
The Zoom Phone export shows `From: heber@minyn.link` for ALL 245 outbound calls. That's because the line `(971) 213-5005` ext 800 is registered to heber@minyn.link. But the user confirmed **all 245 calls were actually placed by steven**. The phone_call.py and phone.py sources record BOTH fields:
- `caller_line_owner` = `heber@minyn.link` (truthful, what Zoom records)
- `is_steven_call` = `y` (per user statement)

If you build a per-agent dashboard from Zoom data alone, you'll wrongly attribute all 245 calls to heber. Trust the user, not the data — but record both fields so the audit trail is honest.

### 6.13 (NEW v3.2.1) The 60% match rate was wrong — the 06-18 batch is a known orphan
`scripts/lead-intake-2026-06-18/` uploaded 100 businesses to HubSpot as **companies only** (no contact records). Steven called them in mid-June using phone numbers preserved in `scripts/lead-intake-2026-06-18/inbound.csv`. The v3.1 `phone.py` matcher only checked HubSpot contacts, so 51 of 98 "unmatched" calls were actually known-pipeline companies, just with no contact row. v3.2.1's matcher adds `inbound.csv` as a 2nd lookup tier (E.164 exact + last-4 + state tiebreaker). Match rate: 60% → 82%. 132 unique companies (up from 90). If you build a new `match_calls.py`, **always** check the inbound CSV tier. Pitfall #30 in `skills/executive-dashboard/SKILL.md`.

### 6.14 (NEW v3.2.1) Zoom auto-creates HubSpot contacts for every number dialed — they're false positives
Zoom's HubSpot integration creates a contact record with name `+150****7770 Auto Zoom Phone` and empty `lifecyclestage` for any number that receives a call. If your matcher does string equality on phone numbers, these auto-contacts will inflate the "unique contacts reached" count. 17 of v3.1's 147 matches were auto-contacts. Filter rule (in `phone.py`): drop any contact where `name.startswith('+')` OR `'Auto Zoom Phone' in name` OR `lifecyclestage == ''`. Pitfall #28 in `skills/executive-dashboard/SKILL.md`.

### 6.15 (NEW v3.2.1) Source-script column names must match the CSV — silent 0s if they don't
`phone_call.py` was written reading columns `result`/`duration`/`date` (the original Zoom export names). But the normalized `leads/phone_call_log.csv` uses prefixed names `call_result`/`call_duration`/`call_date`. The source ran without error, returned 245 rows, and silently emitted zeros for every aggregate (connected=0, connect_rate=0%, talk_time=0m, avg=0s). The dashboard rendered "245 dials / 0 connected" — plausible-looking, totally wrong. **Always `head -1 <csv>` before writing a source reader; assert the first 5 rows have the expected column.** Pitfall #32 in `skills/executive-dashboard/SKILL.md`.

### 6.16 (NEW v3.2.1) 48% of the pipeline has no contact record — the 06-18 orphan is the largest such batch
118 of 244 HubSpot companies (48%) have **no contact record at all** — these are 06-18 batch + similar earlier batches uploaded as company-only. The dashboard now shows match rate 82% (with `inbound.csv` fallback), but the underlying gap is 48% of pipeline companies are contact-less. **Action item v2.1**: add a `has_contact_record` boolean to `pipeline_master.csv` and a "Pipeline contact density" card to the dashboard. Backfilling the 06-18 batch with `inbound.csv` phone numbers is a 30-minute script.

## 7. The "current state" you should know

**v3.2.1 (2026-07-02, current) — the v3.2.1 build added per-person + per-company phone attribution. Three corrections to v3.2 shipped at the same time:**

1. Phone match rate: **60% → 82%** (147 → 201 matched calls; 90 → 132 unique companies)
2. Steven contacted: **39% → 58%** (95 → 143 touched) — the 25% milestone is hit by 2x
3. Phone Activity section was rendering all 0s due to a column-name bug — now shows 245 dials / 213 connected / 86.9% rate / 250.8 min talk time

**Action items (v3.2.1, ordered by leverage):**

| Priority | Item | Effort | Why now |
|---|---|---|---|
| **P0** | **Connect GitHub → CF Pages for auto-deploy** (or wire the cron to push) | 30 sec OAuth click (CF) OR 2 hours (cron + CF API token) | Without this, the dashboard does NOT auto-refresh. Tenzin asked "freshes like everyday?" and the answer is no. |
| P0 | **Resume the weekly dashboard cron** (`1223b798d21f`, Mon 14:00 UTC) | 1 command | Currently PAUSED. Even without auto-deploy, the cron runs `ingest.py` and validates sources. |
| P1 | **Backfill the 42 newly-attributed 06-18 companies as HubSpot contacts** using `scripts/lead-intake-2026-06-18/inbound.csv` phone numbers | 30 min script + 5 min review | 132 unique companies reached, but 42 of them are companies-without-contacts in the 244-pipeline. Backfilling makes them reachable for follow-up emails. |
| P1 | **Add `has_contact_record` column to `pipeline_master.csv`** + a "Pipeline contact density" card to the dashboard | 2 hours | 48% of pipeline has no contact (118/244). Surface the gap, don't bury it in a deep-dive. |
| P1 | **Investigate the 44 truly-unmatched calls** (40 connected + 4 failed). Not in HubSpot, not in 06-18 inbound. Steven was calling from a different list — find that list. | 1 hour (ask steven) | The "last 18% gap" is the next data quality unlock. |
| P2 | **Add per-call duration / disposition to `hubspot_events.py`** (when MCP wrapper is unblocked) | 1 hour | Per-call talk time, hold time, outcome — feeds the per-company phone section. |
| P2 | **Reply counts in `gmail.py`** | 1-2 hours | Per-thread INBOX lookup is 73+ MCP calls. Batch it once on weekly refresh. |
| P2 | **Custom domain `dashboard.strongtowercs.com`** | 5 min (CF DNS) | Polish. |
| P3 | **IG Graph + LinkedIn Pages engagement** | 4-6 hours + new OAuth | Out of scope for v3. |
| P3 | **Real-time / per-day refresh** (change cron from Mon 14:00 → daily 14:00) | 1 min once auto-deploy is wired | Polish. |
| P3 | **Anomaly scan cron** (week-over-week drops, 0-sent days) | 2 hours | Owner-selected next-phase task #1. |
| P3 | **SDR follow-up sequencer** (read contacted.csv + gmail, draft follow-ups) | 3-4 hours | Owner-selected next-phase task #2. |

**Other v3 action items (still live, not duplicated above):**

| Severity | Title | Source | Owner interpretation |
|---|---|---|---|
| **high** | **64 draft emails are waiting in Gmail (not sent)** | pipeline | **Steven has 60 drafts + Miguel has 4 drafts, none sent to the 244-company HubSpot pipeline. This is the highest-leverage action the SDR can take right now.** |
| high | Legacy lead CSVs are 57 days old (paused since May 2026) | leads_csv | The legacy CSVs are paused, not broken. Action is to either retire them or restart the Apollo outreach. |
| high | No walkthroughs booked in 14d | hubspot_events | 73 calls but 0 walkthroughs. Walkthroughs may be off-HubSpot. |
| medium | 56 companies are ready to draft (researched + have a contact) | pipeline | Steven can work through this queue at ~5-10/day. |
| medium | 12 leads have non-standard icp values (legacy CSV) | leads_csv | CSV schema drift in the legacy gym/dental CSVs. Cleanup the CSV. |
| low | 0 emails sent from the 244-company HubSpot pipeline | pipeline | Reinforces the high-severity "drafts waiting" item. |
| low | [Legacy] May 2026 pipeline counts unchanged for 3+ weeks | leads_history (legacy) | The legacy Apollo outreach is paused. Counts haven't changed because nothing is happening. |
| low | [Legacy] No outreach in 2 weeks (paused pipeline) | leads_history (legacy) | Same as above. The SDR is drafting for the HubSpot pipeline, not the legacy one. |

**Cross-source validation that DID work:** Gmail says 73 sent; HubSpot `emails` object says 73. Same number, two independent paths, agree. But both are the LEGACY outreach, not the HubSpot pipeline (which has 0 sent).

**What the owner should do first (in order):**
1. **Open Gmail drafts and send steven's 60 + miguel's 4 drafts** (resolves the top-priority action item; moves the pipeline forward).
2. **Verify walkthroughs are being logged to HubSpot** (if they are, the 0 is real; if not, fix the process).
3. **Decide what to do with the 80-row legacy universe** (gyms/dental CSVs): retire them, re-enrich, or restart the Apollo outreach.

## 8. The v2.1+ backlog (if you have to extend this)

| Item | Effort | Why it's not in v3 |
|---|---|---|
| Per-call duration / disposition in HubSpot | small (1 hour) IF MCP wrapper is fixed, else unblocker | Composio MCP rejects `properties` arg (see 6.1) |
| Reply counts in gmail.py | medium (1-2 hours) | Per-thread INBOX lookup is 73+ MCP calls; adds 30s+ to ingest |
| Per-lead "days since contacted" in pipeline.py | medium (3-4 hours) | Need to add `contact_date` to pipeline_master.csv (cross-ref with email_status.csv) |
| Wire pipeline.py → email_status.csv for sent tracking | small (2 hours) | So the dashboard knows when each draft was actually sent. Today it's all "drafts not sent"; once steven sends, we need to update. |
| IG Graph + LinkedIn Pages engagement (likes/comments) | large (4-6 hours + new OAuth) | Out of scope per v2 plan §10 |
| Real-time / per-day refresh | small (10 min) | Just change the cron schedule from `0 14 * * 1` to `0 14 * * *` |
| Custom domain `dashboard.strongtowercs.com` | 5 min (CF dashboard) | Owner hasn't asked for it |
| Action item deduplication | small (30 min) | Done in v3 for legacy items (downgraded to low + labeled) |
| Wire GitHub → CF Pages for auto-deploys | 30 sec OAuth click in CF dashboard | Owner hasn't done it; direct upload works fine in the meantime |
| Auto-rebuild pipeline_master.csv | medium (3 hours) | When steven sends a draft or a new HubSpot batch lands, the master CSV needs to regenerate. Today it's manual. Could be a webhook or a daily cron. |
| Anomaly scan cron | small (2 hours) | Daily check for week-over-week drops, 0-sent days, etc. Posts to Discord. **Owner selected this as task #1 in the next phase.** |
| SDR follow-up sequencer | medium (3-4 hours) | Reads `leads/contacted.csv` + gmail, identifies leads contacted >7d ago with no reply, drafts follow-ups to `leads/followups_due.csv` for human review. **Owner selected this as task #2 in the next phase.** |

## 9. Pointers

- **Live URL:** https://strong-tower-dashboard.pages.dev
- **Project root:** `/opt/data/profiles/strong-tower/workspace/strong-tower-dashboard/`
- **GitHub:** https://github.com/tenzinngodup/strong-tower-dashboard
- **CF Pages project id:** `57d74733-29fb-458c-843e-f9c3951c2ad2`
- **CF account id:** `6267da94e5b26778c479aebcae85de2e`
- **Cron job id:** `1223b798d21f` (currently **PAUSED**)
- **Cron schedule:** `0 14 * * 1` (Mon 14:00 UTC = Mon 7am Pacific)
- **Refresh+deploy wrapper:** `scripts/refresh_and_deploy.sh`
- **Last deploy:** see GitHub `main` branch, latest commit
- **Operational fixes:** `RUNBOOK.md` in this repo
- **Schema reference:** `data/SCHEMA.md` in this repo
- **Profile-level memory:** `workspace/MEMORY.md` (skill-level patterns, cross-cutting pitfalls)
- **PRD/origin plan:** `~/.hermes/plans/2026-07-01-holistic-owner-dashboard.md` (the 4-phase plan that v2 was built from)
