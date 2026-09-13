# DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3

Packet: `DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3`
Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_CANDIDATE_QUALITY_V3`
Date: 2026-09-13
Canonical base: `0dabd2bca89270e2d0171107af4aca5f8b3a0650` (branch `uiux-overhaul-pro-app`)
Machine-readable artifact: `DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3.json`

## 0. Verdicts (exactly one each)

| Question | Verdict |
|---|---|
| Track-support signal (Phase 3) | **`TRACK_SUPPORT_SIGNAL_PARTIAL`** |
| V3 classification (Phase 12) | **`CANDIDATE_QUALITY_V3_PARTIAL`** |
| Handcrafted heuristics (Phase 13) | **`HANDCRAFTED_SUBJECT_REFERENCE_HEURISTICS_CONTINUE_ONLY_IF_NEW_EVIDENCE`** — no V4 rule cycle proposed |
| Downstream matcher replay (Phase 18) | **`NOT_JUSTIFIED`** (no correct references produced) |
| Learning reassessment (Phase 14) | **`EXPAND_INDEPENDENT_GT_BEFORE_LEARNING`** |
| ARMSTAND (Phase 16) | **`ARMSTAND_STILL_DEFERRED`** |
| Event Logic | **`EVENT_LOGIC_REPLAY_DEFERRED`** |
| Scientific authorities mutated | **NO** |
| Media Backbone mutated | **NO** (B2 reads 0, writes 0) |

## 1. Mission and hypothesis

Test one final bounded no-training hypothesis: can unsupported low-quality
person hypotheses be suppressed or down-ranked — using **track-level
evidence only**, without raising the frozen D5 floor conf (0.001) — while
preserving the subject proposals that keep the true subject available?

The distinction under test:

```text
low-confidence candidate that belongs to a real person trajectory
  vs
