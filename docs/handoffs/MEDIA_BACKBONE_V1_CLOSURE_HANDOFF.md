# MEDIA_BACKBONE_V1_CLOSURE_HANDOFF — Final Parent-Supervisor Handoff

> Task packet `MEDIA_BACKBONE_P11_FINAL_CLOSURE_AND_PARENT_HANDOFF_V1`
> (DIVE_ANALYZER_MEDIA_BACKBONE_V1 — FINAL CLOSURE).
> Executed 2026-09-11 on top of the accepted P10 state (canonical HEAD at P11
> start: `437b6af7f80dd8b0e68fc949671a7ae82434491b` — the perception-status
> rebase commit which preserved media-backbone P10 state read-only; P10's own
> final HEAD `f59b6f3c89e389e5203928a50f6ccdad5881e667` verified present in
> history).
> Verdict: **MEDIA_BACKBONE_V1_CLOSED_READY_FOR_PARENT_SUPERVISOR**.
> This document is self-contained: a fresh main-project supervisor thread
> needs NO chat history beyond this file plus the phase audits it cites.
> Absolute counters for P11: **B2 delete/hide = 0; legacy media deleted = 0;
> Photos assets deleted = 0; UserDiverAccess rows created = 0; science
> mutations = NONE; secrets added to Git = NO.**

---

## 1. Executive summary

**Why the migration was started.** Dive Analyzer's application media
(athlete dive clips) lived exclusively on machine-local storage: the Mac's
Photos library (with iCloud "Optimize Storage" eviction), the ingest vault,
and the server's legacy `media/videos` + `media/cache`. That is one
house-fire / one dead disk away from total loss of a decade-scale dataset,
and playback depended on LAN-local availability. The media-backbone
workstream (P0–P10) built a durable, content-addressed object-store backbone
on Backblaze B2 and migrated **every recoverable historical application
media identity** into it with full roundtrip byte verification.

**Final architecture (one line).** Apple Photos (human trim + caption) →
Mac agent (ingest/materialization/dual-write) → PostgreSQL (logical/business
authority) + B2 PROD bucket (durable bytes) → FastAPI server (auth/playback)
→ authenticated browser playback via short-lived presigned URLs.

**Historical migration result.** 2799/2799 real recoverable media identities
(100%) migrated to B2 PROD with verified bytes, truthful MediaRevision
baselines and resolved caption baselines. 6 historical synthetic test
fixture rows are permanent residuals (no recoverable media exists behind
them) — retained and documented, NOT purged.

**Current production runtime state.** Single production Mac agent daemon
running; backend container healthy; all backbone flags live:
`USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true`,
`object_store.enabled=true`, `dual_write.enabled=true`,
`continuous_new_ingest=true`, `migration.enabled=true`.

**What is now automatic.** Every new captioned Dive Analyzer ingest is
dual-written: legacy success + additive B2 upload with full remote SHA
verification, then a single DB commit (blob/revision/caption/location/
ledger). Authenticated playback can and does select B2 (presigned GET,
read-only bucket-scoped key). DB backup/restore policy is operational and
tested. No migration process is running (P10's one-shot completed; staging
temp dirs empty; second-pass dry run is a no-op).

**What remains intentionally legacy.** The legacy storage stack
(server `media/videos`, `media/cache`, vault, Photos) is retained as
fallback/source infrastructure. Nothing was deleted. External athlete
access is NOT active (provider gate). A second independent media replica
does NOT yet exist.

**Outstanding non-blocking future work (none are B2-migration failures):**
(A) continuous natural-ingest passive proof — PENDING; (B) external access
provider gate (owned Cloudflare domain/zone + hostname — a human action);
(C) second independent media replica (recommended before any future legacy
physical deletion); (D) legacy-decommission work (dry-run ready only);
(E) six synthetic fixture rows (domain/test-fixture hygiene debt,
retained + documented).

**Final canonical HEAD after P11 closure commit:** see §8 of this file
(the P11 closure commit on branch `uiux-overhaul-pro-app`).

---

