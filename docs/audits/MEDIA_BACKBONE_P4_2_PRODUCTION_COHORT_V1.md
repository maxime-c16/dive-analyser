# MEDIA_BACKBONE_P4_2_PRODUCTION_COHORT_V1 — Durable Audit

> Status: **P4_2_COMPLETE** — bounded production dual-write cohort GREEN.
> Date: 2026-09-09. Canonical pre-head `bba47b77ab5667345daf3edfeeca76e723b047cd`
> (branch `uiux-overhaul-pro-app`). Supervisor gate: review before any P5 work.
> Previous accepted states: `P4_PRODUCTION_DUAL_WRITE_GREEN`, `PROD_KEY_HARDENING_GREEN`.

## 1. Mission and boundary

Ran a bounded production dual-write cohort of **8 real NEW production clips**
(bounds [5, 10], target = 8) through the accepted P4 path:

```
existing production agent → legacy materialization ONCE → legacy result
→ stage/reuse the SAME checksum-validated canonical edited bytes
→ B2 PROD (content-addressed, private) → full remote GET SHA verification
→ authenticated backend commit (environment=prod) → durable journal/receipt
→ cleanup
```

LEGACY remained the primary operational path; B2 PROD remained an additive
durable copy; playback remained legacy-only. **No P5 authorization; no
playback change; no remote delete/hide operation of any kind.**

## 2. Fresh preflight (what was verified before any change)

- Canonical HEAD `bba47b77…` on `uiux-overhaul-pro-app` verified via SSH;
  concurrent science worktree `hurdle-identity-repair` (detached) and untracked
  science artifacts (`docs/science/localization_annotations_v1/D5_ANNOTATION_BATCH/`,
  `experiments/landmark_pilot/`) present and untouched throughout.
- Deployed production agent code (`/Users/Shared/services/data/diveanalyzer/code/src`)
  verified **byte-identical to canonical** (33 files, sha256 compare) before deploy.
- Docs read: PROJECT_STATE, CURRENT_STATE, TARGET, INGEST_STATE_MACHINE,
  SECURITY, MIGRATION_PLAN, P4 audit + P4.1 evidence JSON.
- Production key `diveanalyzer-prod-ingest-v2` remained the runtime credential
  (provider-reported capabilities exactly `listFiles, readFiles, writeFiles`,
  bucket-restricted to `diveanalyzer-prod-media`, P4.1 evidence unchanged).
- Baseline production DB (environment=prod): 1 `ingest_object_state` (canary,
  DB_COMMITTED), 1 media blob/revision row pair, 2 caption revisions.
- Flags started **OFF** (`object_store.enabled=false`, `dual_write.enabled=false`);
  daemon healthy; 0 autonomous B2 ingestion pre-arming.

## 3. Production allowlist (§6/§7)

