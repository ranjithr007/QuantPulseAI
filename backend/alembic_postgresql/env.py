import os
import sys

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.runtime import Base
from app.database.runtime import DATABASE_URL
import app.database.models  # noqa: F401,E402


config = context.config
target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))


def _require_postgresql(url):
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError(
            "alembic.postgresql.ini requires QUANTPULSE_DATABASE_URL to use PostgreSQL."
        )


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url").replace("%%", "%")
    _require_postgresql(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    url = config.get_main_option("sqlalchemy.url").replace("%%", "%")
    _require_postgresql(url)
    connectable = engine_from_config(
        {**config.get_section(config.config_ini_section, {}), "sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
