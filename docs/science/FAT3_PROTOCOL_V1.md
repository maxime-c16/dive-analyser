# FAT3 protocol V1 (FROZEN BEFORE ANNOTATION)

## Question

> Given a correct selected flight and observable preparation, does frozen
> FAX V1 recover the same diver through the meaningful action — on fresh
> session-disjoint DEVELOPMENT data in the visible-preparation regime?

Follow-up (same frozen tracks, separate verdict):

> Does a versioned flight-anchored Event Logic successor produce reliable
> takeoff / apex / water-contact landmarks on those validated tracks?

Causal order is enforced: landmark logic is evaluated ONLY on tracks that
independently pass the full-action quality gate. Event Logic success never
compensates for a bad trajectory.

## Frozen inputs

- FAX V1: `experiments/full_action/fax_extension_v1.py` (SHA-256
  `55282fb968cc960919242ee43ef9ebd3db7c13becbd663aab35b3b150306a2ad`);
  protocol `experiments/full_action/FAX_V1_PROTOCOL.md`. Tested unchanged.
- S3 detector `3dc07f69…` (weights SHA asserted before/after inference).
- Frozen FSR search/ranker (selection = user-click emulation).
- Event Logic V3-C0 (baseline replay, unchanged).
- Event Logic successor: designed and frozen on DEV evidence ONLY (FAT1 /
  FGT3H FAX tracks + pre-existing event GT + FAT2 fresh events as design
  evidence). Frozen BEFORE the FAT3 authority opens. Its freeze doc names
  the exact module + SHA + calibration constants. No threshold tuning on
  FAT3, ever.

## Fresh authority

`FULL_ACTION_GT_HUMAN_V3_FRESH` (6 dives: 16/251/1491/1716/2519/2742;
reserve 735 enters only on annotator-exclusion with identical steps):
takeoff, water contact, apex + independent apex repeat; flight k/8 boxes;
prep every 0.5 s; post +0.1/+0.3/+0.5 s; one blind PREP repeat per dive.
Queue: `docs/science/FAT3_ANNOTATION_QUEUE_V1.md`.
Tool: `experiments/full_action/fat3_annotation_v1.py`.

## Gate rule (predeclared; frozen FAX code unchanged)

Per dive, emulate the user click: first Q-ordered candidate passing the
frozen recovery rule (hits >= 2, coverage >= 0.75, purity >= 0.75 on fresh
flight boxes, radius 0.06). No candidate qualifies -> dive recorded
UNSURFACED (perception failure in the funnel denominator); no conditional
track statistics for that dive.

- (i) flight coverage >= 0.75 AND purity >= 0.75 on every selected track;
- (ii) pooled prep purity 1.0 on overlapping visible anchors (zero silently
  linked wrong-person prep);
- (iii) pooled prep coverage >= 0.5 over visible anchors (honest stops
  count as missing, not errors);
- (iv) 100 % of track ends carry a labeled stop reason.
- Gate verdict: PASS iff (i)-(iv) hold on >= 4 selected tracks with (ii)
  exact; else VOID (conditional set too small, FAT2 precedent) or FAIL
  (a selected track violates (ii), or pooled coverage < 0.5).

## Failure attribution (if FAX fails)

Classify each failure as exactly one of: perception/observation (S3 floor
has no candidate at HUMAN anchors), genuine association/extension (floor
has the diver but FAX stops/wanders), ambiguity handling (near-tie stop
where a human would commit, or linked through ambiguity), post-entry
morphing, implementation defect. Only a demonstrated algorithmic
limitation (not perception) justifies a FAX successor. FAX V1 stays
unchanged regardless.

## Landmark evaluation (predeclared; on gate-passing tracks only)

- Replay frozen V3-C0 unchanged (baseline).
- Evaluate the frozen successor (module + SHA named in its freeze doc).
- Report signed AND absolute errors for takeoff / apex / water contact;
  abstention counted separately from wrong prediction.
- Successor bar (predeclared): median |takeoff error| <= 0.5 s across
  gate-passing tracks, with apex/contact not regressed vs V3-C0 medians.
  No threshold is touched after seeing FAT3.

## Product readouts (predeclared)

- Full-action box overlay viable iff gate PASSES with prep purity 1.0 and
  flight coverage/purity >= 0.75 on every selected track.
- Pose/geometry resumes iff overlay is viable AND the landmark bar is met.
- Remaining blocker named as exactly one of: perception-during-prep,
  trajectory-extension, event-semantics. No conflation.

## Firewalls

- Protected: Paris, INTERNAL_EVAL, FINAL_HOLDOUT, 524, 2555 — never
  DEVELOPMENT evidence here. No B2/production-media mutation. No detector
  training. Identity/ReID, reference acquisition, Media Backbone, ARMSTAND,
  pose/biomechanics: paused.
- S3 caches + FSR selection for the 6 queued dives + reserve are built
  GT-free after the queue commit and stay sealed (`runs/full_action_fat3/`
  `sealed/`) until the authority freeze. The annotator never opens them.
- The successor freeze precedes the FAT3 freeze. FAT1/FGT3H/FAT2 are design
  evidence and are never re-scored as validation.

Eval: `experiments/full_action/fat3_fresh_eval_v1.py` (written at successor
freeze; scoring semantics = FAT2 `score_phase`/`score_track` + successor
errors). Host-only numbers: `runs/full_action_fat3/fat3_gate_results.json`.
