# CORE_DETECTION_V1_P0_P1 — Protocol & Results

> Packet: `CORE_DETECTION_V1_P0_P1`. Created: 2026-09-11.
> Gate: `SUPERVISOR_REVIEW_AFTER_CORE_DETECTION_V1_P1`.
> Strategic authority: `PERCEPTION_STATUS_REBASE_V1` — decision
> `PRIORITY_CORE_DETECTION_V1`, `HURDLE_IDENTITY_HEURISTIC_RESEARCH=PAUSED`.
> Code: `experiments/core_detection/` (bounded namespace; no HURDLE/Event Logic
> entanglement). Protocol constants pre-registered in
> `experiments/core_detection/protocol.py`.

## 1. Product north star

> Given a long raw diving session, detect every actual dive with very high
> event recall and automatically extract a rough clip containing the complete dive.

Priority order: (1) event/ENTRY spotting, (2) high dive-event recall,
(3) rough complete-dive clip, (4) only later TAKEOFF/boundary refinement.
P1 is explicitly NOT temporal-landmark research.

Metric philosophy: **missing a real dive is much worse than an extra candidate
clip.** Primary metric is EVENT RECALL; false positives are reported explicitly
(per session and per hour) but are secondary in this gate.

## 2. Phase 0 — canonical authority

Verified live on the canonical server (`mcauchy@192.168.1.57:~/dive-analyser`):

| Item | State |
|---|---|
| Canonical HEAD at packet start | `437b6af7f80dd8b0e68fc949671a7ae82434491b` (branch `uiux-overhaul-pro-app`) — matches the accepted rebase |
| Untracked | localization frame dumps + landmark_pilot helpers (left untouched) |
| Worktrees | `~/dive-analyser` + `~/dive-analyser-worktrees/hurdle-identity-repair` (detached `ef1e55e`, clean) |
| Mac mirror | `~/.perso/diveanalyzer-perception` at `437b6af` (fresh) |

## 3. Phase 0.1 — V3/V4 science history reconciliation

**Verdict: `V3_V4_HISTORY_CANONICALIZED`.**

The accepted HURDLE V3/V4 negative-result commits (`f116558` prototype-v3
closure, `ccf40b5` identity-v4) were reachable only from branch
`hurdle-prototype-v3` on the canonical server. A true `git merge --no-ff`
into the working branch was possible with exactly ONE conflicting file
(`docs/PROJECT_STATE.md`, both sides appended sections at the same anchor).
The merge was performed in the dedicated worktree
`~/.perso/diveanalyzer-core-detection` (branch `core-detection-v1`):

- both original commits preserved **verbatim with original SHAs** (provenance
  by construction, no cherry-pick rewriting);
- `docs/PROJECT_STATE.md` sections unioned (P5–rebase history + V3/V4 science);
- **no scientific conclusions altered; no HURDLE experiments rerun**;
- merge commit: `d968ad1` on `core-detection-v1`; `f116558` and `ccf40b5`
  verified reachable from the merge HEAD.

The merge travels with this packet's commit chain to canonical (Phase Q).

## 4. Phase A — raw-session media inventory

Sources inspected (read-only):

| Source | Finding |
|---|---|
| Server `~/dive-analyser/media/videos` (icloudpd original-size cache, album *Dive Analyzer*) | 176 files; **exactly one long raw session: `IMG_0543-7294485222.MOV`, 3892.35 s (64.9 min), 7.29 GB**; all other files ≤ 35 s (trimmed clips); 19 files are `IMG_0543*` variants of the same session |
| Mac ingest `media-node/sources/by_uuid` | 440 vault entries, all `osxphotos_single_asset_export`, ≤ 134 MB — trimmed single-asset exports, no long sessions |
| B2 PROD (`photos_edited_rendition`) | 2799 real assets — **edited/trimmed renditions only, by design**; no raw-session tier |
| Photos library (ingest Mac + local Mac) | ~188 videos > 2 min each, **originals NOT local (iCloud placeholders)** — recall currently impossible: the icloudpd container is absent on the server (only its cron + sync script remain; downloads dir empty) |
| Local disks (M2 Mac) | no large session videos |

**Session `IMG_0543-7294485222.MOV`** (session_media_id `IMG_0543-7294485222`):

- source: server legacy cache (icloudpd original-size download, album
  *Dive Analyzer*) — authorized project media;
