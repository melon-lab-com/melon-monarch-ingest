"""Tests for the alias resolvers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from monarch_ingest.importers.result import ResolveContext
from monarch_ingest.models import (
    Account,
    AccountAlias,
    Category,
    CategoryAlias,
    Merchant,
    MerchantAlias,
    Owner,
)
from monarch_ingest.resolve import (
    resolve_account,
    resolve_category,
    resolve_merchant,
    resolve_owner,
)


class TestResolveOwner:
    def test_existing_owner_by_name(self, session: Session) -> None:
        existing = Owner(name="Alice")
        session.add(existing)
        session.flush()
        ctx = ResolveContext(accept_new=False)

        owner = resolve_owner(session, "Alice", ctx)

        assert owner is not None
        assert owner.id == existing.id
        assert ctx.unmatched == []

    def test_missing_without_accept_new_records_unmatched(self, session: Session) -> None:
        ctx = ResolveContext(accept_new=False)
        owner = resolve_owner(session, "NewOwner", ctx)
        assert owner is None
        assert ctx.unmatched == ["owner: NewOwner"]

    def test_missing_with_accept_new_creates(self, session: Session) -> None:
        ctx = ResolveContext(accept_new=True)
        owner = resolve_owner(session, "NewOwner", ctx)
        assert owner is not None
        assert owner.name == "NewOwner"
        assert ctx.unmatched == []


class TestResolveMerchant:
    def test_alias_hit(self, session: Session) -> None:
        m = Merchant(canonical_name="Acme Coffee")
        session.add(m)
        session.flush()
        session.add(MerchantAlias(merchant_id=m.id, raw_name="ACME COFFEE #42"))
        session.flush()
        ctx = ResolveContext(accept_new=False)

        resolved = resolve_merchant(session, "ACME COFFEE #42", ctx)

        assert resolved is not None
        assert resolved.id == m.id

    def test_canonical_name_hit(self, session: Session) -> None:
        m = Merchant(canonical_name="Acme Coffee")
        session.add(m)
        session.flush()
        ctx = ResolveContext(accept_new=False)

        resolved = resolve_merchant(session, "Acme Coffee", ctx)

        assert resolved is not None
        assert resolved.id == m.id

    def test_missing_with_accept_new_creates_with_alias(self, session: Session) -> None:
        ctx = ResolveContext(accept_new=True)
        resolved = resolve_merchant(session, "BrandNew", ctx)
        assert resolved is not None
        assert resolved.canonical_name == "BrandNew"
        # Alias row with the same raw name should now exist.
        alias_count = session.query(MerchantAlias).filter_by(raw_name="BrandNew").count()
        assert alias_count == 1


class TestResolveCategory:
    def test_alias_hit(self, session: Session) -> None:
        c = Category(name="Restaurants & Bars")
        session.add(c)
        session.flush()
        session.add(CategoryAlias(category_id=c.id, raw_name="Dining"))
        session.flush()
        ctx = ResolveContext(accept_new=False)

        resolved = resolve_category(session, "Dining", ctx)

        assert resolved is not None
        assert resolved.id == c.id

    def test_canonical_name_hit(self, session: Session) -> None:
        c = Category(name="Groceries")
        session.add(c)
        session.flush()
        ctx = ResolveContext(accept_new=False)

        resolved = resolve_category(session, "Groceries", ctx)

        assert resolved is not None
        assert resolved.id == c.id

    def test_missing_with_accept_new_creates_with_alias(self, session: Session) -> None:
        ctx = ResolveContext(accept_new=True)
        resolved = resolve_category(session, "Rental", ctx)
        assert resolved is not None
        assert resolved.name == "Rental"
        alias_count = session.query(CategoryAlias).filter_by(raw_name="Rental").count()
        assert alias_count == 1

    def test_missing_without_accept_new_appends(self, session: Session) -> None:
        ctx = ResolveContext(accept_new=False)
        assert resolve_category(session, "Rental", ctx) is None
        assert ctx.unmatched == ["category: Rental"]


class TestResolveAccount:
    def test_alias_hit(self, session: Session) -> None:
        a = Account(monarch_name="CHECKING (...9999)", mask="9999")
        session.add(a)
        session.flush()
        session.add(AccountAlias(account_id=a.id, raw_name="CHECKING (...9999)"))
        session.flush()
        ctx = ResolveContext(accept_new=False)

        resolved = resolve_account(session, "CHECKING (...9999)", "9999", ctx)

        assert resolved is not None
        assert resolved.id == a.id

    def test_rename_via_mask_records_alias_when_accept_new(self, session: Session) -> None:
        a = Account(monarch_name="CHECKING (...9999)", mask="9999")
        session.add(a)
        session.flush()
        session.add(AccountAlias(account_id=a.id, raw_name="CHECKING (...9999)"))
        session.flush()
        ctx = ResolveContext(accept_new=True)

        # Monarch renamed the account but the mask is stable.
        resolved = resolve_account(session, "CHECKING RENAMED (...9999)", "9999", ctx)

        assert resolved is not None
        assert resolved.id == a.id
        # The new raw name is now an alias for next time.
        alias_count = (
            session.query(AccountAlias).filter_by(raw_name="CHECKING RENAMED (...9999)").count()
        )
        assert alias_count == 1
        # monarch_name is preserved (historical display name).
        session.refresh(a)
        assert a.monarch_name == "CHECKING (...9999)"
        assert ctx.unmatched == []

    def test_rename_via_mask_is_read_only_when_accept_new_false(self, session: Session) -> None:
        # Strict contract: `accept_new=False` must never persist rows.
        # When mask matches but raw_name is new, resolve returns the
        # existing account *without* creating an alias — the alias
        # bookkeeping defers to the next accept_new=True run.
        a = Account(monarch_name="CHECKING (...9999)", mask="9999")
        session.add(a)
        session.flush()
        session.add(AccountAlias(account_id=a.id, raw_name="CHECKING (...9999)"))
        session.flush()
        ctx = ResolveContext(accept_new=False)

        resolved = resolve_account(session, "CHECKING RENAMED (...9999)", "9999", ctx)

        assert resolved is not None
        assert resolved.id == a.id
        # No new alias row was created.
        alias_count = (
            session.query(AccountAlias).filter_by(raw_name="CHECKING RENAMED (...9999)").count()
        )
        assert alias_count == 0
        assert ctx.unmatched == []

    def test_missing_mask_and_name_without_accept_new(self, session: Session) -> None:
        ctx = ResolveContext(accept_new=False)
        resolved = resolve_account(session, "NewAccount (...5555)", "5555", ctx)
        assert resolved is None
        assert ctx.unmatched == ["account: NewAccount (...5555)"]

    def test_manual_valuation_account_has_no_mask(self, session: Session) -> None:
        ctx = ResolveContext(accept_new=True)
        resolved = resolve_account(session, "Rental Property at Fake Address", None, ctx)
        assert resolved is not None
        assert resolved.mask is None
        assert resolved.is_manual_valuation is True

    def test_create_adds_alias(self, session: Session) -> None:
        ctx = ResolveContext(accept_new=True)
        resolved = resolve_account(session, "New (...7777)", "7777", ctx)
        assert resolved is not None
        alias_count = session.query(AccountAlias).filter_by(account_id=resolved.id).count()
        assert alias_count == 1

    def test_canonical_name_hit_without_alias_records_alias_on_accept_new(
        self, session: Session
    ) -> None:
        # Edge case: an account exists but has no alias row (e.g.
        # pre-seeded by a migration or a bulk fixture). Canonical-name
        # hit under `--accept-new` should self-heal by adding the alias.
        a = Account(monarch_name="CHECKING (...9999)", mask="9999")
        session.add(a)
        session.flush()
        ctx = ResolveContext(accept_new=True)

        resolved = resolve_account(session, "CHECKING (...9999)", "9999", ctx)

        assert resolved is not None
        assert resolved.id == a.id
        alias_count = session.query(AccountAlias).filter_by(raw_name="CHECKING (...9999)").count()
        assert alias_count == 1

    def test_canonical_name_hit_before_mask(self, session: Session) -> None:
        # ADR-0007: step 2 (canonical `monarch_name` match) fires before
        # the mask hint. Even if another account shares the mask, an
        # exact-name match resolves unambiguously.
        a = Account(monarch_name="CHECKING (...9999)", mask="9999")
        b = Account(monarch_name="CHECKING RENAMED (...9999)", mask="9999")
        session.add_all([a, b])
        session.flush()
        ctx = ResolveContext(accept_new=False)

        resolved = resolve_account(session, "CHECKING (...9999)", "9999", ctx)

        assert resolved is not None
        assert resolved.id == a.id

    def test_joint_card_ambiguous_mask_falls_through(self, session: Session) -> None:
        # Issue #30 regression: two accounts share mask `9680` (primary
        # holder + authorized-user). A CSV row with a third new name
        # and that mask must NOT silently match one of the siblings —
        # without `accept_new` it falls through to `unmatched`.
        primary = Account(monarch_name="CHASE COLLEGE (...9680)", mask="9680")
        secondary = Account(monarch_name="CHASE COLLEGE (...9680) YY", mask="9680")
        session.add_all([primary, secondary])
        session.flush()
        ctx = ResolveContext(accept_new=False)

        resolved = resolve_account(session, "CHASE COLLEGE (...9680) Third", "9680", ctx)

        assert resolved is None
        assert ctx.unmatched == ["account: CHASE COLLEGE (...9680) Third"]

    def test_same_batch_duplicate_raw_name_is_idempotent(self, session: Session) -> None:
        # Defensive regression: repeated `resolve_account` calls for the
        # same new raw_name in the same batch must not duplicate the
        # alias or create a second account. Step 1 (alias lookup) is
        # the first catch; the idempotent alias-write helper is the
        # second line of defense.
        ctx = ResolveContext(accept_new=True)
        a1 = resolve_account(session, "NEW CARD (...5555)", "5555", ctx)
        a2 = resolve_account(session, "NEW CARD (...5555)", "5555", ctx)

        assert a1 is not None and a2 is not None
        assert a1.id == a2.id
        alias_rows = session.query(AccountAlias).filter_by(raw_name="NEW CARD (...5555)").count()
        assert alias_rows == 1
        account_rows = session.query(Account).count()
        assert account_rows == 1

    def test_joint_card_ambiguous_mask_creates_under_accept_new(self, session: Session) -> None:
        # With `accept_new=True`, the ambiguous-mask row is created as
        # a new account (no silent merge into either sibling). The
        # operator's `--accept-new` flag is the explicit signal that
        # surprise new account rows are OK.
        primary = Account(monarch_name="CHASE COLLEGE (...9680)", mask="9680")
        secondary = Account(monarch_name="CHASE COLLEGE (...9680) YY", mask="9680")
        session.add_all([primary, secondary])
        session.flush()
        ctx = ResolveContext(accept_new=True)

        resolved = resolve_account(session, "CHASE COLLEGE (...9680) Third", "9680", ctx)

        assert resolved is not None
        assert resolved.id not in {primary.id, secondary.id}
        assert resolved.monarch_name == "CHASE COLLEGE (...9680) Third"
