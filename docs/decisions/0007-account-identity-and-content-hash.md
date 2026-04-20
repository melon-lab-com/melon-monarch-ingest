# 0007 — Account identity: drop `UNIQUE(mask)`, rewrite `content_hash` with canonical account name

- **Status:** Accepted
- **Date:** 2026-04-19
- **Milestone:** M3 close-out / M4 unblock
- **Supersedes:** [ADR-0002](0002-csv-validation-and-hashing.md) — *only*
  the content-hash rule (rule 4 and the payload format). ADR-0002's
  Pydantic v2 validation, amount parsing, and schema-fingerprint
  decisions remain in force.

## Context

Issue [#30] surfaced two data-corruption consequences of ADR-0002's
mask-only account identity during the first real M3 import:

1. **Joint credit-card accounts collapsed.** `UNIQUE(mask)` on
   `account` treats a primary holder and an authorized-user card
   sharing the same last-4 as the same account. M3 observed 4 such
   pairs (e.g. `CHASE COLLEGE (...9680)` and `CHASE COLLEGE (...9680)
   YY`). Per-owner household split (plan.md §8.4, a stated Monarch gap
   this project fills) is impossible for these accounts.
2. **Transactions cross-deduped.** `content_hash` uses `account_mask`
   as the sole account discriminator in the identity tuple. When two
   accounts share a mask, their same-day same-amount transactions hash
   identically and `INSERT OR IGNORE` silently drops the second one.
   M3 observed 708 real transactions deduped this way — cashflow loss
   for the secondary holder's card.

Manual-valuation accounts (rental property at book value, mask=NULL)
have an analogous latent bug: ADR-0002 rule 4 hashes `None → ""`, so
a household with two rental properties would see the same collapse.

Both failures share a root cause — `mask` is not a unique account
identifier in Monarch's data model. We picked mask in ADR-0002 because
it is rename-stable across Monarch-side renames, but we did not
anticipate Monarch's joint-card naming convention or multi-rental
households.

[#30]: https://github.com/melon-lab-com/melon-monarch-cfo/issues/30

## Decision

### Schema: drop `UNIQUE(mask)`

- `account.mask` is no longer unique. It remains a non-unique indexed
  column used as a **secondary resolution hint** for rename detection.
- Primary account identity is `UNIQUE(monarch_name)` (already declared
  in the initial schema).
- `is_manual_valuation` stays as a denormalized flag for rental-style
  accounts with no mask, but it is no longer load-bearing for
  uniqueness — two manual-valuation accounts are distinct by
  `monarch_name`.

### Resolver: `alias → monarch_name → unique-mask → unmatched|create`

`resolve_account` order becomes:

1. **Alias hit** — `account_alias.raw_name == raw_name` → return the
   aliased account.
2. **Canonical name hit** — `account.monarch_name == raw_name` →
   return that account (and, under `--accept-new`, record
   `AccountAlias(raw_name)` so future imports short-circuit to step 1).
3. **Mask hint** — if `mask is not None` **and exactly one** existing
   account has that mask, treat it as a rename (`raw_name` differs
   from all monarch_names seen so far). Record the alias when
   `--accept-new`, return the account.
4. **Unmatched / create** — under `--accept-new` create a new
   `account` row; otherwise append to `ctx.unmatched` and fail the
   importer before writing.

Step 3 intentionally declines to guess when masks collide — an
operator must disambiguate with `--accept-new` (creating the new
account) or pre-seed an alias.

### Content hash: `sha256(date | amount | esc(monarch_name) | esc(orig_stmt) | esc(notes))`

The payload's account field switches from the CSV-derived `mask` to
the **resolved account's canonical `monarch_name`**:

```python
content_hash = sha256(
    f"{date}|{amount_cents}|{esc(monarch_name)}|{esc(orig_stmt)}|{esc(notes)}"
    .encode("utf-8")
).hexdigest()
```

Rules 1, 2, 3, 5, 6 from ADR-0002 carry over unchanged (delimiter,
escaping, date format, amount format, UTF-8 encoding, verbatim string
fields). Only rule 4 (the account field) changes:

**Rule 4 (superseded):** The account field is the resolved account's
`monarch_name` — the UNIQUE canonical string persisted in the
`account` table. The raw CSV `Account` column does **not** feed the
hash; the resolver first looks up the account (alias / name / mask),
and the hash is computed with that account's canonical name.

Consequences of this rewording:

- **Cross-account collisions impossible.** `monarch_name` is UNIQUE
  per ADR-0002's descendant schema — two accounts can never hash to
  the same account-field value.
- **Rename-stable by construction.** The canonical `monarch_name` is
  the name Monarch shipped the *first* time the importer saw the
  account. Subsequent Monarch-side renames land in `account_alias`
  but leave `account.monarch_name` untouched, so the hash computed on
  every future import of a row for that account is identical. No
  re-inserts on rename.
- **Manual-valuation edge case disappears.** `monarch_name` is
  non-null for every account, so the `None → ""` special case in the
  previous rule 4 is gone.
- **Hash is no longer pure-CSV-derived.** It depends on the DB's
  resolution state (which canonical name was captured first). Two
  fresh imports of the same CSV into two empty DBs produce the same
  canonical (the CSV's own name), so golden-hash tests are still
  meaningful — they exercise the "first seen" path.

### Migration: nuke-and-reimport (pre-v0.1)

This is a breaking content-hash change — every row's hash under the
old rule is invalid. ADR-0002's migration procedure calls for an
Alembic data migration that rewrites every `transaction.content_hash`.
For the M3 replica DB, that migration would also need to re-check for
collisions that the old rule silently merged (the 708 lost rows).

Since we are pre-v0.1 and the only DB that exists is the local M3
replica on the operator's machine, **the accepted migration is
nuke-and-reimport**: drop the SQLite file, re-run `alembic upgrade
head` to land the new schema, re-run `monarch-ingest transactions
<csv> --accept-new` and `monarch-ingest balances <csv>`. The re-import
recovers the 708 lost rows automatically (they no longer collide).

A schema-only Alembic revision is still required — `DROP UNIQUE(mask)`
with `batch_alter_table` — because the SQLite schema needs to change
even on a freshly re-imported DB.

**If and when a future content-hash rule change lands after v0.1**,
ADR-0002's original migration procedure (rewrite every
`transaction.content_hash` in place) applies. This ADR's
nuke-and-reimport exception is scoped to the pre-v0.1 replica state.

## Consequences

### Positive

- Joint-card and multi-rental households are now first-class — no
  silent collapse, no silent cashflow loss.
- Rename detection survives: mask is still a hint for renamed
  accounts, just not a uniqueness key.
- Hash is rename-stable by construction (not accidentally, the way
  mask-based stability used to work).

### Negative / trade-offs

- Hash now depends on DB state (the canonical `monarch_name` captured
  at first sight). Re-importing into a brand-new DB still produces
  identical hashes for the same CSV, so golden-hash tests remain
  reproducible, but a human inspecting a `content_hash` value cannot
  recompute it from the CSV alone without also knowing which name
  Monarch shipped first for that account.
- When two accounts share a mask, the resolver refuses to auto-match
  — step 3 requires a unique mask. `--accept-new` is needed to create
  the second account. Acceptable: the alternative is to re-introduce
  the collapse bug.

### Alternatives considered and rejected

- **Hash on raw CSV `Account` string.** Simple, fully deterministic
  from CSV bytes, no DB dependency. Rejected because any Monarch-side
  rename would invalidate every historical hash for that account and
  re-insert every pre-rename row under the new name.
- **Hash on `account_id` (DB integer PK).** Rename-stable, but
  `account_id` is assigned at `INSERT` time and differs across
  rebuilds of the same DB. Golden-hash tests would be pinned to a
  particular insertion order, which is fragile.
- **Keep ADR-0002 rule 4 and add `monarch_name` as a second field.**
  Redundant: `monarch_name` alone already discriminates, and leaving
  `mask` in the hash preserves the `None → ""` manual-valuation
  edge case without benefit.
- **Drop `content_hash` entirely; rely on composite UNIQUE `(account_id,
  date, amount_cents, original_statement, notes)`.** Cleaner
  conceptually, but a much bigger surface area — deletes the whole
  ADR-0002 hashing story and forces every downstream consumer (audit,
  replay, API) to depend on a long composite key. Deferred; this ADR
  keeps the existing `content_hash` column and shape, only updates
  its input.

## References

- Issue [#30] — the M3-import symptoms that motivated this ADR.
- [ADR-0002](0002-csv-validation-and-hashing.md) — content-hash rule
  this ADR supersedes (rule 4 only).
- [`src/monarch_ingest/hashing.py`](../../src/monarch_ingest/hashing.py)
  — canonical implementation; golden-hash tests in
  [`tests/unit/test_hashing.py`](../../tests/unit/test_hashing.py).
- [`docs/plan.md`](../plan.md) — §2 data model, §3 incremental import,
  §14 risks and punts.

[#30]: https://github.com/melon-lab-com/melon-monarch-cfo/issues/30