## 2. Historical results (exact, reconciled 2026-09-11 from live state)

| Metric | Value | Evidence |
|---|---|---|
| `dives` rows | 2805 | live DB |
| dives with `video_uuid` | 2805 | live DB (UNIQUE ⇒ 0 duplicates) |
| distinct `video_uuid` | 2805 | live DB |
| divers represented (with video) | 23 | live DB |
| synthetic non-media fixtures | 6 | §4 below |
| real deterministic media identities | 2799 | 2805 − 6 |
| real identities verified PROD | **2799/2799 (100%)** | live DB: every real identity has ≥1 verified PROD location; 0 revisions without PROD |
| full logical coverage | **2799/2799** | revision + blob + verified PROD + caption all present per identity; 0 missing caption baselines |
| MediaBlob rows | 2800 | live DB (2,785 P10-created + 15 pre-P10) |
| MediaRevision rows | 2800 | live DB |
| CaptionRevision rows | 2802 | live DB |
| verified PROD locations | 2800 | live DB |
| verified DEV locations | 10 | live DB |
| total B2 real media objects | 2,800 | B2 LIST (2801 total incl. 1 evidence object) |
| total B2 bytes (media) | 61,416,354,572 | = Σ `media_blobs.byte_size` (byte-exact) |
| total B2 bytes (incl. evidence) | 61,416,354,980 | B2 LIST byte-exact |
| ingest ledger | 2,810 rows, all `DB_COMMITTED` (2,800 prod + 10 dev) | live DB |
| roundtrip verification | 2,785 P10 uploads each verified by full streaming GET SHA equality (57+ GiB verified in P10); 0 remote SHA failures; second-pass idempotence 0-op | P10 audit §5/§7 + journals |
| storage reconciliation | 2507/2507 OWNER revisions exactly-one-verified-PROD, 0 drift, ratio 1.0 (293 non-owner revisions verified via blob-location + B2 reconciliation) | live run 2026-09-11 |

**Source breakdown of migrated media** (P10 audit §5, durable):
Photos/iCloud materialized 54,361,299,306 B (50.62 GiB) + vault sources
6,136,425,815 B (5.72 GiB); DEV source GET bytes 0 (no DEV-only sources
existed for the corpus).

**Count accounting — RECONCILED (§36).** The exact equation:

```
2799 real identities
  = 2798 identities × 1 blob each
  + 1 identity (42D80813-0D2F-4F75-92BB-F0648E7AA77E) × 2 retained revisions
2800 blobs = 2785 (P10-created) + 15 (pre-P10: 9 dual-write-canary + 6 P7 DEV→PROD)
2800 revisions (append-only history; 1 identity has 2)
2800 verified PROD locations (exactly one per blob)
+ 1 evidence object (P4 preflight, 408 B, not DB-referenced by design)
= 2801 B2 objects / 61,416,354,980 bytes   [byte-exact vs provider LIST]
```

**Multi-revision identity (§4 — proven, EXPECTED_APPEND_ONLY_HISTORY).**
`42D80813-0D2F-4F75-92BB-F0648E7AA77E` (dive id 2838, code `103B`, diver 1):
2 MediaRevisions (ids 1 and 10), 2 distinct blobs (19,019,783 B and
10,139,200 B), both with verified PROD locations. Provenance: the SAME
Photos asset (`IMG_1641.mov`, `hasadjustments=true`) was re-trimmed by the
athlete between the two observations (2026-09-09 16:33 vs 18:07 UTC);
materialized durations differ (9.288 s vs 5.158 s) and edit fingerprints
differ. Both revisions are intentional append-only media history; both PROD
objects are intentional. Classification: **EXPECTED_APPEND_ONLY_HISTORY**
(no action; history must not be deleted to make counts aesthetically match).

---

## 3. Byte accounting — RECONCILED (§35 closure gate)

