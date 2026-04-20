"""`monarch-ingest` CLI — three subcommands wrapping the importers.

Subcommands:
  - `transactions <file>`: import a Monarch transactions CSV.
  - `balances <file>`: import a Monarch balances CSV.
  - `status`: print import history (no write).

See ADR-0004 for the Typer-over-Click choice and the exit-code
contract (0=ok, 2=schema mismatch, 3=unmatched, 4=missing file).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Protocol

import typer
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from monarch_ingest.db import make_engine, session_scope
from monarch_ingest.importers import (
    ImportRunResult,
    UnmatchedNamesError,
    import_balances,
    import_transactions,
)
from monarch_ingest.migrate import current_revision, upgrade_head
from monarch_ingest.models import Category, ImportRun, Merchant, Rule
from monarch_ingest.parsers import SchemaMismatchError
from monarch_ingest.rules import (
    KIND_MERCHANT,
    InvalidRuleError,
    apply_all,
    validate_kind,
    validate_pattern,
)

# Exit codes beyond the 0/1 Typer defaults. Full contract documented
# in docs/decisions/0004-cli-typer.md.
EXIT_SCHEMA_MISMATCH = 2
EXIT_UNMATCHED = 3
EXIT_MISSING_FILE = 4


class _Importer(Protocol):
    def __call__(self, session: Session, path: Path, *, accept_new: bool) -> ImportRunResult: ...


app = typer.Typer(
    name="monarch-ingest",
    help="Import Monarch CSV exports into the local DB.",
    no_args_is_help=True,
)


DbUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--db-url",
        help="SQLAlchemy URL. Defaults to MONARCH_DB_URL env var, otherwise a local SQLite file.",
    ),
]
AcceptNewOpt = Annotated[
    bool,
    typer.Option(
        "--accept-new",
        help=(
            "Auto-create unknown accounts / categories / merchants / "
            "owners. Without this flag, unknowns abort the import."
        ),
    ),
]


def _check_file_exists(path: Path) -> None:
    if not path.exists():
        typer.echo(f"Error: CSV not found: {path}", err=True)
        raise typer.Exit(code=EXIT_MISSING_FILE)


@contextmanager
def _db_session(db_url: str | None) -> Generator[Session, None, None]:
    """Migrate to head, open a session, dispose the engine on exit.

    Centralises the upgrade_head → make_engine → session_scope →
    engine.dispose() sequence that every rules subcommand needs.
    """
    upgrade_head(db_url)
    engine = make_engine(db_url)
    try:
        with session_scope(engine) as session:
            yield session
    finally:
        engine.dispose()


def _run_import(
    importer: _Importer,
    path: Path,
    db_url: str | None,
    accept_new: bool,
) -> None:
    """Shared orchestration: migrate → import → print result."""
    _check_file_exists(path)

    upgrade_head(db_url)
    engine = make_engine(db_url)
    try:
        with session_scope(engine) as session:
            try:
                result = importer(session, path, accept_new=accept_new)
            except SchemaMismatchError as e:
                typer.echo(str(e), err=True)
                raise typer.Exit(code=EXIT_SCHEMA_MISMATCH) from None
            except UnmatchedNamesError as e:
                typer.echo(str(e), err=True)
                raise typer.Exit(code=EXIT_UNMATCHED) from None
    finally:
        engine.dispose()

    typer.echo(
        f"{result.file_type} import #{result.import_id}: "
        f"{result.new_rows} new, {result.dup_rows} dup "
        f"(of {result.row_count} rows)"
    )


@app.command()
def transactions(
    path: Annotated[Path, typer.Argument(help="Path to Monarch transactions CSV.")],
    db_url: DbUrlOpt = None,
    accept_new: AcceptNewOpt = False,
) -> None:
    """Import a Monarch transactions CSV (dedup on content_hash)."""
    _run_import(import_transactions, path, db_url, accept_new)


@app.command()
def balances(
    path: Annotated[Path, typer.Argument(help="Path to Monarch balances CSV.")],
    db_url: DbUrlOpt = None,
    accept_new: AcceptNewOpt = False,
) -> None:
    """Import a Monarch balances CSV (upsert on date + account_id)."""
    _run_import(import_balances, path, db_url, accept_new)


@app.command()
def status(db_url: DbUrlOpt = None) -> None:
    """Print migration state + recent import history.

    Read-only: does not auto-run migrations (so it's safe to invoke
    against a DB whose schema predates a library bump).
    """
    # Migration check first — fast, uses its own engine. If unmigrated,
    # skip opening a session engine we'd never use.
    rev = current_revision(db_url)
    if rev is None:
        typer.echo(
            "DB is unmigrated. Run `monarch-ingest transactions` "
            "or `balances` first to auto-apply migrations."
        )
        return

    typer.echo(f"Migration HEAD: {rev}")

    engine = make_engine(db_url)
    try:
        with session_scope(engine) as session:
            runs = (
                session.execute(select(ImportRun).order_by(desc(ImportRun.id)).limit(10))
                .scalars()
                .all()
            )
        if not runs:
            typer.echo("No imports recorded yet.")
            return

        typer.echo(f"\nLast {len(runs)} import(s):")
        for r in runs:
            finished = r.finished_at.isoformat() if r.finished_at else "IN-FLIGHT"
            typer.echo(
                f"  #{r.id} {r.file_type:<12} {r.row_count:>4} rows "
                f"({r.new_rows} new, {r.dup_rows} dup) @ {finished}"
            )
    finally:
        engine.dispose()


rules_app = typer.Typer(
    help="Manage regex rules that rewrite merchant / category on import.",
    no_args_is_help=True,
)
app.add_typer(rules_app, name="rules")


@rules_app.command("list")
def rules_list(db_url: DbUrlOpt = None) -> None:
    """Print active and inactive rules in priority order."""
    with _db_session(db_url) as session:
        all_rules = (
            session.execute(
                select(Rule).order_by(Rule.kind.asc(), Rule.priority.asc(), Rule.id.asc())
            )
            .scalars()
            .all()
        )
    if not all_rules:
        typer.echo("No rules defined.")
        return
    typer.echo(f"\n{len(all_rules)} rule(s):")
    for r in all_rules:
        flag = "on " if r.active else "off"
        typer.echo(
            f"  #{r.id} {flag} {r.kind:<9} p={r.priority:>4} "
            f"target={r.target_id:>4}  /{r.pattern}/"
        )


@rules_app.command("add")
def rules_add(
    kind: Annotated[str, typer.Argument(help="'merchant' or 'category'.")],
    pattern: Annotated[
        str,
        typer.Argument(help="Regex (case-insensitive) matched against original_statement."),
    ],
    target_id: Annotated[int, typer.Argument(help="Target merchant.id or category.id.")],
    priority: Annotated[
        int,
        typer.Option(help="Lower = higher priority. First match wins."),
    ] = 100,
    db_url: DbUrlOpt = None,
) -> None:
    """Add a rule. Validates the regex + target existence before insert."""
    try:
        validate_kind(kind)
        validate_pattern(pattern)
    except InvalidRuleError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    with _db_session(db_url) as session:
        target_model = Merchant if kind == KIND_MERCHANT else Category
        target = session.get(target_model, target_id)
        if target is None:
            typer.echo(f"Error: {kind} id {target_id} does not exist.", err=True)
            raise typer.Exit(code=1)
        rule = Rule(kind=kind, pattern=pattern, target_id=target_id, priority=priority)
        session.add(rule)
        session.flush()
        typer.echo(f"Added rule #{rule.id} ({kind} → {target_id}, priority {priority}).")


@rules_app.command("remove")
def rules_remove(
    rule_id: Annotated[int, typer.Argument(help="Rule id from `rules list`.")],
    db_url: DbUrlOpt = None,
) -> None:
    """Delete a rule by id."""
    with _db_session(db_url) as session:
        rule = session.get(Rule, rule_id)
        if rule is None:
            typer.echo(f"Error: rule #{rule_id} not found.", err=True)
            raise typer.Exit(code=1)
        session.delete(rule)
        typer.echo(f"Removed rule #{rule_id}.")


@rules_app.command("apply")
def rules_apply(db_url: DbUrlOpt = None) -> None:
    """Replay every active rule across the full transaction history.

    Useful after adding a rule or changing priorities. Writes happen
    under one commit, so a partial replay can't leave the DB in a
    mixed state.
    """
    with _db_session(db_url) as session:
        count = apply_all(session)
    typer.echo(f"Applied rules: {count} transaction field(s) rewritten.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