- 3892.35 s, HEVC, 1920×1080 recorded with rotation metadata (portrait
  display), 60 fps nominal with VFR characteristics (per-clip `avg_frame_rate`
  denominators vary: 35175/599, 63300/1057, …);
- known dives: **5 captioned** (DB dives 2679 5122D-1m, 2681 101B-3m,
  2683 101C-3m, 2687 101C-3m, 2688 101B-1m) + 14 uncaptioned sibling clips
  (Photos trim variants of the same original).

**A1 verdict: `RAW_SESSION_CORPUS_PARTIAL`** — one fully authorized,
end-to-end recoverable raw session (64.9 min, 5 GT dives, dead time, ordinary
pool activity). Diversity gate (different days/camera placements) NOT met.
Thirteen additional long sessions exist in iCloud but are not currently
recalled (see `CORE_DETECTION_V1_CORPUS.json`
`candidate_sessions_pending_recall`). This is sufficient for a feasibility
P1 but NOT for a diversity claim.

## 5. Phase B — label recovery (before any human labeling)

**Key discovery:** the server cache file `IMG_0543-7294485222.MOV` is the
**raw original** of the session from which 19 Photos trim variants were made,
and 5 of those variants are **captioned dives in the Dive Analyzer DB** whose
`media_revisions.blob_sha256` are **byte-identical (SHA-256 verified) to the
local copies** and registered as verified PROD `photos_edited_rendition`
blobs in B2.

Therefore event GT is recoverable **deterministically**: align each captioned
clip against the raw session (strict thumbnail-signature matching) → the clip
window in session time is a verified dive window.

### B1 label authority classification (frozen in `protocol.py`)

| Class | Meaning | Use |
|---|---|---|
| `DIRECT_HUMAN_GT` | captioned clip (dive code in DB) + strict alignment RECOVERED | primary evaluation GT |
| `DETERMINISTICALLY_RECOVERED_GT` | uncaptioned clip + strict alignment RECOVERED | primary evaluation GT |
| `WEAK_LABEL` | relaxed/failed alignment, or uncaptioned assumption | diagnostics only |
| `UNLABELED` | no alignment | unused |

Strict verifier (all required): ≥4/5 sampled clip frames vote offsets agreeing
within 1.0 s; each vote NCC ≥ 0.90 with ≥0.05 margin over the next distinct
peak; refined local check NCC ≥ 0.85. Constants pre-registered
(`ALIGN_*` in `protocol.py`).

### B2 verdict: `NO_NEW_LABELS_REQUIRED_FOR_P1`

No human labeling was requested or performed.

## 6. Phase C — event semantics (frozen)

> **One event ≈ one actual dive** performed from platform/springboard into
> water. ENTRY (splash onset / water impact) is the primary spotting anchor
> because it is visually salient, but the event represents the dive, not the
> splash: `one splash ≈ always a dive` is explicitly rejected.

Edge cases documented (not over-designed): athlete already in water;
unrelated splash; other-lane swimmers; multiple people near the board;
camera shake; replay/screen recording; preparation without dive; dives close
together (refractory period 15 s merges split detections; a real
double-dive within 15 s would be one candidate — accepted for P1).

Matching semantics (pre-registered): a predicted event matches a GT dive when
`gt_start − 2.0 s ≤ event_time ≤ gt_end + 2.0 s` (interval intersection;
coarse GT windows are NOT pretending frame-accurate anchors). Each GT matches
at most one candidate (highest score wins); each candidate at most one GT.

## 7. Phase D — baselines

**Baseline V0 (primary) — visual entry/eventness.** Full-session decode ONCE
into a disk-backed grayscale thumbnail stream (2 fps, long side 480 px,
rotation-safe) → per-timestamp features:

- `water_diff(t)`: frame-difference energy inside the water band;
- `board_diff(t)`: frame-difference energy inside the board/launch band;
- `diff_energy(t)`, `brightness(t)`: diagnostics.

Eventness = `0.7·smooth(water_diff) + 0.3·smooth(board_diff)` (1 s
smoothing). Candidates: robust-z threshold (median + 4·MAD-sigma,
pre-registered) + 15 s refractory NMS. **No GT-derived search windows — the
scan covers the whole session.**

**Baseline V1 (optional) — audio splash transient.** Mono 16 kHz WAV →
0.25 s-hop log-energy onsets; robust-z threshold; fusion = max of visual-z
and audio-z per visual timestep. Audio is strictly supplementary: a session
with bad/no audio remains fully processable (V0-only path).

