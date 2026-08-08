"""Portfolio health score and price_status."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from backend.services.portfolio_health import (
    HoldingRow,
    LotRow,
    RealizedRow,
    compute_portfolio_health,
    price_status_from_snapshot,
)


def test_empty_book():
    h = compute_portfolio_health([], [], [], tax_free_open_basis=Decimal("0"), open_cost_basis=Decimal("0"))
    assert h["grade"] == "N/A"
    assert h["score"] == 0


def test_concentrated_book_low_grade():
    holdings = [
        HoldingRow("PLTR", Decimal("80000"), Decimal("50000"), "stock"),
        HoldingRow("TSLA", Decimal("10000"), Decimal("8000"), "stock"),
        HoldingRow("DOGE", Decimal("10000"), Decimal("5000"), "crypto", is_crypto=True),
    ]
    lots = [
        LotRow("PLTR", Decimal("50000"), tax_free=False, days_until_tax_free=30),
        LotRow("TSLA", Decimal("8000"), tax_free=True, days_until_tax_free=None),
    ]
    h = compute_portfolio_health(
        holdings,
        lots,
        [],
        tax_free_open_basis=Decimal("8000"),
        open_cost_basis=Decimal("63000"),
    )
    assert h["concentration"]["top_ticker"] == "PLTR"
    assert h["concentration"]["top_weight_pct"] > 35
    assert h["score"] < 80
    assert h["grade"] in ("B", "C", "D")
    titles = [i["title"] for i in h["issues"]]
    assert any("concentration" in t.lower() or "PLTR" in t for t in titles)


def test_balanced_book_high_grade():
    holdings = [
        HoldingRow(f"T{i}", Decimal("10000"), Decimal("9000"), "stock")
        for i in range(10)
    ]
    lots = [
        LotRow(f"T{i}", Decimal("9000"), tax_free=True, days_until_tax_free=None)
        for i in range(10)
    ]
    realized = [
        RealizedRow(tax_free=True, gain_usd=Decimal("100")) for _ in range(5)
    ]
    h = compute_portfolio_health(
        holdings,
        lots,
        realized,
        tax_free_open_basis=Decimal("90000"),
        open_cost_basis=Decimal("90000"),
    )
    assert h["score"] >= 80
    assert h["grade"] == "A"
    assert h["concentration"]["top_weight_pct"] <= 25


def test_price_status_modes():
    empty = price_status_from_snapshot(
        quote_count=0,
        open_ticker_count=5,
        missing_quotes=["A"],
        prices_as_of=None,
    )
    assert empty["mode"] == "empty"

    partial = price_status_from_snapshot(
        quote_count=3,
        open_ticker_count=5,
        missing_quotes=["X", "Y"],
        prices_as_of=date(2026, 8, 7),
        as_of=date(2026, 8, 7),
    )
    assert partial["mode"] == "partial"

    live = price_status_from_snapshot(
        quote_count=5,
        open_ticker_count=5,
        missing_quotes=[],
        prices_as_of=date(2026, 8, 7),
        as_of=date(2026, 8, 7),
    )
    assert live["mode"] == "live_ok"
    assert "mode_note" in live
