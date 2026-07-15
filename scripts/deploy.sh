#!/usr/bin/env bash
# scripts/deploy.sh
# One-shot production deploy of the OSINT-api stack on a fresh Linux VPS.
#
# What it does (idempotent):
#   1. Ensures docker + docker compose plugin are installed.
#   2. Clones the repo (or pulls latest) into /opt/osint-api.
#   3. Brings the full stack up with `docker compose up -d --build`.
#   4. Waits for the gateway to become healthy and prints URLs.
#
# Usage:
#   ./scripts/deploy.sh                       # default: github.com/<owner>/<repo>.git, branch=master
#   REPO_URL=git@github.com:you/osint-api.git BRANCH=main ./scripts/deploy.sh
#   SKIP_DOCKER_INSTALL=1 ./scripts/deploy.sh # docker is already installed
#
# Env:
#   REPO_URL              default: <placeholder - set this>
#   BRANCH                default: master
#   DEPLOY_DIR            default: /opt/osint-api
#   SKIP_DOCKER_INSTALL   default: 0
#   OSINT_ENABLE_FREE_SEARCH default: false  (production should disable dev endpoint)

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/NovaAI-innovation/osint-api.git}"
BRANCH="${BRANCH:-master}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/osint-api}"
SKIP_DOCKER_INSTALL="${SKIP_DOCKER_INSTALL:-0}"
FREE_SEARCH="${OSINT_ENABLE_FREE_SEARCH:-false}"

log() { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "must run as root (use sudo $0)"
[ -n "${REPO_URL}" ] || fail "REPO_URL not set"

# 1. Docker
if [ "$SKIP_DOCKER_INSTALL" != "1" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    log "installing docker"
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
  fi
  if ! docker compose version >/dev/null 2>&1; then
    log "installing docker compose plugin"
    apt-get install -y docker-compose-plugin || true
  fi
fi
command -v docker >/dev/null 2>&1 || fail "docker not installed and SKIP_DOCKER_INSTALL=1; aborting"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin missing"

# 2. Repo
if [ ! -d "$DEPLOY_DIR" ]; then
  log "cloning $REPO_URL -> $DEPLOY_DIR"
  mkdir -p "$(dirname "$DEPLOY_DIR")"
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$DEPLOY_DIR"
elif [ -d "$DEPLOY_DIR/.git" ] && git -C "$DEPLOY_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "updating existing clone at $DEPLOY_DIR"
  git -C "$DEPLOY_DIR" fetch --all --prune
  git -C "$DEPLOY_DIR" checkout "$BRANCH"
  git -C "$DEPLOY_DIR" pull --ff-only
else
  warn "$DEPLOY_DIR exists but is not a clean git repo (likely a partial clone). Resetting."
  rm -rf "$DEPLOY_DIR"
  mkdir -p "$(dirname "$DEPLOY_DIR")"
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

# 3. Compose up
export OSINT_ENABLE_FREE_SEARCH="$FREE_SEARCH"
log "docker compose up -d --build (OSINT_ENABLE_FREE_SEARCH=$FREE_SEARCH)"
docker compose up -d --build

# 4. Wait for gateway health
log "waiting for gateway /healthz"
for i in $(seq 1 30); do
  if curl -fsS http://localhost:8000/healthz >/dev/null 2>&1; then
    log "gateway healthy after ${i}s"
    break
  fi
  sleep 2
done

# 5. Status
log "stack status:"
docker compose ps --format 'table {{.Name}}\t{{.State}}\t{{.Ports}}'
cat <<EOF

URLs (default):
  API gateway : http://localhost:8000    (Swagger UI: /docs)
  Web UI      : http://localhost:8080
  Prometheus  : http://localhost:9090
  Billing     : http://localhost:8081
  Postgres    : postgresql://postgres:password@localhost:5432/osint_db (dev only)

Next steps:
  - Set strong POSTGRES_PASSWORD and rotate the API keys (PAYPAL/BTCPay) in .env or compose env.
  - Open http://localhost:8080 and try the Free Dev Search tab (if enabled).
  - For a shell on Postgres: ./scripts/db-shell.sh
EOF
