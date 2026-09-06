# PROJECT_STATE.md - Dive Analyser / DiveSensei

## Perception Decomposition V1 — DEVELOPMENT COMPLETE (2026-09-06)

Report: `docs/science/TEMPORAL_LANDMARK_PERCEPTION_DECOMPOSITION_V1_REPORT.md`.
Starting canonical HEAD `b9d8952a9e9dbfa78595904f4d2dfdf4e3e6cb58`.
Root cause: **MULTI_STAGE_LIMITATION** (detection + acquisition + tracking all fail at 360p).
INTERNAL_EVAL evaluation blocked: 18 localization frames at
`media/perception_decomposition_v1/localization/INTERNAL_EVAL/` require human review.
User-facing analysis: **NOT AUTHORIZED**. Next gate: **SUPERVISOR_REVIEW_AFTER_PERCEPTION_DECOMPOSITION_V1**.

Scientific summary:
- 60-FPS annotation bug discovered, repaired: V2 PTS reference authority established.
- V2 A/B/C re-evaluation: all baselines seriously fail (>80% serious errors; A median 2.0s, C median 3.7s).
- Detector-only (F1/F2): IoU50 recall 3/36 and 1/36 respectively. Detection gap confirmed at 360p.
- Baseline C stage trace (3 DEVELOPMENT dives): wrong-person acquisition (133, 2555) and
  zero detection at landmark frames (2541). Structural bystander-wins confirmed.
- Oracle SAM canary (3 DEVELOPMENT dives): 1/3 successful (dive 133, 38/51 frames active);
  dives 2387 and 2169 collapse immediately at frame index 1.
- Original access: ACCESS_METHOD_BLOCKED (SSH/TCC denied). No paired original data.
- Custom fine-tuning: NOT JUSTIFIED. Automatic seeding: SKIPPED (oracle 1/3 success).
- Pose: POSE_STILL_PREMATURE. Next baseline not frozen.

Last verified: **2026-09-06**.
Latest audit: `docs/audits/FOUNDATION_HARDENING_AND_LAYER2_READINESS_2026-09-05.md`.
Layer-2 architecture: `docs/design/ANALYSIS_LAYER_2_ARCHITECTURE_V1.md`.
Pilot report: `docs/science/TEMPORAL_LANDMARK_REPORT_V1.md`.
Supervisor gate: `SUPERVISOR_REVIEW_AFTER_PERCEPTION_DECOMPOSITION_V1`.

## Canonical Repository

Canonical source is `mcauchy@192.168.1.57:~/dive-analyser` on host `deb-serv`, branch
`uiux-overhaul-pro-app`. History was rewritten on 2026-09-05 to remove historical live DB
credential material and tracked `.env`. Current HEAD: verify with `git rev-parse HEAD`.

The Mac local workspace `/Users/maximecauchy/.perso/diveanalyzer` is not a Git repository
and is not source authority.

## Backup Authority

A sanitized off-host bare mirror exists on the Mac at
`/Users/Shared/services/data/diveanalyzer-source-backups/dive-analyser-2026-09-05.git`.
It is source-only, outside the deployed Mac-agent tree, mode 0700, and must have HEAD equal
to the canonical repository after each final commit.

## Runtime Topology

Debian server `192.168.1.57` runs Docker Compose: PostgreSQL 16, FastAPI backend,
React/Vite frontend image, nginx, and Adminer. Mac `192.168.1.19` runs launchd
`com.diveanalyzer.agent` from `/Users/Shared/services/data/diveanalyzer/`.

nginx is the LAN entrypoint: `http://192.168.1.57:6090` and `https://192.168.1.57:6443`.
Direct service bindings are loopback-only: Postgres `127.0.0.1:5433`, backend `127.0.0.1:6002`,
frontend `127.0.0.1:6001`, Adminer `127.0.0.1:8080`.

## Runtime Configuration Authority

