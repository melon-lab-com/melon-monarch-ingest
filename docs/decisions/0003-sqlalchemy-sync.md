# 0003 — SQLAlchemy 2.0 sync engine, plain `Mapped[...]` declarative style

- **Status:** Accepted
- **Date:** 2026-04-18
- **Milestone:** M2 (Ingest lib)

## Context

M2 stands up the SQLAlchemy 2.0 models and DB session for the ingest
library. Two choices need to be locked before writing the first model:

1. **Sync vs async SQLAlchemy.** 2.0 supports both.
2. **Declarative style.** 2.0 offers `DeclarativeBase` with plain
   `Mapped[...]` annotations, or `MappedAsDataclass` for dataclass
   integration.

Choices propagate through every subsequent PR (parsers, importers, CLI,
eventually the M4 FastAPI layer).

## Decision

**Engine style: synchronous `Engine` + `Session`.**

**Declarative style: plain `DeclarativeBase` with `Mapped[...]`
annotations.** Not `MappedAsDataclass`.

## Consequences

### Positive

- The importer is a single-CSV, single-process batch job. Concurrency
  gives us nothing — SQLite serializes writes anyway — and async
  doubles the surface area (separate session factory, `await`
  everywhere, test harness tangles).
- `monarch-ingest` as a public library stays trivially usable from a
  plain script or Jupyter notebook. No `asyncio.run(...)` wrapper
  required for interactive use.
- Plain `Mapped[...]` composes with mypy-strict without the
  `MappedAsDataclass` pitfalls around `__init__` overriding and
  `default_factory`.
- M4's FastAPI layer can mount sync sessions via
  `fastapi.concurrency.run_in_threadpool` if we ever want async
  endpoints. No rewrite, just an adapter.

### Negative / trade-offs

- If M4 decides to go fully async (SQLAlchemy async sessions end-to-end),
  we would refactor the session-provider layer. Expected cost: one
  adapter module, not a rewrite — accepted.
- `MappedAsDataclass` would have given us free `__init__` + `__repr__`.
  We give that up; tests and the importer construct models explicitly
  and we write `__repr__` where useful.

### Alternatives considered and rejected

- **Async SQLAlchemy.** Considered and rejected — we have no concurrency
  story. SQLite single-writer lock makes "parallel imports" a phantom
  benefit. Reconsidered if and only if we move to Postgres with a
  concurrent-write workload.
- **`MappedAsDataclass`.** Nice ergonomics but interacts poorly with
  custom `__init__` and with mypy-strict's handling of
  `default_factory`. For ~11 tables with straightforward fields, plain
  `Mapped[...]` wins on clarity.
- **Raw SQL + `sqlite3` stdlib.** Would remove two deps. Rejected: we
  need Alembic's migration story, and plain-SQL dedup/upsert is not the
  hill we want to die on.

## References

- [docs/plan.md §1](../plan.md) — stack choice.
- [SQLAlchemy 2.0 ORM quickstart](https://docs.sqlalchemy.org/en/20/orm/quickstart.html).
