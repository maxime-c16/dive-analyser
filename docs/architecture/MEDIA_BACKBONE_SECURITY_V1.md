# MEDIA_BACKBONE_SECURITY_V1 — Storage Security Design & B2 Europe Research

Task packet: `MEDIA_BACKBONE_P0_P1_V1`. Research freshness: 2026-09-09.

## Security review (P1 design commitments)

| Control | Decision | Evidence / mechanism |
|---|---|---|
| Bucket privacy | **Private only.** Public buckets are out of scope. PRECISION (repair R5): at P1 this is a **CONFIGURATION REQUIREMENT / provisioning invariant** — the adapter assumes and requires a private bucket and rejects unsafe application config. It is NOT yet a real-provider-verified property: no bucket exists until the P2 gate. P2 MUST test that anonymous LIST/GET on the actual DEV bucket is denied. Future athlete delivery goes through short-TTL presigned GETs. | `B2Config` / adapter docs; no anonymous-read configuration surface exists; **real verification pending P2** |
| Least-privilege key | Use a **B2 application key** scoped to the single bucket (`capabilities: listFiles,readFiles,writeFiles` on the DEV bucket), never the master key. Master-key use is explicitly warned against in Backblaze's S3-API docs. | docs/architecture notes; operational provisioning step at DEV gate |
| DEV/PROD separation | Separate buckets by naming convention enforced by the config firewall: `diveanalyzer-dev-media` / `diveanalyzer-prod-media`; DEV-with-PROD-bucket (and vice versa) is a construction-time error. Tests cover both cross-wirings. | `mac-agent/src/ingest/objectstore/b2.py`, `test_ingest_backbone.py::TestB2ConfigFirewall` |
| Secrets | Server-side/agent-side only: `B2_APPLICATION_KEY_ID` / `B2_APPLICATION_KEY` environment variables (or operator-injected config). No credentials in source, fixtures, tests, or YAML examples. No browser exposure: the browser never talks to B2 in this packet. | env-var resolution in `B2Config.resolve_credentials()`; repo grep = zero hardcoded secrets |
| Presigned URLs | Bearer semantics: anyone with the URL can GET for the TTL. Short TTL default 3600s, hard max 7d (B2/S3 limit), validated at config and call time. Future P5 delivery must use per-request, per-object, minimal-TTL URLs. | `presign_get` validation + `MAX_TTL_SECONDS` |
| Logging | Never log credentials or presigned URLs. Structured ingest evidence is limited to: clip logical id, Photos source identity, ingest state, media SHA, caption SHA, object key, verification state, retry count, error family, temp path (coordinator state history). Caption raw text is persisted in `caption_revisions` (DB, private) but NOT in logs; parity harness reports hashes/lengths only. | `compare_caption_providers` redaction test; state history fields |
| Object keys | `blobs/sha256/<2>/<sha>` — no athlete name, no caption, no dive code, no email, no Photos title, no PII. Prefix charset validated. | `object_key_for_sha` + tests |
| Object metadata | No canonical caption/business state in object metadata; DB remains business authority. | TARGET doc; commit service |
| No destructive automation | `delete_object_explicit_operator_action` exists on the store adapter only, is unreachable from ingest/sync code, and no automatic purge is implemented. | grep: zero callers in ingest paths |
| No Cloudflare in V1 | Not included (per packet). | — |
| No Object Lock | Not enabled. | — |
| Science firewall | Object-store backbone handles application (athlete-visible) media only; no intersection with HQ analysis-source corpus, frozen D5/Event Logic artifacts. | CURRENT_STATE doc |

## Threat notes (explicit reasoning)

1. **Presigned URL leakage** → future P5: generate on demand server-side, TTL
   ≤ minutes for athlete playback, single object per URL, never cache in HTML
   longer than TTL, never log. V1 has no presign-consuming endpoint at all.
2. **Permanent credentials on iPhone** → none: the iPhone only feeds Apple
   Photos; no app-level cloud credentials are provisioned to devices in this
   architecture.
3. **Metadata transfer to US** (see EU research below): account/billing/API-key
   metadata is processed by Backblaze's US infrastructure even for EU-Central
   buckets. Object keys must therefore stay PII-free (already enforced).
