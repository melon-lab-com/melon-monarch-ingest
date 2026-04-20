"""Alias resolution for the importers.

Each resolver tries:
  1. alias table (raw_name → owner/account/etc.),
  2. canonical lookup (name for most entities; for accounts: name
     first, then a unique-mask hint — see ADR-0007),
  3. if nothing matches: either append to `ctx.unmatched` (when
     `accept_new=False`) or create a new row + alias.

Accounts have a three-step lookup (alias + canonical name + mask
hint). The mask step only applies when exactly one existing account
has that mask — Monarch ships joint cards with a shared last-4 under
different names, so mask is a rename *hint*, not a unique key.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from monarch_ingest.importers.result import ResolveContext
from monarch_ingest.models import (
    Account,
    AccountAlias,
    Category,
    CategoryAlias,
    Merchant,
    MerchantAlias,
    Owner,
)


def _record_unmatched(ctx: ResolveContext, kind: str, raw_name: str) -> None:
    ctx.unmatched.append(f"{kind}: {raw_name}")


def _ensure_account_alias(session: Session, account_id: int, raw_name: str) -> None:
    """Idempotently add an `(account_id, raw_name)` alias.

    Step 1 of `resolve_account` already catches repeated calls for the
    same raw_name, so the duplicate path almost never fires. Guarding
    the write keeps steps 2 and 3 defensively idempotent — a later
    refactor that changes session autoflush behavior can't
    reintroduce a `(account_id, raw_name)` UNIQUE violation.
    """
    exists = session.execute(
        select(AccountAlias).where(
            AccountAlias.account_id == account_id,
            AccountAlias.raw_name == raw_name,
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(AccountAlias(account_id=account_id, raw_name=raw_name))
        session.flush()


def resolve_owner(session: Session, raw_name: str, ctx: ResolveContext) -> Owner | None:
    """Resolve an owner name. No aliasing: households don't rename owners."""
    owner = session.execute(select(Owner).where(Owner.name == raw_name)).scalar_one_or_none()
    if owner is not None:
        return owner
    if not ctx.accept_new:
        _record_unmatched(ctx, "owner", raw_name)
        return None
    owner = Owner(name=raw_name)
    session.add(owner)
    session.flush()
    return owner


def resolve_merchant(session: Session, raw_name: str, ctx: ResolveContext) -> Merchant | None:
    """Resolve a merchant. May append to `ctx.unmatched` on miss."""
    alias = session.execute(
        select(MerchantAlias).where(MerchantAlias.raw_name == raw_name)
    ).scalar_one_or_none()
    if alias is not None:
        return session.get(Merchant, alias.merchant_id)

    merchant = session.execute(
        select(Merchant).where(Merchant.canonical_name == raw_name)
    ).scalar_one_or_none()
    if merchant is not None:
        return merchant

    if not ctx.accept_new:
        _record_unmatched(ctx, "merchant", raw_name)
        return None

    merchant = Merchant(canonical_name=raw_name)
    session.add(merchant)
    session.flush()
    session.add(MerchantAlias(merchant_id=merchant.id, raw_name=raw_name))
    session.flush()
    return merchant


def resolve_category(session: Session, raw_name: str, ctx: ResolveContext) -> Category | None:
    """Resolve a category. May append to `ctx.unmatched` on miss."""
    alias = session.execute(
        select(CategoryAlias).where(CategoryAlias.raw_name == raw_name)
    ).scalar_one_or_none()
    if alias is not None:
        return session.get(Category, alias.category_id)

    category = session.execute(
        select(Category).where(Category.name == raw_name)
    ).scalar_one_or_none()
    if category is not None:
        return category

    if not ctx.accept_new:
        _record_unmatched(ctx, "category", raw_name)
        return None

    category = Category(name=raw_name)
    session.add(category)
    session.flush()
    session.add(CategoryAlias(category_id=category.id, raw_name=raw_name))
    session.flush()
    return category


def resolve_account(
    session: Session, raw_name: str, mask: str | None, ctx: ResolveContext
) -> Account | None:
    """Resolve an account via alias → canonical name → unique-mask → create.

    Resolution order (ADR-0007):
      1. Alias hit — `account_alias.raw_name == raw_name`.
      2. Canonical name hit — `account.monarch_name == raw_name`.
      3. Unique-mask hint — `mask` matches exactly one existing
         account (ambiguous masks fall through).
      4. Create under `--accept-new`, else append to `ctx.unmatched`.

    Steps 2 and 3 record an alias under `--accept-new` so future imports
    short-circuit to step 1. `accept_new=False` is strictly non-mutating:
    a read-only import still resolves via name or unique-mask, but
    defers the alias bookkeeping to the next `--accept-new` run.
    """
    alias = session.execute(
        select(AccountAlias).where(AccountAlias.raw_name == raw_name)
    ).scalar_one_or_none()
    if alias is not None:
        return session.get(Account, alias.account_id)

    account = session.execute(
        select(Account).where(Account.monarch_name == raw_name)
    ).scalar_one_or_none()
    if account is not None:
        if ctx.accept_new:
            _ensure_account_alias(session, account.id, raw_name)
        return account

    if mask is not None:
        # Unique-mask hint: match only when the live `account` table has
        # exactly one row with this mask *and* that row was not created
        # earlier in the same import run. Excluding same-run rows is the
        # guard against joint-card siblings on a first import: after
        # row 1 creates account A for mask 9680, row 2 for a different
        # `YY` sibling would otherwise match A via the unique-mask
        # branch and get its transactions silently merged. See ADR-0007.
        candidates = session.execute(select(Account).where(Account.mask == mask)).scalars().all()
        existing = [a for a in candidates if a.id not in ctx.created_account_ids]
        if len(existing) == 1:
            account = existing[0]
            if ctx.accept_new:
                _ensure_account_alias(session, account.id, raw_name)
            return account

    if not ctx.accept_new:
        _record_unmatched(ctx, "account", raw_name)
        return None

    account = Account(
        monarch_name=raw_name,
        mask=mask,
        is_manual_valuation=(mask is None),
    )
    session.add(account)
    session.flush()
    session.add(AccountAlias(account_id=account.id, raw_name=raw_name))
    session.flush()
    ctx.created_account_ids.add(account.id)
    return account
