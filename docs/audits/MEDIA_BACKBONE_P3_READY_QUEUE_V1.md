# MEDIA_BACKBONE_P3_READY_QUEUE_V1 — Bounded Ready-Album Queue (DEV Canary) Report

Task packet: `MEDIA_BACKBONE_P3_READY_QUEUE_V1` (DIVE_ANALYZER_MEDIA_BACKBONE_V1,
continuation of accepted `MEDIA_BACKBONE_P2_CANARY_V1`, verdict `P2_CANARY_GREEN`).
Executed: 2026-09-09. Scope: DEV object-storage/canary path only. Verdict: **P3_COMPLETE**
(see §13 for the intake-gate recommendation).

## 0. Canonical base / integration

- Canonical base HEAD: `3adc1055a147124d00168f29e2c731432dec7db1` (branch
  `uiux-overhaul-pro-app`, verified fresh via SSH; P2-era PROJECT_STATE HEAD
  `35a1b053` was stale — fresh canonical state wins).
- Implementation branch `media-backbone-p3-ready-queue-v1` (worktree
  `~/.perso/diveanalyzer-media-backbone`, pushed to the canonical repo):
  - `04fb44f` P3 bounded queue runner + tests
  - `d647f94` live-run fixes (GUI-LaunchAgent materialization, receipt
    transport, fingerprint v2)
- Concurrent science work protected: server untracked annotation/landmark files
  untouched; the hurdle-identity worktree (`ef1e55e`) untouched; no
  force-push; merge will be fast-forward only.

## 1. Security prerequisite — key rotation

```text
KEY_ROTATION = PASS
- OLD key (diveanalyzer-dev-canary): revoked by the maintainer in the Backblaze
  console (attested; no old key material exists locally to re-test — nothing to
  clean, revocation is the security boundary).
- NEW key: installed at /Users/Shared/services/data/diveanalyzer/state/
  object_store.env (mode 0600, owner divesensei; exactly one credential file;
  no stale backups; no history leakage).
- Verification (no secrets printed): PUT/HEAD/GET/presign preflight green
  (0.27–0.59 s, synthetic probe deleted afterwards); bucket = DEV only;
  negative probes: list_buckets AccessDenied, create_bucket AccessDenied,
  write to diveanalyzer-prod-media denied (connection refused by B2).
- B2_KEY_SCOPE note: the key was created with the UI "Read and Write" preset,
  which includes deleteFiles in addition to listFiles/readFiles/writeFiles.
  This matches the packet's "or equivalent UI Read/Write permissions" clause;
  the adapter's delete path is unreachable from ingest code (P1 guard).
  Recommend a tighter custom-capability key at the P4 gate if desired.
```

Credential hygiene: obsolete local credential material: none found (single
env file, 0600). Chat history was NOT modified (per packet §2.2); revocation
is the security boundary.

## 2. P3 allowlist (explicit bounded authorization)

`DiveAnalyser Ready` contains 82 assets. ALBUM MEMBERSHIP != P3 AUTHORIZATION.
An explicit allowlist of 9 UUIDs was selected by read-only metadata inspection
(caption text never printed; hashes/lengths/categories only):

| UUID (8-char) | Filename | Category rationale |
|---|---|---|
| 42D80813 | IMG_1641.mov | locally available (only one in album); unicode accented caption (49 UTF-8 bytes); long caption (48 chars); edited; P2 canary re-entry |
| 966304C3 | IMG_1780.mov | edited; longest un-ingested caption (17 chars) |
| 7AB4E9FE | IMG_1780.mov | edited; short caption (9); iCloud-only |
| D9BD76BC | IMG_1780.mov | edited; caption 12 chars |
| ADF83F08 | IMG_1780.mov | edited; simple short caption (8) |
| 901A95AF | IMG_1829.mov | unedited; caption 11; iCloud-only |
| EB4ACB9E | IMG_1829.mov | unedited; shortest caption in album (6) |
| F2A9B8CC | IMG_1829.mov | unedited; caption 11 |
| BB513C7F | IMG_1829.mov | unedited; caption 11 |

