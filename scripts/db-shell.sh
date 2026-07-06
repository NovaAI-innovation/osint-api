#!/usr/bin/env bash
# db-shell.sh: open an interactive psql session against the OSINT-api
# postgres container on the VPS, or run a one-shot SQL statement.
#
# Usage:
#   ./scripts/db-shell.sh                    # interactive psql prompt
#   ./scripts/db-shell.sh -c "SELECT count(*) FROM jobs;"
#   ./scripts/db-shell.sh < queries.sql       # redirect a script in
#
# Env overrides (all optional):
#   VPS_HOST  default 187.77.100.89
#   SSH_USER  default root
#   SSH_KEY   default ~/.ssh/id_ed25519
#   DB_USER   default postgres
#   DB_NAME   default osint_db

set -euo pipefail

VPS_HOST="${VPS_HOST:-187.77.100.89}"
SSH_USER="${SSH_USER:-root}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-osint_db}"

REMOTE="cd /opt/osint-api && docker compose exec -T postgres psql -U '$DB_USER' -d '$DB_NAME'"

if [ "$#" -ge 2 ] && [ "${1:-}" = "-c" ]; then
  shift
  ARGS=$(printf '%q ' "$@")
  exec ssh -T -i "$SSH_KEY" "$SSH_USER@$VPS_HOST" \
    "$REMOTE -c $ARGS"
elif [ "$#" -eq 0 ] && [ -t 1 ]; then
  exec ssh -tt -i "$SSH_KEY" "$SSH_USER@$VPS_HOST" "$REMOTE"
elif [ "$#" -eq 0 ]; then
  exec ssh -T -i "$SSH_KEY" "$SSH_USER@$VPS_HOST" "$REMOTE"
else
  echo "db-shell: use -c to run a SQL statement, or omit args for interactive use" >&2
  exit 2
fi
