#!/usr/bin/env python3
"""Pre-commit guard: refuse to stage real Monarch CSV exports.

Monarch exports use the filenames `Transactions_<timestamp>.csv` and
`Balances_<timestamp>.csv`. Those files contain real financial data and must
never enter git history. This script rejects any staged file matching that
pattern, anywhere in the tree — including `tests/fixtures/`, so a careless
copy of a real export into the fixtures dir is caught too.

Synthetic test data must use a different filename (e.g.
`tests/fixtures/sample_transactions.csv`).
"""

from __future__ import annotations

import re
import sys

_FORBIDDEN = re.compile(r"(?:^|/)(?:Transactions|Balances)_[^/]+\.csv$")


def main(argv: list[str]) -> int:
    bad = [path for path in argv if _FORBIDDEN.search(path)]
    if not bad:
        return 0

    print("Refused to commit real Monarch CSV exports:", file=sys.stderr)
    for path in bad:
        print(f"  - {path}", file=sys.stderr)
    print(
        "\nThese filenames match Monarch export format and likely contain real\n"
        "financial data. Move them outside the repo, or — if you need test data —\n"
        "put synthetic CSVs in tests/fixtures/ with a name that does NOT match\n"
        "Transactions_*.csv / Balances_*.csv.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