4. **Environment cross-wiring** → enforced at construction (firewall) and at
   config validation (agent `Config.validate`); static guard test on the SQL
   migration prevents non-additive drift.

## B2 Europe region / account research (2026-09-09)

Primary sources: Backblaze docs (`backblaze.com/docs/cloud-storage-data-regions`,
`cloud-storage-call-the-s3-compatible-api`), Backblaze 2019 Amsterdam
announcement, and third-party analysis (sota.io, 2026-05) for the legal
dimension. No resources were created during this research.

### Operational facts

- **Available regions** (current docs): US West (Sacramento/Stockton/Phoenix),
  US East (Reston, VA), **EU Central (Amsterdam, Netherlands)**, Canada East
  (Toronto).
- **Region is ACCOUNT-LEVEL, chosen at account creation, and cannot be changed
  afterward.** Backblaze docs: "When you create a Backblaze B2 account, you
  choose whether that account's data is stored in the US East region, the US
  West region, the EU Central region, or the Canada East region… After you
  create your Backblaze B2 account, you cannot change your selected region."
  The S3-API docs confirm: "a Backblaze B2 account is associated with a single
  region. It is not currently possible to create buckets outside of an
  account's region." (Bucket-level region selection has been on Backblaze's
  roadmap since 2019 but is still not what the docs ship today.)
- **An account cannot span regions.** Multi-region is achieved with separate
  accounts administered together via Backblaze Groups.
- **EU Central endpoint:** `https://s3.eu-central-003.backblazeb2.com`
  (S3-compatible; boto3/AWS CLI/rclone work with endpoint + key substitution).
  HTTPS only.
- **EU data residency implications (operational):** customer object data
  uploaded to an EU-Central bucket stays in Amsterdam unless the customer moves
  it; account metadata (email, API keys, usage/billing) resides in US systems.
  Backblaze states restores/snapshots of EU data are served from Europe.
- **Migration difficulty if the region choice changes later:** no in-place
  region moves and no intra-Backblaze data move; migration = new account in the
  desired region + re-upload (or bucket replication rules between accounts in a
  Group — no replication egress fees). For this project the migration path is
  trivial-by-design: content-addressed blobs can be re-uploaded from the
  agent/vault or re-fetched from the old bucket, since the DB (not the object
  store) is the authority. Bucket/key format is region-independent.
- **Cost (PRIMARY SOURCE — Backblaze B2 Pay-As-You-Go, supervisor-verified
  against primary documentation, repair R6):**
  - Storage: **$6.95 / TB / month** (≈ $0.00695/GB-mo)
  - **First 10 GB free**
  - Free egress: **up to 3× average monthly storage**
  - Egress above the free allowance: **$0.01 / GB**
  - Pricing is NOT hardcoded into any runtime logic (config- and doc-level
    only). EU Central launched Q1 2023; no EU price premium documented.
- **Operational constraints:** S3-compatible API only (no B2-native key
  required); master application key cannot be used with the S3 API — create a
  bucket-scoped application key; multipart upload ETags are not SHA-256
  equivalent (already handled: our integrity identity is SHA-256, tested).

### Legal/policy dimension — FLAGGED AS HUMAN DECISION, not resolved here

- Backblaze, Inc. is a US (California) corporation; US law (including the
  CLOUD Act) applies to the provider relationship regardless of the Amsterdam
  data center. Third-party 2026 analysis argues EU-Central provides data
  *residency*, not legal *sovereignty*; SCC-based DPA exists but its adequacy
  under Schrems II reasoning is a legal judgment.
- **No GDPR/compliance claim is made or guessed in this document.** Whether
  EU-Central residency is sufficient for this deployment's personal-data
  posture (single-athlete training media, LAN distribution) is a human/legal
  decision. Evidence-backed alternative if sovereignty is required: EU-based
  providers with EU legal entities (e.g., Hetzner Object Storage,
  OVHcloud) — also S3-compatible, i.e., our `ObjectStore` port makes this a
  configuration change, not a rewrite.

