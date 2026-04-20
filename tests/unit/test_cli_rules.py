"""CLI tests for `monarch-ingest rules {add,list,remove,apply}`.

Each test runs against a fresh SQLite file; `transactions` import
seeds the DB so `rules apply` has real rows to rewrite.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from monarch_ingest.cli import app
from monarch_ingest.db import make_engine, session_scope
from monarch_ingest.models import Merchant, Transaction

runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'cli-rules.db'}"


def _seed(tmp_path: Path) -> str:
    """Import the sample transactions so rules have rows to act on."""
    db_url = _db_url(tmp_path)
    result = runner.invoke(
        app,
        [
            "transactions",
            str(FIXTURES_DIR / "sample_transactions.csv"),
            "--db-url",
            db_url,
            "--accept-new",
        ],
    )
    assert result.exit_code == 0, result.stdout
    return db_url


class TestRulesAdd:
    def test_add_rejects_invalid_kind(self, tmp_path: Path) -> None:
        db_url = _seed(tmp_path)
        result = runner.invoke(
            app,
            ["rules", "add", "not-a-kind", "STARBUCKS", "1", "--db-url", db_url],
        )
        assert result.exit_code == 1
        assert "kind must be" in result.stdout + result.stderr

    def test_add_rejects_invalid_regex(self, tmp_path: Path) -> None:
        db_url = _seed(tmp_path)
        result = runner.invoke(
            app,
            ["rules", "add", "merchant", "unclosed[group", "1", "--db-url", db_url],
        )
        assert result.exit_code == 1
        assert "invalid regex" in result.stdout + result.stderr

    def test_add_rejects_unknown_target(self, tmp_path: Path) -> None:
        db_url = _seed(tmp_path)
        # id=99999 is guaranteed not to exist in the fresh DB.
        result = runner.invoke(
            app,
            ["rules", "add", "merchant", "STARBUCKS", "99999", "--db-url", db_url],
        )
        assert result.exit_code == 1
        assert "does not exist" in result.stdout + result.stderr

    def test_add_then_list_shows_the_rule(self, tmp_path: Path) -> None:
        db_url = _seed(tmp_path)
        # Get a valid merchant id from the seeded data.
        engine = make_engine(db_url)
        with session_scope(engine) as session:
            mid = session.scalars(select(Merchant.id).limit(1)).one()
        engine.dispose()

        add = runner.invoke(
            app,
            ["rules", "add", "merchant", "TEST-PATTERN", str(mid), "--db-url", db_url],
        )
        assert add.exit_code == 0, add.stdout
        assert "Added rule" in add.stdout

        listed = runner.invoke(app, ["rules", "list", "--db-url", db_url])
        assert listed.exit_code == 0
        assert "TEST-PATTERN" in listed.stdout
        assert "merchant" in listed.stdout


class TestRulesList:
    def test_list_empty_prints_friendly_message(self, tmp_path: Path) -> None:
        db_url = _seed(tmp_path)
        result = runner.invoke(app, ["rules", "list", "--db-url", db_url])
        assert result.exit_code == 0
        assert "No rules defined" in result.stdout


class TestRulesRemove:
    def test_remove_nonexistent_errors(self, tmp_path: Path) -> None:
        db_url = _seed(tmp_path)
        result = runner.invoke(app, ["rules", "remove", "4242", "--db-url", db_url])
        assert result.exit_code == 1
        assert "not found" in result.stdout + result.stderr


class TestRulesApply:
    def test_apply_replays_rule_over_history(self, tmp_path: Path) -> None:
        # Add a rule that matches every transaction (catch-all `.`) and
        # points them at an existing merchant. After `rules apply`,
        # every txn should now carry that merchant_id.
        db_url = _seed(tmp_path)
        engine = make_engine(db_url)
        with session_scope(engine) as session:
            mid = session.scalars(select(Merchant.id).limit(1)).one()
            has_txns = session.scalars(select(Transaction.id).limit(1)).first() is not None
        assert has_txns
        engine.dispose()

        add = runner.invoke(
            app,
            [
                "rules",
                "add",
                "merchant",
                ".",
                str(mid),
                "--priority",
                "1",
                "--db-url",
                db_url,
            ],
        )
        assert add.exit_code == 0, add.stdout

        applied = runner.invoke(app, ["rules", "apply", "--db-url", db_url])
        assert applied.exit_code == 0, applied.stdout
        assert "Applied rules" in applied.stdout

        engine = make_engine(db_url)
        with session_scope(engine) as session:
            wrong_merchant = session.execute(
                select(Transaction).where(Transaction.merchant_id != mid).limit(1)
            ).first()
        engine.dispose()
        # Every txn must now point at the catch-all rule's target.
        assert wrong_merchant is None
