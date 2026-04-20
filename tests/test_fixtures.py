"""Smoke tests for synthetic CSV fixtures.

Intentionally minimal: confirms the fixtures exist, parse as CSV with the
expected headers, and have enough rows to be useful. Real parsing logic will
land in Milestone 2 under `src/monarch_ingest/`.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

EXPECTED_TRANSACTION_HEADERS = [
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
EXPECTED_BALANCE_HEADERS = ["Date", "Balance", "Account"]


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames is not None, f"No header in {path}"
        return list(reader.fieldnames), list(reader)


def test_transactions_fixture_has_expected_schema() -> None:
    headers, rows = _read_csv(FIXTURES_DIR / "sample_transactions.csv")
    assert headers == EXPECTED_TRANSACTION_HEADERS
    assert len(rows) >= 15, "transactions fixture should have enough rows for meaningful tests"


def test_balances_fixture_has_expected_schema() -> None:
    headers, rows = _read_csv(FIXTURES_DIR / "sample_balances.csv")
    assert headers == EXPECTED_BALANCE_HEADERS
    assert len(rows) >= 10


def test_transactions_fixture_covers_edge_cases() -> None:
    _, rows = _read_csv(FIXTURES_DIR / "sample_transactions.csv")

    amounts = [float(r["Amount"]) for r in rows]
    assert any(a > 0 for a in amounts), "should include inflow"
    assert any(a < 0 for a in amounts), "should include outflow"

    owners = {r["Owner"] for r in rows}
    assert "Shared" in owners, "should include at least one Shared row"
    assert len(owners - {"Shared"}) >= 2, "should include multiple per-owner rows"

    statements = [r["Original Statement"] for r in rows]
    assert any("," in s for s in statements), "should include a row with commas in a quoted field"

    duplicates = sum(1 for r in rows if r["Merchant"] == "Acme Coffee")
    assert duplicates >= 2, "repeated merchant needed for future dedup tests"


def test_balances_fixture_includes_negative_balance() -> None:
    _, rows = _read_csv(FIXTURES_DIR / "sample_balances.csv")
    balances = [float(r["Balance"]) for r in rows]
    assert any(b < 0 for b in balances), "fixture should include a credit card / debt balance"


@pytest.mark.parametrize(
    "filename",
    ["sample_transactions.csv", "sample_balances.csv"],
)
def test_fixture_filename_does_not_trip_csv_guard(filename: str) -> None:
    """Meta-check: fixture names must not match Transactions_*.csv / Balances_*.csv.

    If this ever fails, the pre-commit guard will refuse to commit the file —
    which is the bug we're guarding against, not a false alarm to silence.
    """
    assert not filename.startswith(("Transactions_", "Balances_"))
