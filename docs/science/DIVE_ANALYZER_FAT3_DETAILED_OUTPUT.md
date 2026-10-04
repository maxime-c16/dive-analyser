# FAT3 full-action + event-logic validation — detailed output for the supervisor

Workdir: `~/.perso/diveanalyzer-fullaction-fat3/` (plain copy, no .git; canonical integration via SSH).
Canonical: `mcauchy@192.168.1.57:~/dive-analyser`, branch `uiux-overhaul-pro-app`.
Cycle HEADs: `69ad2f2` (queue+protocol) → `39bba63` (V4-B0 freeze) → `34fb42b` (viewer fix) →
`a2eade0` (authority) → `48dd1e8` (gate report) → `4d053f0` (PROJECT_STATE).
Prior state: `7a85b59` with FAX V1 frozen (DEV-validated only), FAT2 VOID, V3-C0 frozen with
systematic early-takeoff failure, V4-A0 DEV probe unfrozen.

Mission product path under test:
`clip → S3/FSR candidate flights → user selects correct flight → recover same diver
through preparation and entry → stable full-action AnalysisTrack → temporal landmarks → later pose/biomechanics`.
Causal order enforced throughout: landmarks evaluated only on independently validated tracks.

## 1. Authority construction (all GT-free until annotation)

### 1.1 Session/dive inventory (canonical DB, read-only via backend container)
- DB: 2832 dives / 172 sessions. Forbidden-session union (51): past-science 37
  (recovery-V2 split) + FGT3H/V3-holdout 13 (12/33/38/52/59/61/86/101/111/127/133/142/165)
  + FAT2 session 80. Covers INTERNAL_EVAL sessions (26/51/138) and the sessions of
  524/2555/Paris. Protected dives never candidates.
- Metadata filter: fresh sessions + non-lineup + non-sync + springboard 1m/3m +
  `photos_edited_rendition` source ≥ 10 s → 904 dives / 82 sessions.
- Metadata shortlist (no pixels seen): 10 sessions spread 2024-11..2026-08
  (7/19/31/47/69/92/104/124/139/166); one dive per session preferring 1m + longest
  clip, alternating standing/hurdle → 5 standing / 5 hurdle:
  16/s7, 77/s19, 251/s31, 735/s47, 1083/s69, 1491/s92, 1716/s104, 1933/s124, 2519/s139, 2742/s166.

### 1.2 Dive-context sweep (zero prior use)
- All 111 `dive_id` references across science JSONs: zero candidate overlap.
- Dive-context regex over all 1886 tracked docs/experiments files: only "dives (16"-style
  counts. All remaining plain-word hits verified as collisions (confidences 0.1933/0.2519,
  coordinates cx 0.1491/0.2742, percentages 77.4%/16.7%, ranks 77→14 on dive 133, frame
  indices fi 251, durations 0.735 s, table cells, bbox pixels).

### 1.3 B2 read-only fetch + study-local proxies (frozen recipe)
- 10 edited sources via backend-container playback creds (GetObject only), SHA-verified
  = DB `media_blobs.sha256` byte-exact (16: 30206691 B … 1933: 75473178 B).
- 360p proxies with frozen mac-agent args (scale=-2:360, x264 veryfast crf28, bt709):
  16: 648×360/665f; 251: 884f; 1491: 880f; 1716: 329f; 2519: 968f; 2742: 722f; 735: 200×360/456f.
  Registry `PROXY_REGISTRY_FAT3.json` (host-only) with sequential-decode PTS.
- Notable: dive 77 source is portrait 1076×1912; dive 16 source is 828×460 wide.

### 1.4 Raw-clip screen (contact sheets, NO detector output) → queue
Prep-visibility rank: 16 > 2519 > 2742 > 1716 > 251 > 1491 > 735 > 1083 > 77 > 1933.
Cut at 6 (annotation burden ~200 steps); reserve = rank 7 (735/s47, enters only on
annotator-exclusion — implemented in queue logic, no mid-annotation code change).
- KEEP: 16 (101C, near, long prep), 251 (201C, clear hurdle prep), 1491 (401B, long prep),
  1716 (201C, good prep), 2519 (201C, long prep), 2742 (5122D twist, good prep).
- REJECT: 77 (portrait, small distant figure at frame edge); 1933 (tiny distant figure in
  dark wide shot, 2838-class); 1083 (foreground close-up person at clip start + ~2 s board
  prep); 735 held as reserve (weaker of the small-figure pair vs 1491).

