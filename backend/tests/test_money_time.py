from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.common.money import parse_decimal, parse_money_with_currency
from backend.common.timeutil import parse_czech_date, parse_flexible_datetime


def test_parse_decimal_currency_noise():
    assert parse_decimal("$1,922.70") == Decimal("1922.70")
    assert parse_decimal("4,263.92 CZK") == Decimal("4263.92")
    assert parse_decimal("-185") == Decimal("-185")
    assert parse_decimal("USD 986.26") == Decimal("986.26")


def test_parse_money_with_currency():
    amount, ccy = parse_money_with_currency("94.75 CZK")
    assert amount == Decimal("94.75")
    assert ccy == "CZK"


def test_czech_date():
    assert parse_czech_date("28.07.2026") == date(2026, 7, 28)
    assert parse_czech_date("30.07.2026 05:54") == date(2026, 7, 30)


def test_flexible_datetime_narrow_space_am_pm():
    raw = "Nov 18, 2024, 7:14:54\u202fAM"
    dt = parse_flexible_datetime(raw)
    assert dt.year == 2024 and dt.month == 11 and dt.day == 18
