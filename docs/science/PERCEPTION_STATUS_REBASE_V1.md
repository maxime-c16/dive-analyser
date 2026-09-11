# PERCEPTION_STATUS_REBASE_V1

> Strategic status rebase. Packet: `PERCEPTION_STATUS_REBASE_V1`.
> Created: 2026-09-11. Author: science supervisor thread (maxime@qwokka.fr).
> Type: evidence-synthesis only — **zero new detector / ReID / video-model inference,
> zero new labels, no protected holdout access, no Paris tuning, no new freezes.**
> Gate: `SUPERVISOR_REVIEW_AFTER_PERCEPTION_STATUS_REBASE_V1`

## Phase 0 — Git / authority reconciliation

Verified live on the canonical server (`mcauchy@192.168.1.57:~/dive-analyser`,
Debian 12, Python 3.11.2), 2026-09-11:

| Item | State |
|---|---|
| Canonical server HEAD | `f59b6f3` (P10 closure), branch `uiux-overhaul-pro-app` |
| Science V4 commits `f116558` (V3 closure), `ccf40b5` (V4 result) | **NOT reachable from canonical** — they live on branch `hurdle-prototype-v3` |
| `SCIENCE_V4_REACHABLE_FROM_CANONICAL` | **NO** |
| Worktrees | `~/dive-analyser` (canonical) + `~/dive-analyser-worktrees/hurdle-identity-repair` (detached `ef1e55e`, clean) |
| Mac mirror | remote `mac-mirror` = `divesensei@192.168.1.19:/Users/Shared/services/data/diveanalyzer-source-backups/dive-analyser-2026-09-05.git` (stale at `636b0dc`) |

Integration discrepancy handling (per packet): the V3/V4 HURDLE commits are
**accepted science history** from the previous packet (their reports and freeze-gate
verdicts are the durable record); they are used **read-only** here — the V4 freeze-gate
verdict was read via `git show hurdle-prototype-v3:runs/hurdle_prototype_v4/V4_FREEZE_GATE_VERDICT.json`.
They are NOT merged into the canonical application branch by this packet, and no
unrelated merges were performed. Drift notes (fresh evidence wins over stale text):
the canonical `docs/PROJECT_STATE.md` still names an older Mac mirror path and an
older HEAD (`e3c6cc4`) than reality; the deployed canonical is `uiux-overhaul-pro-app`
at the P10 head.

Concurrent media-backbone firewall: **respected.** B2 state was read from committed
reports/PROJECT_STATE only (see Phase 10). Zero B2 mutations, zero media operations.

## Phase 1 — Current perception inventory (implemented and frozen)

### Media / source layer
- **Active analysis representation:** `proxy_360p` (server `media/cache`, 239 files,
  59.8 MB). Frozen decision: `PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P`
  (`HQ_REPRESENTATION_DECISION_V1.json`).
- **HQ:** full-byte edited renditions recovered for all 14 authorized TRAIN +
  DEVELOPMENT_EVAL media (`highres_analysis_source_v1`, outside Git); 11
  PTS-equivalent + 3 deterministic temporal maps; zero quarantines after forensics.
- **PTS authority:** `PTS_AUTHORITATIVE_SEEK` (explicit seek before anchor reads).
- **Known mapping conflict:** **524** — `HURDLE_M_524_MAPPING_AUDIT_V1` verdict
  `524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED` (claimed HQ mapping NCC ~0.74–0.75 vs
  measured ≤0.32 exact / 0.64 exhaustive). 524 HQ boxes are NOT usable; the dive is
  excluded from identity evaluation.
- **676 map corrected:** prior direction-inverted map superseded; verified top-band
  crop x5.347, NCC 0.998.
- **New backbone tiers:** B2 PROD now holds the full real corpus as
  `photos_edited_rendition` objects (2799 real assets, 61.42 GB). **360p/720p tiers
  are NOT durably addressable in B2**; 720p "canaries" are non-durable tooling
  artifacts (1040 720p drops 7/339 frames, VFR). The 360p proxy tier remains
  legacy cache (rebuildable).

### Detector
- **Frozen:** D5-A (YOLOv8n, model SHA `82b420c4…`), `D5_A_FROZEN`; no retrain
  authorized; no D6 warranted.
- **Proposal floor:** floor_recall 97.1% (canary), floor coverage **100%** across all
  development dives; op_recall 88.2%.
