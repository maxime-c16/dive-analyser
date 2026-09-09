# MEDIA_BACKBONE_MIGRATION_PLAN_V1 — Phased Rollout & Rollback

Task packet: `MEDIA_BACKBONE_P0_P1_V1`. Status: P0/P1 COMPLETE (this branch),
P2 prepared, gates preserved.

## Phase map

| Phase | Scope | State |
|---|---|---|
| **P0** | Current-state audit, interface derivation, additive schema design | **COMPLETE** — `MEDIA_BACKBONE_CURRENT_STATE_V1.md`, `MEDIA_BACKBONE_TARGET_V1.md`, additive models + migration |
| **P1** | Ingestion state machine, ObjectStore abstraction + fake, B2 adapter (no credentials), content addressing, caption revisions, crash/idempotence tests, security review, EU research | **COMPLETE** — all tests green without cloud resources |
| **P2** | ONE real canary clip through the full verified-ingest flow into the DEV bucket | PREPARED — blocked on human/provider gate |
| **P3** | 5–10 clip queue through the same flow, still canary-only, legacy untouched | future |
| **STOP** | Mandatory stop-and-review before any production-facing change | — |
| **P4** (future) | Production dual-write (legacy sink + B2 PROD) behind flags | NOT STARTED |
| **P5** (future) | B2-backed athlete playback via short-TTL presigned GET | NOT STARTED |
| **P6** (future) | Default serving from B2 (cache becomes fallback) | NOT STARTED |
| **P7** (future) | Historical migration of existing media to B2 | NOT STARTED |
| **P8** (future) | Legacy local-media decommission | NOT STARTED |

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
  → shadow caption if available (PhotoKitCaptionProviderShadow; not blocking)
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

- No production dual-write before P4 authorization.
- No migration of existing production playback before P5+.
- No bulk-copy of historical media before P7.
- No removal of local media / deletion of production media (no automatic
  remote purge is implemented at all).
- No PROD B2 resource creation in this packet.
- No athlete-media public exposure (private bucket + presign-only future).
