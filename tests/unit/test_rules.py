"""Unit tests for `monarch_ingest.rules`.

Pure in-memory: builds a couple of `Rule` rows via the fixture
`session`, flushes, then exercises `apply_all` / `apply_to_ids`.
No importer involvement; the rewrite logic is DB-independent.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from monarch_ingest.models import Account, Category, ImportRun, Merchant, Rule, Transaction
from monarch_ingest.rules import (
    InvalidRuleError,
    apply_all,
    apply_to_ids,
    validate_kind,
    validate_pattern,
)


@pytest.fixture
def account_id(session: Session) -> int:
    account = Account(monarch_name="Checking")
    session.add(account)
    session.flush()
    return account.id


@pytest.fixture
def import_run(session: Session) -> int:
    run = ImportRun(
        file_type="transactions",
        source_filename_hash="h-test",
        schema_fingerprint="fp-test",
        row_count=0,
        started_at=dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
    )
    session.add(run)
    session.flush()
    return run.id


def _merchant(session: Session, canonical: str) -> Merchant:
    m = Merchant(canonical_name=canonical)
    session.add(m)
    session.flush()
    return m


def _category(session: Session, name: str) -> Category:
    c = Category(name=name)
    session.add(c)
    session.flush()
    return c


def _txn(
    session: Session,
    *,
    statement: str,
    import_id: int,
    account_id: int,
    content_hash: str,
    merchant_id: int | None = None,
    category_id: int | None = None,
) -> Transaction:
    t = Transaction(
        date=dt.date(2025, 1, 15),
        amount_cents=-1000,
        account_id=account_id,
        merchant_id=merchant_id,
        category_id=category_id,
        original_statement=statement,
        notes="",
        tags="",
        content_hash=content_hash,
        import_id=import_id,
    )
    session.add(t)
    session.flush()
    return t


class TestValidatePattern:
    def test_accepts_valid_regex(self) -> None:
        validate_pattern(r"STARBUCKS.*\d+")

    def test_rejects_invalid_regex(self) -> None:
        with pytest.raises(InvalidRuleError, match="invalid regex"):
            validate_pattern(r"unclosed[group")

    def test_rejects_invalid_kind(self) -> None:
        with pytest.raises(InvalidRuleError, match="kind must be"):
            validate_kind("bogus")

    def test_accepts_valid_kind(self) -> None:
        validate_kind("merchant")
        validate_kind("category")


class TestApplyAll:
    def test_merchant_rewrite_by_statement_match(
        self, session: Session, import_run: int, account_id: int
    ) -> None:
        starbucks = _merchant(session, "Starbucks")
        _txn(
            session,
            statement="SBUX #1234 SEATTLE WA",
            import_id=import_run,
            account_id=account_id,
            content_hash="h-sbux",
        )
        session.add(Rule(kind="merchant", pattern=r"SBUX", target_id=starbucks.id))
        session.flush()

        changed = apply_all(session)
        session.flush()

        assert changed == 1
        t = session.scalars(select(Transaction)).one()
        assert t.merchant_id == starbucks.id

    def test_category_rewrite(self, session: Session, import_run: int, account_id: int) -> None:
        dining = _category(session, "Dining")
        _txn(
            session,
            statement="CHIPOTLE #0042",
            import_id=import_run,
            account_id=account_id,
            content_hash="h-chipotle",
        )
        session.add(Rule(kind="category", pattern=r"chipotle", target_id=dining.id))
        session.flush()

        apply_all(session)

        t = session.scalars(select(Transaction)).one()
        assert t.category_id == dining.id

    def test_priority_first_match_wins(
        self, session: Session, import_run: int, account_id: int
    ) -> None:
        m_starbucks = _merchant(session, "Starbucks")
        m_coffee = _merchant(session, "Generic Coffee")
        _txn(
            session,
            statement="COFFEE STARBUCKS #99",
            import_id=import_run,
            account_id=account_id,
            content_hash="h-coffee",
        )
        # Both rules match; lower priority = higher precedence.
        session.add(
            Rule(kind="merchant", pattern=r"STARBUCKS", target_id=m_starbucks.id, priority=10)
        )
        session.add(Rule(kind="merchant", pattern=r"COFFEE", target_id=m_coffee.id, priority=50))
        session.flush()

        apply_all(session)

        t = session.scalars(select(Transaction)).one()
        assert t.merchant_id == m_starbucks.id

    def test_inactive_rule_is_skipped(
        self, session: Session, import_run: int, account_id: int
    ) -> None:
        starbucks = _merchant(session, "Starbucks")
        _txn(
            session,
            statement="STARBUCKS",
            import_id=import_run,
            account_id=account_id,
            content_hash="h-inactive",
        )
        session.add(
            Rule(kind="merchant", pattern=r"STARBUCKS", target_id=starbucks.id, active=False)
        )
        session.flush()

        changed = apply_all(session)

        assert changed == 0
        t = session.scalars(select(Transaction)).one()
        assert t.merchant_id is None

    def test_no_change_does_not_count(
        self, session: Session, import_run: int, account_id: int
    ) -> None:
        starbucks = _merchant(session, "Starbucks")
        _txn(
            session,
            statement="STARBUCKS",
            import_id=import_run,
            account_id=account_id,
            merchant_id=starbucks.id,
            content_hash="h-nochange",
        )
        session.add(Rule(kind="merchant", pattern=r"STARBUCKS", target_id=starbucks.id))
        session.flush()

        # Transaction already points at the target merchant — applying
        # the rule is a no-op and must NOT bump the change counter.
        changed = apply_all(session)
        assert changed == 0

    def test_both_kinds_count_toward_total(
        self, session: Session, import_run: int, account_id: int
    ) -> None:
        starbucks = _merchant(session, "Starbucks")
        dining = _category(session, "Dining")
        _txn(
            session,
            statement="STARBUCKS",
            import_id=import_run,
            account_id=account_id,
            content_hash="h-both",
        )
        session.add(Rule(kind="merchant", pattern=r"STARBUCKS", target_id=starbucks.id))
        session.add(Rule(kind="category", pattern=r"STARBUCKS", target_id=dining.id))
        session.flush()

        changed = apply_all(session)

        # One txn, two fields rewritten = 2.
        assert changed == 2


class TestOrphanTarget:
    def test_deleted_merchant_rule_is_silently_skipped(
        self, session: Session, import_run: int, account_id: int
    ) -> None:
        # Rule points at a merchant that gets deleted before apply.
        # `_load_rules` joins against merchant, so the orphan rule
        # drops out and the transaction's merchant_id stays None —
        # no dangling FK write, no IntegrityError at commit.
        starbucks = _merchant(session, "Starbucks")
        _txn(
            session,
            statement="STARBUCKS",
            import_id=import_run,
            account_id=account_id,
            content_hash="h-orphan",
        )
        rule = Rule(kind="merchant", pattern=r"STARBUCKS", target_id=starbucks.id)
        session.add(rule)
        session.flush()

        session.delete(starbucks)
        session.flush()

        changed = apply_all(session)

        assert changed == 0
        t = session.scalars(select(Transaction)).one()
        assert t.merchant_id is None


class TestApplyToIds:
    def test_only_rewrites_listed_txns(
        self, session: Session, import_run: int, account_id: int
    ) -> None:
        starbucks = _merchant(session, "Starbucks")
        t1 = _txn(
            session,
            statement="STARBUCKS #1",
            import_id=import_run,
            account_id=account_id,
            content_hash="h-t1",
        )
        _txn(
            session,
            statement="STARBUCKS #2",
            import_id=import_run,
            account_id=account_id,
            content_hash="h-t2",
        )
        session.add(Rule(kind="merchant", pattern=r"STARBUCKS", target_id=starbucks.id))
        session.flush()

        changed = apply_to_ids(session, [t1.id])

        assert changed == 1
        t1_reloaded = session.get(Transaction, t1.id)
        assert t1_reloaded is not None
        assert t1_reloaded.merchant_id == starbucks.id
        # The un-listed txn must be untouched.
        all_txns = list(session.scalars(select(Transaction)).all())
        other = next(t for t in all_txns if t.id != t1.id)
        assert other.merchant_id is None

    def test_empty_id_list_is_noop(self, session: Session) -> None:
        assert apply_to_ids(session, []) == 0
