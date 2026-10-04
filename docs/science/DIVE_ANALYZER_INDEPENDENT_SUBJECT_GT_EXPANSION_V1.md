# DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1

Packet: `DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1`
Gate: `SUPERVISOR_REVIEW_AFTER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1`
Date: 2026-09-20
Canonical base: `4f01003b4413a149f33eab0e32c2b30c9485ee86` (branch `uiux-overhaul-pro-app`)
Machine-readable artifact: `DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1.json`
Annotation plan: `SUBJECT_GT_LEVEL_B_ANNOTATION_PLAN_V1.md`
Annotation queue: `SUBJECT_GT_LEVEL_B_QUEUE_INDEPENDENT_V1.json`
New frozen authority: `docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_B_INDEPENDENT_V1`
Artifact SHA256: `dc958909435ad043a1284064b5dd6f85ca4b8eb365ed643289943f679c83a9df`

## 0. Verdicts (exactly one each)

| Question | Verdict |
|---|---|
| Independence gain (Phase 16) | **`INDEPENDENCE_GAIN_STRONG`** — sessions 8→13, athletes 2→4, 5 novel sessions, 2 new athletes, multi-person scenes |
| Bottleneck generalization (Phase 19) | **`SUPPORTED_REAL_MOVER_IDENTITY_GENERALIZES`** |
| Learning readiness (Phase 21) | **`IDENTITY_LEARNING_PILOT_JUSTIFIED`** |
| Preferred learning formulation (Phase 22) | **L0 — SUBJECT-CONDITIONED TRACK MATCHER** (design only, no training) |
| ARMSTAND (Phase 25) | **`ARMSTAND_STILL_DEFERRED`** |
| Scientific authorities mutated | **NEW_LEVEL_B_GT_AUTHORITY_ONLY** |
| Media Backbone mutated | **NO** (B2 reads bounded, writes 0) |

## 1. Mission and result

Expand the subject-resolution corpus with genuinely independent dives
(session/athlete/appearance/scene/distractor/dive-instance variation) and
create subject-identity authority sufficient to decide whether
identity-aware learning is justified. No model training authorized; none
performed.

Result: **6 new independent dives** (1304, 2204, 2223, 2526, 2583, 2839),
**180 HUMAN_REVIEWED Level-B anchors** (105 boxes + 75 NOT_VISIBLE) frozen
as `SUBJECT_GT_LEVEL_B_INDEPENDENT_V1`, frozen D5 + OSNet caches at parity,
frozen V3 replay read-only on all 6 dives. The V3 interpretation
generalizes: phantoms down-ranked, wrong tops are all supported real
movers, top-1 subject-correct 0/12. Identity-learning pilot justified;
L0 formulation preferred; no training executed.

## 2. Phase 0 — fresh preflight (all verified)

| Item | Value | Status |
|---|---|---|
| Canonical branch | `uiux-overhaul-pro-app` @ `4f01003b…9485ee86` | OK |
| Level-A authority | `SUBJECT_GT_LEVEL_A_STANDING_V1`, record SHA `d805aac2…9a75e`, 63 files + MANIFEST present, unmutated | OK |
| Frozen D5 model | `DIVER_DETECTOR_D5_A_V8N_best.pt` SHA `82b420c4…` | OK |
| Frozen OSNet weights | `osnet_x1_0_market1501.pth` SHA `2809d322…` | OK |
| V2 A0/A1 module | SHA `01a17dd7…` asserted on every analysis run | OK |
| V3 quality stage | `SUPPORT_CONF=0.05`, `SUPPORT_RADIUS=0.06` reused, no new cutoffs | OK |
| Worktree | `~/.perso/diveanalyzer-independent-gt`, concurrent server HEAD (`2bb68c9`, UI thread) preserved | OK |
| B2/media authority | 6/6 `proxy_360p` `ready` in production `media_cache_entries`, SHAs match local proxies and queue inputs | OK |

## 3. Phases 1–4 — census, selection, firewall, protected data

Selection from product/session/metadata (canonical DB read-only) plus
generic scene-diversity evidence, before any subject-resolution algorithm
outcome was inspected: no A0/A1/V3/OSNet replay artifact exists for any new
dive; queue extras use only generic candidate geometry (reused frozen
Level-A close-person constants).

