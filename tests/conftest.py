"""Shared pytest fixtures.

The `session` fixture here replaces per-file duplicates that diverged
slightly during M2. It uses a tmp-file SQLite rather than `:memory:`
because the integration tests need a file URL anyway; the speed
difference is negligible for our scale.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from monarch_ingest.db import make_engine
from monarch_ingest.models import Base


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine, expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()