### 1.5 Queue + protocol + tooling (committed `69ad2f2` BEFORE any detector output)
- `FAT3_ANNOTATION_QUEUE_V1.md`: 6 dives + reserve rule + selection rule + media SHAs.
- `FAT3_PROTOCOL_V1.md`: question, frozen inputs, gate rule (i–iv + PASS/VOID/FAIL),
  failure-attribution taxonomy, landmark layer (V3-C0 baseline + frozen successor, signed +
  absolute errors, abstention separated, predeclared bar median |takeoff| ≤ 0.5 s with
  apex/contact not regressed), product readouts, firewalls.
- `fat3_annotation_v1.py`: takeoff → contact → apex → apex_R (tool-enforced inside window)
  → flight k/8 + prep 0.5 s + post +0.1/0.3/0.5 + one blind mid-PREP repeat per dive;
  per-dive proxy sizes; raw frames only; request logging (ghost-exclusion watch).
- Viewer viewport fix (`34fb42b`, pre-annotation, draft verified empty): dive 16's 648-wide
  canvas pushed the control panel off-screen (inherited fit() constrained by height only).
  Scale now constrained by width too (min 0.5); uniform S → box mapping exact; queue/steps/
  blindness unchanged.
- `fat3_s3_cache_v1.py`: frozen S3 (`3dc07f69…` asserted pre/post) on the 6 + reserve,
  proxy-SHA + decode-PTS asserted. All 7 built GT-free. `fat3_sealed_viability_v1.py`:
  same pre-registered rule as FAT2 (Q ≥ 0.3, drop ≥ 0.1, conf_med ≥ 0.2) → 7/7 viable
  (16: Q 1.039; 251: 0.809; 1491: 0.691; 1716: 0.734; 2519: 0.669; 2742: 0.878; 735: 0.589).
  Queue stood regardless (committed before viability ran).

### 1.6 Annotation + freeze (`a2eade0`)
- Maxime labeled 6/6 dives (~200 steps); zero exclusions; apex-repeat agreement
  0.000–0.033 s (16: 0.0333; 251: 0.0333; 1491: 0.0167; 1716: 0.0; 2519: 0.0167; 2742: 0.0334).
- Visibility mix: 16: 40 vis/1 part/2 nvis; 251: 21/1/2; 1491: 22/2/1; 1716: 8/2/10;
  2519: 21/1/2; 2742: 15/2/5.
- No ghost-exclusion incident (no /api/exclude traffic; exclusion set empty).
- Frozen `FULL_ACTION_GT_HUMAN_V3_FRESH`: 182 items + FAT3_EVENTS, digest
  `dfd493f0fe482cfd73149b38de474d54ba9fdbff6d30c044aacf4cfebcb0c48b`.

## 2. EL-successor design (DEV only, frozen `39bba63` BEFORE annotation)

### 2.1 DEV reproduction (environment verification)
Rebuilt all 17 FAX DEV tracks with frozen code from existing caches + replayed V3-C0/V4-A0:
**zero mismatches** vs frozen `fax_v1_dev_results.json` (rep/pool_rank/ft/n_obs/V4 errors exact).

### 2.2 V4-B0 design (one change vs the A0 probe)
- V4-A0 rise-onset errors on DEV: n=14 scored, 3 honest abstentions (980/992/2242);
  median −0.226 s, mean −0.251 s, range −0.483…−0.184; hurdle −0.217 vs standing −0.234
  (no family structure); SEARCH_BACK_S invariant over {3, 4, 5} s (14/14 identical).
- `TAKEOFF_BIAS_S = +0.23 s` (DEV median; seconds-based, PTS-consistent) + anchor clamp
  (takeoff ≤ ft0; 3 DEV activations: 2257/2288/31). Apex/wc reuse V3-C0 detectors
  unchanged — per-dive picks byte-identical to V4-A0 on all 17 DEV tracks.
- DEV at freeze: takeoff median|err| 2.101 (V3-C0) → 0.050 (V4-B0), max 0.250;
  wc median|err| 0.684 → 0.267 (same detector, better anchor).
- Tests `test_event_logic_v4_b0.py` 10/10 (constants, E1 parity, standing/hurdle synthetics,
  bias application, clamp, abstentions, apex/wc delegation parity, triplet, context-free
  signature); V3-C 14/14 + V3-D0 16/16 unregressed.
