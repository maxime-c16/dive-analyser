# MEDIA_BACKBONE_P2_CANARY_V1 — Single-Real-Clip DEV Canary Report

Task packet: `MEDIA_BACKBONE_P2_CANARY_V1` (DIVE_ANALYZER_MEDIA_BACKBONE_V1, continuation of accepted `MEDIA_BACKBONE_P0_P1_V1`).
Executed: 2026-09-09. Verdict: **P2_CANARY_GREEN**.

## 1. Preflight / integration

- Canonical repo (`mcauchy@192.168.1.57:~/dive-analyser`, branch `uiux-overhaul-pro-app`):
  - P2-PRE base HEAD: `4b192dc0a90cc2ffb0ec85f334bb8ffc329a93e2`
  - Accepted P0/P1 branch `media-backbone-p0-p1-v1` (HEAD `e5fd0c5fab860692a5f0acc8bc3a695f70dad50b`,
    worktree `~/.perso/diveanalyzer-media-backbone`) entered canonical history by
    **fast-forward merge on the server** (`4b192dc → e5fd0c5`). Server working tree had
    NO tracked modifications (only untracked science files, untouched).
  - Concurrent thread protection: the **hurdle-identity science thread** advanced canonical
    to `ef1e55e5…` (commits af09fce, e6a0e9b, ef1e55e) during the canary; P2 support was
    **rebased** onto it (`76ed66f → d4c0c8a`), preserving all concurrent commits
    (`git merge --ff-only` afterwards; no force-push of canonical, no discarded work).
  - Final implementation HEAD at canary time: `ff8beea8cbd33e324b5a0436140f21b9f4094a89`
    (later `dcf04e1e9fa1a387e3147fb17de2353f01f548be` after the shadow repair).
- Tests at integration: mac-agent suite **127/127** → **129/129** after shadow-repair tests;
  backend `test_media_backbone.py` **23/23**; `git diff --check` clean.

## 2. B2 provider (human-authorized: DEV only, EU Central)

- Account topology: **one EU-Central account** (Option A), authorized by the maintainer.
- Bucket: `diveanalyzer-dev-media` — **Private**, created by the maintainer in the B2 UI,
  bucket id `ce32bbfbb597826caf0b0a17`, endpoint `s3.eu-central-003.backblazeb2.com`
  (**EU Central / Amsterdam** — matches the approved region), Object Lock **disabled**,
  lifecycle "Keep all versions", encryption disabled at creation.
- Application key: `diveanalyzer-dev-canary`, **bucket-scoped** to
  `diveanalyzer-dev-media`, capabilities `listFiles, readFiles, writeFiles` (no more).
- Credentials: installed as `B2_APPLICATION_KEY_ID` / `B2_APPLICATION_KEY` in
  `/Users/Shared/services/data/diveanalyzer/state/object_store.env` (mode 0600,
  owner `divesensei`). Never in Git, docs, fixtures, logs, or reports. The runner
  refuses env files looser than 0600.
- Real-preflight (adapter `BackblazeB2Store`, synthetic disposable object under
  `blobs/sha256/preflight/`, deleted afterwards): PUT ok, HEAD ok, GET ok
  (SHA match), presign generated. Elapsed 0.51s. `synthetic_probe_deleted: true`.

## 3. Real-provider privacy evidence (replaces P1 configuration assumption)

