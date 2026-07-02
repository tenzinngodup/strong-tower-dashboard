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

## 3. The 8 sources — what they answer, how they fail

| Source | Question it answers | Auth | Wall-clock | Common failure |
|---|---|---|---|---|
| `leads` | "How many leads in the LEGACY May 2026 funnel?" | filesystem | <1s | CSVs untouched for >14d → action item fires (but they're paused) |
| `leads_history` | "Is the LEGACY May pipeline moving week-over-week?" | filesystem | <1s | SDR's weekly log stops being updated |
| `pipeline` | **"What's the real 244-company HubSpot B2B pipeline doing?"** | filesystem | <1s | `pipeline_master.csv` missing → re-run `scripts/build_pipeline_status.py` |
| `gmail` | "Is the SDR sending emails? Any bounces?" | Composio MCP | 35-45s | Wrong Composio account, rate limit. ⚠️ Counts LEGACY outreach, not HubSpot |
| `hubspot` | "What's in the open pipeline?" | Composio MCP | 5-15s | Token rotated, account 403 |
| `hubspot_events` | "After the touch, do leads engage?" | Composio MCP | 5-10s | Same as `hubspot`; per-event details blocked on MCP wrapper fix |
| `blotato` | "Are we posting on schedule?" | REST | 2-5s | Token expired |
| `ga4` | "Is the site getting traffic?" | Composio MCP | 5-10s | Property deleted, scope revoked |

**Total ingest: ~50s. Each source has 60s timeout. A stuck call fails its own source, not the pipeline.**

**Failure isolation pattern (read this before touching any source):** every source's `collect()` MUST return `safe_source_payload(name, payload, error=...)` and MUST catch every exception. The orchestrator (`ingest.py`) wraps the call too, but the source's own try/except is what makes the failure *informative* (`ok: false` with a clear message, not a stack trace).

**The legacy vs real pipeline distinction is the single most important concept in this dashboard.** Two completely separate lead universes:
- `leads` + `leads_history` = **legacy May 2026 Apollo outreach** (gyms, dental, fitness) — paused since 5/5
- `pipeline` = **current June 2026 HubSpot B2B universe** (property managers, GCs, title, senior living) — 244 companies, 64 drafts waiting in Gmail

**The 73 emails sent in the last 14d are the LEGACY outreach, not the HubSpot pipeline.** Zero emails have been sent to the 244-company HubSpot pipeline.

## 4. The page — 7 sections, in order

1. **Headlines** (4 KPI cards: pipeline, leads, win rate, CAC) — 3 of 4 are deliberately "—" because the data isn't there yet. Don't try to fill them with fake numbers. `new_leads` is now a dict `{value, total, source, note}` (v3) — it shows the weekly additions to the HubSpot pipeline.
2. **HubSpot pipeline** (NEW v3) — **the most important section.** 244 companies, per-stage counts, weekly additions, draft queue (60 steven + 4 miguel = 64 waiting in Gmail), sample of 5 drafts with subjects. The owner's #1 question — "what should steven be doing right now?" — is answered here.
3. **Legacy funnel motion** (NEW v2, now labeled legacy) — weekly pipeline trend from `leads_history.csv`. Surfaces "frozen pipeline" if counts haven't changed for 3+ weeks. Relabeled to make it clear this is the legacy May funnel, not the current B2B pipeline.
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
Built by `scripts/build_pipeline_status.py` in the main workspace (NOT in this dashboard repo). 244 companies, 14 columns, 1 row per HubSpot company. Cross-references 5 HubSpot upload batches + `lead_gen_drafts_log.csv` (steven's 71 drafts) to infer a stage per company: `noted` (179) → `drafted_not_sent` (60) → `contacted` (4) → `active` (1) → `won` (0) → `lost` (0).

The dashboard's "HubSpot pipeline" section reads this file. **If you delete or don't regenerate it, the most important section of the dashboard disappears.** The source (`scripts/sources/pipeline.py`) returns `ok: false` with a clear error if the file is missing, telling the operator to re-run the build script.

### 6.9 (OBSOLETE in v3) `leads/email_status.csv` is the SDR's weekly motion log
**RELABELED in v3.** This file is now labeled "Legacy May 2026 outreach (paused)" in the dashboard. It tracks the legacy Apollo gym/dental outreach, not the HubSpot B2B pipeline. The 73 emails sent in 14d (Gmail) match up with this file, NOT with the HubSpot pipeline. The HubSpot pipeline has **0 emails sent** to date (the 64 drafts in Gmail are sitting unsent).

The "Legacy funnel motion" section still reads this file, but it's now third-priority in the page (after the HubSpot pipeline section). Don't delete it — the historical data has value — but don't add new entries to it either (they'd be confusingly mixed with the HubSpot pipeline data).

### 6.10 The HubSpot `calls` object has no duration/disposition yet
Blocked on Composio MCP wrapper (see 6.1). Volume (in-window count) is wired; per-call details are not. Don't try to call `HUBSPOT_READ_CRM_OBJECT_BY_ID` to hydrate — that would be 59+ calls per ingest.

## 7. The "current state" you should know

As of 2026-07-02 (post-v3 wire-in), the dashboard surfaces 3 high-severity + 2 medium + 3 low action items. **The legacy items are now downgraded to low** and clearly labeled. The high-severity items are now REAL:

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