Constraints honored: 5 ≤ 9 ≤ 10. IMG_1937.mov copies (36 assets) intentionally
NOT selected (science-canary clip; no science data was used for selection or
exclusion). All 81 un-ingested assets are iCloud-only (`ismissing=true`,
Optimize Storage), so the "locally available" diversity category is covered by
the P2 canary re-entry (also the only unicode/long-caption asset).

## 3. Allowlist guard (tested)

- Unit: >10 entries refused, duplicates refused, malformed UUIDs refused,
  packet floor (<5) refused with a distinct reason; album-intersection
  refusal covered (allowlist entry outside Ready album → exit 3).
- Live: an 11-UUID allowlist was refused at runtime:
  `"allowlist guard violation: 11 entries; hard bound is 1..10"`.
- Live check mode: `{"ready_album_size": 82, "allowlist_count": 9,
  "outside_album": [], "packet_floor_ok": true}`.

## 4. Queue implementation

`mac-agent/src/ingest/p3_queue.py` (new) on top of the accepted P2 primitives
(`ObjectStoreIngestCoordinator`, `CurrentStableCaptionProvider`,
`PhotosDbCaptionProviderShadow`, `MediaMaterializer` seam, `BackblazeB2Store`,
`IngestStateStore` JSON journal, P2 commit-transport/receipt doctrine):

- Modes: `check` (read-only guard), `queue` (sequential bounded run),
  `media-mutation` (§17 flow), `aggregate` (privacy-redacted manifest).
- Sequential: one active materialization/upload at a time; per-asset
  discover → caption → materialize → SHA → upload/verify → DB commit →
  cleanup → next. No second daemon; no automatic Ready-album processing.
- Per-asset: counting/injecting ObjectStore wrappers (ops/byte metrics;
  controlled failure injection), free-disk sampling, journal-history latency
  deltas, metrics JSON (0600) rewritten per run.
- Commit: P2 operator-tunneled transport (receipt-confirmed; the mac has no
  direct DB access). Phase 1 → `REMOTE_VERIFIED` + staged
  `<uuid>.commit_input.json`; operator pipes it through
  `docker exec -w /app -e PYTHONPATH=/app dive-analyser-backend-1 python
  /app/scripts/backbone_canary_commit.py`; receipt written back; Phase 3
  re-drive validates receipt ↔ payload and converges `DB_COMMITTED →
  CACHE_CLEANED`.

## 5. Runtime + TCC gate (bounded repair within auto-repair scope)

The 81 un-ingested assets are iCloud-only. The existing materializer exported
only placeholders (`--download-missing` without PhotoKit), and
`--use-photokit` failed from the SSH one-shot runtime even after the maintainer
granted the venv python binary Photos access in System Settings (PhotoKit
requires an Aqua/GUI session context). This is the P2-anticipated
`HUMAN_PROVIDER_GATE` situation; resolved WITHOUT weakening TCC:

- Maintainer granted Photos access (Privacy & Security) to
  `/Users/Shared/services/data/diveanalyzer/venv/bin/python` (the documented
  rehearsal step 3; grant persists per binary).
