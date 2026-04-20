"""Alembic migration environment.

Wired to `monarch_ingest.models.Base.metadata` so autogenerate and
online migrations see the live ORM schema. URL resolution:

1. If the caller (e.g. `monarch_ingest.migrate`) has set
   `sqlalchemy.url` on the config, use that.
2. Otherwise fall back to `monarch_ingest.db.get_db_url()` which
   honors `MONARCH_DB_URL` env var.

`render_as_batch=True` is required for SQLite — without it, ALTER
TABLE-style migrations (rename/drop/type-change) silently fail.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from monarch_ingest.db import get_db_url
from monarch_ingest.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_db_url())


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Note: this engine bypasses `make_engine()`'s connect-event listener
    # that flips `PRAGMA foreign_keys = ON`. Schema migrations don't
    # insert/update rows, so this is harmless today. Any future data
    # migration that moves FK references should enable the pragma
    # explicitly before DML.
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # `compare_type` / `compare_server_default` must match the
        # drift-detection test (tests/integration/test_migrations.py);
        # keeping them in sync means autogenerate catches the same
        # divergences the test asserts against.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
