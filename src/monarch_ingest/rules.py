"""User-defined rewrite rules: regex → merchant_id / category_id.

Two rule kinds:

- `merchant` — match `transaction.original_statement` (case-insensitive);
  on first match rewrite `transaction.merchant_id` to `target_id`.
- `category` — same match, rewrite `transaction.category_id`.

Rules are ordered `priority ASC, id ASC` within each kind; the first
matching rule wins for a given `(transaction, kind)` pair. Rules are
applied in two passes per transaction (merchant first, then category)
so a merchant rewrite can feed category inference in a future iteration
without order-of-application surprises.

Rules are **replayable**: `apply_all(session)` walks every active
transaction; `apply_to_ids(session, ids)` narrows to a subset (the
importer path).

Invalid regex patterns are caught at add-time (`validate_pattern`);
`apply_*` never catches `re.error` because every stored pattern is
already proven compilable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from monarch_ingest.models import Category, Merchant, Rule, Transaction

KIND_MERCHANT = "merchant"
KIND_CATEGORY = "category"
_VALID_KINDS = frozenset({KIND_MERCHANT, KIND_CATEGORY})

# SQLite's default compound-parameter limit is 999. A large CSV drop
# produces >999 newly-inserted transaction ids, and `WHERE id IN (...)`
# expands to that many host params. Chunk below the limit with headroom
# for the other bound params in the query.
_IN_CLAUSE_CHUNK = 900


class InvalidRuleError(ValueError):
    """Raised by the CLI when a rule is syntactically invalid."""


def validate_pattern(pattern: str) -> None:
    """Raise `InvalidRuleError` if `pattern` fails to compile.

    Called from the CLI's `rules add`. Rules are stored as text, so
    this is the one place to catch bad regex before it enters the
    DB — `apply_*` assumes every stored pattern compiles.
    """
    try:
        re.compile(pattern)
    except re.error as exc:
        raise InvalidRuleError(f"invalid regex pattern: {exc}") from exc


def validate_kind(kind: str) -> None:
    if kind not in _VALID_KINDS:
        raise InvalidRuleError(f"rule kind must be one of {sorted(_VALID_KINDS)}; got {kind!r}")


def _load_rules(session: Session, kind: str) -> list[tuple[re.Pattern[str], int]]:
    """Return compiled (pattern, target_id) pairs for active rules of `kind`.

    `target_id` is a polymorphic FK (not a real FK — see model). Filter
    orphans at load time by inner-joining the target table: if the
    merchant or category was deleted after the rule was added, the rule
    silently drops out of this load and never writes a dangling FK.

    IGNORECASE is always on: Monarch statement lines are bank-normalized
    (typically all-caps); a case-sensitive flag would carry no user
    value and adds a schema column for no payoff.
    """
    target_model = Merchant if kind == KIND_MERCHANT else Category
    rows = session.execute(
        select(Rule.pattern, Rule.target_id)
        .join(target_model, target_model.id == Rule.target_id)
        .where(Rule.kind == kind, Rule.active.is_(True))
        .order_by(Rule.priority.asc(), Rule.id.asc())
    ).all()
    return [(re.compile(pat, re.IGNORECASE), tid) for pat, tid in rows]


def _apply_kind_to_txns(
    txns: Sequence[Transaction],
    rules: list[tuple[re.Pattern[str], int]],
    *,
    attr: str,
) -> int:
    """Apply `rules` to `txns`; return count of transactions mutated.

    `attr` is the `Transaction` attribute to rewrite (`merchant_id`
    or `category_id`).
    """
    if not rules:
        return 0
    changed = 0
    for txn in txns:
        statement = txn.original_statement or ""
        for pat, target_id in rules:
            if pat.search(statement):
                if getattr(txn, attr) != target_id:
                    setattr(txn, attr, target_id)
                    changed += 1
                break
    return changed


def apply_to_ids(session: Session, txn_ids: Iterable[int]) -> int:
    """Apply active rules to the given transaction ids.

    Used by the importer to rewrite newly-inserted rows. Returns the
    count of rewrites made across both kinds (a single transaction
    updated for merchant + category counts as 2).

    The id list is chunked at `_IN_CLAUSE_CHUNK` to stay under SQLite's
    default 999-parameter limit, which a large CSV drop can exceed.
    """
    ids = list(txn_ids)
    if not ids:
        return 0
    txns: list[Transaction] = []
    for start in range(0, len(ids), _IN_CLAUSE_CHUNK):
        chunk = ids[start : start + _IN_CLAUSE_CHUNK]
        txns.extend(session.scalars(select(Transaction).where(Transaction.id.in_(chunk))).all())
    return _apply_rules(session, txns)


def apply_all(session: Session) -> int:
    """Replay active rules against every transaction; return mutation count."""
    txns = list(session.scalars(select(Transaction)).all())
    return _apply_rules(session, txns)


def _apply_rules(session: Session, txns: Sequence[Transaction]) -> int:
    merchant_rules = _load_rules(session, KIND_MERCHANT)
    category_rules = _load_rules(session, KIND_CATEGORY)
    count = _apply_kind_to_txns(txns, merchant_rules, attr="merchant_id")
    count += _apply_kind_to_txns(txns, category_rules, attr="category_id")
    # Caller owns the commit (and the flush) — the importer's
    # `session_scope` commits on exit, and `rules apply` does the same.
    # Flushing here would be a redundant round-trip.
    return count
