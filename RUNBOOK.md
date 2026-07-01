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
| `leads` | Local CSVs in `workspace/leads/*.csv` | Bad row data (e.g. `icp` column has non-standard values) | Edit the CSV, re-run |
| `hubspot` | Composio MCP → HubSpot | API token rotated, account 403 | Update `COMPOSIO_API_KEY` in `.env` |
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
cd public && python3 -m http.server 8765
# Browser: http://localhost:8765
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
```
