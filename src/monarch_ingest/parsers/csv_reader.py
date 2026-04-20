"""Streaming CSV readers with schema-fingerprint guard.

Refuses any file whose header row doesn't match the expected
fingerprint (ADR-0002), surfacing a diff so the operator can see what
changed in the Monarch export format.
"""

from __future__ import annotations

from collections.abc import Iterator
from csv import DictReader
from pathlib import Path

from monarch_ingest.hashing import schema_fingerprint
from monarch_ingest.parsers.schemas import BalanceRow, TransactionRow

_TRANSACTION_HEADERS = [
    "Date",
    "Merchant",
    "Category",
    "Account",
    "Original Statement",
    "Notes",
    "Amount",
    "Tags",
    "Owner",
]
_BALANCE_HEADERS = ["Date", "Balance", "Account"]

TRANSACTION_SCHEMA_FINGERPRINT = schema_fingerprint(_TRANSACTION_HEADERS)
BALANCE_SCHEMA_FINGERPRINT = schema_fingerprint(_BALANCE_HEADERS)


class SchemaMismatchError(ValueError):
    """Raised when a CSV's header row doesn't match the expected schema.

    Carries both the expected fingerprint and the actual headers so
    callers (CLI) can print a helpful diff.
    """

    def __init__(
        self,
        *,
        expected_fingerprint: str,
        expected_headers: list[str],
        got_headers: list[str],
    ) -> None:
        self.expected_fingerprint = expected_fingerprint
        self.expected_headers = expected_headers
        self.got_headers = got_headers
        missing = sorted(set(expected_headers) - set(got_headers))
        unexpected = sorted(set(got_headers) - set(expected_headers))
        parts = [f"CSV schema mismatch (expected fingerprint {expected_fingerprint[:12]}…)."]
        if missing:
            parts.append(f"  missing columns: {missing}")
        if unexpected:
            parts.append(f"  unexpected columns: {unexpected}")
        if not missing and not unexpected:
            parts.append(f"  got headers: {got_headers} (casing or duplicate mismatch)")
        super().__init__("\n".join(parts))


def _read_rows(
    path: Path, expected_fingerprint: str, expected_headers: list[str]
) -> list[dict[str, str]]:
    # Materialize rows eagerly so the file handle is closed on return.
    # Monarch exports are ~50K rows; memory impact is negligible and
    # eliminates the generator-close-semantics concern under non-
    # refcounting GC (PyPy) or when the caller breaks mid-iteration.
    with path.open(newline="", encoding="utf-8") as f:
        reader = DictReader(f)
        headers = list(reader.fieldnames or [])
        if schema_fingerprint(headers) != expected_fingerprint:
            raise SchemaMismatchError(
                expected_fingerprint=expected_fingerprint,
                expected_headers=expected_headers,
                got_headers=headers,
            )
        return list(reader)


def parse_transactions(path: Path) -> Iterator[TransactionRow]:
    """Yield `TransactionRow`s from a Monarch transactions CSV.

    Raises `SchemaMismatchError` if the header row's fingerprint
    doesn't match `TRANSACTION_SCHEMA_FINGERPRINT`.
    """
    for row in _read_rows(path, TRANSACTION_SCHEMA_FINGERPRINT, _TRANSACTION_HEADERS):
        yield TransactionRow.model_validate(row)


def parse_balances(path: Path) -> Iterator[BalanceRow]:
    """Yield `BalanceRow`s from a Monarch balances CSV."""
    for row in _read_rows(path, BALANCE_SCHEMA_FINGERPRINT, _BALANCE_HEADERS):
        yield BalanceRow.model_validate(row)
