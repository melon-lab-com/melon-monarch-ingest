"""drop unique(mask), index mask (ADR-0007)

Revision ID: 08d910599bec
Revises: 598e57315a29
Create Date: 2026-04-19 10:17:11.094010

Drops the `UNIQUE(mask)` constraint on `account` in favor of a plain
index — Monarch ships joint cards with the same last-4, so mask is
not a unique key. See ADR-0007.

SQLite has no `ALTER TABLE DROP CONSTRAINT`, so batch mode rebuilds
the table. The initial migration declared `UNIQUE(mask)` as an
unnamed table-level constraint, so we pass a `naming_convention` at
batch-alter time so the reflected constraint picks up the
deterministic name `uq_account_mask`, which `drop_constraint` then
targets.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "08d910599bec"
down_revision: str | Sequence[str] | None = "598e57315a29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Deterministic names for the unnamed constraints reflected from the
# initial migration's `account` table. Scoped to this migration only
# so we don't change ORM-wide naming behavior.
_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def upgrade() -> None:
    """Drop UNIQUE(mask); keep UNIQUE(monarch_name); add ix_account_mask."""
    with op.batch_alter_table(
        "account",
        schema=None,
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint("uq_account_mask", type_="unique")
        batch_op.create_index(batch_op.f("ix_account_mask"), ["mask"], unique=False)


def downgrade() -> None:
    """Re-add UNIQUE(mask); drop ix_account_mask."""
    with op.batch_alter_table(
        "account",
        schema=None,
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_index(batch_op.f("ix_account_mask"))
        batch_op.create_unique_constraint("uq_account_mask", ["mask"])
