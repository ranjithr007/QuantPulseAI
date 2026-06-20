import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import get_settings


Base = declarative_base()
DATABASE_URL = get_settings().database_url


def _workspace_sqlite_path() -> Path:
    override = os.getenv("QUANTPULSE_SQLITE_PATH")

    if override:
        path = Path(override).expanduser()
        if path.suffix:
            sqlite_path = path
        else:
            sqlite_path = path / "quantpulse_ai.sqlite"
    else:
        sqlite_path = Path(tempfile.gettempdir()) / "quantpulse_ai" / "quantpulse_ai.sqlite"

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite_path


def _build_sqlserver_engine(database_url: str):
    return create_engine(
        database_url,
        pool_size=20,
        max_overflow=30,
        pool_timeout=60,
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def _build_sqlite_engine():
    sqlite_path = _workspace_sqlite_path()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{sqlite_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )


def _initialize_engine():
    database_url = DATABASE_URL

    if database_url.startswith("sqlite"):
        return _build_sqlite_engine(), True

    try:
        sqlserver_engine = _build_sqlserver_engine(database_url)
        with sqlserver_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return sqlserver_engine, False
    except SQLAlchemyError:
        return _build_sqlite_engine(), True


engine, USING_SQLITE_FALLBACK = _initialize_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


from app.database import models as _models  # noqa: E402,F401