Server runtime secrets live in `/home/mcauchy/dive-analyser/.env` (ignored by Git).
Contains: rotated PostgreSQL credential, Mac machine API key, CORS origins,
`ANALYSIS_ARTIFACT_ROOT=/app/analysis-artifacts`.

Mac runtime config: `/Users/Shared/services/data/diveanalyzer/state/config.yaml` (0600).

## Source Authorities

- backend: Git `backend/`; runtime bind-mounted `/app`; PASS.
- frontend: Git `frontend/`; deployed image must be rebuilt for application source changes.
- infra: Git `docker-compose.yml`, `nginx/`; nginx config is bind-mounted; PASS.
- Mac agent: Git `mac-agent/` plus deployed Mac code; reconciled 2026-09-05 (byte-parity).
- Analysis schema: `backend/migrations/add_analysis_layer2.sql` applied to production DB.
- Experiment code: `experiments/landmark_pilot/` (NOT in backend container; standalone only).

## Security Status

- DB credential rotation: PASS (from 2026-09-05 hardening).
- Git sanitization: PASS; `git fsck --strict` passed.
- Machine API auth: PASS.
- TLS: PASS for Mac agent (local CA, explicit trust).
- Layer-2 security: proxy-only processing, no bulk recall, no production bulk-enqueue,
  no credentials in experiment code.

## Current Analysis Capabilities

### Layer 1 (Production)

User-authored metadata + deterministic/statistical/heuristic backend logic: caption parsing,
DD lookup/provenance, session aggregates, two-phase self ratings, Personal Dive Value V1,
Journey/fear/plateau heuristics, media readiness, representative-media workflows.

### Layer 2 (Experimental — Research Phase)

**Temporal landmark extraction** implemented and piloted:

- Schema: 9 new tables (`analysis_runs`, `analysis_jobs`, `analysis_landmarks`,
  `analysis_phases`, `analysis_metrics`, `analysis_artifacts`, `analysis_comparisons`,
  `analysis_comparison_artifacts`, `analysis_comparison_metrics`) applied to production DB.
- API: `/api/v1/analysis/` routes (all return `experimental: true`).
- Metric registry: 11 metrics in `backend/app/data/metric_registry.yaml`.
- Artifact storage: `media/analysis-artifacts/<dive_id>/<run_uuid>/` (bind-mounted in Docker).
- Baseline A pipeline: MOG2 + vertical centroid → takeoff/apex/water_contact landmarks.
- Pilot corpus: 20 dives run; 12/20 APPLICABLE (60%), 8/20 UNCERTAIN (40%).
- Pairwise comparison: 66 pairs computed and stored.
- Annotation tool: `experiments/landmark_pilot/annotate.py` (web UI, port 8765).

**Temporal Landmark Pilot V1 COMPLETE.**

**Baseline A:** 0% within-tolerance on all 3 landmarks (all 20 dives). Architectural failure.
See docs/science/BASELINE_A_EVALUATION_V1.json + BASELINE_A_ERROR_TAXONOMY_V1.json.

**Baseline B (DIBT):** 5.6%/15.4%/5.3% within-tol (takeoff/apex/water_contact, all-20).
INTERNAL_EVAL: 16.7%/33.3%/0%. NOT ADOPTED — does not meet ≥50% production bar.
See docs/science/BASELINE_B_EVALUATION_V1.json + BASELINE_B_FREEZE_V1.json.

**Full pilot report:** `docs/science/TEMPORAL_LANDMARK_REPORT_V1.md`.

## Production Data Authority

PostgreSQL Docker volume is the production metadata authority.
Server `media/videos` holds legacy originals/stubs; `media/cache` holds derived renditions.
Mac Photos and `/Users/Shared/services/data/media-node/` remain authority for new originals.
`media/analysis-artifacts/` holds Layer-2 analysis outputs (excluded from Git).

## Layer-2 DB State (2026-09-05)

