"""Shared types and helpers for the importers."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

FileType = Literal["transactions", "balances"]


@dataclass(frozen=True)
class ImportRunResult:
    """Summary of a completed import run.

    Mirrors the audit `import_run` row with a thin typed surface for
    callers (CLI) that shouldn't have to reopen a session to see what
    happened.
    """

    import_id: int
    file_type: FileType
    row_count: int
    new_rows: int
    dup_rows: int
    started_at: dt.datetime
    finished_at: dt.datetime


def source_filename_hash(path: Path) -> str:
    """Return sha256 of the CSV's basename.

    The `import_run` audit records this instead of the full path so we
    don't leak the operator's directory structure.
    """
    return hashlib.sha256(path.name.encode("utf-8")).hexdigest()


@dataclass
class ResolveContext:
    """Per-import state carried through the alias resolvers.

    Unmatched raw names accumulate here when `accept_new=False`; the
    importer aborts the transaction if any were collected, printing
    them so the operator can decide whether to re-run with
    `--accept-new` or fix the CSV.

    `created_account_ids` holds account IDs created *during this
    import run*, which the mask-hint branch of `resolve_account`
    excludes so joint-card siblings on the same first import can't
    merge into each other. See ADR-0007.
    """

    accept_new: bool
    unmatched: list[str] = field(default_factory=list)
    created_account_ids: set[int] = field(default_factory=set)


class UnmatchedNamesError(ValueError):
    """Raised when the importer hit unknown names and `accept_new=False`.

    Carries the prefixed raw names (e.g. `"account: CHECKING (...9999)"`)
    so the CLI can format them into a clear message.
    """

    def __init__(self, unmatched: list[str]) -> None:
        self.unmatched = list(unmatched)
        super().__init__(
            f"{len(unmatched)} unmatched name(s); re-run with --accept-new "
            f"to auto-create or fix the CSV. First few: {unmatched[:5]}"
        )
