# MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1 — durable audit

Task packet: `MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1` (phases
P6-A..P6-F). Executed 2026-09-10 on the canonical repository
`mcauchy@192.168.1.57:~/dive-analyser`, branch `uiux-overhaul-pro-app`,
reported base `a2f7885094b3fe6e5056d4d58c14679b064b75f7` (P5 closure) —
verified fresh at packet start (`git rev-parse HEAD` matched exactly).

## 0. Canonical-state integration

- Local Mac directory `~/.perso/diveanalyzer` is NOT a git repo (verified:
  `git rev-parse` fatal) and was never treated as canonical.
- Fresh canonical HEAD at packet start = reported P5 head `a2f7885`.
  Untracked science artifacts (experiments/landmark_pilot/*,
  docs/science/localization_annotations_v1/…) were present and were NEVER
  staged, modified, or committed. All P6 work is additive on top of
  `a2f7885` without rebasing or rewriting concurrent histories.

## 1. P6-A: dedicated playback credential (§3-§6)

**Before:** the backend playback presigner consumed
`B2_PLAYBACK_KEY_*` which pointed at `003e2bb572cfba70000000006` — the
WRITE-CAPABLE `diveanalyzer-prod-ingest-v2` PROD ingest key (verified
against the P4.1 key inventory). Credential separation was violated in
practice (config surface existed, value was wrong).

**One attended operator session** (`/tmp/p6_operator.py`, outside the
repo, self-deleted; admin credential parsed from a maintainer-supplied
`~/key.txt` into memory via a shell-interpreted session, file shredded
after use; NOTHING in argv/Git/docs/runtime history beyond this audit):

- Created `diveanalyzer-prod-playback-v1`
  (`003e2bb572cfba7000000000a`), capabilities exactly **`readFiles`**,
  bucket-restricted to `diveanalyzer-prod-media`
  (bucketId `7e720bcb6587827caf0b0a17`). Nothing else granted.
- Wrote the new key directly into the server `.env`
  (`B2_PLAYBACK_KEY_ID/_SECRET`, 0600) — the secret never left the
  server's memory/0600 file and never entered chat, Git, or docs.
- An earlier aborted attempt had created a duplicate key
  (`003e2bb572cfba70000000009`) whose secret was never stored; recorded
  for one-batch UI revocation (§4.1 below).
- Revoked `diveanalyzer-dev-agent` (`003e2bb572cfba70000000001`,
  account-wide admin) via `b2_delete_key` → **200 OK** (§19 debt cleared
  by the same operator run).
- Attested **Object Lock** state of `diveanalyzer-prod-media`: the
  bucket record carries **no `objectLock` (None)** → Object Lock is
  **DISABLED** at provider attestation time. Desired V1 state (Disabled)
  holds; no retention was touched.

### Playback key proof (read-only, non-destructive)

Native API (with the readFiles-only key): `b2_list_file_names` on the
PROD bucket → **401 unauthorized** (correct: listing is NOT in readFiles;
the target design needs no listing — the S3 client is configured directly
with the known endpoint+bucket).

S3 API (boto3 inside the backend container, `s3_probe.py`):

| Probe | Result |
|---|---|
| GetObject (ranged) | **206**, 1024 bytes |
| HeadObject | **200** (31 MB object, content-type binary/octet-stream) |
| Presigned GET (120 s TTL) | **200** (full object) |
| Presigned GET + Range | **206**, 1024 bytes |
| Presigned GET cross-bucket (DEV) | **403 denied** |
| PutObject | **denied** (403 family; B2 closes the connection before a parseable body — combined with native-API and S3-Delete denials below, write authority is proven absent) |
| HeadObject cross-bucket | **403 denied** |
| DeleteObject | **403 denied** |
| b2_hide_file (native) | **401 denied** |
| b2_delete_file_version (native, fake non-existent file id) | denied |
| b2_create_bucket (native) | denied |

Evidence JSON (secret-free; contains only names, ids, caps, statuses):
`docs/audits/MEDIA_BACKBONE_P6_PLAYBACK_KEY_EVIDENCE.json`.

### Credential domains (§6)

- Backend container env: only `B2_PLAYBACK_KEY_ID/SECRET` (…000a,
  readFiles). No ingest secret present (verified: ingest key id absent
  from backend env).
- Mac ingest runtime (`/Users/Shared/services/data/diveanalyzer/state/
  object_store_prod.env`, 0600): `diveanalyzer-prod-ingest-v2`
  (listFiles/readFiles/writeFiles). Live-verified after the cutover:
  native authorize + S3 list/head on the PROD bucket → 200 (the key is
  functional; it simply does not appear in `b2_list_keys` output of
  another key — a provider listing-visibility quirk, not a loss).

### Provider cleanup requiring the maintainer (single UI action, remaining)

- `003e2bb572cfba70000000009` — duplicate `diveanalyzer-prod-playback-v1`
  created by the first aborted operator run; its secret was never stored
  anywhere. **Maintainer: delete this key in the B2 console** (one UI
  action).
- `003e2bb572cfba70000000008` — `p6-op-ephemeral`, the all-capabilities
  admin key the maintainer created for this packet's operator session.
  Used once (in memory), key.txt shredded; **maintainer: revoke it in the
  B2 console** (same UI action).
- Final desired inventory after that action: dev-canary (003), prod-agent
  (004), prod-ingest-v2 (006), prod-playback-v1 (…000a).

## 2. §7 login rate-limit hardening (lockout-DoS repair)

Fresh audit confirmed the P5 design: 5 failures / identifier / 15 min,
successful logins did NOT reset the counter. An unauthenticated attacker
who knows the owner email could keep re-bursting 5 failures every window
and maintain an **indefinite lock** on the legitimate owner.

**Repair (two-tier, no durable account lock):**

- per-IDENTIFIER failed-attempt cap raised to 20 / rolling 15 min
  (`AUTH_LOGIN_MAX_FAILURES`, docker-compose default now 20);
- NEW per-client-IP failed-attempt cap 10 / rolling 15 min
  (`AUTH_LOGIN_IP_MAX_FAILURES`) — one source cannot spray guesses nor
  hold the identifier at its ceiling;
- client source = first X-Forwarded-For element (nginx appends the direct
  peer; a caller-supplied chain cannot forge the first element). Used
  ONLY for limiter bucketing/ledger scoping — never authorization;
  a new `login_attempts.client_ip` column (additive idempotent migration
  `add_login_attempts_ip.sql`, applied to the real Postgres).
- **ANY successful login clears the identifier's failure rows** (and the
  rows recorded from the source that just proved the credential) —
  non-destructive recovery;
- window roll-off unchanged (no durable lock); generic 429 body
  (`Too many attempts`) preserved; brute-force protection not weakened
  (single source: 10 tries/15min; distributed: 20/15min).

Live tests: burst from one IP throttled at the IP cap; a different source
still logs in; identifier ceiling (20, distributed) bounds guessing;
success clears the counter; a different identifier is never globally
locked; state expires; generic responses preserved. Unit tests in
`test_p6_playback_default.py`; the P5 rate-limit test was updated to the
two-tier semantics (its name and bounded-window contract unchanged).

## 3. §8 session security revalidation + cleanup

Revalidated live and by test: Secure + HttpOnly + SameSite=Strict +
Path=/ cookie; 256-bit CSPRNG raw token; SHA-256-only at rest; expiry,
revocation, logout, login rotation (fresh token, prior sessions revoked)
all verified against the live deployment during the canary. **Added**
bounded cleanup (`sessions.cleanup_stale_sessions`): after a successful
login, expired sessions are deleted and revoked sessions older than the
retention window (default 24 h, `AUTH_SESSION_CLEANUP_RETENTION_SECONDS`)
are deleted, max 500 rows per call. No bearer values logged (grep-asserted
in P5 and unchanged).

## 4. §9 CSRF / same-origin assessment (exact)

Topology: single-origin app — nginx serves the SPA and proxies `/api/`;
the session cookie is `SameSite=Strict`, so cross-site browser requests
never carry it. **Assessment: SameSite=Strict provides the primary CSRF
protection for this topology; a full token framework would be
cargo-culting.** Added the MINIMAL correct defense-in-depth: an Origin
check on state-changing auth POSTs (`/auth/login`, `/auth/logout`) — if
`Origin` is present it must match a configured CORS origin or the
request's own Host/scheme; absent Origin is allowed (non-browser
clients). Cookie policy NOT weakened. Tests: hostile origin → 403,
same-origin → 200, no-Origin → 200.

## 5. §10/§11/§14 legacy route inventory + ingress closure

Fresh inspection of actual runtime (nginx conf, listeners, docker ports):

- Public ingress: `dive-analyser-nginx` binds `0.0.0.0:6090` (HTTP) and
  `0.0.0.0:6443` (HTTPS). iptables INPUT policy ACCEPT (LAN-open). The
  authenticated application and ALL legacy media routes share this
  single ingress. (Caddy on :24443 is an unrelated kcpm service; the
  systemd caddy unit is inactive.)
- Legacy media-serving routes found (all previously unauthenticated):

| Route | What it serves | P6 closure (while `USER_AUTH_ENABLED=true`) |
|---|---|---|
| `GET /api/v1/videos/{video_uuid}` | legacy files (/videos, /photos_library) or 307 → cache play | session required (401) + central OWNER authorization (404 deny) |
| `GET /api/v1/videos/check/{video_uuid}` | availability metadata + playback_url disclosure | same gate, raised BEFORE the probe (never a spoofed `{"available":false}`) |
| `GET/HEAD /api/v1/media/cache/{entry_id}/play` | cache renditions (proxy/poster) | session + central OWNER authorization via the deterministic chain `MediaCacheEntry → PhotosAsset.video_uuid → dives.video_uuid (UNIQUE) → dives.diver_id` |
| `POST /api/v1/media/events/viewed` | metadata only | same gate |

- With `USER_AUTH_ENABLED=false` the routes keep byte-for-byte legacy
  behavior — that flag state is the documented emergency rollback and the
  routes are then LAN-only legacy surface (pre-existing boundary,
  unchanged by P6).
- Authorization-failure semantics on gated routes: 401 (no session) /
  uniform 404 (wrong owner) — NEVER a redirect, so no authorization
  outcome can steer any client to media.

## 6. §12/§13 authenticated legacy fallback + failure semantics

`backend/app/services/legacy_media.py` resolves, ONLY after session auth
AND central OWNER authorization: ready media-cache playback renditions
(preference proxy_720p > proxy_360p > original; posters never) inside the
configured cache root, else the exact legacy file candidates used by
`/videos/{uuid}` constrained to the same allowed roots. The backend
streams it server-side with full HTTP Range support (`_serve_media_file`)
— **the browser never receives an unauthenticated legacy URL**.

Exact P6 failure-semantics matrix (single route
`GET /api/v1/media/revisions/{id}/play`):

| Condition | Response | Fallback? |
|---|---|---|
| flags off / unauthenticated / unknown revision / no diver chain / wrong owner | 401/404 | NEVER |
| zero verified PROD locations (NO_PROD_B2_REPLICA) | legacy fallback stream (200/206) if a legacy source resolves, else 404 | authorized only |
| verified PROD location + presign or provider-HEAD failure (B2_TEMPORARY_FAILURE) | legacy fallback stream if available, else explicit 503 `B2 provider unavailable` | authorized only |
| more than one verified PROD location (B2_INTEGRITY/AMBIGUITY) | 404 fail-closed | NEVER (never sign an ambiguous object) |
| location exists but backend≠b2 / wrong bucket | 404 fail-closed | NEVER |

**Grant-time provider health proof (new in P6):** boto3 presigning is a
LOCAL signing operation — an invalid/revoked credential still yields a
well-formed URL the provider would reject, i.e. the browser would get a
dead redirect. `b2_presign.head_object()` now proves the read-only
credential can actually read the object at grant time; any failure is
B2_TEMPORARY_FAILURE (→ authorized legacy fallback + `provider_failures`
metric; explicit 503 when no legacy copy exists). Live-proven by
injecting an invalid playback secret: authorized user received a real
legacy stream (200, video/mp4, Range 0-1023 → 206) instead of a dead
Location; wrong owner during the outage got 404.

## 7. §15/§16/§21/§26 player abstraction + default policy

- The ONLY application playback URL is
  `GET /api/v1/media/revisions/{id}/play`; the backend chooses the source.
  The frontend (`frontend/src/pages/P5Canary.tsx`, route
  `/media/p5-canary`) uses exactly this URL; no B2 storage keys, bucket
  names, or presigned URLs ever enter frontend state or the page.
- Frontend copy neutralized for the owner (no developer/provider
  terminology: "Media player" heading + sign-in/out; internals only in
  code comments/API paths).
- Default policy implemented exactly per §16: verified PROD B2 replica +
  healthy provider → **B2 (default)**; otherwise authorized legacy
  fallback; never DEV B2; never unverified/ambiguous replicas. For the
  canary revision the live chain is:
  login → player page → auth → ownership → 302 presigned (120 s) →
  provider 200/206; with B2 unavailable → authenticated legacy 200/206.

## 8. §18 Object Lock + §19 DEV admin key

- Object Lock `diveanalyzer-prod-media`: attested **None/absent →
  Disabled**. No retention mutation. (Earlier "pending" uncertainty
  resolved by direct provider evidence.)
- `diveanalyzer-dev-agent` (…0001, account-wide admin): REVOKED via the
  operator session (b2_delete_key → 200). Post-revocation inventory
  (maintainer UI cleanup pending for two keys as noted in §1): dev-canary
  (003), prod-agent (004), prod-ingest-v2 (006), prod-playback-v1 (…000a),
  plus the one-time `p6-op-ephemeral` (008) to be revoked by the
  maintainer.

## 9. §20/§21/§22/§23 live canary evidence

Flags armed (`USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true`)
only after the credential + security + ingress gates were GREEN. A
temporary synthetic OWNER (bound to the SAME diver 1 as the bootstrapped
owner) exercised the flows; deleted after the proofs (real owner account
user_id=1 persists untouched). Standing negative accounts:
`p5-synthetic-negative@test.local` (from P5) and `p6-negative@example.test`
(both with zero diver access).

- **Default B2 grant chain (live)**: login 200 → `GET .../play` → **302**
  to `s3.eu-central-003.backblazeb2.com/diveanalyzer-prod-media/...`
  presigned URL (TTL 120 s) → provider GET **200** (14.3 MB) and ranged
  **206**; hardened redirect headers present
  (`Cache-Control: private, no-store`, `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff`).
- **Expired presign refresh (live)**: URL fetched >120 s after grant →
  provider **401**; re-request → fresh 302 (different URL) → **206**.
- **B2 failure injection (live)**: playback secret invalidated at runtime
  → authorized legacy fallback stream 200 (496 KB proxy_720p), Range
  0-1023 → **206**, `Accept-Ranges: bytes`; NO redirect, NO
  unauthenticated URL; wrong owner during outage → **404**; restored
  secret → B2 default resumed (302 → 206).
- **Wrong owner (live)**: auth'd no-access user → 404 (no Location);
  wrong-owner user (bound to a synthetic diver) → 404 on the play route
  AND on `/videos/{uuid}` AND on `/videos/check/{uuid}`; unauthenticated
  → 401. No fallback bypasses authorization.
- **Legacy routes (live)**: unauth 401 / owner 307-200 / wrong owner 404
  on both `/videos/{uuid}` and `/videos/check/{uuid}` while flags ON.
- **Browser matrix (Playwright, live production ingress 6443)**:

| Engine | videos listed | metadata | play | seek | page errors |
|---|---|---|---|---|---|
| Google Chrome (channel `chrome`) | 15 | ~6.0 s | 0.74 s | to 7.2 s ✓ | 0 |
| WebKit (Playwright v2248) | 15 | ~7.0 s | 0.24 s (play_ok) | to 7.2 s ✓ | 0 |

  (15 = all owner revisions listed with `b2_ready`/`legacy_available`
  booleans; the first video is the P5 canary revision 12.)

## 10. §24/§25 owner cohort + production default

Cohort = ALL currently verified PROD revisions owned by the bootstrapped
diver (9 of them: revisions 6,7,8,9,11,12,13,14,15) — bounded ≤15, no
supervisor roundtrip. Sweep result:

- **9/9 → B2 selected**, every presigned provider fetch ranged **206**;
- DEV-only revisions (1,10) → **LEGACY_FALLBACK** stream authorized
  (200); DEV-only revisions 2-5 (no legacy copy) → uniform 404
  fail-closed — recorded in the grant ledger (`storage_not_found`);
- 0 denied for the owner; deny ledger rows only for negative accounts.

**Production default (§25, authorized)**: `USER_AUTH_ENABLED=true`,
`B2 authenticated playback enabled` (B2 default + authorized legacy
fallback) for the existing OWNER account only. No public registration, no
additional athletes, no ownership broadening. The real owner (user_id=1)
must simply log in with their own credentials (unchanged from P5
bootstrap).

## 11. §27 observability

`backend/app/services/playback_metrics.py` (in-process, thread-safe) +
authenticated endpoint `GET /api/v1/media/playback/metrics`:
playback_requests_total, authorized, denied, b2_selected,
legacy_fallback_selected, provider_failures, legacy_fallback_failures,
range_successes, grant_refreshes, storage_lookup_latency_ms (avg/max),
presign_latency_ms (avg/max). Grant-ledger outcomes (ALLOWED / DENIED /
PROVIDER_FAILURE / LEGACY_FALLBACK) continue to be the durable record.
NEVER recorded: tokens, cookies, presigned URLs, signatures, passwords
(tested: no `X-Amz-Signature`/marker in the endpoint body; P5 no-leak
assertions unchanged).

## 12. §28 security headers

- Play grants + auth responses: `private, no-store`, `no-referrer`,
  `nosniff` (live-verified on 302 and legacy-stream responses).
- Legacy streaming responses (`/videos/{uuid}`, cache play): added
  `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`.
- Frontend SPA pages: nginx adds `Referrer-Policy: no-referrer` +
  `X-Content-Type-Options: nosniff` (server-level + repeated inside
  locations that define their own add_header — nginx does not inherit
  then). CSP untouched (no CSP existed; no framework change made).

## 13. §30 rollback (both paths proven live)

1. **Flag rollback** (`B2_PLAYBACK_CANARY_ENABLED=false`, auth stays on):
   play route + metrics endpoint → 404 (fail-closed); auth-gated legacy
   routes keep requiring auth; legacy app healthy. PROVEN live.
2. **Emergency rollback** (both flags false): exact legacy behavior —
   unauthenticated legacy playback restored (307 to cache play),
   auth routes hidden (404). PROVEN live.

Re-arming is a `.env` flip + backend restart (documented in
USER_AUTHORIZATION_V1 §8). Final state after the proofs: both flags ON.

## 14. §32/§36 B2 operations + science firewall

- `B2_MEDIA_WRITES = 0`; **delete/hide operations = 0** on existing
  objects (all negative probes were denials or non-existent ids).
- Dual-write flags remain OFF; no Photos interaction; no media ingested;
  no historical object rewrites; existing `binary/octet-stream` objects
  proved playable as-is (live provider fetches above).
- Science: zero mutations; concurrent untracked experiment artifacts
  untouched; science worktree (`hurdle-identity-repair`) untouched.

## 15. §33 test matrix results

- New suite `backend/tests/test_p6_playback_default.py` — **30 passed**:
  B2-default grant, B2-failure→legacy (incl. Range 206), B2-failure without
  legacy → 503, NO_PROD_B2_REPLICA → legacy, ambiguous → fail-closed,
  provider-HEAD failure → fallback (never a dead URL), wrong-owner ×3
  (B2 copy / B2 failing / legacy copy), unauth/unknown, legacy gating
  (401/404/owner-allowed/Range-206/flags-off-legacy-preserved), rate-limit
  matrix (burst throttled per-IP, owner recoverable cross-IP, success
  clears, per-identifier independence, expiry, generic 429), session
  cleanup, Origin matrix, metrics no-leak.
- P5 suite updated for the two-tier limiter + fake head: **21 passed**.
- Full backend suite: `2 failed / 357 passed / 43 skipped / 273 errors` —
  identical pre-existing environmental set as P4.3/P5 (the 2 failures:
  agent-coordinator env test + a pre-existing dive-analysis signature
  failure; 273 errors pre-existing). **NEW_FAILURES_INTRODUCED = 0.**
- Mac agent: untouched by P6 (182/182 remains the last proven state; no
  mac-agent change in this packet).
- Legacy live checks after every backend mutation: `/health` 200, legacy
  video + cache routes correct per gate state.

## 16. Commits

See the P6 commit in the branch log. Secrets in Git: NONE (playback
secret lives ONLY in server `.env` 0600; no presigned URL, token, or
credential committed anywhere; `~/key.txt` shredded; operator script
self-deleted).

## 17. Outstanding items

1. Maintainer UI action (one batch): revoke `…0009` (duplicate playback
   key) and `…0008` (`p6-op-ephemeral` admin key) in the Backblaze
   console.
2. Frontend container hard-restart caution: the frontend ships as the
   baked image `dive-analyser-frontend:latest` built via
   `docker build -f frontend/Dockerfile.deploy -t dive-analyser-frontend:latest frontend`
   (compose `build:` on that service is a development Dockerfile and does
   NOT produce the deployed image — recorded here so future packets don't
   mistake a `docker-compose build frontend` for a deploy).
3. Multi-worker metrics are per-process (documented in §11).

## 18. Verdict

All packet targets met; production default playback for the owner is B2
with authenticated legacy fallback and both rollback paths proven.

```
P6_OWNER_DEFAULT_PLAYBACK_GREEN
```
