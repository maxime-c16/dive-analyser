# HQ Representation 720p & Quarantine Forensics — V1 Report

Date: 2026-09-09 · Branch: `uiux-overhaul-pro-app` · Node: Mac arm64 (M2, mps)
Status: **COMPLETE — decision frozen, zero quarantines remain**

---

## 1. Executive summary

The HQ (iCloud high-resolution) thread closes with three outcomes:

1. **Quarantines lifted.** Dives 311 and 524 — quarantined as
   `TEMPORAL_MISMATCH` — are proven same-content with explicit deterministic
   transforms and are lifted (`label_transfer_allowed: true`). Dive 676's
   spatial map is now *verified* (the prior map was applied in the wrong
   direction). The manifest is `RECOVERED_ALL_DETERMINISTIC`: all 14 batch
   entries have explicit temporal (and, where needed, spatial) mappings.
2. **Representation decided.** Production detector inference stays at
   **proxy_360p** (frozen D5). 720p/HQ arms show real detection-quality
   regressions for the frozen detector (top-1 target switching on 1040/676,
   anchored missingness on 2169) that outweigh the 3–4x pixel-height gain.
   HQ is re-purposed as the archival master + future-retrain source.
3. **Original-master caveat stands (Phase A).** `ORIGINAL_MASTER_NOT_
   INDEPENDENTLY_PROVEN`: the Photos library is fully iCloud-optimized (no
   `resources/origs`), and exported "original" files are byte-identical to the
   edited renditions. The analysis basis remains the
   `edited_highres_rendition`, SHA-tracked.

Full evidence chain: `docs/science/HIGHRES_QUARANTINE_FORENSICS_V1.json`,
decision: `docs/science/HQ_REPRESENTATION_DECISION_V1.json`.

## 2. Scope and inputs

- Batch: 14 dives (DEV_EVAL roles; 1040/2169 HURDLE, 133/676 STANDING,
  10 TRAIN batch assets), HQ on media node
  `/Users/Shared/services/data/media-node/highres_analysis_source_v1/batch/`
  (355,637,796 bytes, SHA-tracked), 360p proxies from the backend cache.
- Canary set for the audit: 1040, 2169 (HURDLE), 676 (STANDING difficult),
  133 (STANDING control); 720p canaries regenerated from HQ
  (`runs/hq_rep_v1/720p_canaries/`).
- Detector: frozen `DIVER_DETECTOR_D5_A_V8N_best.pt` (recipe conf floor 0.001,
  OP conf 0.05, iou 0.45, imgsz 640, device mps). Human GT boxes at
  `docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN/`.
- GT takeoffs (proxy timeline): 1040 = 4.463857 s, 2169 = 6.46124 s,
  676 = 3.553575 s, 133 = 1.800274 s.

## 3. Phase A — original-master semantics (conclusion unchanged)

- `resources/origs` does not exist on the Photos host; every asset is
  iCloud-optimized. Original masters are not locally recoverable.
- All three canary `original_master` exports are byte-identical to the
  corresponding `edited_highres_rendition` (SHA-verified).
- osxphotos logs show "Skipping original version / Exporting edited version"
  for edited assets; Photos.sqlite edit states (ZADJUSTMENTSSTATE = 2) for
  311, 524, 676, 2169, 2353, 2625; = 0 for 133, 1040, 2387, 2541, 2555, 2661, 2680.
- Consequence: HQ semantics = "edited Photos rendition exported through the
  authorized PhotoKit path", exactly as frozen in
  `ANALYSIS_SOURCE_HQ_V1_FREEZE.json`.

## 4. Temporal alignment results

| Dive | Mapping | Evidence |
|---|---|---|
| 1040, 2169, 133 | PTS_EQUIVALENT (offset 0) | app-sim ≥ 0.997 |
| 676 | PTS_EQUIVALENT (offset ~0) | durations 7.405 vs 7.407 s |
| 311 | TRIM, `t_hq = t_proxy − 12.125` | 10/10 stride-1 samples NCC 0.977–0.995 (blur-equalized); HQ covers proxy [12.125, 19.2433] |
| 524 | PTS_EQUIVALENT (offset 0) | 716/717 pts, durations 11.933 vs 11.940 s |

720p canaries (libx264 crf18, `scale=720:-2` portrait / `scale=-2:720`
landscape) all validate PTS-equivalent to HQ at offset 0. Caveat: dive 1040's
720p has 332 frames vs HQ 339 (minor VFR drop) — do not assume CFR anywhere.

