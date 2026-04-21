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

- [ ] **code-reviewer verdict comment posted for the current HEAD SHA**
      (required — the `code-reviewer-gate` CI check blocks merge until a
      matching comment is present; see instructions below)

<details>
<summary>How to post the verdict (expand)</summary>

1. Run the `code-reviewer` subagent on this PR (e.g. via Claude Code's
   built-in `code-reviewer` agent type).
2. Address any blockers; justify dismissed nits in a reply.
3. Post a PR comment whose **first two lines are exactly**:

   ```
   [code-reviewer] verdict: APPROVED
   reviewed-sha: <full 40-char SHA of the tip commit you reviewed>
   ```

   Or, if blockers remain:

   ```
   [code-reviewer] verdict: CHANGES REQUESTED
   reviewed-sha: <full 40-char SHA>
   ```

4. The `code-reviewer-gate` CI job will re-evaluate within ~30 s.
   A new push **resets the gate** — post a fresh verdict for the new SHA.

</details>

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
