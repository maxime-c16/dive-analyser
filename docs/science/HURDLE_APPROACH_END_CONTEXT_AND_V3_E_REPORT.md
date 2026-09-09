# HURDLE APPROACH-END CONTEXT AND V3-E REPORT

**Label:** HURDLE_APPROACH_END_CONTEXT_AND_V3_E_REPORT
**Date:** 2026-09-09
**Branch:** `uiux-overhaul-pro-app`
**Base commit (thread start / canonical HEAD reported):** `30267b1` (Event Logic V3-D0 freeze); parent `9881813` (HQ/media freeze)
**Final HEAD of this thread:** see `git log` — V3-E thread commits after `5177924`.
**Authority split:** Event Logic authority = this thread. HQ/media authority = the independent iCloud thread, consumed **read-only** through its frozen manifest (`ANALYSIS_SOURCE_HQ_V1_FREEZE.json`). No scientific ownership merged.

---

## 1. Parallel-thread integration state

- Canonical HEAD at thread start: `30267b1958970e3bd7c98b7d6dfafdfa49978b4c` — verified identical on the canonical server (`diveanalyzer-server:dive-analyser`), the Mac working copy, and `origin/uiux-overhaul-pro-app` after fetch.
- Both reported HEADs verified as ancestors of canonical HEAD (`git merge-base --is-ancestor`): Event Logic `30267b1` ✓, HQ/media `9881813956de5aa51be0f78109c7a58cb771f801` ✓. The histories were already **linearly integrated** (9881813 is the direct parent of 30267b1). **No merge/rebase was required.**
- Event Logic artifacts retained (V3-C0/V3-D0 sources, tests, freeze artifacts); HQ/media artifacts retained (HQ freeze + manifest + recovery evidence). The HQ thread's uncommitted stable artifacts (`hq_temporal_alignment_v1.py`, `runs/hq_rep_v1/alignment_*.json`) were committed for preservation; its in-flight files (`hq_scale_match_v1.py`, `hq_representation_audit_v1.py`) were left untracked for its own author to commit.
- `docs/PROJECT_STATE.md` contains both authoritative outcomes. Integration audit: `docs/science/PARALLEL_THREAD_INTEGRATION_AUDIT.json`.
- Quarantined HQ assets **311 and 524** were never used by Event Logic (see §7/§10).

## 2. V3-D0 authority correction

V3-D0 remains **`V3_D0_EXPERIMENTAL_FROZEN_DEVELOPMENT_BASELINE`** — a frozen *development* baseline. It is **not production-promoted**. The prior thread's freeze artifact already recorded `V3_D_DEVELOPMENT_IMPROVES_PARIS_FAILS`; this thread re-verified it and additionally showed (§11) that V3-D0's HURDLE gain is effectively a **single-dive improvement** (2169) on the wider corpus.

Status: `CLOSED` (FM1), `OPEN / PARTIALLY_ADDRESSED` (FM2), FM3 (360p target instability on 1040) remains relevant; the HQ comparison in §7 shows improved SNR on 1040 at HQ but no material detection gain.

## 3. HURDLE corpus size

Development HURDLE corpus extended from **2 → 7 dives**, all with complete human V2 temporal GT (takeoff/apex/water_contact, `HUMAN_CORRECTED`), 360p proxies, D5 trajectories regenerated with the frozen recipe (`DEV_HURDLE_TRAJ_CACHE_V2.json`):

| dive | code | context note | n_valid/n_frames | fps |
|---|---|---|---|---|
| 1040 | 102C | existing | 332/332 | 29.97 |
| 2169 | 101B | existing | 1078/1078 | 59.94 |
| 524 | 103B | new (existing GT; HQ rendition quarantined — 360p only) | 716/716 | 60.00 |
| 2341 | 101B | new (proxy pulled from server) | 607/607 | 60.00 |
| 2353 | 101A | new (**drill** modifier — flagged, secondary evidence) | 1437/1437 | 59.94 |
| 2541 | 5111B | new | 968/975 | 29.97 |
| 2555 | 5132D | new | 722/722 | 59.26 |

Excluded by design: 2625 (takeoff GT `NOT_APPLICABLE`), 2661/2680 (010x armstand — not running-approach hurdles), all `INTERNAL_EVAL` dives (2281 is the only HURDLE there and remains protected), Paris. No human-labeling gate was triggered (≥4 dives with trustworthy GT existed). **No approach_end GT was created; no step-count inference was performed anywhere** (dive numbering was used only for context classification, never for timing).

## 4. Robust board reference (Phase C)

