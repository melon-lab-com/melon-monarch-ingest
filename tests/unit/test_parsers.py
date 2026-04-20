"""Tests for the CSV parsers: row schemas and the file-level reader."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from pydantic import ValidationError

from monarch_ingest.parsers import (
    BALANCE_SCHEMA_FINGERPRINT,
    TRANSACTION_SCHEMA_FINGERPRINT,
    BalanceRow,
    SchemaMismatchError,
    TransactionRow,
    extract_mask,
    parse_balances,
    parse_transactions,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestExtractMask:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("CHECKING (...9999)", "9999"),
            ("CREDIT CARD (...1111) Test Card", "1111"),
            ("SAVINGS (...2222)", "2222"),
            ("BROKERAGE (...3333)", "3333"),
        ],
    )
    def test_extracts_last_4(self, raw: str, expected: str) -> None:
        assert extract_mask(raw) == expected

    def test_no_mask_returns_none(self) -> None:
        assert extract_mask("Rental Property at Fake Address") is None

    def test_unicode_ellipsis_rejected(self) -> None:
        # Guard: we only accept ASCII "..." — Unicode ellipsis would
        # silently produce None, which is a signal to add a fixture
        # and bump the regex.
        assert extract_mask("Account (\u20269999)") is None

    def test_non_digit_mask_returns_none(self) -> None:
        # `(...XXXX)` shouldn't produce a mask; the importer will
        # route these to unmatched_names for the operator to review.
        assert extract_mask("Account (...XXXX)") is None

    def test_first_mask_wins_when_multiple(self) -> None:
        # Unlikely in practice, but pin the behavior so an accidental
        # regex flip (e.g. switching to `findall()[-1]`) is caught.
        assert extract_mask("Weird (...1111) (...2222)") == "1111"


class TestTransactionRow:
    def test_parses_expense(self) -> None:
        row = TransactionRow.model_validate(
            {
                "Date": "2025-01-02",
                "Merchant": "Acme Coffee",
                "Category": "Restaurants & Bars",
                "Account": "CREDIT CARD (...1111) Test Card",
                "Original Statement": "ACME COFFEE #42",
                "Notes": "",
                "Amount": "-4.75",
                "Tags": "",
                "Owner": "Alice",
            }
        )
        assert row.date == dt.date(2025, 1, 2)
        assert row.amount_cents == -475
        assert row.account_mask == "1111"
        assert row.original_statement == "ACME COFFEE #42"
        assert row.notes == ""
        assert row.tags == ""

    def test_integer_amount(self) -> None:
        # A whole-number "Amount" string should still round-trip to cents.
        row = TransactionRow.model_validate(
            {
                "Date": "2025-01-05",
                "Merchant": "Synthetic",
                "Category": "Paycheck",
                "Account": "CHECKING (...9999)",
                "Original Statement": "PAYROLL",
                "Notes": "",
                "Amount": "3500",
                "Tags": "",
                "Owner": "Alice",
            }
        )
        assert row.amount_cents == 350000

    def test_rental_account_has_no_mask(self) -> None:
        row = TransactionRow.model_validate(
            {
                "Date": "2025-02-10",
                "Merchant": "Rental Tenant",
                "Category": "Rental",
                "Account": "Rental Property at Fake Address",
                "Original Statement": "RENT PAYMENT",
                "Notes": "",
                "Amount": "2200",
                "Tags": "rental",
                "Owner": "Shared",
            }
        )
        assert row.account_mask is None

    def test_rejects_sub_cent_precision(self) -> None:
        with pytest.raises(ValidationError) as exc:
            TransactionRow.model_validate(
                {
                    "Date": "2025-01-01",
                    "Merchant": "x",
                    "Category": "y",
                    "Account": "CHECKING (...9999)",
                    "Original Statement": "",
                    "Notes": "",
                    "Amount": "1.234",
                    "Tags": "",
                    "Owner": "Alice",
                }
            )
        assert "sub-cent" in str(exc.value)

    def test_rejects_non_numeric_amount(self) -> None:
        with pytest.raises(ValidationError):
            TransactionRow.model_validate(
                {
                    "Date": "2025-01-01",
                    "Merchant": "x",
                    "Category": "y",
                    "Account": "CHECKING (...9999)",
                    "Original Statement": "",
                    "Notes": "",
                    "Amount": "not-a-number",
                    "Tags": "",
                    "Owner": "Alice",
                }
            )

    def test_rejects_bool_amount(self) -> None:
        # Without the explicit bool guard, `True` → Decimal("True") raises
        # — but we want a clear "invalid amount" message, not a
        # confusing Pydantic/Decimal error. Bool is the load-bearing
        # case: `bool` is a subclass of `int` in Python.
        with pytest.raises(ValidationError) as exc:
            TransactionRow.model_validate(
                {
                    "Date": "2025-01-01",
                    "Merchant": "x",
                    "Category": "y",
                    "Account": "CHECKING (...9999)",
                    "Original Statement": "",
                    "Notes": "",
                    "Amount": True,
                    "Tags": "",
                    "Owner": "Alice",
                }
            )
        assert "invalid amount" in str(exc.value)

    def test_none_notes_becomes_empty_string(self) -> None:
        # DictReader with a missing key yields None — normalize to "".
        row = TransactionRow.model_validate(
            {
                "Date": "2025-01-01",
                "Merchant": "x",
                "Category": "y",
                "Account": "CHECKING (...9999)",
                "Original Statement": None,
                "Notes": None,
                "Amount": "1.00",
                "Tags": None,
                "Owner": "Alice",
            }
        )
        assert row.original_statement == ""
        assert row.notes == ""
        assert row.tags == ""


class TestBalanceRow:
    def test_parses_positive_balance(self) -> None:
        row = BalanceRow.model_validate(
            {
                "Date": "2025-01-01",
                "Balance": "12500.00",
                "Account": "CHECKING (...9999)",
            }
        )
        assert row.date == dt.date(2025, 1, 1)
        assert row.balance_cents == 1_250_000
        assert row.account_mask == "9999"

    def test_parses_negative_balance(self) -> None:
        row = BalanceRow.model_validate(
            {
                "Date": "2025-01-01",
                "Balance": "-850.00",
                "Account": "CREDIT CARD (...1111) Test Card",
            }
        )
        assert row.balance_cents == -85_000

    def test_rental_balance_has_no_mask(self) -> None:
        row = BalanceRow.model_validate(
            {
                "Date": "2025-01-01",
                "Balance": "275000.00",
                "Account": "Rental Property at Fake Address",
            }
        )
        assert row.account_mask is None


class TestFixtureRoundtrip:
    def test_all_transaction_fixture_rows_parse(self) -> None:
        rows = list(parse_transactions(FIXTURES_DIR / "sample_transactions.csv"))
        assert len(rows) == 40
        assert all(isinstance(r.amount_cents, int) for r in rows)
        # Inflow + outflow both present.
        assert any(r.amount_cents > 0 for r in rows)
        assert any(r.amount_cents < 0 for r in rows)

    def test_all_balance_fixture_rows_parse(self) -> None:
        rows = list(parse_balances(FIXTURES_DIR / "sample_balances.csv"))
        assert len(rows) == 30
        rental = [r for r in rows if r.raw_account.startswith("Rental")]
        # 6 rental snapshots: 2024-01-01, 2024-12-31 (year-end),
        # 2025-01-01, 2025-02-01, 2025-03-01, 2025-12-31 (year-end).
        assert len(rental) == 6
        assert all(r.account_mask is None for r in rental)


class TestSchemaMismatch:
    def test_missing_column_raises_with_diff(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.csv"
        bad.write_text("Date,Balance\n2025-01-01,100\n", encoding="utf-8")
        with pytest.raises(SchemaMismatchError) as exc:
            list(parse_balances(bad))
        assert "missing columns" in str(exc.value)
        assert "Account" in str(exc.value)

    def test_unexpected_column_raises_with_diff(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.csv"
        bad.write_text("Date,Balance,Account,Extra\n2025-01-01,100,CHK,x\n", encoding="utf-8")
        with pytest.raises(SchemaMismatchError) as exc:
            list(parse_balances(bad))
        assert "unexpected columns" in str(exc.value)
        assert "Extra" in str(exc.value)

    def test_lowercased_headers_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.csv"
        bad.write_text("date,balance,account\n2025-01-01,100,CHK\n", encoding="utf-8")
        with pytest.raises(SchemaMismatchError):
            list(parse_balances(bad))

    def test_exposes_expected_fingerprint(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.csv"
        bad.write_text("Wrong\n", encoding="utf-8")
        with pytest.raises(SchemaMismatchError) as exc:
            list(parse_balances(bad))
        assert exc.value.expected_fingerprint == BALANCE_SCHEMA_FINGERPRINT

    def test_duplicate_header_triggers_casing_branch(self, tmp_path: Path) -> None:
        # DictReader keeps the second occurrence of a duplicated header,
        # so the set difference is empty but the fingerprint still
        # differs from the expected. Exercises the "casing or duplicate
        # mismatch" branch of SchemaMismatchError.
        bad = tmp_path / "bad.csv"
        bad.write_text(
            "Date,Balance,Account,Account\n2025-01-01,100,CHK,CHK\n",
            encoding="utf-8",
        )
        with pytest.raises(SchemaMismatchError) as exc:
            list(parse_balances(bad))
        msg = str(exc.value)
        assert "casing or duplicate mismatch" in msg


class TestFingerprintConstants:
    def test_transaction_constant_matches_hashing(self) -> None:
        # Double-checks that parsers and consumers (importer, CLI) see
        # the same fingerprint so schema-drift detection is coherent.
        from monarch_ingest.hashing import schema_fingerprint

        assert (
            schema_fingerprint(
                [
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
            )
            == TRANSACTION_SCHEMA_FINGERPRINT
        )
