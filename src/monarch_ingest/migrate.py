"""Programmatic Alembic wrapper for `monarch_ingest`.

Keeps the CLI and tests from needing to shell out to the `alembic`
binary. Resolves `alembic.ini` and the `migrations/` script dir
relative to the repo root; when the ingest lib is eventually packaged
as a public wheel this will switch to `importlib.resources`.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from monarch_ingest.db import get_db_url, make_engine


def _repo_root() -> Path:
    # src/monarch_ingest/migrate.py → repo root is three parents up.
    # When the package is installed as a wheel (future — M7 public split)
    # this heuristic breaks; `alembic.ini` won't be next to site-packages.
    # Until then, catch the mis-resolution early with a clear error.
    root = Path(__file__).resolve().parent.parent.parent
    if not (root / "alembic.ini").exists():
        raise RuntimeError(
            f"alembic.ini not found at {root}. "
            "monarch_ingest must be installed from source (editable) "
            "until the M7 split moves migrations to importlib.resources."
        )
    return root


def _alembic_config(url: str | None = None) -> Config:
    root = _repo_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
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
