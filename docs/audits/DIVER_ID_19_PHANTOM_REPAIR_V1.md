# DIVER_ID_19_PHANTOM_REPAIR_V1

**Packet:** DIVE_ANALYZER_SUBJECT_RESOLUTION_V1 — Phase 1
**Date:** 2026-09-13
**Status:** PHANTOM_DIVER_REPAIR_GREEN
**Authorization:** Supervisor live-repair authorization (10 guard-rails), executed as specified.
**Branch:** `subject-resolution-v1` (off canonical `uiux-overhaul-pro-app` @ `c4c9cfc1ad0ab77ccd9bea02d75f1a2c5b7560c5`)

---

## 1. Root cause (proven)

`mac-agent/src/metadata.py` `_is_person_name()` (pre-fix) accepted any token that
starts with an uppercase letter, is 2–20 chars, and is alphabetic. The docstring
claimed `"JOHN" → False (all caps)` but the code did not enforce it. Production
captions are typed in ALL CAPS, so names (TOM, PAUL, FANNY, SARA, MAT) legitimately
match — but so did the diving annotation token **`RIP`** (rip entry).

Downstream, `backend/app/services/diver_identity.py::resolve_diver()`
exact-matches canonicalized person names and **auto-creates** a `Diver` row on
miss. Sync of the six captions below therefore created `divers.id = 19`
(display_name `RIP`, created 2026-07-10 11:40:25 UTC) and attached six dives to it.

`video_labels` contains **zero** `RIP` rows — the phantom exists only through the
dive-caption path.

## 2. Affected rows (durable pre-repair evidence)

Captured 2026-09-13 13:05 CEST from production `diving_analyzer_db`
(`docker exec dive-analyser-postgres-1 psql -U diving -d diving_analyzer_db`):

| dive_id | session_id | video_uuid | diver_id | diver name | raw_caption | person_name |
|---|---|---|---|---|---|---|
| 217 | 28 | A99CBAB1-0B1C-4147-AD6A-A1CEA13F05D1 | 19 | RIP | `101C M SYNC RIP` | RIP |
| 1919 | 28 | 29F7FDC3-8E38-4A36-B697-D807E895D51C | 19 | RIP | `101B M SYNC PBSR6 RIP` | RIP |
| 1957 | 28 | F1AF7C68-8410-4F08-A423-E43B939CA9EC | 19 | RIP | `101B G SYNC PBSR11 RIP` | RIP |
| 2169 | 134 | 01B7736F-83C3-4419-B936-2BA37F062846 | 19 | RIP | `101B G/P 5m RIP` | RIP |
| 2388 | 153 | 47174218-537C-4AF0-816A-FCAEFC596982 | 19 | RIP | `100A P 10m RIP` | RIP |
| 2713 | 165 | 6BA67E5E-C6A8-4A05-92C0-6615D3E24938 | 19 | RIP | `103B M/P 5m RIP` | RIP |

Precondition audit at mutation time:
- population of `diver_id = 19` in `dives` = **exactly these 6 rows** (verified `count(*) = 6`);
- all 6 had `diver_id = 19` (re-verified in-transaction before UPDATE);
- `divers.id = 1` exists: `Maxime` / canonical `maxime` / `is_primary_user = true` / active.

## 3. Deterministic target identity (→ diver_id = 1)

Product authority: unlabelled dives belong to the default athlete = the primary
user (Maxime, diver 1); `person_name` tokens are used to attribute dives to
*other* divers (TOM/PAUL/EMI/FANNY/SARA/MAT). `RIP` is not a person.

- **Session 28** (217, 1919, 1957): diver 1 owns 16 dives in the session, the RIP
  rows are SYNC-flagged (`is_sync = true`) → default-athlete convention applies.
- **Session 134** (2169): GT-verified chain (`target_chains_v1.json`, eval-only)
  identifies 2169's subject as Maxime.
- **Session 153** (2388): diver 1 owns 5 of 6 dives in the session.
- **Session 165** (2713): diver 1 owns 30 of 31 dives in the session.

## 4. Parser fix (guard-rail 1)

`mac-agent/src/metadata.py`:
- `RIP` added to `_is_reserved_label_token()` → `parse_video_label("RIP")` → None.
- `_ANNOTATION_TOKENS = {"RIP"}` checked in the dive-caption token loop **before**
  `_is_person_name()` → dive captions can no longer carry `person_name = "RIP"`.
- Docstring corrected to document that ALL-CAPS names ARE accepted (production
  convention); caps rejection was deliberately NOT the fix (it would break
  TOM/PAUL/FANNY/SARA/MAT).
- Regression tests added in `mac-agent/tests/test_metadata.py`:
  caption-RIP (3 variants incl. SYNC), label-RIP, and all-caps person names
  still parsing. **33/33 tests pass** (20 metadata + 13 audit).

