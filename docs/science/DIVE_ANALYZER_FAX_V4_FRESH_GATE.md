# FAX4 fresh gate — clean controls; mixed-reattachment question untested

2026-09-27. The FAX4 queue was committed at `70b008f` from source metadata
and raw snapshots before opening S3/FSR. The blind HUMAN authority was sealed
at `93b61ef`, with 92 individual files plus events and manifest, digest
`f6bd2af9818c888ad9a44dfc8ecf3dd349e3c0497b06f950b309b02d9492e1c0`,
manifest SHA256 `79821de479410f8d066d72931041213722c5363c347362990eb4fc71bd18f18d`.
Four session-disjoint dives entered the denominator: 2473/s140, 2533/s148,
410/s35, 1667/s102. HUMAN excluded 410 as unlabelable (phone replay screen),
leaving three labelable clips. Apex-repeat disagreement was 0.0501, 0.0667,
and 0.0333 s. Proxy/source identities are in `FAX4_QUEUE_MANIFEST.json` and
`FAX_V4_PROTOCOL.md`. No protected authority, B2 object, or frozen method
was changed.

Frozen S3 model SHA256 `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`,
proxy floor cache SHA256 `632a6ee3869094441c238ab44b7d45cc2d58c5848b25517cc918aee51f3694a9`,
GT payload NONE. Frozen V4 bridge code SHA256
`d13c53584e908d1d9a5ae40f7394d18cc5b1bdf5f2103c7538e7df102048e3b6`;
evaluator SHA256 `3e26a67c82b56434f496d23af322ff4ef8ac9cddb9bda3715c5616fe6bc331f7`.
The host-only result JSON SHA256 is
`351029e2e4ceeacb82342ebc565b180272d3f2bbf81c1732a0e81e65a3c4db5d`.

| Dive | Selected flight | Mixed selected edge | Correct prep | Honest prep NULL | Wrong prep center | Correct flight | Correct post |
|---|---|---|---:|---:|---:|---:|---:|
| 2473 | yes | no | 0/7 | 7 | 0 | 7/9 | 1/1 |
| 2533 | yes | no | 10/13 | 3 | 0 | 9/9 | 1/2 |
| 1667 | no | not scored | — | — | — | — | — |
| 410 | HUMAN excluded | not scored | — | — | — | — | — |

V1, V2, V3, and V4 are identical on both selected tracks. Pooled selected
prep: 10/20 correct (50%), 10 honest abstentions, zero sampled wrong-person
center links; flight: 16/18 correct (88.9%); post: 2/3 correct. Sampled
full-action center coverage is 28/41 (68.3%). Raw overlay review at sampled
anchors shows the tracked physical target on both selected dives. The 2533
prep box at frame 150 touches a nearby swimmer but remains centered on the
selected diver; that is a box-purity limitation, not an adjudicated switch.
First wrong-person link: none observed. Correct reattachment opportunities:
zero, so no reattachment rate can be estimated. Both selected flight source
paths were preserved.

2473 has a 2.50 s longest missing visible-prep anchor run. S3 has a target
candidate at all seven visible prep anchors, but extension stops at an
explicit ambiguous handoff at 8.408 s, before any prep assertion: an
association/coverage abstention, not a perception miss. 2533 has a 1.0 s
longest missing visible-prep run; S3 lacks target candidates at its three
uncovered prep anchors, so that gap is perception-limited. 1667's best
flight candidate hits only 3/9 HUMAN flight anchors and never satisfies
the first-qualifying selection rule: upstream surfacing failure. These are
distinct from the mixed-interval reattachment question.

Adjacent asserted-box center jumps above .06: zero on both selected dives;
max adjacent steps .048 (2473) and .029 (2533). The selected overlay is
stable where asserted. No mixed selected-flight edge occurred, so this
fresh round neither validates nor falsifies the provisional V4 motion
bridge. It does not show a reduction in silent switches relative to V3.
General full-action box overlays remain unsafe in light of consumed 164/205,
and Event Logic/pose remain frozen. A second raw-only targeted queue is
needed for the actual merge/split gate.