```
analysis_runs          20  (pilot; pipeline=temporal_landmarks_baseline_a_v1)
analysis_jobs          20  (all succeeded)
analysis_landmarks     60  (3 per run: 36 APPLICABLE, 24 UNCERTAIN)
analysis_phases        36  (3 per APPLICABLE run: flight_ascent, flight_descent, flight)
analysis_metrics      120  (10 per APPLICABLE run)
analysis_artifacts     20  (diagnostic.json per run)
analysis_comparisons   66  (pairwise, method=temporal_landmark_pairwise_v1)
analysis_comparison_metrics 264  (4 per comparison)
```

## Tests And Validation

- Pre-Layer-2 backend security/sync/media tests: 21 passed.
- Layer-2 schema invariants: verified manually (temporal ordering, UNCERTAIN → conf=0,
  NOT_APPLICABLE → NULL timestamps, unique metric constraint).
- Layer-2 unit/integration tests (Phase T): not yet written. TODO.

## Remaining Engineering Debt

1. Layer-2 test suite not yet written.
2. Baseline C not yet implemented (Baseline A+B both fail production bar).
3. Proxy-vs-original canary deferred (originals are iCloud-only; Phase G scientifically low priority at current error magnitudes).
4. Migration-system consolidation remains deferred.
5. DB role privileges remain broad; rotation preserved current architecture.
6. Browser/system trust for the local CA is not installed.
7. Frontend image should be rebuilt on next user-facing frontend source change.
8. Layer-2 temporal landmark results not yet surfaced in the web UI.

## Current Gate

`SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_BASELINE_C_V1`

Previous completed gates:
- `SUPERVISOR_REVIEW_AFTER_HIGHRES_PERCEPTION_CANARY_V1` (2026-09-05)
- `SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_PILOT_V1_COMPLETE` (2026-09-05)

**What the supervisor should review:**
1. Baseline C R4 finding: generic COCO person detection insufficient for this footage
2. Next baseline direction: D2-POSE (pose estimation), D1-FT (fine-tune), or D3-OPT (strengthen B)
3. Proxy-vs-original canary: KEEP_DEFERRED until within striking distance of tolerances
4. Off-host backup: refresh Mac mirror after this commit
5. UI layer: decide when to surface temporal landmark results in the frontend


## Science layer — Baseline C (2026-09-06)

> **Gate before Baseline C**: `SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_PILOT_V1_COMPLETE`
> **Classification**: R4 — HUMAN_DETECTION_ITSELF_INSUFFICIENT
> **Report**: `docs/science/TEMPORAL_LANDMARK_BASELINE_C_V1_REPORT.md`
> **New gate**: `SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_BASELINE_C_V1`

### Baseline C identity

| Item | Value |
|---|---|
| Algorithm | YOLOv8n (COCO class 0) + ByteTrack + y_norm trajectory + C-TAKEOFF-V2 heuristic |
| Variant | C2 (temporal priors; C1 ≡ C2 on DESIGN so C2 chosen for safety) |
| Proposer fingerprint | `b4afd8ae85878308ad0abb445f4da7fe708cd4a9b5987a57b120419176f2bd41` |
| Weights SHA256 | `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36` (yolov8n.pt) |
| Freeze manifest | `docs/science/BASELINE_C_FREEZE_V1.json` |
| Ultralytics | 8.3.253, PyTorch 2.10.0+cu128, CPU-only (GTX 850M sm_50 incompatible) |

### DESIGN results (14 dives)

| Landmark | Within-tol | Serious | Median err | UNCERTAIN |
|---|---|---|---|---|
| takeoff | 0% | 9/9 (100%) | 224f | 5 of 14 |
| apex | 0% | 7/7 (100%) | 150f | — |
| water_contact | 0% | 9/9 (100%) | 277f | — |

### INTERNAL_EVAL results (6 dives, accessed once after freeze)

