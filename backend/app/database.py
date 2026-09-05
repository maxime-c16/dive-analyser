"""Database configuration and session management"""

from time import perf_counter

from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.pool import StaticPool
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Create engine
engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
}
if settings.database_url.startswith("sqlite"):
    engine_kwargs.update({
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    })
else:
    engine_kwargs.update({
        "pool_recycle": 3600,
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
    })

engine = create_engine(settings.database_url, **engine_kwargs)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class for models
Base = declarative_base()


def get_db() -> Session:
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database (create all tables)"""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Set SQLite pragmas (no-op for PostgreSQL)"""
    pass


@event.listens_for(Engine, "before_cursor_execute")
def start_query_timer(conn, cursor, statement, parameters, context, executemany):
    context._dive_query_started_at = perf_counter()


@event.listens_for(Engine, "after_cursor_execute")
def log_slow_query(conn, cursor, statement, parameters, context, executemany):
    started_at = getattr(context, "_dive_query_started_at", None)
    if started_at is None:
        return
    elapsed_ms = (perf_counter() - started_at) * 1000
    if elapsed_ms >= settings.slow_query_log_ms:
        logger.warning("Slow database query: %.1fms: %s", elapsed_ms, " ".join(statement.split())[:300])
