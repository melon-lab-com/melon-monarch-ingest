"""Database engine and session factory for `monarch_ingest`.

Sync SQLAlchemy 2.0 engine. The DB URL is env-driven (`MONARCH_DB_URL`);
default is a local SQLite file. See ADR-0003 for the sync vs async choice.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DB_URL = "sqlite:///./monarch.db"


def get_db_url(override: str | None = None) -> str:
    """Return the DB URL: explicit override → env var → default file."""
    if override is not None:
        return override
    return os.environ.get("MONARCH_DB_URL", DEFAULT_DB_URL)


def make_engine(url: str | None = None) -> Engine:
    """Build an Engine for the given URL (or the resolved default).

    For SQLite, FK enforcement is off by default; we flip it on via a
    `PRAGMA foreign_keys = ON` fired on every new connection. Without it,
    the `ForeignKey(...)` declarations in `models.core` are documentation
    only and orphaned rows are permitted.
    """
    engine = create_engine(get_db_url(url), future=True)
    if engine.dialect.name == "sqlite":
        _enable_sqlite_foreign_keys(engine)
    return engine


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn: Any, _: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Context-managed session with commit on exit, rollback on exception."""
    session = make_session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
