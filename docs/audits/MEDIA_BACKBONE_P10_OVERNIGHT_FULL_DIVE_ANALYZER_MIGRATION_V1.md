# MEDIA_BACKBONE_P10_OVERNIGHT_FULL_DIVE_ANALYZER_MIGRATION_V1 — Durable Audit

> Task packet `MEDIA_BACKBONE_P10_OVERNIGHT_FULL_DIVE_ANALYZER_MIGRATION_V1`.
> Executed UNATTENDED OVERNIGHT 2026-09-10 → 2026-09-11 on top of the accepted
> P9 state (canonical HEAD `2fa9187fc417ae8228db568954c4b5bfae276869`,
> fresh-verified on server + Mac before any change).
> Verdict: **FULL_RECOVERABLE_CORPUS_GREEN** — every real recoverable Dive
> Analyzer media identity (2799/2799) now has verified PROD bytes, a truthful
> MediaRevision baseline and a resolved caption baseline. 6 historical
> synthetic TEST identities are permanent residuals (no recoverable media
> exists behind them).
> Absolute counters: **B2 delete/hide = 0; legacy media deleted = 0;
> Photos assets deleted = 0; science mutated = NO; secrets in Git = NO;
> UserDiverAccess rows created = 0; AppUsers created = 0.**

## 1. Fresh preflight (verified)

- Canonical `mcauchy@192.168.1.57:~/dive-analyser` @ `2fa9187` (P9 accepted
  HEAD). Mac mirror + deployed runtime verified.
- Production flags unchanged: `USER_AUTH_ENABLED=true`,
  `B2_PLAYBACK_CANARY_ENABLED=true`, `object_store.enabled=true`,
  `dual_write.enabled=true`, `continuous_new_ingest=true`,
  `migration.enabled=true`.
- DB fresh: dives 2805 / dives-with-video_uuid 2805 / distinct video_uuid
  2805 (UNIQUE constraint ⇒ 0 duplicate references, 0 cross-diver conflicts)
  / divers 23 (all with video) / 15 MediaRevision rows (14 DISTINCT
  identities — ids 1 and 10 share video_uuid `42D80813…`) / 15 blobs /
  17 captions / 25 locations (15 verified PROD, 10 verified DEV) /
  exactly 1 real user (Maxime → diver 1 OWNER).
- PRE-P10 backup: `ops/postgres-backup.sh` live run →
  `20260910T200319Z.dump.enc`, 2,585,456 B, SHA
  `1fe1ef65e71696272ef5efa088a64af477d1c0d1439720f6d2600a47abb575b8`,
  readability gate pass, off-host Mac copy byte-identical.

## 2. Corpus definition (domain-driven, §2)

The inventory boundary is the DIVE ANALYZER DOMAIN — every dive row bearing
`video_uuid` — NOT the media_revisions table (15 rows covered only 14
identities). The P7/P9 "15/15 migrated" was MediaRevision-bounded; P10
closed the real gap: 2805 distinct deterministic video identities.

Fresh identity findings (fresh counts win, §2/§13/§14):

- `dives.video_uuid` is UNIQUE (duplicate references structurally
  impossible; fresh count confirmed 2805 = 2805).
- Only 210/2805 `dives.video_uuid` resolve in Photos. **2799/2805 resolve
  via `dives.video_filename` stem** (210 overlap; 1 case where both resolve
  to DIFFERENT assets). The historical era recorded the Photos asset UUID
  in `video_filename`; the DB-driven resolution rule
  (video_uuid → video_filename stem) is corroborated CORPUS-WIDE:
  all 2799 resolvable assets' current Photos descriptions contain the
  dive's `dive_code` (2799/2799, 0 mismatches).
- 6 rows are historical TEST fixture identities (empty filename: 2;
  `AAAA…`, `upsert-live-uuid…`, `maxime-default-name-…`, malformed hex:
  4) — no recoverable media.
- Source-vault (440 entries, all `osxphotos_single_asset_export`): ALL 440
  `agent_local_uuid` values equal the resolved fn stem (440/440) — vault
  identity mapping is deterministic. Freshness proof (edit recipe unchanged
  since export) accepted 201 as class C; the rest fell through to Photos
  (authority over convenience).

Classification (§12, sums exactly to 2805):
A 14 / B 0 / C 201 / D 0 / E 7 / F 2576 / G 1 / H 6 / I 0 / J 0.
Estimated corpus bytes 62.48 GB — far below the 1 TiB runaway guard (§8).

## 3. Tooling (branch `media-backbone-p10-full-corpus-migration-v1`)

Additive, tested:

