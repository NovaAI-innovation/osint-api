# OSINT-api

API wrapper for a collection of OSINT tools that facilitates the collection of personal information.

The API exposes:

- `POST /v1/profiles` - create an identity-resolution profile (deducts credits).
- `GET  /v1/jobs/{id}` - read job status and collected tool results.
- `POST /v1/credits/purchase` - create a payment invoice (PayPal / BTCPay).
- `GET  /dev/free-search` - **dev-only** synchronous mock OSINT lookup (no auth, no DB, no credits).
- `GET  /healthz` - gateway liveness probe.

The full machine-readable contract lives in [`.a0proj/osint-api-spec.yaml`](.a0proj/osint-api-spec.yaml).

## Repo layout

| Path | What it is |
|---|---|
| `gateway/`        | FastAPI gateway. Public REST surface, auth, credits, queues to Redis. |
| `worker/`         | Background consumer of the Redis `osint_jobs` queue. Runs tools as subprocesses. |
| `orchestrator/`   | Polls completed jobs, extracts entities, chains child jobs up to `max_depth`. |
| `billing/`        | PayPal + BTCPay webhooks, invoice settlement. |
| `shared/db.py`    | SQLAlchemy models + engine/session factory shared by every service. |
| `db/schema.sql`   | Postgres schema, mounted into the container on first boot. |
| `web/`            | Static HTML dev console + nginx config. |
| `docs/`           | Architecture, security, data model (blueprint). |
| `ops/`            | Prometheus scrape config, Loki config, monitoring plan. |
| `infrastructure/` | Container infrastructure spec (`compose.spec.yml`). |
| `scripts/`        | Deploy + dev quickstart + DB shell helper. |
| `tests/`          | Pytest suite (CI runs these). |

## Quickstart - full Docker stack

Requires Docker + the Compose plugin on the host.

```sh
docker compose up -d --build

# then open:
#   http://localhost:8080   HTML dev console (Free Dev Search + Real API)
#   http://localhost:8000   API gateway (Swagger UI at /docs)
#   http://localhost:9090   Prometheus
```

## Quickstart - gateway only, no Docker (fastest)

```sh
./scripts/dev-run.sh
# open web/index.html in your browser
```

The dev script runs the gateway with SQLite (no docker needed for the dev
search endpoint). Set `USE_POSTGRES=1 ./scripts/dev-run.sh` to spin up
postgres + redis containers alongside.

## Deploy to a VPS

`scripts/deploy.sh` is idempotent and works on a fresh Ubuntu/Debian host.

```sh
# On the VPS, as root:
REPO_URL=git@github.com:your-org/osint-api.git \
BRANCH=master \
OSINT_ENABLE_FREE_SEARCH=false \
./scripts/deploy.sh
```

It installs Docker if missing, clones or pulls the repo, runs
`docker compose up -d --build`, waits for the gateway `/healthz`, and prints
URLs.

## Dev-mode `/dev/free-search`

This endpoint is for local development and CI only - no API key, no
credits, no DB writes, no Redis, no auth. The response is a deterministic
mock keyed by `(target_type, target)` so the HTML UI and frontend tests have
a stable shape.

Disable in any non-dev environment by setting the env var:

```
OSINT_ENABLE_FREE_SEARCH=false
```

When disabled the route returns `404 Not Found`.

### Examples

```sh
# GET
curl 'http://localhost:8000/dev/free-search?target_type=username&target=alice'

# POST
curl -X POST http://localhost:8000/dev/free-search \
  -H 'Content-Type: application/json' \
  -d '{"target_type":"email","target":"alice@example.com"}'
```

## Tests

```sh
pip install -r requirements-test.txt
pip install -r gateway/requirements.txt
pytest -v
```

The CI workflow at `.github/workflows/test.yml` does exactly this on
push / PR.

## Configuration reference

| Service        | Env var                       | Default                                |
|----------------|-------------------------------|----------------------------------------|
| gateway        | `DATABASE_URL` / `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | assembled from `DB_*` |
| gateway        | `REDIS_URL`                   | `redis://localhost:6379`               |
| gateway        | `OSINT_ENABLE_FREE_SEARCH`    | `true` - **set `false` in prod**       |
| gateway        | `LOG_LEVEL`                   | `info`                                 |
| worker         | `REDIS_URL`                   | `redis://localhost:6379`               |
| worker         | `WORKER_CONCURRENCY`          | `2`                                    |
| billing        | `BTCPAY_WEBHOOK_SECRET`       | `test_secret` (dev)                    |
| billing        | `PAYPAL_*`                    | mock values (dev)                      |

## Security note

The default `docker-compose.yml` ships with weak dev-only credentials
(`POSTGRES_PASSWORD=password`, mock PayPal/BTCPay keys). **Rotate all of
these before exposing the stack to the internet.** See
[`docs/security-policy.md`](docs/security-policy.md).
