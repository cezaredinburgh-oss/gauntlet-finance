"""Decimal parsing for multi-currency CSV amount fields."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_CURRENCY_TOKEN = re.compile(
    r"(?i)\b(USD|EUR|CZK|GBP|INR|PLN|CHF|BTC|ETH)\b"
)
# Keep digits, sign, and decimal point only after stripping currency noise.
_NON_NUMERIC = re.compile(r"[^\d.\-]")


def detect_currency_token(raw: str | None) -> str | None:
    """Return ISO-like currency code embedded in a cell, if any."""
    if not raw:
        return None
    m = _CURRENCY_TOKEN.search(str(raw))
    if not m:
        return None
    token = m.group(1).upper()
    if token in {"BTC", "ETH"}:
        return None
    return token


def parse_decimal(raw: str | None) -> Decimal:
    """
    Parse amounts like ``$1,922.70``, ``USD 986.26``, ``4,263.92 CZK``, ``-185``.
    """
    if raw is None:
        raise ValueError("empty amount")
    s = str(raw).strip()
    if not s:
        raise ValueError("empty amount")
    s = s.replace("\u00a0", " ").replace("\u202f", " ")
    s = _CURRENCY_TOKEN.sub("", s)
    s = s.replace("$", "").replace(",", "").strip()
    s = _NON_NUMERIC.sub("", s)
    if s in {"", "-", ".", "-."}:
        raise ValueError(f"unparseable amount: {raw!r}")
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"unparseable amount: {raw!r}") from exc


def parse_decimal_optional(raw: str | None) -> Decimal | None:
    """Parse amount or return None for blank cells."""
    if raw is None:
        return None
    if not str(raw).strip():
        return None
    return parse_decimal(raw)


def parse_money_with_currency(
    raw: str | None,
    *,
    default_currency: str | None = None,
) -> tuple[Decimal | None, str | None]:
    """
    Parse a money cell that may embed currency.

    Returns ``(amount, currency)``. Both may be None if cell is empty.
    """
    if raw is None or not str(raw).strip():
        return None, default_currency
    currency = detect_currency_token(raw) or default_currency
    return parse_decimal(raw), currency