- **Ranking failure modes:** D5-alone top-1 only 33.3% (canary anchors); on HURDLE,
  op-point top-1 is the target on just 0.5–51.8% of GT frames — static background
  distractors with top confidence outrank the diver (R1 reranker made this worse: −5.5pp).

### Target identity
- **Production/research canonical selector:** frozen D5 op-point top-1 (single best).
- **Experimental selectors:** V6 GT-free prototype (V3), A1 bounded-degree graph +
  component-seeded rollouts (V4), R4/R5 appearance tracklets — **all gate FAILED**.
- **Known failure mode:** GT-free ranking is gameable by coherent junk; component
  purity 0.10–0.42 → `IDENTITY_COMPONENT_CONSTRUCTION_STILL_PRIMARY_BLOCKER`.
- **Identity association needed by:** all HURDLE dives (5.2xxx / 1xxx-hurdle); 2169
  is the one measured near-clean case (top-1 0.963).

### Trajectory
- Construction: bytetrack + longest-x-conf selection → smoothed/interpolated cy series
  (`DEV_HURDLE_TRAJ_CACHE_V2`, `STANDING_TRAJ_CACHE_V2`).
- Valid continuous trajectories: 133, 311, 676 (with noise), 2387, 2169 (artifact at
  6.406s), 1040/2341/2541/2555/524 follow the wrong object for long runs (33–363 frames).
- 2541 EL coverage 0.9928 but errors ~15s (wrong-object trajectory, post-wc scan).

### Event Logic
- **Frozen:** `EVENT_LOGIC_V2_1` (29/29), `EVENT_LOGIC_V2_2`, `V3-C0` (A1+A2 bounded
  fixes, 14/14), `V3-D0` (development experimental baseline, 16/16). V3-E gate FAILED;
  V3-B/C1/D1/E1 not promoted.
- **FM1 (apex fallback): CLOSED** (V3-C0; 311 wc 3.530→0.027s). **FM2 (HURDLE
  prep_end): OPEN and identity-limited** (systematic per-frame selection failure,
  not oscillation). **FM3 (360p noise): OPEN** (676).
- Paris external (report-only): V2.1 to_err 1.685s / wc 0.183s; V3-D0 identical FM2.

## Phase 2 — Authorized evaluation corpus (durable authorities only)

No new labeling. Actual grouping (from human-annotated context + baseline metadata):

| Group | Dives |
|---|---|
| STANDING (annotated context) | 133 (301B), 311 (401C), 676 (301A), 2387 (5411C) |
| HURDLE_ORDINARY | 1040 (102C), 2169 (101B), 2341 (101B), 2541 (5111B) |
| HURDLE_DRILL | 2353 (101A, drill=true) |
| HURDLE_STRESS (screen recording) | 2555 (5132D) |
| HURDLE authority conflict | 524 (103B) — excluded from identity experiments |
| NO_TAKEOFF_GT | 2625 (excluded from HURDLE corpus) |
| ARMSTAND | 2661, 2680 (excluded) |
| INTERNAL_EVAL (pilot-protected, NOT accessed) | 160, 169, 191, 192, 848, 2281 |
| EXTERNAL canary (firewall, report-only) | IMG_1937.mov (2819) |

## Phases 3–4 — Scorecard (generated artifact)

Per-dive rows and family aggregation are in
`docs/science/PERCEPTION_STATUS_SCORECARD_V1.json` (sha256-provenanced sources).
Summary:

| Family | N | Proposal recall | Identity | Trajectory | Takeoff | Apex | Water contact | Overall |
|---|---:|---|---|---|---|---|---|---|
| STANDING | 4 | 4/4 PASS | 4/4 anchor-valid (full-video NOT_EVALUATED) | 4/4 | 2/4 | 2/3 | 4/4 | 2 PASS / 2 FAIL |
| HURDLE_ORDINARY | 4 | 4/4 (avail_floor=1.000) | 1/4 (2169) | 1/4 usable | 1/4 (2169 0.412s) | 1/4 | 1/4 | 0 PASS / 1 PARTIAL / 3 FAIL |
| HURDLE_DRILL | 1 | 1/1 | 0/1 | FAIL | FAIL (1.809s) | FAIL | FAIL | FAIL |
| HURDLE_STRESS (screen recording) | 1 | 1/1 (dense boxes) | PARTIAL (0.518) | PARTIAL | FAIL (2.614s) | FAIL (4.414s) | FAIL (7.480s) | FAIL |
| 524 authority conflict | 1 | UNKNOWN | NOT_EVALUATED | PARTIAL | FAIL (4.744s) | FAIL | FAIL | FAIL |
| NO_TAKEOFF_GT (2625) | 1 | PASS | NOT_EVALUATED | UNKNOWN | NOT_EVALUATED | no GT | PARTIAL | NOT_EVALUATED |
| ARMSTAND | 2 | NOT_EVALUATED | NOT_EVALUATED | NOT_EVALUATED | — | — | — | NOT_EVALUATED |
| EXTERNAL Paris (report-only) | 1 | PASS | NOT_EVALUATED | PASS (GT-anchored) | FAIL (FM2 1.685s) | PARTIAL | PASS (0.183s) | PARTIAL |

