# FAX6 fresh mixed-interval instance gate — local recovery, no promotion

2026-09-27. Raw-only queue frozen at `122ea6818999c2a284975fb9aee4e146832efb5c`;
blind HUMAN authority sealed at `9965c9783e429ac82b6b6c9c6e6c2a15e5820067`
before FAX6 detector inspection. Four new session-disjoint dives (649/s45,
745/s48, 772/s49, 850/s52), no exclusions. Authority contains 109
individual event/box files plus manifest, digest
`a719d25f1e32a22aaededa178925916a6b718284f484a4b24c6d8b411e9a7a45`;
manifest SHA256
`e77bfab011f115fb137b1db0de333e60e1cd58bccbf05219a1f3280aa4f5f92a`.
Apex-repeat disagreements were 0.0167/0.0167/0.0167/0 seconds.
Queue manifest SHA256 `5813d48740f91039f04ef6ebd438361f8df3431e616eeefd4fe8e888ebeab3d5`;
host-only proxy registry SHA256
`095816a83c519dccabac1f3d1cf054f379f90448b07f1dce4a032c70b0c96983`.
Source/proxy hashes and raw-screen selection are in `FAX_V6_PROTOCOL.md`.

Frozen S3 weights SHA256
`3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`;
GT-free S3 floor cache SHA256
`767921b22d45459cd4b8cae6e97e1d8a9c61c8949e6867826ccfc5e8d88a6766`.
Frozen instance bridge source SHA256
`46db2213e4e21f206d58746a57ea26adeaeea353bb0e68a4e5369cbf4731944f`;
separate person-segmentation weights SHA256
`a7cd8f929e1903d78a12a48efecab430209f18dc46cb96c3599a5980c63c423c`.
Evaluator source SHA256: control `cf09b78ebb52d8d29844a517a09ae7d1bd9eda6463622beb182073e51d5b5f8f`,
instance `2ddc8f9bb9e4302e9eec79b4fd60c84988fa7b43fe17205929ace0ea85fd54bc`;
cache builder `058b67420ed74f586815e25887f5d29fb250f1c7986ba9499359c09aeffb9e5b`.
Host-only control result SHA256
`8c2304517d3ee07f967ba38009c2ca85d89e8e19d168fce2da447fc4daad66e7`,
instance summary SHA256
`e8299adbbf0d4faf9e1fea1d93352a01813e51ed20a085eba6941634160318cc`;
host-only mask trajectories: 745
`84d6e116f4dd5286523fd71df5d83afa9395ca413ea24c62647b1aa5131f110e`,
850 `d61a183d1e3157549fd020e40521d08c5cc817ed55e2b8784a799a170ef84f11`.
No B2 objects, protected authorities, or frozen methods were mutated.

649 has no qualifying selected flight: best target-matching pool path hits
only 5/9 HUMAN flight anchors, below the pre-existing 75% selection rule.
This is upstream flight surfacing, not a reattachment failure. 772 has a
clean selected flight and is delegated to frozen V3 behavior; it preserves
11/12 prep, 8/9 flight, and 1/1 post center hits. Its missing prep at frame
0 has an S3 target candidate and is an association edge.

| Fresh mixed selected flight | Mixed edge | First mask assertion | Explicit NULL | Correct asserted HUMAN flight masks | Post | Observed wrong person |
|---|---:|---:|---:|---:|---:|---:|
| 745 | f256, 4.267 s | f280, 4.667 s | 0.400 s | 3/3 (3/9 visible covered) | 1/1 | 0 |
| 850 | f345, 5.756 s | f351, 5.856 s | 0.100 s | 5/5 (5/9 visible covered) | 1/1 | 0 |

The mixed source edge stays NULL; later three-mask trusted subcores are
f284–286 and f356–358. The chosen mask paths contain 39 and 49 consecutive
source frames, ending at unsupported next frames. Sampled overlays at every
HUMAN flight anchor and dense four-frame contact sheets show the selected
physical diver; nearby board people stay outside the asserted masks.
850 f371 is a box-center miss but the mask covers the HUMAN target, not a
wrong-person link. No observed first wrong-link time. Both paths have zero
center steps above .06, with maxima .028 and .051; no internal frame gap.
These observations support local reattachment 2/2, honest pre-reattachment
NULL 2/2, observed wrong-person continuation 0/2. The denominator is two;
these are case results, not population rates.

V3/V4 assert 0/18 mixed-flight HUMAN anchors. The instance bridge restores
8/18 correct physical-person anchors and both immediate post anchors while
maintaining explicit NULL at the edge. With clean 772 delegated to V3, the
candidate has 16/27 correct covered flight anchors, 3/3 post, but only
11/31 correct prep anchors; both mixed clips have 0 prep assertions. V1/V2
have 28/31 prep center hits, 25/27 flight center hits, 3/3 post; visual
review of 745 f180/f238 shows their center misses are partial boxes on the
same selected diver. No physical-person switch was observed in V1/V2 on
this authority. Thus the fresh gate demonstrates recovery relative to
V3/V4 but does **not** demonstrate a reduction in silent switches versus
the ungated baseline, nor acceptable general full-action coverage.

The bridge's longest-supported-path choice is still an unproven safety
heuristic when a wrong branch stays continuous. Individual masks improve
person-specific representation here; they do not certify preparation
identity across the unresolved interval. FAX instance V1 remains
development-only. General full-action box overlays remain unsafe; Event
Logic and pose remain frozen. Remaining association work is a bounded,
two-sided prep-to-trusted-subcore consistency rule that can abstain on
competing branches. Separate perception: 850 f270 has no S3 target box;
legacy 164/1363 prep absences remain. Separate surfacing: 649 here and
legacy 1751/373. No global ReID or `diver_id` is warranted.
