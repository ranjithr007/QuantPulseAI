"""Compatibility imports for legacy modules.

New database code should import from ``app.database.runtime``. This module stays
temporarily so the PostgreSQL transition does not require a risky all-at-once
rewrite of jobs, repositories, and model imports.
"""

from app.database.runtime import Base
from app.database.runtime import DATABASE_BACKEND
from app.database.runtime import DATABASE_URL
from app.database.runtime import SessionLocal
from app.database.runtime import USING_SQLITE_FALLBACK
from app.database.runtime import _build_database_engine
from app.database.runtime import _build_sqlite_engine
from app.database.runtime import _initialize_engine
from app.database.runtime import database_backend
from app.database.runtime import engine
from app.database.runtime import normalize_database_url


# Backward-compatible helper name retained for external scripts during PG1.
_build_sqlserver_engine = _build_database_engine


from app.database import models as _models  # noqa: E402,F401
