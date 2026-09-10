# USER_AUTHORIZATION_V1 — browser user authentication & media access authority

Packet: `MEDIA_BACKBONE_P5_ACCELERATED_AUTH_PLAYBACK_V1`. Fresh 2026-09-10.
This document is the durable authority for the P5 V1 USER auth layer. It is
additive to, and does not replace, `MEDIA_BACKBONE_SECURITY_V1.md` (storage
authority) or the legacy application behavior.

## 1. Architecture (P5 V1)

| Layer | Authority |
|---|---|
| AppUser | `app_users` — provisioned browser users. **No public signup, no OAuth/social login, no password-reset email, no multi-tenant admin in V1.** The only provisioning path is the operator CLI. |
| Password | `user_credentials` — one Argon2id PHC verifier per user (`argon2-cffi==23.1.0`, pinned params: t=3, m=64 MiB, p=2, 32-byte tag). No plaintext, no reversible encryption, no raw-password logging. |
| Session | `user_sessions` — server-side OPAQUE: raw token (`secrets.token_urlsafe(32)`) lives ONLY in the browser cookie; the DB stores ONLY `sha256(token)`. Login rotates (fresh token, previous live session revoked). `expires_at` / `revoked_at` / `last_used_at` enforced on every resolution. |
| Cookie | `da_session`: `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=604800`. `AUTH_COOKIE_SECURE` defaults true; disabling is only valid for an isolated plain-HTTP test environment. Production requires HTTPS. |
| Binding | `user_diver_access` — durable explicit user→diver rows, V1 `access_kind='OWNER'` only. `divers.is_primary_user` is descriptive and NEVER authorizes. |

## 2. Machine vs user authority

`X-API-Key` remains the MACHINE credential for the macOS agent. It must
never appear in a browser. Browser users authenticate through
`POST /api/v1/auth/login` (email + password → opaque session cookie).
The two authorities are disjoint.

## 3. Media→diver ownership (classification)

**`MEDIA_DIVER_LINK_ALREADY_DETERMINISTIC`.** No additive ownership table
was introduced in P5 V1. The authoritative chain in the existing domain:

```
MediaRevision.video_uuid → dives.video_uuid (UNIQUE) → dives.diver_id
```

Verified fresh against production: all 15 `media_revisions` → exactly one
dive each (0 orphans). Authorization NEVER uses: filename, caption text,
UUID secrecy, Photos albums, `divers.is_primary_user`, or LAN locality.

## 4. Central policy

`backend/app/services/user_access.py:can_user_access_media(db, user, media_revision)`
is the single implementation every playback path must use:

```
ALLOW iff
  authenticated, active user
  AND media revision resolves to exactly one trusted diver owner
      (deterministic chain, fail-closed)
  AND explicit OWNER UserDiverAccess(user, diver) row exists
else DENY
```

Denial is uniform 404 for media-existence privacy; 401 for
unauthenticated; 503 `B2_PROVIDER_FAILURE` family for provider failures
(never a fallback to legacy unauthenticated playback — authorization
denial is never masked as, nor rescued by, provider failure or legacy
playback).

## 5. Endpoints & rate limit

- `POST /api/v1/auth/login` — uniform generic failure; dummy-verify timing
  smoothing; bounded brute-force protection: DB-backed
  **5 failures / identifier / 15-min rolling window → 429**, window
  roll-off resets (no permanent lockout). Cross-worker reliable
  (`login_attempts` table).
- `POST /api/v1/auth/logout` — revoke + clear cookie (idempotent).
- `GET /api/v1/auth/me` — identity + bound diver kinds.
- All fail closed (404) while `USER_AUTH_ENABLED=false`.

## 6. Playback grant (B2 canary scope)

`GET /api/v1/media/revisions/{id}/play` (only while
`USER_AUTH_ENABLED AND B2_PLAYBACK_CANARY_ENABLED`):

```
session → can_user_access_media → exactly-one verified PROD replica
(environment=prod, verified=true, storage_backend=b2,
 bucket=diveanalyzer-prod-media) → B2 presigned GET (TTL 120 s,
clamp [1,300]) → HTTP 302 Location (Cache-Control: private, no-store;
Referrer-Policy: no-referrer; X-Content-Type-Options: nosniff)
```

- The presigned URL exists only as the redirect target: never JSON body,
  never DB, never logs, never metrics. Verified by tests + live log scan.
- CORS: NOT required for the `<video>`-element flow (no `crossorigin`
  attribute, no JS fetch of media bytes) — verified live in Chromium and
  WebKit; B2 bucket CORS remains untouched.
- Content-Type: existing `binary/octet-stream` objects play correctly as-is
  (no historical rewrite); future uploads get evidence-based video MIME
  (`video/quicktime`/`video/mp4`/...) via ffprobe container/codec evidence
  (mac-agent `media_content_type`).
- IDOR: knowing a revision id / video UUID / blob SHA / B2 key /
  storage-location id is insufficient. All resolution passes through the
  policy. Two synthetic users proven isolated (wrong-owner → 404).

## 7. Provisioning

`backend/scripts/bootstrap_user.py` (operator-side, one-shot):
`create user → UserCredential (Argon2id) → UserDiverAccess OWNER`,
password via `getpass` (never argv, never history). Current production
state: one user (`user_id=1`, OWNER of diver 1), plus the standing
synthetic negative-test user `p5-synthetic-negative@test.local` (no
access).

## 8. Flags & rollback

- `USER_AUTH_ENABLED=false` + `B2_PLAYBACK_CANARY_ENABLED=false`
  (defaults): every new route 404s; legacy app 100% unchanged.
- Post-canary state (2026-09-10): flags returned OFF after the live
  canary/cohort proof. Re-activation: set both true in server `.env`,
  `docker-compose up -d backend` (schema + account persist; nothing to
  re-migrate).
- Legacy playback remains the product default; the P5 route is never a
  global replacement.

## 9. Outstanding items

- Object Lock attestation for `diveanalyzer-prod-media`: pending (P5 did
  not mutate retention; see SECURITY_V1).
- `diveanalyzer-dev-agent` (account-wide admin, unused): recorded cleanup
  debt; unused by P5.
- Presign credential: the backend presigner currently uses the P4.1
  least-privilege PROD key (`diveanalyzer-prod-ingest-v2`, caps
  listFiles/readFiles/writeFiles — broader than playback needs). A
  dedicated presign-only (readFiles) playback key is the correct end
  state and requires a provider-console action (HUMAN_PROVIDER_ACTION).
  Recorded as security debt, not a blocker.
- Historical `binary/octet-stream` objects: compatibility verified;
  re-upload/rewrite remains forbidden without a future explicit packet.
