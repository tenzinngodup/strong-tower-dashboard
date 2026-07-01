# Strong Tower Owner Dashboard

Weekly executive dashboard for **Strong Tower Cleaning Services** (Portland, OR).

A static site that auto-updates from a weekly cron run. The owner opens one URL
and sees: pipeline status, marketing cadence, site traffic, sales funnel, and
auto-generated action items.

## What it does

- Pulls data from 4 sources (HubSpot, Blotato, GA4, local lead CSVs)
- Computes a small set of rollups once
- Writes two JSON files the static site renders
- Designed to update **weekly** (per Phase 0 decision)

## Project layout

```
strong-tower-dashboard/
├── README.md
├── data/
│   ├── SCHEMA.md         # field-level documentation
│   ├── snapshot.json     # raw inputs from each source (generated)
│   └── kpis.json         # computed rollups (generated)
├── scripts/
│   ├── ingest.py         # main entrypoint — runs all sources, writes JSON
│   ├── sources/
│   │   ├── leads.py      # local CSVs in workspace/leads/
│   │   ├── hubspot.py    # Composio MCP → HubSpot
│   │   ├── blotato.py    # REST API for posting cadence
│   │   └── ga4.py        # Composio MCP → Google Analytics
│   ├── compute/
│   │   └── kpis.py       # snapshot → kpis rollups
│   └── lib/
│       └── dashboard_lib.py
├── public/               # static site (Phase 2)
└── tests/                # smoke tests (Phase 2)
```

## Quick start

```bash
cd /opt/data/profiles/strong-tower/workspace/strong-tower-dashboard
python3 scripts/ingest.py
```

This will:
1. Run all 4 sources (each in its own try/except)
2. Write `data/snapshot.json` and `data/kpis.json`
3. Print a summary line: "X ok, Y failed (of 4 sources)"

**One source at a time (faster iteration):**
```bash
python3 scripts/ingest.py --only leads   # or hubspot / blotato / ga4
```

**Dry run (don't write files):**
```bash
python3 scripts/ingest.py --dry-run --print kpis
```

## Secrets

The scripts read from `/opt/data/profiles/strong-tower/.env`:
- `COMPOSIO_API_KEY` — for HubSpot + GA4 (MCP)
- `BLOTATO_API_KEY` — for social posting cadence
- `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` — for wrangler direct-upload deploys

All are already in your `.env`. No new secrets are required.

## Deployment

Production: `https://strong-tower-dashboard.pages.dev`
CF Pages project: `57d74733-29fb-458c-843e-f9c3951c2ad2` (account `6267da94e5b26778c479aebcae85de2e`)

Two deploy paths, in order of recommendation:

1. **Direct upload via wrangler** (current cron path — `scripts/refresh_and_deploy.sh`)
   - Fast (~5s), no GitHub OAuth needed
   - Cron job: `1223b798d21f` — `strongtower-weekly-dashboard` (Mon 14:00 UTC = 7am Pacific, currently PAUSED)

2. **GitHub auto-deploy** (optional, one-time setup in CF dashboard)
   - See `RUNBOOK.md` section 7 for setup steps
   - Once enabled, every `git push origin main` auto-deploys

## Validation status (Phase 2)

- **Phase 1** (data foundation): 4/4 sources return ok. Numbers validated against
  the 2026-06-19 biweekly report within ±5%. See `data/SCHEMA.md` for full details.
- **Phase 2** (static page): built and visually verified via headless browser.
  All 5 sections render with real data, mobile-responsive at 720px and 420px
  breakpoints, no console errors.

| Metric | Biweekly (Jun 5-19) | Dashboard (Jul 1) | Status |
|---|---|---|---|
| Active leads | 45 | 44 | ✓ |
| Contacted | 26 | 25 | ✓ |
| Won | 0 | 0 | ✓ |
| IG posts (7d) | (n/a) | 9 | matches HEARTBEAT cadence |
| LinkedIn posts (7d) | "29 in 15d" | 18 | ✓ |
| Sessions (7d) | 18 | 21 | ✓ (within 15%) |
| Archived HubSpot deals | 53 | 53 | ✓ exact match |

**New finding the dashboard surfaces:** HubSpot currently has **0 active
deals**. Combined with the biweekly report's "0 closes" this means the
outreach → deal pipeline is not yet active in HubSpot. The 25 contacted
leads have not yet been moved to Walkthrough/Quoted stages in the CRM.

## What's next

- **Phase 3:** Deploy to Cloudflare Pages at `dashboard.strongtowercs.com`
  (connect GitHub repo, add DNS, done) — ✅ done at strong-tower-dashboard.pages.dev
- **Phase 4:** Wire up the weekly cron (Monday 7am Pacific) so the dashboard
  auto-updates — ✅ done, cron `1223b798d21f` (currently PAUSED)
- **Phase 5:** Polish (link from biweekly email, owner walkthrough) — ✅ done

See the planning notes in the chat history for the full phase breakdown.
For operational tasks (rotating secrets, debugging, adding KPIs), see
[`RUNBOOK.md`](./RUNBOOK.md).

## Local preview

```bash
# Terminal 1: serve the static site
cd public && python3 -m http.server 8765

# Terminal 2: regenerate data
python3 scripts/ingest.py
cp data/kpis.json public/kpis.json

# Browser: open http://localhost:8765/index.html
```

Or run the smoke test (no server needed — uses file://):
```bash
python3 tests/smoke_test.py disk
```