- New `materializer.use_gui_launchagent` path (P3-only opt-in in the canary
  config): each export runs as ONE transient `launchd` job in `gui/501` (the
  production agent's runtime context class), booted out after the export.
  Not a daemon; refuses interactive osxphotos prompts; hard timeout.
- Rendition selection refined: prefers the osxphotos `<name>_edited` file
  when present (edited-rendition doctrine), else largest passing file.

## 6. Queue results (initial run)

```text
DISCOVERED (album)  82
SELECTED (allowlist)  9
INGESTED              9   (8 new clips + P2 canary re-entry; 100%)
RETRIED               0
FAILED                0
QUARANTINED           0
DEDUPLICATED (live)   1   (see §8)
unique_media_blobs    9   (8 new + canary original; all byte-distinct)
```

Per-asset integrity: every upload verified by full remote GET:
`local_sha256 == remote_full_get_sha256` — **verified 9 / attempted 9 (100%)**.
Caption authority: `CurrentStableCaptionProvider`; caption SHA-256 over exact
provider bytes; no strip/normalization (P2 R1 doctrine unchanged).

Caption shadow parity aggregate (`PhotosDbCaptionProviderShadow`; real PhotoKit
caption shadow remains `NOT_IMPLEMENTED_CURRENT_RUNTIME`; no shadow promoted;
mismatches would not alter `caption_raw`):

```text
sample_count        9
stable_success      9
shadow_available    9
exact_equal_count   9   (exact_equal_rate = 1.0)
shadow_failures     0
mismatches          0
```

Per-asset diversity evidence (sizes/durations/frames from ffprobe provenance):
11,470,391–31,322,626 bytes; 8.28–12.39 s; 497–748 frames; 4 edited + 5
unedited; caption lengths 6–48 chars incl. the only accented caption.

## 7. DB authority state (final)

```text
media_blobs          10  (P2 canary + 8 new + trimmed canary re-ingest)
media_revisions      10  (9 assets + trim-mutation re-ingest id 10)
caption_revisions    11  (P2 2 rows + 8 new + §16 caption-only edit id 11)
ingest_object_state  10  (all DB_COMMITTED, verified=t, environment=dev)
LEGACY_PRODUCTION_PATH_MUTATIONS: NONE
BACKBONE_CANARY_DB_MUTATIONS: YES (additive tables only, as authorized)
```

## 8. Content dedupe (§14)

- Live initial run: no two assets resolved to the same SHA (byte-distinct
  renditions) — `deduplicated=0` in the initial run; no duplicate uploads
  occurred by construction.
- Live dedupe path proven separately: on re-ingest of already-uploaded
  content, the opt-in head-check (same key + same byte size) skips the PUT
  and the full-GET verification still runs fail-closed (21,601,174 B verified
  with 0 bytes uploaded). Synthetic-schema tests additionally prove the
  same-size-corruption case quarantines (fail closed).
- bytes avoided: 0 in the initial run (no duplicates existed); the dedupe
  mechanism itself is live-verified.

## 9. Unchanged re-entry (§15)

Exact same allowlist rerun after the full queue completed:
all 9 assets `already_committed_before_queue=true`, final `CACHE_CLEANED`,
**0 new MediaBlob / 0 new MediaRevision / 0 new CaptionRevision, 0 B2
operations (0 puts, 0 heads, 0 gets)**. Repeated again after all mutation
tests with identical zero-op results.

## 10. Controlled failure tests (live, one asset each; queue unaffected)

| Test | Asset | Evidence |
|---|---|---|
| §19 retryable PUT failure | 966304C3 | pass 1: injected first-PUT failure → retryable (`object_store_unavailable`, journal state unchanged); pass 2: re-PUT 21,601,174 B (idempotent same key) → verified → committed → `CACHE_CLEANED`; same blob SHA `8172dd34…`; exactly one successful logical upload |
| §14 live dedupe | 966304C3 | re-ingest with dedupe opt-in: 0 bytes uploaded, full GET verification only, converged |
| §21 quarantine isolation | D9BD76BC | corrupted verification GET (controlled wrapper; remote object untouched) → `QUARANTINED` (`verification_failed`, fail-closed, no commit); next asset processed normally; after release + journal reset: resumed → `CACHE_CLEANED`, same SHA `dfc3fd31…`, 0 re-upload |
| §10 low-disk guard | ADF83F08 | configured guard above free space → refused BEFORE materialization (`insufficient_disk`, retryable; journal `MEDIA_REQUESTED`); no dummy data filled; queue continued; real guard restored → resumed → `CACHE_CLEANED`, same SHA `764b1fd5…`, 0 re-upload |
| §20 queue restart | 7AB4E9FE | runner SIGKILLed mid-materialization (and once at caption capture); restart: journal resumed, re-materialized (osxphotos `--update` idempotent), same SHA `153d2579…`, receipt re-validated (no second commit), converged `CACHE_CLEANED`; committed assets skipped; no duplicate blobs/revisions |
| §16 caption-only mutation | 42D80813 | maintainer edited ONLY the caption in Photos; fingerprint unchanged (gate passed); same blob (existed), same MediaRevision (id 1), new CaptionRevision id 11 (append-only; old revisions retained); 0 media upload |
| §17 media trim mutation | 42D80813 | maintainer trimmed the clip in Photos; fingerprint changed (v2 gate); fresh re-ingest: materialized bytes 19,019,783 → 10,139,200; ffprobe 9.288333 s/580 frames → 5.158333 s/310 frames; new SHA `b712e2ea…` → new blob (existed=false), new MediaRevision id 10; OLD blob still PRESENT on B2 (both HEAD-verified); CaptionRevision NOT re-revised (caption itself unchanged since §16 edit) |

Process kill during queue: bounded P3 runner only; production LaunchAgent
never touched (its pid was stable through P2; not used in P3).

## 11. B2 privacy / presign / range (§24/§25)

With the rotated key and the new objects (representative object =
largest new blob `dfc3fd31…`, 31,322,626 B):

- Anonymous bucket LIST → **403** (denied).
- Anonymous object GET → **401** (denied).
- Bucket remains Private. No B2 deletion exercised on any P3 media (§23:
  no automatic delete anywhere in the runner; delete is unreachable from
  ingest code).
- Presigned GET (300 s TTL) → **200** (full 31,322,626 B; URL never logged).
- Range GET `bytes=0-1023` → **206**, `Content-Range: bytes 0-1023/31322626`.
- No production playback path modified.

## 12. Metrics (§26) — honest reconstruction note

Phase-1 per-pass metrics were captured per run but overwritten by the later
convergence runs of the same file (`p3_metrics.json` is per-run); the initial
file was snapshotted too late. Honest per-phase latencies below are
reconstructed from the journal history of the latest full chains (each asset
has at least one complete single-run chain from a controlled-test re-drive —
equivalent workloads) plus evidence-file materialization timestamps; the
initial-run `REMOTE_VERIFIED→DB_COMMITTED` gaps (177–233 s) were OPERATOR
tunnel wait (manual Phase 2), not system latency.

Per-asset (latest full chain, seconds):

| Asset | materialize | upload (PUT) | verify (full GET) | total (excl. operator wait) |
|---|---|---|---|---|
| 966304C3 (21.6 MB) | 21 | 5 | 2 | 28 |
| 7AB4E9FE (25.7 MB) | 17 | 4 | 2 | 23 |
| D9BD76BC (31.3 MB) | 12 | 0 | 3 | 15 |
| ADF83F08 (29.5 MB) | 30 | 0 | 3 | 33 |
| 901A95AF (11.5 MB) | ~5–30 (fast phase-1) | ~1 | ~2 | — |
| EB4ACB9E (15.9 MB) | ~5–30 | ~2 | ~1 | — |
| F2A9B8CC (13.8 MB) | ~5–30 | ~1 | ~2 | — |
| BB513C7F (17.2 MB) | ~5–30 | ~2 | ~2 | — |
| 42D80813 trimmed (10.1 MB) | 15 | 3 | 1 | 19 |

Aggregate (chains with full precision, n=5): materialize mean 19.0 / median
17 / max 30 s; upload mean 2.4 / median 3 / max 5 s; verify mean 2.2 /
median 2 / max 3 s. The four phase-1-only rows are bounded by the fast
phase-1 timeline (8 assets ≤ ~11 min wall clock end-to-end) but exact
per-phase values are not preserved — recorded as such, not invented.

Bounds: min free disk observed **20.28 GB** (> 10 GiB guard, never
approached); peak temp cache **275 MB** (single-asset sequential policy held;
temp cleaned after every commit; `object_ingest_tmp` empty between assets).

## 13. Cost (§27, DEV only)

```text
new stored bytes (initial 8 + trimmed blob)   176,719,468 B  (~176.7 MB)
total DEV store incl. P2 canary               ~195.7 MB (10 objects)
GET verification bytes (roundtrips + tests)   ~347 MB
range/presign/HEAD                            negligible (~1 KB + metadata)
B2 model: $6.95/TB-mo, first 10 GB free; free egress ≤ 3× storage
approximate monthly storage impact: $0 (0.2 GB, deep inside free tier)
athlete-production traffic: NOT extrapolated (out of scope per packet)
```

## 14. Ready-album UX finding (§22)

Evidence recorded, decision NOT frozen:

- `READY_ALBUM_AS_REQUIRED_ACTION` (current P2/P3 mechanism): worked as an
  explicit boundary; but the album currently holds 82 assets while ~81 are
  stale already-processed-or-never-picked clips — operational friction is
  already visible at this scale (selection requires metadata probing; a
  human "put in Ready" step per clip adds workflow cost), and album
  membership stayed stable through caption/trim mutations (it is NOT a
  semantic "done" marker).
- `READY_ALBUM_AS_OPTIONAL_OVERRIDE`: viable — allowlist ∩ album is safe and
  could become an operator override instead of the required boundary.
- `IMPLICIT_READINESS_PREFERABLE`: plausible — the production agent already
  treats caption presence as readiness; the backbone could adopt
  caption-present + not-yet-ingested as the implicit queue, with the album
  as override. The 82-member album size is the main argument that a
  required manual album step does not scale.

Recommendation to carry to the P4 gate: implicit readiness with album as an
optional override; do not freeze either way in code without that decision.

## 15. Repairs performed (auto-repair scope §32)

1. Shadow of P2 flow kept intact; new P3 runner added beside it (no rewrites).
2. Coordinator: additive content-dedupe opt-in (`skip_put_if_remote_present`,
   default OFF; P2 single-canary behavior unchanged) + journal flag
   `last_put_skipped_existing`.
3. `make_materialize_fn` config plumbing unchanged; P3 adds the
   GUI-LaunchAgent materialization opt-in (§5) + edited-preferred selection
   with size bounds.
4. Commit transport: full staged `extra` block (P2 evidence parity); staged
   `commit_input.json` persisted for receipt-confirmed restart convergence.
5. `media-mutation`: stale receipt/commit-input cleared on journal reset.
6. Edit fingerprint v2 (`canary.py`): adds SHA-256 of the Photos adjustment
   render plist (edit recipe) — v1 was blind to re-trims on already-edited
   assets with osxphotos 0.76.1 (duration unavailable → constant 0.0 input).
   Caption edits do not touch the recipe; historical evidence keeps the v1
   values recorded at capture time.
7. Interactive-prompt refusal in the export poller (stale export-db case).

## 16. Tests

- mac-agent suite (mac runtime, osxphotos present): **148/148**
  (129 P2-era + 15 P3 queue tests + 4 selection tests; stable through the
  fingerprint v2 change).
- backend `test_media_backbone.py`: **23/23** (server, container runtime).
- Unrelated pre-existing local-env failures on the MacBook Air
  (missing osxphotos / pytest-asyncio) — pass on the mac venv; matched against
  fresh canonical baseline.
- `git diff --check`: clean. Secret scan: no credentials/presigned URLs/
  caption text in Git or logs (greps over the diff; captions only in the
  private state dir + server DB, per doctrine). Large-media scan: no media
  files staged for commit.

## 17. Boundaries held

```text
LEGACY_PRODUCTION_PATH_MUTATIONS        NONE
BACKBONE_CANARY_DB_MUTATIONS            YES (additive tables only)
PROD B2 resources created               NONE
Secrets added to Git                    NO
Scientific authorities mutated          NO
Production dual-write/playback changes  NONE
Rollback status: production agent config still has NO object_store block
(feature flag off by construction); canary config separate; disabling =
stop running the P3 runner; nothing to revert in production paths.
```

## 18. Operational findings (summary)

1. 81/82 Ready assets are iCloud-only: the backbone's ability to handle
   iCloud-only media headlessly REQUIRES the GUI-launchd materialization
   context (or user pre-downloads). This is now implemented and proven for
   the DEV path; it is a key input to P4 design (agent runtime context).
2. The Ready album is a poor exclusive queue boundary at realistic sizes
   (§14); implicit readiness (caption-present + not-yet-ingested) with
   album override is the evidence-backed direction.
3. Edit fingerprint v2 required for real-world media mutation detection.
4. Sequential single-asset pipeline kept temp cache ≤ 275 MB and free disk
   never below 20.28 GB.
5. Duplicate imports (same filename families) are byte-distinct after Photos
   edits — dedupe remained available but unused on this sample.

## 19. Commits (this packet)

- `04fb44f` P3 bounded queue runner + tests (allowlist guards, sequential
  verified ingest, metrics, injections, mutation mode)
- `d647f94` live-run fixes (§15.1–7)
- (docs commit: this report + PROJECT_STATE + P2 terminology correction)

## 20. Production mutations (corrected terminology)

```text
LEGACY_PRODUCTION_PATH_MUTATIONS    NONE
BACKBONE_CANARY_DB_MUTATIONS        YES
```

PROD B2 resources created: NONE. Secrets added to Git: NO.
Scientific authorities mutated: NO.
