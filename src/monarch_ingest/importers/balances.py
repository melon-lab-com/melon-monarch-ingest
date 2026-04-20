"""Balances CSV importer.

Upsert semantics on `(date, account_id)` — later export wins. Monarch
can retroactively correct historical balances, so re-importing a file
with a changed balance updates the existing row in place.

Audit counter semantics for M2:
  - `new_rows` = rows where `(date, account_id)` did not previously exist.
  - `dup_rows` = rows where `(date, account_id)` already existed, whether
    the balance value changed or not. A retroactive correction by
    Monarch counts as `dup_rows` here — the `updated_rows` axis is
    tracked as a follow-up (see #3 M2 exit criteria, deferred beyond
    M2 in favor of keeping the audit schema stable for M3).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from monarch_ingest.importers.result import (
    ImportRunResult,
    ResolveContext,
    UnmatchedNamesError,
    source_filename_hash,
)
from monarch_ingest.models import BalanceSnapshot, ImportRun
from monarch_ingest.parsers import BALANCE_SCHEMA_FINGERPRINT, parse_balances
from monarch_ingest.resolve import resolve_account


def import_balances(
    session: Session,
    path: Path,
    *,
    accept_new: bool = False,
) -> ImportRunResult:
    """Import balances from a Monarch CSV; upsert on (date, account_id).

    Transactional contract (the caller owns the boundary):
      - On success: call `session.commit()` to persist.
      - On `UnmatchedNamesError`: call `session.rollback()` before
        reusing the session. A partial `import_run` row with
        `finished_at=None` is in the session at that point and must be
        discarded.
    """
    rows = list(parse_balances(path))

    started = dt.datetime.now(dt.UTC)
    run = ImportRun(
        file_type="balances",
        source_filename_hash=source_filename_hash(path),
        schema_fingerprint=BALANCE_SCHEMA_FINGERPRINT,
        started_at=started,
        row_count=len(rows),
    )
    session.add(run)
    session.flush()

    ctx = ResolveContext(accept_new=accept_new)
    # (account_id) per row, or None placeholder on the unmatched path.
    resolved: list[int | None] = []
    for row in rows:
        account = resolve_account(session, row.raw_account, row.account_mask, ctx)
        resolved.append(account.id if account else None)

    if ctx.unmatched:
        raise UnmatchedNamesError(ctx.unmatched)

    # Bulk-load existing composite keys in a single query so we can
    # distinguish new from dup per-row without N+1 SELECTs. For ~50K
    # rows the memory cost of a set of (date, int) tuples is trivial.
    existing_keys: set[tuple[dt.date, int]] = {
        (row.date, row.account_id)
        for row in session.execute(select(BalanceSnapshot.date, BalanceSnapshot.account_id)).all()
    }

    new_rows = 0
    dup_rows = 0
    for row, account_id in zip(rows, resolved, strict=True):
        assert account_id is not None, (
            f"account resolved to None for row {row.raw_account!r} "
            "but ctx.unmatched was empty — importer invariant violated"
        )

        if (row.date, account_id) in existing_keys:
            dup_rows += 1
        else:
            new_rows += 1

        stmt = (
            sqlite_insert(BalanceSnapshot)
            .values(
                date=row.date,
                account_id=account_id,
                balance_cents=row.balance_cents,
                import_id=run.id,
            )
            .on_conflict_do_update(
                index_elements=["date", "account_id"],
                set_={"balance_cents": row.balance_cents, "import_id": run.id},
            )
        )
        session.execute(stmt)

    finished = dt.datetime.now(dt.UTC)
    run.new_rows = new_rows
    run.dup_rows = dup_rows
    run.finished_at = finished
    session.flush()

    return ImportRunResult(
        import_id=run.id,
        file_type="balances",
        row_count=len(rows),
        new_rows=new_rows,
        dup_rows=dup_rows,
        started_at=started,
        finished_at=finished,
    )