Counts: 2 PASS, 3 PARTIAL, 7 FAIL, 3 NOT_EVALUATED (over the 15 recorded rows).
**MEASURED FAILURE vs NOT YET MEASURED:** HURDLE failures are measured (per-frame GT
chains, frozen baselines); ARMSTAND and the ~2793 non-annotated product dives are
NOT YET MEASURED.

## Phase 5 — STANDING / non-HURDLE rebase (mandatory)

Evidence (existing, frozen):
- **Identity:** all 4 STANDING dives are PERCEPTION_VALID at annotated anchor frames
  under D5-only selection (DEV_D5_ONLY_EVAL_V1; R1 reranker was the contaminant and is
  retired). Full-video GT-free identity was never classified for STANDING → partial.
- **Trajectory:** continuous caches exist for all 4 (op-conf coverage 58.4–89.2%,
  floor coverage 100%).
- **Takeoff/apex/water contact (frozen V3-C0/V3-D0):** 133 = 0.165/0.285/0.147s (PASS);
  311 = 0.059 / – / 0.027s (PASS, FM1 closed); 676 = 3.086/2.519/1.016s (FAIL, FM3);
  2387 = 2.148/1.964/0.161s (FAIL takeoff/apex).

Answer: the current system already produces scientifically useful results for
**2 of 4 STANDING dives** (133, 311) and is capability-complete on the family, but
2/4 dives fail Event-Logic takeoff at 360p. STANDING is the only family with any
end-to-end validity today. It is NOT yet a supported product capability (no raw-session
detection, no clip extraction, and 2/4 landmark failures).

## Phase 6 — HURDLE status (summary, not reopened)

- **Ordinary HURDLE:** proposal generation usable (100% floor availability);
  identity BLOCKING (top-1 correct 0.5–51.8% except 2169 0.963); Event Logic FM2
  downstream-blocked (`FM2_STILL_IDENTITY_LIMITED`). V4 freeze gate FAILED 0/4
  (V4_FREEZE_GATE_VERDICT), no repaired trajectories, historical V3-D0 replay
  re-verified byte-exact.
- **Screen-recording stress case:** 2555 — dense candidate boxes, top-1 0.518,
  longest wrong run 33; EL fails badly (to 2.614s / ap 4.414s / wc 7.480s).
  Confirmed stress case in V4 verdict.
- **524:** authority conflict confirmed (read-only); excluded from identity
  experiments until repaired.

## Phase 7 — Failure-family map (whole authorized corpus)

| Failure family | Affected dives | Blocks | New training? | New labels? | HQ/B2 helps? |
|---|---|---|---|---|---|
| DETECTOR_PROPOSAL_MISS | 0 measured | — | n/a | n/a | n/a |
| TARGET_IDENTITY (incl. DETECTOR_RANKING mechanism) | 5: 1040, 2341, 2353, 2541, 2555 | HURDLE Layer-2 trajectory + EL + FM2 | YES (learned discriminator) | No (GT chains exist) | Likely yes (3–4× diver pixel height; D5 floor unaffected) |
| TRAJECTORY_GAP | 2: 676, 2169 | confident EL landmarks on those dives | No (selection-linked) | No | Likely (1040 signal visible at HQ; 2169 missingness rises at 720p/HQ — mixed) |
| EVENT_LOGIC | 3: 676, 2387 (+Paris FM2) | takeoff landmark product quality | No | No | Partially (FM2 is identity-limited, not resolution-limited) |
| MEDIA_AUTHORITY | 1: 524 | identity experiments on 524 | No | No | Yes (authority repair is prerequisite) |
| UNMEASURED | 2625, 2661, 2680 + ~2793 product dives | everything | — | eventually | — |
| NONE | 2: 133, 311 | — | — | — | — |

