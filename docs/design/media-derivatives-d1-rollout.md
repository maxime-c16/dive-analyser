# D1 rollout: `add_media_derivatives.sql` (manual SQL, no secrets)

D1 is publish- and read-inert: the migration adds one empty ledger table
plus four nullable columns. Old code boots on the new schema (it never
touches the new objects); new code reads nothing new yet. Rollback = code
rollback only (`ci/ship.sh server --ref <prev>`); NEVER roll back this
migration (drops would destroy ledger history later slices depend on).

## Preflight (from any checkout that can reach GitHub + the server)

```bash
git fetch origin
git log --oneline origin/master -3          # confirm the D1 merge SHA
ci/ship.sh status                            # live server/mac SHAs vs origin/master
```

Gate (informational; the migration needs no gate, the deploy does):

```bash
ci/gate.sh backend                           # isolated SQLite suite, zero failures
CALENDAR_TEST_DATABASE_URL=postgresql://<user>@<host>:<port>/calendar_test_<name> \
  ci/postgres.sh                             # includes the D1 PG evidence file
```

Replace `<user>@<host>:<port>/calendar_test_<name>` with the disposable PG
URL (CI service or a local `calendar_test_*` database). No production
database name ever appears here.

## Apply (manual, BEFORE `ci/ship.sh server`)

`ci/ship.sh` never applies SQL. Run from a machine with Postgres access
(usually `deb-serv` over ssh; copy the file, never secrets):

```bash
# 1. Copy the migration to the DB host (example path; any scratch dir works)
scp backend/migrations/add_media_derivatives.sql <db-host>:/tmp/add_media_derivatives.sql

# 2. On the DB host, apply with psql (re-run safe: idempotent)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /tmp/add_media_derivatives.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /tmp/add_media_derivatives.sql   # second run must succeed

# 3. Verify (expected: 1 table, 4 columns, 0 derivative rows)
psql "$DATABASE_URL" -c "\d media_derivatives"
psql "$DATABASE_URL" -c "SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_name IN ('media_cache_entries','media_jobs') AND column_name IN ('source_blob_sha256','transform_version','lease_token','finalized_slots') ORDER BY 1,2;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM media_derivatives;"
```

`$DATABASE_URL` is the runtime env on the DB host (never pasted into chat
or committed). Expected: `media_derivatives` with the `uq_media_derivative_identity`
unique + `ck_media_derivative_role/status` checks, the four columns present
and NULLABLE, count `0`.

## Deploy

```bash
ci/ship.sh server --dry-run    # read every warning; abort on unexpected lines
ci/ship.sh server              # build, swap, health-check, publish
```

No Mac deploy needed (no `mac-agent/` change).

## Postflight (on the deployed server)

```bash
# New code boots and serves exactly as before (no new routes/jobs)
ci/ship.sh status
# Ledger empty, columns NULL (proves inertness, not absence of schema)
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM media_derivatives;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM media_cache_entries WHERE source_blob_sha256 IS NOT NULL OR transform_version IS NOT NULL;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM media_jobs WHERE lease_token IS NOT NULL OR finalized_slots IS NOT NULL;"
```

All three counts must be `0`. Any nonzero row before D3 ships means an
unreviewed writer touched the ledger — stop and report to Maxime.

## Backout

- Code: `ci/ship.sh server --ref <previous-sha>` (standard; old code
  ignores the new table/columns).
- Schema: no backout. The additive schema stays; old code keeps working on
  it indefinitely.
