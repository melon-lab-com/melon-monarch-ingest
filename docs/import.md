# Importing Monarch CSVs

The `monarch-ingest` CLI imports Monarch CSV exports into a local
SQLite database.

## Quick start

```shell
# First time: pass --accept-new so the importer creates accounts,
# categories, merchants, and owners from the CSV.
monarch-ingest transactions ~/Downloads/Transactions_2025-04-01.csv --accept-new
monarch-ingest balances     ~/Downloads/Balances_2025-04-01.csv     --accept-new

# Subsequent imports: drop --accept-new. New entity names will then
# fail the import with exit code 3 so you can decide whether to add
# them or fix the CSV.
monarch-ingest transactions ~/Downloads/Transactions_2025-05-01.csv

# See import history and current schema version.
monarch-ingest status
```

All commands accept `--db-url <sqlalchemy-url>`. Default is
`sqlite:///./monarch.db` unless `MONARCH_DB_URL` is set.

## Schema fingerprint

Each import is gated by a `schema_fingerprint = sha256(sorted(headers))`
check. If Monarch changes the CSV format (adds, renames, or reorders
columns — beyond reordering, which the sort absorbs), the importer
refuses with exit code `2` and prints the missing / unexpected column
diff.

Recovering from a refused import:

1. **If the new column is one you want to *ignore*:** update
   `_TRANSACTION_HEADERS` / `_BALANCE_HEADERS` in
   `src/monarch_ingest/parsers/csv_reader.py` and re-pin the
   `TRANSACTION_SCHEMA_FINGERPRINT` / `BALANCE_SCHEMA_FINGERPRINT`
   constant (tests will prompt for the new golden value). The column
   will be silently dropped — that's the intent.
2. **If you want to *ingest* the new column:** in addition to step 1,
   you must also:
   - Add a field to the corresponding Pydantic row model in
     `src/monarch_ingest/parsers/schemas.py`.
   - Add a column to the ORM model in
     `src/monarch_ingest/models/core.py`.
   - Generate a new Alembic migration
     (`alembic revision --autogenerate -m "add <column>"`).
   - Wire the field into the importer's INSERT statement.
   - If the column is part of the dedup identity (rare), this is also
     a hash-rule change — see the migration procedure in
     [ADR-0002](decisions/0002-csv-validation-and-hashing.md) (post-v0.1:
     rewrite every `content_hash` via an Alembic data migration; the
     pre-v0.1 nuke-and-reimport exception in
     [ADR-0007](decisions/0007-account-identity-and-content-hash.md)
     only applies while the DB is the local M3 replica).

   Skipping any of these sub-steps makes the column land as an
   always-NULL ORM field, silently.
3. **If a column of the dedup hash identity changed** (e.g. `Original
   Statement` → `OriginalStatement`), the existing `content_hash`
   values no longer match — see the content-hash migration procedure
   in [ADR-0002](decisions/0002-csv-validation-and-hashing.md), as
   amended by
   [ADR-0007](decisions/0007-account-identity-and-content-hash.md)
   for the account-field rule.

## `--accept-new` workflow

The importer resolves every row's account, category, merchant, and
owner through an alias table. A new raw name that has never been seen
is "unmatched" by default; the import aborts with exit code `3` and
prints up to the first 5 unmatched names:

```
5 unmatched name(s); re-run with --accept-new to auto-create or fix the CSV.
First few: ['merchant: New Coffee Shop', 'category: Subscriptions', ...]
```

`--accept-new` flips the behavior: unknowns become new rows in the
relevant canonical + alias tables, and the import continues.

The recommended workflow:

- **First import** of fresh data: use `--accept-new`.
- **Routine re-imports**: drop the flag. If Monarch introduces a new
  merchant or category, the failure is an intentional review point —
  decide if it's a real new entity or a typo/rename before accepting.

## Dedup vs. upsert

**Transactions** use `ON CONFLICT (content_hash) DO NOTHING`: the
second import of the same row is a no-op. Any operator-side edit
(notes, tags, category) in Monarch produces a new `content_hash`, so
the edited row re-imports as "new" and the old row stays. This
preserves history but does mean a net-new row for every edit.

**Balances** use `ON CONFLICT (date, account_id) DO UPDATE`: the
later export wins. Monarch can retroactively correct a historical
balance; the new value overwrites in place without growing the row
count.

## Exit codes

| code | meaning |
| --- | --- |
| 0 | Success. |
| 1 | Unhandled error. |
| 2 | CSV schema mismatch (fingerprint changed). |
| 3 | Unmatched names, `--accept-new` not passed. |
| 4 | CSV file not found. |

Scripts consuming the CLI can branch on these without parsing stderr.

## Auto-migration

`monarch-ingest transactions` and `monarch-ingest balances` run
`alembic upgrade head` on entry. The first real import against a
fresh DB applies every migration automatically; subsequent imports
re-check and no-op if already at head.

`monarch-ingest status` is read-only and does NOT auto-migrate, so
it's safe to inspect a DB that predates a library bump.

## See also

- [`docs/data-model.md`](data-model.md) — table-by-table schema reference.
- [`docs/decisions/0002-csv-validation-and-hashing.md`](decisions/0002-csv-validation-and-hashing.md) — hash rules, locked.
- [`docs/decisions/0004-cli-typer.md`](decisions/0004-cli-typer.md) — CLI framework + exit-code decision.
