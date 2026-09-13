# DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1

Packet: `DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1`
Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1`
Date: 2026-09-13
Branch: `subject-resolution-cohort-expansion-v1` (base = canonical `uiux-overhaul-pro-app` @ `7289037`)

## Phase 0 — Fresh preflight

- Accepted V2 canonical `72890378810574164caaacee731133aee3b06559` verified as
  `origin/uiux-overhaul-pro-app` HEAD (server canonical). Local `uiux-overhaul-pro-app`
  branch pointer was stale at `c4c9cfc`; this packet's branch was cut from `7289037`.
- Dedicated worktree `~/.perso/diveanalyzer-cohort-exp`. Concurrent threads untouched:
  UI (`diveanalyzer-perception`, dirty main worktree), core-detection, media-backbone
  P8/P9/P10, identity-v2, sci-v2, subject-resolution worktrees all preserved.
- Host caches symlinked/copied read-only from `diveanalyzer-prototype-v3` (provenance
  verified by SHA before use). New caches written to `runs/subject_resolution/` (outside Git).
- Frozen D5 identity re-verified: `DIVER_DETECTOR_D5_A_V8N_best.pt`
  sha256 `82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25`;
  OSNet `osnet_x1_0_market1501.pth` sha256 `2809d3227f7d078f6045f7feb874a34d0684f0e0057b264b99adccf7d4519154`.

## Phase 1 — Development authority census

Complete table in the JSON artifact (`development_authority_census`). Summary:

| Dive | Family | Subject authority | GT level | D5 full-candidate cache | Appearance cache |
|---|---|---|---|---|---|
| 1040 | HURDLE_ORDINARY | target_chains_v1 | FULL_SUBJECT_GT | yes (V1) | yes (V1) |
| 2169 | HURDLE_ORDINARY | target_chains_v1 | FULL_SUBJECT_GT | yes (V1) | yes (V1) |
| 2341 | HURDLE_ORDINARY | target_chains_v1 | FULL_SUBJECT_GT | yes (V1) | yes (V1) |
| 2353 | HURDLE_DRILL | target_chains_v1 | FULL_SUBJECT_GT | yes (V1) | yes (V1) |
| 2541 | HURDLE_ORDINARY | target_chains_v1 | FULL_SUBJECT_GT | yes (V1) | yes (V1) |
| 524 | HURDLE_AUTHORITY_CONFLICT | none usable | NO_SUBJECT_GT | present, EXCLUDED | — |
| 2555 | HURDLE_STRESS (screen rec.) | chains, 239/635 AMBIGUOUS | SPARSE_SUBJECT_GT | present, EXCLUDED from primary | yes, not loaded |
| 133 | STANDING | 3 human bbox anchors + temporal GT | SPARSE_SUBJECT_GT | **NEW (this packet)** | **NEW** |
| 311 | STANDING | 4 human bbox anchors + temporal GT | SPARSE_SUBJECT_GT | **NEW** | **NEW** |
| 676 | STANDING | 9 human bbox anchors + temporal GT | SPARSE_SUBJECT_GT | **NEW** | **NEW** |
| 2387 | STANDING | 3 human bbox anchors + temporal GT | SPARSE_SUBJECT_GT | **NEW** | **NEW** |
| 2661 | ARMSTAND | 8 human bbox anchors | SPARSE_SUBJECT_GT | none (proxy not materialized) | none |
| 2680 | ARMSTAND | 6 human bbox anchors | SPARSE_SUBJECT_GT | none (proxy not materialized) | none |
| 2625 | NO_TAKEOFF_GT | 4 wc-only anchors | SPARSE_SUBJECT_GT | none | none |

Pre-existing `STANDING_TRAJ_CACHE_V2` (133/311/676/2387) is a **single-target
framewise trajectory cache**, not a multi-person candidate cache — it cannot support
subject-resolution evaluation. `DEV_D5_ONLY_EVAL_V1` anchor IoUs are D5 top-1 vs human
anchor boxes at 2–3 event frames per dive (model-vs-GT comparison, not GT itself).

## Phase 2 — Protected-data firewall

- `FINAL_HOLDOUT`: no holdout set exists in any science artifact; NOT_ACCESSED.
- `INTERNAL_EVAL` (160/169/191/192/848/2281): NOT_ACCESSED.
- Paris / IMG_1937: `EXTERNAL_ONLY`; not accessed.
- 524: `AUTHORITY_CONFLICT_EXCLUDED`; its V1 cache record was not loaded or modified;
  no 524 proxy exists in the materialized proxy set.
- 2555: `SCREEN_RECORDING_STRESS_CASE`; cache exists from V1 but was not loaded,
  not evaluated, and is excluded from the primary cohort.

## Phase 6/7 — Frozen D5 cache materialization + determinism

New artifact `runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json`
(GT-free schema identical to `R5_FULLCLIP_CANDIDATES_V1`; no `gt_eval_only` payload;
proxy SHA verified against frozen `STANDING_TRAJ_CACHE_V2` before inference):

| Dive | Frames | Candidates | Runtime | Peak RAM |
|---|---|---|---|---|
| 133 | 178 | 11 803 | 4.0 s | 0.54 GB |
| 311 | 577 | 41 914 | 9.3 s | 0.56 GB |
| 676 | 222 | 19 504 | 4.2 s | 0.57 GB |
| 2387 | 748 | 71 508 | 11.8 s | 0.60 GB |

- Determinism: bounded re-run of 133 reproduced **0/178 differing frames**
  (byte-equal candidate lists) under the frozen protocol.
- Cross-check: per-frame best candidate matches the frozen `STANDING_TRAJ_CACHE_V2`
  within 0.02 cy/bh on **all** comparable frames (0 mismatches in 104/358/181/667
  frames) ⇒ frozen D5 semantics reproduced exactly; frozen D5 behaves well on STANDING.
- Cache SHA256: `b2f01e4116466a6ac7f48de7361c3f9d5586a0902ad3f2a68d55b5348b53403f`.

## Phase 8 — Appearance cache materialization

New artifact `runs/subject_resolution/osnet_emb_cohort_v1.npz` — 144 729 crops
(11803+41914+19504+71508), exact frozen recipe (pad 1.3, 256×128, L2, MPS, batch 32),
runtime 1195 s total, peak RSS 0.57 GB. Meta JSON records weights SHA + recipe.
Cache SHA256: `4d8360026bb8276599262ac87b8c0b8a695c7536d9f0a3df2394450c43dd0b8d`.
This brings the four STANDING dives to full parity with HURDLE cache authority.

## Phase 4/9 — Subject-GT sufficiency audit (no self-labeling)

Human-authoritative annotation inventory for non-HURDLE candidates
(all `HUMAN_REVIEWED`, annotator `maxime`, in `docs/science/localization_annotations_v1/`):
`DEVELOPMENT_DESIGN` event-frame boxes (2–3/dive), `D4_ANNOTATION_BATCH` mining boxes
(676: 4, 2680: 3), `D5_ANNOTATION_BATCH` mining boxes (311: 4, 676: 4, 2661: 8, 2680: 4,
2625: 4). These are genuine human boxes, not model outputs.

**Derivation test (deterministic, geometry-only, no model):** seeding a
nearest-candidate walker (gate 0.05, pure geometry) from each human anchor and
requiring multi-anchor chain agreement **fails defensibility**:

- 676 (9 anchors, ~0.8 s spacing): 49 conflicting frames out of 148 covered;
  conflicts cluster at 1 s, 4 s, 5 s (two nearby people swap the walker).
- 133/2387/311: zero overlap frames where all anchor-seeded chains agree.
- Forward-walk survival from anchors: median 0.73 s, p25 0.17 s.

Verdicts (exactly one per dive):
- STANDING 133/311/676/2387: **SUBJECT_GT_INSUFFICIENT** (SPARSE_SUBJECT_GT).
- ARMSTAND 2661/2680: **SUBJECT_GT_INSUFFICIENT** (also no proxy/candidate cache).
- HURDLE 1040/2169/2341/2353/2541: **SUBJECT_GT_ALREADY_SUFFICIENT** (unchanged).

The forbidden pattern (human takeoff timestamp + D5 nearest person ⇒ "GT") was
explicitly rejected. No synthetic GT was created.

## Phase 10/11 — Minimum GT requirement + Level A/B

**Level A (reference correctness)** is answerable on STANDING **only when the
candidate reference span contains a human anchor frame**. To certify an arbitrary
reference interval, anchors at ~0.5 s spacing over the eval window `[0, wc+0.5s]`
are required — derived from measured walker survival, not assumed:
133 → 7, 311 → 31, 676 → 11, 2387 → 12 anchor units (≈2× at 0.25 s spacing).
Full spec: `docs/science/SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1.md` (plan only; no
labels collected in this packet).

**Level B (downstream framewise matching)** requires per-frame chain authority like
HURDLE `target_chains_v1`; NOT derivable from existing STANDING/ARMSTAND annotations
(walker conflicts measured above). Hundreds of boxes per clip, or a new validated
derivation protocol, would be needed.

## Phase 13/14 — Frozen V2 cross-family replay (bounded)

`V2_CROSS_FAMILY_REPLAY_EXECUTED` — bounded to the acquisition half + anchor-frame
identity check (full replay requires per-frame GT chains that STANDING lacks).
Frozen A0/A1 scorers and constants, GT-free store, new STANDING caches:

| Dive | A0 top-1 subject? | A1 top-1 subject? | Best anchor-consistent rank (A0/A1) | Top-20 contains subject (A0/A1) |
|---|---|---|---|---|
| 133 | NO | NO | 4 / 3 | yes / yes |
| 311 | NO | NO | 89 / 61 | no / no |
| 676 | NO | NO | 9 / 4 | yes / yes |
| 2387 | NO | NO | 13 / 22 | yes / no |

**The V2 failure reproduces outside HURDLE**: A0/A1 top-1 is not the subject on all
4 STANDING dives (anchor-verified). Same failure signature — a wrong stable/static
tracklet outranks the subject. No new rules were derived; nothing was tuned.

## Phase 15/16/17 — Learning gate, balance, decision

- `LEARNING_GATE = COHORT_EXPANSION_REQUIRES_MINIMAL_HUMAN_GT`
  (≥2 families hold for *evaluation-caches*, but learned-reference training labels
  exist only for HURDLE; supervisor policy forbids HURDLE-only training).
- Balance: 9 primary dives, 2 families, subject positives evaluable per-frame on
  HURDLE only; STANDING anchor positives 3/3/9/3; multi-person negatives present in
  all 9; static-structure negatives dominate. Training-eligible ≠ evaluation authority.
- `SCIENCE_DECISION = COLLECT_MINIMAL_SUBJECT_GT_NEXT` — the cheapest unlock is the
  Level-A sparse anchor plan (~61 anchor boxes total across 4 STANDING dives) which
  would make reference-acquisition science multi-family immediately; trajectory
  science waits for Level-B authority.

## Resources / firewalls

0 B2 reads/writes, 0 training, 0 new human labels, 0 protected-data access,
0 Paris access, no scientific authority mutated, no media-backbone mutation.
Peak RAM 0.6 GB (limit 20 GB), strictly sequential, `caffeinate -i -s`.

## Tests

New: `experiments/subject_resolution/test_cohort_expansion_v1.py` (cohort
determinism, family classification, protected-data firewall, Paris/524/2555
exclusions, frozen D5 config identity, cache provenance, no GT self-labeling,
no B2 mutation). Existing regressions: V2 suite 11/11, audit 13/13.

## Git

Science commit on `subject-resolution-cohort-expansion-v1`, integrated into
canonical `uiux-overhaul-pro-app` (server), Mac mirror synced. Final canonical
HEAD recorded in the LOCAL_AGENT_REPORT.
