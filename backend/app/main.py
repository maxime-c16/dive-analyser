"""FastAPI application entry point"""

import asyncio
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

    from app.services.upload_queue import start_worker
    upload_worker_stop = start_worker()
    from app.services.xray import loop_lag
    lag_task = asyncio.create_task(loop_lag.run())
    try:
        yield
    finally:
        upload_worker_stop.set()
        lag_task.cancel()
        try:
            await lag_task
        except asyncio.CancelledError:
            pass

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


class _SlowRequestLogger:
    """Pure ASGI slow-request logger.

    Replaces the former @app.middleware("http") / BaseHTTPMiddleware approach
    that caused SQLAlchemy sessions to leak when clients disconnected (HTTP
    499).  BaseHTTPMiddleware defers dependency-generator teardown (db.close)
    until the response body is consumed by the middleware coroutine; a client
    disconnect means that never happens, leaving connections "idle in
    transaction" with row-level locks until Postgres kills them.

    This middleware awaits the inner ASGI app directly so teardown runs as
    part of the normal request lifecycle and is unaffected by client drops.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started_at = perf_counter()
        from app.services.xray import request_timing
        timing = {"auth": 0.0, "db": 0.0}
        token = request_timing.set(timing)
        status_code = 0

        async def send_with_capture(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                if scope.get("path", "").startswith("/api/"):
                    # auth and db overlap; app is total time until response headers.
                    total = (perf_counter() - started_at) * 1000
                    value = f'auth;dur={timing["auth"]:.2f}, db;dur={timing["db"]:.2f}, app;dur={total:.2f}'
                    message.setdefault("headers", []).append((b"server-timing", value.encode("ascii")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_capture)
        finally:
            request_timing.reset(token)
        elapsed_ms = (perf_counter() - started_at) * 1000
        if elapsed_ms >= settings.slow_request_log_ms:
            logger.warning(
                "Slow request: %s %s -> %s in %.1fms",
                scope.get("method", "?"),
                scope.get("path", "?"),
                status_code,
                elapsed_ms,
            )


app.add_middleware(_SlowRequestLogger)


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
from app.api.v1.ws_sync import socket_router
app.include_router(socket_router, prefix="/api/v1")

logger.info("FastAPI application initialized")
