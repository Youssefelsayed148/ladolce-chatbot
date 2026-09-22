"""Alembic migration environment.

Reads the database URL from the DATABASE_URL env var and swaps the async driver
(+asyncpg) for a sync one (+psycopg) that Alembic's engine can use.

target_metadata is set from the app's ORM models (best-effort import below) so
`alembic revision --autogenerate` works; hand-written migrations don't need it.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Make the FastAPI app package importable so autogenerate can see the models'
# metadata. In the container the app lives at /app (PYTHONPATH=/app); locally it
# sits alongside this project at <repo>/api. Import is best-effort: hand-written
# migrations run fine without it, so a failure here must never block `upgrade`.
_api_dir = Path(__file__).resolve().parents[2] / "api"
if _api_dir.is_dir():
    sys.path.insert(0, str(_api_dir))

try:
    from app.core.db import Base
    import app.models  # noqa: F401  (registers tables on Base.metadata)

    target_metadata = Base.metadata
except Exception:  # pragma: no cover - autogenerate convenience only
    target_metadata = None


def _sync_database_url() -> str:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://ladolce:ladolce@db:5432/ladolce",
    )
    # Alembic runs synchronously; map the async driver to its sync counterpart.
    return url.replace("+asyncpg", "+psycopg")


config.set_main_option("sqlalchemy.url", _sync_database_url())


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
