# BACKUP_AND_RETENTION_V1 — frozen backup, restore and retention authority

> Frozen in `MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1`
> (2026-09-10). This document is the authority for what must be recoverable
> and what may never be deleted automatically. Machine-readable invariants:
> `ops/retention_policy_v1.json` (tested by
> `backend/tests/test_p9_production_readiness.py::test_retention_policy_invariants`).

## 1. Failure model — what must be recoverable

| Failure | What is lost | Recovery authority |
|---|---|---|
| home server dies (deb-serv) | running app + Postgres + legacy cache + /videos cache | Git repo (canonical on server, Mac mirror) + Postgres encrypted backup (server local + off-host copy on the ingest Mac) + B2 PROD media replicas; rebuild = redeploy + restore + agent re-sync |
| Postgres dies | all business/auth metadata | encrypted pg_dump backups (below); tested restore (§3) |
| Mac (ingest) dies | source vault + agent state + off-host DB copies | Photos/iCloud library is the media source authority; B2 holds the canonical application-media replicas; Git holds code/config |
| B2 account unavailable | cloud media replicas | Photos library + source vault can rebuild media via the existing ingest/migration machinery; B2 outage does NOT touch Postgres backups (server-local + off-host) |
| simultaneous B2 + Mac loss | cloud replicas + source authority | V1 residual risk: a SECOND independent off-site copy (different cloud or offline) is RECOMMENDED before any legacy deletion is ever executed — decision point for the human (see §5) |

## 2. Separate authorities (never conflated)

| Authority | Location | Backup approach |
|---|---|---|
| PostgreSQL business/auth metadata | deb-serv (loopback :5433) | encrypted pg_dump, scheduled + tested (§3/§4) |
| B2 canonical application-media replicas | diveanalyzer-prod-media (EU-Central 003, private) | IS the durable replica (§5); restore = re-commit from Photos/vault or re-GET from B2 |
| Photos/iCloud source authority | Mac Photos library + iCloud | never touched by Dive Analyzer; not backed up by it |
| macOS journals/runtime state | Mac /Users/Shared/services/data/... | small JSON state; rebuildable; not backed up in V1 |
| Git/configuration | canonical server repo + Mac bare mirror | existing multi-host redundancy |
| legacy cache/vault | server media/cache + media/videos; Mac vault | rebuildable cache (see retention §6) |
| science data | Mac highres/cache + Git manifests | science authority — OUT OF SCOPE, never touched |

## 3. PostgreSQL backup policy (FROZEN, live)

- Tool: `ops/postgres-backup.sh` (server).
- Frequency: daily 03:15 (cron installed as mcauchy) + ad-hoc runs.
- Format: `pg_dump -Fc` (custom, internally compressed).
- Encryption: AES-256-CBC + PBKDF2 via openssl; key file
  `~/backups/postgres/.backup_key` 0600 (never in Git, never printed).
- Readability gate: every backup is decrypted and parsed by
  `pg_restore --list` before it is counted as a backup.
- Retention: 14 daily + 8 weekly encrypted archives.
- Off-host replication: the ENCRYPTED archive is rsynced to the ingest Mac
  (`/Users/Shared/services/data/diveanalyzer-backups/postgres/`) with a
  dedicated SSH key restricted in the Mac's authorized_keys with
  `restrict,from="192.168.1.57"` (no pty/forwarding). Byte-identity verified
  via sha256 manifests.
- Live evidence (2026-09-10): backup 2.58 MB in 3 s (dump 1 s, encrypt <1 s,
  verify 1 s); off-host push OK; sha256 equal on both hosts.
- No plaintext secrets: the DB password exists only inside the Postgres
  container env; the backup uses container-local peer auth.

## 4. Restore procedure + restore test (PERFORMED, live)

- Tool: `ops/postgres-restore-test.sh` — NON-DESTRUCTIVE: decrypts the newest
  archive, restores into an ISOLATED throwaway `postgres:16` container
  (loopback-only random port 55432), then reconciles row counts for 14
  critical tables against the live production DB:
  - user/auth tables: app_users, user_credentials, user_sessions,
    user_diver_access, login_attempts, media_playback_grants
  - domain data: dives, divers
  - media backbone: media_blobs, media_revisions, caption_revisions,
    media_blob_locations, ingest_object_state
  - security_audit_log
  - plus: the media ownership chain (media_revisions → dives →
    user_diver_access OWNER → active app_users) and the count of verified
    PROD media_blob_locations must match production exactly.
- Never overwrites production: production DB is read-only to this script.
- Live evidence (2026-09-10): decrypt 0 s, restore 45 s, reconcile PASS
  (all 14 tables equal; ownership chain 15/15; verified PROD locations
  15/15), total 73 s.

## 5. B2 recovery semantics (failure model, no new provider)

B2 PROD (`diveanalyzer-prod-media`) is the **primary durable
application-media backbone**: content-addressed, private, least-privilege
keys (read-only playback key + write ingest key), versioning retained by
default (S3 deletes are soft hides; no automatic deletion exists anywhere).

V1 recovery assumption: **single-provider durable copy + Photos source +
legacy retained** is the current state. It is adequate for day-to-day
operation because every logical media revision also exists as an edited
rendition in the Photos/iCloud source, and legacy caches are retained.

RECOMMENDATION (real current risk, no action taken): before any future
`LEGACY_PHYSICAL_DELETION_READY = YES`, a SECOND INDEPENDENT replica of the
B2 media (a second cloud provider, or an offline/local copy on a different
failure domain) should exist, because after legacy deletion the B2 account
becomes the only place holding the canonical bytes for media whose Photos
assets may later be changed/deleted by the user. Decision intentionally left
to the human; no provider was created in P9.

## 6. Retention policy (FROZEN)

| Subject | Policy |
|---|---|
| B2 verified PROD media | retain indefinitely until an explicit logical-deletion policy exists; NO automatic delete/hide in V1 |
| caption revisions | append-only; never mutated/deleted |
| media revisions | append-only; never mutated/deleted |
| legacy transcoded cache | temporary/rebuildable; eviction only via the five existing bounded sanctioned sites; deletion candidates enumerated by dry-run only |
| legacy /videos directory | temporary/rebuildable icloudpd iCloud-original cache; deletion NOT authorized in P9 |
| Photos assets | never deleted or modified by Dive Analyzer |
| B2 delete/hide | NEVER automatic in V1; logical delete is DB-state only (§7) |
| science data | excluded from every product-reclamation calculation |

## 7. Logical delete design (DESIGN ONLY — no implementation deletes B2)

Future logical deletion MUST be layered:

1. **User-visible logical deletion / retirement** → DB state only
   (e.g. a `retired_at` state on MediaRevision / Dive rows; playback and UI
   exclude retired media; B2 rows untouched). Reversible.
2. **Physical B2 purge** → a SEPARATE, DELAYED, operator-controlled
   lifecycle step (batch manifest, human approval, retention window,
   audit-logged), implemented only in a later packet with its own
   safety firewall. Nothing in V1 performs it.

Rationale: deletes must never be coupled to the user gesture; a mistaken
"delete" must be recoverable until the delayed purge window passes.

## 8. Restore test cadence

- After every restore-relevant schema change and at least monthly: run
  `ops/postgres-restore-test.sh` (isolated container; ~75 s).
- Any policy change to this document requires a fresh restore test before
  it is considered frozen.
