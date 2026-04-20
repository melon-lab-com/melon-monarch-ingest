# 0002 — CSV row validation (Pydantic v2) and content-hash rules

- **Status:** Partially superseded by
  [ADR-0007](0007-account-identity-and-content-hash.md) — rule 4 (the
  `account_mask` field of the content-hash payload) and the migration
  path for that change. The Pydantic-v2 validation, amount parsing,
  and schema-fingerprint decisions below remain in force.
- **Date:** 2026-04-18
- **Milestone:** M2 (Ingest lib)

## Context

Two related decisions show up in PR-3 of M2 and need to be locked
before any row is ever hashed for real:

1. **CSV row validation.** Pydantic v2 BaseModel vs stdlib dataclasses
   + manual validators for parsing Monarch CSVs.
2. **Content-hash rules.** The dedup identity of a transaction is
   `sha256(...)` over a concatenation of fields. Once we have run this
   against real data, changing any byte of the rule invalidates every
   hash in the DB.

## Decision

### CSV validation: Pydantic v2

Pydantic v2 `BaseModel` for `TransactionRow` and `BalanceRow`:

- Field coercion from CSV strings (dates, amounts).
- Required-vs-optional field semantics surface as validation errors
  with column context.
- `Pydantic` is already committed as a FastAPI dep (plan §1), so we
  are not paying a new dep cost for `monarch_ingest`.

Alternative rejected: dataclasses + hand-written validators. Too much
boilerplate for ~2 row schemas.

### Content-hash algorithm (frozen)

> **Superseded by [ADR-0007](0007-account-identity-and-content-hash.md)
> — rule 4 only.** The `esc(mask)` field in the code block below, and
> rule 4 itself, are no longer current. The account field of the
> payload is the resolved account's canonical `monarch_name`, not
> the mask. Rules 1 (field list), 2, 3, 5, 6 remain in force.

```
content_hash = sha256(
    f"{date}|{amount_cents}|{esc(mask)}|{esc(original_statement)}|{esc(notes)}"
    .encode("utf-8")
).hexdigest()

esc(s) = s.replace("%", "%25").replace("|", "%7C")
```

**Locked rules — any change is a breaking migration:**

1. **Delimiter is `|` (ASCII 0x7C)**, one character between fields. No
   trailing delimiter. String fields (the account field — `mask`
   under the original rule, `monarch_name` under
   [ADR-0007](0007-account-identity-and-content-hash.md) — plus
   `original_statement` and `notes`) are percent-escaped before
   joining: `%` → `%25`, then `|` → `%7C`. The order matters — `%`
   must be escaped first so decoding is unambiguous. This prevents a
   `|` inside `original_statement` from silently colliding with a
   different row where the `|` lives in `notes`. Embedded `\r\n`
   inside a field is preserved verbatim (csv.DictReader delivers it
   intact and we hash what it delivers).
2. **`date`** is rendered as ISO-8601 `YYYY-MM-DD` (Python's
   `datetime.date.isoformat()`).
3. **`amount_cents`** is rendered as a signed decimal integer via
   `str(amount_cents)` — no leading zeros, no thousands separators, no
   padding. `-475`, `3500`, `0`.
4. **`account_mask`** *(superseded by
   [ADR-0007](0007-account-identity-and-content-hash.md))* — was
   either the extracted mask string (e.g. `"9999"`) or the literal
   empty string `""` when the account has no mask (manual-valuation
   accounts — rental property). Never `"None"`, never `None`. Under
   ADR-0007 the account field is the resolved account's canonical
   `monarch_name` instead, which is always non-null.
5. **`original_statement`** and **`notes`** are rendered verbatim as
   the exporter provided them, with empty cells normalized to `""`
   (not `None`, not the literal string `"None"`). No whitespace
   trimming. No case folding. No unicode normalization.
6. **Encoding** is UTF-8. Monarch exports UTF-8. If they ever ship a
   different encoding we bump the ADR, not the code silently.

### Amount parsing (frozen)

Float → int cents bridges a floating-point trap: `-4.75 * 100 ==
-474.99999...`. The rule:

```python
from decimal import Decimal
cents = int(Decimal(str(amount)) * 100)
```

`Decimal(str(x))` not `Decimal(x)` — the latter preserves the float's
binary imprecision. `int(Decimal)` truncates toward zero which is
correct for values that are exact multiples of 0.01; a guard raises if
the scaled Decimal has any fractional part (i.e., the CSV had more
than two decimal places).

### Schema fingerprint (frozen)

```python
schema_fingerprint = sha256(
    ",".join(sorted(headers)).encode("utf-8")
).hexdigest()
```

- `headers` is the first row of the CSV verbatim (no normalization,
  case-sensitive).
- Sorted lexicographically, joined with `,`.
- Change in Monarch's column set or casing → mismatch → importer
  refuses with a clear diff.

### Schema bump procedure (when Monarch adds/renames columns)

1. Hit the `SchemaMismatchError` on a real import — the error message
   lists missing / unexpected columns.
2. If a new optional column landed, update `_TRANSACTION_HEADERS` (or
   `_BALANCE_HEADERS`) in `csv_reader.py` and re-pin the
   corresponding `TRANSACTION_SCHEMA_FINGERPRINT` constant (tests
   will prompt for the new golden value).
3. If a semantic column of the hash identity changed (e.g.
   `"Original Statement"` renamed), this is a *content-hash* change
   too — see the migration procedure below.

### Content-hash migration procedure

A content-hash rule change (any of rules 1-6 above) requires:

1. A **superseding ADR** that supersedes this one by number, explains
   the reason, and links back.
2. An **Alembic data migration** that rewrites every
   `transaction.content_hash` value in the DB. The migration must
   run a consistent recompute using the new rule — not a re-parse of
   the original CSV, which may no longer exist.
3. A bump of the golden-hash tests in `test_hashing.py` and the
   `TRANSACTION_SCHEMA_FINGERPRINT` constant if the schema-fingerprint
   algorithm changed.

Until a real import has run, no DB rows exist and rule changes are
free. After the first real import, the above procedure applies.

## Consequences

### Positive

- Hash rules documented in one place, in prose, so a future
  implementer can reconstruct them from the ADR even if the code
  drifts. Golden-hash unit tests (PR-3) pin the algorithm.
- Pydantic gives per-field error context "for free" — the importer's
  user-facing errors point at the right column.
- Floating-point trap is eliminated at the boundary.

### Negative / trade-offs

- Hash rules are effectively frozen. Any future change needs a
  superseding ADR, a migration that rewrites every `content_hash` in
  the DB, and a coordinated bump.
- Pydantic adds a dep to `monarch_ingest`. Small, ubiquitous, fine.
- Case-sensitive fingerprinting means Monarch changing `"Original
  Statement"` → `"original statement"` would break imports until the
  schema bump PR. Accepted — we want to notice format drift.

### Alternatives considered and rejected

- **`json.dumps(...)` for the hash payload** — stable, but adds a
  second dimension of "which JSON serialization" that could drift
  across Python versions. Simple `|`-joined string is reproducible by
  a human inspecting the DB.
- **Normalize whitespace/case before hashing** — rejected. Monarch
  sometimes edits `original_statement` in place (cleanup). We want
  those edits to show as "new row, old row stays"; normalizing would
  mask them.
- **Hash on the raw CSV row bytes** — rejected. Column order in the
  CSV could change; we want hash stability across any Monarch reorder.

## References

- [docs/plan.md §3](../plan.md) — incremental import strategy.
- [`src/monarch_ingest/hashing.py`](../../src/monarch_ingest/hashing.py)
  — the canonical implementation.