**The reported discrepancy (573,060,903 B) is explained exactly.** The
authoritative byte truth is DB ↔ B2 equality (byte-exact, re-proven 2026-09-11
by a fresh read-only B2 LIST against `media_blobs`). The P10 *metric*
`P10_B2_PROD_UPLOAD_BYTES = 60,497,725,121` is a surviving-run-counter
aggregation whose scope excluded three categories of physically-uploaded,
roundtrip-verified bytes:

```
AUTHORITATIVE EQUATION (byte-exact, re-proven 2026-09-11):

  FINAL_B2_BYTES        = 61,416,354,980   (B2 LIST)
  = PRE_P10_B2_BYTES      345,568,956     (P9 state: 15 media 345,568,548 + 1 evidence 408)
  + P10_MEDIA_OBJECTS     61,070,786,024  (2,785 new blobs = Σ media_blobs.byte_size of P10-created rows)

P10 PHYSICAL PUT RECONSTRUCTION (byte-exact, from durable journals/checkpoints):

  61,070,786,024 =
    216,084,468   (a) canary cohort, 6 items: PUT by the crashed first canary
                  process; the restart re-verified them via PROD HEAD
                  (journal dedupe=true; Σ byte-exact 216,084,468 — reported by
                  P10 as "dedupe_avoided", physically landed bytes)
  + 183,131,868   (b) 7 items uploaded by the 21:10–21:32 UTC process whose
                  per-process PUT counter was lost at the restart boundary
                  (journals CLEANED, byte-exact 183,131,868)
  + 60,468,819,741 (c) main overnight process cumulative PUT at its final
                  checkpoint (13:44 UTC)
  + 173,696,767   (d) main-process uploads after that final checkpoint
                  (crash-recovered via journals; no later checkpoint)
  + 29,053,180    (e) final same-day run: the G item `662C57F8…` resolved
                  deterministically (raw_caption "103B P/G 3m" ==
                  asset 20E90523 description), 1 object

METRIC SCOPE (exactly what 60,497,725,121 counted):
  = (c) 60,468,819,741  (surviving main-process counter)
  + 28,905,380          (a partial final-run counter snapshot)
  ⇒ EXCLUDED (the entire 573,060,903 gap):
      (a) 216,084,468 + (b) 183,131,868 + (d) 173,696,767
        + (e-sliver) 147,800 = 573,060,903  [byte-exact]

  Check: 60,497,725,121 + 573,060,903 = 61,070,786,024 ✓
         345,568,956 + 61,070,786,024  = 61,416,354,980 ✓
```

Root cause of the exclusion: the one-shot run's `StandardOutPath` log is
re-truncated on every launchd relaunch (KeepAlive restart-on-crash), so
per-process counters from crashed/restarted segments did not survive into
the closure summary. The bytes themselves were never lost — every one of the
2,785 new objects carries per-item journal SHA-verification evidence and is
byte-accounted in the bucket. Historical metrics are NOT altered; their
precise scope is documented here.

**Object count reconciliation (§8):**
```
PRE_P10 objects (16) = 15 application media (9 dual-write-canary-era
                       + 6 P7 DEV→PROD at 2026-09-10 18:04 UTC)
                     + 1 P4 preflight evidence object
+ P10 new physical objects (2,785; 0 dedupe-reused — all distinct content)
+ explained concurrent objects (0 — the final run WAS the concurrent item)
= FINAL objects (2,801)   [byte-exact vs fresh LIST]
```
Logical MediaRevision creation (2,800 rows incl. append-only history) is
distinct from physical B2 object creation (2,785 P10 objects); dedupe/reuse
avoided exactly 216,084,468 B of re-uploads during the canary repair
re-drive (PROD-HEAD short-circuit) — recorded, not re-counted.

**Durable ledger artifact:**
`/Users/Shared/services/data/media-node/p10/p11-b2-object-ledger.json`
(0600) — all 2,801 objects classified
(PRE_P10_APPLICATION_MEDIA 15 / P10_APPLICATION_MEDIA 2785 /
KNOWN_SYNTHETIC_EVIDENCE 1), totals byte-exact, 0 unexplained objects, 0
unexplained bytes.

---

