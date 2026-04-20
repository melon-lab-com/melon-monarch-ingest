"""Cheap doc-sync guardrail for `docs/data-model.md`.

Asserts every ORM table gets its own section in the docs. Checks
for a level-3 markdown heading whose content is the code-formatted
table name — e.g. `### `transaction`` — which is stricter than a
bare substring search and survives table names that appear in prose
of other sections.
"""

from __future__ import annotations

import re
from pathlib import Path

from monarch_ingest.models import Base

DOC_PATH = Path(__file__).parent.parent.parent / "docs" / "data-model.md"


def test_every_orm_table_has_a_doc_section() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        # Match `### ` followed by the table name wrapped in backticks.
        if not re.search(rf"^###\s+`{re.escape(table.name)}`", doc, re.MULTILINE):
            missing.append(table.name)
    assert not missing, (
        f"docs/data-model.md missing a `### `<table>`` section for: {missing}. "
        "Add a heading and column table for each missing table."
    )