Explicit allowlist of **8 UUIDs** (target), all in the `DiveAnalyser Ready`
album (Maxime's normal manual marker), all captioned with valid grammar, none
a PROD backbone lineage, none selected using scientific performance data:

| # | UUID (first 8) | file | adj | bytes | note |
|---|---|---|---|---|---|
| 1 | 606653E2 | IMG_1937.mov | false | 14,318,043 | iCloud-only |
| 2 | C3A7A952 | IMG_1937.mov | false | 33,980,362 | iCloud-only |
| 3 | 0EC8DDBE | IMG_1937.mov | false | 31,347,541 | iCloud-only |
| 4 | 901A95AF | IMG_1829.mov | false | 11,470,391 | locally available |
| 5 | F2A9B8CC | IMG_1829.mov | false | 13,811,585 | locally available |
| 6 | BB513C7F | IMG_1829.mov | false | 17,209,995 | locally available |
| 7 | EB4ACB9E | IMG_1829.mov | false | 15,937,716 | locally available |
| 8 | C27D4087 | IMG_1592.mov | true | 29,317,731 | edited; legacy poster/360p already ready |

The "IMG_1937.mov / IMG_1829.mov" copies are Maxime's multi-dive captioning
workflow (one caption per copy); verified **byte-distinct** (distinct SHAs and
sizes) and not referenced anywhere in the science corpus (grep-proven).

Reconciliation note (§24): clips 4–7 are 4 of the 10 P3 **DEV**-environment
lineages (committed to `diveanalyzer-dev-media` earlier today by P3). They are
NOT PROD lineages, so they satisfy the §7 selection rule; their P4.2 prod
commits content-dedupe onto the existing rows (see §8). **New-to-PROD
lineages: 4; dev-overlap re-verifications into the PROD bucket: 4.**

## 4. Allowlist guard (§6)

`validate_prod_allowlist` hardened from "exactly one canary UUID" (P4) to the
P4.2 bounded-cohort guard:

```text
5 <= len(allowlist) <= 10, all entries valid unique Photos UUIDs
any value outside [5, 10] → REFUSE TO ARM (ValueError at construction)
```

Implicit readiness (whole library / whole album / all captioned clips) is
structurally impossible: the count must be supplied explicitly. Tests cover
0/2/4/11/duplicate/malformed refusals and 5/8/10 authorizations
(`test_dual_write_p4.py`), wired through `Config._validate_dual_write_config`.

## 5. No-delete / no-hide firewall (§4/§23)

- New **static tests** (P4.2): ingestion-path modules (`coordinator.py`,
  `dual_write.py`, `states.py`, `state_store.py`, `p3_queue.py`,
  `media_jobs.py`) contain no delete/hide primitives
  (`delete_object`, `DeleteObject`, `delete_file_version`, `b2_hide_file`,
  `hide_file`); the ingest state machine contains no destructive state; the
  only delete-capable symbol remains the intentionally verbose
  `delete_object_explicit_operator_action` on store adapters with zero
  callers in ingest/orchestration code (its single historical caller is the
  canary `b2-preflight` operator diagnostic, which cleans only its own
  SYNTHETIC probe — never invoked in P2/P3/P4/P4.1/P4.2).
- Provider-level: the runtime key cannot hard-delete
  (`b2_delete_file_version` → 401, P4.1) and S3 `DeleteObject` was never
  called. **Delete/hide operations performed by P4.2: 0.**

## 6. B2 adapter repair (real production defect found and fixed by P4.2)

**Discovered live during the cohort** (exactly what this phase exists for):

- With the P4.1 least-privilege key, Backblaze B2's S3-compatible API returns
  **403 Forbidden — not 404 — for `HeadObject` on a MISSING object**
  (verified live three ways: HEAD existing → 200; HEAD missing → 403;
  LIST prefix → works). The P4-era adapter mapped only the 404 family to
  "absent", so every pre-PUT HEAD raised `object_store_unavailable` and
  drives parked at `REMOTE_UPLOAD_STARTED` (retryable — legacy unaffected).
  P4.1's preflight had only probed HEAD on an EXISTING object; this negative
  case surfaced first at cohort scale.
- Repair (bounded, `§31`): `BackblazeB2Store.head` now disambiguates 403 via
  a prefix `list_objects_v2` probe (listFiles is an authorized capability):
  proven-absent → `None` (ingest proceeds to PUT); proven-present-but-403 →
  fail closed; LIST probe failure → fail closed (raise). Fail-closed
  semantics preserved for genuine auth failures. Three new adapter tests
  (`test_head_b2_403_on_missing_returns_none`,
  `test_head_b2_403_on_missing_with_failing_list_fails_closed`,
  `test_head_b2_403_but_list_shows_present_fails_closed`).
- Recovery semantics validated live: stalled journals were re-driven via the
  one-shot run mode; staging copies were REUSED (zero new Photos
  materialization; put/get/commit exactly once per asset).

The same provider quirk affects GET-on-missing (`AccessDenied`); in the
verified-ingest flow GET only follows a successful PUT, so it stays a
fail-closed retryable error (unchanged behavior).

## 7. Cohort execution (legacy primary + additive B2)

- Legacy media jobs created through the **normal product request endpoint**
  (`POST /api/v1/media/{uuid}/request`, reason `p42_cohort`): 22 jobs
  (7 assets × poster/360p/720p + C27D4087 × 720p only — its poster/360p were
  already cached from July).
- Legacy result: **22/22 renditions eventually READY** for all 8 assets.
  606653E2's first two 600 s-capped export attempts failed
  (`osxphotos_export_timeout`) before the iCloud asset was local; after the
  cache warmed, retry requests succeeded (poster, 360p ready; 720p had
  succeeded earlier). Legacy success never waited on B2 at any point.
- Object-store leg: for every asset the dual-write hook staged a copy of the
  SAME legacy bytes (0.01–0.03 s local copy, off the legacy critical path;
  `extra_photos_materializations = 0` in every snapshot), then in background:
  evidence (exact caption + shadow parity `exact_equal` for all 8) → SHA →
  B2 PUT → full GET SHA equality → HTTP commit (environment=prod) → receipt
  0600 → cleanup. **8/8 verified_committed** (`CACHE_CLEANED`).
- One-materialization: the object-store leg NEVER triggered a Photos export
  (`extra_photos_materializations = 0` in all 8 cohorts' snapshots). Three
  iCloud-only assets were additionally pre-materialized into the production
  source vault by a bounded operator repair using the **P3-proven transient
  GUI-LaunchAgent export primitive** after the 600 s legacy caps burned
  twice (§6-era); the legacy path then resolved vault-first. For 0EC8DDBE the
  vault already held the asset (legacy itself imported it) so the repair
  exited without exporting (outcome `already_in_vault`).

## 8. Backbone DB audit (§24, environment=prod)

| Table | prod rows after cohort | Reconciliation |
|---|---|---|
| `ingest_object_state` | 5 (was 1) | canary + 4 new cohort lineages (606653E2, C3A7A952, 0EC8DDBE, C27D4087), all DB_COMMITTED |
| `media_blobs` (bucket=prod) | 5 (was 1) | canary + 4 cohort blobs |
| `media_revisions` (prod blob join) | 5 (was 1) | 1 per prod lineage |
| `caption_revisions` (prod-uuid set) | 6 (was 2) | canary 2 + 4 cohort × 1 |

Dev counts unchanged (10 ledger rows). The 4 dev-overlap clips committed
**idempotently with zero duplicate rows**: same video_uuid + same content
SHA + same caption SHA → `blob_existed / media_revision_existed /
caption_revision_existed = true` in their commit receipts (cross-environment
content-addressed dedupe exercised in production for the first time).
Their media bytes were nonetheless uploaded and fully GET-verified in the
PROD bucket (distinct content-addressed keys). B2 PROD bucket final state:
**10 objects** = 1 retained P4 synthetic probe (408 B) + 1 canary blob
(40,865,620 B) + 8 cohort blobs (167,393,364 B total). No legacy-table
migration; no DEV/PROD row mixing in the reported counts.

## 9. Idempotence and unchanged rerun (§13)

After all 8 assets completed, the complete allowlist was rerun unchanged
(one-shot run mode per asset): **8/8 `already_terminal`, `zero_new_ops`**;
DB counters byte-identical to pre-rerun; 0 new MediaBlob / MediaRevision /
CaptionRevision; **0 new B2 byte uploads** (metrics totals unchanged at
8 PUTs / 8 GETs / 8 commits); 0 duplicate legacy logical clips (`dives`
unchanged for the cohort). Unchanged-caption guard probe: `unchanged_caption`
no-op (exit path proven without mutation).

## 10. Natural mutations (§14/§15)

- Caption parity: `osxphotos_description_stable` vs
  `PhotosDbCaptionProviderShadow` — **exact_equal for 8/8** at capture.
- No natural caption edit occurred during the cohort window (8/8
  `caption_unchanged`); no controlled mutation was forced — the caption-only
  mechanism was already proven at P4 §32 (0 B2 upload, old revision
  retained) and its unchanged-caption guard path re-proven here.
- No production retrim occurred (not required — P3 proved media re-edit).

## 11. Retries, restart, backpressure (§16/§17/§18/§19)

- Real retries observed and recovered without any deliberate disruption:
  (a) the pre-repair B2 403-on-missing HEAD stall (all retryable, legacy
  unaffected, re-driven to convergence); (b) legacy 600 s export timeouts on
  the cold iCloud cache (jobs retried via fresh product-driven requests and
  succeeded); (c) one daemon restart mid-cohort (adapter deploy, 23:04)
  after which committed clips were skipped, pending state resumed via run
  mode, legacy loops stayed healthy, and no duplicate uploads/revisions
  occurred (per-asset `put_count=1`).
- Backpressure policy (repo-native, documented in code): **one active
  dual-write at a time**; triggers arriving while the slot is busy are
  REFUSED with a tiny bounded pending marker (`backpressure_skip` in
  `<uuid>.stage.json`) and **no staged media bytes retained** — staged
  full-media copies exist for at most ONE asset. Recovery is the bounded
  one-shot run mode. Observed live: backpressure skips for C3A7A952,
  0EC8DDBE, 901A95AF while 606653E2's B2 leg was active; all assets
  subsequently converged with zero staged-byte accumulation
  (`dual_write_staging` 0 B at close). Backpressure marker test added.
- Disk: minimum free disk 17.9 GB (guard 10 GiB); peak staged/cache bytes =
  one active staged copy + coordinator workdir copy (~2× largest clip,
  ≈ 68 MB peak); temp dirs at 0 B after cohort.

## 12. Metrics (privacy-safe, immutable snapshots)

Per asset (all snapshots under `object_ingest_state_prod/metrics/`, O_EXCL
immutable): uuid/provenance identity, materialization provenance
(reused legacy bytes), staged bytes, copy seconds, legacy completion, B2 PUT
bytes/latency, GET verify bytes, commit attempts, final state, free disk.
Cohort aggregates:

```
cohort size                 8 (4 new prod lineages + 4 dev-overlap)
legacy success              8/8 (22/22 renditions eventually ready)
B2 verified success         8/8 (local SHA == remote full-GET SHA)
eventual commit             8/8 receipts persisted; 4 new prod rows + 4
                            idempotent dedupe returns
retry rate                  0 deliberate; 3 assets experienced real
                            retryable failures, all converged
B2 PUT+verify+commit per asset: median 8.97 s, max 12.82 s (31–34 MB),
                              min 2.88 s (11.5 MB); 167.4 MB total
staging copy (legacy critical-path overhead) 0.01–0.03 s per job
upload throughput ≈ 167 MB cohort in ~65 s aggregate background work
free disk floor during cohort ≈ 17.9 GB (guard 10 GiB)
```

## 13. Privacy and playback firewalls (§22/§26)

- Anonymous LIST on the PROD bucket → **403**; anonymous GET of the canary
  object → **401**; anonymous GET of a cohort object → **401**. No public
  policy changes; nothing was made public.
- Playback: frontend media URLs, backend playback selection, cache priority
  and athlete browser behavior untouched; legacy playback verified working
  post-rollback (cache entry 2266 play → 200). B2 remains invisible to
  athlete playback. **Legacy playback regressions: 0.**

## 14. Ready-album UX observation (§25)

The explicit `DiveAnalyser Ready` album (83 assets) worked as the cohort
boundary with zero friction for this packet: the newest Ready members were
legitimate prepared clips with valid captions. Observation only; no
production UX semantics changed; the explicit-vs-implicit readiness decision
remains a separate future packet.

## 15. Rollback (§27)

After cohort + rerun evidence: `object_store.enabled=false`,
`dual_write.enabled=false` (allowlist retained in config but inert), daemon
restarted. Proven: 0 ARMED/dual-write log lines after restart; sync +
extractor + media polling loops healthy; backend health 200; legacy playback
200; **all 10 PROD B2 objects retained** (read-only LIST diagnostic). No
new object-store work possible while flags are off.

## 16. Security findings (§3/§28)

1. `diveanalyzer-prod-ingest-v2` remained exactly least-privilege
   (listFiles/readFiles/writeFiles, prod-bucket-scoped) throughout; no
   destructive capability was ever exercised.
2. **Pre-existing P4.1 synthetic objects are no longer in the bucket.** P4.1
   evidence describes two retained synthetic validation objects
   (`bc1fece7…` 784 B, `a5f2bc63…` 12 MB); a full LIST during P4.2 shows only
   the P4 preflight probe (72d94c7f, 408 B) and the P4 canary blob. P4.2
   performed no delete/hide (count 0); the disappearance predates P4.2's
   first list and was most likely external console cleanup by the
   maintainer. Flagged for reconciliation — P4.2 did NOT touch them.
3. Pre-existing (unchanged, flagged at P4.1): `diveanalyzer-dev-agent`
   remains an account-wide key with admin capabilities.
4. Secrets: none in Git, docs, logs, or reports; single 0600 env file
   unchanged; no presigned URLs emitted or logged in P4.2.

## 17. Tests

- mac-agent (production venv, authoritative): **171/171** (168 pre-existing
  + P4.2 allowlist-boundary tests, backpressure-marker test, 3 static
  no-delete/hide firewall tests, state-machine non-destructive test).
  Includes 20/20 P4 dual-write tests revalidated against the 5–10 guard.
- backend: backbone suites 35 passed / 1 pre-existing environment failure
  (static test reads agent files at a host-path that is absent inside the
  container — byte-identical pre-existing baseline; not P4.2-related;
  backend code is untouched by P4.2).
- `git diff --check` clean; secret scan clean; no media, Photos DB copies,
  captions, or presigned URLs committed.

## 18. Commits (canonical)

```
<code>  P4.2: bounded production cohort — prod allowlist guard 5–10 explicit
        UUIDs (REFUSE TO ARM outside), backpressure pending marker (bounded
        staged bytes), static no-delete/hide firewall tests, B2 adapter
        403-on-missing-HEAD repair with fail-closed LIST disambiguation +
        3 adapter tests; suites: mac-agent 171/171, backend backbone 35/36
        (1 pre-existing env failure)
<docs>  P4.2 closure: durable audit MEDIA_BACKBONE_P4_2_PRODUCTION_COHORT_V1,
        PROJECT_STATE P4.2 handoff, migration plan P4.2 COMPLETE
```

## 19. Explicit non-goals honored

No P5 athlete B2 playback; no B2 default serving; no historical migration;
no legacy decommission; no automatic remote deletion/hide (count = 0); no
local media deletion; no caption-authority change (PhotoKit caption path
still out of scope; shadow remains read-only NON-AUTHORITATIVE); no
science-layer mutation (detector/selector/Event Logic/HQ media/temporal
labels/annotations untouched — zero diffs in science paths); no whole-library
ingestion (allowlist only).

## 20. Verdict

All §21 production success targets met: legacy success 8/8 (with two legacy
renditions converged through product-driven retry), B2 verified 8/8,
eventual commit 8/8 (4 new + 4 content-deduped), duplicate uploads/revisions
on unchanged rerun 0/0, legacy playback regressions 0, automatic remote
deletes/hides 0. One real production bug (B2 403-on-missing HEAD under
least-privilege key) was discovered, repaired, and re-proven.

**P4_2_COMPLETE — PRODUCTION_COHORT_GREEN.** STOP before P5.
