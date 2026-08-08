"""USD/CZK historical series for analysis charts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.services.fx_series import build_usd_czk_series
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import fx_rate


def test_usd_czk_series_with_portfolio_context():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "FXRates",
        [
            fx_rate(rate_date=date(2026, 6, 1), base="USD", rate="21.00"),
            fx_rate(rate_date=date(2026, 6, 15), base="USD", rate="21.50"),
            fx_rate(rate_date=date(2026, 6, 19), base="USD", rate="21.07"),
        ],
    )
    out = build_usd_czk_series(
        repo,
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 19),
        portfolio_usd=Decimal("100000"),
    )
    assert out["pair"] == "USD/CZK"
    assert out["point_count"] >= 3
    assert out["rate_start"] == "21.0000"
    assert out["rate_end"] == "21.0700"
    assert out["portfolio"] is not None
    assert out["portfolio"]["portfolio_usd"] == "100000.00"
    # 100k * 21.07
    assert out["portfolio"]["portfolio_czk_now"] == "2107000.00"
    # first point portfolio_czk
    assert out["series"][0]["portfolio_czk"] == "2100000.00"
    assert Decimal(out["change_abs"]) == Decimal("0.0700")


def test_series_empty_without_rates():
    repo = InMemorySheetsRepository()
    out = build_usd_czk_series(
        repo,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 10),
        portfolio_usd=None,
    )
    assert out["point_count"] == 0
    assert out["portfolio"] is None
