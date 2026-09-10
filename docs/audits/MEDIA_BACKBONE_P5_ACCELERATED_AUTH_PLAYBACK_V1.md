# MEDIA_BACKBONE_P5_ACCELERATED_AUTH_PLAYBACK_V1 — durable audit

Task packet: `MEDIA_BACKBONE_P5_ACCELERATED_AUTH_PLAYBACK_V1`
(combined P5-A..P5-F). Executed 2026-09-10 on the canonical repository
`mcauchy@192.168.1.57:~/dive-analyser`, branch `uiux-overhaul-pro-app`,
reported base `59e9097573ef5ca9194910d669b382c3efa52387` (P4.3 closure),
reported P5-PRE head `8a332d3`.

## 0. Canonical-state integration

- `8a332d3` was **NOT found in canonical history** (`git cat-file -t`:
  invalid object; absent from every branch/ref). The reported P5-PRE
  investigation was never committed to the canonical repo. No divergence
  integration was required beyond proceeding from the verified base:
  fresh canonical state at packet start was `636b0dc` (a concurrent
  SCIENCE commit, `hurdle-identity-v2`, sitting directly on top of the
  accepted base `59e9097`), plus untracked science experiment files.
- All concurrent work was preserved: the science commit remains untouched
  in history, the untracked experiment files were never staged, and P5
  work was committed ON TOP of `636b0dc` without rebasing or rewriting
  anything.
- The local Mac directory `~/.perso/diveanalyzer` is (per PROJECT_STATE)
  NOT a git repo and was never treated as canonical.

## 1. P5-PRE diagnosis (fresh, accepted)

The application had NO browser user authentication of any kind: no login,
no session, no JWT/OAuth, no user→diver binding. The only credential was
the machine `X-API-Key` authority for the macOS agent. Legacy video
playback (`GET /api/v1/videos/{video_uuid}`) is unauthenticated historical
behavior — NOT a suitable security model for B2 playback.

## 2. Auth schema (additive, reversible, idempotent)

`backend/migrations/add_user_auth_tables.sql` (run twice on the REAL
production Postgres to prove idempotence):

| Table | Purpose |
|---|---|
| `app_users` | provisioned browser users (lower(email) unique index); NO public signup |
| `user_credentials` | one Argon2id PHC verifier per user (`password_algo='argon2id'`); never plaintext, never reversible |
| `user_sessions` | server-side opaque sessions: SHA-256(raw token) as lookup identity (`uq_user_sessions_token_hash`); `created_at/expires_at/revoked_at/last_used_at` |
| `user_diver_access` | durable explicit user→diver binding, V1 `access_kind='OWNER'` only |
| `login_attempts` | bounded brute-force ledger (per-identifier, cross-worker) |
| `media_playback_grants` | privacy-safe grant ledger: ids/outcomes/TTL only |

Reversibility: each table is standalone; the full pre-P5 state returns via
the six `DROP TABLE IF EXISTS` statements in reverse order (documented in
the migration header). No legacy table altered, no row rewritten.

## 3. Password authority

`backend/app/services/passwords.py` — `argon2-cffi==23.1.0`, **Argon2id**
(`PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2,
hash_len=32, salt_len=16, type=Type.ID)`; OWASP baseline class).
Verification uses ONLY the library verifier (`PasswordHasher.verify`);
all failure families collapse to a single boolean. No plaintext storage,
no reversible encryption, no raw-password logging (verified: slow-query
log prints statement text only, bind params never; grep for password
material in logs = none). Dependencies pinned in `backend/requirements.txt`
(argon2-cffi 23.1.0, boto3 1.34.69 for presigning).

## 4. Session model

`backend/app/services/sessions.py`:

- raw token: `secrets.token_urlsafe(32)` (256-bit), returned once, placed
  ONLY in the browser cookie; **never persisted server-side**
- DB stores only `sha256(raw token)` hex
- resolution denies missing/malformed/unknown/revoked/expired; live
  resolution updates `last_used_at`
- every login issues a FRESH token and revokes the user's previous live
  sessions (one live browser session at canary stage; fixation avoided)

## 5. Cookie policy

`da_session`, `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`,
`Max-Age=604800` (config-driven). `AUTH_COOKIE_SECURE` defaults **true**
and was never disabled for production; the isolated plain-HTTP unit-test
environment scoped it off (asserted separately that production login
returns the full hardened flag set — live-verified:
`httponly=True, secure=True, samesite_strict=True, path_root=True`).
Production browser authentication runs over HTTPS (nginx 6443, TLS 1.2+,
DiveAnalyzer Local CA).