| Probe (unauthenticated, no credentials) | Result |
|---|---|
| Bucket LIST (`?list-type=2`) | **HTTP 403** `AccessDenied` — "Unauthenticated requests are not allowed for this api" |
| Object GET on the real canary key | **HTTP 401** (Backblaze's unauthenticated-request denial) |
| Object GET on presigned URL (signed, TTL 300s) | **HTTP 200** (full 19,019,783 bytes) |

No bucket/object was made public to test this.

## 4. Runtime / TCC preflight (fresh evidence)

- Production runtime (recorded, untouched): LaunchAgent `com.diveanalyzer.agent`
  (gui domain, pid 26457) executes
  `/Users/divesensei/Applications/DiveSensei Python Runtime.app/Contents/MacOS/divesensei-python-runtime`.
  NOTE: this corrects the P0-era belief that the venv interpreter is the deployed
  runtime — the app bundle IS the production runtime (`com.diveanalyzer.python-runtime`).
- **Canary execution context (the context that actually ran P2):** one-shot CLI on the
  same host/user — host `192.168.1.19` (macOS 15.1.1, user `divesensei`),
  interpreter `/Users/Shared/services/data/diveanalyzer/venv/bin/python`
  (Python 3.12.13, osxphotos 0.76.1, boto3 1.43.90),
  code `/Users/Shared/services/data/diveanalyzer/code` (repo `mac-agent/src` mirror),
  config `/Users/Shared/services/data/diveanalyzer/state/object_store_canary.yaml`
  (separate from the production `config.yaml`, which has NO `object_store` block).
- TCC proof from that exact context (read-only):
  - direct `Photos.sqlite` `mode=ro` health probe: **PHOTOS_DB_OK, 12277 videos**;
  - osxphotos full-library read + album discovery: ok;
  - targeted single-asset materialization: ok (Section 6).
  - No raw SSH PhotoKit execution; no macOS security setting weakened.

## 5. Ready album (canary boundary)

- Album did not exist at packet start (human UI action requested).
- The maintainer created it as **`DiveAnalyser Ready`** (the project's canonical en-GB
  spelling; the packet's en-US `DiveAnalyzer Ready` is accepted as an alias and the
  exact matched title is recorded in evidence). Album discovered from the canary
  runtime: 81 historical captioned clips, then the canary asset (82 total).

## 6. Canary clip + exact caption

- Asset: uuid `42D80813-0D2F-4F75-92BB-F0648E7AA77E`, `IMG_1641.mov`, in album
  `DiveAnalyser Ready`, `hasadjustments=true` (visible Photos trim edit),
  iCloud-backed (`incloud=true`).
- Caption authority: `CurrentStableCaptionProvider` (`osxphotos_description_stable`).

```text
caption_raw        = "107B | 7.5 | H:3 | drill:no-arms | note:à revoir"   (exact provider string)
chars / UTF-8      = 48 chars / 49 bytes (à = 2 bytes)
caption_sha256     = 18d6377f07c92bf3baed78b44326f09542dfa412050d5f4aa0d416eb4101668b
```

- Byte/string exactness: no strip, no Unicode normalization, no whitespace collapse
  before `CaptionRevision`; the legacy `.strip()` remains isolated in
  `legacy_caption_transform` (legacy path only). Legacy parser result for this
  canary string is recorded honestly as `null` (`parser_version=legacy_parse_dive_caption_v1`)
  — the backbone caption authority is raw text, not the legacy grammar.
- Shadow: `PhotosDbCaptionProviderShadow` — initially reported `shadow_column_not_found`
  (truthful). **Bounded repair (auto-repair scope):** the shadow now introspects the
  macOS 13+ caption path `ZASSET → ZADDITIONALASSETATTRIBUTES → ZASSETDESCRIPTION.ZLONGDESCRIPTION`
  (all tables/columns located by PRAGMA/sqlite_master introspection). Result:
  `shadow_available=true`, shadow SHA == stable SHA, **`exact_equal=true`** (both
  caption revisions). Real PhotoKit shadow status remains
  `PHOTOKIT_CAPTION_SHADOW_STATUS=NOT_IMPLEMENTED_CURRENT_RUNTIME` (unchanged doctrine).

## 7. Materialization + rendition provenance

- Targeted single-UUID osxphotos export (`--uuid … --only-movies --download-missing --update`),
  same hardened `MediaMaterializer` seam; no full-library materialization; bounded
  export (2 GB cap), 600–900s timeout, UUID regex + path containment.
- Result: `/Users/Shared/services/data/media-node/object_ingest_tmp/<uuid>/…/IMG_1641.mov`,
  **19,019,783 bytes**, materialization 9.5s (16:25:53→16:26:03Z).
- ffprobe: HEVC, 1920×1080, **9.288333 s**, ~16.38 Mbit/s, 580 frames, start_pts 0.
- Edited-rendition evidence: `hasadjustments=true` on the asset; osxphotos export
  without `--skip-edited` yields the user's edited/trim representation (documented
  osxphotos semantics; the same authority already used by the production pipeline).
  Residual note: osxphotos 0.76.1 exposes no `PhotoInfo.duration` attribute, so the
  extra export-vs-Photos duration cross-check is unavailable
  (`rendition_duration_match=null` recorded); provenance rests on the adjustment flag
  + export semantics, recorded in `source_provenance`.

