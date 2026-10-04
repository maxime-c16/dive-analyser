# MEDIA_BACKBONE_P8_ACCELERATED_PRODUCTIONIZATION_V1 — Durable Audit

> Task packet `MEDIA_BACKBONE_P8_ACCELERATED_PRODUCTIONIZATION_V1`.
> Executed 2026-09-10 on top of the accepted P7 state (canonical HEAD
> `b8e5de930388595b4cc8d8812d77fe2968c4df20`, fresh-verified on server + Mac).
> Branch `media-backbone-p8-productionization-v1`; ff-merged into
canonical `uiux-overhaul-pro-app` (final HEAD `61d1703`).
> Verdicts: `P8_PRODUCTIONIZATION_GREEN`, `EXTERNAL_ACCESS_PROVIDER_GATE`,
> `LEGACY_DECOMMISSION_NOT_READY`.
> Absolute counters: **B2 delete/hide = 0; legacy media deleted = 0;
> Photos delete = 0; science mutated = NO; secrets in Git = NO.**

## 1. Fresh preflight (verified)

- Canonical repo `mcauchy@192.168.1.57:~/dive-analyser` @ `b8e5de9`
  (branch `uiux-overhaul-pro-app`); Mac mirror in sync; the local
  `~/.perso/diveanalyzer` dir remains a non-git reference slice.
- Deployed backend healthy; `USER_AUTH_ENABLED=true`,
  `B2_PLAYBACK_CANARY_ENABLED=true` (docker env, live-read).
- Mac production runtime config (`/Users/Shared/services/data/diveanalyzer/
  state/config.yaml`): `object_store.enabled=true`, `dual_write.enabled=true`,
  `dual_write.continuous_new_ingest=true`, `migration.enabled=true`,
  vault `enabled=true`.
- DB: 15 media_revisions / 15 verified PROD locations / 15 blobs /
  25 ledger rows (all DB_COMMITTED) / 1 real user (maxime → diver 1 OWNER).

## 2. P8-A — continuous natural ingest

`CONTINUOUS_NATURAL_INGEST = NOT_OBSERVED_YET`. No legitimate new
captioned clip entered the legacy pipeline during the P8 window; per the
packet no synthetic production data was created to force the gate. The
continuous dual-write path stayed armed the whole time (config verified
live, event-driven trigger unchanged). Legacy decommission readiness is
consequently NOT_READY (§35 condition 1 unmet). Nothing blocked.

## 3. P8-B — multi-user auth model + provisioning

V1 model unchanged and preserved: one AppUser → one or more explicit
`UserDiverAccess` OWNER rows → deterministic media→diver chain
(`MediaRevision.video_uuid → dives.video_uuid UNIQUE → diver_id`). No
coach/team/club/admin-over-all-media role invented (no domain evidence).

New **server-local operator CLI** `backend/scripts/manage_user.py` (packet
§8 — deliberately NOT the mac-agent X-API-Key authority, deliberately NOT a
web admin role):

    create-user / disable / enable / reset-password / bind-diver /
    unbind-diver / revoke-sessions / list-users / list-access / list-divers

Contract: passwords only via getpass (typed twice, ≥10 chars, Argon2id);
disable blocks login AND revokes every live session; reset-password
revokes every live session; users are never deleted by the CLI; lists
carry no secrets; every mutation appends a `security_audit_log` row.
No public self-registration exists; a diver object implies no account.

Password reset is the operator-assisted flow required by packet §9
(getpass TTY, Argon2id, sessions revoked, no argv/password logs). No
email reset system in P8, per packet.

## 4. P8 live production proofs (real Postgres + real nginx)

Synthetic world created live (2 divers, 2 dives, 2 users), fully removed
after the tests (audit rows retained intentionally).

- **IDOR matrix through production nginx (`https://…:6443`)** —
  A→A 200, A→B 404, B→B 200, B→A 404, B→maxime 404 (legacy route),
  A→maxime B2 play 404, anonymous 401, foreign-Origin login 403.
- **§44 disable live test** (synthetic user): pre-me 200 → CLI disable →
  existing session loses access (me 401, own media 401) → login denied
  401 → (synthetic user later deleted as cleanup; audit retained).
- **§45 password reset live test** (synthetic user): old session revoked
  (me 401), old password 401, new password 200, new session me 200.
  No secret appeared in any output/log.
- **Login rate limit live**: 10 wrong attempts from one source → 429 on
  the 11th; `login_rate_limited` audit row written with
  `{"identifier_present": true}` (no identifier stored).
- **§25 metrics live**: `GET /api/v1/auth/metrics` (authenticated) returns
  login_success/login_failure/login_rate_limited/session_revocations +
  active_sessions_approx (DB count). In-process per worker, privacy-safe.

## 5. New production defect found and fixed (ingress)