## 5. Quarantine forensics — dive 311 (lifted)

- **Proven:** HQ = deterministic trim of the proxy content, no spatial
  transform (scale 1.0, loc (0,1)–(0,2) at common width 480).
- Offset verified at stride 1 s (10 samples): scores 0.9774–0.9950, constant
  loc — artifact `runs/hq_rep_v1/offset_verify_311_stride1.json`.
- Annotated events (proxy timeline): takeoff 13.747 s → HQ 1.622 s;
  water_contact 14.815 s → HQ 2.690 s. Both inside the covered window.
- Manifest: `RECOVERED_DETERMINISTIC_MAPPING`, `DETERMINISTICALLY_MAPPABLE`,
  transfer allowed through the recorded transform.

## 6. Quarantine forensics — dive 524 (lifted)

- **Proven:** temporally PTS-equivalent; spatially HQ display = hflip of the
  proxy content at zoom 1.25 (crop). Identity (no-hflip) scan failed; hflip
  scan matched 16/16 frames (scores 0.701–0.778, loc (93,8) at 480-wide).
- Transform (480-wide portrait normalization): HQ point (u,v) → proxy point
  `(u/1.25 + 93, v/1.25 + 8)`.
- Annotated events (direct temporal transfer): takeoff 5.800 s, apex 6.317 s,
  water_contact 7.083 s (no bbox annotated for water_contact).
- Manifest: `RECOVERED_DETERMINISTIC_MAPPING`, `PTS_EQUIVALENT`, transfer
  allowed; HQ-arm box math for 524 remains unexercised (no audit run).

## 7. Quarantine forensics — dive 676 (spatial map verified)

The earlier map `{y_off: 0.002, y_span: 0.5917}` was **inverted**: it mapped
proxy coordinates into the top 59% of HQ, while the truth is the opposite —
**HQ display (1080x1136, coded 1136x1080 rot −90) is a uniform ×5.347 upscale
of the proxy's top band** (rows [0, ~213/360]), full horizontal FOV, no hflip:

- Blur-equalized NCC of HQ-downscaled (202x212) against the proxy frame:
  **0.9977 (t=3.5) / 0.9957 (t=3.375)** at loc (0,1); x-shift 0 confirmed by
  central-patch matching (`runs/hq_rep_v1/scale_match_676_v2_blur.json`).
- Prior patch-match failures were blur-asymmetry artifacts (HQ sharp vs proxy
  blurry), not evidence of different recordings.
- The "black bottom 40%" seen in earlier pair sheets was **sheet-renderer
  padding**, not video content (HQ row means 57–217 across all 1136 rows).
- Definitive validation: GT takeoff/apex/water_contact boxes mapped into HQ
  display frames land exactly on the diver
  (`runs/hq_rep_v1/sheets/676_gt_overlay_HQ.png`).
- Correct map (proxy-normalized → HQ-normalized):
  `{"x_off": 0, "x_span": 1, "y_off": -0.00471, "y_span": 1.69468}`.

## 8. Representation audit design (frozen D5, three arms)

`experiments/landmark_pilot/hq_representation_audit_v1.py` (+ authoritative
recompute `hq_audit_recompute_v2.py`): same frozen detector, same recipe, over
`proxy_360p` / `canary_720p` / `native_hq` arms with PTS-nearest frame
matching; top-50 candidates stored per frame; GT-anchored trajectories;
HURDLE-signal aggregation. Event identity compares the **top-1** box against
the human GT box (proxy arm in proxy coords, 720p/HQ arms through the verified
spatial map — the proxy-arm mapping bug in v1 is fixed).

## 9. Audit results per dive

| Dive | Metric | proxy_360p | canary_720p | native_hq |
|---|---|---|---|---|
| 1040 | takeoff/apex/wc top-1 IoU | 0.67 / 0.75 / 0.74 | 0.60 / 0.85 / 0.74 | 0.54 / 0.69 / 0.74 |
| 2169 | takeoff/wc top-1 IoU | 0.55 / 0.55 | 0.50 / 0.69 | 0.50 / 0.68 |
| 676 | takeoff/apex/wc top-1 IoU | 0.62 / 0.63 / 0.82 | 0.67 / **0.00** / 0.59 | **0.00 / 0.00** / 0.48 |
| 133 | takeoff/apex/wc top-1 IoU | 0.84 / 0.32 / 0.66 | 0.80 / – / 0.57 | 0.77 / – / 0.57 |

