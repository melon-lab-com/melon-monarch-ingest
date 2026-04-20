# melon-monarch-ingest

Monarch Money CSV ingest library: parsers, dedup hashing, SQLAlchemy
models, Alembic migrations, and a `monarch-ingest` CLI.

Monarch has no public developer API — the only way out is the
"Export" buttons on the transactions and balances pages. This
library turns those CSV dumps into a local SQLite (or Postgres)
database you can query, back up, and build tools on top of.

## Features

- **Deterministic content hashing** so re-importing the same CSV
  doesn't duplicate rows, even when Monarch reorders them.
- **Schema-fingerprint guard** — the CSV shape is locked; a
  Monarch-side header change fails the import loudly instead of
  silently shifting columns.
- **Account-rename stability** ([ADR-0007](docs/decisions/0007-account-identity-and-content-hash.md)):
  when Monarch renames an account mid-history, the importer keeps
  the original canonical name so previously-computed content hashes
  stay valid; the new name lands in `account_alias`.
- **User-defined rewrite rules** ([docs/data-model.md#rule](docs/data-model.md#rule)):
  regex → `merchant_id` / `category_id`, replayable across the
  full history via `monarch-ingest rules apply`.
- **Integer cents on the hot path** — no `Float` or `Decimal` in
  the DB, so totals never drift by a penny on re-import.

## Install

Editable from Git (most common for library consumers):

```sh
pip install "git+https://github.com/melon-lab-com/melon-monarch-ingest"
```

Or clone and use [uv](https://github.com/astral-sh/uv):

```sh
git clone https://github.com/melon-lab-com/melon-monarch-ingest
cd melon-monarch-ingest
uv python install 3.12
uv sync --extra dev
.venv/bin/pre-commit install
.venv/bin/pytest
```

## Quick start

Export your Monarch CSVs (Transactions, Balances), then:

```sh
monarch-ingest transactions path/to/Transactions.csv --accept-new
monarch-ingest balances     path/to/Balances.csv     --accept-new
monarch-ingest status
```

See [`docs/import.md`](docs/import.md) for the full workflow —
exit codes, schema-drift recovery, and the `--accept-new` rule.

By default the library writes to `sqlite:///./monarch.db` in the
current working directory. Point at a different database with the
`MONARCH_DB_URL` environment variable or the `--db-url` CLI flag.

## Rules engine

Match a merchant's raw statement line with a regex and rewrite the
canonical `merchant_id` or `category_id`:

```sh
# Every "SBUX" charge becomes merchant id 42 (which you've already
# created in the merchant table). Case-insensitive.
monarch-ingest rules add merchant "SBUX" 42 --priority 10

# List what's active.
monarch-ingest rules list

# Replay every active rule over the full transaction history
# (useful after adding or re-prioritizing rules).
monarch-ingest rules apply
```

Rules run automatically against newly-inserted rows during
`monarch-ingest transactions`, so ongoing imports pick up your
overrides from first sight.

See [`docs/data-model.md`](docs/data-model.md) for the full rule
table contract.

## Data model

Ten tables (`owner`, `account`, `account_alias`, `category`,
`category_alias`, `merchant`, `merchant_alias`, `transaction`,
`balance_snapshot`, `import_run`, `raw_import_row`, `rule`). Full
per-table schema + design rationale at
[`docs/data-model.md`](docs/data-model.md).

## Architecture Decision Records

Locked choices:

- [ADR-0002](docs/decisions/0002-csv-validation-and-hashing.md) — CSV validation and the content-hash rule.
- [ADR-0003](docs/decisions/0003-sqlalchemy-sync.md) — sync SQLAlchemy over async.
- [ADR-0004](docs/decisions/0004-cli-typer.md) — Typer over Click for the CLI.
- [ADR-0007](docs/decisions/0007-account-identity-and-content-hash.md) — account identity rule under Monarch rename churn.

## Status

`0.1.0` — extracted from the private `melon-monarch-cfo` project in
April 2026. The data-model and hashing contracts are frozen by ADR
and validated by tests; breaking either requires a superseding ADR
and a migration.

## License

MIT — see [`LICENSE`](LICENSE). Contributions welcome: please file
an issue first if the change is non-trivial, and include a
regression test. The repo runs `ruff check`, `ruff format --check`,
`mypy --strict`, and `pytest` with 85 % coverage gate on every
pull request (see `.github/workflows/ci.yml`).