## 8. Roundtrip + DB commit (verified-ingest rule)

```text
local edited bytes  SHA A = 2af63b4b0951653580790b6652bcab53b60799c5b09c56e14e6b0ffc9b3f96e9
→ B2 PUT  blobs/sha256/2a/2af63b4b0951653580790b6652bcab53b60799c5b09c56e14e6b0ffc9b3f96e9.mov
→ B2 full GET
→ SHA B identical, byte size identical → REMOTE_VERIFIED   (A == B PASS)
```

- Upload through the accepted `BackblazeB2Store` adapter (multipart, ETag
  `9b5b0a6650fe2fbbede3988c22be759d-3` — never used as integrity identity).
- DB commit executed **only after** remote verification, through the accepted service
  `backend/app/services/media_backbone.py::commit_verified_ingest` (tunneled by the
  operator into the backend container; the mac has no direct DB access — the commit
  transport is `backend/scripts/backbone_canary_commit.py`, receipt-confirmed).

## 9. Controlled crash/restart (preferred boundary)

- Phase A ran the coordinator with the injected failpoint `REMOTE_VERIFIED:before_effect`
  → real `InjectedCrash` **after** upload+verification, **before** DB commit.
  Journal after crash: `state=REMOTE_VERIFIED`, `remote.verified=true`,
  `db_commit.committed=false`, object key + media SHA recorded.
- Restart convergence: server-side commit executed via the accepted service
  (rows id 1×4), then the coordinator restart presented the **receipt**; the runner
  validates receipt ↔ journal payload equality (any mismatch refuses
  `DB_COMMITTED`), then converged `DB_COMMITTED → CACHE_CLEANED`.
- Result: same remote object, no duplicate blob/revision, journal + DB consistent.

## 10. DB authority state (final)

```text
media_blobs            1 row  (sha 2af63b4b…, 19,019,783 B, hevc 1920×1080, 9.288333s,
                               photos_edited_rendition, b2 / diveanalyzer-dev-media)
media_revisions        1 row  (video_uuid 42D80813…, edit fingerprint 80b41e83…)
caption_revisions      2 rows (18d6377f… then 2c11f584…; append-only history preserved;
                               shadow parity exact_equal=t on both)
ingest_object_state    1 row  (state DB_COMMITTED, verified=t, environment=dev)
```

Legacy tables untouched: 0 `dives`, 0 `captioned_media_catalog` rows for the canary
uuid; `media_jobs` unchanged (4357 pre-existing rows); legacy serving/paths byte-identical.

## 11. Cache cleanup

- Temp bytes removed only after `remote.verified AND db_commit.committed`
  (`object_ingest_tmp/` empty afterwards); free disk 19 GiB > 10 GiB guard.
- Nothing on B2 deleted; no legacy/Photos media touched.

## 12. Presigned GET + Range GET (future browser-seek evidence only)

- Short-TTL (300s) presigned GET: generated, **HTTP 200**, full 19,019,783 bytes.
  URL never logged.
- Range GETs via presigned URL: `bytes=0-1023` → **206**, `Content-Range: bytes 0-1023/19019783`;
  `bytes=10000000-10001023` → **206**; `bytes=19018759-19019782` (tail) → **206**.
- No production playback path modified.

## 13. Idempotence

- Unchanged rerun (terminal journal): coordinator converged instantly
  (elapsed 0.0s), **zero** B2 operations, object HEAD/ETag stable
  (`9b5b0a6650fe2fbbede3988c22be759d-3`, 19,019,783 B), DB counts unchanged.