- Backend: `GET /media/backbone/migration/domain_inventory` (domain-driven,
  read-only, agent-key gated, caption-free), `GET …/dive_caption/{uuid}`
  (per-item, G-class tie-break ONLY), media-only commit mode
  (`media_only` + `media_only_reason`; ledger state
  `MEDIA_VERIFIED_METADATA_PENDING`; caption data forbidden in that mode).
- Mac agent: `src/ingest/migration_full.py` — video_uuid-keyed durable
  journals (0600, atomic), §39 state machine, vault provenance firewall,
  targeted Photos EDITED-rendition materialization, streamed SHA roundtrip
  verification, 1 TiB runaway counters, 10 GiB disk guard, sequential
  one-item processing, checkpoints (25 items / 30 min), launchd one-shot
  (never a daemon component).
- `b2.get_streaming_sha`: full GET streamed through a hash sink (§29 — no
  second disk copy; verified mandatory requirement).
- `media_materializer` optional `library_path` (P10 fix: explicit `--library`
  skips osxphotos' "last opened library" XPC resolution, which BLOCKS
  indefinitely in one-shot launchd contexts; production daemon unaffected).
  P10 runtime additionally gained the P9 `natural_ingest_evidence.py`,
  `b2_inventory.py` and `sync_client._curl_get` in the deployed tree.
- Engine G-class rule: when video_uuid and video_filename resolve to two
  DIFFERENT Photos assets, the dive's recorded raw_caption (exact provider
  string, with the documented legacy .strip() boundary) is compared to each
  asset's description; exactly one match resolves deterministically, both/
  neither stays residual. NEVER a guess.

Tests: backend 9 pass (P10 suite: media-only commit semantics, idempotence,
no-access invariant, domain inventory boundary, dive_caption endpoint);
mac-agent 267/267 on the production venv (14 new engine tests: class A
skip zero-byte-ops, full roundtrip, media-only, verification failure
isolation, vault provenance firewall + freshness, content dedupe, disk
guard, journal terminality, G tie-break).

## 4. Execution (unattended overnight)

- RUN_MODE: UNATTENDED_OVERNIGHT; HUMAN_INTERACTIONS_REQUIRED: 0;
  TCC/Allow dialogs: 0 (one-shot ran inside the already-authorized
  GUI-launchd context: launchctl bootstrap gui, venv python — verified with
  a PhotosDB probe BEFORE any migration; NO new TCC request).
- AC power: ON (80% charging at start); `caffeinate -i -s` wrap;
  KeepAlive restart-on-crash; sleep prevented throughout.
- Canary (§42): 6 items (2 vault C + 2 Photos-local E divers 19/7 + 2
  Photos-iCloud F) → 6/6 CLEANED, roundtrip SHA equal, DB committed.
- Bulk (§43): full authorization exercised. First pass 2767/2767 CLEANED
  (16 h sequential, ~167 items/h, ~3.4 GB/h); second-pass refresh of the
  E class (7/7) and the G item (1/1) after the tie-break rule.
- iCloud retry: 0 timeouts needed (explicit `--library` fix; per-asset
  downloads 4-30 s). B2 retries: 0. Interactive deferrals: 0.
- Peak RAM: 719 MiB (PhotosDB index; all byte ops streamed/chunked).
- Min free disk: 10.92 GiB (guard never breached; macOS evicts downloaded
  originals as purgeable — free space oscillated 10.6-20 GiB).

## 5. Byte accounting (§56)

| Metric | Value |
|---|---|
| New PROD bytes uploaded (all roundtrip-verified) | 60,497,725,121 (56.35 GiB) |
| PROD full-GET verification bytes | 60,497,725,121 (every upload) |
| DEV source GET bytes | 0 (no DEV-only sources existed for the corpus) |
| Photos/iCloud materialized | 54,361,299,306 (50.62 GiB) |
| Vault source bytes | 6,136,425,815 (5.72 GiB) |
| Dedupe-avoided uploads | 216,084,468 (canary repair re-drive, PROD HEAD) |
| Final PROD B2 | 2,801 objects / 61,416,354,980 B (57.20 GiB) |
| B2 storage economics | ~57.2 GiB ≈ 0.056 TiB ≈ **$0.36/month** at $6/TB-mo |

## 6. Final reconciliation (§51/§52)

- B2 (read-only LIST with least-privilege ingest key):
  **2,801 objects, 61,416,354,980 bytes; 0 malformed keys; 0 missing
  verified DB keys; 1 documented P4 preflight evidence object
  (`72d94c7f…bin`, 408 B) = the only non-media object; 0 unexplained
  orphans; nothing deleted or hidden.**
