# Dive Analyzer — Flight Perception Successor V1

Packet: `DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1` · Gate: `SUPERVISOR_REVIEW_AFTER_FLIGHT_PERCEPTION_SUCCESSOR`
Metrics: `DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1.json` · Split: `FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1.json`
(`525ee82`, frozen before any label/model) · Protocol: `FLIGHT_PERCEPTION_SUCCESSOR_V1_PROTOCOL.md`
(sha256 `df8cca10…`, `c1e002e`, committed before the holdout was loaded; holdout loaded once).

## 1. Conclusions

1. **Yes — the detector was the limiting substrate for the dives it can see.** A flight-focused
   successor (YOLOv8n, COCO init, 571 training images of which 435 are human flight-phase boxes)
   surfaces the HUMAN subject flight in the top-5 on **5/9 fresh holdout dives vs 1/9 for frozen D5**
   (4 at rank 1), with the trajectory algorithm byte-unchanged. On holdout dives with verified HQ:
   **5/6 vs 0/6**. Pre-registered "material improvement" rule met (+4 ≥ +2, presence not lower).
2. **Mechanism = confidence separation, as hypothesised.** Mid-flight, the subject becomes the top
   box on 91 % of HQ anchors (D5 28 %); median margin over the nearest other person −0.16 → +0.76;
   presence at conf ≥ 0.10 0.48 → 0.82 (HQ), 0.32 → 0.56 (360); subject-box IoU vs HUMAN 0.49 → 0.74;
   fewer continuity breaks (INTERP runs 4.9 → 2.2 at 360).
3. **New failure mode: loss of the low-confidence tail on out-of-domain footage.** Raw presence at any
   confidence drops 0.93 → 0.67 (360). All 4 successor failures are observation losses on footage
   without verified HQ or with a distant subject: 538/540 (phone filming a replay screen, S0 0.33/0.11),
   66 (S0 0.78 but graph-unreachable), 2498 (distant 3 m subject, S0 0.11 at 360 / 0.56 at HQ).
   D5 saw these subjects faintly but surfaced only one of them (540, rank 4).
4. **HQ now matters.** With the successor, HQ is where it wins (5/6); with D5, HQ surfaced 0/6.
   No resolution-specific threshold was used.
5. **Manual multi-track selection: narrowly not viable** under the pre-registered bar (top-5 56 % < 60 %,
   top-10 56 % < 70 %). On "normal" footage (HQ available, subject not tiny) it is effectively solved on
   this holdout; the gap is domain coverage.
6. **Successor promoted for further Dive Analyzer science (experimental), not as a replacement of
   frozen D5.** Frozen D5 stays the reference and is untouched.

## 2. Fresh evaluation authority

- Eligibility from the canonical DB (read-only): 2 832 dives / 172 sessions; eligible = sessions never
  used by any science artifact, production proxy_360p ready (SHA-verified). No FINAL_HOLDOUT existed.
  Unused proxies: 66/540/551/2498/2838 eligible → holdout; **2584 ineligible** (session 158 = validation 2583).
- Roles (session-grouped, disjoint): FRESH holdout 13 dives / 10 sessions → after the annotator excluded 4
  as unlabelable (551, 1190, 1194, 2838: diver not reliably visible) **9 dives / 8 sessions / 4 athletes**
  (23, 66, 538, 540, 980, 1555, 2257, 2288, 2498); new-train 16 dives / 6 sessions; validation =
  FLIGHT_GT_HUMAN_V1 on the 6 Level-B dives (never D-series training).

## 3. New human GT (blind; no detector output ever shown; annotator not told the set)

| authority | dives | boxes | digest |
|---|---|---|---|
| `FLIGHT_GT_HUMAN_V2_HOLDOUT` (sealed) | 9 | 81 (+5 repeats) at k/8 of human flight window | `f9712942…` |
| `FLIGHT_TRAIN_HUMAN_V1` | 16 | 176 at k/10 | `05574219…` |

Events (takeoff / water contact) marked by Maxime in the tool. Repeatability 0.004–0.028 normalized
centre distance (≪ 0.06). 203/262 boxes drawn on HQ frames resampled to proxy geometry; stored in proxy
pixels on the proxy PTS timeline.

## 4. Training corpus and successor design

- Audit: frozen D5 = D4 fine-tune on **69 images** (1 subject box each, no negatives, landmark/failure-mined,
  includes protected 524/2555 — historical caveat, not rewritten).
