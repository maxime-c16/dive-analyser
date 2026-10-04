# FAX V3 first fresh readout (FAX3, DEVELOPMENT)

2026-09-27. The V3 candidate and raw-only FAX3 queue were committed at
`5a29f85` before HUMAN geometry was available. Four disjoint sessions
(1515/s94, 2086/s128, 2160/s131, 2674/s156) were labeled blind on raw
proxies. `FULL_ACTION_GT_HUMAN_FAX3_FRESH` has 150 individual records plus
events, no exclusions, apex repeat disagreement 0–0.0334 s, manifest digest
`9a9e712c052625d39f03306c2a910955d22e65ffd67c66c77232767a7c1ef1d5`
and manifest SHA256
`c0904d8c851bfc0c7a6f5732a38b23e56f6dd50c0343d638769440245efe7e07`.
The S3 cache used frozen model SHA256 `3dc07f69…`, conf `.001`, NMS `.45`,
imgsz 640, cap 200 and no GT payload. The HUMAN click rule selected one
correct FSR flight on each dive.

| Dive | Correct prep | Honest prep abstention | Wrong prep center | Correct flight | Post | Longest missing prep |
|---|---:|---:|---:|---:|---:|---:|
| 1515 | 5/21 | 16 | 0 | 8/9 | 0/1 | 6.506 s |
| 2086 | 6/9 | 3 | 0 | 9/9 | 0/1 | 1.000 s |
| 2160 | 14/15 | 1 | 0 | 9/9 | 1/1 | 0 s (single missed anchor) |
| 2674 | 0/6 | 6 | 0 | 7/9 | 1/1 | 2.502 s |

Pooled V1, V2 and V3 results are identical: correct prep 25/51 (49.0%),
wrong-person prep overlap 0, honest prep abstention 26/51, flight center hits
33/36, post 2/4, full-action center hits 60/91. All four selected flight
source paths were preserved (core lengths 86, 94, 32, 58). The two 2674
flight center misses were visually checked on raw frames: one diver is visible
and the boxes are offset/partial, so these are localization misses, not
evidence of a person switch. The first wrong-person link is therefore none in
this sampled round. Adjacent center jumps above 0.06 are 0/0/1/3 by dive;
maximum adjacent jumps are .060/.021/.067/.075 normalized. The largest
absolute log-area steps are .774/.535/.638/.729. These are descriptive box
stability measures, not identity proof.

There are **zero detected mixed selected-flight edges in four**. Raw 1515
and 2086 contain competing people, but their selected S3 edge boxes remain
person-sized (edge widths .262 and .165 normalized; 2160 .317, 2674 .316).
No V3 mixed-edge safeguard fires. This round validates that the abstention
candidate preserves clean continuation, but it is non-discriminating for the
205-class failure. It cannot clear the overlay gate or establish V3 superiority.

Residuals are distinct. On 2674, S3 floor candidates are near the HUMAN
target at all 6 prep anchors, but the V1/V2/V3 backward link stops at 5.923 s
before the last prep anchor: association/bridge coverage failure, not floor
recall. On 1515, 17/21 prep anchors have a nearby floor candidate but only
5 are linked; the 6.506-s missing interval is a trajectory coverage issue in
a multiple-action clip. On 2086, the 6/9 prep hits match its 6/9 nearby
floor-candidate ceiling. 2160 is a clean continuation control. 1363 remains
a separate perception-limited case; 1751 remains upstream flight surfacing.

The consumed FAX2 comparison remains development evidence: V1/V2 gave
7/54 correct prep, 26 wrong-person prep overlaps and 21 abstentions; V3
gives 7/54 correct, zero wrong overlaps and 47 abstentions by marking 205's
selected mixed-edge path unresolved. V3 does not infer the target body inside
that box. A high-resolution crop of consumed 205 at f1102 resolves two
candidate boxes (centers x=.247/conf=.037 and x=.384/conf=.483); at f1108 it
again finds separated candidates, but f1116 partly merges them. No reliable
reconnection or appearance separation has been measured. No high-resolution
path is promoted.

Decision: **fresh mixed-box gate remains untested**. FAX3B was selected from
raw B2 contact sheets to stress adjacent-board situations. Full-action box
overlays and pose remain paused. Event Logic stays frozen.