low-confidence phantom fragments that accidentally form dive-like motion
```

## 2. Phase 0 — fresh preflight (all verified)

| Item | Value | Status |
|---|---|---|
| Canonical branch | `uiux-overhaul-pro-app` @ `0dabd2bca89270e2d0171107af4aca5f8b3a0650` | OK |
| Level-A authority | `SUBJECT_GT_LEVEL_A_STANDING_V1`, artifact SHA recomputed `d805aac2…9a75e`, 63 anchors, all `HUMAN_REVIEWED` | OK |
| Frozen D5 model | `DIVER_DETECTOR_D5_A_V8N_best.pt` SHA `82b420c4…` | OK |
| Frozen HURDLE caches | `R5_FULLCLIP_CANDIDATES_V1.json` `3bed1aaf…`, `osnet_emb_cache_v1.npz` `48ab9bd3…` | OK |
| Frozen STANDING caches | `R5_FULLCLIP_CANDIDATES_COHORT_V1.json` `b2f01e41…`, `osnet_emb_cohort_v1.npz` `4d836002…` | OK |
| V2 A0/A1 implementation | module SHA `01a17dd7…` (pinned, byte-identical) | OK |
| D5 floor | `0.001`, NMS `0.45`, imgsz `640`, cap `200` in both caches; `gt_payload: NONE` | OK |
| Worktree | `~/.perso/diveanalyzer-cand-quality-v3`, branch `subject-candidate-quality-v3`, fresh from canonical; concurrent UI/infra/science work untouched | OK |

## 3. Phase 1 — baseline reproduction (BLOCKER check: PASSED)

- **HURDLE**: frozen V2 A0/A1 replayed on 1040/2169/2341/2353/2541 from the
  frozen candidate cache. Top-1 tid, score, status and candidate counts match
  the frozen V2 freeze artifact exactly on all 10 (dive, method) cells.
- **STANDING**: frozen Level-A replay re-run on 133/311/676/2387. The full
  ranked lists (tid + score, all candidates) and the candidate feature dicts
  are byte-identical to the durable Level-A replay artifact; evaluation
  verdicts identical: **0/7 measurable top-1 subject-correct**
  (2387-A0 `REFERENCE_GT_UNOBSERVED`), best strict subject ranks 17–435.
- **`BASELINE_REPRODUCTION_OK`** — no repair needed.

## 4. Phase 2 — candidate-quality diagnostic

Per-candidate measures computed from the frozen caches only: observation
count, temporal span, D5 confidence distribution (max/mean/median/q75/q90),
count and fraction of frames with credible person-detector support,
longest support run, support episodes, area/shape consistency, plus the
frozen A0/A1 features. GT (HURDLE full subject chains, STANDING Level-A
anchors) is used by a separate evaluator for **labeling only**.

Candidate classes (generic, frozen semantics): `subject`
(HURDLE purity ≥ 0.5 / STANDING all-visible-anchors consistent),
`nonsubject_mover` (excursion ≥ frozen `ENTRY_EXTREME_MARGIN_CY` = 0.08),
`nonsubject_static`.

### Support distributions (`support_count` = frames with a conf ≥ 0.05
detection within normalized center distance 0.06 of the tracklet box)

| Family | Class | n | zero-support | support_frac median | conf_max median |
|---|---|---|---|---|---|
| HURDLE | subject | 41 | 26.8% | 0.333 | 0.225 |
| HURDLE | nonsubject_mover | 1725 | 52.1% | 0.000 | 0.013 |
| HURDLE | nonsubject_static | 1122 | 80.6% | 0.000 | 0.004 |
| STANDING | subject | 12 | **0.0%** | 0.348 | 0.136 |
| STANDING | nonsubject_mover | 891 | **76.7%** | 0.000 | 0.007 |
| STANDING | nonsubject_static | 592 | 92.2% | 0.000 | 0.003 |

Key per-dive facts:

- STANDING top-1 phantom decoys on **133 (A0 tid 281, A1 tid 30)** and
  **311 (A0 tid 719, A1 tid 654)** have **zero** supported frames.
- Every STANDING subject candidate has ≥ 2 supported frames
  (support_frac 0.037–0.903).
- But several dominant decoys are **supported movers**: 2169-A1 tid 285
  (158/177 frames supported), 2387-A1 tid 147 (86/140), 2541-A1 tid 834
  (129/146), 676-A0 tid 455 (7/20), 2353 (both decoys supported). Several of
  these partially overlap the subject GT (purity 0.43–0.67) — they are
  association fragments riding the subject, or real other movers.

## 5. Phase 3 — core premise verdict

> Does the intended subject typically receive intermittent credible
> person-detector support even when many frames are low confidence? Do
> STANDING phantom movers systematically lack that support?

**`TRACK_SUPPORT_SIGNAL_PARTIAL`.**

- In STANDING the signal is strong: subjects always carry intermittent
  support; phantom movers overwhelmingly (76.7%) carry none; the actual
  top-1 phantom decoys on 133/311 carry none.
- In HURDLE the signal does not cover all subject candidates (26.8%
  zero-support — the true subject sometimes only exists as sub-0.05
  proposals), and the top-1 decoys on 2169/2353/2541 are supported movers.
- Therefore the signal suppresses phantoms but cannot arbitrate
  subject-vs-supported-mover.

## 6. Phase 4 — subject retention gate (PASSED)

Invariant: at least one useful subject reference hypothesis survives.
Result: **passed on all 9 dives at every pre-registered cutoff**
(support_count ≥ 1, 2, 3, 5). Per-dive best supported subject candidate
support_count: 1040:12, 2169:343, 2341:47, 2353:162, 2541:42, 133:12,
311:6, 676:8, 2387:28. No subject hypothesis is deleted by any variant
(soft handling preserves the full ranked list).

## 7. Phase 5/6/7/8 — Q0 and Q1

### Q0 — TRACK SUPPORT EVIDENCE (executed; the V3 formulation)

```text
support_count(tracklet) = #frames where ANY candidate with conf >= 0.05
                          lies within normalized center distance 0.06 of
                          the tracklet box (own box included)
quality handling        = SOFT TIERED DOWN-RANK (no deletion):
  tier 1: support_count >= 1   (credible person-detector support)
  tier 0: support_count == 0   (unsupported; still ranked, inspectable)
