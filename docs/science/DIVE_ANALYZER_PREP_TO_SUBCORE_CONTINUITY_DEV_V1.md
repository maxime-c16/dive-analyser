# Preparation-to-trusted-subcore continuity V1 — consumed development only

2026-09-28. This is a bounded local experiment, **not** a fresh gate or a
general full-action tracker promotion. It consumes FAX2 dive 205 and FAX6
dives 745/850, all previously inspected. FAX6 HUMAN digest is
`a719d25f1e32a22aaededa178925916a6b718284f484a4b24c6d8b411e9a7a45`;
FAX2 authority is read-only. The result is reproducible with
`python3 experiments/full_action/prep_to_subcore_dev_eval.py`; host-only
instance observations, paths, and results live under
`runs/prep_to_subcore_dev/`. None of the frozen S3, FSR, FAX, instance-bridge,
Event Logic, pose, or protected authorities was modified.

Exact SHA256 identities: method
`b71b3f3b4aa61d10fcef30809ecf87e750f30e0e3ac0c147b5a4a95d1319e404`;
evaluator `39681421917a2ff7f0a5f38dbc489f1344915aa14ffd03c87ad007ffa480c734`;
host-only result
`2b4291a370c517c0c0e61f4f02895c4b80d067303fb29fc4cc269292c277bcfc`.
The result JSON includes exact per-dive interval, V1 path, and subcore
artifact hashes. The 205/745/850 interval detection SHAs are respectively
`27c96c88f53d9c5dfc74c17ad3df2d397cffb934ad8d66e3a324069c625c90c6`,
`f5b38ce824ad98b28e30a6f4d9108c0cef5c0f01610c09c696bf4460b40508ed`,
and `d8cf069d8d8c21810f4e34e47b7ad1d3c854c164101e57add4a30216edc80790`.

## Representation and rule

At a selected flight, the existing mask bridge supplies a person-specific
subcore. A separate pre-merge preparation branch is supplied as a hypothesis.
Person masks are inferred at roughly 20 Hz over a bounded 0.8–1.0 s window
spanning the broad S3 edge. A directed graph retains all supported mask links
(time, center movement, scale, mask overlap); dynamic programming keeps the
least-cost path to **each** earlier instance, including competitors and NULL.
The pre-merge branch is connected only if its instance reaches the subcore
and no different ancestor has a near-equal or better path. The full ambiguous
window remains NULL in the proposed overlay; no box is interpolated through
the mixed S3 detections. This tests local continuity, with no `diver_id`.

The thresholds are development choices adjusted after inspecting these
consumed clips (0.12 normalized center step and log-area change up to 1.0
admit the observed fast 745 motion). The 745 static competitor remains more
plausible under this representation; the rule abstains. 205 also abstains:
its backward person-mask path reaches a different pre-merge instance than
the V1 preparation branch. This is the measured separation the old geometric
path lacked, but 205's post-merge mask path has only 6/9 sampled flight
anchors covered, so its endpoint still needs an independent trust check.

| Consumed dive | Prep-to-subcore outcome | Correct prep sampled | Wrong prep sampled | Flight sampled | Immediate post |
|---|---|---:|---:|---:|---:|
| 205 | UNRESOLVED: prep branch not reached | 0/35 | 0; V1 had 26 wrong overlaps | 6/9 center hits; physical review pending | 0/1 |
| 745 | UNRESOLVED: competing prep ancestor | 0/8 | 0 | 3/9 | 1/1 |
| 850 | CONNECTED with NULL interval | 9/11 | 0 | 5/9 mask-person correct (4/9 center hits) | 1/1 |

The 850 connection test spans a 0.984 s NULL interval from the tested prep
endpoint at 4.955 s to the trusted subcore at 5.939 s. A conservative
rendered overlay ending the prep branch before f297 and starting the mask
suffix at f351 has a 0.918 s display gap, no asserted consecutive center
step above .06 (maximum .052), and an existing 0.200 s V1 prep gap that
requires explicit NULL display. On 745 no prep
branch is asserted. The mixed clips together retain 9/19 visible prep,
8/18 physical-person flight, and 2/2 immediate post anchors: 19/39 sampled
full-action anchors. The 850 f371 center miss covers the HUMAN target in its
person mask, as previously reviewed in FAX6. No wrong-person assertion is
observed in these three consumed clips; no first wrong-link time exists here.
The first development summary counted 850 f300 inside its declared NULL
window; this correction excludes it from the overlay and reduces the strict
prep count from 10/19 to 9/19.
The FAX6 mask paths had no internal frame gap or center step above .06 on
their asserted flight suffixes. The new proposed cross-interval overlay
asserts nothing inside the sampled graph window, so there is no overlay jump
across the merge; the prep branch itself still needs its own trust authority.
Removing 745's stationary competing mask after inspection makes the same
graph reach its preparation branch; that ablation confirms why preserving
the competitor changes the decision, but is not an admissible inference rule.

## Gate and attribution

There is **no new session-disjoint DEVELOPMENT HUMAN authority in this
environment**. The available raw clips from earlier flight science were
already used in prior development, and their sessions were explicitly
excluded in FAX2's freshness protocol. The unused FAX6 raw-screen candidates
have only contact snapshots locally; their source videos, verified proxies,
and fresh HUMAN annotations are absent. Current process credentials do not
provide B2 read access. Selecting them now by outcome or treating their
screenshots as an authority would defeat the blind gate. A new raw-only
close-person queue and blind annotations are required before any claim of
wrong-person reduction or pilot safety. Maxime is needed for the HUMAN
identity/event annotations once the videos are acquired and the queue is
frozen; machine labels cannot substitute.

Preparation perception gaps (e.g. FAX6 850 f270) and upstream selected-flight
surfacing (FAX6 649) are separate failures. Event Logic and pose were not
run. General full-action overlays remain unsafe for a pilot; Event Logic
validation and pose/geometry remain paused. This V1 stays development-only.

Gate: `SUPERVISOR_REVIEW_AFTER_PREP_TO_SUBCORE_CONTINUITY`.
