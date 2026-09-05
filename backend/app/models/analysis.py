"""Layer 2 Analysis domain models.

Tables:
  analysis_runs              — immutable scientific execution identity
  analysis_jobs              — execution orchestration (lease/heartbeat/retry)
  analysis_landmarks         — temporal point events (takeoff, apex, water_contact…)
  analysis_phases            — named intervals between boundaries
  analysis_metrics           — scalar / compact structured quantitative results
  analysis_artifacts         — file-like outputs (stored on filesystem, metadata in DB)
  analysis_comparisons       — first-class pairwise comparison results
  analysis_comparison_artifacts
  analysis_comparison_metrics
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


# ---------------------------------------------------------------------------
# AnalysisRun
# ---------------------------------------------------------------------------

class AnalysisRun(Base):
    """One exact analysis specification applied to one exact media input for one dive.

    The spec_fingerprint is the idempotence key:
        hash(dive_id + media identity + pipeline_key + pipeline_version + canonical_parameters)
    Two byte-equivalent analysis requests share the same fingerprint and must not
    produce duplicate active runs (enforced by a partial unique index).
    """

    __tablename__ = "analysis_runs"

    id                      = Column(Integer, primary_key=True, index=True)
    run_uuid                = Column(UUID(as_uuid=True), nullable=False, unique=True,
                                     server_default="gen_random_uuid()")

    # Scientific subject
    dive_id                 = Column(Integer, ForeignKey("dives.id", ondelete="RESTRICT"),
                                     nullable=False, index=True)
    photos_asset_id         = Column(Integer, ForeignKey("photos_assets.id", ondelete="RESTRICT"),
                                     nullable=True, index=True)

    # Exact media identity consumed
    media_key               = Column(String(64), nullable=True)   # ref to media_cache_entries.media_key
    media_role              = Column(String(30), nullable=True)   # 'proxy_360p', 'proxy_720p', 'original'
    input_checksum_sha256   = Column(String(64), nullable=True)

    # Pipeline specification
    pipeline_key            = Column(String(100), nullable=False)
    pipeline_version        = Column(String(40),  nullable=False)
    canonical_parameters    = Column(JSON, nullable=False, default=dict)

    # Idempotence key
    spec_fingerprint        = Column(String(64), nullable=False, index=True)

    # Execution status
    status                  = Column(String(30), nullable=False, default="pending", index=True)
    # pending | running | succeeded | failed | cancelled | superseded

    forced                  = Column(Boolean, nullable=False, default=False)

    # Timestamps
    created_at              = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    started_at              = Column(DateTime, nullable=True)
    completed_at            = Column(DateTime, nullable=True)

    # Provenance
    implementation_version  = Column(String(100), nullable=True)
    environment_meta        = Column(JSON, nullable=True)
    error_summary           = Column(Text, nullable=True)

    # Relationships
    jobs        = relationship("AnalysisJob",      back_populates="run", cascade="all, delete-orphan")
    landmarks   = relationship("AnalysisLandmark", back_populates="run", cascade="all, delete-orphan")
    phases      = relationship("AnalysisPhase",    back_populates="run", cascade="all, delete-orphan")
    metrics     = relationship("AnalysisMetric",   back_populates="run", cascade="all, delete-orphan")
    artifacts   = relationship("AnalysisArtifact", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_analysis_runs_pipeline", "pipeline_key", "pipeline_version"),
        # Partial unique index (idempotence) is in the migration SQL; SQLAlchemy does
        # not express WHERE clauses on unique indexes natively — the DB enforces it.
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisRun(id={self.id}, run_uuid={self.run_uuid}, "
            f"dive_id={self.dive_id}, pipeline={self.pipeline_key}@{self.pipeline_version}, "
            f"status={self.status})>"
        )


# ---------------------------------------------------------------------------
# AnalysisJob
# ---------------------------------------------------------------------------

class AnalysisJob(Base):
    """Execution orchestration for one analysis run attempt.

    Mirrors the proven media_jobs lease/heartbeat/retry lifecycle but is kept
    entirely separate — analysis jobs have different processor specs, partial
    failure semantics, and artifact classes.

    A retry creates a new AnalysisJob row; the AnalysisRun is preserved.
    """

    __tablename__ = "analysis_jobs"

    id                  = Column(Integer, primary_key=True, index=True)
    run_id              = Column(Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"),
                                 nullable=False, index=True)

    status              = Column(String(40), nullable=False, default="pending", index=True)
    # pending | leased | running | succeeded | failed | abandoned

    attempt             = Column(Integer, nullable=False, default=1)
    max_attempts        = Column(Integer, nullable=False, default=3)

    # Lease fields
    claimed_by          = Column(String(100), nullable=True)
    claimed_at          = Column(DateTime, nullable=True)
    claimed_until       = Column(DateTime, nullable=True, index=True)
    last_heartbeat_at   = Column(DateTime, nullable=True)

    last_error          = Column(Text, nullable=True)

    created_at          = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at          = Column(DateTime, nullable=False, default=datetime.utcnow,
                                 onupdate=datetime.utcnow)

    run = relationship("AnalysisRun", back_populates="jobs")

    def __repr__(self) -> str:
        return (
            f"<AnalysisJob(id={self.id}, run_id={self.run_id}, "
            f"status={self.status}, attempt={self.attempt})>"
        )


# ---------------------------------------------------------------------------
# AnalysisLandmark
# ---------------------------------------------------------------------------

class AnalysisLandmark(Base):
    """A temporal point event within a dive clip.

    source distinguishes automatic proposals (AUTO) from human ground truth
    (HUMAN / HUMAN_CORRECTED) and imported labels (IMPORTED).

    applicability = NOT_APPLICABLE means the landmark is semantically undefined
    for this dive type (e.g. 'hurdle' for a standing dive).  No frame/time is
    stored in that case.
    """

    __tablename__ = "analysis_landmarks"

    id                      = Column(Integer, primary_key=True, index=True)
    run_id                  = Column(Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"),
                                     nullable=False, index=True)

    landmark_key            = Column(String(60), nullable=False, index=True)
    # e.g. 'takeoff', 'apex', 'water_contact', 'board_depression', 'hurdle'

    frame_index             = Column(Integer, nullable=True)
    timestamp_seconds       = Column(Numeric, nullable=True)

    confidence              = Column(Numeric, nullable=True)
    # 0.0–1.0; NULL when not computed

    source                  = Column(String(30), nullable=False, default="AUTO")
    # AUTO | HUMAN | HUMAN_CORRECTED | IMPORTED

    applicability           = Column(String(30), nullable=False, default="APPLICABLE")
    # APPLICABLE | NOT_APPLICABLE | UNCERTAIN

    algorithm_key           = Column(String(100), nullable=True)
    algorithm_version       = Column(String(40),  nullable=True)

    uncertainty_window_frames = Column(Integer, nullable=True)

    created_at              = Column(DateTime, nullable=False, default=datetime.utcnow)

    run = relationship("AnalysisRun", back_populates="landmarks")

    __table_args__ = (
        UniqueConstraint("run_id", "landmark_key", name="uq_analysis_landmarks_run_key"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_analysis_landmarks_confidence",
        ),
        CheckConstraint(
            "source IN ('AUTO', 'HUMAN', 'HUMAN_CORRECTED', 'IMPORTED')",
            name="ck_analysis_landmarks_source",
        ),
        CheckConstraint(
            "applicability IN ('APPLICABLE', 'NOT_APPLICABLE', 'UNCERTAIN')",
            name="ck_analysis_landmarks_applicability",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisLandmark(id={self.id}, run_id={self.run_id}, "
            f"key={self.landmark_key}, frame={self.frame_index}, "
            f"applicability={self.applicability}, source={self.source})>"
        )


# ---------------------------------------------------------------------------
# AnalysisPhase
# ---------------------------------------------------------------------------

class AnalysisPhase(Base):
    """A named interval between temporal boundaries within a dive clip.

    Boundaries are expressed as landmark_key references when possible;
    explicit frame/time values are a fallback when boundaries are not
    landmark-derived.
    """

    __tablename__ = "analysis_phases"

    id                  = Column(Integer, primary_key=True, index=True)
    run_id              = Column(Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"),
                                 nullable=False, index=True)

    phase_key           = Column(String(60), nullable=False)
    # e.g. 'pre_takeoff', 'flight_ascent', 'flight_descent', 'entry'
    # or coarser: 'takeoff', 'flight', 'entry'

    start_landmark_key  = Column(String(60), nullable=True)
    end_landmark_key    = Column(String(60), nullable=True)

    # Explicit fallback boundaries
    start_frame         = Column(Integer, nullable=True)
    end_frame           = Column(Integer, nullable=True)
    start_seconds       = Column(Numeric, nullable=True)
    end_seconds         = Column(Numeric, nullable=True)

    source              = Column(String(30), nullable=False, default="AUTO")
    confidence          = Column(Numeric, nullable=True)

    algorithm_key       = Column(String(100), nullable=True)
    algorithm_version   = Column(String(40),  nullable=True)

    created_at          = Column(DateTime, nullable=False, default=datetime.utcnow)

    run = relationship("AnalysisRun", back_populates="phases")

    __table_args__ = (
        UniqueConstraint("run_id", "phase_key", name="uq_analysis_phases_run_key"),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisPhase(id={self.id}, run_id={self.run_id}, "
            f"key={self.phase_key}, start={self.start_landmark_key}, "
            f"end={self.end_landmark_key})>"
        )


# ---------------------------------------------------------------------------
# AnalysisMetric
# ---------------------------------------------------------------------------

class AnalysisMetric(Base):
    """A scalar or compact structured quantitative result attached to a run.

    metric_key references the authoritative metric registry (defined in
    backend/app/data/metric_registry.yaml).  Consumers must use the same
    key+version pair; never compare metrics across incompatible versions.
    """

    __tablename__ = "analysis_metrics"

    id               = Column(Integer, primary_key=True, index=True)
    run_id           = Column(Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"),
                              nullable=False, index=True)

    metric_key       = Column(String(100), nullable=False, index=True)
    metric_version   = Column(String(20),  nullable=False, default="v1")

    # Value slots — exactly one populated per row
    value_numeric    = Column(Numeric, nullable=True)
    value_text       = Column(Text, nullable=True)
    value_json       = Column(JSON, nullable=True)

    unit             = Column(String(40), nullable=True)
    confidence       = Column(Numeric, nullable=True)
    phase_key        = Column(String(60), nullable=True)

    producer_key     = Column(String(100), nullable=True)
    producer_version = Column(String(40),  nullable=True)

    created_at       = Column(DateTime, nullable=False, default=datetime.utcnow)

    run = relationship("AnalysisRun", back_populates="metrics")

    def __repr__(self) -> str:
        v = self.value_numeric if self.value_numeric is not None else self.value_text
        return (
            f"<AnalysisMetric(id={self.id}, run_id={self.run_id}, "
            f"key={self.metric_key}@{self.metric_version}, value={v})>"
        )


# ---------------------------------------------------------------------------
# AnalysisArtifact
# ---------------------------------------------------------------------------

class AnalysisArtifact(Base):
    """Metadata record for a large / file-like analysis output.

    Actual bytes live under ANALYSIS_ARTIFACT_ROOT on the server filesystem.
    storage_path is relative to that root.

    Artifacts in status 'pending'/'writing' must not be served.
    Incomplete artifacts must not masquerade as completed results.
    """

    __tablename__ = "analysis_artifacts"

    id               = Column(Integer, primary_key=True, index=True)
    run_id           = Column(Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"),
                              nullable=False, index=True)

    artifact_key     = Column(String(100), nullable=False)
    # e.g. 'frame_strip', 'timeline_svg', 'centroid_trajectory_json'

    artifact_type    = Column(String(60), nullable=False)
    # e.g. 'diagnostic_json', 'frame_strip', 'timeline_svg',
    #      'trajectory_series', 'overlay_video', 'alignment_map'

    storage_path     = Column(Text, nullable=False)
    checksum_sha256  = Column(String(64), nullable=True)
    size_bytes       = Column(BigInteger, nullable=True)
    format           = Column(String(40), nullable=True)   # 'png', 'svg', 'json', 'mp4'

    status           = Column(String(30), nullable=False, default="pending", index=True)
    # pending | writing | ready | failed

    is_debug         = Column(Boolean, nullable=False, default=False)
    # Debug artifacts may be cleaned up aggressively; canonical results → False

    producer_key     = Column(String(100), nullable=True)
    producer_version = Column(String(40),  nullable=True)

    created_at       = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at       = Column(DateTime, nullable=False, default=datetime.utcnow,
                              onupdate=datetime.utcnow)

    run = relationship("AnalysisRun", back_populates="artifacts")

    __table_args__ = (
        UniqueConstraint("run_id", "artifact_key", name="uq_analysis_artifacts_run_key"),
        CheckConstraint(
            "status IN ('pending', 'writing', 'ready', 'failed')",
            name="ck_analysis_artifacts_status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisArtifact(id={self.id}, run_id={self.run_id}, "
            f"key={self.artifact_key}, type={self.artifact_type}, "
            f"status={self.status})>"
        )


# ---------------------------------------------------------------------------
# AnalysisComparison
# ---------------------------------------------------------------------------

class AnalysisComparison(Base):
    """First-class pairwise comparison between a target and a reference run.

    V1 supports explicit user-chosen pairings only.
    Automatic best-self or rolling-baseline selection is deferred.
    """

    __tablename__ = "analysis_comparisons"

    id                   = Column(Integer, primary_key=True, index=True)
    comparison_uuid      = Column(UUID(as_uuid=True), nullable=False, unique=True,
                                  server_default="gen_random_uuid()")

    target_run_id        = Column(Integer, ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
                                  nullable=False, index=True)
    reference_run_id     = Column(Integer, ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
                                  nullable=False, index=True)

    method_key           = Column(String(100), nullable=False)
    method_version       = Column(String(40),  nullable=False)
    canonical_parameters = Column(JSON, nullable=False, default=dict)
    spec_fingerprint     = Column(String(64),  nullable=False)

    status               = Column(String(30), nullable=False, default="pending", index=True)
    # pending | running | succeeded | failed

    created_at           = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at         = Column(DateTime, nullable=True)

    comparison_artifacts = relationship(
        "AnalysisComparisonArtifact", back_populates="comparison",
        cascade="all, delete-orphan",
    )
    comparison_metrics   = relationship(
        "AnalysisComparisonMetric", back_populates="comparison",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisComparison(id={self.id}, "
            f"target={self.target_run_id}, ref={self.reference_run_id}, "
            f"method={self.method_key}@{self.method_version}, "
            f"status={self.status})>"
        )


# ---------------------------------------------------------------------------
# AnalysisComparisonArtifact
# ---------------------------------------------------------------------------

class AnalysisComparisonArtifact(Base):
    """An artifact produced as output of a comparison (e.g. alignment_map)."""

    __tablename__ = "analysis_comparison_artifacts"

    id              = Column(Integer, primary_key=True, index=True)
    comparison_id   = Column(Integer,
                             ForeignKey("analysis_comparisons.id", ondelete="CASCADE"),
                             nullable=False, index=True)

    artifact_key    = Column(String(100), nullable=False)
    artifact_type   = Column(String(60),  nullable=False)
    storage_path    = Column(Text, nullable=False)
    checksum_sha256 = Column(String(64), nullable=True)
    size_bytes      = Column(BigInteger, nullable=True)
    format          = Column(String(40), nullable=True)
    status          = Column(String(30), nullable=False, default="pending")

    created_at      = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at      = Column(DateTime, nullable=False, default=datetime.utcnow,
                             onupdate=datetime.utcnow)

    comparison = relationship("AnalysisComparison", back_populates="comparison_artifacts")

    __table_args__ = (
        UniqueConstraint("comparison_id", "artifact_key",
                         name="uq_analysis_comparison_artifacts_cmp_key"),
    )


# ---------------------------------------------------------------------------
# AnalysisComparisonMetric
# ---------------------------------------------------------------------------

class AnalysisComparisonMetric(Base):
    """A scalar difference metric produced by a comparison."""

    __tablename__ = "analysis_comparison_metrics"

    id              = Column(Integer, primary_key=True, index=True)
    comparison_id   = Column(Integer,
                             ForeignKey("analysis_comparisons.id", ondelete="CASCADE"),
                             nullable=False, index=True)

    metric_key      = Column(String(100), nullable=False)
    metric_version  = Column(String(20),  nullable=False, default="v1")
    value_numeric   = Column(Numeric, nullable=True)
    value_text      = Column(Text, nullable=True)
    value_json      = Column(JSON, nullable=True)
    unit            = Column(String(40), nullable=True)
    phase_key       = Column(String(60), nullable=True)

    created_at      = Column(DateTime, nullable=False, default=datetime.utcnow)

    comparison = relationship("AnalysisComparison", back_populates="comparison_metrics")

    __table_args__ = (
        UniqueConstraint("comparison_id", "metric_key",
                         name="uq_analysis_comparison_metrics_cmp_key"),
    )