## 6. Auth endpoints

- `POST /api/v1/auth/login` — uniform `401 {"detail": "Invalid credentials"}`
  for unknown email / inactive user / wrong password; timing-smoothed with a
  constant dummy Argon2 verify when the email is unknown; rate-limited.
- `POST /api/v1/auth/logout` — revokes the session, clears the cookie
  (idempotent).
- `GET /api/v1/auth/me` — identity + explicitly bound diver access rows.
- All three fail closed (404) while `USER_AUTH_ENABLED=false`.

## 7. Login rate limit

DB-backed (`login_attempts`), cross-worker reliable on the 2-worker
uvicorn deployment: **max 5 failed logins per identifier per rolling
15-minute window → 429** (generic body, no distinct account-locked
semantics). Window roll-off resets naturally (no permanent lockout → no
trivial account-DoS vector). Successful logins are recorded but do not
reset the counter. Tested live in `test_login_rate_limit_bounded_window`.

## 8. Bootstrap user

`backend/scripts/bootstrap_user.py` — operator-side one-shot CLI:

- password read via `getpass` twice; NEVER an argv value, never echoed,
  never in shell history, never in chat
- refused-by-default one-shot semantics (existing email → error +
  `--reset-password` path)
- live result: `OK created user_id=1 diver_id=1 access_kind=OWNER`
  (login `maxime.cauchy93@gmail.com`, bound to the existing diver 1
  "Maxime" — `is_primary_user=true` made the intended bootstrap diver
  unambiguous, so no human disambiguation question was needed; the password
  was the only human interaction)
- a second run's `ModuleNotFoundError` (script invoked without workdir)
  was diagnosed live and repaired by making the script CWD-independent.

## 9. User→diver binding

Explicit `UserDiverAccess(user_id=1, diver_id=1, access_kind=OWNER)`.
`divers.is_primary_user` is NEVER consulted for authorization (it was used
only to identify the intended bootstrap diver). No coach/team access.

## 10. MEDIA→DIVER LINK — fresh schema audit

Classification: **`MEDIA_DIVER_LINK_ALREADY_DETERMINISTIC`**.

The existing domain already holds the authoritative chain:

```
MediaRevision.video_uuid → dives.video_uuid (UNIQUE) → dives.diver_id → divers
```

Fresh audit of the REAL production DB: all 15 `media_revisions` resolve to
exactly one dive row (0 orphans), `dives.video_uuid` is UNIQUE, so the
( MediaRevision → diver ) relation is a function. No additive
`MediaDiverOwnership` table was introduced; no bulk binding was performed.
The chain helper lives in
`backend/app/services/user_access.py:resolve_media_diver_owner` and fails
closed (None → DENY) on missing dive, missing diver binding, or unknown
revision.

## 11. Central access policy

`backend/app/services/user_access.py:can_user_access_media` — the single
implementation used by every playback path:

```
ALLOW iff
  authenticated, active user
  AND media revision resolves to exactly one trusted diver owner
      through the deterministic chain
  AND the user holds an explicit OWNER UserDiverAccess row for that diver
else DENY
```

No fallback: not to the primary user, not to LAN locality, not to UUID/SHA/
revision-id secrecy, not to same-browser, not to legacy unauthenticated
playback. Denial reasons are coarse (`unknown_revision`,
`no_diver_chain`, `no_owner_access`) and appear only in the private
grant ledger.

## 12. IDOR firewall

`GET /api/v1/media/revisions/{revision_id}/play` is the ONLY playback
resolution path; it always runs session → `can_user_access_media` →
verified-PROD-location lookup. Knowing the revision id, video UUID, blob
SHA, B2 key, or storage-location id alone yields nothing (every case is
tested: `unknown_revision`, wrong owner, unauthenticated, flags-off,
DEV/unverified/ambiguous storage). Live two-user check: a synthetic user
with no ownership binding logged in successfully and received **404 (no
Location header)** for the canary owner's media revision — while the
owner's own request returns the redirect.

## 13. Storage lookup

Reuses the accepted P4.3 authority
(`resolve_verified_location` semantics): the play route requires
**exactly one** verified PROD replica
(`environment=prod, verified=true, storage_backend=b2, bucket=diveanalyzer-prod-media`).
Zero verified PROD locations → DENY; more than one → DENY (ambiguous);
non-b2 / wrong bucket → DENY. DEV-only objects (verified DEV location
only), unverified PROD rows, and ambiguous pairs each have a dedicated
test; all return the uniform 404.

