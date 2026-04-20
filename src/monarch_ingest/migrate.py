"""Programmatic Alembic wrapper for `monarch_ingest`.

Keeps the CLI and tests from needing to shell out to the `alembic`
binary. `alembic.ini` + the `migrations/` script dir ship inside the
installed package (`src/monarch_ingest/alembic.ini` and
`src/monarch_ingest/migrations/`) so a wheel install works without a
source checkout.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from monarch_ingest.db import get_db_url, make_engine


def _package_dir() -> Path:
    """Path to the installed `monarch_ingest` package directory."""
    return Path(__file__).resolve().parent


def _alembic_config(url: str | None = None) -> Config:
    pkg = _package_dir()
    cfg = Config(str(pkg / "alembic.ini"))
    cfg.set_main_option("script_location", str(pkg / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_db_url(url))
    return cfg


def upgrade_head(url: str | None = None) -> None:
    """Run all pending migrations up to head against the given URL."""
    command.upgrade(_alembic_config(url), "head")


def current_revision(url: str | None = None) -> str | None:
    """Return the migration hash currently applied to the DB, or None."""
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