**D2/D5 role:** frozen D5 may be used later as a supplementary visual feature
(person presence / disappearance near entry), but target identity is NOT a
prerequisite — Core Detection must detect *that a dive occurred* without
solving *which athlete*. For this P1 cycle D5 was not needed (see §9).

## 8. Phase E/F — spotting + metrics (see RESULTS json for numbers)

Pipeline: `run_core_detection_v1.py` stages probe → scan → alignment →
features → V0 candidates → optional audio fusion → evaluation
(`event_metrics`, `timing_errors`, `containment_recall`, manifest, taxonomy).

Reported metrics: event recall, missed dives, precision, FP/session,
FP/hour, median + p90 timing error vs GT window center (diagnostic only —
coarse windows), full-dive containment recall, entry/preparation visibility
rates, excess clip duration.

## 9. Phase G — rough clip extraction

Pre-registered deterministic window: `[event_time − 8 s, event_time + 6 s]`.
Rationale: entry-anchored; 8 s pre-roll covers approach+hurdle+flight for
1 m/3m springboard dives; 6 s post-roll covers entry+resurface. The goal is
containment, not tight editing. Containment is evaluated against recovered
GT windows (`FULL_DIVE_CONTAINMENT_RECALL` primary).

## 10. Phases H–K — outputs, taxonomy, representation, gate

- Session manifest JSON per §H (candidates with event_time/score/rough
  window). Generated clips stay OUTSIDE Git (`~/.perso/core_detection_media`).
- Failure taxonomy applied to every miss/FP (observed categories only).
- Representation: 360p-class scanning (long side 480). Verdict recorded in
  RESULTS (`360P_SUFFICIENT_FOR_SPOTTING` / `HIGHER_RES_MAY_BE_REQUIRED` /
  `UNKNOWN`) — spotting-only, does not reopen the HQ representation freeze.
- P1 gate: pre-registered development target **event recall ≥ 0.90**
  (NOT a production SLA) with FP reported separately; statuses
  `CORE_DETECTION_P1_PROMISING` / `_PARTIAL` / `_NOT_READY`.

## 11. Phase L — target identity background line (prep only)

Lightweight inventory only (no training, no selector freeze):

- GT identity chains: `HURDLE_TARGET_CHAINS_V1.json`,
  `HURDLE_TARGET_ANCHORS_V1.json`, `HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json`
  (canonical, from the V3/V4 line now merged);
- OSNet cache authority: host cache 579,709 keys (1.0 candidate-ocean
  coverage), manifest `HURDLE_OSNET_EMBED_CACHE_V1.json` V1.1 (npz NOT in Git);
- HQ crop availability: 14 authorized TRAIN/DEVELOPMENT_EVAL media have
  full-byte HQ sources (`highres_analysis_source_v1`), 524 excluded
  (mapping conflict);
- grouped-by-dive evaluation design: existing D4/D4-A grouped protocol
  (`PHASE_I_GROUPED_EVAL_D2`, `PHASE_J_GROUPED_EVAL_D3`) is the template for
  the future `TARGET_IDENTITY_V1_LEARNED` line.

## 12. Phase M — holdout firewall

No FINAL_HOLDOUT, INTERNAL_EVAL (160/169/191/192/848/2281), or Paris data
was accessed. The only session used is the authorized server-cache raw
original `IMG_0543-7294485222.MOV` + its own derived clips. Test
`test_holdout_firewall_no_protected_ids` guards the corpus manifest.

## 13. Phase N — tests

`experiments/core_detection/tests/test_core_detection_v1.py` — 16 tests:
corpus existence/readiness, clip provenance (SHA), GT authority semantics,
full-session scanning (no GT windows), eventness selectivity, refractory
NMS, interval matching + tolerance edge, one-candidate-per-GT, FP
accounting (per hour), rough-window generation, containment (incl. short-clip
failure), audio optionality contract, manifest shape, taxonomy categories,
holdout firewall, HURDLE non-mutation (no landmark_pilot imports),
pre-registration freeze.

## 14. Compute / resource rules honored

Apple M2 only; `caffeinate -i -s` for the full-session decode; one raw
session at a time; disk-backed intermediates (thumbnail stream + WAV on
disk, memory-mapped/ndarray loads only); no model training; no >20 GB
memory workflow. Server remains canonical Git authority.

## 15. Results (P1 evaluation, single authorized session)

Full numbers: `CORE_DETECTION_V1_RESULTS.json`; per-candidate detail:
`experiments/core_detection/runs/session_IMG_0543/`.

