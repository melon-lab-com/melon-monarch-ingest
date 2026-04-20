# AGENTS.md

Conventions for agent-driven work on `melon-monarch-ingest`. A fresh
agent should be able to open this file and work on the repo without
reading anything else first.

The sibling project [`melon-monarch-cfo`](https://github.com/melon-lab-com/melon-monarch-cfo)
(private) consumes this library. It runs the same conventions where
they apply, plus a few extras (HTMX video-proof gate, per-package
coverage gates) that are out of scope here — this repo is a
library, not an app.

## TL;DR for an incoming agent

1. Read the PR you're about to work on, including the issue it
   references. Don't start coding before you know what "done" means.
2. Branch off `main`. **Every PR off `main`, no stacking** (see
   "Reland rule" below).
3. Before every commit: `uv run ruff check .`, `uv run ruff format .`,
   `uv run mypy`, `uv run pytest -q`. All green or don't commit.
4. Run the `code-reviewer` agent on your own PR and address its
   feedback before merging.
5. Small atomic commits > big mega-commits.
6. On merge: `--squash --delete-branch`. No merge commits.

## Repository layout

```
src/monarch_ingest/      # the library: parsers, dedup hashing, ORM,
                         #   migrations, CLI, rules engine
src/monarch_ingest/
  ├─ alembic.ini         # shipped inside the wheel so the library is
  ├─ migrations/         #   self-sufficient on a fresh install
  └─ ...
tests/                   # pytest + synthetic fixtures (no real Monarch data)
docs/decisions/          # ADRs (0002, 0003, 0004, 0007 moved here
                         #   from cfo under the M7 public split)
docs/                    # import.md, data-model.md — user-facing
scripts/                 # one-off helpers (pre-commit guards, etc.)
.github/                 # CI workflow, PR template, issue templates
```

## Workflow preferences

### Small, atomic commits

One coherent change per commit. One coherent concern per PR. A
10-file PR that does two things is two PRs.

### Reland rule — branch off `main`, no stacking

Every PR starts from `main`. Do not chain `pr-2` off `pr-1`. If
`pr-1` is squash-merged with `--delete-branch`, `pr-2`'s base
vanishes and GitHub auto-closes the stack. This has bitten the
cfo side of this project multiple times; it's a non-negotiable
convention both repos share.

If work really does depend on an unmerged PR, wait for the
dependency to merge and rebase.

### code-reviewer agent on every PR

Before merging, run the `code-reviewer` agent (Claude Code
sub-agent) against the PR. Post its findings as a PR comment or
review. Address blockers. Dismiss nits with a one-line
justification.

### pre-commit is a hard gate

Install once: `uv run pre-commit install`. Thereafter every
commit goes through the full hook stack:

- `trailing-whitespace`, `end-of-file-fixer`, `mixed-line-ending`
  (LF-normalize).
- `check-yaml`, `check-toml`, `check-merge-conflict`,
  `check-added-large-files` (500 KB cap — bump the cap, don't
  work around it, if a repo asset needs to be larger).
- `debug-statements` — catches stray `pdb.set_trace()` / `print`.
- `ruff-check --fix` (may auto-fix lints; re-stage).
- `ruff-format --check` — **fails on drift, does not auto-fix.**
  If it fails, run `uv run ruff format .` manually, re-stage,
  re-commit. This is deliberate: auto-fix silently hides the
  exact issue CI's `ruff format --check` is there to catch, and
  bit the project twice before we flipped this.
- `mypy --strict` — zero errors, zero warnings.
- `gitleaks` — secrets guard.
- `block-real-monarch-csv` — rejects files that look like real
  Monarch exports (`Transactions_*.csv` / `Balances_*.csv`) so
  an operator can't accidentally commit PII. Use the synthetic
  fixtures under `tests/fixtures/` for tests.

Hook bypasses (`--no-verify`) are reserved for explicit, narrow
reasons (e.g. mid-review retry where the hook env is thrashing).
Default answer is "run the hooks."

### Milestone rituals

At every milestone close — even small ones:

1. **Drift check.** Re-invoke the Plan mental model (or a
   `code-reviewer` agent with a drift-check prompt) against the
   merged state. Verify every exit-criteria checkbox from the
   milestone issue matches reality. File drift fixes as
   follow-up PRs before closing the milestone issue.
2. **Simplify pass.** Run the `simplify` Claude Code skill against
   everything the milestone touched. Collapse premature
   abstractions, delete dead paths. Output becomes one cleanup
   PR.
3. **Close the milestone issue** with a summary comment listing
   every merged PR, the exit-criteria table, and what's deferred.

Issue templates for these rituals live in
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) (milestone,
decision, drift-check, simplify).