### Recommended setup for European athlete media (operational recommendation, legal sign-off human)

```text
Account layout (at DEV/PROD provisioning gate, NOT created in this packet):
  Option A (single-region EU): one EU-Central account
    bucket diveanalyzer-dev-media  (private, bucket key w/ write+read)
    bucket diveanalyzer-prod-media (private, bucket key w/ write+read)
  Option B (strict DEV/PROD isolation): two EU-Central accounts (one per env),
  administered via Backblaze Groups
DEV first, canary on DEV bucket only; PROD created only at the P4 gate.
```

Both options keep DEV and PROD in separate buckets; Option B additionally
separates credentials/accounts, which matches the packet's environment
separation doctrine more strictly and is therefore the recommended shape if
both buckets are provisioned by the same provider account holder.

## B2 resource plan — human decision (NOT executed)

### Option A — one EU-Central account, two buckets, separate least-privilege keys

```text
one EU-Central account
  bucket diveanalyzer-dev-media  (private, bucket-scoped app key w/ read+write)
  bucket diveanalyzer-prod-media (private, created later at the P4 gate,
                                  separate bucket-scoped app key)
```

Advantages: simpler, same residency, less account administration.

### Option B — separate EU-Central DEV and PROD accounts

```text
DEV account  -> bucket diveanalyzer-dev-media  (DEV app key)
PROD account -> bucket diveanalyzer-prod-media (PROD app key, at P4)
(optional: both administered together via Backblaze Groups)
```

Advantages: stronger blast-radius / billing / administrative isolation.

**Decision is the human's.** Operational note (repair R6): the supervisor
considers Option A adequate technically for an initial small project unless a
security/administrative requirement motivates Option B; Option B can be
adopted later without re-uploading content-addressed blobs (the DB, not the
object store, is the authority). Both options keep DEV and PROD in separate
buckets with separate least-privilege keys.

### Provisioning sheet (identical under either option)

| Item | Value |

| Item | Value |
|---|---|
| DEV bucket | `diveanalyzer-dev-media` — private, EU-Central region (pending human region decision); **anonymous LIST/GET denial must be tested at P2** |
| PROD bucket | `diveanalyzer-prod-media` — private, created only at P4 gate |
| DEV app key | bucket-scoped application key (files read/write/list on DEV bucket only) |
| PROD app key | bucket-scoped, separate, provisioned at P4 |
| Secrets transport | environment variables on the mac-server agent runtime + backend env; never in Git |
| Object prefix | `blobs/sha256/` |
| Endpoint | `https://s3.eu-central-003.backblazeb2.com` (if EU Central selected) |

## Least-privilege PROD key authority (established at P4.1, 2026-09-09)

The PROD runtime credential is a **true least-privilege application key**,
created via the Backblaze **Native API v4** `b2_create_key` with an explicit
capabilities array (the console UI cannot express this scope — its
bucket-restricted presets force extra capabilities such as `deleteFiles`):

```text
key name:        diveanalyzer-prod-ingest-v2
capabilities:    [listFiles, readFiles, writeFiles]   (exactly, nothing more)
bucket scope:    diveanalyzer-prod-media only (bucketIds restricted)
provider flags:  options = ["s3"]   (S3-compatible surface enabled)
```

Authority rules (binding for all future phases):

1. **No destructive or administrative capability is ever granted** to a
   runtime key: `deleteFiles`, `writeBuckets`, `deleteBuckets`, `writeKeys`,
   `deleteKeys`, `shareFiles` are absent by construction and verified
   against the provider response (`b2_create_key` response and a fresh
   `b2_authorize_account` with the key itself).
2. **Creation transport:** privileged key-creation credentials (Master Key
   or temporary `writeKeys` account key) are ephemeral operator input in a
   local trusted context (`read -s`, in-memory only) — never stored in Git,
   PROJECT_STATE, docs, agent config, runtime env files, or shell history.
   The local agent owns all API plumbing.
3. **Key lifecycle order is fixed:** create → validate provider scope →
   S3 compatibility validation → install (0600, atomic swap) →
   production-runtime preflight GREEN → revoke the previous key. No
   availability gap.
