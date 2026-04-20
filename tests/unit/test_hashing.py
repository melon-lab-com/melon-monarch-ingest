"""Hash-stability tests for `monarch_ingest.hashing`.

These are the guardrail against accidental changes to the content-hash
rule. Any change to the pinned values here means we've broken the
dedup contract — see ADR-0002 (base rules) and ADR-0007 (account
field: canonical `monarch_name`).
"""

from __future__ import annotations

import datetime as dt

from hypothesis import given
from hypothesis import strategies as st

from monarch_ingest.hashing import content_hash, schema_fingerprint


class TestContentHashGoldenValues:
    """Pinned hashes. Changing these is a breaking migration."""

    def test_simple_expense(self) -> None:
        h = content_hash(
            date=dt.date(2025, 1, 2),
            amount_cents=-475,
            account_key="CREDIT CARD (...1111) Test Card",
            original_statement="ACME COFFEE #42",
            notes="",
        )
        assert h == ("aa50187f6f78133ebc9ff745a0d636e76b31602f5f018fad9ec0f364614f704a")

    def test_income_with_notes(self) -> None:
        h = content_hash(
            date=dt.date(2025, 1, 5),
            amount_cents=350000,
            account_key="CHECKING (...9999)",
            original_statement="ORIG CO NAME:SYNTHETIC SOL CO ENTRY DESCR:PAYROLL",
            notes="regular paycheck",
        )
        assert h == ("cd8360678d435f22c4dfa74b92fc90bc8d907e1eb878b8075f41222b31ddb65f")

    def test_rental_income(self) -> None:
        h = content_hash(
            date=dt.date(2025, 2, 10),
            amount_cents=220000,
            account_key="CHECKING (...9999)",
            original_statement="RENT PAYMENT MARCH",
            notes="",
        )
        assert h == ("7e5efde90c473f336904e2477127302c23bb77c9e0dc96a7bd3d05021ac4eaae")

    def test_joint_card_siblings_do_not_collide(self) -> None:
        # Regression for issue #30: two accounts sharing a mask (joint
        # credit-card primary + authorized-user) produced identical
        # content_hashes under the pre-ADR-0007 rule, silently
        # deduping real cashflow on the secondary card. Under ADR-0007
        # the hash is keyed on the resolved account's canonical
        # `monarch_name`, so siblings diverge even when the CSV row
        # content and mask are otherwise identical.
        primary = content_hash(
            date=dt.date(2025, 1, 1),
            amount_cents=-100,
            account_key="CREDIT CARD (...9680) Chase College",
            original_statement="COLLEGE CAMPUS COFFEE",
            notes="",
        )
        secondary = content_hash(
            date=dt.date(2025, 1, 1),
            amount_cents=-100,
            account_key="CREDIT CARD (...9680) Chase College YY",
            original_statement="COLLEGE CAMPUS COFFEE",
            notes="",
        )
        assert primary != secondary
        # Pinned so a future refactor can't accidentally re-collapse.
        assert primary == "0b1c8ae28cd2c1293ed8203376846f6c27c5cdefa5b0ca119ebca60701e2b18e"
        assert secondary == "1ddcc3aa59e9f34d774c57d57d2edc67e6f70eb20db8fe0bf7aab190aba96b2b"

    def test_pipe_in_fields_does_not_collide(self) -> None:
        # Regression: without escaping, `statement="ACME|COFFEE" notes="tip"`
        # and `statement="ACME" notes="COFFEE|tip"` produced the same
        # payload. Percent-encoding the delimiter makes them distinct.
        h_a = content_hash(
            date=dt.date(2025, 1, 1),
            amount_cents=-100,
            account_key="CARD A",
            original_statement="ACME|COFFEE",
            notes="tip",
        )
        h_b = content_hash(
            date=dt.date(2025, 1, 1),
            amount_cents=-100,
            account_key="CARD A",
            original_statement="ACME",
            notes="COFFEE|tip",
        )
        assert h_a != h_b

    def test_percent_in_fields_does_not_collide(self) -> None:
        # Escaping `%` itself prevents the escape-of-an-escape collision:
        # `"a%7Cb"` (literal text) must not hash the same as `"a|b"`.
        h_literal = content_hash(
            date=dt.date(2025, 1, 1),
            amount_cents=1,
            account_key="CARD X",
            original_statement="a%7Cb",
            notes="",
        )
        h_pipe = content_hash(
            date=dt.date(2025, 1, 1),
            amount_cents=1,
            account_key="CARD X",
            original_statement="a|b",
            notes="",
        )
        assert h_literal != h_pipe