within a tier: FROZEN A0/A1 order untouched
selection + abstention: frozen MIN_ACTION_SCORE / ABSTAIN_MARGIN applied
                        to the top tier only; graceful fallback to the
                        frozen ranking when no candidate has support
```

Constants provenance (Phase 6 — no new numeric cutoff):

- `0.05` — frozen V2 `characterize_clip_structure` person-plausible
  occupancy threshold (existing accepted meaning).
- `0.06` — frozen `reference_purity` / Level-A anchor-consistency
  normalized center-distance radius.
- Cutoff family pre-registered: `{1, 2, 3, 5}`; primary member `>= 1`
  (pure existence-of-evidence, zero new constants). Results are
  qualitatively identical at every member: **0/18 top-1 correct**.

### Q1 — SUPPORT + APPEARANCE COHERENCE (`REJECTED_EARLY`)

Premise probe from the frozen OSNet caches (read-only, no re-extraction):
within-track mean pairwise cosine of cached embeddings.

| Slice | n | median coherence |
|---|---|---|
| subject (supported) | 89 | 0.824 |
| non-subject mover (supported) | 2247 | **0.866** |
| subject (all) | 124 | 0.870 |
| non-subject (all) | 10335 | **0.918** |

Non-subject candidates are equally or more appearance-coherent than
subjects. Q1 offers no generic benefit against the remaining supported-mover
failure mode and is rejected before formulation. Only two formulations were
considered, per the packet budget.

## 8. Phase 9/10 — V3 reference results and phantom suppression

Top-1 subject correctness (V3 = Q0 tier before frozen A0/A1):

| Family | Frozen V2 | V3 |
|---|---|---|
| HURDLE (A0+A1, 5 dives) | 0/5 | **0/10** |
| STANDING (A0+A1, 4 dives) | 0/7 measurable | **0/8** |

Best subject rank, frozen → V3 (per dive, per method):

| Dive | A0 | A1 |
|---|---|---|
| 1040 | 11 → 8 | 2 → **15** (regression) |
| 2169 | 6 → 6 | 14 → 11 |
| 2341 | 5 → 4 | 178 → 83 |
| 2353 | 9 → **18** (regression) | 2 → **16** (regression) |
| 2541 | 71 → 37 | 35 → 19 |
| 133 | 77 → 14 | 17 → 5 |
| 311 | 30 → **2** | 22 → 5 |
| 676 | 22 → 13 | 152 → 32 |
| 2387 | 435 → 100 | 92 → 45 |

Top-5/10/20 subject containment improves on many cells (e.g. 133-A1 and
311-A0/A1 enter top-5; 133-A0, 2387-A0/A1, 2541-A0 enter top-10/20) —
see the JSON artifact for the full matrix.

Phantom suppression (Phase 10):

```text
phantom candidates (zero-support movers)      : 1581
meaningfully down-ranked (>=1 method)         : 1578
phantom top-1 wins before                     : 9  (of 18 cells)
phantom top-1 wins after                      : 0
```

Phantom suppression is real — but the freed top-1 slots are captured by
**supported movers**, so top-1 correctness does not move.

## 9. Phase 11 — family-separated failure analysis

1. **Does Q0 suppress STANDING phantom movers?** Yes — all STANDING
   zero-support phantom top-1 decoys (133, 311) are demoted out of top-1;
   1578/1581 phantom candidates are down-ranked.
2. **Does it preserve HURDLE true-subject low-confidence proposals?** Yes —
   retention gate passed on all dives; unsupported subject tracklets remain
   ranked (inspectable), and every dive keeps a supported subject candidate.
3. **Useful against HURDLE static distractors?** Partially — static
   candidates are 80.6% zero-support and are demoted, but statics were never
   the top-1 failure mode in HURDLE (movers were).
4. **Does one family improve while another regresses?** No top-1 change
   anywhere; best-subject-rank improves strongly on STANDING (133/311/676/
   2387 all improve) but regresses on 3 HURDLE cells (1040-A1, 2353-A0/A1)
   where the subject's best hypothesis is itself unsupported and is demoted
   below supported junk.

No pooled-only verdict is claimed.

## 10. Phase 12 — classification

**`CANDIDATE_QUALITY_V3_PARTIAL`.**

- Subject candidates preserved (retention gate passed) ✓
- Phantom/static wrong selections meaningfully decrease (phantom top-1
  wins 9 → 0) ✓
- Reference ranks materially improve — **no**: top-1 is 0/18 before and
  after; rank improvements are real but mixed (3 HURDLE regressions) ✗
- Improvement in both families — **no** (STANDING ranks improve, HURDLE
  mixed) ✗

The decisive finding: after phantom suppression, the dominant wrong
references are **supported movers** — real other-person tracks and
subject-adjacent association fragments (purity up to 0.67). That is an
**identity/association** failure mode, not a candidate-quality failure
mode. Candidate quality is now the wrong lever for the remaining gap.

## 11. Phase 13 — stop heuristics gate

`CANDIDATE_QUALITY_V3_PARTIAL` → per the packet, no automatic further rule
cycle is proposed. Status:
`HANDCRAFTED_SUBJECT_REFERENCE_HEURISTICS_CONTINUE_ONLY_IF_NEW_EVIDENCE`.
The `…_PAUSED` invariant is **not** added (reserved for FAILS), but no V4
rule tuning on this corpus is proposed: the remaining failure (subject
identity among supported real movers) is not addressable by more
candidate-quality rules.

## 12. Phase 14 — learning reassessment

**`EXPAND_INDEPENDENT_GT_BEFORE_LEARNING`.**

9 dives / 2 families / ~17 subject positives, negatives correlated within
dive. V3 clarifies the learning target (distinguish the subject's
trajectory from supported real movers — i.e., identity-aware reference
selection), but does not sharpen it enough to justify a bounded pilot:
the target definition itself would need identity supervision that 9
independent dives cannot support.

## 13. Phase 15 — next GT investment (bounded plan only)

Do NOT add more anchors to the same four STANDING clips. Priority order:

1. **New sessions / new dives** with full subject chains (HURDLE-style
   Level-B), 3–5 independent clips — highest value: they attack the
   supported-mover identity problem with independent negatives and enable
   grouped evaluation.
2. **Additional athletes** where available in already-ingested sessions
   (different body size/appearance → stronger identity signal).
3. **Additional scene configurations** (different board/platform angle,
   background density) to decorrelate distractor structure.

Bounded plan: 4–6 new independent dives, Level-B subject chains (the
existing chain format), no new annotation tooling. No annotation performed
in this packet.

## 14. Phase 16 — ARMSTAND

**`ARMSTAND_STILL_DEFERRED`.** The dominant limitation is independent-dive
count and the identity/association failure mode, not family diversity: the
same supported-mover failure appears inside both existing families. A third
family would not resolve it.

## 15. Phase 17 — abstention diagnostic

No retuning. V3 wrong top-1 margins (frozen semantics, top tier):

- Confidently wrong (`REFERENCE_FOUND`, margin ≥ 0.05): 1040-A0 (0.23),
  1040-A1 (0.65), 133-A0 (0.26), 2169-A0 (0.18), 2341-A0 (0.06),
  2353-A0 (0.54), **2353-A1 (2.24)**, 2387-A0 (0.13), 2541-A0 (0.40),
  2541-A1 (0.62), 311-A0 (0.52), 311-A1 (0.07), 676-A0 (1.29).
- Abstaining correctly by frozen semantics: 133-A1, 2341-A1
  (`REFERENCE_NOT_FOUND`), 2169-A1, 2387-A1, 676-A1 (`REFERENCE_AMBIGUOUS`).

Wrong references remain confidently wrong; abstention cannot separate them.

## 16. Phase 18/19 — matcher and Event Logic

- Downstream matcher: **`NOT_JUSTIFIED`** — V3 produced no correct
  references, so the frozen matcher replay has no improved input. Matcher
  untouched.
- Event Logic: untouched; **`EVENT_LOGIC_REPLAY_DEFERRED`**.

## 17. Phases 20–22 — firewalls and resources

| Item | Result |
|---|---|
| 524 | `AUTHORITY_CONFLICT_EXCLUDED` — not loaded |
| 2555 | `SCREEN_RECORDING_STRESS_CASE` — not loaded |
| Paris / INTERNAL_EVAL / FINAL_HOLDOUT | not accessed |
| GT in inference path | none (structural test: ranking identical with all GT fields stripped) |
| D5 floor / NMS / imgsz / model | unchanged (asserted) |
| A0/A1 module | byte-identical (`01a17dd7…`), constants asserted |
| New D5 inference | 0 |
| New embeddings | 0 |
| Model training | 0 |
| New human labels | 0 |
| B2 reads / writes | 0 / 0 |
| New media tiers | 0 |
| Level-A GT mutated | NO (63 files, manifest SHA stable) |

## 18. Required tests

`experiments/subject_resolution/test_subject_candidate_quality_v3.py` —
19 tests, all green; full subject-resolution suite **73 passed, 1 skipped**
(the skip is the pre-existing draft-annotation-session gate). Covered:
baseline replay identity (both families), Level-A SHA identity, protected-data
firewall, GT-stripped inference path, D5 config/floor unchanged, V2 module
identity, candidate-quality determinism (byte-identical rerun), subject
retention gate, soft handling preservation (no candidate deleted), family
separation, no new labels, no B2 mutation, phantom suppression counts, pinned
V3 top-1 expectations, Q1 rejection consistency.

## 19. Answers to the success questions

1. **Do true-subject hypotheses have stronger temporal detector support than
   STANDING phantom movers?** Yes — STANDING subjects: 0% zero-support
   (support_count ≥ 2); phantom movers: 76.7% zero-support; actual top-1
   phantom decoys: zero support.
2. **Can that evidence be expressed generically without raising the D5
   floor?** Yes — track-level support counting with two reused frozen
   constants; no detector change.
3. **Can phantom candidates be down-ranked while preserving subject
   hypotheses?** Yes — 1578/1581 phantoms down-ranked, retention gate passed
   on all 9 dives, no deletion.
4. **Does reference ranking improve on STANDING?** Ranks improve materially
   (best subject rank 30→2, 77→14, 152→32, 435→100) but **top-1 does not
   become correct on any STANDING dive**.
5. **Does HURDLE remain stable or improve?** Mixed: no top-1 change; rank
   improvements on 7 of 10 cells, regressions on 3 (1040-A1, 2353-A0/A1).
6. **Does candidate-quality evidence help both failure modes or only one?**
   Only one — it suppresses phantom/static unsupported candidates in both
   families but cannot arbitrate subject-vs-supported-real-mover.
7. **Are handcrafted subject-reference heuristics now exhausted?** For
   candidate quality: yes — the remaining failure is identity/association,
   outside the candidate-quality lever. No V4 rule cycle proposed.
8. **Should the next investment be more independent GT or a bounded learning
   pilot?** More independent GT (`EXPAND_INDEPENDENT_GT_BEFORE_LEARNING`).

## 20. Current true bottleneck

**Subject identity among supported real movers.** The candidate ocean now
provably contains the subject on every dive (retention gate), phantom
fragments are suppressible with generic evidence, but selecting the subject
— as opposed to another real person or a subject-adjacent association
fragment — requires identity-level evidence that neither A0/A1 motion
semantics nor track-quality heuristics provide.

## 21. Git / integration

- Science branch: `subject-candidate-quality-v3` (worktree
  `~/.perso/diveanalyzer-cand-quality-v3`), fresh from canonical `0dabd2b`.
- Integrated into canonical `uiux-overhaul-pro-app` server-side (union-style
  PROJECT_STATE merge; concurrent uncommitted work preserved untouched).
- Mac mirror synced.
- Final canonical HEAD: see PROJECT_STATE / LOCAL_AGENT_REPORT.