### 15.1 GT recovery (verifier v2)

Of 19 derived clips: **10 RECOVERED** (5 captioned → DIRECT_HUMAN_GT,
5 uncaptioned → DETERMINISTICALLY_RECOVERED_GT), 9 WEAK (ambiguous
similar-dive clusters — diagnostics only), 0 FAILED. Two recovered clips
cover the same dive (both offset −1655.5 s) → **10 unique primary-GT dives**
after overlap merge, spanning session t ≈ 950–3719 s.

### 15.2 Event metrics (pre-registered thresholds, no tuning)

| metric | V0 visual-only | final (visual+audio) |
|---|---|---|
| event recall (target ≥ 0.90) | 0.50 | **0.90** |
| matched / primary GT | 5/10 | 9/10 |
| candidates | 36 | 106 |
| false positives | 31 (~28.7/h) | 97 (~89.7/h) |
| precision | 0.139 | 0.085 |
| median/p90 timing err vs window center | — | 4.0 s / 6.55 s |
| full-dive containment recall | 0.20 | **0.0** |
| preparation visible rate | 1.0 | 1.0 |
| entry visible rate | 0.2 | 0.22 |

The single remaining miss (GT window [2188.0, 2196.5], clip `IMG_0543.MOV`)
had the weakest evidence in the session: visual eventness peak 256 vs
threshold 276, audio onset z ≈ 3.5 vs 4.0.

### 15.3 Failure taxonomy (observed only)

- `VISUAL_ENTRY_NOT_SALIENT` — all misses: weak-splash dives whose
  eventness peak (144–256) stayed under the pre-registered robust-z 4.0
  threshold (276); audio fusion recovered 4 of 5.
- `UNRELATED_SPLASH` — FPs: predominantly low-score audio blips (median z
  6.4) plus large camera-handling transients in the first ~130 s and last
  ~200 s of the recording.

### 15.4 Representation verdict

`360P_SUFFICIENT_FOR_SPOTTING_WITH_CAVEATS` — 480 px grayscale thumbnails
reached the recall target with audio; failures are signal/threshold
problems, not resolution problems. Does not reopen the HQ representation
freeze.

### 15.5 P1 verdict: `CORE_DETECTION_P1_PARTIAL`

Rationale: the pre-registered recall target (0.90) was reached exactly, but
only with audio fusion (visual-only 0.50); precision (0.085) and full-dive
containment (0.0 — `event_time` anchors at the splash peak while the
pre-registered `[t−8 s, t+6 s]` rough window is evaluated against
clip-extent GT that includes the athlete's walk-in padding) fail the
"rough clip containing the complete dive" half of the north star.
Single-session corpus (PARTIAL readiness) limits generalization.

### 15.6 Deviations from the initial protocol

All registered before or at evaluation time; none tuned against final
metrics.

1. **Alignment verifier v2** — v1 raw-thumbnail NCC matching is
   undiscriminating in this static pool scene (global median NCC ≈ 0.99;
   top peaks verified visually to land in empty segments). v2:
   temporal-derivative signature votes (robust-z ≥ 6, NCC ≥ 0.10), offset
   clustering (1 s tolerance), path-score ranking, ambiguity margin ≥ 0.05,
   raw block-NCC floor ≥ 0.97; captioned clips accept cluster size ≥ 3.
2. **Audio fusion implementation fix** — the onset score is one-sided, so
   full-series median/MAD degenerate to 0 and smoothing dilutes sparse
   transients ~5×; robust stats now use the positive support, audio z is
   rectified at 0, and fusion is a per-visual-bin max without pre-smoothing
   (pre-registered "max of visual-z and audio-z" preserved).
3. **Band freeze** — `water_band [0.50, 0.66]`, `board_band [0.28, 0.48]`
   frozen from frame inspection at t = 1657 s before event-level evaluation.
4. **Server-side sha256 skipped** (timeout > 600 s); identity rests on
   exact byte size + local sha256 + ffprobe match.

## 16. Gate

`SUPERVISOR_REVIEW_AFTER_CORE_DETECTION_V1_P1` — verdict
`CORE_DETECTION_P1_PARTIAL`; decision requested on: (a) accept audio-fused
recall as the P1 signal and iterate on precision (audio gating / FP
suppression) next, (b) revisit the rough-window anchor (event start instead
of splash peak) for containment, (c) recall of the remaining iCloud-only
sessions to widen the corpus before further threshold work.
