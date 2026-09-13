# DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1

> Diagnostic + architectural audit. Packet: `DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1`.
> Created: 2026-09-13. Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_AUDIT_V1`.
> Scope: **Dive Analyzer only** (individual edited clip → analysis). Core Detection
> V1 / raw-session spotting belongs to DiveSensei and is out of scope here.
> Discipline: 0 D5 reruns, 0 new embeddings (frozen OSNet cache reused), 0 training,
> 0 new labels, 0 B2 writes, no protected holdout, no Paris development access,
> no Event Logic / HURDLE / D5 / freeze mutation.

## Phase 0 — Fresh authority

| Item | State (verified live 2026-09-13) |
|---|---|
| Canonical | `mcauchy@192.168.1.57:~/dive-analyser`, branch `uiux-overhaul-pro-app`, HEAD `98a3528123e6d2ce17f9dd7d80daf9de3e30c0de` |
| Concurrent dirty state | infra-thread working tree (HTTPS migration, session auth, DB leak fix) — **preserved untouched**; committed separately by its own thread |
| Worktrees | canonical + `hurdle-identity-repair` (detached) + this audit's Mac worktree `~/.perso/diveanalyzer-subject-resolution` (branch `subject-resolution-audit-v1` @ `98a3528`) |
| Mac mirror | `mac-mirror` = `divesensei@192.168.1.19:…/dive-analyser-2026-09-05.git` |
| Lineage | Perception Status Rebase (`437b6af`) → V3/V4 negative history (`d968ad1`) → Media Backbone P11 closure (`8bba4b3`) → Core Detection P0/P1 (`44bd14f`) → merge `98a3528` |

## Headline answer to the packet's central question

**Yes — the reformulation is supported by the data, with one honest correction:**
the historical HURDLE "wrong target" failures are **mostly NOT identity-continuity
failures and mostly NOT cases of correctly following another legitimate diver**.
On 1040/2341 the per-frame selector rode **static background structures**
(non-person false positives); on 2353 it rode a **persistent bystander**; only
2341's next-diver trap is a genuine "other legitimate diver" case. The system
never maintained person tracks at all, so "lost identity continuity" (A) is
rarely the mechanism — the mechanism is **per-frame confidence ranking with no
subject information** (B-adjacent: no subject context) plus non-person
confusion. Product subject identity, however, is **known before vision runs**
on essentially the whole corpus (Phase 1), so subject-conditioned resolution is
architecturally available and measurably helps exactly where generic targetness
failed (Phase 9).

## Phase 1 — Product subject authority

From the production DB (read-only export, `SUBJECT_RESOLUTION_DB_EXPORT_V1.json`):

```text
SUBJECT_AUTHORITY_STRONG:  2798   (diver_id set + FK-valid, minus known artifacts)
SUBJECT_AUTHORITY_PARTIAL:    7   (6× diver_id=19 phantom + 1× SYNCK ambiguity)
SUBJECT_AUTHORITY_MISSING:    0
```

- 2805/2805 dives have `diver_id` set, FK-valid, and `video_uuid` UNIQUE 1:1
  (`MediaRevision.video_uuid → dives.video_uuid → diver_id` is deterministic —
  the ownership chain the auth layer already relies on).
- `person_name` cross-check: 299/299 non-null rows match the diver's
  `display_name` exactly; 0 conflicts.
- **Data-quality finding (new this audit):** `diver_id=19 ("RIP")` is a
  **caption-parsing phantom** — "RIP" is the rip-entry annotation token, misparsed
  as a PersonName (all 6 raw captions end in "RIP"; e.g. 2169 `101B G/P 5m RIP`).
  By the caption grammar's no-name convention these clips belong to the default
  athlete (Maxime). **2169 — the historical HURDLE control dive — is a Maxime
  clip.** `SYNCK` (1 clip, 1928) is ambiguous (typo of SYNC vs a nickname).
  No DB mutation performed (read-only audit); flagged for a future product fix.
- Sync (`is_sync`, 100 dives) and lineup (`is_lineup`, 346) flags exist as
  first-class product semantics.

## Phase 2 — Historical target-GT reconciliation

```text
TARGET_GT_MATCHES_PRODUCT_SUBJECT: 10
TARGET_GT_PRODUCT_SUBJECT_CONFLICT:  1   (2169 — semantic only, GT itself correct)
TARGET_GT_PRODUCT_SUBJECT_UNKNOWN:   1   (524 — no usable anchors, authority conflict)
```

Historical anchors/chains were annotated as "the diver performing this clip's
dive" — i.e. the product subject — wherever usable anchors exist. The only
conflict is the 2169 `diver_id=19` phantom above; the GT boxes track the real
performer. **No GT was reinterpreted or modified.**

## Phase 3 — Multi-person / multi-diver audit

Annotated corpus (14 authorized development dives), scene classification from
the committed record (anchor notes, V2/V3/V4 reports, V4 family benchmark):

```text
SINGLE_DIVE_ACTOR:                        0
MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR:       9   (133, 311, 676, 2387, 1040, 2169, 2353, 2541, +)
MULTIPLE_DIVE_ACTORS_SEQUENTIAL:          1   (2341 — recorded next-diver-on-board trap)
MULTIPLE_DIVE_ACTORS_OVERLAPPING:         0
SYNCHRONIZED_DIVE:                        0
AMBIGUOUS:                                2   (2555 screen recording, 524 authority conflict)
```

(Exact per-dive table in the JSON artifact; 1040's "bystander/fast-mover/next-diver"
candidate families number 9/67/52 — other people are present but only the subject
dives.)

Product-wide metadata prevalence (necessary-not-sufficient proxies):

- 100 sync dives (3.6% of 2805); 31 with a non-primary `diver_id`.
- 36 sessions contain >1 distinct diver; 929 dives live in such sessions
  (636 of them primary-athlete clips).
- 695 distinct clips have another diver's dive timestamped within 20 s
  (382 of them non-sync primary-athlete clips) — a **lower bound** on
  "another diving actor appears near/inside this clip". Visual truth requires
  decode; not swept. **Product-wide multi-diver prevalence: UNCERTAIN, but
  materially present (≥13.6% of primary clips by the timestamp proxy).**

## Phase 4/5 — Failure reinterpretation + reclassification

Per-dive primary mechanism under the new taxonomy (evidence-cited in JSON):

| dive | wrong-object class | new primary failure |
|---|---|---|
| 1040 | NON_PERSON_FALSE_POSITIVE (static structure + pool object) | NON_PERSON_CONFUSION |
| 2341 | NON_PERSON_FALSE_POSITIVE (+ next-diver trap secondary) | SUBJECT_DISAMBIGUATION_FAILURE |
| 2353 | BYSTANDER_NON_DIVER | SUBJECT_DISAMBIGUATION_FAILURE |
| 2541 | AMBIGUOUS (pan + mixed movers) | SUBJECT_DISAMBIGUATION_FAILURE |
| 2169 | NONE (selection correct) | TRACK_FRAGMENTATION (cy artifact 6.406 s) |
| 2555 | AMBIGUOUS (screen recording) | AMBIGUOUS |
| 524 | — | AMBIGUOUS (authority conflict) |
| 676 / 2387 | — | EVENT_LOGIC_DOWNSTREAM |
| 133 / 311 | — | NONE |

**The A-vs-B question is answered:** the selector failed neither by losing
identity continuity (it never had tracks) nor mainly by correctly following
another legitimate diver (that is 2341's secondary trap and 2353's bystander).
It failed by **confidence-ranked per-frame selection with no subject prior,
dominated by static non-person structures** — a pathology that disappears once
tracks exist and the known subject is matched.

## Phase 6 — Subject anchor availability

```text
STRONG_IDENTITY_ANCHOR_AVAILABLE: 3   (133, 311, 2169)
WEAK_IDENTITY_ANCHOR_AVAILABLE:   7   (676, 2387, 1040, 2341, 2353, 2541, 2555)
NO_RELIABLE_IDENTITY_ANCHOR:      1   (524)
```

2169: 8/8 chain-vs-human IoU 1.000, clear platform diver. 133/311: anchor-valid
identity + working Event Logic. The HURDLE failing dives have 4–10 anchors each
but tiny low-confidence prep crops. Diagnostic only — no inference logic built
on GT event times.

## Phase 7/8 — Gallery feasibility & B2 representation

Metadata: 13 divers have ≥2 clips; 8 divers span ≥2 dates. Maxime 2511 clips /
169 sessions / 171 dates; FANNY 128/21; SARA 57/9; MAT 31. **A diver-conditioned
gallery is plausible at the data level.**

Visual/embedding level (Phase 9 H1b): cross-clip matching with the **frozen
Market-1501 OSNet at 360p is currently insufficient** (top-1 ≈ 0 across all
12 same-diver cross-clip pairs — pose transition + crop scale dominate).
Future representation path: 360p crops remain the default for identity
(HQ appearance gain measured MIXED, aggregate AUC 0.923→0.932); HQ becomes
relevant for pose/geometry and possibly for a *learned* matcher later. The old
"frozen D5 on HQ failed → HQ identity is bad" inference remains rejected.

## Phase 9 — H0 vs H1 diagnostic (no training)

Frozen OSNet cache (579,709 keys, sha-verified), GT chains for evaluation only,
full candidate ocean scored per frame:

| dive | H0 D5-top1 | H1a subject@1 | note |
|---|---|---|---|
| 1040 | 0.106 | 0.000 | prep crops tiny/conf 0.001–0.011; pose transition kills NN |
| 2169 | 0.963 | 0.880 | control preserved |
| 2341 | 0.022 | **0.364** | repaired where next-diver/structure dominated |
| 2353 | 0.005 | **0.730** | repaired where bystander dominated |
| 2541 | 0.149 | 0.005 | reference window heuristic misses the late prep (pan) |
| 2555 | 0.518 | 0.024 | screen-recording stress case, as expected |

H1b (cross-clip same-diver reference): ≈ 0 everywhere (see Phase 7).

**Verdict: `SUBJECT_MATCHING_SIGNAL_WEAK`** — the subject-conditioned formulation
removes ambiguity exactly on the historical person-distractor failures (2353,
2341), but reference construction is a real design problem (temporal window
choice, pose transition), and cross-clip gallery matching needs better
representations than frozen Market-1501 OSNet at 360p. Honest limits: the
reference-window heuristic (first 40% of eval interval) is crude; 2541's prep
sits outside it. This is evidence *for* the formulation, not a selector.

## Phase 10 — Synchro decision

**`SYNCHRO_MUST_BE_REPRESENTABLE_BUT_NOT_V1_DRIVER`.** 100/2805 dives (3.6%)
are flagged sync in product data (0 in the annotated science corpus). Not rare
enough to ignore, not prevalent enough to drive V1. Architecture requirement:
**never assume exactly one valid diver exists in a clip**; preserve additional
valid diver tracks through subject resolution (Phase 16 roles make this
concrete).

## Phase 11 — Architecture comparison

| criterion | A target classifier | B dive-actor classifier | C association+subject match | **D hybrid** |
|---|---|---|---|---|
| product correctness | weak (no subject semantics) | weak (subject-agnostic) | strong | strong |
| multi-diver ambiguity | poor | poor | strong | strong |
| synchro extensibility | poor | poor | strong | strong |
| data availability | needs new labels | action labels partial | GT chains exist | GT chains exist |
| training requirement | new head | new head | matcher (later) | junk-filter + matcher (later) |
| overfit risk | high (history) | medium | medium | low-medium |
| compatibility with D5 | yes | yes | yes | yes |
| compatibility with B2 | yes | yes | yes | yes |

**`PREFERRED_ARCHITECTURE = OPTION_D_HYBRID`**:
`D5 proposals → multi-person temporal association → PersonTracks →
eliminate obvious non-divers/non-person junk (frozen action-semantic evidence:
bystander 0.01–0.24 vs diver 0.71–0.96) → match remaining tracks to the known
diver_id → subject trajectory → frozen Event Logic → pose/geometry`.
Perception fact ("track A performs a dive") stays separate from product
semantic ("track A is this Dive record's subject").

## Phase 12/13 — Next learning problem & data sufficiency

**`TRAIN_SUBJECT_CONDITIONED_MATCHER`** (when authorized; not trained here):
- inputs: candidate/track crops (360p; HQ optional) + frozen or fine-tuned embeddings;
- labels already available: GT chains (`HURDLE_TARGET_CHAINS_V1`) on 6 dives,
  ~1.5k GT frames, 3 effective subjects after phantom correction;
- negatives: candidate-ocean crops ≠ target (same frame + temporal);
- grouping: **evaluation grouped by dive/session/subject; random frame-level
  splits forbidden**; LOSO-by-dive minimum;
- leakage risks: same-session same-apparel dives; phantom diver_ids;
  2555 must stay excluded (out-of-domain);
- evaluation unit: per-dive subject trajectory correctness (per-frame top-1
  + longest wrong run), not frame accuracy.

**`EXISTING_DATA_SUFFICIENT_BUT_IMBALANCED`** — sufficient for a first bounded
LOSO experiment on existing GT chains; subject diversity is 1 real athlete
(Maxime) + 1 (FANNY) + 1 stress-excluded, so widening to FANNY/SARA/MAT dives
would eventually need GT chains on their clips (future; not collected now).

## Phase 14 — FM2 reclassification

**`FM2_MIXED_IDENTITY_AND_SUBJECT_DISAMBIGUATION`.** The per-frame selection
that starves FM2's board-level/departure inputs fails through non-person
structure dominance (1040, 2341-primary) *and* subject ambiguity against
legitimate other persons (2353 bystander, 2341 next-diver). Not an
identity-continuity problem (no tracks exist to lose). Event Logic remains
frozen; this changes only the diagnosis.

## Phase 15 — Proposed perception stack (minimal, evidence-justified)

```text
INDIVIDUAL_B2_CLIP (verified PROD, read-only)
↓ frozen D5 proposals (360p; 100% floor availability)
↓ multi-person temporal association (candidate-complete; A1-style bounded graphs)
↓ PersonTracks (preserve ALL plausible diver tracks)
↓ non-diver/junk elimination (frozen action-semantic + static-forever tests)
↓ known-subject resolution (diver_id-conditioned matching; reference from
  product context, e.g. early-clip stable crops / future gallery)
