"""
Database connection and session management
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise EnvironmentError("DATABASE_URL environment variable is required")

_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # Local desktop fallback DB tuning: enable WAL and avoid thread pinning.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        echo=os.getenv("DEBUG", "False") == "True",
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()
else:
    # Server database (PostgreSQL): pooled connections for high-load API.
    _statement_timeout_ms = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "60000"))
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # Verify connections before using
        pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),  # 30min: avoid stale conn
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),    # fail fast under exhaustion
        connect_args={
            "options": f"-c statement_timeout={_statement_timeout_ms}",
        },
        echo=os.getenv("DEBUG", "False") == "True",
    )

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Context manager for database sessions
    
    Usage:
        with get_db() as db:
            db.query(Transaction).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Generator[Session, None, None]:
    """
    Get database session for dependency injection (FastAPI).

    Commits only when the session has actual changes — avoids per-GET WAL flush.
    """
    db = SessionLocal()
    try:
        yield db
        if db.new or db.dirty or db.deleted:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Initialize database tables in dev mode only.

    Production environments should use Alembic migrations.
    """
    from database.models import Base
    allow_create_all = str(os.getenv("DB_CREATE_ALL_ON_STARTUP", "false")).strip().lower() in {
        "1", "true", "yes", "on"
    }
    if allow_create_all:
        Base.metadata.create_all(bind=engine)