**nginx Host forwarding stripped the port**: `proxy_set_header Host $host`
sends `Host: host-without-port`, so the backend's P6 Origin validation
could not reconstruct `https://<host>:<port>` candidates; a same-origin
browser login POST failed with 403 unless the exact origin string was in
`CORS_ALLOW_ORIGINS`. Fix: `proxy_set_header Host $http_host` (port-
preserving) in all locations; `nginx -t` + reload; live re-verified
(Origin `https://localhost:6443` login 200 after the fix; foreign origin
still 403). No wildcard origins; cookie policy untouched
(HttpOnly/Secure/SameSite=Strict).

## 6. Security audit trail (§26)

Additive table `security_audit_log` (migration
`backend/migrations/add_security_audit_log.sql`, IF NOT EXISTS only,
reversible by DROP TABLE; applied to the real Postgres). Events recorded:
`user_created`, `user_disabled`, `user_enabled`, `password_reset`,
`session_revoked`, `ownership_granted`, `ownership_revoked`,
`login_rate_limited`. Fields: event_type, actor_context (operator-cli /
system / user), actor_note, target_user_id, target_diver_id,
metadata_json (non-secret), created_at. No credentials, no tokens, no
URLs. Synthetic-user audit rows were kept after cleanup as the durable
trail.

## 7. P8-C — ownership inventory (privacy-safe counts)

    divers_total                     23
    divers_with_video_dives          23 (dives_with_video_uuid = 2805)
    divers_with_media_revisions      1  (all 15 revisions → diver 1)
    divers_with_verified_PROD_B2     1
    app_users                        3  (1 real = maxime; 2 historical
                                        synthetic negatives from P5/P6)
    user→diver OWNER mappings        1  (maxime → diver 1)
    unowned media revisions          0
    ambiguous ownership              0  (no multi-diver chain, no
                                         multi-verified-PROD revision)

No accounts were auto-created for unonboarded divers; media for them
stays private (no public link, no inferred account, no shared fallback).

## 8. P8-D — external access audit

Topology (fresh audit): application on Debian server `192.168.1.57`
(`deb-serv`); nginx container binds `0.0.0.0:6090` (HTTP→SPA/API) and
`0.0.0.0:6443` (HTTPS, self-managed cert, internal CA); backend/postgres/
adminer bound to loopback only; no host firewall (INPUT policy ACCEPT)
but the router performs no port-forward for these ports (WAN probe of
6090/6443 = dead). Public IPv4 is the VPN exit IP (VPN active), not a
port-forwarded ingress. IPv6 prefix is provider-delegated; no
dive-analyser ingress tested/published over IPv6. The host also runs a
navidrome-only cloudflared tunnel (inactive service, different app) and
ZeroTier — neither exposes dive-analyser.

Classification: **LAN_ONLY** (with a documented provider-gate path for
external athlete access — `EXTERNAL_ACCESS_PROVIDER_GATE`).

No ports were opened to satisfy P8. No raw `router port-forward → nginx`
publication was performed or approved. External access preparation,
analysis and the recommended pattern are in
`docs/architecture/EXTERNAL_ACCESS_V1.md` (Cloudflare Zero-Trust tunnel
is the recommended family for non-technical athletes; Tailscale would
require a client per athlete — unsuitable). HTTPS already mandatory on
6443; production cookie unchanged. The single consolidated
HUMAN/PROVIDER action for external access is recorded in
EXTERNAL_ACCESS_V1 §6 — P8 performed NONE of it (no provider/domain/DNS
action taken).

## 9. P8-E — playback observation cohort

Operator-minted server-side session for the real OWNER account (user 1)
plus automated representative requests against the live production
backend:

- **34 + 28 = 62+ authenticated playback requests observed** (target was
  15–30; exceeded), plus repeated re-observations after restarts.
- Outcomes: **authorized 100%**, **B2 selected 100%** (302 → presigned
  provider URL), **denied 0**, **unexpected legacy fallback 0**,
  **provider failures 0**, **presign leaks 0** (URLs only in the redirect
  Location; never logged/stored — fetched once in-process for the Range
  probe and discarded).
- Provider Range proof: fresh presign → ranged GET → **206** with
  Content-Range (read-only).
- Grant ledger (privacy-safe) grew accordingly; grant refresh counter
  live (`grant_refreshes`).
- Playback metrics snapshot (one worker): requests 28/28 authorized,
  b2_selected 28, denied 0, provider_failures 0; storage lookup avg
  ~1.5–1.8 ms; presign path avg ~80–100 ms (incl. grant-time provider
  HEAD), max ~1.7 s on cold credential init.

## 10. Continuous-ingest soak (§29)

- Exactly one production daemon instance (launchd state=running, single
  pid, `daemon.lock` present, last exit 0).
- No disk runaway (server `/` 48% used; Mac 17 GiB free), no staging
  accumulation (Mac incoming 45 MB / object staging clean), no legacy
  ingestion regression (media_jobs: 0 active/leased; loops healthy),
  no unbounded B2 retry (ledger 25/25 DB_COMMITTED, 0 pending).

## 11. Backlog + reconciliation (§30/§31/§32)

- `ingest_object_state`: 25/25 DB_COMMITTED; 0 pending/retryable;
  no quarantine; migration residuals: none.