- Server commit replay (same payload twice): identical ids (blob/1, media-revision/1,
  caption-revision/1, state/1), only `*_existed` flags flipped — no duplicate rows.
- Caption-only mutation (see §14): 0 media upload, 0 new blob/revision.

## 14. Caption-only mutation

- Maintainer changed ONLY the caption (no trim change):
  `107B | 7.5 | H:3 | drill:no-arms | note:à revoir` →
  `107B | 7.0 | H:3 | drill:no-arms | note:à revoir`
- Runner gate: edit fingerprint **unchanged** (`80b41e83…`) → mutation accepted;
  new caption SHA `2c11f5840efd6cef5ad9c482921639fc1ce1125e4bf32d3b6f8d1021b62b36b8`
  (49 bytes, exact), shadow SHA equal, parser result `null` (honest).
- Server result: `blob_existed=true`, `media_revision_existed=true` (id 1),
  **`caption_revision_id=2` (new)**, `ingest_state_id=1`. Old CaptionRevision (id 1)
  remains. Zero media upload.

## 15. Feature flag / rollback

- Production agent config (`state/config.yaml`) has **no `object_store` block** →
  defaults `enabled=false`; the canary runner refuses a config without an explicit
  object_store section, so the object-store path cannot be triggered by the
  production config or the LaunchAgent.
- The LaunchAgent ran continuously through the whole canary (pid 26457 unchanged),
  backend `/health` 200 throughout, legacy tables untouched (§10).
- Rollback = the flag was never on in production; nothing to revert. B2 media remains
  (deletion is out of scope; the DB, not the object store, is the authority).

## 16. Cost / transfer accounting (actual)

- Uploaded (PUT): 19,019,783 B (one object, one version — lifecycle "Keep all versions").
- Full GETs: 2 × 19,019,783 B (roundtrip verification + presigned test) = 38,039,566 B.
- Range GETs: 2 × 1,024 B. HEAD/presign/list: negligible.
- Storage footprint: ≈ 19.0 MB.
- B2 pricing (primary source, see SECURITY_V1): $6.95/TB-month, first 10 GB free,
  free egress up to 3× average monthly storage → estimated cost **$0** (deep inside
  the free tier).

## 17. Security findings

1. The first `diveanalyzer-dev-canary` applicationKey was exposed in a chat screenshot
   during credential installation → the key was used to complete the canary;
   **rotation (delete + recreate + re-inject) is recommended as an immediate
   post-canary human action.**
2. `mac-agent/src/queue.py` (dead code) shadows the stdlib `queue` module when
   `src/` is placed on `sys.path` ahead of the stdlib (observed with a diagnostic
   script; botocore import failed). The agent's own entrypoints are unaffected, but
   the module should be removed in a later packet (already listed in DEPRECATE_LATER).
3. All other P1 security commitments held: no secrets in Git/logs/reports, no
   presigned URL logged, private bucket verified against the real provider (§3),
   PII-free object keys, no destructive automation.

## 18. Durable evidence locations

- Journal/evidence (private, on the mac-server, NOT in Git):
  `/Users/Shared/services/data/media-node/object_ingest_state/42D80813-0D2F-4F75-92BB-F0648E7AA77E{.json,.evidence.json,.commit_input.json,.commit_receipt.json,.mutation_input.json}`
- Canary tooling (committed): `mac-agent/src/ingest/canary.py`,
  `backend/scripts/backbone_canary_commit.py`.
- Postgres rows: `media_blobs` / `media_revisions` / `caption_revisions` /
  `ingest_object_state` (ids 1,1,[1,2],1).

## 19. Commits (this packet)

- `d4c0c8a` P2 canary runner + server commit transport (rebased over concurrent science work)
- `ff8beea` live-preflight fixes (osxphotos 0.76.1 duration fallback, 401/403 denial probe, album alias)
- `dcf04e1` shadow repair (macOS 13+ introspected caption join) + refresh-shadow mode + tests (129/129)

## 20. Production mutations

NONE. PROD B2 resources created: NONE. Secrets added to Git: NO.
Scientific authorities mutated: NO (hurdle-identity thread's concurrent commits
preserved untouched).