| dive | diver/athlete | date/session | code/height | scene reason | independence reason | product authority |
|---|---|---|---|---|---|---|
| 1304 | 7 FANNY | 2025-10-28 / s81 | 105B 1m SB | clean baseline (0 extras) | only 2025-Q4 session | STRONG (FK + FANNY) |
| 2204 | 7 FANNY | 2026-04-07 / s137 | 105C 3m SB | — | FANNY across sessions | STRONG (FK + FANNY) |
| 2223 | 10 LOUIS | 2026-04-07 / s137 | 107C 3m SB | same-session contrast w/ 2204 | **new athlete** | STRONG (FK + LOUIS) |
| 2526 | 14 MAT | 2026-05-30 / s147 | 5121D 1m SB | richest multi-person (19 extras) | **new athlete** | STRONG (FK + MAT) |
| 2583 | 1 MAXIME | 2026-07-08 / s158 | 010B 5m SB lineup | 16 extras, unique config | novel session | STRONG (FK, no-name convention) |
| 2839 | 1 MAXIME | 2026-09-06 / s203 | 5124D 1m SB | longest clip 17.5 s | newest session | STRONG (FK, no-name convention) |

Protected: 524 / 2555 / Paris / INTERNAL_EVAL / FINAL_HOLDOUT untouched,
none selected, none accessed. ARMSTAND not selected (family count not a driver).

## 4. Phases 5–7 — media, frozen D5 cache, frozen appearance cache

- Media: existing B2 canonical proxies only; sequential one-clip-at-a-time
  materialization; SHA-verified; B2 writes 0; no MediaRevision/ingest change.
- D5 cache `runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json`:
  exact frozen recipe (floor 0.001, NMS 0.45, imgsz 640, cap 200, MPS,
  PTS-sequential), 6/6 dives, 3,362 frames, 364,563 candidates,
  peak RSS ≤ 0.65 GB. HURDLE/cohort caches unmutated.
- OSNet cache `runs/subject_resolution/osnet_emb_indep_v1.npz`:
  identical representation (pad 1.3, 256×128, L2, 512-d),
  **n_keys 364,563 == total candidates** (full parity). No ReID/HQ/model
  comparison.

## 5. Phases 8–12 — Level-B density, propagation, UI, human stop

- Density: 0.5 s base grid over full clip (no event-GT authority exists for
  new dives) + frozen close-person extras (+0.25 s; conf ≥ 0.05, dist < 0.10
  mean-bh, IoU < 0.50 — all reused Level-A constants). Queue 180 units
  (14/18/22/51/36/39), byte-deterministic rebuild verified.
- Propagation: deterministic draft (best-IoU supported candidate vs nearest
  earlier human box ≤ 1.0 s, IoU ≥ 0.40) offered only as suggestion; draft
  never authoritative without explicit ACCEPT/CORRECT. Observed:
  **0 drafts used** — all 105 boxes human-drawn/corrected, 75 NOT_VISIBLE.
- UI blind: dive/diver/frame/t/progress only; no ranking/support/identity
  scores shown or stored (verified by inspection).
- Human stop executed 2026-09-20: machine prep verified, Maxime annotated
  177/180, then completed the final 3 (2526 f0/f15/f30) on request.
  Validation PASS 180/180.

## 6. Phases 13–15 — product authority, Level-B freeze, quality validation

- Product subject authority STRONG for 6/6 (table above); no ambiguous dive
  presented to the annotator; no replacement needed.
- Freeze `SUBJECT_GT_LEVEL_B_INDEPENDENT_V1`: 180 anchors + MANIFEST,
  artifact SHA `dc958909…`, per-frame proxy/image SHAs, provenance
  (origin/queue/packet/D5-cache-SHA). Level-A STANDING and HURDLE
  authorities unmutated.
- Mechanical validation: bounds/frame-identity/no-conflicts/explicit
  NOT_VISIBLE/provenance — PASS. Human-consistency diagnostics (anchor-PTS
  jump rate, flag > 4 mean-bh/s): **CLEAN, 0 flags** (max 1.3–3.3 bh/s,
  plausible dive motion; one initial flag traced to a 60-vs-30 fps dt bug
  in the diagnostic, fixed, true rate 2.6 bh/s). No auto-correction
  anywhere; no genuine conflict required human re-review.

## 7. Phase 16 — independence audit: `INDEPENDENCE_GAIN_STRONG`

Expanded corpus: **15 dives / 13 sessions / 4 athletes / 2 families**
(HURDLE 7 incl. one drill; STANDING 8 incl. two STANDING_APPROACH variants).

| Unit | Before | After | Delta |
|---|---|---|---|
| dives | 9 | 15 | +6 |
| sessions | 8 | 13 | +5 novel |
| athletes | 2 (Maxime, FANNY) | 4 (+LOUIS, MAT) | +2 |
| families | 2 | 2 (+approach variant) | scene, not family, gain |

