# Temporal Landmark Pilot Protocol V1

**Status:** FROZEN — development pilot only  
**Authority:** `docs/science/TEMPORAL_LANDMARK_PILOT_PROTOCOL_V1.md`  
**Created:** 2026-09-05  
**Pilot label:** `TEMPORAL_LANDMARK_DEVELOPMENT_PILOT_V1`

---

## 1. Scientific Question

> Can automatic video analysis reliably propose the temporal positions of
> **takeoff**, **apex**, and **water contact** in springboard and platform
> dives from personal training footage, using proxy-quality video?

Reliable means: proposal errors small enough for human correction to be
practical, and systematic failure modes identifiable from review artifacts.

This is a feasibility and discovery question.  No performance claim is made
without human ground-truth labels.

---

## 2. Target Landmarks

### 2.1 Required Candidates

| Landmark Key | Definition | Frame Definition |
|---|---|---|
| `takeoff` | The last frame in which both feet are in contact with the board/platform | Last frame where foot contact is visible before full airborne phase |
| `apex` | The frame at or nearest to maximum elevation of the diver's center of mass | Frame of lowest apparent downward velocity / highest center-of-mass position |
| `water_contact` | The first frame in which any part of the diver's body contacts the water surface | First frame showing splash or limb below water level |

### 2.2 Applicability Rules

| Landmark | springboard | platform | Standing (SD) | Double bounce (DB) |
|---|---|---|---|---|
| `takeoff` | APPLICABLE | APPLICABLE | APPLICABLE | APPLICABLE (final takeoff) |
| `apex` | APPLICABLE | APPLICABLE | APPLICABLE | APPLICABLE |
| `water_contact` | APPLICABLE | APPLICABLE | APPLICABLE | APPLICABLE |

> All three core landmarks apply to all primary dive types in this pilot.  
> Context-specific landmarks (hurdle, board depression) are NOT part of V1.

If a clip is too short, damaged, or the diver is not visible at the expected
point, the landmark must be marked `NOT_APPLICABLE` or `UNCERTAIN`, never
with a guessed timestamp.

---

## 3. Phase Semantics

Phases derived from the three core landmarks:

| Phase Key | Start | End | Description |
|---|---|---|---|
| `flight_ascent` | `takeoff` | `apex` | Rising phase: board leave to peak height |
| `flight_descent` | `apex` | `water_contact` | Falling phase: peak to entry |
| `flight` | `takeoff` | `water_contact` | Full flight (composite) |

Additional phases are NOT defined in V1.  Pre-takeoff and post-entry analysis
are deferred.

---

## 4. Tolerance and Evaluation Metrics

The following tolerances are used for human review.  They do NOT constitute
validated accuracy targets until ground truth is collected.

| Metric | Target for Useful Proposal | Threshold for Serious Failure |
|---|---|---|
| Takeoff frame error | ≤ 5 frames | > 15 frames |
| Apex frame error | ≤ 8 frames | > 20 frames |
| Water-contact frame error | ≤ 5 frames | > 15 frames |
| Ordering valid (takeoff < apex < water_contact) | 100% | any violation |

At 30 fps, 5 frames ≈ 167 ms.  At 60 fps, 5 frames ≈ 83 ms.

---

## 5. Proxy vs Original Policy

**Default:** use proxy_360p (existing server-side cache).

**Justification:** proxy quality is sufficient for motion-energy and vertical
centroid methods at this scale.  Original recall adds latency without proven
scientific gain for V1 temporal segmentation.

**Canary:** a bounded subset of ≤ 6 dives will be processed with both proxy
and original to measure any systematic landmark timing difference.

**Decision rule:** if proxy-vs-original timing difference exceeds 3 frames
median across the canary set, original recall will be authorized for the
full pilot.  If not, proxy suffices for V1.

---

## 6. Development Pilot Selection

### 6.1 Split Label

All pilot dives are labeled: `TEMPORAL_LANDMARK_DEVELOPMENT_PILOT_V1`

No holdout, validation, or test split is defined for V1.  No generalization
claim may be made from development pilot results.

### 6.2 Selection Criteria

- All dives must have a ready `proxy_360p` cache entry.
- Target approximately 18–24 dives, maximum 24.
- Selection must represent variation across:
  - Dive group (1/2/3/4/5)
  - Execution position (A/B/C/D)
  - Height (1m/3m/5m platform)
  - Modifier presence (SD, DB, drill)
  - Session spread (at least 3 different sessions)

### 6.3 Exclusion Rules

- Dives where the diver is not the primary subject.
- Clips shorter than 2 seconds.
- SYNC dives (two divers; landmark ambiguity).
- Clips where proxy file is zero bytes or corrupt.