4. **B2 semantics note (provider-documented behavior, verified live):** the
   S3 `DeleteObject` call maps to a *hide* marker (soft hide; the upload
   version is retained); hard deletion requires `b2_delete_file_version`,
   which least-privilege runtime keys cannot perform (401). The ingest path
   performs no delete operations regardless (P4 compensating control).
5. **Scope verification is provider-reported evidence, persisted non-secret**
   in `docs/audits/…_EVIDENCE.json`; negative probes are synthetic-only and
   never target the production canary lineage.
6. P4.1 status: `TEMPORARY_DELETEFILES_SECURITY_DEBT = NO`;
   `P5_OR_BROADER_PROD_KEY_BLOCKER = NO` (credential blocker cleared only —
   not an authorization for P5 or broader rollout). Known outstanding debt
   (pre-existing, flagged at P4.1, out of scope): `diveanalyzer-dev-agent`
   (`003e2bb572cfba70000000001`) is an ACCOUNT-WIDE key holding admin
   capabilities (`writeKeys`, `deleteKeys`, `deleteBuckets`).

## DEV admin key debt — P4.3 audit (audit only, NO rotation performed)

Packet §18: `diveanalyzer-dev-agent` (applicationKeyId `003e2bb572cfba70000000001`,
P4.1 key inventory) remains an **account-wide key with admin capabilities**.
P4.3 audited it read-only; no credential was rotated or touched:

- **Where it is used:** NOWHERE in any runtime config found. The Mac
  production host's `object_store.env` (DEV ingest) holds
  `diveanalyzer-dev-canary` (`…0003`, bucket-scoped — the P3 rotation); the
  PROD runtime holds `diveanalyzer-prod-ingest-v2` (…0006). A targeted
  search over the Mac state directory, deployed code, and the canonical
  repo found **zero references** to the …0001 key ID.
- **What capabilities it has:** account-wide admin (all buckets, full
  capability set including `deleteFiles`/key management).
- **Does production runtime depend on it?** NO — both runtime credentials
  are bucket-scoped least-privilege keys.
- **Does DEV ingest require admin capabilities?** NO — P3 ran the complete
  ingest flow green on the bucket-scoped DEV key; P4.1 proved
  `[listFiles, readFiles, writeFiles]` suffices end-to-end.
- **Remaining exposure:** whoever holds this key can read/write/delete in
  every bucket of the account and manage keys. It is presumably held only
  by the maintainer (used interactively for console/API administration,
  e.g. P4.1 key creation used a privileged credential in memory only).

**Recommendation (future maintainer-attended step, NOT overnight):** revoke
`diveanalyzer-dev-agent` …0001 entirely — no runtime needs it. If a
privileged maintenance credential is ever required again, create it ad hoc
with exact capabilities via the P4.1 in-memory procedure and delete it
immediately after use. Until then the key is dormant-but-dangerous debt;
treat any committed reference to it as a secret-class finding.

## P4.1 synthetic-object absence — P4.3 reconciliation (§17, read-only)

P4.1's S3-compatibility validation PUT two synthetic objects and documented
them as retained evidence (`bc1fece7…` 784 B single-PUT probe, `a5f2bc63…`
12 MB multipart probe). P4.2's first full LIST found them absent, and P4.3's
read-only LIST re-confirmed: the PROD bucket holds exactly 10 objects — the
P4 synthetic preflight probe (`72d94c7f…`, 408 B), the P4 canary blob, and
the 8 P4.2 cohort blobs. P4.3 performed no delete/hide and did not recreate
them. Evidence collected:

- The two keys exist verbatim in the P4.1 evidence JSON (`put_single.key`,
  `multipart.key`) with SHA-verified PUT/HEAD/GET results; no timestamps
  were recorded for their creation beyond the P4.1 session window.
- Project-code deletion is excluded: the runtime key cannot hard-delete
  (401, P4.1) and S3 `DeleteObject` was never called (0 log matches for
  delete/hide primitives in the full production log; the P4.2 static
  no-delete firewall covers the entire ingest path; the P4 `b2-preflight`
  diagnostic cleans only its own `72d94c7f` probe, which is still present).