Why STRONG, not PARTIAL: every new dive brings a previously unrepresented
session; two never-before-seen athletes; the two richest multi-person
scenes in the science corpus (2526: 19 close-person extras; 2583: 16);
a lineup configuration (2583) and the longest clip (2839, 17.5 s).
The remaining correlation (single general venue context, 2204+2223 sharing
session 137 as different athletes) is disclosed, not hidden.

## 8. Phase 17 — identity-negative audit (HUMAN_REVIEWED × frozen D5)

Strict STANDING subject rule reused unchanged (≥1 visible anchor with box,
ALL consistent at ≤ 0.06). Tracklets via frozen v2 association; classes via
frozen excursion margin; support via frozen Q0 constants.

| dive | cand | strict subj | supp movers | phantoms | static | adj frag | other-diver-like |
|---|---|---|---|---|---|---|---|
| 1304 | 285 | 4 | 96 | 126 | 59 | 4 | 92 |
| 2223 | 717 | 0 | 360 | 242 | 115 | 7 | 353 |
| 2204 | 623 | 3 | 333 | 237 | 50 | 1 | 332 |
| 2526 | 554 | 4 | 218 | 87 | 245 | 20 | 198 |
| 2583 | 422 | 0 | 123 | 154 | 145 | 21 | 109 |
| 2839 | 837 | 2 | 347 | 287 | 201 | 11 | 336 |
| **total** | **3,438** | **13** | **1,477** | **1,133** | **815** | **64** | **1,420** |

What the future identity model must distinguish: ~1.5k supported
real-person movers (1,420 never overlapping subject anchors), 64
partial-purity association fragments (purity up to 0.86 — the 2583 0.86/7
case), 1.1k phantom movers, 815 statics. Two findings beyond the old
corpus: (a) on 2223/2583 the strict rule yields **zero** subject tracklets
— dense anchors + fragmentation + weak D5 subject detection (only 4/20 and
13/15 visible anchors have a conf ≥ 0.05 candidate within 0.06; 2204:
2/13). This is a labeling-rule×density interaction, reported as data, and
it strengthens the identity/association diagnosis rather than contradicting
it. (b) D5 subject observability at support conf is weak on the new dives
(1304: 5/10, 2839: 8/29) — detection weakness compounds the identity
blocker but ranking among *detected* candidates is still identity-bound
(all wrong tops below are supported).

## 9. Phase 18 — frozen V3 replay (read-only, 12 cells)

Q0 tier + frozen A0/A1 order + frozen abstention, GT labeling-only.

| dive | A0 top (verdict/status) | A1 top (verdict/status) | best subj (V3 \| frozen) |
|---|---|---|---|
| 1304 | mover s9 WRONG/FOUND | mover s1 WRONG/FOUND | A0 56\|24, A1 16\|38 |
| 2204 | mover s5 WRONG/AMBIG | mover s5 WRONG/FOUND | A0 16\|25, A1 193\|291 |
| 2223 | mover s15 WRONG/AMBIG | mover s1 WRONG/FOUND | none\|none (both) |
| 2526 | mover s72 WRONG/FOUND | mover s1 WRONG/AMBIG | A0 5\|6, A1 170\|297 |
| 2583 | mover s18 WRONG/FOUND | mover s2 WRONG/FOUND | none\|none (both) |
| 2839 | mover s74 WRONG/FOUND | mover s44 WRONG/AMBIG | A0 89\|154, A1 131\|236 |

- Top-1 subject-correct: **0/12**.
- Phantom top-1: before 1 (2204-A0) → **after 0**; no post-V3 top is an
  unsupported phantom. Phantoms down-ranked: YES.
- Subject retained in ranked list: 8/12 cells (4 cells on 2223/2583 have no
  strict subject — §8a).
- Supported real movers dominant ambiguity: YES — **12/12 wrong tops are
  supported** (support 1–74); 8/12 WRONG tops delivered as REFERENCE_FOUND
  (confidently wrong, margins to 1.56).

## 10. Phases 19–20 — generalization verdict and dataset size

**`SUPPORTED_REAL_MOVER_IDENTITY_GENERALIZES`**: the same transition occurs
on independent dives — phantom suppression holds, subjects are retained
where strictly labeled, and every remaining error is a supported real
mover. The new-dives-only nuances (strict-rule zero-subject cells from
fragmentation; weaker D5 subject detection) extend the diagnosis to
association, they do not constitute a different bottleneck.

Independent-unit counts (primary): dives 15, sessions 13, athletes 4,
families 2 (+approach variant). Secondary: strict subject tracklets 13 +
64 partial-purity fragments + 105 visible anchors; same-scene real-person
negatives 1,477 (1,420 other-diver-like); subject-adjacent fragments 64;
phantom negatives 1,133; static negatives 815. Raw candidate count (3,438
new / 364,563 D5 instances) is reported but NOT used as evidence.