## 14. Playback grant architecture

Implemented exactly as the preferred accelerated V1:

```
browser <video src="/api/v1/media/revisions/{id}/play">
  → same-origin authenticated GET (cookie)
  → session auth → can_user_access_media → verified PROD location
  → B2 presigned GET (S3-compatible SigV4 via boto3)
  → HTTP 302, Location = presigned URL (120s TTL)
  → browser follows the redirect itself; Range/seek go straight to B2
```

The presigned URL is returned ONLY as a redirect Location — never a JSON
body, never persisted, never logged. Live-verified: the presign→redirect
→provider path works, and Range requests through it return **206**.

## 15. Grant response security

Redirect responses carry `Cache-Control: private, no-store`,
`Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff` (also
applied to auth responses). Verified zero leakage:
- DB (`media_playback_grants`) asserted to contain no `X-Amz`/`Signature`
  material (test + live inspection of 16 rows)
- backend logs scanned live: 0 hits for `x-amz|signature=`
- ledger rows contain only `user_id, media_revision_id, storage_location_id,
  outcome, denial_reason, ttl_seconds, created_at`.

## 16. Presign TTL

Config `MEDIA_PLAYBACK_PRESIGN_TTL_SECONDS=120`, hard-clamped to
`[1, 300]` in `b2_presign.clamp_ttl` (tested incl. the 10 000 → 300
ceiling). Live proof: a captured presigned URL fetched immediately
returns **206** with 1024 bytes; the same URL re-fetched after
130 s (>120 s TTL) is **rejected by the provider (401)**; re-requesting
the application route yields a **fresh 302** grant. No multi-hour links.

## 17. CORS

**NOT_REQUIRED** — verified, not assumed. The canary `<video>` element has
no `crossorigin` attribute, uses no `fetch()` for media bytes, and follows
the same-origin → 302 → B2 path natively. The full browser matrix (below)
ran without any B2 CORS mutation and without any CORS error in the page.
B2 bucket configuration was NOT touched (zero bucket config calls).

## 18. Browser matrix (Playwright, isolated env)

Real-browser evidence on the live canary page (`/media/p5-canary`, 9
authorized videos):

| Browser | videos | metadata load | play start | seek | result |
|---|---|---|---|---|---|
| Chromium (Google Chrome channel, H.264-capable) | 9 | 1153 ms | 1066 ms | works | **GREEN** |
| WebKit (Safari engine) | 9 | 751 ms | 1601 ms | works | **GREEN** |

Notes: the Playwright stock headless Chromium build is H.264-decode-limited
(mediabackbone-unrelated: metadata+seek still worked there; frame decode
needs the proprietary codec, so the real Chrome channel was used — recorded
as a test-environment note, NOT an app defect). No page errors in either
engine; no manual UI interaction required.

## 19. Content-Type (existing objects + future policy)

- Existing objects carry `Content-Type: binary/octet-stream`. Live
  playback of those objects was tested AS-IS and is GREEN (metadata,
  duration, play, Range/seek) in Chromium and WebKit — **no historical
  rewrite performed** (0 B2 writes, 0 deletes).
- FUTURE uploads repaired additively in the mac-agent:
  `media_content_type.video_content_type()` maps ffprobe
  container/codec evidence (never a bare filename guess) to
  `video/quicktime` / `video/mp4` / `video/webm` / `video/x-matroska`,
  failing closed to `binary/octet-stream`. `BackblazeB2Store.put` passes
  `ContentType` to boto3 for both bytes-PUT and fileobj-upload paths (and
  omits it when unset = legacy behavior); the coordinator forwards the
  type computed from the staged file's ffprobe metadata. 11 new mac-agent
  tests; production-mac full suite 182/182. Dual-write flags remained OFF
  and NO real upload occurred, so the fix ships inert until the next
  authorized ingest.

## 20. Feature flags

`USER_AUTH_ENABLED` / `B2_PLAYBACK_CANARY_ENABLED` (defaults **false**;
docker-compose passthrough with `${VAR:-false}`). All new routes fail
closed while disabled (`/auth/*` and `/media/revisions/*/play` → 404).
Legacy playback and the whole legacy UI are untouched. After the live
canary/cohort proof the flags were **returned OFF** (production default
playback mutation NONE, §42), with the documented re-activation procedure
(`USER_AUTH_ENABLED=true B2_PLAYBACK_CANARY_ENABLED=true` + backend
restart; the provisioned account and all tables persist).

