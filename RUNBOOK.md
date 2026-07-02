# Strong Tower Dashboard — Runbook

Operational notes for the person (or future agent) who has to keep this
dashboard running. Read this before you change anything.

## TL;DR

- **Live URL:** https://strong-tower-dashboard.pages.dev
- **Project root:** `/opt/data/profiles/strong-tower/workspace/strong-tower-dashboard/`
- **GitHub:** https://github.com/tenzinngodup/strong-tower-dashboard
- **CF Pages project id:** `57d74733-29fb-458c-843e-f9c3951c2ad2`
- **CF account id:** `6267da94e5b26778c479aebcae85de2e`
- **Cron job id:** `1223b798d21f` (currently **PAUSED**)
- **Cron schedule:** `0 14 * * 1` (Mon 14:00 UTC = Mon 7am Pacific)

If the page is wrong, look at the four sections below in order.

## 1. The numbers look wrong / stale

**Symptom:** page shows old data, or a number doesn't match what you see in HubSpot/GA4/etc.

**Fix:**
1. Run the wrapper manually:
   ```bash
   /opt/data/profiles/strong-tower/workspace/strong-tower-dashboard/scripts/refresh_and_deploy.sh
   ```
2. This takes ~30 seconds. If it succeeds, the live page is updated.
3. If it fails, read the log:
   ```bash
   tail -50 /opt/data/profiles/strong-tower/workspace/dashboard_deploy.log
   ```
4. The log will tell you which step (ingest / wrangler / verify) failed and why.

**Don't** try to fix a wrong number by editing `public/kpis.json` directly — the next cron run will overwrite it.

## 2. A source is failing

**Symptom:** one or more of `leads`, `hubspot`, `blotato`, `ga4` shows `ok: false` in the deploy log.

**Sources and their common failure modes:**

| Source | What it talks to | Common failure | Fix |
|---|---|---|---|
| `leads` | Local CSVs in `workspace/leads/*.csv` (LEGACY May 2026 outreach, paused) | Bad row data (e.g. `icp` column has non-standard values) or stale CSVs (>14d untouched) | Edit the CSV, re-run. Note: CSVs are paused, not broken. The high-severity "57 days old" alert is by design. |
| `leads_history` | Local `leads/email_status.csv` (SDR weekly log, LEGACY) | Stale log (last entry >7d ago) or frozen pipeline (no motion for 3+ weeks) | Run the SDR's weekly email-status pipeline; update the CSV. Labeled "Legacy" on the dashboard. |
| `pipeline` | Local `leads/pipeline_master.csv` (244-company HubSpot B2B universe, v3) | `pipeline_master.csv` missing or stale | Re-run `python3 /opt/data/profiles/strong-tower/workspace/scripts/build_pipeline_status.py` to regenerate. **This is the most important source** — if it fails, the most important section of the dashboard disappears. |
| `gmail` | Composio MCP → steven@ Gmail | Composio rate-limit, wrong account, GMAIL_FETCH_EMAILS pagination | Update `COMPOSIO_API_KEY` in `.env`; verify `STEVEN_ACCOUNT_ID` in `scripts/sources/gmail.py` is `gmail_deem-ultima`. **Note: counts LEGACY outreach, not the HubSpot pipeline.** |
| `hubspot` | Composio MCP → HubSpot | API token rotated, account 403 | Update `COMPOSIO_API_KEY` in `.env` |
| `hubspot_events` | Composio MCP → HubSpot (calls/meetings/emails) | Same as `hubspot`; also: per-call details currently blocked by MCP wrapper | Volume works; per-call details (duration, disposition) deferred to v2.1 |
| `blotato` | Blotato REST API | Token expired | Update `BLOTATO_API_KEY` in `.env` |
| `ga4` | Composio MCP → GA4 | Property deleted, scope revoked | Update `COMPOSIO_API_KEY` + check GA property exists |

**Rotating a secret:**
1. Generate the new secret at the provider (Cloudflare dashboard, Composio dashboard, Blotato dashboard, GitHub settings).
2. Edit `/opt/data/profiles/strong-tower/.env` (mode 600, hermes-owned).
3. Test:
   ```bash
   source /opt/data/profiles/strong-tower/.env && \
     python3 /opt/data/profiles/strong-tower/workspace/strong-tower-dashboard/scripts/ingest.py --only <source>
   ```