## 11. Phases 21–24 — learning readiness, formulation, reference, splits

**`IDENTITY_LEARNING_PILOT_JUSTIFIED`**: (1) multi-session independence
meaningful (13 sessions, 5 new); (2) 4 athletes ≥ 3; (3) supported
real-person ambiguity beyond the old corpus (1,477 movers, 12/12 wrong
tops); (4) Level-B GT supports grouped evaluation (dive/session groups,
track-matched labels); (5) MATCH/NON_MATCH objective definable without GT
leakage (GT used only for labels + grouping, never as input); (6) 15
dives/13 sessions support leave-one-dive/session-out with meaning.

Preferred formulation (DESIGN ONLY, no training): **L0 —
SUBJECT-CONDITIONED TRACK MATCHER** (reference evidence + candidate track
→ MATCH / NON_MATCH / AMBIGUOUS). L0 is preferred over L1 because it
separates the unresolved reference-acquisition interface from identity
matching instead of hiding it inside a ranker; the replay proves ranking
among supported movers is exactly what fails.

Reference interface (Phase 23): the pilot trains/evaluates with an
**oracle within-clip reference** derived from Level-B GT; production
reference acquisition (which fails 0/12 top-1 here) is an explicitly open
interface, and joint reference+track scoring is deferred, not assumed.

Future splits (Phase 24): leave-one-dive-out primary, leave-one-session-out
where feasible, athlete-aware reporting. Random frame/candidate splits
remain forbidden. If training is Maxime-dominated, unseen-athlete
generalization is NOT demonstrated — stated in advance, no inflated claim.

## 12. Phases 25–28 — ARMSTAND, abstention, Event Logic, media firewalls

- ARMSTAND: **`ARMSTAND_STILL_DEFERRED`** — ordinary dives delivered the
  independence (2 new athletes, 5 new sessions); nothing uniquely valuable
  shown for armstand.
- Abstention: diagnostic-only; L0 carries MATCH/NON_MATCH/AMBIGUOUS; no
  calibration training this packet.
- Event Logic: not run, not tuned (identity-authority packet).
- Media Backbone: closed; B2 reads bounded (proxy verification), writes 0;
  no storage changes.

## 13. Phase 29 — resource safety

One clip at a time on Apple M2 throughout (D5 cache runs peak RSS
0.50–0.65 GB per dive, recorded in cache metadata; diagnostic/embedding
runs completed without incident, no instrumentation beyond process
completion). No >20 GB regression. Temp disk (frames + caches under
`runs/`, gitignored) retained for reproducibility; no source videos
committed.

## 14. Phase 30 — stop conditions

Two stops occurred, both packet-prescribed: (1) HUMAN_STOP at 0/180 with
`HUMAN_SUBJECT_GT_ANNOTATION_REQUIRED`, resumed after Maxime annotated
180/180; (2) one consistency-flag investigation (diagnostic dt bug, fixed,
re-verified CLEAN). Ordinary tooling issues: none outstanding.

## 15. Required tests

New: `experiments/subject_resolution/test_indep_gt_expansion_v1.py`
(15 tests) covering selection determinism, model-outcome independence,
subject authority, protected firewall, Level-A unchanged, frozen D5/OSNet/V3
identity, annotation schema, human-review authority, no silent propagation,
Level-B provenance/SHA, no training, no B2 mutation. Plus full
subject-resolution suite green (see JSON artifact).

## 16. Durable artifacts and Git

- Created: `docs/science/DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1.md`
  (this file), `.json` (machine record), `SUBJECT_GT_LEVEL_B_ANNOTATION_PLAN_V1.md`,
  `SUBJECT_GT_LEVEL_B_QUEUE_INDEPENDENT_V1.json`.
- Frozen: `docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_B_INDEPENDENT_V1`
  (180 anchors + MANIFEST, SHA `dc958909…`).
- Code: `phase_indep_gt_d5_cache_v1.py`, `phase_indep_gt_osnet_cache_v1.py`,
  `phase_subject_gt_level_b_annotation_v1.py`,
  `phase_indep_gt_expansion_analysis_v1.py`, `test_indep_gt_expansion_v1.py`.
- `docs/PROJECT_STATE.md` updated union-style; gate advances to
  `SUPERVISOR_REVIEW_AFTER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1`.
- Caches/frames/run outputs under `runs/` remain gitignored (host-only).
- Final canonical HEAD: see PROJECT_STATE / LOCAL_AGENT_REPORT.