↓ subject trajectory
↓ frozen Event Logic (untouched)
↓ pose / mask / geometry (HQ when durably addressable)
```

## Phase 16 — Multi-subject extensibility

PersonTracks carry a role field reserved for
`PRIMARY | CO_PRIMARY | OTHER_DIVER | BYSTANDER` — assigned only at the
subject-resolution stage; association must never destroy additional valid
diver tracks before that stage. No role logic implemented now.

## Phase 17 — Stop-doing list

1. Generic targetness scoring without `diver_id` context (V2–V7 history).
2. Assuming only one diver performs an action in a clip.
3. Treating every other diver as junk before subject resolution.
4. Per-frame target classification without temporal identity/tracks.
5. HURDLE graph-threshold tuning (paused, unchanged).
6. Using D5 confidence as identity signal (measured anti-informative).
7. Training on random frame-level splits.
8. **New:** per-frame NN appearance matching across the prep→flight pose
   transition without a temporal model (H1a failure mode on 1040/2541).
9. **New:** cross-clip gallery matching with frozen Market-1501 OSNet at 360p
   (H1b ≈ 0) — needs a learned/better representation first.
10. Treating `diver_id=19` ("RIP") as an athlete in any future experiment.

## Phase 18 — Corrected Dive Analyzer roadmap

```text
INDIVIDUAL_B2_CLIP
M1  subject-resolution / identity continuity (PersonTracks + hybrid Option D)
M2  clean subject trajectory (+ frozen Event Logic consumes it)
M3  temporal landmarks (takeoff/apex/water contact at product quality)
M4  pose / mask / body geometry (HQ renditions once durably addressable)
M5  biomechanical metrics
M6  comparison / patterns (athlete-vs-self)
```

No raw-session Core Detection (DiveSensei scope).

## Resource results

- new D5 inference: **0**; new embeddings: **0** (frozen cache reused);
  new model training: **0**; B2 writes: **0**; new labels: **0**;
  protected holdout: **NONE**; Paris development access: **NONE**.
- One bounded decode-free diagnostic on the host OSNet cache (~2 min CPU).

## Tests

`experiments/subject_resolution/test_subject_resolution_audit_v1.py` —
provenance/sha, DB-export consistency, corpus classification schema enums,
GT-reconciliation consistency, protected-data firewall (no holdout/Paris
strings), no B2/HURDLE/EL mutation, deterministic sampling N/A (no sweep),
architecture/decision enums, failure-reclassification consistency.

## Next supervisor decisions (max 5)

1. Accept `OPTION_D_HYBRID` as the Dive Analyzer perception formulation.
2. Authorize `SUBJECT_RESOLUTION_V1` implementation packet (association +
   junk elimination + subject resolution; no training yet).
3. Decide whether the `diver_id=19` phantom fix is a product-side data repair
   (out of science scope) before any multi-diver training.
4. Confirm synchro policy: representable, not V1-driving.
5. Schedule the learned subject-conditioned matcher as M1.5 with LOSO-by-dive
   evaluation and the imbalance caveat.

`SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_AUDIT_V1`
