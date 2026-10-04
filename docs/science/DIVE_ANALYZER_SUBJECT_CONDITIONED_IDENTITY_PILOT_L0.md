# DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0

Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0`
Protocol: `SUBJECT_CONDITIONED_IDENTITY_PILOT_L0_PROTOCOL.md` (frozen at 534d4b210d19e1f156e557719e13dce80b932d53, before any learned held-out result).

## Interface

```text
HUMAN-GT ORACLE SUBJECT REFERENCE + candidate person track
  -> learned identity matcher -> MATCH / NON_MATCH / AMBIGUOUS
```

GT-free reference acquisition stays explicitly OUTSIDE this pilot.

## Primary result (Layer A, LODO, matcher-eligible dives)

- B0 frozen appearance: **4/12**
- B1 appearance + V3 support: **2/12**
- L0 learned logistic: **1/12**
- LOSO-session L0: **1/12**

| dive | fam | reach | B0 top1 / rank | B1 top1 / rank | L0 top1 / rank |
|---|---|---|---|---|---|
| 1040 | HURDLE | MATCHER_ELIGIBLE | 1 / 1 | 0 / 139 | 0 / 3 |
| 1304 | STANDING | PARTIAL_PROPOSAL_REACHABILITY | 0 / None | 0 / None | 0 / None |
| 133 | STANDING | MATCHER_ELIGIBLE | 0 / 26 | 0 / 6 | 0 / 3 |
| 2169 | HURDLE | MATCHER_ELIGIBLE | 1 / 1 | 1 / 1 | 1 / 1 |
| 2204 | STANDING | MATCHER_ELIGIBLE | 0 / 27 | 0 / 21 | 0 / 34 |
| 2223 | STANDING | PARTIAL_PROPOSAL_REACHABILITY | 0 / None | 0 / None | 0 / None |
| 2341 | HURDLE | MATCHER_ELIGIBLE | 0 / 192 | 0 / 105 | 0 / 92 |
| 2353 | HURDLE | MATCHER_ELIGIBLE | 0 / 56 | 0 / 6 | 0 / 28 |
| 2387 | STANDING | MATCHER_ELIGIBLE | 0 / 233 | 0 / 52 | 0 / 27 |
| 2526 | HURDLE | PARTIAL_PROPOSAL_REACHABILITY | 0 / None | 0 / None | 0 / None |
| 2541 | HURDLE | MATCHER_ELIGIBLE | 1 / 1 | 0 / 113 | 0 / 3 |
| 2583 | STANDING | MATCHER_ELIGIBLE | 1 / 1 | 1 / 1 | 0 / 2 |
| 2839 | HURDLE | MATCHER_ELIGIBLE | 0 / 179 | 0 / 102 | 0 / 49 |
| 311 | STANDING | MATCHER_ELIGIBLE | 0 / 111 | 0 / 11 | 0 / 49 |
| 676 | STANDING | MATCHER_ELIGIBLE | 0 / 57 | 0 / 19 | 0 / 13 |

## Classification: `IDENTITY_MATCHER_L0_FAILS`

Next: `SCALE_IDENTITY_MATCHER_DATA_NEXT` — no grouped gain from 29 MATCH positives / 11-D matcher (small-data overfitting signature: rank smoothing without top-1 gain); B0 oracle-cosine 4/12 shows the interface carries signal worth more data; representation-vs-summary limits not isolated, so no richer-representation claim.

Interpretation: Subject-conditioned identity learning with an ORACLE within-clip reference does not beat frozen cosine on grouped held-out top-1 (L0 1/12 vs B0 4/12, B1 2/12). The oracle reference is non-production by construction; GT-free reference acquisition remains explicitly unresolved and is the dominant product bottleneck.

Oracle reference is non-production. Reference acquisition remains open.