1040's historical weakness confirmed: `y_prep` (B0 = smoothed cy at prep_end = **0.531**) is a *mixture* of two D5 target levels (diver on board cy≈0.221, 70% of pre-hurdle frames; a second target cy≈0.599, 30%) and matches neither. Candidates audited GT-blind (`BOARD_REFERENCE_AUDIT_V1.json`):

- **B0** historical single `y_prep`;
- **B1** robust center-y support median (stable-support cluster: |vel| ≤ 0.02, conf ≥ 0.10);
- **B1r** B1 + 1.5×MAD outlier rejection;
- **B2** robust bbox-bottom support estimate (converted to center-y units).

**Chosen: B1r** (rule: minimize median |ref − dominant stable level|; near-tie prefers the fail-loud variant). On 1040, B1r = **0.2208** — the true diver-on-board level. On 2541 the initial "plateau" is a non-diver low-conf target (conf 0.06): B1r **fails loud (None)** where B0 silently adopted cy = 0.0288. C2: `min_hurdle_rise_cy = 0.01` is image-scale dependent; a body-scale rise (`rise/bh`) distribution at the scanned crossings was recorded descriptively in the audit — **no threshold was changed and no grid search was performed** (max one alternative, descriptive only).

## 5. 2D trajectory audit (Phase D)

Full kinematics (`cx, cy, bbox-bottom, vx, vy, 2D speed, direction changes, curvature`) audited per dive, GT-blind (`TWOD_APPROACH_AUDIT_V1.json`). Result: **vertical-only kinematic failure generalizes to 2D.** Direction-change counts are dominated by 360p target flicker (1040: 15 flips, 2541: 39, 2555: 60). No dive qualifies as `APPROACH_END_OBSERVABLE_FROM_2D_TRAJECTORY`; 1040/2169 are `MIXED_2D_OBSERVABILITY`; 524/2341/2353/2541/2555 are `NOT_RELIABLY_OBSERVABLE`.

## 6. Approach-progress coordinate (Phase E)

Robust principal-axis / line-fit `s(t)` over the approach portion (GT-blind bounds) is **not reliably extractable at 360p** on this corpus: axis inlier ratios range 0.56–1.0 but sustained-progression fractions and terminal-region detection are corrupted by target flicker; 2555's approach window is degenerate (0.03 s); 2341's clean axis covers only 0.34 s. Best case is 2169 (`MIXED`). The E1 gating pattern (progression → slowdown/reversal → rise → recontact → departure) therefore cannot be instantiated from 2D alone on this corpus.

## 7. 360p/HQ comparison (Phase G, read-only)

Only the two Event-Logic-authorized HQ assets were used: **1040, 2169** (both `PTS_EQUIVALENT`, label-transfer allowed by the frozen manifest; PTS equality verified within 20 ms). Quarantined assets (311, 524) were **not** used; no HQ manifest, mapping, or media was modified; no retraining.

Controlled comparison (`HQ_HURDLE_DIAGNOSTIC_V1.json`, identical primitives on both renditions):

| metric | 1040 360p → HQ | 2169 360p → HQ |
|---|---|---|
| target-level switches | 5 → 5 | 4 → 3 |
| raw_neg_ratio (GT±0.35 s) | 0.429 → 0.524 | 0.500 → 0.452 |
| smooth_neg_ratio (σ=0.117 s) | 0.000 → **0.762** | 0.000 → 0.048 |
| V3-D0 to_err | 1.9947 → 1.8605 | 0.4123 → 0.4221 |
| axis inlier ratio | 0.764 → 0.660 | 0.740 → 0.512 |

**G1 verdicts:** 1040 = `HQ_IMPROVES_SNR_ONLY` (the vertical signal becomes visible at HQ yet detection improves only marginally; target instability persists at HQ). 2169 = `HQ_NO_MATERIAL_GAIN`. (The earlier V3-D freeze note "1040 HQ to_err 1.094s" was produced under a different primitive convention and is not reproducible under the controlled frozen recipe; the discrepancy is flagged in the diagnostic JSON.)

**Conclusion:** HQ does not repair the HURDLE detection path; the bottleneck is target identity/geometry, not raw resolution alone.

## 8. V3-E0

**Definition (Phase H):** V3-D0 + validated robust board-level reference only. The 2D approach-end/progress gate was **excluded** — the Phase F/H precondition ("DEVELOPMENT supports a meaningful 2D approach cue") was not met. Source: `proposer_event_logic_v3_e0.py`; `PARAMS_V3E0 = PARAMS_V3D0 + {variant, board_ref_min_support_n=5}`; no other parameter touched; `min_hurdle_rise_cy` stays 0.01; A1/A2 terminal bounds untouched; STANDING path byte-identical; B1r computed GT-blind from the raw signal, with a `HISTORICAL_FALLBACK` mode (→ B0 `y_prep`) when support is insufficient.