- 676 zeros at 720p/HQ are **ranking switches, not detection failures**: the
  diver is present in the candidate set with IoU 0.63–0.72 at takeoff and apex
  but a lower-confidence candidate (seated woman / umbrella region) takes top-1.
- Diver pixel height: 360p ≈ 56–69 px vs 720p ≈ 210–253 px vs HQ ≈ 142–228 px.
- ms/frame: 360p 16.3–21.0; 720p 25.9–27.7; HQ 24.5–47.0.

## 10. HURDLE-signal findings

- **1040:** top-1 target switching at 720p (anchored cy SNR 0.22 vs 2.81 at
  360p) — severe; the 360p arm is the only stable arm for this dive.
- **2169:** anchored missingness 0.24–0.27 in the takeoff window at 720p/HQ
  (vs 0.0 at 360p); anchored peak departure velocity ~2× higher at 720p
  (1.65 vs 0.83) — scale-dependent kinematics bias vs the GT timeline.
- **No HURDLE blocker is resolved by 720p/HQ with the frozen detector**;
  FM3 (360p target instability, 1040) remains open and is *worse* at 720p.

## 11. Cost / benefit and storage policy

- Storage: durable HQ batch = 355,637,796 bytes (media node, immutable,
  SHA-tracked). Proxies remain the working cache. 720p canaries are derived,
  regenerable, **not durable** (and not committed to Git).
- Compute: 360p is 1.4–1.8× faster per frame than 720p/HQ on the audit node.
- Benefit of higher resolution is real but **contingent on retraining**: pixel
  height 3–4× larger; 2169 water-contact IoU better at 720p/HQ (0.69/0.68 vs
  0.55). With the frozen 360p D5, net effect is negative.
- Storage policy: HQ = archival master (never fed to frozen D5); proxies =
  inference representation; 720p = tooling only.

## 12. Representation decision (frozen)

`PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P`
(`docs/science/HQ_REPRESENTATION_DECISION_V1.json`):

- detector inference: proxy_360p only (frozen D5);
- HQ files: archival master + label forensics + future retrain source;
- HQ label transfer: allowed for all 14 dives through explicit deterministic
  transforms (`PTS_EQUIVALENT` direct; `DETERMINISTICALLY_MAPPABLE` through the
  recorded mapping);
- retrain at ≥480p only via a new detector freeze + fresh audit; **not
  authorized** in this packet.
- `ANALYSIS_SOURCE_HQ_V1_FREEZE.json` amended accordingly
  (`resolution_decision`, `batch_summary`, amendment log).

## 13. Manifest changes and tests

- `HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json`: 311 and 524 lifted (status
  `RECOVERED_DETERMINISTIC_MAPPING`, transforms recorded), 676 spatial map
  verified and recorded; `recovery_history` entries preserve prior states;
  `summary.temporal_mismatch_quarantined = 0`; status
  `RECOVERED_ALL_DETERMINISTIC`; `derived_artifacts` documents the 720p
  canaries and audit outputs.
- Tooling fixes: 676 map direction corrected in
  `hq_representation_audit_v1.py` (`DIVES["676"]["map"]`), and the proxy-arm
  identity bug in `event_identity` fixed (proxy arm now compares in proxy
  coords).
- Tests: `experiments/landmark_pilot/test_hq_quarantine_forensics_v1.py` —
  **10/10 passing** (manifest invariants, history preservation, 676 map
  direction math, 311 window coverage, forensics↔manifest consistency,
  decision/freeze consistency, audit-script map parity). Existing suites
  untouched.

## 14. Limitations and next steps

- 524's hflip+crop transform is frame-match-verified but has **no HQ-arm
  detector audit**; treat HQ-arm box math for 524 as unexercised until needed.
- 2555 HQ was never pulled locally (not needed; manifest entry unchanged).
- 676's top-1 instability at 720p/HQ is a ranking issue — if higher-resolution
  inference is ever revisited, fix ranking (e.g. track-gated selection)
  **before** retraining.
- Event-logic GT remains proxy-timeline; HQ consumes labels only through the
  recorded transforms (see `docs/science/HQ_PROXY_TEMPORAL_SPATIAL_INTEROP_V1.md`).
- FM3 (1040 360p target instability) stays open; HQ does not repair it.
