<!--
PR template for melon-monarch-ingest.

Policy: every PR requires code-reviewer agent feedback before merge.
The checkbox below is not optional — if it's unchecked, do not merge.

See AGENTS.md at the repo root for the full workflow contract
(reland rule, pre-commit hygiene, milestone rituals).
-->

## Summary

<1–3 sentences on *why*, not just *what*.>

## Linked issues

- Closes #
- Related milestone: #

## Changes

<Bullet list of user-visible or architecturally-interesting changes.
Drop boilerplate like "added tests" if it's the default.>

## Test plan

- [ ] `uv run pytest` passes locally (85% coverage gate)
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy` passes (strict)
- [ ] `uv run pre-commit run --all-files` passes (or CI's `pre-commit` job is green)
- [ ] Schema change? `uv run alembic upgrade head` on a fresh SQLite verifies
- [ ] New ORM table? `docs/data-model.md` gained a matching `### <name>` section

## Required reviews

- [ ] **code-reviewer agent review posted on this PR and blockers resolved**
      (required — invoke the `code-reviewer` subagent, post its review
      as a PR review, address findings or justify dismissal in a comment)

## Data safety

- [ ] No real Monarch CSV exports in the diff (the `block-real-monarch-csv`
      pre-commit guard should have caught this, but confirm)
- [ ] No secrets, tokens, or real account numbers in diffs or test fixtures

## Schema / hash contract

- [ ] No change to the content-hash payload, OR a superseding ADR
      (see [ADR-0002](docs/decisions/0002-csv-validation-and-hashing.md),
      [ADR-0007](docs/decisions/0007-account-identity-and-content-hash.md))
      and a migration that rewrites every `content_hash` in the DB

## Downstream

- [ ] No public-API change visible to `melon-monarch-cfo`, OR a
      coordinated cfo-side PR bumping the pinned SHA is linked below

## Notes for reviewers

<Anything worth flagging — tricky bits, judgment calls, deliberate scope cuts.>
