# MEDIA_BACKBONE_MIGRATION_PLAN_V1 — Phased Rollout & Rollback

Task packet: `MEDIA_BACKBONE_P0_P1_V1`. Status: P0/P1 COMPLETE (this branch),
P2 prepared, gates preserved.

## Phase map

| Phase | Scope | State |
|---|---|---|
| **P0** | Current-state audit, interface derivation, additive schema design | **COMPLETE** — `MEDIA_BACKBONE_CURRENT_STATE_V1.md`, `MEDIA_BACKBONE_TARGET_V1.md`, additive models + migration |
| **P1** | Ingestion state machine, ObjectStore abstraction + fake, B2 adapter (no credentials), content addressing, caption revisions, crash/idempotence tests, security review, EU research | **COMPLETE** — all tests green without cloud resources |
| **P2** | ONE real canary clip through the full verified-ingest flow into the DEV bucket | PREPARED — blocked on human/provider gate |
| **P3** | 5–10 clip queue through the same flow, still canary-only, legacy untouched | **COMPLETE** — `MEDIA_BACKBONE_P3_READY_QUEUE_V1.md` (9-clip bounded allowlist queue; GUI-launchd materialization for iCloud-only assets; controlled failure/restart/quarantine/low-disk/mutation evidence) |
| **STOP** | Mandatory stop-and-review before any production-facing change | — |
| **P4** | Production dual-write canary (legacy sink primary + B2 PROD additive, flags + single-UUID allowlist, authenticated commit endpoint) | **COMPLETE 2026-09-09 — `P4_PRODUCTION_DUAL_WRITE_GREEN`** (one-canary cohort; broader PROD rollout blocked on the deleteFiles key debt — see P4 audit §3) |
| **P5** (future) | B2-backed athlete playback via short-TTL presigned GET | NOT STARTED |
| **P6** (future) | Default serving from B2 (cache becomes fallback) | NOT STARTED |
| **P7** (future) | Historical migration of existing media to B2 | NOT STARTED |
| **P8** (future) | Legacy local-media decommission | NOT STARTED |

## P2 runtime preflight (repair R7)

The packet-era hypothesis "DiveSensei Python Runtime.app / com.diveanalyzer.python-runtime"
has zero hits in the repository. The actually deployed runtime is the
Dive Analyzer LaunchAgent with the venv interpreter
(`deploy/com.diveanalyzer.agent.mac-media-01.plist`:
`/Users/Shared/services/data/diveanalyzer/venv/bin/python`, config
`/Users/Shared/services/data/diveanalyzer/state/config.yaml`, GUI/Aqua launch
context). Do NOT "fix" toward the stale reference; instead, before any canary
run, execute and RECORD a runtime preflight (read-only):

```text
1. Identify the exact process/runtime that will execute P2:
     host, user, launch context (launchd gui/<uid> vs interactive shell),
     process identity (pid path), interpreter binary + version,
     the exact config.yaml loaded.
2. Prove Photos/TCC access from THAT runtime (read-only):
     health-probe read of Photos.sqlite (mode=ro) succeeds,
     osxphotos read returns captions, heartbeat photos_access_status=ok.
3. Prove 'DiveAnalyzer Ready' album discovery from THAT runtime:
     osxphotos album lookup returns the album and contains the canary clip.
4. Prove targeted iCloud-only edited-rendition materialization from THAT
     runtime: single-UUID export of the canary asset completes and produces
     the edited rendition bytes (ffprobe provenance recorded).
```

Canary must record (preflight evidence file, no secrets):

```text
host, process identity, runtime/interpreter (+version), launch context,
Photos library identity (path + library UUID if exposed), materializer path
(osxphotos binary used), config file used
```

No raw SSH PhotoKit execution. If TCC access is not proven from the recorded
runtime, STOP at `HUMAN_PROVIDER_GATE` (interactive GUI rehearsal required),
do not attempt workaround launches.

## P2 canary (exact remaining steps)

Precondition — HUMAN/PROVIDER GATE (see below): EU-Central (or chosen region)
account exists, DEV bucket + bucket-scoped application key provisioned,
credentials installed as env vars on the mac-server agent runtime.

```text
Photos album:  DiveAnalyzer Ready   (explicit canary boundary)
ONE new clip   (prefer iCloud-only if practical)
Caption (complex):
  107B | 7.5 | H:3 | drill:no-arms | note:à revoir

Flow:
  manual trigger (CLI/one-shot invocation of ObjectStoreIngestCoordinator —
    chosen as the least invasive canary mechanism; no polling, no new album
    polling loop in the agent main loop)
  → Ready-album discovery: for the canary, discovery is a single asset picked
    manually (video_uuid known); album-based discovery is evaluated for P3
    (new album lookup via osxphotos album API — least invasive reuse of the
    existing PhotosReader; no UX freeze)
  → stable caption (CurrentStableCaptionProvider)
  → shadow caption if available (PhotosDbCaptionProviderShadow — direct
    Photos-DB SQLite read; real PhotoKit = NOT_IMPLEMENTED_CURRENT_RUNTIME;
    not blocking)
  → targeted edited rendition (existing MediaMaterializer, single UUID)
  → ffprobe/provenance (codec/width/height/duration recorded on MediaBlob)
  → local SHA (sha256, object key blobs/sha256/<2>/<sha>)
  → B2 DEV private upload (BackblazeB2Store)
  → full GET → remote SHA → equality (fail closed on mismatch)
  → additive DB commit (backend commit_verified_ingest → media_blobs /
    media_revisions / caption_revisions / ingest_object_state)
  → legacy untouched (no changes to media_jobs / upload / serving paths)
  → cleanup (temp bytes removed only after verified + committed)
```

Rollback at any canary point: `object_store.enabled: false` (or backend
`OBJECT_STORE_INGEST=false` once wired) → the legacy pipeline is byte-identical
to today (feature-flag tests prove disabled mode never constructs object-store
components).

## Historical migration doctrine (P7, future)

- Historical media migration is **Dive Analyzer DB-driven**: the DB
  (`dives` / `photos_assets` / `media_cache_entries`) is the manifest of
  historical media; migration walks DB rows (sha of existing artifacts known),
  re-uploads legacy renditions/source-vault sources, and records blobs.
- It is **NOT a full Photos-library crawl.** Photos is only re-consulted for
  assets whose bytes are missing locally (selective recall), consistent with
  the existing selective-media-recall doctrine.

## Explicit non-goals until later gates

- No broader PROD cohort before the `deleteFiles` key debt is resolved or
  explicitly re-approved (P4 audit §3: `P5_OR_BROADER_PROD_BLOCKER = YES`).
- No P5 athlete B2 playback; production playback remains legacy-only.
- No migration of existing production playback before P5+.
- No bulk-copy of historical media before P7.
- No removal of local media / deletion of production media (no automatic
  remote purge is implemented at all; the PROD canary blob and the retained
  synthetic preflight probe stay as durable audit evidence).
- No athlete-media public exposure (private bucket + presign-only future).
