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

## 3. The 7 sources — what they answer, how they fail

| Source | Question it answers | Auth | Wall-clock | Common failure |
|---|---|---|---|---|
| `leads` | "How many leads in each funnel stage?" | filesystem | <1s | CSVs untouched for >14d → action item fires |
| `leads_history` | "Is the pipeline moving week-over-week?" | filesystem | <1s | SDR's weekly log stops being updated |
| `gmail` | "Is the SDR sending emails? Any bounces?" | Composio MCP | 35-45s | Wrong Composio account, rate limit |
| `hubspot` | "What's in the open pipeline?" | Composio MCP | 5-15s | Token rotated, account 403 |
| `hubspot_events` | "After the touch, do leads engage?" | Composio MCP | 5-10s | Same as `hubspot`; per-event details blocked on MCP wrapper fix |
| `blotato` | "Are we posting on schedule?" | REST | 2-5s | Token expired |
| `ga4` | "Is the site getting traffic?" | Composio MCP | 5-10s | Property deleted, scope revoked |

**Total ingest: ~50s. Each source has 60s timeout. A stuck call fails its own source, not the pipeline.**

**Failure isolation pattern (read this before touching any source):** every source's `collect()` MUST return `safe_source_payload(name, payload, error=...)` and MUST catch every exception. The orchestrator (`ingest.py`) wraps the call too, but the source's own try/except is what makes the failure *informative* (`ok: false` with a clear message, not a stack trace).

## 4. The page — 7 sections, in order

1. **Headlines** (4 KPI cards: pipeline, leads, win rate, CAC) — 3 of 4 are deliberately "—" because the data isn't there yet. Don't try to fill them with fake numbers.
2. **Funnel motion** (NEW v2) — weekly pipeline trend from `leads_history.csv`. Surfaces "frozen pipeline" if counts haven't changed for 3+ weeks. **This is the most actionable section.**
3. **Outreach** (NEW v2) — SDR sent email volume from Gmail + bounce signal. Replies not yet wired (v2.1).
4. **Engagement** (NEW v2) — HubSpot calls/meetings/emails volume. **Alerts when calls > 0 but meetings = 0** (the "no walkthroughs booked" signal).
5. **Marketing** — Blotato cadence + GA4 traffic. Unchanged from v1.
6. **Sales pipeline** — funnel chart from `leads.csv`. Unchanged from v1.
7. **Customer & operations** — gray placeholder until first closed-won deal. Don't add fake MRR.
8. **Action items** — auto-generated. 4 currently fire as high-severity.

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

### 6.8 The lead CSVs in `workspace/leads/*.csv` are the source of truth for the funnel
NOT the HubSpot deals. The HubSpot pipeline is empty (0 active deals) but the lead CSVs have 44 active + 26 contacted. **If you only look at HubSpot, the dashboard will show "0 active" forever and the owner will think the funnel is dead.** The CSVs are hand-maintained by the SDR; they have known schema drift (the `icp` column has notes/dates leaked in 12 rows; the `stage` column is similarly dirty).

### 6.9 `leads/email_status.csv` is the SDR's weekly motion log
This is **already being collected** by the SDR's email-status pipeline. It has `active/contacted/won/lost/sent/hubspot_new` per week. **It is the dashboard's primary source for "is the pipeline moving week-over-week"** — much more useful than trying to derive motion from the static CSVs. The funnel_motion section reads this file.

### 6.10 The HubSpot `calls` object has no duration/disposition yet
Blocked on Composio MCP wrapper (see 6.1). Volume (in-window count) is wired; per-call details are not. Don't try to call `HUBSPOT_READ_CRM_OBJECT_BY_ID` to hydrate — that would be 59+ calls per ingest.

## 7. The "current state" you should know

As of 2026-07-02, the dashboard surfaces 4 high-severity + 1 medium action item:

| Severity | Title | Source | Owner interpretation |
|---|---|---|---|
| high | Lead CSVs are 57 days old | leads_csv | **The funnel numbers may be wrong.** Fix the SDR's CSV update process. |
| high | Pipeline counts have not changed in 3+ weeks | leads_history | The pipeline IS frozen. Either no outreach or no recording. |
| high | No walkthroughs booked in 14d | hubspot_events | 59 calls but 0 walkthroughs. Walkthroughs may be off-HubSpot. |
| high | Pipeline counts have not changed in 3+ weeks | leads_history | (duplicate — deduplication is a v2.1 task) |
| medium | 12 leads have non-standard icp values | leads_csv | CSV schema drift. Cleanup the CSV. |
| medium | SDR has not sent outreach in 2 weeks | leads_history | **CONTRADICTS gmail.py which says 73 sent in 14d.** This is because leads_history.csv is 6 days stale (last entry 2026-06-26). The leads_history file is the SDR's weekly checkpoint; the SDR hasn't been checkpointing. |

**Cross-source validation that DID work:** Gmail says 73 sent; HubSpot `emails` object says 73. Same number, two independent paths, agree.

**What the owner should do first (in order):**
1. Get the SDR to update `leads/email_status.csv` weekly (resolves 1-2 action items).
2. Verify walkthroughs are being logged to HubSpot (if they are, the 0 is real; if not, fix the process).
3. Re-engage on the 25 contacted-but-stalled leads (the funnel motion chart shows them).

## 8. The v2.1+ backlog (if you have to extend this)

| Item | Effort | Why it's not in v2 |
|---|---|---|
| Per-call duration / disposition in HubSpot | small (1 hour) IF MCP wrapper is fixed, else unblocker | Composio MCP rejects `properties` arg (see 6.1) |
| Reply counts in gmail.py | medium (1-2 hours) | Per-thread INBOX lookup is 73+ MCP calls; adds 30s+ to ingest |
| Per-lead "days since contacted" | medium (3-4 hours) | Lead CSVs don't have `createdate` columns — would need to add to the CSV schema first |
| IG Graph + LinkedIn Pages engagement (likes/comments) | large (4-6 hours + new OAuth) | Out of scope per v2 plan §10 |
| Real-time / per-day refresh | small (10 min) | Just change the cron schedule from `0 14 * * 1` to `0 14 * * *` |
| Custom domain `dashboard.strongtowercs.com` | 5 min (CF dashboard) | Owner hasn't asked for it |
| Action item deduplication | small (30 min) | v2 already has 1 dup; v2.1 is to add a "title in last 30d" dedup key |
| Wire GitHub → CF Pages for auto-deploys | 30 sec OAuth click in CF dashboard | Owner hasn't done it; direct upload works fine in the meantime |

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
