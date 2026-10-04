# FAT2 gate V1 — verdict: VOID (not a FAX failure finding)

**Gate verdict: `FAT2_GATE_VOID`.** Neither fresh dive passes the frozen
flight-recovery rule, so the conditional selected-track set is empty and
criteria (ii)-(iv) cannot be evaluated. This void is reported exactly as the
predeclared protocol demands; the diagnostic layer below is non-gate
evidence from frozen code and cannot change the verdict.

## Strict gate record (frozen rule, fresh HUMAN flight boxes)

| Dive | Top-Q candidate | Hits/anchors | Verdict |
|---|---|---|---|
| 1190 | 360, Q 0.669, ft 6.60-7.47 | 6/9 | UNSURFACED |
| 1279 | 360, Q 0.526, ft 0.97-1.67 | 4/9 | UNSURFACED |
| 2838 | — | — | ANNOTATOR-EXCLUDED (unlabelable clip) |

## Why (diagnostic, frozen code, post-freeze)

- **1190 is the correct flight, missed on localization noise.** Per-anchor:
  6 hits, two boundary misses (0.061, 0.080 over the frozen 0.06 radius),
  one mid-flight detector gap (f211). Confidences 0.6-0.85, visual overlay
  shows the right diver through flight into entry. A user would click it;
  the rule's radius strictness on a small subject blocks it. Evaluator
  judgment (n=1, labeled): identity correct, localization noisy.
- **1279 is a partial flight (takeoff-region recall miss).** The segment
  starts 0.30 s after HUMAN takeoff (0.97 vs 0.67) and ends before contact;
  the pool path's pre-flight nodes sit 0.22 off the takeoff box. The dive
  itself is a short-prep regime (2 distinct prep frames: f0/f15).
- **S3 prep recall is ~0 on both fresh dives.** At every HUMAN prep anchor
  (1190: 13 partial; 1279: 2 visible + repeat) the floor has no candidate
  within radius on 360 (hq adds two conf-0.001 blips on 1190). DEV dives had
  near subjects with dense prep candidates; fresh dives have small/partial
  prep figures the detector never sees. This is a perception-coverage bound
  on the product path (S3 training stays frozen this cycle), not an
  extension bug.

## Fresh abstention evidence (real, non-gate)

Where S3 sees nothing, FAX links nothing: 1190 FAX = 30-obs flight-only
track (prep 0/13, GAP stops labeled both ends); 1279 FAX = 25-obs short
track (prep 0/2). Zero hallucinated prep across 15 prep anchors against
honest GAP stops. The uncertainty design holds on fresh data precisely
where a wander-prone method would invent trajectory.

## Event Logic diagnostics (fresh, non-gate; first scored apex)

Frozen V3-C0 abstains on both short tracks (no prep plateau — defensible,
uninformative). V4-A0 DEV probe: 1190 to −0.167 / apex 0.000 / wc −0.533;
1279 to +0.167 / apex +0.067 / wc −0.267. Same envelope as DEV (14/17
within ±0.5 s takeoff, systematic ~0.25 s bias question open). First HUMAN
apex errors ever scored for the successor direction; they corroborate
rather than validate (n=2, non-gate tracks).

## Conclusion

FAT2 as drawn **cannot validate FAX prep recovery** (regime mismatch: no
visible-prep dive with detector recall; n=2 with one exclusion). This is
not evidence against FAX: DEV (21/33 prep at purity 1.0) stands as design
evidence, still unvalidated. The validated fresh findings are: (1) correct
abstention under zero prep evidence, (2) S3 prep-recall bound on
small/partial figures, (3) 1190-class flights surface correctly below the
historical radius bar, (4) V4-DEV envelope reproduces on fresh tracks
including exact apex on 1190.

Next: one more targeted fresh round in the FAT1 regime (long visible prep,
near subjects, new sessions) combined with EL-successor validation (apex
authority now proven collectible at 0.033 s agreement); then the bounded
overlay pilot. Alternatively, if no further annotation is authorized, the
program continues on DEV evidence with explicitly unvalidated status.

Exact record (host-only): `runs/full_action_fax_v1/fat2_gate_results.json`.
Sealed viability (opened post-freeze): `runs/full_action_fax_v1/sealed/`.
Overlays (evaluation viewing): `runs/full_action_fax_v1/overlays/FAT2_*_top.png`.
