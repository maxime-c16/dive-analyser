# Analysis Layer 2 Foundation Proposal - 2026-09-05

Status: proposal for supervisor review. No Layer-2 migrations, models, CV/ML processing, or corpus reprocessing are authorized by this document.

## 1. Current Analysis Boundary

Dive Analyzer currently analyzes user-authored and relational data. The Mac agent parses Photos captions into dive metadata and the backend provides deterministic aggregation, DD lookup/provenance, phase-1/phase-2 self ratings, Journey heuristics, execution fault rules over manually supplied metrics, Personal Dive Value V1, media readiness, and representative media workflows. There is no pixel-derived phase detection, pose estimation, trajectory model, entry geometry, embedding store, or ML model in production.

The current media pipeline is a server-requested Mac-edge rendition system: `lease -> heartbeat -> process -> upload -> finalize`. It creates posters and proxy videos from Mac-held originals and stores verified outputs in local filesystem cache with relational metadata.

## 2. Requirements

Layer 2 must support richer, interpretable analysis without collapsing into one opaque quality score. It must represent phase-specific observations, temporal alignment, takeoff differences, height and trajectory estimates, body configuration, rotation, entry, consistency, athlete-vs-self comparison, athlete-vs-best-self comparison, repeated-pattern recognition, and personally meaningful feedback.

It must allow multiple analyses of the same dive using different media renditions, algorithms, parameters, models, or environments. Old results must remain identifiable and comparable.

## 3. Non-goals

This proposal does not consolidate migration systems, change the DB engine, add Redis/Kafka/Celery, split services, move to cloud, implement CV/ML, reprocess the corpus, add Analysis Layer 2 database migrations, freeze a scientific protocol, or change dive scoring formulas.

## 4. Proposed Domain Model

Recommended entities:

- `AnalysisRun`: one execution of one analysis specification against one dive/media input.
- `AnalysisInput`: immutable pointer to the exact media identity used by a run.
- `AnalysisArtifact`: stored output object such as keypoints, overlays, trajectories, diagnostics, or arrays.
- `AnalysisMetric`: scalar or compact structured metric with metric-definition metadata.
- `AnalysisPhase`: named time interval or event marker within a dive.
- `AnalysisInsight`: human-readable interpretation linked to metrics, phases, artifacts, and confidence.
- `AnalysisComparison`: first-class output comparing two dives or one dive to a selected/self baseline.

`Dive` remains the canonical attempt record. Layer 2 attaches to it through `dive_id` plus `video_uuid`/media identity, not by mutating core dive semantics.

## 5. Provenance And Versioning Contract

Each `AnalysisRun` should record: run UUID, dive id, canonical video UUID, source media kind, media cache entry or recalled source id, rendition, media key, checksum when available, pipeline version, processor versions, model/algorithm versions, parameters hash and full JSON parameters, code commit if available, execution host, Python/package/runtime summary, started/completed timestamps, status, and failure details.

Idempotence key: hash of `(dive_id, canonical video UUID, input media key/checksum, pipeline key/version, processor set, model versions, parameters canonical JSON)`. Re-running the same spec should return/reuse the existing terminal run unless explicitly forced.

## 6. Artifact Taxonomy

Use PostgreSQL for run metadata, scalar metrics, compact phase/event records, status, lineage, and small JSON summaries. Use local filesystem object-like storage for large arrays, per-frame data, overlays, thumbnails, masks, embeddings, and diagnostics. Store artifact metadata in PostgreSQL with content type, storage path, byte size, checksum, schema version, and retention class.

Suggested artifact classes: `scalar_metric`, `phase_timeline`, `trajectory_series`, `keypoints_2d`, `keypoints_3d`, `mask_sequence`, `embedding`, `frame_table`, `thumbnail`, `overlay_video`, `diagnostic_json`, and `alignment_map`.

## 7. Job And Execution Architecture

Recommendation: introduce `analysis_jobs`, analogous to `media_jobs`, rather than extending `media_jobs` or creating a generic job framework now. Evidence: existing media jobs are tightly about renditions, media keys, upload/finalize, and Mac materialization; analysis jobs need processor specs, artifact classes, partial success, and comparison/baseline inputs. A generic abstraction would add risk before the second job family proves common requirements.

Reuse the proven lifecycle concepts: lease, heartbeat, process, upload artifacts, finalize, fail. Keep the first implementation single-worker and bounded. Do not refactor the existing media framework in the Layer 2 first slice.

## 8. Storage Architecture

- Relational metadata: PostgreSQL tables for runs, jobs, inputs, metrics, phases, comparisons, artifacts.
- Scalar metrics: typed relational rows with numeric/text/boolean/json value slots.
- Moderate JSON: JSONB for diagnostics, processor summaries, parameters, quality flags.
- Large arrays: compressed `.npz` or Parquet under a local `analysis-artifacts/` root, referenced from DB.
- Video-derived artifacts: existing media cache pattern, with a separate analysis artifact namespace.
- Embeddings: start as local files plus metadata; defer vector indexing until a real retrieval workflow exists.
- Per-frame data: file-backed, chunked, checksumed; never millions of rows in PostgreSQL by default.

## 9. Metric-definition Contract

Define metrics through a shared registry before new computed metrics ship. Each metric should include: key, label, description, unit, value type, directionality, applicable phase, algorithm key/version, source media requirement, valid range, confidence model, quality flags, display format, and interpretation notes. Backend formulas, heuristics, CV processors, and frontend displays must reference the same metric key and version.