## Phase 8 — Product prevalence

Safest available source (option 1): `DOMAIN_INVENTORY_V1.json` (repository report):
2803 dives, 168 sessions, 239 360p proxies; `hurdle_dives_approx = 156` (5.6%) via
hurdle-mandatory code group. **The caption grammar encodes no approach field**
(`dive_code [perf] [height] [SYNC] [SMACK|BELLY] [drill] [PersonName]`), and one
annotated counterexample (2387, 5411C, context STANDING) shows the code proxy is
imperfect in both directions.

**PRODUCT_PREVALENCE_UNKNOWN** (exact per-dive approach share is not derivable
from the current data model). Documented lower bound: ≥5.6% hurdle-mandatory.

## Phase 9 — Current product coverage estimate

- **SUPPORTED:** ~0 (no family is fully supported end-to-end at product level).
- **PARTIALLY_SUPPORTED:** STANDING family (2/4 dives scientifically usable).
- **IDENTITY_BLOCKED:** HURDLE (≥5.6% lower-bound share; ordinary + drill + stress cases).
- **UNEVALUATED:** the overwhelming remainder of the product corpus (~2793 dives).

Answer: we are **not blocked on one difficult subset** — we are **unevaluated on most
dives and blocked specifically on the HURDLE subset**, while a small STANDING subset
already works scientifically.

## Phase 10 — Media-backbone opportunity (read-only from committed state)

Backbone state (durable, from P10 audit): 2799/2799 real recoverable assets in
verified PROD (61.42 GB, roundtrip-verified, `$0.36/mo`), all-diver storage with
0 access rows; `rendition_semantics = photos_edited_rendition`. Continuous ingest
armed (`CONTINUOUS_NATURAL_INGEST = PENDING`); external access = PROVIDER_GATE;
legacy physical deletion NOT ready.

Architectural recommendation (not an experiment):

| Stage | 360p | 720p/HQ | Recommendation |
|---|---|---|---|
| Proposal detection | Sufficient (100% floor) | Unnecessary for frozen D5 | Keep frozen D5 on 360p |
| Identity | Current baseline; OSNet features discriminative | Likely material for a learned discriminator (3–4× pixel height) | Train on HQ-derived crops, run GT-free on both arms |
| Event Logic geometry | 360p noisy (FM3) | Better SNR where trajectory is correct | 360p first; HQ when trajectory authority is repaired |
| Pose / mask | Insufficient | Required | HQ renditions once durably addressable |
| Future biomechanics | Insufficient | Required | HQ + multi-rendition access via B2 |

## Phase 11 — Is 360p a real blocker today?

| Problem | Classification |
|---|---|
| Proposal detection | RESOLUTION_NOT_PRIMARY (target in floor proposals 100% at 360p) |
| GT-free identity (current) | RESOLUTION_NOT_PRIMARY (selection-dominated failure; appearance non-discriminative at 360p for ImageNet features, but OSNet features are; failure is ranking/construction, not pixels) |
| FM3 360p trajectory noise (676) | RESOLUTION_LIKELY_BINDING |
| Event Logic on wrong-object trajectories | RESOLUTION_NOT_PRIMARY (identity-limited) |
| Pose / mask / biomechanics | RESOLUTION_LIKELY_BINDING |

The earlier "HQ did not improve D5 → HQ useless" conclusion is explicitly rejected:
frozen D5 is calibrated to 360p; HQ remains valuable for label forensics, future
identity/pose/mask, and retrained perception (`NO_RETRAIN_AUTHORIZED` unchanged).

## Phase 12 — Core Detection V1 status

Fresh repository search (backend/app, experiments, docs/science) found **zero**
raw-session spotting / clip-extraction work (`NOT_STARTED`). Today's product ingest
assumes user pre-trimmed clips; the frozen D5 runs on already-trimmed proxies only.

**CORE_DETECTION_V1_STATUS = NOT_STARTED.**

## Phase 13 — Priority matrix (artifact)

`docs/science/PERCEPTION_PRIORITY_MATRIX_V1.json`. Weighted totals (higher=better):
CORE_DETECTION_V1 **4.00** > SUPPORTED_FAMILY_TEMPORAL_PIPELINE 3.75 >
TARGET_IDENTITY_V1_LEARNED 3.35 > MEDIA_QUALITY_PERCEPTION_REBASE 3.25.

