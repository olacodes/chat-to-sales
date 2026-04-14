#!/usr/bin/env bash
# =============================================================================
# ChatToSales — Deploy / Update Script
# Run as the 'deploy' user on the Hetzner server.
#
# Usage:
#   bash deploy/deploy.sh              # pull latest main and redeploy
#   bash deploy/deploy.sh --no-build   # restart without rebuilding image
# =============================================================================
set -euo pipefail

APP_DIR="/opt/chattosales"
# --env-file makes Compose use .env.prod for ${VAR} interpolation in the YAML
# (distinct from env_file: which injects vars into container environments)
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"

NO_BUILD=false
if [[ "${1:-}" == "--no-build" ]]; then
    NO_BUILD=true
fi

cd "$APP_DIR"

# ── Validate env file ─────────────────────────────────────────────────────────
if [[ ! -f .env.prod ]]; then
    echo "ERROR: .env.prod not found in $APP_DIR"
    echo "       Copy .env.prod.example, fill in secrets, then re-run."
    exit 1
fi

# Warn about any CHANGE_ME values left in the file
if grep -q "CHANGE_ME" .env.prod; then
    echo "ERROR: .env.prod still contains placeholder values (CHANGE_ME)."
    echo "       Fill in all secrets before deploying."
    exit 1
fi

echo "▶ Pulling latest code..."
git pull --ff-only

if [[ "$NO_BUILD" == "false" ]]; then
    echo "▶ Building Docker images..."
    $COMPOSE build --pull
fi

echo "▶ Running database migrations..."
$COMPOSE run --rm migrate

echo "▶ Starting / updating services..."
$COMPOSE up -d --remove-orphans

echo "▶ Removing dangling images..."
docker image prune -f

echo ""
echo "✅ Deployment complete. Container status:"
$COMPOSE ps
