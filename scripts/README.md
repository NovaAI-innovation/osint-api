# scripts/db-shell.sh

Spawn an interactive psql session against the OSINT-api Postgres container on the VPS.

## Quick start

```sh
# interactive
./scripts/db-shell.sh

# one-shot query
./scripts/db-shell.sh -c "SELECT count(*) FROM jobs;"

# redirect a SQL file
./scripts/db-shell.sh < all-tables-and-counts.sql
```

## Defaults

- `VPS_HOST`  - 187.77.100.89
- `SSH_USER`  - root
- `SSH_KEY`   - `~/.ssh/id_ed25519`
- `DB_USER`   - postgres
- `DB_NAME`   - osint_db

Override at the call site, e.g. `VPS_HOST=staging.example.com ./scripts/db-shell.sh`.

## Windows

Run from WSL or git-bash. A PowerShell variant can be added if needed.

## What you can query

After deploy the OSINT-api stack creates tables from `db/schema.sql`:

- `users`, `user_credits`, `api_keys`
- `profiles`
- `jobs`, `job_results`
- `entities`, `entity_relationships`
- `invoices`

Useful starter queries:

```sql
\dt
\d jobs

SELECT id, target_type, target_value, status, depth, parent_job_id, updated_at
FROM jobs ORDER BY updated_at DESC LIMIT 20;

SELECT tool_name, count(*), avg(status_code)
FROM job_results GROUP BY tool_name;

SELECT depth, status, count(*)
FROM jobs GROUP BY depth, status ORDER BY depth, status;
```
