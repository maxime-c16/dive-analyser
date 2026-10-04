"""WebSocket endpoint for real-time sync status updates."""

import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query, status
from fastapi.exceptions import WebSocketException
import uuid

from app.config import get_settings
from app.database import SessionLocal
from app.services import sessions as session_service
from app.services.workspace_access import require_workspace_user
from app.services.sync_status import (
    get_ws_manager,
    get_status_tracker,
    SyncEventType,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["websocket"])


def _ws_session_ok(websocket: WebSocket) -> bool:
    """Session-boundary check for the sync websocket.

    WS connections share the workspace data scope, so the boundary mirrors
    require_workspace_user: mandatory only when user auth is ENABLED
    (legacy flag-off access preserved). The cookie is resolved against its
    own short-lived session so the request session is never held for the
    whole websocket lifetime.
    """
    settings = get_settings()
    if not settings.user_auth_enabled:
        return True
    with SessionLocal() as db:
        resolved = session_service.resolve_session(
            db, websocket.cookies.get(settings.auth_cookie_name)
        )
    return resolved is not None


@router.websocket("/sync")
async def websocket_sync_endpoint(websocket: WebSocket, client_id: str = Query(None)):
    """
    WebSocket endpoint for real-time sync status updates.

    Clients can connect to receive live updates about video sync operations.

    Query Parameters:
        client_id: Optional client identifier. If not provided, a UUID is generated.

    Message Format (received from client):
        {
            "type": "heartbeat" | "get_status",
            "sync_id": "optional-sync-id"
        }

    Message Format (sent to client):
        {
            "type": "sync_started" | "sync_progress" | "sync_complete" | "sync_error" | "milestone_detected",
            "timestamp": "2026-01-31T12:00:00",
            "sync_id": "sync-uuid",
            "data": {...}
        }

    Args:
        websocket: WebSocket connection
        client_id: Optional client identifier
    """
    # Generate client_id if not provided
    if not client_id:
        client_id = str(uuid.uuid4())[:8]

    if not _ws_session_ok(websocket):
        # No live session while auth is enabled: reject the upgrade before
        # accepting. 1008 (policy violation) tells the front end to stop
        # retrying the same unauthenticated state.
        logger.warning("Sync websocket rejected: no live session (client_id=%s)", client_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    ws_manager = get_ws_manager()
    status_tracker = get_status_tracker()

    try:
        # Accept connection
        await websocket.accept()
        await ws_manager.connect(websocket, client_id)

        while True:
            # Receive message from client
            try:
                message = await websocket.receive_text()
            except WebSocketDisconnect:
                await ws_manager.disconnect(websocket, client_id)
                logger.info(f"Client disconnected: {client_id}")
                break

            # Parse message
            try:
                import json
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from {client_id}: {message}")
                continue

            message_type = data.get("type", "unknown")
            sync_id = data.get("sync_id")

            # Handle message types
            if message_type == "heartbeat":
                # Client heartbeat - no response needed, just acknowledgment
                logger.debug(f"Heartbeat from {client_id}")

            elif message_type == "get_status" and sync_id:
                # Client requesting sync status
                tracked = status_tracker.get_status(sync_id)
                if tracked:
                    # Send status back to client
                    import json
                    from app.services.sync_status import SyncEvent

                    event = SyncEvent(
                        type=SyncEventType.HEARTBEAT,
                        timestamp=__import__("datetime").datetime.utcnow().isoformat(),
                        sync_id=sync_id,
                        data=tracked.to_dict(),
                    )
                    await websocket.send_text(event.to_json())

            else:
                logger.debug(f"Unknown message type from {client_id}: {message_type}")

    except WebSocketException as e:
        logger.error(f"WebSocket exception for {client_id}: {e}")
        await ws_manager.disconnect(websocket, client_id)
    except Exception as e:
        logger.error(f"Unexpected error for {client_id}: {e}")
        try:
            await ws_manager.disconnect(websocket, client_id)
        except:
            pass


@router.get("/sync/status", dependencies=[Depends(require_workspace_user)])
async def get_all_sync_statuses():
    """
    Get status of all active syncs.

    Returns:
        Dictionary of all active sync statuses
    """
    status_tracker = get_status_tracker()
    statuses = {}

    for sync_id, status in status_tracker.get_all_active().items():
        statuses[sync_id] = status.to_dict()

    return {
        "active_syncs": statuses,
        "total_active": len(statuses),
        "connected_clients": get_ws_manager().get_connected_clients(),
    }


@router.get("/sync/status/{sync_id}", dependencies=[Depends(require_workspace_user)])
async def get_sync_status(sync_id: str):
    """
    Get status of a specific sync.

    Args:
        sync_id: Sync identifier

    Returns:
        SyncStatus dictionary or error if not found
    """
    status_tracker = get_status_tracker()
    status = status_tracker.get_status(sync_id)

    if not status:
        return {
            "error": f"Sync {sync_id} not found",
            "available_syncs": list(status_tracker.get_all_active().keys()),
        }

    return status.to_dict()


@router.get("/health")
async def ws_health():
    """
    Health check for WebSocket system.

    Returns:
        Health status information
    """
    ws_manager = get_ws_manager()
    status_tracker = get_status_tracker()

    return {
        "status": "healthy",
        "connected_clients": ws_manager.get_connected_clients(),
        "total_connections": ws_manager.get_total_connections(),
        "active_syncs": len(status_tracker.get_all_active()),
        "completed_syncs": len(status_tracker.get_all_completed()),
    }
