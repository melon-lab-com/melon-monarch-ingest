"""Schema-shape tests for `monarch_ingest.models`.

Verifies the declarative schema matches plan §2 and that the key
constraints (UNIQUE content_hash, composite PK on balance_snapshot, FK
presence, CHECK on import_run.file_type) are enforced by SQLite.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from monarch_ingest.db import make_engine
from monarch_ingest.models import (
    Account,
    BalanceSnapshot,
    Base,
    ImportRun,
    Transaction,
)

EXPECTED_TABLES = {
    "owner",
    "account",
    "account_alias",
    "category",
    "category_alias",
    "merchant",
    "merchant_alias",
    "transaction",
    "balance_snapshot",
    "import_run",
    "raw_import_row",
    "rule",
}


def test_all_expected_tables_present() -> None:
    assert {t.name for t in Base.metadata.sorted_tables} == EXPECTED_TABLES


def _seed_account_and_import_run(session: Session) -> tuple[Account, ImportRun]:
    account = Account(monarch_name="Checking", mask="9999")
    run = ImportRun(
        file_type="transactions",
        source_filename_hash="deadbeef",
        schema_fingerprint="cafebabe",
        started_at=dt.datetime.now(dt.UTC),
    )
    session.add_all([account, run])
    session.flush()
    return account, run


def test_transaction_content_hash_is_unique(session: Session) -> None:
    account, run = _seed_account_and_import_run(session)
    session.add(
        Transaction(
            date=dt.date(2025, 1, 1),
            amount_cents=-475,
            account_id=account.id,
            content_hash="abc123",
            import_id=run.id,
        )
    )
    session.flush()

    session.add(
        Transaction(
            date=dt.date(2025, 2, 1),
            amount_cents=-500,
            account_id=account.id,
            content_hash="abc123",
            import_id=run.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_balance_snapshot_has_composite_pk(session: Session) -> None:
    account, run = _seed_account_and_import_run(session)
    session.add(
        BalanceSnapshot(
            date=dt.date(2025, 1, 1),
            account_id=account.id,
            balance_cents=1_250_000,
            import_id=run.id,
        )
    )
    session.flush()

    session.add(
        BalanceSnapshot(
            date=dt.date(2025, 1, 1),
            account_id=account.id,
            balance_cents=1_300_000,
            import_id=run.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_balance_snapshot_allows_same_date_different_account(session: Session) -> None:
    a1 = Account(monarch_name="Checking", mask="9999")
    a2 = Account(monarch_name="Savings", mask="2222")
    run = ImportRun(
        file_type="balances",
        source_filename_hash="f00d",
        schema_fingerprint="ba5e",
        started_at=dt.datetime.now(dt.UTC),
    )
    session.add_all([a1, a2, run])
    session.flush()

    session.add_all(
        [
            BalanceSnapshot(
                date=dt.date(2025, 1, 1),
                account_id=a1.id,
                balance_cents=1_250_000,
                import_id=run.id,
            ),
            BalanceSnapshot(
                date=dt.date(2025, 1, 1),
                account_id=a2.id,
                balance_cents=4_500_000,
                import_id=run.id,
            ),
        ]
    )
    session.flush()


def test_account_mask_is_not_unique(session: Session) -> None:
    # ADR-0007: `UNIQUE(mask)` was dropped. Monarch ships joint cards
    # with a shared last-4 under different names, so two accounts
    # may share a mask.
    session.add_all(
        [
            Account(monarch_name="Checking A", mask="9999"),
            Account(monarch_name="Checking B", mask="9999"),
        ]
    )
    session.flush()


def test_account_allows_multiple_null_masks(session: Session) -> None:
    # Manual-valuation accounts (rental property, etc.) have no mask.
    session.add_all(
        [
            Account(
                monarch_name="Rental A",
                mask=None,
                is_manual_valuation=True,
            ),
            Account(
                monarch_name="Rental B",
                mask=None,
                is_manual_valuation=True,
            ),
        ]
    )
    session.flush()


def test_import_run_file_type_check_constraint(session: Session) -> None:
    session.add(
        ImportRun(
            file_type="bogus",
            source_filename_hash="x",
            schema_fingerprint="y",
            started_at=dt.datetime.now(dt.UTC),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_import_run_accepts_both_valid_file_types(session: Session) -> None:
    now = dt.datetime.now(dt.UTC)
    session.add_all(
        [
            ImportRun(
                file_type="transactions",
                source_filename_hash="a",
                schema_fingerprint="b",
                started_at=now,
            ),
            ImportRun(
                file_type="balances",
                source_filename_hash="c",
                schema_fingerprint="d",
                started_at=now,
            ),
        ]
    )
    session.flush()


def test_foreign_key_enforcement_is_enabled(session: Session) -> None:
    # SQLite FK constraints require `PRAGMA foreign_keys = ON`; `make_engine`
    # sets it on every connection. Bogus FK → IntegrityError, not silent.
    session.add(
        Transaction(
            date=dt.date(2025, 1, 1),
            amount_cents=-100,
            account_id=99999,
            content_hash="orphan",
            import_id=99999,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_db_session_scope_commits_and_rolls_back() -> None:
    from monarch_ingest.db import session_scope

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with session_scope(engine) as s:
        s.add(Account(monarch_name="Committed", mask="1111"))

    with session_scope(engine) as s:
        assert s.query(Account).filter_by(monarch_name="Committed").one() is not None

    with pytest.raises(RuntimeError), session_scope(engine) as s:
        s.add(Account(monarch_name="RolledBack", mask="2222"))
        s.flush()
        raise RuntimeError("boom")

    with session_scope(engine) as s:
        assert s.query(Account).filter_by(monarch_name="RolledBack").one_or_none() is None
