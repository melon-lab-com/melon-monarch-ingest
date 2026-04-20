---
name: Milestone
about: Track a milestone with exit-criteria checklist
title: "[M?] <milestone title>"
labels: ["type:milestone"]
assignees: []
---

## Goal

<One-sentence statement of what this milestone delivers.>

## Exit criteria

<Checklist of concrete, testable items. All must be checked before closing.>

- [ ] Feature code lands on `main` via PR(s)
- [ ] Tests pass in CI (ruff check/format, mypy --strict, pytest + coverage)
- [ ] Pre-commit hooks pass on all touched files
- [ ] Code-reviewer agent has posted a review on each PR and blockers are resolved
- [ ] ADR filed under `docs/decisions/` if a new architectural decision was made
- [ ] Drift check confirms current state still aligned with AGENTS.md + ADRs
- [ ] README / docs updated for user-visible changes
- [ ] Downstream consumer (`melon-monarch-cfo`) still installs cleanly against
      the new commit SHA (spot-check before closing, or bump its pin)

## Scope (included)

- <bullet>

## Out of scope (punt to later milestone)

- <bullet>

## Linked PRs

<Paste PR links as they open. Update on merge/close.>

## Notes from agent runs

<code-reviewer summaries, drift-check verdicts, simplify-pass PRs — either
inline comments on this issue or links to the relevant PR reviews / files.>