**H1 physical semantics honored and tested:** a rise during sustained approach progression does not automatically become the hurdle apex (test cases 8–9 of the V3-E suite); the mechanism remains *rise → recontact → sustained final departure*.

## 9. Minimal board context (Phase I) — result

Not executed as a separate representation: the audit found **no validated GT-blind cue** for an end-of-board *region* (support-axis/board-tip/ROI candidates all failed the 2D/terminal-region evidence). Per the packet, Phase I runs only if V3-E0 remains insufficient **and** a lightweight cue exists — the second condition failed.

## 10. V3-E1 — not built

`V3_E1 = NOT_JUSTIFIED_BY_DEVELOPMENT_EVIDENCE`: no validated end-of-board cue exists, and the remaining non-drill failure (524, to_err 4.74) is corruption-family. Building E1 would have required an unvalidated cue or per-venue constants — forbidden. Candidate budget respected (≤2: V3-E0 only).

## 11. DEVELOPMENT comparison (Phase K)

Identical trajectories (`DEV_HURDLE_TRAJ_CACHE_V2.json` / `STANDING_TRAJ_CACHE_V2.json`). **Raw per-dive HURDLE results (absolute errors, s):**

| dive | V3-D0 to / apex / wc | V3-E0 to / apex / wc | E0 board_ref mode |
|---|---|---|---|
| 1040 | 1.9947 / 2.1612 / 2.5110 | **5.7463 / 5.7467 / 5.5971 (REGRESSED)** | B1R 0.2208 |
| 2169 | 0.4123 / 0.4960 / 0.2872 | identical | B1R 0.2626 |
| 524 | 4.7436 / 4.8603 / 4.6769 | identical | B1R 0.2624 |
| 2341 | 1.0108 / 1.5441 / 3.4108 | identical | B1R 0.1113 |
| 2353 (drill) | 1.8089 / 1.6915 / 2.2414 | identical | B1R 0.6337 |
| 2541 | 15.0156 / 15.3488 / 14.9144 | identical (B0 fallback — non-diver plateau) | HISTORICAL_FALLBACK |
| 2555 | 2.6137 / 4.4137 / 7.4803 | identical | B1R 0.6096 (n=6, weak support) |

STANDING (K2 protection): **byte-identical** on 133 (0.1653), 311 (0.0592), 676 (3.0864), 2387 (2.1476). Catastrophic count (to_err > 2.5 s): V3-D0 3 → V3-E0 4; complete triplets 7/7 for both.

**Mechanistic explanation of the 1040 regression:** with the *correct* board level (B1r 0.2208), every pre-takeoff crossing is correctly rejected — but the gate scan is unbounded in time, so a **post-water-contact flicker crossing at 9.343 s** (cy_apex 0.1949 < board − 0.01) now passes and the takeoff is picked at 10.21 s. V3-D0's B0 mixture failed *earlier* (false crossing at 1.63 s). Both variants fail; the missing ingredient is a physically bounded validity horizon for the hurdle chain — a parameter that would need to be derived from trustworthy HURDLE DEVELOPMENT data, i.e. **more/better GT and reliable target identity first**.

## 12. Freeze decision (Phases L/M)

**Freeze gate: FAILED.** Criteria: hurdle improvement beyond a single dive ✗ (zero improved, one regression); no STANDING regression ✓; FM1 closed ✓ (311 wc_err 0.0269 ≤ 0.1); terminal WC stability ✗ (1040 wc 2.511 → 5.597); mechanism interpretable ✓; no Paris influence ✓. **No `EVENT_LOGIC_V3_E_FREEZE` was created.** Decision string: **`MORE_HURDLE_GT_REQUIRED`**. Artifact: `V3E_FREEZE_GATE_FAILED_V1.json`.

## 13. Paris external result (Phase N, report-only, post-decision)

Run **only after** the freeze decision, with parameters frozen in advance (`PARIS_EXTERNAL_V3E_EVAL_V1.json`, `paris_role: EXTERNAL_REPORT_ONLY`). Two readings, both report-only:

- **Full-clip documented authority (unchanged, immutable):** V3-C0 = V3-D0 to_err **1.685 s** (false hurdle accepted at 1.117 s: y_prep 0.4635, cy_apex 0.380, rise 0.083); wc_err 0.1333.
- **Frozen 182-frame flight-window trajectory (`PARIS_FULL_TRAJECTORY_V2.json`, span 2.28–5.49 s, excludes the 1.117 s pre-window feature):** V3-D0 and V3-E0 give **identical predictions** (window-prep fallback; takeoff 4.5119 s → to_err 1.3919 s vs GT 3.120; apex_err 1.455; wc not in span). V3-E0 ran in `HISTORICAL_FALLBACK` mode (cluster n=1 < 5) — the Paris window's prep region does not provide robust support, exactly the graceful-degradation behavior designed in §8.

