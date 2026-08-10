"""Database-neutral SQLAlchemy runtime for SQL Server, PostgreSQL, and dev SQLite."""

import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import get_settings


Base = declarative_base()


def normalize_database_url(database_url: str) -> str:
    """Select psycopg 3 when a provider supplies a driver-neutral Postgres URL."""
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


DATABASE_URL = normalize_database_url(get_settings().database_url)


def database_backend(database_url: str) -> str:
    return make_url(normalize_database_url(database_url)).get_backend_name()


def _workspace_sqlite_path() -> Path:
    override = os.getenv("QUANTPULSE_SQLITE_PATH")

    if override:
        path = Path(override).expanduser()
        sqlite_path = path if path.suffix else path / "quantpulse_ai.sqlite"
    else:
        sqlite_path = Path(tempfile.gettempdir()) / "quantpulse_ai" / "quantpulse_ai.sqlite"

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite_path


def _build_database_engine(database_url: str):
    return create_engine(
        normalize_database_url(database_url),
        pool_size=20,
        max_overflow=30,
        pool_timeout=60,
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def _build_sqlite_engine():
    sqlite_path = _workspace_sqlite_path()
    return create_engine(
        f"sqlite:///{sqlite_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )


def _initialize_engine(database_url=None, settings=None, engine_builder=None):
    configured_url = normalize_database_url(database_url or DATABASE_URL)
    runtime_settings = settings or get_settings()

    if database_backend(configured_url) == "sqlite":
        if not runtime_settings.allow_sqlite_fallback:
            raise RuntimeError(
                "SQLite evidence storage is disabled. Configure QUANTPULSE_DATABASE_URL "
                "for the production database."
            )
        return _build_sqlite_engine(), True

    builder = engine_builder or _build_database_engine
    try:
        database_engine = builder(configured_url)
        with database_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return database_engine, False
    except SQLAlchemyError as exc:
        if not runtime_settings.allow_sqlite_fallback:
            raise RuntimeError(
                "Canonical database connection failed and SQLite fallback is disabled."
            ) from exc
        return _build_sqlite_engine(), True


engine, USING_SQLITE_FALLBACK = _initialize_engine()
DATABASE_BACKEND = engine.url.get_backend_name()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