class TestContentHashProperties:
    @given(
        st.dates(),
        st.integers(min_value=-10_000_000, max_value=10_000_000),
        st.text(min_size=1, max_size=80),
        st.text(max_size=200),
        st.text(max_size=200),
    )
    def test_is_deterministic(
        self,
        date: dt.date,
        amount_cents: int,
        account_key: str,
        statement: str,
        notes: str,
    ) -> None:
        kwargs = {
            "date": date,
            "amount_cents": amount_cents,
            "account_key": account_key,
            "original_statement": statement,
            "notes": notes,
        }
        assert content_hash(**kwargs) == content_hash(**kwargs)  # type: ignore[arg-type]

    @given(st.integers(min_value=-10_000_000, max_value=10_000_000))
    def test_amount_differentiates(self, amount_cents: int) -> None:
        base_kwargs: dict[str, object] = {
            "date": dt.date(2025, 1, 1),
            "account_key": "CARD Z",
            "original_statement": "x",
            "notes": "",
        }
        h1 = content_hash(amount_cents=amount_cents, **base_kwargs)  # type: ignore[arg-type]
        h2 = content_hash(amount_cents=amount_cents + 1, **base_kwargs)  # type: ignore[arg-type]
        assert h1 != h2

    @given(
        st.tuples(
            st.dates(),
            st.integers(min_value=-1_000_000, max_value=1_000_000),
            st.text(min_size=1, max_size=40),
            st.text(max_size=60),
            st.text(max_size=60),
        ),
        st.tuples(
            st.dates(),
            st.integers(min_value=-1_000_000, max_value=1_000_000),
            st.text(min_size=1, max_size=40),
            st.text(max_size=60),
            st.text(max_size=60),
        ),
    )
    def test_different_rows_produce_different_hashes(
        self,
        row_a: tuple[dt.date, int, str, str, str],
        row_b: tuple[dt.date, int, str, str, str],
    ) -> None:
        # Injectivity property: any two rows that differ in any locked
        # field must produce different hashes. This is the property
        # that would have caught the `|`-collision bug.
        def _h(row: tuple[dt.date, int, str, str, str]) -> str:
            d, amt, key, stmt, notes = row
            return content_hash(
                date=d,
                amount_cents=amt,
                account_key=key,
                original_statement=stmt,
                notes=notes,
            )

        if row_a != row_b:
            assert _h(row_a) != _h(row_b)


class TestSchemaFingerprint:
    def test_transaction_headers_pinned(self) -> None:
        fp = schema_fingerprint(
            [
                "Date",
                "Merchant",
                "Category",
                "Account",
                "Original Statement",
                "Notes",
                "Amount",
                "Tags",
                "Owner",
            ]
        )
        assert fp == ("ffbf0729a7c2371e9fad2a388903b602cd9fb0e5cd8aaa30be04ab187675fbdb")

    def test_balance_headers_pinned(self) -> None:
        fp = schema_fingerprint(["Date", "Balance", "Account"])
        assert fp == ("93c613dc85a171e01b204a0fad18a59d04284ca491dd1f96ed6503340b0111f5")

    def test_column_order_is_irrelevant(self) -> None:
        # Monarch can reorder columns without invalidating dedup.
        a = schema_fingerprint(["Date", "Merchant", "Amount"])
        b = schema_fingerprint(["Merchant", "Amount", "Date"])
        assert a == b

    def test_case_sensitive(self) -> None:
        # Casing change → fingerprint mismatch → we want to notice.
        a = schema_fingerprint(["Date", "Amount"])
        b = schema_fingerprint(["date", "amount"])
        assert a != b

    def test_added_column_changes_fingerprint(self) -> None:
        a = schema_fingerprint(["Date", "Amount"])
        b = schema_fingerprint(["Date", "Amount", "Category"])
        assert a != b
