"""Content-hash and schema-fingerprint functions.

**These algorithms are frozen.** See ADR-0002 for the base hash rules
(delimiter, escaping, date/amount formatting, UTF-8 encoding) and
ADR-0007 for the account-field amendment. The content-hash identity
tuple uses the resolved account's canonical `monarch_name` — not the
CSV-derived mask — so joint cards with a shared last-4 no longer
collide. Any further rule change is a breaking migration that
invalidates every `content_hash` already in the DB. Pinned
golden-hash tests live in `tests/unit/test_hashing.py`.
"""

from __future__ import annotations

import datetime as dt
import hashlib


def _escape(s: str) -> str:
    # Percent-encode the delimiter (and the escape character itself)
    # so a literal `|` or `%` in a merchant-supplied field can't bleed
    # across field boundaries and collide with a different row. See
    # ADR-0002 rule 1.
    return s.replace("%", "%25").replace("|", "%7C")


def content_hash(
    *,
    date: dt.date,
    amount_cents: int,
    account_key: str,
    original_statement: str,
    notes: str,
) -> str:
    """Return the sha256 dedup identity of a transaction row.

    Locked per ADR-0002 + ADR-0007:
      - `|`-joined. String fields are percent-escaped (`%` → `%25`,
        `|` → `%7C`) so embedded delimiters can't silently cross
        field boundaries.
      - date: ISO-8601 `YYYY-MM-DD`.
      - amount_cents: signed decimal via `str(int)`.
      - account_key: the resolved account's canonical `monarch_name`
        (ADR-0007). Caller looks up the account first (alias →
        canonical name → unique-mask hint) and passes the canonical
        name; the raw CSV `Account` column never feeds the hash
        directly. Two accounts can never collide (UNIQUE on
        `account.monarch_name`), and renames leave the canonical
        name untouched, so the hash stays stable across renames.
      - original_statement / notes: verbatim (empty cells → "").
      - UTF-8 encoding throughout.
    """
    payload = (
        f"{date.isoformat()}"
        f"|{amount_cents}"
        f"|{_escape(account_key)}"
        f"|{_escape(original_statement)}"
        f"|{_escape(notes)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def schema_fingerprint(headers: list[str]) -> str:
    """Return the sha256 fingerprint of a CSV header row.

    Headers are case-sensitive and sorted lexicographically before
    hashing, so column-order changes don't invalidate the fingerprint
    but added / removed / renamed columns do.
    """
    payload = ",".join(sorted(headers))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
