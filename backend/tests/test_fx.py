from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from backend.engines.fx import FXService
from backend.schema.models import FXRate, FXSource
from backend.tests.helpers import TS, fx_rate


def test_convert_usd_to_czk_exact_cnb():
    svc = FXService()
    svc.load_rates(
        [fx_rate(rate_date=date(2026, 7, 20), base="USD", rate="23.10")]
    )
    out = svc.convert(Decimal("100"), "USD", "CZK", date(2026, 7, 20))
    assert out == Decimal("2310.00")


def test_convert_identity_and_missing_returns_none():
    svc = FXService()
    assert svc.convert(Decimal("5"), "EUR", "EUR", date(2026, 1, 1)) == Decimal("5.00")
    assert svc.convert(Decimal("5"), "EUR", "CZK", date(2026, 1, 1)) is None


def test_lookback_to_prior_business_day():
    svc = FXService()
    svc.load_rates(
        [fx_rate(rate_date=date(2026, 7, 18), base="EUR", rate="25.00")]
    )
    # Sunday 19th → look back to 18th
    out = svc.convert(Decimal("2"), "EUR", "CZK", date(2026, 7, 19))
    assert out == Decimal("50.00")


def test_inverse_czk_to_usd():
    svc = FXService()
    svc.load_rates(
        [fx_rate(rate_date=date(2026, 7, 20), base="USD", rate="20.00")]
    )
    out = svc.convert(Decimal("40"), "CZK", "USD", date(2026, 7, 20))
    assert out == Decimal("2.00")


def test_cross_via_czk():
    svc = FXService()
    svc.load_rates(
        [
            fx_rate(rate_date=date(2026, 7, 20), base="USD", rate="20.00"),
            fx_rate(rate_date=date(2026, 7, 20), base="EUR", rate="25.00"),
        ]
    )
    # 10 USD → 200 CZK → 8 EUR
    out = svc.convert(Decimal("10"), "USD", "EUR", date(2026, 7, 20))
    assert out == Decimal("8.00")


def test_parse_cnb_daily_text():
    sample = """\
05 Aug 2026 #150
Country|Currency|Amount|Code|Rate
Australia|dollar|1|AUD|14.500
EMU|euro|1|EUR|25.000
Japan|yen|100|JPY|15.000
United States|dollar|1|USD|23.100
"""
    pairs = {c: r for c, r in FXService.parse_cnb_daily_text(sample, date(2026, 8, 5))}
    assert pairs["USD"] == Decimal("23.100")
    assert pairs["EUR"] == Decimal("25.000")
    assert pairs["JPY"] == Decimal("0.15")  # 15 / 100


def test_fetch_cnb_uses_injected_opener():
    body = b"""05 Aug 2026 #150
Country|Currency|Amount|Code|Rate
United States|dollar|1|USD|23.100
"""
    svc = FXService(urlopen_bytes=lambda url: body)
    rows = svc.fetch_cnb_rates_for_date(date(2026, 8, 5))
    assert len(rows) == 1
    assert rows[0].base_currency == "USD"
    assert rows[0].rate == Decimal("23.100")
    assert rows[0].source == FXSource.CNB
    # loaded into service
    assert svc.convert(Decimal("1"), "USD", "CZK", date(2026, 8, 5)) == Decimal("23.10")


def test_preferred_source_over_other_on_same_day():
    svc = FXService(preferred_source="CNB")
    d = date(2026, 1, 2)
    svc.load_rates(
        [
            FXRate(
                id=uuid4(),
                rate_date=d,
                base_currency="USD",
                quote_currency="CZK",
                rate=Decimal("99.00"),
                source=FXSource.REVOLUT_STATEMENT,
                created_at=TS,
                updated_at=TS,
            ),
            fx_rate(rate_date=d, base="USD", rate="23.00", source=FXSource.CNB),
        ]
    )
    assert svc.rate_for(on=d, base="USD", quote="CZK") == Decimal("23.00")
