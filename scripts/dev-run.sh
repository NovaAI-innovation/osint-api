#!/usr/bin/env bash
# scripts/dev-run.sh
# Local-only dev quickstart: run the gateway (and minimal deps) without docker.
#
# What it does:
#   1. Spins up postgres + redis via docker (one-shot, no project network).
#   2. Starts the gateway on http://localhost:8000 with SQLite (no DB needed
#      for the free-search dev endpoint and basic POST /v1/profiles testing).
#   3. Tails logs; Ctrl-C cleans up.
#
# Usage:
#   ./scripts/dev-run.sh
#
# Env:
#   USE_POSTGRES=1   spin up postgres+redis in docker and point gateway at them
#                    (default: SQLite-only, no docker required)
#   OSINT_ENABLE_FREE_SEARCH=true  (default)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cleanup() {
  echo
  echo "[dev-run] shutting down..."
  [ -n "${GATEWAY_PID:-}" ] && kill "$GATEWAY_PID" 2>/dev/null || true
  if [ "${USE_POSTGRES:-0}" = "1" ]; then
    docker rm -f osint-dev-pg osint-dev-redis >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

if [ "${USE_POSTGRES:-0}" = "1" ]; then
  echo "[dev-run] starting postgres + redis in docker"
  docker rm -f osint-dev-pg osint-dev-redis >/dev/null 2>&1 || true
  docker run -d --name osint-dev-pg -e POSTGRES_PASSWORD=password -e POSTGRES_DB=osint_db -p 5432:5432 postgres:15-alpine >/dev/null
  docker run -d --name osint-dev-redis -p 6379:6379 redis:7-alpine >/dev/null
  echo "[dev-run] waiting for postgres"
  for i in $(seq 1 20); do
    if docker exec osint-dev-pg pg_isready -U postgres >/dev/null 2>&1; then break; fi
    sleep 1
  done
  export DB_HOST=localhost DB_PORT=5432 DB_NAME=osint_db DB_USER=postgres DB_PASSWORD=password
  export REDIS_URL=redis://localhost:6379
  export DATABASE_URL="postgresql+psycopg2://postgres:password@localhost:5432/osint_db"
  echo "[dev-run] applying schema"
  docker exec -i osint-dev-pg psql -U postgres -d osint_db < db/schema.sql
else
  echo "[dev-run] using sqlite in-memory (USE_POSTGRES=0)"
  export DATABASE_URL="sqlite:///./osint_dev.db"
fi

export OSINT_ENABLE_FREE_SEARCH="${OSINT_ENABLE_FREE_SEARCH:-true}"
export LOG_LEVEL=info

if [ ! -d venv ]; then
  echo "[dev-run] creating venv and installing deps"
  python3 -m venv venv
  ./venv/bin/pip install -q -r gateway/requirements.txt -r requirements-test.txt
fi

echo "[dev-run] starting gateway at http://localhost:8000  (free-search=$OSINT_ENABLE_FREE_SEARCH)"
echo "[dev-run] open the HTML UI:    $ROOT/web/index.html"
echo "[dev-run] free-search example: curl 'http://localhost:8000/dev/free-search?target_type=username&target=alice'"
echo
./venv/bin/uvicorn gateway.main:app --app-dir "$ROOT" --host 0.0.0.0 --port 8000 --reload &
GATEWAY_PID=$!
wait $GATEWAY_PID