## 4. The six synthetic fixture identities (§9/§10)

Freshly re-verified 2026-09-11 from the live DB. Each is a historical TEST
fixture row — domain/test-fixture hygiene debt, NOT a failed media migration.
**Policy: RETAIN + DOCUMENT (SYNTHETIC_NON_MEDIA_FIXTURE). Do not purge
during media-backbone closure; exclude transparently from media-backbone
coverage denominators; do NOT hide from general DB-health audits.**

| dive id | diver | `video_uuid` | provenance |
|---|---|---|---|
| 1728 | 1 | `8079F5E2-B58F-4031-BD8D-1C115D03A6E3` | empty `video_filename` fixture |
| 1803 | 1 | `C3F9EE4D-6AC9-407E-93D4-A5F2BA8B4DDF` | empty `video_filename` fixture |
| 1878 | 1 | `7F063331A24B41DBA02E9BAAD2509E3Dabc` | malformed-hex fixture |
| 1887 | 1 | `AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA` | `AAAA…` fixture |
| 1980 | 20 | `upsert-live-uuid-1234567890abcdef` | upsert-test fixture |
| 1981 | 1 | `maxime-default-name-uuid-1234567890ab` | default-name test fixture |

For each: production DB row exists (dives, created 2026-03-11/03-24, test-era
timestamps); zero `caption_revisions`; zero `ingest_object_state` rows; zero
backbone media; no Photos/source media exists (P10 engine classified all six
H — no Photos asset, no vault entry); no PROD B2 media required; no real
athlete media hidden behind the fixture (the six rows are the ONLY uncovered
identities in the domain; every diver's real media is covered). Created as
exclusion classification via this handoff + the P10 residuals artifact;
no new production schema field added.

---

## 5. Architecture (§29)

- **Apple Photos** — human trim + caption source (compact caption grammar).
  Never deleted by Dive Analyzer.
- **`caption_raw` / `CaptionRevision.caption_raw`** — exact provider string
  (osxphotos description), append-only caption history; legacy path strip
  behavior unchanged (documented boundary).
- **PostgreSQL** — logical/business authority (dives, media_blobs,
  media_revisions, caption_revisions, media_blob_locations,
  ingest_object_state, users/access).
- **B2** — durable application-media bytes; content-addressed keys
  `blobs/sha256/<2>/<sha>.<ext>`; PROD bucket private.
- **Mac** — ingest/materialization/control execution (single production
  LaunchAgent daemon, GUI domain, KeepAlive).
- **Server (deb-serv)** — API/auth/database/playback (FastAPI + Postgres 16
  + nginx, LAN-only).
- **Local cache/vault** — NOT B2 authority; rebuildable renditions and
  source-provenance storage.
- **Storage authority model:** MediaBlob = immutable content identity
  (SHA-256); media_blob_locations = physical replicas (unique per
  blob/backend/bucket/key); environment = storage/commit context (dev/prod);
  MediaRevision = logical edited-media history (append-only);
  CaptionRevision = append-only caption history. All re-proven from live
  schema + data 2026-09-11; no architectural changes, no regressions found.
- **Playback model:** authenticated session → server authorizes
  (OWNER-scoped) → 302 to short-lived presigned B2 GET (read-only key).
- **Authorization:** OWNER-based (`UserDiverAccess`); independent of
  storage existence (proven: B2 object exists for non-owner diver → Maxime
  playback 404; unauthenticated 401; owner 302).

---

## 6. Automatic future flow (§30)

Current normal path for every NEW captioned Dive Analyzer ingest:

```
new captioned Dive (Photos) 
  → Mac agent discovers (caption present + parses)
  → one edited-rendition materialization (vault-first; targeted Photos
    materialization with explicit --library only when needed)
  → legacy upload success (unchanged path)
  + additive B2 dual-write (content-addressed PUT)
  → full remote verification (streaming full-GET SHA equality)
  → single DB commit (blob/revision/caption/location/ledger)
  → authenticated B2 playback (302 → presigned GET)
```

The continuous-ingest trigger provenance capture is deployed live
(passive). **CONTINUOUS_NATURAL_INGEST = PENDING** — no real post-P7
natural ingest has been observed yet (`natural_ingest_evidence --latest`
→ NO_NATURAL_INGEST_EVIDENCE_YET, 0 media jobs during the window). It is
NOT proven live; it is an independent future operational observation and
does NOT gate historical-migration closure.

---

## 7. Safety / immutability (§31)

- B2 PROD bucket **private**; no public object URLs; all playback via
  short-lived presigned GETs (read-only, bucket-restricted key
  `003e2bb572cfba70…` = "playback" key, readFiles only).
- **No automatic B2 delete/hide** — invariant tested; P10/P11 operations = 0
  deletes/hides; Object Lock disabled (policy is no-delete at application
  level; retention artifact `ops/retention_policy_v1.json` invariant-tested).
- **Legacy retained** (server media/videos + cache + vault + Photos); zero
  deletions; legacy fallback routes intact (rollback revalidated P8/P9).
- **Ingest key** bucket-scoped (listFiles/readFiles/writeFiles on the PROD
  bucket only); **DEV source key** (if still present) scoped to the DEV
  bucket only; **old account-wide DEV admin key: revoked** (P4_1).
- **Science firewall:** no mutation to DiveSensei scientific media, detector,
  selector, Event Logic, HQ authority, annotations, or science worktrees
  (`hurdle-identity-repair` worktree intact; untracked science artifacts
  preserved; P11 commits touch docs only).
- **Backups:** PostgreSQL encrypted scheduled backup (daily 03:15 cron,
  AES-256-CBC+PBKDF2, readability-gated, off-host copy on the ingest Mac,
  restore test previously GREEN in isolated container with row-count +
  verified-PROD-location proof). B2 PROD media retained indefinitely in V1
  (no automatic delete/hide). Photos not deleted by Dive Analyzer. A second
  independent media replica is RECOMMENDED before any future physical legacy
  deletion (§5a BACKUP_AND_RETENTION_V1).

---

## 8. Closure state, artifacts, commits

- **P10_STATE_VERIFICATION:** fresh-verified 2026-09-11 — all reported P10
  numbers reproduced exactly from live state (counts §2, bytes §3, B2 LIST
  2801/61,416,354,980, flags live, auth regression live, ledger
  DB_COMMITTED).
- **Canonical pre-HEAD:** `437b6af7f80dd8b0e68fc949671a7ae82434491b`.
- **P11 commits:** one closure commit on `uiux-overhaul-pro-app` adding
  `docs/handoffs/MEDIA_BACKBONE_V1_CLOSURE_HANDOFF.md` (this file) and the
  PROJECT_STATE gate update. No code changes; no science changes.
- **Test results:** backend P10/commit suites 20/20 pass;
  P9 production-readiness suite 9 pass / 1 skipped / 1 env-only path
  failure (retention-artifact path resolves to `/` inside the backend
  container; artifact exists and is git-tracked in the canonical repo —
  pre-existing environment-only failure, unchanged from P9).
- **PROJECT_STATE gate (§33):** `MEDIA_BACKBONE_V1: CLOSED_AND_RETURNED_TO_PARENT_SUPERVISOR`.

---

## 9. What this closure statement does NOT imply

- legacy storage deleted — **NO** (retained; physical deletion NOT authorized)
- external athlete access active — **NO** (provider gate remains)
- natural continuous-ingest already observed — **NO** (PENDING)
- second independent media replica exists — **NO** (recommended only)

**DIVE ANALYZER MEDIA BACKBONE V1 is COMPLETE.** B2 PROD is the durable
application-media backbone; all recoverable historical application media is
represented and verified in PROD; new production media has continuous
dual-write wiring; authenticated playback can select B2; legacy remains
retained as fallback/source infrastructure; access authorization is
independent of storage existence; DB backup/restore policy is operational.

STOP — the media-backbone subproject ends here. The next thread belongs to
the MAIN DIVE ANALYZER SUPERVISOR.