## 21. Object Lock / DEV admin key

- Object Lock on `diveanalyzer-prod-media`: **pending attestation** —
  this packet did not touch retention and no provider-side evidence was
  re-collected; live P5 closure carries the outstanding uncertainty
  forward (recorded in SECURITY_V1).
- `diveanalyzer-dev-agent` (account-wide admin, unused, DEV): NOT used
  for P5 anywhere. Recorded as future cleanup debt; did not block any
  playback work.

## 22. Live canary + cohort

- Live canary media: `media_revision_id=12`, `video_uuid=606653E2-…`
  (the P4 dual-write canary clip, verified PROD replica, dive 102B/1m,
  diver 1). No new media ingest; 0 B2 writes; 0 object mutations.
- Live flow: login → hardened cookie → authenticated grant → 302 →
  ranged B2 fetch **206** → expired grant rejected by provider → fresh
  grant works. Grant latencies 306–3529 ms (first call includes B2
  client warm-up), ranged fetches ~65 536 bytes each.
- Negative live tests: synthetic no-ownership user → wrong-owner playback
  **404 (no Location)**; unauthenticated → **401**; unknown revision →
  **404**. A temporary synthetic OWNER user (created for the TTL-expiry
  proof only) was deleted afterwards (cascade-verified); the
  `p5-synthetic-negative` user remains as the standing negative-test
  account with NO diver access.
- Playback cohort: **9/9 authorized** (all verified-PROD revisions owned
  by the canary user/diver; target 8, available 9 — all exercised), 0
  denied for the owner, deny ledger rows only for the synthetic-negative
  probes. Metadata + representative ranged fetch per revision (full
  downloads not required).
- Cohort metrics (evidence JSON, no URLs): grant 302→206 ranged fetch
  343–3529 ms per revision; expired-grant refresh after expiry wait:
  206. Browser metadata-load 0.7–2.8 s, play-start 1.0–1.6 s (realtime
  progression), seek 100% success. Bytes read ~0.6 MB total (9×64 KB).
  B2 read traffic: 18 ranged requests across the canary runs; no
  production-scale cost extrapolation attempted.
- Provider-failure behavior: `PresignUnavailable` → **503
  B2_PROVIDER_FAILURE** family with no redirect and no legacy fallback
  (test `test_provider_failure_is_explicit_no_fallback`). Legacy app
  health re-verified after deployment (`/health` 200, legacy video
  routes untouched).

## 23. Security test matrix (§37) — results

`backend/tests/test_p5_auth_playback.py` — **21 passed** in the backend
container (plus 32 with the backbone suites):

valid login ✓ · invalid login generic ✓ · Argon2id hashing ✓ · token
hash-at-rest ✓ · hardened cookie flags ✓ · expired session ✓ · revoked
session ✓ · logout ✓ · token rotation ✓ · rate limit + window reset ✓ ·
authorized owner playback ✓ · unauthenticated denied ✓ · wrong-owner
IDOR denied ✓ · unknown revision ✓ · DEV location ✓ · unverified ✓ ·
ambiguous ✓ · flags-off fail-closed ✓ · signed URL never logged/stored ✓ ·
provider failure explicit ✓ · TTL clamp ✓ · session authority raw-token
non-persistence ✓

Full backend suite: `2 failed / 327 passed / 43 skipped / 273 errors` —
the delta vs the documented P4.3 baseline (1 failure / 273 errors) is the
environmental `test_agent_coordinator_does_not_reference_server_state`
(container lacks the mac-agent source path; unrelated to P5, pre-existing
in this environment class). `NEW_FAILURES_INTRODUCED_BY_BRANCH = 0`.

mac-agent (production Mac venv): **182/182** including the 11 new
Content-Type tests (two pre-existing test-harness signatures repaired to
accept the additive `content_type` argument).

## 24. Commits

See the commit list in the P5 report. Secrets added to Git: NONE
(credential values live in server `.env` / mac state, never in Git;
presigned URLs never committed anywhere).

## 25. Verdict

All P5 packet success targets met. Production default playback unchanged
(legacy). Recommended verdict:

```
P5_AUTH_AND_PLAYBACK_GREEN
```