- Freeze: `EVENT_LOGIC_V4_B0_FREEZE.json` + note; module SHA `21ad37bb…`.

## 3. Gate results (frozen FAX `55282fb9…`, eval SHA `81dd9d03…`)

All 6 dives SELECTED (first Q-ordered candidate passing hits≥2 / coverage≥0.75 /
purity≥0.75 @ 0.06). 12/12 ends labeled. No unsurfaced cases.

| Dive | HUMAN to/apex/wc (s) | Flight | Prep | Back stop | V3-C0 to/apex/wc err | V4-B0 to/apex/wc err |
|---|---|---|---|---|---|---|
| 16 | 14.800/15.267/15.767 | 8/9 pur 1.0 | 0/30 (wrong f466/f481) | AMBIGUOUS (margin 0.015) | −0.667/−0.833/−0.167 | +0.133/−0.033/−0.167 |
| 251 | 5.317/5.767/6.400 | 8/9 pur 0.89 (wrong f360) | 11/11 pur 1.0 | CLIP_START | −1.933/−2.000/−2.417 | −0.883/−1.183/−1.583 |
| 1491 | 6.017/6.450/7.083 | 9/9 pur 1.0 | 12/12 pur 1.0 | CLIP_START | −3.033/−3.167/−3.750 | 0.000/0.000/−0.583 |
| 1716 | 3.467/3.867/4.500 | 7/9 pur 1.0 | 0/0 (none visible) | GAP | −0.100/0.000/−0.067 | +0.133/0.000/−0.067 |
| 2519 | 5.500/5.800/6.500 | 6/9 pur 0.75 (wrong f337/f345) | 0/11 (wrong f270/f300) | GAP | abstain | abstain (honest) |
| 2742 | 4.188/4.588/5.255 | 9/9 pur 1.0 | 6/6 pur 1.0 | GAP @1.47 s | −2.352/−2.369/−2.986 | −1.168/−1.268/−1.885 |

Pooled: prep 29/70 coverage (0.414 < 0.5), 4 wrong overlaps, flights_ok=false (2519:
0.667) → **verdict FAIL** (not VOID). 16's top-Q (1.039, 0/9) is a competing flight
(simultaneous 3m dive); the rule correctly fell through to Q-rank 8 (pool_rank 5, Q 0.942).

## 4. Attribution (visual + coordinate forensics)

- **1491 — VALIDATED.** Same athlete on one board f0→flight (HUMAN+FAX coincide tightly),
  CLIP_START, 12/12 + 9/9. Single-dive clip.
- **251 — VALIDATED (after adjudication, §5).** Same athlete deck-wait → board-sprint →
  rushed hurdle → center dive; 11/11 + 8/9; CLIP_START. V4 error is prep-rise lock on the
  satellite-board bounce (~4.3 s), not wrong identity.
- **2742 — VALIDATED track.** One athlete mounting/standing/hurdling on one board
  (HUMAN+FAX coincide 6/6), no second dive in clip. V4 error is mount-rise lock (~2.8 s).
- **1716 — honest short track.** Clip opens EMPTY; diver walks in ~3.3 s; all prep anchors
  correctly not-visible; GAP/GAP; flight 7/9. Both logics work (+0.133/−0.100 takeoffs).
- **16 — association failure (crowd drift).** HUMAN right on all 30 prep anchors. Backward
  chain leaves the correct core and is on the wrong object within ~1 s (f466 dist 0.160,
  f481 dist 0.092 — wrong object, not radius noise), then AMBIGUOUS stop at f465
  (margin 0.015; diver candidate in floor @ conf 0.007 but gated out). Scene: TWO
  SIMULTANEOUS divers (1m blue + 3m dark) + walkers-by. Stop desirable; 2 prior wrong
  links are the violation.
- **2519 — association failure (static-junk ride).** HUMAN right (diver waiting at pool
  edge; S3 conf med 0.77 @ 10/11 prep anchors). Chain steps off the diver onto a frozen
  water-junk box (0.515, 0.489, conf 0.001–0.01) via an IoU-0.10 handoff (f334) and rides
  it 0.35 s (IoU≈1.0); GAP back at f243 (t=4.05). Partial flight (starts 0.27 s
  post-takeoff, 6/9). Residual-margin uniqueness systematically favors the static
  distractor over the moving diver at handoffs. Both logics abstain = honest output.