- DB: dives 2805; distinct video_uuid 2805; covered with verified PROD
  coverage **2799/2805 distinct identities** = **2799/2799 real recoverable
  assets (100%)**; blobs 2800 (2799 corpus + 1 historical second-ingest
  blob of `42D80813…`); revisions 2800; caption_revisions 2802;
  ledger `ingest_object_state` prod: 2800 DB_COMMITTED,
  **0 MEDIA_VERIFIED_METADATA_PENDING** (media-only path built + tested,
  never needed: every migrated item's caption authority resolved).
- Per-diver coverage (IDs only): diver 1: 2505; diver 7: 128; diver 20: 56;
  diver 14: 31; diver 9: 17; diver 18: 12; divers 11/17: 9 each;
  diver 19: 6; divers 22/23(diver id 22): 6; divers 4: 4; diver 8: 3;
  divers 13/2/3/5/6/10/12/16/21/24: 1-2 each — every diver's real media is
  covered; the 6 uncovered identities are all synthetic test rows
  (5 diver 1 + 1 diver 20).
- Authorization regression (§44): migrated non-owner items (divers 19/7) —
  B2 storage exists; Maxime playback → 404 DENIED; unauthenticated → 404/401.
  Maxime's OWN migrated item → 302 → presigned B2 (GREEN). Proven:
  **storage existence ≠ authorization.**

## 7. Idempotence / restart (§50/§41)

- Second FULL pass (A,C,E,F classes; all 2798 journal-bearing items):
  **0 uploads, 0 verification GETs, 0 source reads, 0 Photos
  materializations, 0 commits, 0 duplicate rows** (2784 terminal + 14
  already-PROD skips).
- Crash-resume: video_uuid-keyed journals + KeepAlive restart; during the
  canary repair the engine re-verified PROD evidence via HEAD + dedupe
  before re-driving (no blind trust of a journal `uploaded` state).

## 8. Residuals (explicit, §47/§48/§49)

| Item | Class | Disposition |
|---|---|---|
| 6 synthetic test fixture rows (empty filename ×2, `AAAA…`, malformed hex, `maxime-default-name-…` diver 1; `upsert-live-uuid…` diver 20) | H | PERMANENT: no recoverable media exists; test rows, not media identities. No engine bypass. |
| `662C57F8…` (103B, diver 1) | G→migrated | RESOLVED deterministically: raw_caption "103B P/G 3m" exactly equals asset `20E90523…`'s description (the dive's recorded exporter asset); the other candidate `662C57F8…` ("103B P/M 3m", edited) is a DIFFERENT dive's rendition of the same capture. Migrated from the resolved asset. |

Retry pass: nothing to retry (0 retryable). Caption repair pass: nothing
pending (0 media-only commits).

## 9. Not done (deliberate, unchanged from P9)

- CONTINUOUS_NATURAL_INGEST: **PENDING** (passive capture deployed live and
  armed; `natural_ingest_evidence.py --latest` → NO_NATURAL_INGEST_EVIDENCE_YET;
  0 media jobs leased during the window). Not a prerequisite for the
  historical migration.
- EXTERNAL_ACCESS: unchanged (`EXTERNAL_ACCESS_PROVIDER_GATE`); no
  Cloudflare/DNS/domain/router work.
- LEGACY_DECOMMISSION: unchanged (`LEGACY_PHYSICAL_DELETION_READY = NO`);
  second independent replica still RECOMMENDED before any future physical
  deletion (§5a BACKUP_AND_RETENTION_V1); legacy cache/vault/Photos
  untouched (deletions = 0).
- Science data: untouched (worktree `hurdle-identity-repair` and all
  untracked science artifacts preserved; merge excluded untracked files).

## 10. Deployments + integration

- Backend container: P10 schema/router/service deployed + restarted
  (healthy; rollback proven pattern from P8/P9 reused). No DB migration
  files were needed (schema unchanged — existing tables only).
- Mac agent runtime: `migration_full.py`, `media_materializer.py`,
  `b2.py` (get_streaming_sha) deployed; P9 tools
  (`b2_inventory.py`, `natural_ingest_evidence.py`, `_curl_get`) restored
  into the deployed tree.
- Integration: branch pushed to canonical, merged `--no-ff` into
  `uiux-overhaul-pro-app`; canonical HEAD after P10 =
  `8a50d89e2cbbdffb4d96785f534ac024dde09cf0`. No force push; no history
  rewrite; untracked science artifacts preserved.
- Durable artifacts (outside Git, 0600/0700):
  `/Users/Shared/services/data/media-node/p10/{full-corpus-inventory.json,
  migration-plan.json, migration-final-summary.json,
  migration-residuals.json, migration-journals/ (2799),
  migration-checkpoints/}`. No full captions in the generic inventory.

## 11. Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P10` — recommended next:
media-backbone P11 (a) decide the H-fixture rows (purge or document),
(b) second independent replica decision before any legacy physical
deletion, (c) external-access hostname action (§7 EXTERNAL_ACCESS_V1),
(d) natural-ingest evidence closure.