No tuning occurred after either reading; nothing Paris-derived entered any parameter (enforced by the Paris firewall tests, §14).

## 14. Scene-context decision and test quality

**Phase O decision (exactly one): `MORE_HURDLE_GT_REQUIRED`.**
`SCENE_SEGMENTATION_NEXT_JUSTIFIED` requires (a) correct target trajectory — currently **false** (target instability is the root cause on 1040/524/2555/2541) — and (b) adequate HQ signal — §7 shows HQ gives no material detection gain. 2D progress fails (§5–6) and minimal board geometry only validated the board *level*, not an end-of-board region. With the packet's own preconditions unmet, the honest next step is a larger, perception-validatable HURDLE GT corpus (and/or target-identity repair authority from the perception thread) before scene segmentation is justified.

**Phase P decision (exactly one): `V3_D0_REMAINS_EXPERIMENTAL_BASELINE`.** V3-D0 stays the active experimental frozen DEVELOPMENT baseline; V3-E0 is not eligible for promotion (it would be external-failing and one-dive-regressing).

**Tests (all green, 74 total):** V3-E suite 13/13 (`test_event_logic_v3_e.py`: robust board reference, outlier rejection, insufficient-support fallback, STANDING non-regression, FM1 closure, full-pipeline regression fixtures for 1040/2169/524 from real cached trajectories, time-shift invariance, long approach, approach rise ≠ hurdle, board recontact, final departure, HQ read-only + quarantined-HQ exclusion, Paris firewall extension, freeze identity); V3-D0 16/16 including the **repaired Paris firewall** (the historical `Paris to_err ≤ 2.0s` selection criterion is retired; replaced by firewall-integrity tests: Paris absent from DEVELOPMENT inputs, Paris absent from parameter derivation, freeze precedes Paris evaluation, Paris artifact report-only); V3-C 14/14; highres recovery 16/16; PTS authority 15/15.

## 15. Remaining FM2 taxonomy

- **FM2 root cause (unchanged):** D5 target instability at 360p — target switching/oscillation corrupts both board level and departure detection. Robust board level (B1r) repairs the *level* but not the *scan validity*; an unbounded scan turns 1040's repair into a late false-positive.
- **Missing ingredient:** a physically grounded validity horizon / end-of-board region, derivable only from more trustworthy HURDLE DEVELOPMENT evidence (target identity first). Step-count inference remains forbidden and was never used.
- **HQ:** read-only authority confirmed; SNR-only benefit on 1040; not a fix.
- **Open items for the next gate:** (1) supervisor decision on expanding DEVELOPMENT HURDLE GT (how many new dives, which sessions); (2) perception-thread decision on target-identity repair (the 1040 two-level problem) — this belongs to the perception authority, not Event Logic; (3) whether Paris' full-clip pre-window region should be re-extracted with the same windowing discipline as DEVELOPMENT (report-only).

## Artifacts produced by this thread

- Scripts: `build_hurdle_traj_cache_v2.py`, `phase_v3e_baseline_b.py`, `phase_v3e_board_reference.py`, `phase_v3e_2d_audit.py`, `phase_v3e_hq_diagnostic.py`, `proposer_event_logic_v3_e0.py`, `phase_v3e_eval.py`, `phase_v3e_freeze_gate.py`, `phase_v3e_paris_eval.py`, `test_event_logic_v3_e.py`
- Artifacts: `DEV_HURDLE_TRAJ_CACHE_V2.json`, `STANDING_TRAJ_CACHE_V2.json`, `V3D0_HURDLE_CORPUS_BASELINE_V1.json`, `BOARD_REFERENCE_AUDIT_V1.json`, `TWOD_APPROACH_AUDIT_V1.json`, `HQ_HURDLE_TRAJ_CACHE_V2.json`, `HQ_HURDLE_DIAGNOSTIC_V1.json`, `V3E_DEVELOPMENT_COMPARISON_V1.json`, `V3E_FREEZE_GATE_FAILED_V1.json`, `PARIS_EXTERNAL_V3E_EVAL_V1.json`, `PARALLEL_THREAD_INTEGRATION_AUDIT.json`
- Test repairs: `test_event_logic_v3_d0.py` (Paris firewall 1–4 replacing the Paris-performance test)