---

## 7. Annotation Procedure

1. Run automatic landmark proposer on all pilot dives.
2. Review each proposed landmark set in the annotation tool.
3. For each landmark, either:
   - **Accept** (no correction needed) — source stays `AUTO`
   - **Correct** (wrong by > tolerance) — source becomes `HUMAN_CORRECTED`
   - **Set** (no proposal existed) — source becomes `HUMAN`
   - **Mark NOT_APPLICABLE** — if landmark truly does not apply
   - **Mark UNCERTAIN** — if frame boundary is genuinely ambiguous
4. Record annotator: `maxime` (primary athlete / maintainer).
5. Save annotation with media checksum and annotation schema version `v1`.

Ground-truth annotations are written to:
`docs/science/pilot_annotations/` (YAML, Git-versioned, no media).

---

## 8. Baseline Methods

### Baseline A: Motion Energy + Vertical Centroid

- **Input:** proxy_360p video frames (every N-th frame for efficiency)
- **Approach:**
  1. Compute per-frame foreground mask via background subtraction or inter-frame
     difference.
  2. Extract vertical centroid of largest moving region each frame.
  3. Fit a quadratic or smoothed trajectory to the centroid time series.
  4. **Takeoff:** frame where centroid starts moving rapidly upward (or away
     from board region).
  5. **Apex:** frame of maximum centroid Y-position (highest in image → lowest
     pixel coordinate in most camera setups).
  6. **Water contact:** frame with sudden large foreground area change at
     bottom of frame (splash signal).
- **Dependencies:** OpenCV (cv2), NumPy, SciPy
- **Advantages:** fully deterministic, no trained model, interpretable
- **Expected failures:** platform dives with limited motion pre-takeoff;
  cluttered backgrounds; camera panning

### Baseline B: Person Detection Trajectory (if Baseline A insufficient)

- **Input:** proxy_360p video frames
- **Approach:**
  1. Run a lightweight pretrained person detector (e.g. YOLOv8n) on key frames.
  2. Track the bounding-box centroid over time.
  3. Derive landmarks from the trajectory the same way as Baseline A.
- **Dependencies:** ultralytics YOLOv8 (isolated environment), PyTorch
- **Advantages:** more robust to background clutter; handles occlusion better
- **Expected failures:** training data mismatch for underwater/poolside view;
  false detections; slower (GPU beneficial)
- **Authorization:** implement only if Baseline A produces > 30% frame errors
  on the pilot set.

---

## 9. Artifact and Provenance Rules

Every analysis run must record:
- `pipeline_key` and `pipeline_version`
- `media_key` and `media_role` (which exact file was used)
- `input_checksum_sha256` where computable
- `implementation_version` (git commit or script hash)
- `environment_meta` (Python version, OpenCV version, host)

All automatic outputs are labeled `source = AUTO` and `EXPERIMENTAL = true`.
They must not be displayed as validated results in the production UI.

Review visualizations (frame strips, timeline SVGs) are labeled `is_debug = true`
in the artifact table.

---

## 10. Success and Failure Interpretation

### Infrastructure Success

The pipeline infrastructure is a success when:
- An analysis run can be enqueued, leased, executed, and finalized without error.
- Landmarks, phases, and metrics are persisted in the DB.
- Artifacts are written to the filesystem and registered.
- Idempotence works: re-running the same spec returns the existing run.
- The annotation tool can load and save landmark corrections.

This does NOT require the landmark proposals to be scientifically accurate.

### Scientific Validity

Scientific validity can only be assessed AFTER human annotation.  Before that:
- Automatic proposals are "candidate suggestions".
- No accuracy metric (frame error, precision, recall) is valid.
- The only evaluable measure is: "are proposals close enough to be correctable
  in reasonable annotation time?"

### No-Score Rule

This protocol does NOT produce a quality score, diving performance score,
judging simulation, or AQA metric.  The sole output is temporal landmark
proposals for human review.

---

## 11. Data Safety

- No production dive metadata is mutated.
- No media originals are recalled unless the canary test authorizes it.
- No more than 24 dives processed in the pilot.
- No results are published to the production user-facing UI.
- Pilot annotation files contain no sensitive personal data (timestamps only).

---

## 12. Open Questions (Pending Human Annotation)

1. What is the typical frame error of Baseline A for each landmark?
2. Does proxy quality cause systematic timing errors vs original?
3. Which dive types (platform vs springboard, position, modifier) are hardest?
4. Is Baseline B necessary or is Baseline A sufficient?
5. What annotation time per dive is required?

These questions can only be answered with ground-truth labels.

---

*Protocol frozen: 2026-09-05. Do not modify without creating a new versioned protocol.*