- Storage reconciliation: 15/15 eligible OWNER media revisions have
  exactly one verified PROD B2 location (`100%`), 0 ambiguous chains.
- B2 PROD inventory (fresh, read-only LIST via the least-privilege ingest
  key): **16 objects / 345,568,956 bytes, 100% content-addressed
  (`blobs/sha256/…`), 0 non-conforming keys, 0 unexplained orphans**
  (15 logical locations + 1 retained P4 canary lineage).
- B2 cost: storage 345.6 MB → free tier ($0); no caps changed.

## 12. P8-F — legacy decommission readiness (§33–§38)

Full dependency audit (code-level, with file/line references) in
`docs/architecture/LEGACY_DECOMMISSION_PLAN_V1.md`. Highlights:

- The legacy transcoded cache is **still the primary playback substrate**
  for every product surface (dives list, analysis, representative
  gallery, posters); the B2 backbone serves playback via the revisions
  route. Decommissioning the cache today would break the main UI.
- The `/videos` file family is FALLBACK_ONLY and effectively
  unreferenced (`dives.video_path` NULL for all 2805 dives; 14 GB on the
  server, largest file 6.8 GB) — the largest clean future reclaim, but
  deletion remains forbidden.
- Canonical source/vault (13 GB Mac, 440 sources) is ACTIVE_REQUIRED as
  the ingest/migration source.
- Exactly five sanctioned deletion sites exist in code (cache eviction,
  vault retention, materializer/exporter cleanup, ingest staging, ops
  /videos prune); nothing deletes Photos originals or B2 objects.
- Science reads only its own caches; the backend landmark pipeline
  consumes legacy proxy_360p files (ACTIVE_REQUIRED dependency).

Storage economics measured (no deletion):

    Server media/cache      864 MB  (poster 116 MB, 360p 62 MB, 720p 671 MB)
    Server media/videos      14 GB  (icloudpd fallback files, unreferenced)
    Postgres DB              34 MB
    Mac source vault         13 GB  (440 sources)
    Mac highres (science)   445 MB  (science authority, not product)
    B2 PROD              345.6 MB  (16 objects)

**LEGACY_DECOMMISSION_VERDICT: LEGACY_DECOMMISSION_NOT_READY** — the
packet's prerequisites (natural continuous-ingest proof, extended
playback observation, frozen backup/retention policy, rollback strategy
independent of legacy bytes) are not all satisfied; P8 explicitly
computed readiness rather than bypassing it. No dry-run plan produced
(not authorized by §37 conditions). P9 dry-run design guidance is in
LEGACY_DECOMMISSION_PLAN_V1 §5.

## 13. Normal rollback (§48)

The P7-proven rollback paths remain structurally intact and untouched:
B2 playback off → authenticated legacy fallback (auth stays ON; the
unauthenticated historical mode remains an emergency-only state, unsafe
for any public ingress — documented in EXTERNAL_ACCESS_V1). User auth was
never disabled during P8.

## 14. Test results

- Backend `test_p8_user_admin.py`: **10/10 pass** (multi-user IDOR matrix
  across B2 play + legacy check/viewed/cache routes, disable semantics,
  password-reset rotation, IP rate limit, foreign Origin, audit trail
  no-secrets, session revocation counts, CLI end-to-end, unbind/rebind).
- P5 (21) + P6 (30) suites: **51/51 pass** (fixtures updated additively
  for the new audit table).
- `test_media_backbone.py`: 91 pass + 1 pre-existing env-only failure
  (static source-path test requiring `/mac-agent` inside the backend
  container — byte-identical on base code).
- `test_media_backbone_commit_api.py`: 10 failures reproduced on base
  HEAD in this container (pre-existing env condition, X-API-Key test
  fixture vs container env; not caused by P8 — verified by running the
  suite on the reverted code).
- Migrations: `add_security_audit_log.sql` applied on real Postgres;
  idempotent rerun safe (IF NOT EXISTS); reversible (DROP TABLE).
- mac-agent untouched; P7 baseline (218/218) preserved.

## 15. Durable artifacts

- `backend/scripts/manage_user.py` — operator CLI
- `backend/app/models/security_audit_log.py` +
  `backend/migrations/add_security_audit_log.sql`
- `backend/app/services/security_audit_log.py`, `auth_metrics.py`
- `backend/app/api/v1/auth.py` (audit + metrics wiring),
  `backend/app/services/sessions.py` (public revoke helper)
- `backend/tests/test_p8_user_admin.py`
- `nginx/conf.d/default.conf` — Host $http_host fix (committed + deployed live)
- `docs/architecture/EXTERNAL_ACCESS_V1.md`
- `docs/architecture/LEGACY_DECOMMISSION_PLAN_V1.md`
- PROJECT_STATE + USER_AUTHORIZATION/SECURITY/TARGET/MIGRATION_PLAN P8
  sections

## 16. Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P8` — then a P9 packet for:
continuous-ingest observation window (passive), extended B2 soak, the
single HUMAN_PROVIDER_ACTION if external athlete access is desired, and
(only after prerequisites) the legacy dry-run design.
