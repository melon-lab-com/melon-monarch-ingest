# Changelog

Notable changes to `melon-monarch-ingest`. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Infrastructure

- Branch protection on `main`: direct pushes rejected, `code-reviewer-gate`
  required status check, `enforce_admins: true`. Sentinel:
  `[code-reviewer] verdict: APPROVED` in a top-level PR comment.

## [0.1.0] — 2026-04-19

### Added

- Initial public release. Extracted from the private
  `melon-monarch-cfo` project's `src/monarch_ingest/` subtree under
  the M7 "public split" milestone.
- CSV parsers for Monarch Transactions + Balances exports with
  schema-fingerprint drift detection.
- Deterministic content-hashing for re-import dedup (ADR-0002,
  amended by ADR-0007).
- SQLAlchemy 2.0 ORM models covering 12 tables (owner, account +
  alias, category + alias, merchant + alias, transaction,
  balance_snapshot, import_run, raw_import_row, rule).
- Alembic migration baseline with two post-initial revs:
  `08d910599bec` (drop `UNIQUE(mask)` per ADR-0007) and
  `11fdf91169d9` (add `rule` table for the regex rewrite engine).
- Regex-based rewrite rules engine: `rules add|list|remove|apply`
  CLI surface, replayable across history, orphan-safe against
  deleted merchant/category targets.
- `monarch-ingest` Typer CLI: `transactions`, `balances`, `status`,
  `rules` subcommands. Documented exit codes (0/2/3/4) per
  ADR-0004.
- Locked ADRs: 0002 (CSV hashing), 0003 (sync SQLAlchemy),
  0004 (Typer), 0007 (account identity).

### Tests

- 80+ unit + integration tests against synthetic CSV fixtures.
- 85 % coverage floor enforced in CI.
- Fixtures live at `tests/fixtures/sample_*.csv`; real Monarch
  exports are explicitly blocked by a pre-commit guard.

[0.1.0]: https://github.com/melon-lab-com/melon-monarch-ingest/releases/tag/v0.1.0
