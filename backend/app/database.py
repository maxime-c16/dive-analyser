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
        # Explicit rollback before close: ensures any open transaction is
        # ended regardless of the code path that called db.close().  Without
        # this, SQLAlchemy 2.0 Session.close() can return the connection to
        # the pool while the transaction is still open (idle in transaction),
        # blocking concurrent UPDATEs until Postgres kills the connection.
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


def init_db():
    """Initialize database (create all tables).

    Tables tagged ``sql_migration_only`` (the calendar domain) are skipped:
    their SQL migration is an explicit deployment step, never a side effect
    of starting a new backend image.
    """
    tables = [t for t in Base.metadata.sorted_tables if not t.info.get("sql_migration_only")]
    Base.metadata.create_all(bind=engine, tables=tables)
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