- DS1 (`c1daa813…`): historical D4/D5 labels minus 524/2555 (104 images), FLIGHT_GT_HUMAN_V1 boxes on the
  9 event dives (126, incl. 8 background), FLIGHT_TRAIN_HUMAN_V1 (341); each label as native 360p frame and,
  where the HQ map is verified, as HQ frame (360×640). Single class = the subject; bystanders are background.
  No interpolated / detector-snapped / pseudo labels.
- Recipe (one family): YOLOv8n, imgsz 640, 60 fixed epochs, batch 16, MPS, amp False, last.pt, mosaic 0.5,
  degrees 10, scale 0.5. Candidates: S0 (D5 init, existing labels), S1 (D5 init, DS1), S2 (COCO init, DS1).
- Validation-only selection (protocol §4 lexicographic score): D5 (2,2,10,0.47), S0 (5,6,8,0.57),
  S1 (5,4,6,0.53), **S2 (7,7,8,0.63)** → frozen successor `S2_COCOinit_DS1`, checkpoint sha256
  `d3ba0b035e7a8eb20bb5af66db62984bfb4682075b0c1267677d293e0e9d9c7f`. COCO init beats D5 init.

## 5. Frozen D5 vs successor on the fresh holdout (primary = 360+HQ where HQ verified, else 360)

| metric | D5 | S2 |
|---|---|---|
| surfaced top-1 / top-5 / top-10 (9) | 0 / 1 / 1 | 4 / 5 / 5 |
| 360 only: top-5 · S0≥0.75 · S2 graph · S3 pool | 1 · 8 · 8 · 3 | 4 · 5 · 4 · 4 |
| HQ (6): top-5 · S2 graph · S3 pool | 0 · 6 · 1 | 5 · 5 · 5 |
| presence any conf / ≥0.10 (360) | 0.93 / 0.32 | 0.67 / 0.56 |
| presence any conf / ≥0.10 (HQ) | 0.98 / 0.48 | 0.93 / 0.82 |
| subject top-1 box (360 / HQ) | 0.26 / 0.28 | 0.58 / 0.91 |
| median margin vs other person (360 / HQ) | −0.12 / −0.16 | +0.38 / +0.76 |

Per dive (first recovered rank, D5 → S2): 23 – → 5; 980 – → 1; 1555 – → 1; 2257 – → 1 (HQ only);
2288 – → 1; 540 4 → –; 538, 66, 2498 – → –.

## 6. Method integrity

- Downstream = frozen FSR search/rank/surfacing via an adapter that only swaps the candidate source;
  parity with the sealed FSR funnel: 0 differences on 15 dives. New cache script byte-identical to frozen
  D5 caches (360) and to frozen HQ caches on 8/9 dives (133: 1/178 frames, nearest-PTS tie).
- HQ: 35 edited renditions read from PROD B2 (read-only playback key inside the backend container,
  authorised by Maxime after the Photos LaunchAgent export hung), SHA-verified vs `media_blobs`; frozen
  NCC gate verified 29; unavailable 538/540/551/66 (aspect/letterbox), 2636/2838 (content mismatch).
- Protected data untouched (Paris, INTERNAL_EVAL, 524, 2555; 2584 excluded). No identity/ReID, Event Logic,
  pose, Media Backbone change; no B2/DB writes. Frozen D5 SHA re-asserted after every training.
- Caveats: holdout is 9 dives (4 athletes but MAXIME-dominated); holdout now burned for iteration;
  FLIGHT_GT_HUMAN_V1 validation is 6 dives (selection noisy); session 163 labels share one camera view.

## 7. Remaining blocker and next step

Observation of the subject on **out-of-domain footage** (phone recordings of screens, letterboxed
renditions, distant/small subjects) — the successor trades D5's faint low-confidence tail for strong
separation. Bounded next options (validation-first, new holdout needed for any claim): (a) union of
frozen-D5 and successor candidates as one search input (keeps D5's tail, successor confidence);
(b) targeted flight labels on screen-recorded and far-camera footage; (c) letterbox-aware HQ maps for
the screen-recorded assets. Identity/ReID remains out of scope.

## 8. Artifacts (outside Git, provenance in JSON)

`runs/flight_perception_successor_v1/`: `caches/CAND_{D5,S0_pilot_DS0,S1_D5init_DS1,S2_COCOinit_DS1}_{360,hq}.json`,
`datasets/DS{0,1}_*` (MANIFEST digests), `models/<variant>/weights/last.pt`, `MODEL_REGISTRY_V1.json`,
`HQ_REGISTRY_V1.json`, `HQ_ALIGNMENT_VERIFY_V1.json`, `downstream/*.json`; `media/fps_v1/` (proxies, B2 HQ).
Code: `experiments/flight_perception/fps_*.py`; tests `test_flight_perception_successor_v1.py` (9 passed).