- Provider lifecycle rules cannot be excluded: bucket-level lifecycle
  configuration is not readable with the least-privilege key (401 on
  bucket ops) — noted as an unproven alternative.

**Classification: `EXTERNAL_OR_MANUAL_REMOVAL_MOST_LIKELY`** (maintainer
console cleanup during the P4.1→P4.2 window is the leading hypothesis;
`PROVIDER_LIFECYCLE` cannot be fully excluded; `PROJECT_CODE_ACTION` is
excluded by evidence). Not a P5 blocker: the objects were non-sensitive
synthetic validation bytes, and no unauthorized destructive action by
project code is indicated.

## P4.3 storage-authority hardening (2026-09-10)

The P4.2 cross-environment cohort exposed a schema-representation gap:
`media_blobs` carried physical location fields on the content-identity row,
so the four P3 DEV lineage blobs that were verified into the PROD bucket at
P4.2 deduped onto their DEV rows and their PROD replicas were not durably
represented. P4.3 repaired this additively (see STORAGE AUTHORITY in
`MEDIA_BACKBONE_TARGET_V1.md`): `media_blob_locations` is now the
authoritative per-replica record, the legacy blob location columns are
documented transitional/non-authoritative, the commit ledger is
environment-scoped, and the commit service rejects environment/bucket
mismatches and conflicting-SHA location keys at the service boundary (in
addition to the existing commit-API firewall). No destructive migration;
no media deletion; no credential changes; dual-write flags remain OFF.

## P5 user authentication & playback authorization (2026-09-10)

Packet `MEDIA_BACKBONE_P5_ACCELERATED_AUTH_PLAYBACK_V1` added the smallest
production-grade USER auth layer needed for authorized B2 playback. Full
authority: `docs/architecture/USER_AUTHORIZATION_V1.md`. Summary:

- **AppUser / UserCredential / UserSession / UserDiverAccess** — additive,
  reversible, idempotent schema (`add_user_auth_tables.sql`), idempotence
  re-proven on the real Postgres.
- **Argon2id** password verifier (argon2-cffi 23.1.0, pinned); no plaintext,
  no reversible encryption; safe library verifier only.
- **Opaque server-side sessions**: cookie carries a 256-bit raw token; DB
  stores only its SHA-256; login rotates and revokes prior sessions.
- **Cookie**: `HttpOnly; Secure; SameSite=Strict; Path=/` (production
  HTTPS via nginx 6443; AUTH_COOKIE_SECURE never disabled for production).
- **Endpoints**: login / logout / me; uniform generic failures; DB-backed
  rate limit (5 failures / identifier / 15 min window → 429, rolling
  reset; no permanent lockout); no public registration.
- **MEDIA→DIVER link**: `MEDIA_DIVER_LINK_ALREADY_DETERMINISTIC`
  (MediaRevision.video_uuid → dives.video_uuid UNIQUE → dives.diver_id);
  no additive ownership table; no inference from filename/caption/albums/
  is_primary_user.
- **Central policy** `can_user_access_media`: ALLOW iff authenticated
  + exactly one trusted diver owner + explicit OWNER binding; otherwise
  DENY. No LAN/UUID/legacy fallbacks. IDOR-proven with two synthetic users.
- **Playback grant**: authenticated same-origin route → verified-PROD
  location (exactly one; ambiguous/unverified/DEV → DENY) → B2 presign
  TTL 120 s (clamp [1,300]) → 302 with `Cache-Control: private, no-store`
  + `Referrer-Policy: no-referrer`. Presigned URLs never logged or stored
  (test-asserted + live log scan). Expired grants rejected by the
  provider (live-proven 401 after 130 s) and a fresh grant is obtained by
  re-requesting the route.
- **CORS**: NOT required for the `<video>`-element flow (no crossorigin,
  no JS media fetch) — live-verified in Chromium + WebKit; B2 untouched.
- **Content-Type**: existing `binary/octet-stream` objects play as-is
  (recorded compatibility, no rewrite); future uploads get evidence-based
  video MIME via ffprobe container/codec (mac-agent change, dual-write
  flags still OFF, 0 media ops).