Do not migrate all existing statistics immediately. Start with Layer-2 metrics only, then bridge selected V1 statistics once the registry shape proves stable.

## 10. Comparison Contract

Comparisons are outputs, not ad hoc UI calculations. Store comparison subject(s), baseline selection rule, selected baseline dive ids/run ids, alignment method/version, metric deltas, phase deltas, confidence, and artifact links. Required comparison modes: Dive A vs Dive B, current dive vs recent self baseline, current dive vs selected best/reference dive.

The system needs stable identifiers for dives, analysis runs, artifacts, metrics, baselines, and time-alignment maps. A baseline should be materialized as the selected set and selection query/version so later data changes do not silently rewrite old comparisons.

## 11. Compute Placement Matrix

| Mode | Use | Advantages | Costs/Risks |
|---|---|---|---|
| Server plus existing proxy | temporal checks, UI overlays, lightweight frame sampling | fast iteration, no Mac dependency after proxy exists | proxy quality may limit science |
| Server plus recalled original | height/trajectory/entry requiring quality | keeps backend orchestration centralized | Mac recall latency, source retention |
| Mac edge computation | original-only processing, Photos-local source access | avoids moving originals, best source fidelity | Mac CPU limits, launchd/runtime complexity |
| Future compute node | heavy pose/ML batches | isolates expensive processing | not needed now; adds infrastructure |

## 12. Proxy-vs-original Matrix

| Analysis family | Initial media need |
|---|---|
| Temporal segmentation | proxy sufficient for first experiments |
| Pairwise visual alignment | proxy sufficient initially; original recommended for final high-quality overlays |
| Pose/keypoints | original recommended; proxy may be acceptable for feasibility only |
| Takeoff/vertical trajectory/height | original recommended, possibly mandatory depending framing/calibration |
| Entry detection/geometry | original recommended; original mandatory if splash/entry frames are blurred in proxy |
| Embeddings/repeated-pattern search | proxy sufficient for prototype; original optional later |

## 13. Failure And Idempotence Model

An analysis run may be `planned`, `leased`, `running`, `partial`, `succeeded`, `failed`, `cancelled`, or `superseded`. Individual processors can fail while unrelated metrics/artifacts succeed. The run status should be `partial` when useful outputs exist with explicit failure records.

Every output must carry producer, input, metric/artifact schema version, and confidence/quality metadata. Re-running the same idempotence key should be detectable and should not create duplicate terminal results unless the caller requests a forced run with a new run id.

## 14. Resource Constraints

Start with one active analysis job at a time. Use disk-backed intermediates, bounded frame batches, explicit temp directories, checksums, cleanup policies, and max artifact sizes. Do not create huge frame directories by default. Do not process the whole corpus in this phase. Make every processor resumable or safely restartable before batch use.

## 15. First Scientific Slice Comparison

| Option | Usefulness | Burden | Media | Notes |
|---|---|---|---|---|
| 1. Temporal dive/phase segmentation | high | low-medium | proxy sufficient | unlocks phase-aware UI and later alignment |
| 2. Pose/keypoint extraction | high | high | original recommended | powerful but dependency/model/evaluation heavy |
| 3. Takeoff/vertical trajectory/height | high | medium-high | original recommended | interpretable but calibration-sensitive |
| 4. Pairwise temporal alignment and visual comparison | high | medium | proxy sufficient initially | directly supports athlete-vs-self feedback |
| 5. Entry detection/geometry | medium-high | medium-high | original recommended/mandatory | useful but splash/water/reflection sensitive |

Recommended order: temporal segmentation, pairwise temporal alignment, takeoff/trajectory feasibility, entry detection, pose/keypoint extraction. This is an implementation order, not a permanent scientific choice.

## 16. Recommended Implementation Sequence

1. Add schema proposal/migration for `analysis_runs`, `analysis_inputs`, `analysis_artifacts`, `analysis_metrics`, `analysis_phases`, `analysis_comparisons`, and `analysis_jobs` after supervisor approval.
2. Implement a no-CV temporal segmentation processor over proxy media with manual-review diagnostics.
3. Add pairwise alignment between two selected dives using phase markers.
4. Add artifact storage root and lifecycle cleanup.
5. Add first metric registry entries for Layer-2 metrics only.
6. Run bounded single-dive experiments, then a small development set. No held-out/evaluation split is created yet.

## 17. Alternatives Rejected Or Deferred

- Extending `media_jobs`: rejected because analysis has different specs, outputs, and partial-failure semantics.
- Generic job framework now: deferred until two job families prove shared abstractions.
- PostgreSQL for per-frame arrays: rejected for simplicity and DB health.
- Opaque single quality score: rejected by product contract.
- Immediate pose model integration: deferred until temporal/alignment foundations and evaluation discipline exist.
- Remote/cloud compute: deferred for local personal system simplicity.

## 18. Supervisor Decisions Still Required

1. Approve the Layer-2 entity names and migration boundary.
2. Choose the first scientific slice order or revise it.
3. Decide whether initial analysis runs may use proxy media only.
4. Approve artifact root location and retention policy.
5. Decide how much UI should expose intermediate diagnostics.
6. Approve whether Mac edge compute is allowed for original-only processors.
7. Decide when to create development/evaluation dataset separation.
8. Decide whether any old deterministic metrics should be bridged into the new metric registry in the first implementation.
