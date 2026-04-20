# 0004 — CLI framework: Typer over Click / argparse

- **Status:** Accepted
- **Date:** 2026-04-18
- **Milestone:** M2 (Ingest lib)

## Context

M2 ships a CLI entry point `monarch-ingest` with three subcommands:
`transactions <file>`, `balances <file>`, `status`. Shared options
`--db-url` and `--accept-new` apply to the import subcommands.

## Decision

**Typer** — typed function signatures as command definitions. Built on
Click, so the escape hatch to raw Click is available if needed.

### Exit codes

- `0` — success.
- `1` — unhandled error (default Typer behavior).
- `2` — CSV schema mismatch (`SchemaMismatchError`). The operator
  needs to update the ingest library to support the new schema.
- `3` — unmatched names (`UnmatchedNamesError`). The operator can
  re-run with `--accept-new` or fix the CSV.
- `4` — CSV path does not exist.

Scripts consuming this CLI can distinguish these cases by exit code
without parsing stderr.

### Migrations

The CLI auto-runs Alembic `upgrade head` on every import invocation.
This matches the "just works" DX goal — the user doesn't have to
remember a `migrate` step. The read-only `status` command does NOT
auto-migrate (so it can run against a DB that predates a schema bump
without silently migrating it).

## Consequences

### Positive

- Python-type-hinted command signatures mesh with mypy strict; every
  CLI arg is typed.
- Generates `--help` from docstrings and annotations without
  boilerplate.
- Click underneath means the broader Click ecosystem (testing with
  `CliRunner`, completion, shell-integration) is available.
- Small install footprint (~100KB).

### Negative / trade-offs

- Adds `typer` (and its `rich` dep for pretty output) to
  `monarch_ingest`'s runtime dependencies. Fine — the library is
  positioned as a public lib where a CLI dep is expected.
- Typer's default exit code on raised exception is 1; we override in
  the CLI module to emit domain-specific codes (2/3/4) for scripted
  consumers.

### Alternatives considered and rejected

- **Click** directly. Equivalent capability, but the decorator-based
  command definition is less congenial to mypy strict than Typer's
  signature-derived form. Rejected.
- **argparse**. Stdlib so no dep, but three subcommands with shared
  options require 50+ lines of boilerplate and no ergonomic `--help`.
  Rejected for the complexity budget at our scale.
- **Fire** (Google). Auto-generates CLI from class hierarchies but
  with weak type signatures. Rejected — inconsistent with
  mypy-strict-everywhere.

## References

- [Typer docs](https://typer.tiangolo.com/).
- [`src/monarch_ingest/cli.py`](../../src/monarch_ingest/cli.py).