4. If it works, the next cron run will pick up the new key.

**Don't** commit the secret to git. The `.env` is gitignored. The CF token is in `.env` and is also gitignored.

## 2.5. The legacy vs real pipeline (READ THIS if confused about the numbers)

The dashboard has **two completely separate lead universes**. Confusing them is the #1 way to misread the dashboard.

| Source | Universe | Status | What it tracks |
|---|---|---|---|
| `leads` + `leads_history` | **Legacy May 2026 Apollo outreach** (gyms, dental, fitness) | **PAUSED** since 2026-05-05 | 80 rows, last touched 57 days ago. The frozen-pipeline / stale-CSV alerts refer to this. |
| `pipeline` | **Current June 2026 HubSpot B2B universe** (property managers, GCs, title, senior living) | **ACTIVE** | 244 companies uploaded in 5 batches (5/13 master, 6/12, 6/13, 6/17, 6/18). **v3.1**: 95 contacted by steven, 145 noted, 4 drafted. |
| `phone` (NEW v3.1) | **Per-company call attribution** | ACTIVE | 90 HubSpot companies matched to Zoom calls via E.164 normalization. 245 matched of 245 outbound (60% match). |
| `gmail` | Tracks sent emails | Active | **The 73 sent in 14d are the LEGACY outreach, NOT the HubSpot pipeline.** Cross-validate with `hubspot_events` (also 73 emails) — same universe. |

