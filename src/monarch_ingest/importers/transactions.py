"""Transactions CSV importer.

Pipeline:
  1. Parse the CSV (schema-fingerprint gate raises on drift).
  2. Create an `import_run` audit row.
  3. Dry-pass over rows: resolve account/category/merchant/owner via
     the alias layer. If any are unmatched and `accept_new=False`,
     abort before writing.
  4. Write pass: for each row, compute `content_hash` and INSERT with
     `ON CONFLICT (content_hash) DO NOTHING RETURNING id`. The
     `RETURNING` tells us which rows were new vs. duplicates without
     relying on driver-specific `rowcount` semantics.
  5. Finalize the import_run with counts and `finished_at`.

Idempotency: re-importing the same file produces zero new rows because
every row's content_hash already exists.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from monarch_ingest.hashing import content_hash
from monarch_ingest.importers.result import (
    ImportRunResult,
    ResolveContext,
    UnmatchedNamesError,
    source_filename_hash,
)
from monarch_ingest.models import Account, ImportRun, Transaction
from monarch_ingest.parsers import TRANSACTION_SCHEMA_FINGERPRINT, parse_transactions
from monarch_ingest.resolve import (
    resolve_account,
    resolve_category,
    resolve_merchant,
    resolve_owner,
)


def import_transactions(
    session: Session,
    path: Path,
    *,
    accept_new: bool = False,
) -> ImportRunResult:
    """Import transactions from a Monarch CSV into the given session.

    Transactional contract (the caller owns the boundary):
      - On success: call `session.commit()` to persist.
      - On `UnmatchedNamesError`: call `session.rollback()` before
        reusing the session. A partial `import_run` row with
        `finished_at=None` is in the session at that point and must be
        discarded.
    """
    rows = list(parse_transactions(path))

    started = dt.datetime.now(dt.UTC)
    run = ImportRun(
        file_type="transactions",
        source_filename_hash=source_filename_hash(path),
        schema_fingerprint=TRANSACTION_SCHEMA_FINGERPRINT,
        started_at=started,
        row_count=len(rows),
    )
    session.add(run)
    session.flush()

    ctx = ResolveContext(accept_new=accept_new)
    # (account_id, merchant_id, category_id, owner_id) per row, or None
    # placeholder on the unmatched path. After the `ctx.unmatched` check
    # below all entries are guaranteed non-None on the account axis.
    resolved: list[tuple[int | None, int | None, int | None, int | None]] = []
    for row in rows:
        account = resolve_account(session, row.raw_account, row.account_mask, ctx)
        # merchant/category/owner are required CSV columns; guard only
        # against Pydantic passing through a blank string for one.
        merchant = resolve_merchant(session, row.merchant, ctx) if row.merchant else None
        category = resolve_category(session, row.category, ctx) if row.category else None
        owner = resolve_owner(session, row.owner, ctx) if row.owner else None
        resolved.append(
            (
                account.id if account else None,
                merchant.id if merchant else None,
                category.id if category else None,
                owner.id if owner else None,
            )
        )

    if ctx.unmatched:
        # accept_new=False hit unknowns — fail before writing any tx.
        raise UnmatchedNamesError(ctx.unmatched)

    # Cache account canonical names keyed by id — the importer resolves
    # the same account many times per run, and we hash with the
    # canonical `monarch_name` (ADR-0007), not the CSV field.
    canonical_names: dict[int, str] = {}

    new_rows = 0
    dup_rows = 0
    new_txn_ids: list[int] = []
    for row, (account_id, merchant_id, category_id, owner_id) in zip(rows, resolved, strict=True):
        # Invariant: past the `ctx.unmatched` guard, every row resolved
        # its account successfully. If not, we'd rather crash loudly
        # here than INSERT with a sentinel FK and silently corrupt data.
        assert account_id is not None, (
            f"account resolved to None for row {row.raw_account!r} "
            "but ctx.unmatched was empty — importer invariant violated"
        )
        account_key = canonical_names.get(account_id)
        if account_key is None:
            # `resolve_account` just returned this id via `flush()`, so
            # it is guaranteed to be in the session identity map.
            # `get_one` raises if it isn't — that would be an invariant
            # violation worth surfacing, not papering over.
            account_key = session.get_one(Account, account_id).monarch_name
            canonical_names[account_id] = account_key
        h = content_hash(
            date=row.date,
            amount_cents=row.amount_cents,
            account_key=account_key,
            original_statement=row.original_statement,
            notes=row.notes,
        )
        stmt = (
            sqlite_insert(Transaction)
            .values(
                date=row.date,
                amount_cents=row.amount_cents,
                account_id=account_id,
                merchant_id=merchant_id,
                category_id=category_id,
                owner_id=owner_id,
                original_statement=row.original_statement,
                notes=row.notes,
                tags=row.tags,
                content_hash=h,
                imported_at=started,
                import_id=run.id,
            )
            .on_conflict_do_nothing(index_elements=["content_hash"])
            .returning(Transaction.id)
        )
        inserted_id = session.execute(stmt).scalar_one_or_none()
        if inserted_id is None:
            dup_rows += 1
        else:
            new_rows += 1
            new_txn_ids.append(inserted_id)

    if new_txn_ids:
        # Apply any user-defined rewrite rules to the rows we just
        # inserted so merchant/category reflect the user's overrides
        # from first sight. Rules are replayable — `rules apply` in
        # the CLI re-runs over history if a rule changes later.
        # An unhandled exception here rolls back the full import:
        # intentional — a half-imported file with partial rewrites is
        # worse than a clean failure the operator can re-run.
        from monarch_ingest.rules import apply_to_ids

        apply_to_ids(session, new_txn_ids)

    finished = dt.datetime.now(dt.UTC)
    run.new_rows = new_rows
    run.dup_rows = dup_rows
    run.finished_at = finished
    session.flush()

    return ImportRunResult(
        import_id=run.id,
        file_type="transactions",
        row_count=len(rows),
        new_rows=new_rows,
        dup_rows=dup_rows,
        started_at=started,
        finished_at=finished,
    )
