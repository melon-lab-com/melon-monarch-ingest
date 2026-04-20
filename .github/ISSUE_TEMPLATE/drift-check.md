---
name: Drift check
about: End-of-milestone drift check comparing repo state vs AGENTS.md + ADRs + the milestone's exit criteria
title: "[Drift] M? end-of-milestone drift check"
labels: ["type:drift-check", "status:needs-input"]
assignees: []
---

## Which milestone is closing?

<Link to the milestone issue.>

## What shipped

<Bullet list or PR links — concrete changes that landed on `main` during this milestone.>

## Questions

1. Does the current repo state satisfy every exit criterion checkbox on the milestone issue?
2. Did we drift from any locked ADR (0002 hashing, 0003 sync SQLAlchemy, 0004 Typer, 0007 account identity)?
3. Are `docs/data-model.md` and `AGENTS.md` still accurate? Any undocumented-but-shipped conventions?
4. Is `melon-monarch-cfo` still green against the latest commit SHA (quick local rebuild)?

## Verdict

<Paste the drift-check agent's output here as a comment, or link to the
follow-up PR(s) that close any gaps found. Close this issue only after
either the docs / code are updated to match reality, or the drift is
intentionally accepted with a short note here explaining why.>
