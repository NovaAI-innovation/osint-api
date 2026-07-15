#!/usr/bin/env sh
# web/entrypoint.sh
#
# Selects between two nginx configs based on OSINT_API_PROXY:
#   OSINT_API_PROXY=1  -> web/nginx-proxy.conf  (reverse-proxy mode, single origin)
#   OSINT_API_PROXY=0  -> web/nginx.conf        (static-only, cross-origin to gateway)
#
# Defaults to 0 (cross-origin / CORS-mode) which matches the docker-compose
# default and the development quickstart.

set -eu

MODE="${OSINT_API_PROXY:-0}"

if [ "$MODE" = "1" ]; then
  echo "[nginx] OSINT_API_PROXY=1 -> using nginx-proxy.conf (reverse-proxy mode)"
  cp /etc/nginx/conf.available/nginx-proxy.conf /etc/nginx/conf.d/default.conf
else
  echo "[nginx] OSINT_API_PROXY=0 -> using nginx.conf (static-only / CORS mode)"
  cp /etc/nginx/conf.available/nginx.conf /etc/nginx/conf.d/default.conf
fi

# Test config and start nginx.
nginx -t
exec nginx -g 'daemon off;'
