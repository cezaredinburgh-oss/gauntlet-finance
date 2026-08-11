from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.common.money import parse_decimal, parse_money_with_currency
from backend.common.timeutil import (
    parse_czech_date,
    parse_flexible_datetime,
    reinterpret_naive_utc_wall_as_zone,
)


def test_parse_decimal_currency_noise():
    assert parse_decimal("$1,922.70") == Decimal("1922.70")
    assert parse_decimal("4,263.92 CZK") == Decimal("4263.92")
    assert parse_decimal("-185") == Decimal("-185")
    assert parse_decimal("USD 986.26") == Decimal("986.26")


def test_parse_decimal_european_comma():
    """Raiffeisen / CZ style: comma decimal, optional dot or space thousands."""
    assert parse_decimal("1.234,56") == Decimal("1234.56")
    assert parse_decimal("1234,56") == Decimal("1234.56")
    assert parse_decimal("-1 234,50") == Decimal("-1234.50")
    assert parse_decimal("80,00 CZK") == Decimal("80.00")


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
    # Europe/Prague CET (Nov): 7:14 AM → 06:14 UTC
    assert dt.tzinfo is not None
    assert dt.astimezone(timezone.utc).hour == 6
    assert dt.astimezone(timezone.utc).minute == 14


def test_flexible_datetime_prague_summer_cest():
    """Revolut wall 11:45 AM in August CEST → 09:45 UTC (not 11:45 UTC)."""
    dt = parse_flexible_datetime(
        "Aug 11, 2026, 11:45:00 AM",
        default_tz="Europe/Prague",
    )
    assert dt == datetime(2026, 8, 11, 9, 45, 0, tzinfo=timezone.utc)


def test_flexible_datetime_explicit_z_unchanged():
    dt = parse_flexible_datetime("2026-08-11T11:45:00Z")
    assert dt == datetime(2026, 8, 11, 11, 45, 0, tzinfo=timezone.utc)


def test_reinterpret_naive_utc_wall_as_prague():
    wrong = datetime(2026, 8, 11, 11, 45, 0, tzinfo=timezone.utc)
    fixed = reinterpret_naive_utc_wall_as_zone(wrong, zone="Europe/Prague")
    assert fixed == datetime(2026, 8, 11, 9, 45, 0, tzinfo=timezone.utc)
    # Winter CET: 11:45 wall → 10:45 UTC
    wrong_w = datetime(2026, 1, 15, 11, 45, 0, tzinfo=timezone.utc)
    fixed_w = reinterpret_naive_utc_wall_as_zone(wrong_w, zone=ZoneInfo("Europe/Prague"))
    assert fixed_w == datetime(2026, 1, 15, 10, 45, 0, tzinfo=timezone.utc)
