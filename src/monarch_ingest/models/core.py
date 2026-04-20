"""Core schema for `monarch_ingest`.

See [docs/plan.md §2](../../../../docs/plan.md) for the data-model rationale.
See ADR-0003 for the sync-SQLAlchemy and plain-`Mapped[...]` style choice.

Amount and balance values are stored as integer cents — never `Float` or
`Numeric` on the hot path — to eliminate rounding drift on re-import and to
make the dedup hash exact. See `monarch_ingest.hashing` for the content-hash
rule (landed in PR-3).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Owner(Base):
    __tablename__ = "owner"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


class Account(Base):
    __tablename__ = "account"

    # Rename handling (lands in PR-4 with the importer): a Monarch rename
    # must `INSERT account_alias(account_id, raw_name=<old>) + UPDATE
    # account SET monarch_name=<new>` atomically inside one session_scope.
    # If the new name collides with another existing account (rare Monarch
    # name-reuse), the importer surfaces the unmatched row via `unmatched`
    # rather than looping against the UNIQUE constraint.
    id: Mapped[int] = mapped_column(primary_key=True)
    monarch_name: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    institution: Mapped[str | None] = mapped_column(String(255))
    # Account-number mask (last-4 digits) extracted from names like
    # "CHECKING (...9999)". Non-unique: Monarch ships joint cards
    # where the primary holder and an authorized-user card share a
    # last-4 under different names — `UNIQUE(mask)` would collapse
    # them. Used as a rename hint in `resolve_account` (matched only
    # when exactly one account has that mask). See ADR-0007.
    mask: Mapped[str | None] = mapped_column(String(16), index=True)
    type: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(default=True)
    is_manual_valuation: Mapped[bool] = mapped_column(default=False)
    first_seen: Mapped[dt.date | None] = mapped_column(Date)
    last_seen: Mapped[dt.date | None] = mapped_column(Date)


class AccountAlias(Base):
    __tablename__ = "account_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    raw_name: Mapped[str] = mapped_column(String(255))
    seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )

    __table_args__ = (UniqueConstraint("account_id", "raw_name"),)


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"))
    active: Mapped[bool] = mapped_column(default=True)


class CategoryAlias(Base):
    __tablename__ = "category_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    raw_name: Mapped[str] = mapped_column(String(128))

    __table_args__ = (UniqueConstraint("category_id", "raw_name"),)


class Merchant(Base):
    __tablename__ = "merchant"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), unique=True)


class MerchantAlias(Base):
    __tablename__ = "merchant_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchant.id"))
    raw_name: Mapped[str] = mapped_column(String(255))

    __table_args__ = (UniqueConstraint("merchant_id", "raw_name"),)


class ImportRun(Base):
    __tablename__ = "import_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    # "transactions" | "balances" — a CHECK constraint locks these values.
    file_type: Mapped[str] = mapped_column(String(16))
    # Hash of the source filename (not the path) — we want an audit trail
    # without recording absolute paths that could identify the user.
    source_filename_hash: Mapped[str] = mapped_column(String(64))
    schema_fingerprint: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(default=0)
    new_rows: Mapped[int] = mapped_column(default=0)
    dup_rows: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "file_type IN ('transactions', 'balances')",
            name="ck_import_run_file_type",
        ),
    )


class Transaction(Base):
    __tablename__ = "transaction"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    amount_cents: Mapped[int]
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchant.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owner.id"))
    original_statement: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")
    # Stable hash of the dedup-identity tuple; see `monarch_ingest.hashing`.
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    imported_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
    import_id: Mapped[int] = mapped_column(ForeignKey("import_run.id"))

    __table_args__ = (
        Index("ix_transaction_date", "date"),
        Index("ix_transaction_account_id", "account_id"),
    )


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshot"

    # Composite PK: (date, account_id). Upsert on re-import.
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), primary_key=True)
    balance_cents: Mapped[int]
    import_id: Mapped[int] = mapped_column(ForeignKey("import_run.id"))

    __table_args__ = (Index("ix_balance_snapshot_date", "date"),)


class Rule(Base):
    """User-defined rewrite rule.

    A rule matches `transaction.original_statement` against a regex
    (case-insensitive) and, on match, overrides the row's
    `merchant_id` (kind="merchant") or `category_id` (kind="category").

    Replay rules: rules apply at import time to newly-inserted rows
    and can be re-run across the full history via
    `monarch_ingest.rules.apply_all` / the `rules apply` CLI command.

    Ordering: rules partition by `kind`, then sort `priority ASC,
    id ASC`; the first match wins for a given transaction + kind.
    Invalid patterns are silently deactivated at CLI-add time (see
    `monarch_ingest.rules.validate_pattern`) so `apply_rules` never
    needs to catch `re.error` in its hot loop.
    """

    __tablename__ = "rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    pattern: Mapped[str] = mapped_column(Text)
    # Target FK depends on `kind`: merchant.id for "merchant",
    # category.id for "category". Not declared as a real FK because
    # SQLAlchemy can't express a polymorphic FK without extra columns.
    # The CLI validates existence at add-time.
    target_id: Mapped[int]
    priority: Mapped[int] = mapped_column(default=100)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('merchant', 'category')",
            name="ck_rule_kind",
        ),
        Index("ix_rule_kind_priority", "kind", "priority"),
    )


class RawImportRow(Base):
    __tablename__ = "raw_import_row"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("import_run.id"))
    row_json: Mapped[str] = mapped_column(Text)
