"""Allow-listed media-agent authentication and source reporting."""

import hashlib
import hmac
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.media import MediaAgent, RecalledMediaSource
from app.schemas.media import MediaAgentHeartbeatRequest, RecalledSourceReportRequest


def authenticate_media_agent(db: Session, agent_id: str, api_key: str) -> MediaAgent:
    agent = db.get(MediaAgent, agent_id)
    supplied_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    if not agent or not agent.active or not hmac.compare_digest(agent.api_key_sha256, supplied_hash):
        raise PermissionError("media_agent_not_authorized")
    return agent


def require_leasing_agent(db: Session, agent_id: str, api_key: str) -> MediaAgent:
    agent = authenticate_media_agent(db, agent_id, api_key)
    if not agent.leasing_enabled:
        raise PermissionError("media_agent_leasing_disabled")
    return agent


def update_agent_heartbeat(
    db: Session,
    request: MediaAgentHeartbeatRequest,
    api_key: str,
) -> MediaAgent:
    agent = authenticate_media_agent(db, request.agent_id, api_key)
    now = datetime.utcnow()
    agent.hostname = request.hostname
    agent.capabilities = request.capabilities
    agent.photos_access_status = request.photos_access_status
    agent.last_successful_photos_query_at = request.last_successful_photos_query_at
    agent.last_permission_error_at = request.last_permission_error_at
    agent.last_query_timeout_at = request.last_query_timeout_at
    agent.last_successful_export_at = request.last_successful_export_at
    agent.last_materialization_success_at = request.last_materialization_success_at
    agent.internal_free_bytes = request.internal_free_bytes
    agent.vault_volume_uuid = request.vault_volume_uuid
    agent.vault_free_bytes = request.vault_free_bytes
    agent.vault_mounted = request.vault_mounted
    agent.storage_status = request.storage_status
    agent.last_seen_at = now
    agent.updated_at = now
    db.add(agent)
    db.flush()
    return agent


def report_recalled_source(
    db: Session,
    request: RecalledSourceReportRequest,
    api_key: str,
) -> RecalledMediaSource:
    authenticate_media_agent(db, request.agent_id, api_key)
    if request.dive_id is not None:
        dive = db.get(Dive, request.dive_id)
        if not dive or dive.video_uuid != request.video_uuid:
            raise ValueError("source_dive_uuid_mismatch")

    existing = db.execute(
        select(RecalledMediaSource).where(
            RecalledMediaSource.video_uuid == request.video_uuid,
            RecalledMediaSource.agent_id == request.agent_id,
            RecalledMediaSource.active.is_(True),
        )
    ).scalars().first()
    source = existing or RecalledMediaSource(
        video_uuid=request.video_uuid,
        agent_id=request.agent_id,
    )
    source.dive_id = request.dive_id
    source.source_kind = request.source_kind
    source.source_path = request.source_path
    source.volume_uuid = request.volume_uuid
    source.size_bytes = request.size_bytes
    source.checksum_sha256 = request.checksum_sha256
    source.retention_class = request.retention_class
    source.active = True
    source.validated_at = request.validated_at
    source.last_seen_at = datetime.utcnow()
    source.expires_at = request.expires_at
    db.add(source)
    db.flush()
    return source


def public_agent_status(agent: MediaAgent) -> dict:
    return {
        "agent_id": agent.id,
        "hostname": agent.hostname,
        "active": agent.active,
        "leasing_enabled": agent.leasing_enabled,
        "capabilities": agent.capabilities or [],
        "photos_access_status": agent.photos_access_status,
        "last_successful_photos_query_at": agent.last_successful_photos_query_at,
        "last_permission_error_at": agent.last_permission_error_at,
        "last_query_timeout_at": agent.last_query_timeout_at,
        "last_successful_export_at": agent.last_successful_export_at,
        "last_materialization_success_at": agent.last_materialization_success_at,
        "internal_free_bytes": agent.internal_free_bytes,
        "vault_volume_uuid": agent.vault_volume_uuid,
        "vault_free_bytes": agent.vault_free_bytes,
        "vault_mounted": agent.vault_mounted,
        "storage_status": agent.storage_status,
        "last_seen_at": agent.last_seen_at,
    }
