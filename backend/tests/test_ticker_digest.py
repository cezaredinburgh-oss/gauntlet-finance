"""Ticker verification digests."""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    Price,
)
from backend.services.ticker_digest import (
    annualized_unrealized_pct,
    build_ticker_digests,
    cost_weighted_holding_years,
    roi_grade,
)
from backend.sheets.repository import InMemorySheetsRepository

TS = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 8, 6)


def _lot(
    *,
    ticker: str = "PLTR",
    source: str = "Revolut",
    qty: str = "10",
    cost_usd: str = "100",
    acquisition: date = date(2022, 1, 1),
) -> InvestmentLot:
    return InvestmentLot(
        id=uuid4(),
        account_id=uuid4(),
        ticker=ticker,
        asset_class=AssetClass.STOCK,
        source=source,
        acquisition_date=acquisition,
        quantity_opened=Decimal(qty),
        quantity_remaining=Decimal(qty),
        cost_basis_native=Decimal(cost_usd),
        cost_basis_czk=Decimal(cost_usd) * Decimal("22"),
        cost_basis_usd=Decimal(cost_usd),
        native_currency="USD",
        open_event_id=None,
        status=LotStatus.OPEN,
        notes=None,
        created_at=TS,
        updated_at=TS,
    )


def _price(ticker: str, price: str) -> Price:
    return Price(
        id=uuid4(),
        ticker=ticker,
        price=Decimal(price),
        currency="USD",
        as_of=TS,
        source="yfinance",
        created_at=TS,
        updated_at=TS,
    )


def test_roi_grade_thresholds():
    assert roi_grade(None) == ("—", "Unpriced")
    assert roi_grade(50)[0] == "A"
    assert roi_grade(20)[0] == "B"
    assert roi_grade(0)[0] == "C"
    assert roi_grade(-10)[0] == "D"
    assert roi_grade(-25)[0] == "F"


def test_cost_weighted_holding_years():
    # Equal cost: average of 1y and 3y = 2y
    as_of = date(2024, 1, 1)
    lots = [
        (Decimal("100"), date(2023, 1, 1)),
        (Decimal("100"), date(2021, 1, 1)),
    ]
    y = cost_weighted_holding_years(lots, as_of=as_of)
    assert y is not None
    assert abs(y - 2.0) < 0.02
    # Heavier recent lot pulls age down
    lots2 = [
        (Decimal("300"), date(2023, 1, 1)),
        (Decimal("100"), date(2021, 1, 1)),
    ]
    y2 = cost_weighted_holding_years(lots2, as_of=as_of)
    assert y2 is not None and y2 < y


def test_annualized_unrealized_pct():
    # Double in 2 years → ~41.4% ann (sqrt(2)-1)
    ann = annualized_unrealized_pct(1.0, 2.0)
    assert ann is not None
    assert abs(ann - 41.42) < 0.1
    # Too short
    assert annualized_unrealized_pct(0.5, 30 / 365.25) is None
    # Wipeout
    assert annualized_unrealized_pct(-1.0, 2.0) is None


def test_digest_includes_annualized():
    # 2 years hold, MV doubles: 100% total, ~41% ann
    repo = InMemorySheetsRepository()
    acq = date(2024, 8, 6)  # exactly 2y before AS_OF 2026-08-06
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="AAA", qty="10", cost_usd="100", acquisition=acq)],
    )
    repo.upsert_rows("Prices", [_price("AAA", "20")])  # MV 200
    repo.upsert_rows("InvestmentEvents", [])
    result = build_ticker_digests(repo, as_of=AS_OF)
    row = next(t for t in result["tickers"] if t["ticker"] == "AAA")
    assert row["unrealized_pct"] == 100.0
    assert row["holding_years"] is not None and row["holding_years"] >= 1.9
    assert row["annualized_unrealized_pct"] is not None
    assert abs(row["annualized_unrealized_pct"] - 41.42) < 1.0


def test_multi_platform_qty_and_tax_tranches():
    # Tax-free: acquired 2022 (more than 1095 days before 2026-08-06)
    free_lot = _lot(
        ticker="PLTR",
        source="Revolut",
        qty="100",
        cost_usd="1000",
        acquisition=date(2022, 1, 1),
    )
    # Locked: recent
    locked_lot = _lot(
        ticker="PLTR",
        source="eToro",
        qty="10.67",
        cost_usd="200",
        acquisition=date(2025, 6, 1),
    )
    other = _lot(
        ticker="AAPL",
        source="Revolut",
        qty="5",
        cost_usd="500",
        acquisition=date(2022, 1, 1),
    )

    repo = InMemorySheetsRepository()
    repo.replace_all_rows("InvestmentLots", [free_lot, locked_lot, other])
    repo.replace_all_rows(
        "Prices",
        [_price("PLTR", "20"), _price("AAPL", "100")],
    )
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("FXRates", [])

    out = build_ticker_digests(repo, as_of=AS_OF, exemption_days=1095)
    pltr = next(t for t in out["tickers"] if t["ticker"] == "PLTR")

    assert Decimal(pltr["quantity_total"]) == Decimal("110.6700")
    assert pltr["multi_platform"] is True
    assert len(pltr["by_platform"]) == 2
    sources = {p["source"]: Decimal(p["quantity"]) for p in pltr["by_platform"]}
    assert sources["Revolut"] == Decimal("100.0000")
    assert sources["eToro"] == Decimal("10.6700")

    # MV: 110.67 * 20 = 2213.4
    assert Decimal(pltr["market_value_usd"]) == Decimal("2213.40")
    # Cost 1200 → unrealized 1013.4 → ROI ~84.45% → grade A
    assert pltr["roi_grade"] == "A"
    assert pltr["asset_class"] == "Stock"

    now_tr = next(t for t in pltr["tax_tranches"] if t["key"] == "now")
    assert Decimal(now_tr["quantity"]) == Decimal("100.0000")
    assert Decimal(now_tr["market_value_usd"]) == Decimal("2000.00")  # 100 * 20

    locked_qty = sum(
        Decimal(t["quantity"])
        for t in pltr["tax_tranches"]
        if t["key"] != "now"
    )
    assert locked_qty == Decimal("10.6700")

    assert pltr["portfolio_weight_pct"] is not None
    assert pltr["growth_contribution_pp"] is not None
    # PLTR is majority of portfolio MV
    assert pltr["portfolio_weight_pct"] > 50


def test_growth_contribution_math():
    # Single ticker: growth contribution = portfolio unrealized / cost * 100 = unrealized_pct
    lot = _lot(qty="10", cost_usd="100", acquisition=date(2020, 1, 1))
    repo = InMemorySheetsRepository()
    repo.replace_all_rows("InvestmentLots", [lot])
    repo.replace_all_rows("Prices", [_price("PLTR", "15")])  # MV 150, unrealized 50
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("FXRates", [])

    out = build_ticker_digests(repo, as_of=AS_OF)
    pltr = out["tickers"][0]
    assert pltr["unrealized_pct"] == 50.0
    assert pltr["growth_contribution_pp"] == 50.0
    assert pltr["portfolio_weight_pct"] == 100.0
    assert pltr["roi_grade"] == "A"