## Phase 14 — Recommendation

- **PRIMARY_NEXT_MILESTONE = `PRIORITY_CORE_DETECTION_V1`** — raw-session dive
  spotting + rough full-dive clip extraction + recall measurement, emphasizing event
  recall, using the frozen D5 on 360p with the media backbone as source authority;
  audio/water-entry sound admissible only as a non-mandatory supplementary signal.
  Justification: it is the packet's North Star, family-agnostic (benefits the whole
  corpus rather than the ≥5.6% hurdle subset), has the lowest overfit risk among
  high-impact candidates, and its dependency (durable media access) just reached GREEN
  (P10). The scorecard shows nothing else moves product coverage further today.
- **SECONDARY_PARALLEL_LINE:** TARGET_IDENTITY_V1_LEARNED background line — assemble
  the crop/embedding dataset from existing GT chains (`HURDLE_TARGET_CHAINS_V1`,
  anchor authority) + the already-cached OSNet embeddings (579,709-key ocean);
  evaluation-only probes; no selector freeze. This resolves the only known Layer-2
  blocker cheaply and in parallel.

## Phase 15 — HURDLE decision

**`HURDLE_DEPENDS_ON_FUTURE_TARGET_IDENTITY`.** FM2 is identity-limited by
measurement (FM2 reclassification authority); further heuristic iteration is paused.

## Phase 16 — Training decision

**`LEARNED_TARGET_IDENTITY_JUSTIFIED_BUT_NOT_NEXT_PRIORITY`.** Scientifically
justified (frozen-feature discriminability AUC 0.902; GT chains labeled; all GT-free
gates exhausted), but project-level priority goes to Core Detection V1.

## Phase 17 — Labeling decision

**`NEW_LABELS_LIKELY_REQUIRED`** for the *recommended* milestone (Core Detection
V1): minimum kind = raw-session event-window annotations (dive start/end PTS) on a
small set of raw sessions to measure spotting recall. No collection in this packet.
(The secondary identity line needs **no** new labels.)

## Phase 18 — Stop-doing list

Without new evidence, do NOT repeat:
1. more HURDLE graph threshold tuning;
2. more handcrafted HURDLE targetness scorers (V2–V6 all gate-FAILED);
3. running frozen D5 directly on HQ/720p and treating the result as an HQ verdict;
4. further 2555-specific optimization;
5. 524 identity experiments before the media-authority conflict is repaired;
6. more V3-E-style Event Logic variants without scene-level context or repaired
   trajectories (`MORE_HURDLE_GT_REQUIRED` stands).

## Phase 19 — Roadmap rebase (2–4 milestones)

- **M1 — CORE_DETECTION_V1:** raw-session ENTRY spotting → rough full-dive clip →
  recall measurement (detect → extract). Minimal new labels.
- **M2 — TARGET_IDENTITY_V1_LEARNED:** learned target discriminator on M1 clips +
  existing GT chains; compares 360p/HQ once derived renditions are durably
  addressable (align groundwork).
- **M3 — SUPPORTED_FAMILY_TEMPORAL_PIPELINE + TAKEOFF refinement:** takeoff
  boundary refinement and Event Logic on confident trajectories; rough-clip →
  refined-clip product step.
- **M4 — POSE/MASK/BIOMECHANICS at HQ renditions** (measure → compare → interpret),
  gated on M2 and durable multi-quality access.

## Phases 20–23 — Freezes, implementation, tests, artifacts

- No new freeze of any kind created (detector / identity / Event Logic / model /
  trajectory authority all untouched).
- Implementation: `experiments/landmark_pilot/phase_perception_status_rebase_v1.py`
  (stdlib-only, deterministic aggregation; zero inference).
- Tests: `experiments/landmark_pilot/test_perception_status_rebase_v1.py` — 13 tests,
  13 passed, 0 failed (provenance, corpus, holdout firewall, no-Paris-tuning,
  no-inference, family aggregation, taxonomy, consistency, enums, no mutation).
- Durable artifacts:
  - `docs/science/PERCEPTION_STATUS_REBASE_V1.md` (this file)
  - `docs/science/PERCEPTION_STATUS_SCORECARD_V1.json`
  - `docs/science/PERCEPTION_PRIORITY_MATRIX_V1.json`
  - `docs/PROJECT_STATE.md` updated (PAUSE flag + next milestone).