- **Flags**: `USER_AUTH_ENABLED` / `B2_PLAYBACK_CANARY_ENABLED` default
  false, fail-closed; after the live canary/cohort proof both were
  returned OFF (legacy playback remains the product default).
- **Live proof**: one real owner account (bootstrap CLI, getpass-only
  password), canary revision 12 → 9/9 cohort authorized (target ≥5),
  Range/seek GREEN in Chromium + WebKit, negative tests (unauthenticated
  401, wrong-owner 404 no-Location, unknown-revision 404), expired-grant
  provider rejection + fresh grant. 0 B2 writes, 0 deletes, no object
  mutation, dual-write flags OFF throughout.
- **Outstanding**: Object Lock attestation pending; DEV admin key cleanup
  debt; presign credential is the P4.1 key (readFiles included) — a
  dedicated presign-only playback key is the recorded end-state debt
  (provider-console action).

## P6 dedicated playback key, legacy IDOR closure, default playback (2026-09-10)

Packet `MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1`. Durable audit:
`docs/audits/MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1.md` (+ key
evidence JSON `docs/audits/MEDIA_BACKBONE_P6_PLAYBACK_KEY_EVIDENCE.json`).

- **Dedicated playback key** `diveanalyzer-prod-playback-v1`
  (…000a): capabilities exactly `readFiles`, bucket-restricted to
  `diveanalyzer-prod-media`, S3 client configured directly with the known
  endpoint/bucket (no account-level listing needed). Proofs: GetObject/
  HeadObject/presigned GET/Range-206 GREEN; PutObject, delete, hide,
  create-bucket, cross-bucket all DENIED. The backend holds NO
  write-capable B2 credential anymore; the Mac ingest runtime keeps the
  P4.1 ingest key (verified functional). One-time operator admin key
  `p6-op-ephemeral` (…0008) + duplicate playback key `…0009` await one
  maintainer UI revocation.
- **Login lockout-DoS repair**: two-tier limiter — per-IP failed-attempt
  cap (10/15 min, first X-Forwarded-For element; nginx is the only
  ingress) + per-identifier cap (20/15 min); ANY successful login CLEARS
  the identifier failures (non-destructive recovery, no durable lock).
  Brute force still bounded; a single source cannot hold an identifier at
  its ceiling.
- **Session hygiene**: bounded cleanup of expired/revoked sessions after
  successful login (retention default 24 h, max 500 rows/call).
- **CSRF (exact)**: SameSite=Strict is the primary control for this
  single-origin topology; added minimal Origin validation on state-
  changing auth POSTs (login/logout) as defense-in-depth; cookie policy
  unchanged.
- **Legacy IDOR closure** (routes now auth-gated while auth enabled —
  rollback = flags off): `/videos/{uuid}` + `/videos/check/{uuid}` +
  `/media/cache/{id}/play` + `/media/events/viewed` require session +
  central OWNER authorization through the deterministic chains
  (cache entry → PhotosAsset → dive → diver). Unauth 401, wrong owner
  404, owner allowed; live-proven for all identities.
- **Authenticated legacy fallback**: authorized owner gets B2 by default;
  B2 unavailable (grant-time provider HEAD proof catches invalid/revoked
  credentials that local presigning would mask) → server-side legacy
  stream with Range (browser NEVER receives an unauthenticated legacy
  URL); no legacy copy → explicit 503 provider failure; ambiguous/
  unverified/DEV-only location → fail-closed 404; authorization failures
  NEVER fall back.
- **Object Lock** attested: none/absent → DISABLED (no retention touch).
- **dev-agent admin key REVOKED** (b2_delete_key 200).
- **Security headers**: legacy media streams now carry no-referrer +
  nosniff; frontend SPA pages carry both via nginx (server-level +
  repeated in header-defining locations).
- Live default-playback canary GREEN (Chrome + WebKit), cohort 9/9 B2
  (all provider 206), expired-presign refresh GREEN, B2-failure injection
  → authenticated legacy fallback (200/206), wrong-owner DENY in all
  three states. 0 B2 writes, 0 deletes/hides.
