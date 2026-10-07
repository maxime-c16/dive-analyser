"""Health and read-only operational status endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.operations_status import build_operations_status

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


@router.get("/operations/status")
def operations_status(db: Session = Depends(get_db)):
    """Return a LAN/WireGuard read-only operational snapshot for the admin UI."""
    # The snapshot uses synchronous SQLAlchemy and media coverage work. FastAPI
    # runs sync routes in its thread pool so unrelated requests can proceed.
    return build_operations_status(db)
