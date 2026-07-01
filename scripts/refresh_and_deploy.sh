#!/usr/bin/env bash
# Strong Tower Dashboard — refresh + deploy wrapper.
#
# What this does:
#   1. Re-runs the ingest pipeline (regenerates data/*.json + public/kpis.json)
#   2. Deploys the static site to Cloudflare Pages via wrangler (direct upload)
#   3. Verifies the live URL returns HTTP 200
#
# Designed to be called from a cron session. Exits non-zero on any failure
# so the cron runner reports the failure back to you.
#
# Usage:
#   ./scripts/refresh_and_deploy.sh
#
# Environment (loaded from /opt/data/profiles/strong-tower/.env):
#   CLOUDFLARE_API_TOKEN    required (for wrangler)
#   CLOUDFLARE_ACCOUNT_ID   required
#   GITHUB_TOKEN            optional (only needed if you switch to git-push)
#
# Side effects:
#   - Overwrites data/snapshot.json, data/kpis.json, public/kpis.json
#   - Uploads public/ to Cloudflare Pages
#   - Returns the new deployment URL on stdout (for cron logs)

set -euo pipefail

PROJ="/opt/data/profiles/strong-tower/workspace/strong-tower-dashboard"
ENV_FILE="/opt/data/profiles/strong-tower/.env"
DEPLOY_LOG="/opt/data/profiles/strong-tower/workspace/dashboard_deploy.log"

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$DEPLOY_LOG"
}

# ── 0. Load env ──────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  log "FATAL: $ENV_FILE not found"
  exit 2
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  log "FATAL: CLOUDFLARE_API_TOKEN and/or CLOUDFLARE_ACCOUNT_ID missing in $ENV_FILE"
  exit 2
fi

export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID
export NEXTAUTH_URL PATH HOME
export GIT_CONFIG_GLOBAL="/opt/data/profiles/strong-tower/.gitconfig"

cd "$PROJ"
log "== refresh_and_deploy started =="

# ── 1. Ingest ────────────────────────────────────────────────
log "Step 1/3: running scripts/ingest.py"
# Ingest's default --print is "both", which is what we want for the cron log
# (the operator wants to see source-status per run). Output goes to the
# deploy log so the cron runner gets a clean digest.
if ! python3 scripts/ingest.py >>"$DEPLOY_LOG" 2>&1; then
  log "FATAL: ingest failed (see $DEPLOY_LOG for details)"
  exit 1
fi

# Sanity check: kpis.json must have content
KPI_SIZE=$(stat -c%s data/kpis.json 2>/dev/null || echo 0)
if [ "$KPI_SIZE" -lt 100 ]; then
  log "FATAL: data/kpis.json is suspiciously small ($KPI_SIZE bytes)"
  exit 1
fi
log "  kpis.json: $KPI_SIZE bytes"

# ── 2. Deploy to Cloudflare Pages ───────────────────────────
log "Step 2/3: deploying public/ to Cloudflare Pages"
DEPLOY_OUTPUT=$(npx --yes wrangler pages deploy public \
  --project-name=strong-tower-dashboard \
  --branch=main \
  --commit-dirty=true 2>&1 | tee -a "$DEPLOY_LOG")

# wrangler prints "Deployment complete! Take a peek over at https://<id>.strong-tower-dashboard.pages.dev"
DEPLOY_URL=$(echo "$DEPLOY_OUTPUT" | grep -oE 'https://[a-z0-9]+\.strong-tower-dashboard\.pages\.dev' | tail -1)
if [ -z "$DEPLOY_URL" ]; then
  log "FATAL: wrangler did not return a deployment URL"
  log "  last 10 lines of wrangler output:"
  echo "$DEPLOY_OUTPUT" | tail -10 | sed 's/^/    /' | tee -a "$DEPLOY_LOG"
  exit 1
fi
log "  deployed: $DEPLOY_URL"

# ── 3. Verify the page is reachable ─────────────────────────
log "Step 3/3: verifying deploy"
HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 30 \
  "https://strong-tower-dashboard.pages.dev" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "200" ]; then
  log "FATAL: production URL returned HTTP $HTTP_CODE (expected 200)"
  exit 1
fi
log "  production URL HTTP $HTTP_CODE ✓"

log "== refresh_and_deploy complete: $DEPLOY_URL =="
echo "$DEPLOY_URL"   # last line is what the cron runner reports
