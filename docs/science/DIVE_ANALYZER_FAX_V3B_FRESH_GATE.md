# FAX V3B targeted mixed-person fresh gate — FAIL for product readiness

2026-09-27. FAX V3 candidate/thresholds were committed at `5a29f85` and
unchanged for this gate. The raw-only FAX3B queue was committed at `c5914d9`
before S3/FSR outcomes or HUMAN geometry were inspected. Four session-disjoint
DEVELOPMENT clips were included: 164/s26, 200/s27, 389/s34, 373/s33.
The annotator saw raw study-local proxies only. Sources were fetched B2
read-only, SHA-checked against `media_blobs`, and proxies have host-only PTS
and SHA registry. Protected data and B2 were not mutated. `diver_id` was
never used for association.

The sealed blind `FULL_ACTION_GT_HUMAN_FAX3B_FRESH` authority has 110
individual records plus events, no exclusions, apex-repeat disagreement
0–0.0333 s, digest
`0cf6e1d96524238b591bb24d20f6ea482b5281602be06635e6a18aba02b435f1`
and manifest SHA256
`8b2812584ce829494666b56941f5c9fc4bc55ffe8753edb10e09327ef6886b2d`.
Frozen S3 cache SHA256 is
`3bf64125b3787b1220704f69abfdfaf1d6444f7283bf1a901fae6c2622dec58e`,
model SHA256 `3dc07f69…`, conf .001, NMS .45, imgsz 640, floor cap 200,
GT payload NONE. FSR and the established first-qualifying user-click
emulation rule were unchanged. Three of four correct flights qualified;
373 did not (top Q only 2/9 flight hits, a lower candidate 5/9).

| Dive | Outcome | V1/V2 correct prep | V3 correct prep | V3 abstained prep | Wrong-person prep | V1/V2 flight | V3 flight | V3 mixed edge |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 164 | selected | 0/7 | 0/7 | 7 | 0 | 8/9 | 0/9 | yes |
| 200 | selected | 13/14 | 13/14 | 1 | 0 | 8/9 | 8/9 | no |
| 389 | selected | 10/10 | 10/10 | 0 | 0 | 8/9 | 8/9 | no |
| 373 | unsurfaced | — | — | — | — | — | — | not scored |

Selected pooled V1/V2: 23/31 correct prep (74.2%), 8 honest prep
abstentions, 0 sampled wrong-person prep overlaps, 24/27 flight center
hits and 3/3 post hits. V3: the same 23/31 correct prep, 8 abstentions and
0 wrong prep overlaps, but flight falls to 16/27 and post to 2/3 because
the 164 mixed path is withheld. Correct full-action center hits fall from
50/61 to 41/61. First sampled wrong-person link: none for all three methods.
The center misses on 164 f214 and 389 f296 were visually adjudicated as
partial/shifted boxes on the target, not person switches. The first wrong
*center* is not a first wrong *identity* link.

## Mixed-box and interval findings

At 164 selected core edge f217 (3.617 s), the S3 box
`(cx=.386, cy=.412, w=.450, h=.344)` spans the selected launching diver and
another visible person near the left platform. A separate compact body
near x=.596 was repeatedly detected before the edge. V3 correctly identifies
the edge as unresolved, retains 74 selected source frames as provenance, and
emits an explicit `MIXED_FLIGHT_EDGE` state with compact/group/NULL
alternatives. It does **not** assert a person-specific box from this mixed
observation. It also fails to recover the clear target-specific flight
subcore visible by f241 (the selected core box has width .210 there). Thus
the selected physical diver remains represented as a chosen source path and
an uncertainty interval, but not as a useful person-specific overlay on
164. The visible target has no asserted V3 box from 0 to 4.717 s.

Visual prep inspection of 200 and 389 confirms their scored boxes continue
on the HUMAN target. Some 389 broad boxes touch the adjacent person's edge,
showing that center-radius purity alone is not an instance-purity guarantee;
these are not adjudicated as a full person switch. At sampled anchors, mixed
selected-flight-edge incidence is 1/3 selected; a framewise census of all
mixed detector boxes was not made. The V3 mixed trigger is therefore a
useful abstention signal, but its calibration is too conservative for a
full-action overlay and has not shown a fresh reduction in wrong-person
continuations relative to V1/V2.

Longest missing visible prep run is 3.0 s on 164 (both V1/V2 and V3),
zero-duration single-anchor gaps on 200/389. V3's full visible missing span
on 164 is 4.717 s through the post probe. Adjacent-box jumps >.06 are
0/1/0 for V1/V2 on 164/200/389, with max steps .053/.088/.053 and
max absolute log-area steps .499/.517/.569. V3 has no asserted 164 boxes;
on 200/389 its stability is identical to V2. Flight source paths were
preserved on all selected dives; 164's person-specific flight overlay was not.

## Attribution and decision

- **164:** a true mixed selected-flight edge, followed by a clear later
  target subcore. V3 represents uncertainty safely but over-abstains. The
  prep gap is also perception-limited: S3 has 0/7 candidates near visible
  target prep anchors. Association alone cannot recover those prep frames.
- **200/389:** useful clean continuation with nearby people. S3 has target
  candidates at 13/14 and 10/10 prep anchors; V1/V2/V3 cover exactly those.
- **373:** upstream flight-surfacing failure, separate from extension. It
  cannot enter selected-flight-conditioned scoring.
- **205 (consumed FAX2):** association/representation failure; V3 changes
  26 wrong prep overlaps to explicit abstention, but that is only development
  evidence. **1363** remains floor-recall-limited; **1751** upstream
  flight-surfacing-limited.

**Decision: FAX V3 is not promoted.** It handles a detected mixed edge by
honest abstention, but fresh data show no improvement over V1/V2 in wrong
person continuation and a material loss of flight coverage. The next
association method needs a trusted person-specific subcore and bounded
competing paths that can reattach after a merge, with uncertainty until
the reconnection is proved. Targeted higher-resolution 205 crops separate
two candidate people at some frames but merge again; no instance-level
path is validated. Full-action box overlays remain unsafe for a general
pilot. Event Logic V3-C0/V4-B0 stays frozen; pose remains paused. The next
blocker is **calibrated reattachment after a mixed interval**, with separate
perception work for 1363/164 prep and upstream flight surfacing for
1751/373.

Gate: `SUPERVISOR_REVIEW_AFTER_UNCERTAINTY_AWARE_FULL_ACTION_TRACKING`.
