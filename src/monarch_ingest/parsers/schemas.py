"""Pydantic v2 row models for Monarch CSV exports.

See ADR-0002 for the amount-to-cents rule and the verbatim-empty-string
handling of `original_statement` / `notes` / `tags`.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MASK_RE = re.compile(r"\(\.\.\.(\d+)\)")


def extract_mask(raw_account: str) -> str | None:
    """Return the last-N-digit mask from `"CHECKING (...9999) Display"`.

    Returns None for names with no `(...NNNN)` segment (manual-valuation
    accounts like a rental property). We intentionally don't accept
    Unicode ellipsis — if Monarch ever ships one we want to notice.
    """
    m = _MASK_RE.search(raw_account)
    return m.group(1) if m else None


def _amount_to_cents(value: Any) -> int:
    """Convert a CSV amount value (a `str` like "-4.75") to signed cents.

    All inputs go through `Decimal(str(...))` — never `Decimal(float)` —
    to dodge the float-binary-representation trap. Inputs with more
    than 2 decimal places are rejected (Monarch always exports at cent
    precision). `bool` is rejected explicitly because `isinstance(True,
    int)` is True in Python and would otherwise coerce to 100 cents.
    """
    if isinstance(value, bool):
        raise ValueError(f"invalid amount {value!r}")
    try:
        d = Decimal(str(value)) * 100
    except InvalidOperation as e:
        raise ValueError(f"invalid amount {value!r}") from e
    if d != d.to_integral_value():
        raise ValueError(f"amount {value!r} has sub-cent precision")
    return int(d)


def _empty_string_default(value: Any) -> str:
    # Monarch emits empty cells as "" already, but DictReader on a
    # missing key yields None; normalize both to "".
    if value is None:
        return ""
    return str(value)


_ROW_CONFIG = ConfigDict(populate_by_name=True, str_strip_whitespace=False)


class TransactionRow(BaseModel):
    model_config = _ROW_CONFIG

    date: dt.date = Field(alias="Date")
    merchant: str = Field(alias="Merchant")
    category: str = Field(alias="Category")
    raw_account: str = Field(alias="Account")
    original_statement: str = Field(default="", alias="Original Statement")
    notes: str = Field(default="", alias="Notes")
    amount_cents: int = Field(alias="Amount")
    tags: str = Field(default="", alias="Tags")
    owner: str = Field(alias="Owner")

    @field_validator("amount_cents", mode="before")
    @classmethod
    def _parse_amount(cls, v: Any) -> int:
        return _amount_to_cents(v)

    @field_validator("original_statement", "notes", "tags", mode="before")
    @classmethod
    def _normalize_optional_strings(cls, v: Any) -> str:
        return _empty_string_default(v)

    @property
    def account_mask(self) -> str | None:
        return extract_mask(self.raw_account)


class BalanceRow(BaseModel):
    model_config = _ROW_CONFIG

    date: dt.date = Field(alias="Date")
    balance_cents: int = Field(alias="Balance")
    raw_account: str = Field(alias="Account")

    @field_validator("balance_cents", mode="before")
    @classmethod
    def _parse_balance(cls, v: Any) -> int:
        return _amount_to_cents(v)

    @property
    def account_mask(self) -> str | None:
        return extract_mask(self.raw_account)
