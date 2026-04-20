"""CLI smoke tests via Typer's CliRunner."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from monarch_ingest.cli import (
    EXIT_MISSING_FILE,
    EXIT_SCHEMA_MISMATCH,
    EXIT_UNMATCHED,
    app,
)

runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

# Rich (Typer's help renderer) bolds option names by splitting them
# across ANSI style runs, so `"--accept-new" in stdout` fails even
# when the text is visually there. Strip ANSI escape sequences before
# substring checks.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'cli.db'}"


# Set COLUMNS wide so Rich doesn't wrap option names across lines.
_HELP_ENV = {"COLUMNS": "300", "NO_COLOR": "1"}


class TestHelp:
    def test_top_level_help(self) -> None:
        result = runner.invoke(app, ["--help"], env=_HELP_ENV)
        assert result.exit_code == 0
        out = _clean(result.stdout)
        assert "transactions" in out
        assert "balances" in out
        assert "status" in out

    def test_transactions_help(self) -> None:
        result = runner.invoke(app, ["transactions", "--help"], env=_HELP_ENV)
        assert result.exit_code == 0
        out = _clean(result.stdout)
        assert "--accept-new" in out
        assert "--db-url" in out


class TestStatus:
    def test_fresh_db_reports_unmigrated(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["status", "--db-url", _db_url(tmp_path)])
        assert result.exit_code == 0
        assert "unmigrated" in result.stdout

    def test_after_import_lists_runs(self, tmp_path: Path) -> None:
        db = _db_url(tmp_path)
        runner.invoke(
            app,
            [
                "transactions",
                str(FIXTURES_DIR / "sample_transactions.csv"),
                "--db-url",
                db,
                "--accept-new",
            ],
        )
        result = runner.invoke(app, ["status", "--db-url", db])
        assert result.exit_code == 0
        assert "Migration HEAD" in result.stdout
        assert "transactions" in result.stdout
        assert "40 new" in result.stdout


class TestTransactionsImport:
    def test_happy_path(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "transactions",
                str(FIXTURES_DIR / "sample_transactions.csv"),
                "--db-url",
                _db_url(tmp_path),
                "--accept-new",
            ],
        )
        assert result.exit_code == 0
        assert "40 new" in result.stdout
        assert "0 dup" in result.stdout

    def test_missing_file_exit_code(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "transactions",
                str(tmp_path / "nonexistent.csv"),
                "--db-url",
                _db_url(tmp_path),
            ],
        )
        assert result.exit_code == EXIT_MISSING_FILE
        assert "not found" in result.stderr

    def test_unmatched_without_accept_new_exits_3(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "transactions",
                str(FIXTURES_DIR / "sample_transactions.csv"),
                "--db-url",
                _db_url(tmp_path),
            ],
        )
        assert result.exit_code == EXIT_UNMATCHED
        assert "unmatched" in result.stderr

    def test_schema_mismatch_exits_2(self, tmp_path: Path) -> None:
        bad = tmp_path / "wrong_schema.csv"
        bad.write_text("Date,Balance\n2025-01-01,100\n", encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "transactions",
                str(bad),
                "--db-url",
                _db_url(tmp_path),
                "--accept-new",
            ],
        )
        assert result.exit_code == EXIT_SCHEMA_MISMATCH
        assert "schema mismatch" in result.stderr


class TestBalancesImport:
    def test_happy_path(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "balances",
                str(FIXTURES_DIR / "sample_balances.csv"),
                "--db-url",
                _db_url(tmp_path),
                "--accept-new",
            ],
        )
        assert result.exit_code == 0
        assert "30 new" in result.stdout

    def test_missing_file_exit_code(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "balances",
                str(tmp_path / "nonexistent.csv"),
                "--db-url",
                _db_url(tmp_path),
            ],
        )
        assert result.exit_code == EXIT_MISSING_FILE

    def test_unmatched_without_accept_new_exits_3(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "balances",
                str(FIXTURES_DIR / "sample_balances.csv"),
                "--db-url",
                _db_url(tmp_path),
            ],
        )
        assert result.exit_code == EXIT_UNMATCHED

    def test_schema_mismatch_exits_2(self, tmp_path: Path) -> None:
        bad = tmp_path / "wrong_balance_schema.csv"
        bad.write_text(
            "Date,Merchant,Amount\n2025-01-01,x,1.00\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "balances",
                str(bad),
                "--db-url",
                _db_url(tmp_path),
                "--accept-new",
            ],
        )
        assert result.exit_code == EXIT_SCHEMA_MISMATCH
