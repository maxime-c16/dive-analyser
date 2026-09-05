"""FastAPI application entry point"""

import logging
import os
from contextlib import asynccontextmanager
from time import perf_counter
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.database import init_db, get_db
from app.api.v1 import v1_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


def run_auto_import():
    """Run automatic import on startup if JSON file exists"""
    from app.services.import_service import ImportService, find_latest_json
    from app.database import SessionLocal

    # Check if auto-import is enabled (default: True)
    auto_import = os.environ.get('AUTO_IMPORT', 'true').lower() == 'true'
    if not auto_import:
        logger.info("Auto-import disabled via AUTO_IMPORT env var")
        return

    # Find JSON file
    json_path = None
    for base_path in ['/app/reports', '/app', '.', 'reports']:
        result = find_latest_json(base_path)
        if result:
            json_path = result
            break

    if not json_path:
        logger.info("No dive metadata JSON found for auto-import")
        return

    db = SessionLocal()
    lock_key = 834927
    locked = False
    try:
        # Multiple Uvicorn workers start independently. Only one may import,
        # otherwise they can compete to update every session at startup.
        locked = bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}).scalar())
        if not locked:
            logger.info("Auto-import skipped; another backend worker owns the import lock")
            return
        logger.info(f"Auto-importing data from: {json_path}")
        service = ImportService(db)
        stats = service.import_from_json(json_path)
        logger.info(f"Auto-import complete: {stats['sessions_created']} sessions, {stats['dives_created']} dives created, {stats['dives_skipped']} skipped")
        if stats['errors']:
            logger.warning(f"Import errors: {stats['errors'][:5]}")  # Log first 5 errors
    except Exception as e:
        logger.error(f"Auto-import failed: {e}")
    finally:
        if locked:
            db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("Starting Diving Analytics API")
    init_db()
    db_url = make_url(settings.database_url)
    logger.info("Connected to database: %s", db_url.render_as_string(hide_password=True))

    # Auto-import data on startup
    run_auto_import()

    yield

    # Shutdown
    logger.info("Shutting down Diving Analytics API")


# Create FastAPI app
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="Interactive analytics API for diving performance tracking",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_slow_requests(request, call_next):
    started_at = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - started_at) * 1000
    if elapsed_ms >= settings.slow_request_log_ms:
        logger.warning(
            "Slow request: %s %s -> %s in %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    return response


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "api": settings.api_title,
        "version": settings.api_version,
    }


# Root endpoint
@app.get("/", tags=["root"])
async def root():
    """Root endpoint"""
    return {
        "message": "Diving Analytics API",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


# Include API routes
app.include_router(v1_router)

logger.info("FastAPI application initialized")