Floor presence at HUMAN prep anchors (radius 0.06): 16: 19/30 (conf med 0.033);
2519: 10/11 (0.772); 2742: 6/6 (0.246); 1491: 11/12 (0.780); 1716: n/a (0 visible).
Total 56/65 (86%) — perception SUFFICIENT; failures are association.

## 5. 251 identity-adjudication episode (recorded, not hidden)

Designer initially read two continuous bodies (deck-waiter vs board-hurdler) with the dive
leaving from center, no second dive in clip (t=6.5–14.7 pool-only verified) → provisional
shared-HUMAN-error finding. Targeted annotator adjudication returned SAME ATHLETE
(deck-wait → board-sprint → dive). Adjudication ACCEPTED (first-hand identity knowledge
beats 202×360 pixels); provisional finding retracted; 251 graded legitimate. Consequence:
V4's −0.883 is prep-rise lock on a legitimate complex track (unifies with 2742).
Policy: targeted adjudication is now the identity firewall; never unilaterally overturn
HUMAN identity (this also qualifies DEV 21/33 purity as unverified-not-refuted on identity).

## 6. Landmark readouts

- V3-C0 still fails on validated tracks (1491/2742/251: −1.9…−3.1 s) — first-motion firing.
- V4-B0 on identity-clean {1491, 2742, 251, 1716}: takeoff errs 0.000/−1.168/−0.883/+0.133
  (median |err| 0.508 vs V3-C0 2.142; with flight-validated 16: 0.133 vs 2.033).
  Apex EXACT on clean takeoffs (1491/1716: 0.000 — first validated fresh apex errors).
  WC mixed (1716 −0.067, 16 −0.167 fine; 1491 −0.583 water-line-threshold semantics).
  Predeclared bar: narrowly missed strict n=4 (0.508), met n=5 (0.133); apex/contact
  strongly improved either way. Material improvement: YES.
- New mode: prep-rise lock (mount/bounce rises ~0.9–1.2 s early; smoothing can erase the
  true hurdle dip). Successor-cycle direction: prefer the sustained rise CLOSEST to ft0.
  No change here (FAT3 is validation).

## 7. Definition-of-done answers

1. FAX V1 generalizes on fresh visible-prep dives? YES where identity is unambiguous
   (29/29 @ 1.0 on 1491/251/2742); NO in multi-person prep (16/2519).
2. Perception or extension? EXTENSION (56/65 floor presence; wrong-identity links).
3. Stable overlay viable? CONDITIONAL (sparse scenes yes; crowds no — confident-wrong risk).
4. V3-C0 still fails on fresh validated trajectories? YES (−2.4…−3.0 s).
5. Versioned successor materially improves? YES (4–16× takeoff; exact apexes) with a
   documented prep-rise failure mode.
6. Pose/geometry resume? NO — identity blocker first.
7. Remaining blocker? Trajectory extension = identity-aware association (neither
   perception-during-prep nor event-semantics).

## 8. Integration record

`69ad2f2` queue+protocol → `39bba63` V4-B0 (+eval/overlay scripts) → `34fb42b` viewer fix →
`a2eade0` authority (184 files) → `48dd1e8` gate report (+eval/overlay self-containment
fixes: latent FAT2-path bugs — fax_eval import, SELECTED-row assignment, rep-dict cache;
gate ran on SHA `81dd9d03…`) → `4d053f0` PROJECT_STATE. Frozen modified: NONE
(FAX/V3-C0/S3/D5/S2/FSR/identity/ReID/reference-acquisition/Media Backbone/ARMSTAND/pose;
only new files + PROJECT_STATE + my own new scripts changed). Concurrent worktree state
untouched. .gitignore: `runs/full_action_fat3/`, `runs/fat3_annotation/`, `runs/fat3_media/`.
Host-only: S3 FAT3 caches, `fat3_gate_results.json`, overlays, DEV repro (exact match),
y(t)+adjudication strips, annotation work dir, contact sheets, B2-manifest + proxy registry.

## 9. Pending work (next session/cycle)

1. FAX successor cycle (identity-aware association): own protocol + fresh validation
   authority (FAT3 burned); design inputs: static-distractor residual loss (2519),
   crowd drift + late AMBIGUOUS (16), rise-proximity takeoff (251/2742 V4 mode).
2. Bounded overlay pilot on sparse-scene tracks with identity-risk flagging.
3. Optional: retrospective identity audit of DEV FAT1 purity (251 precedent); wc
   first-touch vs water-line semantics (1491 −0.583).
4. Ghost-exclusion watch continues (no recurrence this cycle).