**Deployment:** the running mac-agent service on `diveanalyzer-mac`
(`/Users/Shared/services/data/diveanalyzer/code`, process started 2026-09-10
21:40) still ran the pre-fix parser. Fixed `metadata.py` was verified identical
to canonical c4c9cfc pre-fix content (md5 `518e79d8…`), the fixed file (md5
`fcd40573…`) deployed, service restarted via
`launchctl kickstart -k gui/$(id -u)/com.diveanalyzer.agent` (new PID 12922),
and the live agent re-verified: `parse_dive_caption("101B G/P 5m RIP").person_name
is None`, `parse_dive_caption("101B P TOM").person_name == "TOM"`,
`parse_video_label("RIP") is None`. Pre-deploy copy preserved at
`/tmp/metadata.py.pre-repair-20260913` on the Mac host.
**New ingest can no longer recreate the phantom.**

## 5. Backup verification (guard-rail 3)

Policy: `ops/postgres-backup.sh` (pg_dump -Fc, AES-256-CBC + PBKDF2, key file
0600, sha256 manifest, off-host push), daily 03:15 cron (P9-C, BACKUP_AND_RETENTION_V1).

**Finding:** the daily cron had been failing since 2026-09-11 — the script lost
its exec bit (mtime 2026-09-10 21:48, during P4.3 reconciliation work):
`backup.log` shows 3 × "Permission denied". Remediated minimally:
`chmod +x` on the script, then one ad-hoc manual run (explicitly provided for by
the policy) executed 2026-09-13 13:14 CEST:
`20260913T111414Z.dump.enc` (3,900,976 bytes), in-script decrypt-verify OK,
sha256 `101fdb0a…a82c`, retention kept 5 / pruned 0, off-host push OK.
Cron is repaired for subsequent days.

## 6. Transaction (guard-rails 4–8)

Single explicit transaction (psql, `ON_ERROR_STOP`), atomic file
`experiments/subject_resolution/phantom_repair_v1.sql` (committed):

```
BEGIN;
  DO block:
    preconditions: 6 target rows exist; population of diver 19 == 6;
                   all 6 still diver_id=19; diver 1 = (Maxime, primary=true)
    snapshot:      temp table snap_19 = to_jsonb(dive) - 'diver_id' for the 6 rows
    UPDATE dives SET diver_id = 1
      WHERE id IN (217,1919,1957,2169,2388,2713) AND diver_id = 19
    GET DIAGNOSTICS rowcount == 6            → else exception
    6 rows now diver_id=1                    → else exception
    count(dives WHERE diver_id=19) == 0      → else exception
    snap_19 join: no column other than diver_id changed
      (IS NOT DISTINCT FROM on jsonb minus diver_id) → else exception
COMMIT;
```

Execution log: `BEGIN → DO → COMMIT` (all invariants silent-pass; rowcount
exactly 6). No `updated_at` or any other field changed (no triggers exist on
`dives`; verified post-commit: 2169 `updated_at` still `2026-07-20 10:34:31.956626`).

Note: a first attempt failed cleanly inside the transaction
(`GET DIAGNOSTICS ROW_COUNT` inside a DO block does not see a prior top-level
UPDATE; it returned 0, the invariant tripped, and the transaction rolled back —
guard-rail 8 behaved exactly as specified). The script was restructured to
EXECUTE the UPDATE inside the same block and re-run.

## 7. Post-commit verification (guard-rail 9)

Independent re-read:

| dive_id | diver_id after | raw_caption | person_name |
|---|---|---|---|
| 217 | 1 | `101C M SYNC RIP` | RIP (column untouched) |
| 1919 | 1 | `101B M SYNC PBSR6 RIP` | RIP |
| 1957 | 1 | `101B G SYNC PBSR11 RIP` | RIP |
| 2169 | 1 | `101B G/P 5m RIP` | RIP |
| 2388 | 1 | `100A P 10m RIP` | RIP |
| 2713 | 1 | `103B M/P 5m RIP` | RIP |

- `dives WHERE diver_id = 19` → **0 rows**
- diver 1 population: 2511 → 2517 (+6)
- captions and all other fields byte-identical (jsonb snapshot check)
- **Dive 2169 re-validated** through the app layer: `d.diver_id = 1`;
  `resolve_diver(db, 'RIP')` still returns the existing (now orphaned) diver 19 —
  expected: the phantom diver row was deliberately not touched (guard-rail 10).
- Tests: 33/33 pass (`mac-agent/tests/test_metadata.py` +
  `experiments/subject_resolution/test_subject_resolution_audit_v1.py`).

## 8. Phantom diver row (guard-rail 10)

`divers.id = 19` (display_name `RIP`, canonical `rip`, active, created
2026-07-10 11:40:25.685889 +0.17s after diver 1) is now **orphaned**:
0 dives, 0 `diver_aliases`, 0 `user_diver_access`. It is **not deleted**;
physical removal or deactivation (`active = false`) is a separate decision.

**Known residual risk (documented, not fixed here):** `resolve_diver()` does not
filter on `active`, so any future code path that feeds `person_name = "RIP"`
(e.g. re-importing a historical JSON export containing `person: "RIP"`) would
re-attach dives to diver 19. The mac-agent parser fix blocks the live ingest
path; backend-side name deny-listing or `active` filtering in `resolve_diver`
is recommended as a follow-up hardening, out of this packet's authorized scope.

## 9. Gate

**PHANTOM_DIVER_REPAIR_GREEN** — all 10 supervisor guard-rails satisfied,
6 rows repaired in one transaction, zero collateral change, parser fixed and
live, backup fresh + readable, orphan documented.
