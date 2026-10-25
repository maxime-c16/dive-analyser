"""Schemas for asynchronous media cache requests."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class MediaJobSummary(BaseModel):
    id: int
    status: str
    rendition: str
    progress: int = 0
    request_reason: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MediaCacheEntrySummary(BaseModel):
    id: int
    rendition: str
    status: str
    content_type: Optional[str] = None
    size_bytes: int
    playback_url: str
    created_at: datetime
    expires_at: Optional[datetime] = None


class DerivativeRoleStatus(BaseModel):
    """One durable-derivative role's honest read state (D5).

    Only ``state == 'ready'`` carries a playback URL (distinct bytes or
    an honest small-source HQ alias via ``aliased_to == 'light'``).
    Every other state (missing|preparing|stale|superseded|unavailable)
    reports no URL: the player falls back to legacy renditions.
    """

    state: str = "missing"
    playback_url: Optional[str] = None
    revision_id: Optional[int] = None
    aliased_to: Optional[str] = None


class DerivativeStatusBlock(BaseModel):
    """Whole-clip durable-derivative read for one canonical source."""

    source_revision_id: Optional[int] = None
    transform_version: Optional[str] = None
    start: Optional[str] = None
    recommended: Optional[str] = None
    hq: DerivativeRoleStatus = Field(default_factory=DerivativeRoleStatus)
    light: DerivativeRoleStatus = Field(default_factory=DerivativeRoleStatus)
    poster: DerivativeRoleStatus = Field(default_factory=DerivativeRoleStatus)


class MediaStatusResponse(BaseModel):
    video_uuid: str
    status: str
    can_request: bool
    preferred_rendition: Optional[str] = None
    available_renditions: List[str] = Field(default_factory=list)
    playback_url: Optional[str] = None
    poster_url: Optional[str] = None
    thumb_url: Optional[str] = None
    thumbhash: Optional[str] = None
    full_quality_url: Optional[str] = None
    preview_url: Optional[str] = None
    derivatives: Optional[DerivativeStatusBlock] = None
    cache_entries: List[MediaCacheEntrySummary] = Field(default_factory=list)
    job: Optional[MediaJobSummary] = None
    last_mac_seen_at: Optional[datetime] = None


class MediaRequest(BaseModel):
    rendition: str = Field("proxy_720p", pattern="^(poster|proxy_360p|proxy_720p|original)$")
    reason: Optional[str] = Field("user_view", max_length=40)


class MediaStatusBatchRequest(BaseModel):
    video_uuids: List[str] = Field(..., max_length=1000, min_length=1)


class MediaRequestResponse(MediaStatusResponse):
    media_key: str
    created_job: bool = False
    reused_job: bool = False
    cache_hit: bool = False


class MediaJobLeaseRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    capabilities: List[str] = Field(default_factory=lambda: ["poster", "proxy_360p", "proxy_720p"])
    max_jobs: int = Field(1, ge=1, le=5)
    lease_seconds: int = Field(300, ge=60, le=3600)
    # D2 lease fencing: workers that understand per-claim fencing tokens set
    # this. Old workers omit it (False) and receive legacy tokenless leases
    # during the bounded SERVER-before-MAC drain (see
    # docs/design/media-d2-rollout.md). After the drain,
    # MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true rejects non-token leases.
    supports_lease_token: bool = False


class MediaLeasedJob(BaseModel):
    job_id: int
    video_uuid: str
    canonical_video_uuid: str
    rendition: str
    media_key: str
    status: str
    request_reason: Optional[str] = None
    export_options: dict = Field(default_factory=dict)
    # D2 fencing token for this claim (uuid4 hex). None only for legacy
    # tokenless leases issued to old workers during the drain window.
    # Every heartbeat/upload/finalize/fail for a tokened claim must echo it.
    lease_token: Optional[str] = None
    # Verified B2 original to transcode from (signed, short-lived). Absent
    # when no verified replica exists or signing is unavailable: the agent
    # then falls back to its Photos export.
    source_url: Optional[str] = None
    source_sha256: Optional[str] = None
    source_size_bytes: Optional[int] = None
    # D3b2 fenced web package (rendition == "web_package" only): the exact
    # transform identity pinned at lease plus the per-slot derivative media
    # keys the worker must stamp. Legacy renditions leave these None so old
    # workers and old flows are byte-identical.
    transform_version: Optional[str] = None
    expected_slots: Optional[List[str]] = None
    package_media_keys: Optional[dict] = None


class MediaJobLeaseResponse(BaseModel):
    jobs: List[MediaLeasedJob] = Field(default_factory=list)


class MediaJobHeartbeatRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    status: str = Field(..., pattern="^(claimed|materializing|exporting|transcoding|uploading|verifying)$")
    progress: int = Field(0, ge=0, le=100)
    # D2 fencing token echoed from the lease. None = legacy worker; accepted
    # only while the stored claim is itself tokenless (pre-D2 drain).
    lease_token: Optional[str] = None


class MediaJobFailRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    error: str = Field(..., min_length=1)
    status: str = Field("failed", pattern="^(failed|unavailable)$")
    # D2 fencing token (same rule as heartbeat): a stale worker must not
    # fail a job that has since been re-leased to a new attempt.
    lease_token: Optional[str] = None


class MediaJobUploadResponse(BaseModel):
    job_id: int
    status: str
    upload_tmp_path: str
    size_bytes: int
    checksum_sha256: str


class MediaJobFinalizeRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    checksum_sha256: str = Field(..., min_length=64, max_length=64)
    size_bytes: int = Field(..., ge=1)
    content_type: str = Field("application/octet-stream", max_length=100)
    # D2 fencing token echoed from the lease (same rule as heartbeat).
    lease_token: Optional[str] = None


class MediaJobFinalizeResponse(BaseModel):
    job_id: int
    status: str
    cache_entry_id: int
    playback_url: str


class MediaPackageSlotFinalizeRequest(BaseModel):
    """Finalize one web_package slot (hq/light/poster) into durable storage.

    The worker uploads slot bytes first (slot upload route), then calls this
    with the staged checksum/size plus the source identity it actually
    encoded. The server re-validates everything (lease token + expiry with a
    row lock, canonical source SHA, transform version, slot format via
    ffprobe) before any B2 publish, and commits the ledger row plus the
    job's finalized_slots atomically. A stale attempt (re-leased mid-upload,
    source changed) is rejected with 409 and its verified B2 bytes are kept
    as a safe orphan — never promoted to ready.
    """

    agent_id: str = Field(..., min_length=1, max_length=100)
    slot: str = Field(..., pattern="^(hq|light|poster)$")
    checksum_sha256: str = Field(..., min_length=64, max_length=64)
    size_bytes: int = Field(..., ge=1)
    content_type: str = Field("application/octet-stream", max_length=100)
    # D2 fencing token echoed from the lease (same rule as heartbeat).
    lease_token: Optional[str] = None
    # Source the worker actually encoded (must match the canonical source
    # pinned at lease AND the current canonical source at commit).
    source_sha256: str = Field(..., min_length=64, max_length=64)
    # Small-source honesty: when the source short side is below a role
    # floor the worker declares hq_aliased_to="light" and omits hq. The
    # server checks the claim against the actual probed slot dims instead
    # of trusting it blindly (see web_packages.expected_slots_for_source).
    hq_aliased_to: Optional[str] = Field(None, pattern="^(light)$")
    source_width: Optional[int] = Field(None, ge=1)
    source_height: Optional[int] = Field(None, ge=1)
    # Lease-pinned transform echoed from the lease payload (must equal the
    # persisted job pin AND the canonical transform on EVERY slot). The slot
    # route requires the same field as Form data; this schema keeps the
    # contract truthful for any future JSON callers.
    transform_version: Optional[str] = Field(None, max_length=40)


class MediaPackageSlotFinalizeResponse(BaseModel):
    job_id: int
    slot: str
    status: str
    derivative_status: str
    job_ready: bool
    finalized_slots: List[str] = Field(default_factory=list)


class MediaPinResponse(BaseModel):
    entry_id: int
    pinned: bool


class MediaCleanupResponse(BaseModel):
    removed_entries: int
    removed_bytes: int
    remaining_bytes: int


class RepresentativePrepareRequest(BaseModel):
    tier: int = Field(1, ge=1, le=1)
    renditions: List[str] = Field(default_factory=lambda: ["poster", "proxy_720p"])
    dry_run: bool = True


class RepresentativeReplaceRequest(BaseModel):
    replacement_dive_id: int = Field(..., ge=1)
    prepare: bool = False
    renditions: List[str] = Field(default_factory=lambda: ["poster", "proxy_720p"])
    diver_scope: str = "self"
    diver_id: int | None = None


class RepresentativeReadyRemapRequest(BaseModel):
    """Promote already-playable candidates without creating media work."""

    dry_run: bool = True
    max_changes: int = Field(100, ge=1, le=200)
    diver_scope: str = Field("self", pattern="^(self|all)$")
    diver_id: int | None = None


class MediaAgentHeartbeatRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    hostname: str = Field(..., min_length=1, max_length=255)
    capabilities: List[str] = Field(default_factory=list)
    photos_access_status: str = Field("unknown", pattern="^(ok|permission_required|denied|query_timeout|library_unavailable|sync_incomplete|unknown)$")
    last_successful_photos_query_at: Optional[datetime] = None
    last_permission_error_at: Optional[datetime] = None
    last_query_timeout_at: Optional[datetime] = None
    last_successful_export_at: Optional[datetime] = None
    last_materialization_success_at: Optional[datetime] = None
    internal_free_bytes: Optional[int] = Field(None, ge=0)
    vault_volume_uuid: Optional[str] = Field(None, max_length=64)
    vault_free_bytes: Optional[int] = Field(None, ge=0)
    vault_mounted: bool = False
    storage_status: Optional[dict] = None


class RecallBatchPlanRequest(BaseModel):
    priority: str = Field(..., pattern="^(zero_ready_typical|partial_typical_proxy|representative_high|representative_low|recent|historical)$")
    limit: int = Field(6, ge=1, le=10)
    dry_run: bool = True


class RecalledSourceReportRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    video_uuid: str = Field(..., min_length=36, max_length=100)
    dive_id: Optional[int] = Field(None, ge=1)
    source_kind: str = Field(..., min_length=1, max_length=50)
    source_path: str = Field(..., min_length=1)
    volume_uuid: str = Field(..., min_length=1, max_length=64)
    size_bytes: int = Field(..., ge=1)
    checksum_sha256: str = Field(..., min_length=64, max_length=64)
    retention_class: str = Field("temporary", pattern="^(permanent_representative|pinned|recent|temporary|failed_diagnostic)$")
    validated_at: datetime
    expires_at: Optional[datetime] = None


class CatalogRunStartRequest(BaseModel):
    agent_id: str = Field("mac-media-01", min_length=1, max_length=100)


class CatalogRunLeaseRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)


class CaptionedCatalogRecord(BaseModel):
    agent_local_uuid: str = Field(..., min_length=36, max_length=100)
    cloud_fingerprint: Optional[str] = Field(None, max_length=100)
    raw_caption: str = Field(..., min_length=1)
    captured_at: Optional[datetime] = None
    duration_seconds: Optional[float] = Field(None, ge=0)
    width: Optional[int] = Field(None, ge=0)
    height: Optional[int] = Field(None, ge=0)
    estimated_source_bytes: Optional[int] = Field(None, ge=0)
    filename: Optional[str] = Field(None, max_length=255)
    local_available: bool = False
    is_missing: bool = False
    in_cloud: bool = False
    is_hidden: bool = False
    parsed_metadata: Optional[dict] = None


class CatalogChunkRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    checkpoint: int = Field(..., ge=1)
    records: List[CaptionedCatalogRecord] = Field(..., min_length=1, max_length=250)


class CatalogCompleteRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    photos_library_bytes_start: Optional[int] = Field(None, ge=0)
    photos_library_bytes_end: Optional[int] = Field(None, ge=0)
    free_bytes_start: Optional[int] = Field(None, ge=0)
    free_bytes_end: Optional[int] = Field(None, ge=0)


class CatalogFailRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    error: str = Field(..., min_length=1, max_length=2000)
    paused: bool = False


class CatalogPopulationPlanRequest(BaseModel):
    scope: str = Field("all_eligible_captioned", pattern="^all_eligible_captioned$")
    dry_run: bool = True


class CatalogPopulationStartRequest(BaseModel):
    limit: int = Field(..., ge=1, le=200)
    stage: int = Field(..., ge=1, le=3)
    catalog_item_ids: List[int] = Field(default_factory=list, max_length=200)


class CatalogPopulationRolloverRequest(BaseModel):
    batch_limit: int = Field(200, ge=1, le=200)


class ResolutionUpgradeStartRequest(BaseModel):
    """Schedule a safe one-at-a-time 360p to 720p migration."""

    starts_after_population_run_id: Optional[int] = Field(None, ge=1)
    scope: str = Field("self", pattern="^(self|all)$")