**Key numbers (as of 2026-07-02, v3.1):**
- 244 companies in the HubSpot pipeline
- **Stage distribution (v3.1, 6-stage vocabulary):** 145 noted, 38 contacted_both (steven emailed+called), 33 contacted_call_only, 24 contacted_email_only, 4 drafted, 0 unworked
- **Steven contacted 95 of 244 (39%)** — 62 emailed, 71 called, 59 drafted. **Heber contacted 0** (heber's drafts go to legacy list)
- 64 drafts in Gmail (60 by steven, 4 by miguel), **0 sent to the HubSpot pipeline**
- 245 outbound calls in 16 days, 213 connected (87% pick-up), 90 unique companies reached
- 73 sent emails in 14d = legacy Apollo outreach (different universe)
- 56 companies ready to draft (have a HubSpot note + a contact, no draft yet)

**If the page says "0 new leads this week" but the legacy `leads/active.csv` has 45 rows:** that's correct. The 45 are the legacy universe; the 0 is the HubSpot pipeline (no new batches uploaded this week).

### 2.6. v3.1 per-person attribution (Steven vs Heber)

The dashboard v3.1 splits outreach by person. **Critical fact:** steven and heber operate on DIFFERENT lead universes for the most part:
- Steven = SDR working the 244-company HubSpot B2B pipeline
- Heber = manager; his drafts go to the legacy gym/dental list (paused May 2026)

If the dashboard shows "steven 95 touched / heber 4 touched", that's correct: 95 unique HubSpot companies have evidence of steven reaching out, 4 have evidence of heber reaching out (and those 4 are noise — legacy companies re-uploaded to HubSpot).

The "Phone — per company" section shows 90 unique HubSpot companies that received calls. All 245 calls are recorded as `is_steven_call=y` (per user statement that steven was the dialer), even though the Zoom line owner is `heber@minyn.link`. Both fields are kept honest in the source data.

### 2.7. v3.2.1 phone match rate (60% → 82%)

**v3.1 reported 60% match rate (147 calls, 90 companies). v3.2.1 corrects to 82% (201 calls, 132 companies).** The 22pp gap is two real issues:

1. **51 of the 98 "unmatched" calls were to 06-18 batch companies** (churches, schools, medical centers, senior living) whose phone numbers are in `scripts/lead-intake-2026-06-18/inbound.csv` — never imported to HubSpot as contact records. `phone.py` now has a 2nd lookup tier that matches against this CSV before falling back to "unmatched".
2. **17 of the 147 v3.1 "matches" were false positives** — Zoom auto-creates HubSpot contacts named `+150****7770 Auto Zoom Phone` for any number that receives a call. The v3.2.1 matcher filters these out by name pattern.

After v3.2.1: **steven touched 143 of 244 (58%), 132 unique companies reached, 201 of 245 calls matched, 25% milestone hit by 2x.**

**Action to take if you ever rebuild `phone.py`:** keep the 2-tier lookup (HubSpot contacts → `inbound.csv` fallback) and the auto-contact filter (`name.startswith('+')` OR `'Auto Zoom Phone' in name` OR `lifecyclestage == ''`).

### 2.8. v3.2.1 Phone Activity section showing all 0s (column-name bug)

**Symptom:** The Phone Activity card shows "245 dials / 0 connected / 0% rate / 0m talk time / 0s avg" — plausible-looking, totally wrong. The "Phone — per company" section (which reads a different file) shows correct numbers.

**Cause:** `scripts/sources/phone_call.py` reads columns `result`/`duration`/`date` (the original Zoom export names). The normalized `leads/phone_call_log.csv` uses prefixed names `call_result`/`call_duration`/`call_date`. The source runs without error, returns 245 rows, and silently emits zeros for every aggregate. Pitfall #32 in `skills/executive-dashboard/SKILL.md`.

**Fix:** `head -1 leads/phone_call_log.csv` to confirm the actual column names, then patch the source to match. Always do this BEFORE assuming the rendered page is right.

## 3. The page is broken (deploy error)

**Symptom:** `https://strong-tower-dashboard.pages.dev` returns 404, 500, or the HTML is wrong.

**Diagnose:**
1. Check the latest deploys in the CF dashboard:
   `https://dash.cloudflare.com/6267da94e5b26778c479aebcae85de2e/pages/view/strong-tower-dashboard`
2. The most recent deployment is at the top. Click it to see its status.
3. If the latest deploy failed, check `dashboard_deploy.log` for the wrangler output.

**Roll back:**
- In the CF dashboard, click "Rollback to this deployment" on the last known-good deploy.
- Or via API: `curl -X POST https://api.cloudflare.com/client/v4/accounts/.../pages/projects/strong-tower-dashboard/deployments/<id>/rollback` (with `Authorization: Bearer $CLOUDFLARE_API_TOKEN`).

**Redeploy manually:**
```bash
cd /opt/data/profiles/strong-tower/workspace/strong-tower-dashboard
set -a; source /opt/data/profiles/strong-tower/.env; set +a
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID
npx --yes wrangler pages deploy public --project-name=strong-tower-dashboard --branch=main
```

## 4. Adding or changing a KPI

**Goal:** add a new number to the headlines, marketing, sales, customer, or action items section.

**Where to edit:**

1. If the data comes from an existing source → edit `scripts/sources/<source>.py::collect()` to add the field.
2. If you need a new source → copy an existing source, rename, replace the body, add to `SOURCES = [...]` in `scripts/ingest.py`.
3. To surface a computed number → add a rollup in `scripts/compute/kpis.py::compute()`.
4. To render it on the page → edit `public/app.js` (the section renderer for that section) and `public/index.html` (the markup) and `public/styles.css` (if it needs new visual treatment).

**Then:**
1. Run `python3 scripts/ingest.py` to verify the data is in `data/kpis.json`.
2. Run `./scripts/refresh_and_deploy.sh` to push the new page to CF.
3. Open the live URL and confirm visually.

**Don't** skip the local preview. The CF deploy is fast but the round-trip is still 30+ seconds; preview locally first:
```bash
# Use port 8770+ to avoid collisions with other dev servers
cd /opt/data/profiles/strong-tower/workspace/strong-tower-dashboard/public
python3 -m http.server 8770
# Browser: http://localhost:8770
```

## 5. Enabling / disabling the cron

The cron is **PAUSED by default** (verified safe on 2026-07-01 — the manual dry-run left it in `paused` state).

**To enable:**
```bash
# Either via the cron tool
hermes cron resume 1223b798d21f
# Or via the dashboard UI
```
**Warning:** `cronjob run` (the manual-trigger tool) **silently re-enables** a paused job after the run. If you use it, always re-pause afterward with `cronjob pause`.

**To disable:**
```bash
hermes cron pause 1223b798d21f
```

**To change the schedule** (e.g. add a second weekly run, or move to 8am):
```bash
hermes cron edit 1223b798d21f --schedule "0 15 * * 1"  # 8am Pacific during DST
```

**⚠️ CRITICAL: The cron runs `ingest.py` but does NOT push to CF Pages.** The cron job writes `data/kpis.json` locally and then ends. The dashboard only updates when someone manually runs `npx wrangler pages deploy public` (or when GitHub auto-deploy is wired — see §7). As of v3.2.1, there is NO automatic dashboard refresh.

**The three manual steps to actually refresh the dashboard:**
```bash
# 1. Pull the new Zoom CSV into leads/phone_call_log.csv
# 2. Run the ingest
cd /opt/data/profiles/strong-tower/workspace/strong-tower-dashboard
python3 scripts/ingest.py
# 3. Deploy to CF Pages
npx --yes wrangler pages deploy public --project-name=strong-tower-dashboard
```

**To get true "freshes like everyday" automation:** wire §7 (GitHub auto-deploy) AND change the cron schedule. Then a push to `main` after the cron run will trigger CF Pages to rebuild from `data/kpis.json`. Without that, the cron is a no-op for the live page.

## 6. Rotating the GitHub token (for git push, optional)

The cron uses wrangler direct-upload, not git-push, so this only matters if you
also `git push` from this container (e.g. for code changes). The current token
is in `/opt/data/profiles/strong-tower/.git-credentials`.

**To rotate:**
1. Generate a new PAT at https://github.com/settings/tokens (classic, `repo` scope, expiry 90 days).
2. Update the file:
   ```bash
   echo "https://x-access-token:<NEW_TOKEN>@github.com" > /opt/data/profiles/strong-tower/.git-credentials
   chmod 600 /opt/data/profiles/strong-tower/.git-credentials
   ```
3. Test: `git ls-remote https://github.com/tenzinngodup/strong-tower-dashboard.git` (should return refs without 401).

## 7. Wiring GitHub auto-deploy (optional, for the future)

The current deploy path is **wrangler direct-upload** (no GitHub OAuth needed).
If you want **every `git push` to auto-deploy**, do this one-time setup in the
CF dashboard:

1. Go to `https://dash.cloudflare.com/.../pages/view/strong-tower-dashboard` → Settings → Builds.
2. Click "Connect to Git" → authorize CF to access the `tenzinngodup` GitHub account.
3. Select `tenzinngodup/strong-tower-dashboard`.
4. Set:
   - Production branch: `main`
   - Build command: *(empty)*
   - Build output directory: `public`
   - Root directory: *(empty)*
5. Click "Save and Deploy".

**After that**, you can change `scripts/refresh_and_deploy.sh` to use `git push origin main` instead of wrangler. The wrangler step is currently faster (5s vs 30-60s) and works without the OAuth, so I left it as-is.

## 8. Useful one-liners

```bash
# Re-run the whole pipeline + deploy, see live output
/opt/data/profiles/strong-tower/workspace/strong-tower-dashboard/scripts/refresh_and_deploy.sh

# Re-run a single source, no deploy
cd /opt/data/profiles/strong-tower/workspace/strong-tower-dashboard
python3 scripts/ingest.py --only hubspot

# Smoke test the static page (no server needed)
python3 tests/smoke_test.py disk

# View the deploy log
tail -30 /opt/data/profiles/strong-tower/workspace/dashboard_deploy.log

# Check the cron job state
hermes cron list | grep strongtower-dashboard

# Quick verify the live page
curl -sS -o /dev/null -w "HTTP %{http_code}\n" https://strong-tower-dashboard.pages.dev

# Regenerate the pipeline master CSV (after a new HubSpot batch, or after steven sends drafts)
python3 /opt/data/profiles/strong-tower/workspace/scripts/build_pipeline_status.py
# Then re-run the dashboard ingest + deploy
/opt/data/profiles/strong-tower/workspace/strong-tower-dashboard/scripts/refresh_and_deploy.sh
```