### Commit trailers

Every agent-authored commit ends with:

```
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

## Agent team

This repo mirrors the private sibling
[`melon-monarch-cfo`](https://github.com/melon-lab-com/melon-monarch-cfo)'s
documented agent team. Definitions for custom personas live in
[`.claude/agents/`](.claude/agents/). Invocation is via Claude
Code's `Agent` tool with `subagent_type` matching the filename.

| Agent                       | File                                                    | Owns                                                                                                                                      | Triggers                                                                                                                  |
| ---                         | ---                                                     | ---                                                                                                                                       | ---                                                                                                                       |
| `code-reviewer`             | built-in Claude Code                                    | Adversarial review across correctness, security, perf, design.                                                                            | Every PR before merge.                                                                                                    |
| `cloud-ops-specialist`      | [`.claude/agents/cloud-ops-specialist.md`](.claude/agents/cloud-ops-specialist.md) | CI workflow infra (not content), release tagging + CHANGELOG, PyPI publishing, version-pin conventions, CI spend, secret flow maintainer-`.env`→GHA. | PRs touching `.github/workflows/*.yml`, `pyproject.toml` `[project]` / `[build-system]`, release-tag PRs, CHANGELOG drift, published-release incidents. |
| `simplify` skill            | bundled Claude Code skill                               | End-of-milestone pruning of premature abstractions.                                                                                        | Milestone close.                                                                                                           |

Scope in this repo is narrower than in cfo — there's no VM, no
Kamal, no TLS, no DNS. If a library release grows cloud surface
later (hosted test runner, PyPI trusted publishing, a signing
service), `cloud-ops-specialist` absorbs it.

Release-touching milestones get a `cloud-ops-specialist` review
before close, in addition to the standard `code-reviewer` gate
and `simplify` pass. No synthetic-vs-real data fence here (that
applies only to cfo); the library's equivalent safeguard is the
pre-existing `block-real-monarch-csv` pre-commit hook.

## Library-specific rules

### Schema and hashing contracts are frozen

[ADR-0002](docs/decisions/0002-csv-validation-and-hashing.md) +
[ADR-0007](docs/decisions/0007-account-identity-and-content-hash.md)
together lock the content-hash payload. A change to either
requires a superseding ADR **and** a data migration that rewrites
every `content_hash` in the DB. Do not edit those fields on a
whim — downstream consumers (cfo) have stable hashes pinned by
content.

### Migrations ship inside the wheel

`src/monarch_ingest/alembic.ini` + `src/monarch_ingest/migrations/`
are bundled via `[tool.hatch.build.targets.wheel.force-include]`.
`migrate.py::_package_dir()` resolves paths relative to
`__file__`, so the same code works in both editable installs
and wheel installs. When adding a migration: drop the revision
file under `src/monarch_ingest/migrations/versions/`, don't move
the baseline. Verify `uv run alembic upgrade head` against a
fresh SQLite file.

### `data-model.md` parity test

`tests/docs/test_data_model_is_current.py` asserts every ORM
table has a `### <name>` section in `docs/data-model.md`. When
you add a table, add the docs section in the same PR or the test
fails.

### No real Monarch exports in the tree

The `block-real-monarch-csv` pre-commit hook rejects files
matching `(?:Transactions|Balances)_*\.csv` anywhere in the tree.
The synthetic fixtures at `tests/fixtures/sample_*.csv` are the
only acceptable CSV inputs for tests.

### ADR numbering

Four ADRs (0002, 0003, 0004, 0007) moved here from the cfo repo
in the M7 public split. Numbering is preserved across both repos
so cross-references still resolve. New ingest-side ADRs start at
0100+ to avoid colliding with future cfo ADRs (cfo is up to 0008
as of 2026-04-19; leave headroom).

## Downstream consumer

`melon-monarch-cfo` pins this library by commit SHA (see its
[`pyproject.toml`](https://github.com/melon-lab-com/melon-monarch-cfo/blob/main/pyproject.toml)
`melon-monarch-ingest @ git+https://…@<sha>` line). A public-API
change in this repo requires a coordinated cfo-side PR that
bumps the pin and absorbs the breakage. Flag breaking changes in
the PR description under "Downstream" so the cfo-side agent
notices.

## Useful one-liners

```sh
uv sync --extra dev                 # install dev deps
uv run ruff check .                 # lint
uv run ruff format .                # format in place
uv run ruff format --check .        # what CI runs (and pre-commit)
uv run mypy                         # type-check (strict)
uv run pytest                       # tests + coverage (85% gate)
uv run alembic upgrade head         # migrate a DB to head
uv run pre-commit run --all-files   # run every hook over the tree
```