| Landmark | Within-tol | Serious | Median err | UNCERTAIN |
|---|---|---|---|---|
| takeoff | 0% | 2/2 (100%) | 569f | 4 of 6 |
| apex | 0% | 2/2 (100%) | 338.5f | — |
| water_contact | 0% | 1/2 | 372f | — |

### Scientific findings

- **Failure mode**: EARLY_TRIGGER (7/9 DESIGN takeoffs predicted at frame 0–11 vs true 108–1051)
- **Root cause**: Athletic dive poses in flight (~30–50px at 360p) outside COCO person distribution
- **Confidence**: Does not separate reliable from catastrophic predictions; useless as filter
- **Proxy/original**: KEEP_DEFERRED (errors are orders above any proxy artifact)
- **C vs A/B**: C is strictly worse than both A (median 94/89/85f) and B (157/63/70f DESIGN)
- **UNCERTAIN rate**: A=7%, B=21%, C=36% DESIGN; C=67% INTERNAL_EVAL

### Classification R4 implications

Generic COCO pretrained detection cannot be tuned to work on this footage. Next baseline
must use domain-specific detection or pose estimation.

### New files committed (Baseline C commit)

- `backend/tests/test_analysis_layer2.py` (119 tests, expanded from 37)
- `experiments/landmark_pilot/proposer_baseline_c.py`
- `experiments/landmark_pilot/run_baseline_c.py`
- `experiments/landmark_pilot/requirements_c.txt`
- `docs/science/BASELINE_C_FREEZE_V1.json`
- `docs/science/BASELINE_CC2_CANARY_RESULTS_V1.json`
- `docs/science/BASELINE_CC2_DESIGN_RESULTS_V1.json`
- `docs/science/BASELINE_CC2_EVAL_RESULTS_V1.json`
- `docs/science/TEMPORAL_LANDMARK_BASELINE_C_V1_REPORT.md`

---

## TEMPORAL_LANDMARK_PERCEPTION_V2 — Study Complete (2026-09-06)

**Gate**: SUPERVISOR_REVIEW_AFTER_TEMPORAL_LANDMARK_PERCEPTION_V2

**Result**: All 9 scientific questions answered. Phases A–W complete.

### Key Findings
- **Root cause**: SCALE_FAILURE (360p proxy) — primary limiting factor throughout
- **Failure topology**: SCALE_FAILURE → DOMAIN_GAP → ACQUISITION_FAILURE → TRACKING_COLLAPSE
- **Domain adaptation (Phase L)**: VIABLE — L1 mAP50=0.766 (9x improvement over frozen COCO)
- **SAM2 model size (Phase J)**: NOT a factor — both tiny and base_plus collapse at 360p (1/6 success rate)
- **INTERNAL_EVAL CC2 (Phase Q)**: 33.3% within-tolerance (2/6 evaluable), mean error 7.12 s
- **Architecture decision (Phase N)**: DETECTION_PLUS_LIGHTWEIGHT_TRACKING
- **All integrity tests (Phase U)**: PASS (3/3) — frozen predictions unaltered, human timestamps unchanged

### Artifacts
- TEMPORAL_LANDMARK_PERCEPTION_V2_REPORT.md — full study report
- PHASE_J_ORACLE_TRACKING_V1.json — oracle tracking results
- PHASE_L_DOMAIN_ADAPTATION_V1.json — domain adaptation results
- PHASE_M_DECISION_V1.json — method freeze
- PHASE_N_DECISION_V1.json — architecture decision
- PHASE_Q_INTERNAL_EVAL_CC2_V1.json — INTERNAL_EVAL evaluation
- PHASE_R_FINAL_CLASSIFICATION_V1.json — failure classification
- PHASE_U_TEST_RESULTS_V1.json — integrity tests

### Next Iteration
- Build CC3: fine-tuned L1 detector (all 38 DEVELOPMENT frames, no val hold-out) + ByteTrack
- Evaluate CC3 on INTERNAL_EVAL at 360p
- Long-term: original-resolution processing to overcome SCALE_FAILURE root cause
