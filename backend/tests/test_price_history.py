"""Price history: range mapping, aggregate MV, service with mocked fetcher."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.schema.models import AssetClass, InvestmentLot, LotStatus
from backend.services.price_history import (
    PriceHistoryService,
    aggregate_mv_series,
    clear_history_cache,
    range_to_yfinance_period,
)
from backend.sheets.repository import InMemorySheetsRepository

TS = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)


def _lot(
    *,
    ticker: str,
    asset_class: AssetClass,
    qty: str,
    cost_usd: str,
) -> InvestmentLot:
    return InvestmentLot(
        id=uuid4(),
        account_id=uuid4(),
        ticker=ticker,
        asset_class=asset_class,
        source="Revolut",
        acquisition_date=date(2024, 1, 1),
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


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_history_cache()
    yield
    clear_history_cache()


def test_range_to_period():
    assert range_to_yfinance_period("1y") == "1y"
    assert range_to_yfinance_period("1m") == "1mo"
    assert range_to_yfinance_period("YTD") == "ytd"
    with pytest.raises(ValueError):
        range_to_yfinance_period("2w")


def test_aggregate_mv_forward_fill():
    qty = {"AAA": Decimal("10"), "BBB": Decimal("2")}
    closes = {
        "AAA": [
            (date(2026, 1, 1), Decimal("1")),
            (date(2026, 1, 2), Decimal("2")),
            (date(2026, 1, 3), Decimal("2")),
        ],
        "BBB": [
            (date(2026, 1, 2), Decimal("100")),
            (date(2026, 1, 3), Decimal("110")),
        ],
    }
    series = aggregate_mv_series(qty, closes)
    # Day1: only AAA → 10*1 = 10
    assert series[0] == (date(2026, 1, 1), Decimal("10.00"))
    # Day2: 10*2 + 2*100 = 220
    assert series[1] == (date(2026, 1, 2), Decimal("220.00"))
    # Day3: 10*2 + 2*110 = 240
    assert series[2] == (date(2026, 1, 3), Decimal("240.00"))


def test_history_ticker_mocked():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="DOGE", asset_class=AssetClass.CRYPTO, qty="100", cost_usd="10")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period):
        assert period == "1y"
        assert any("DOGE" in s for s in yahoo_symbols)
        our = yahoo_map[yahoo_symbols[0]]
        return {
            our: [
                (date(2026, 1, 1), Decimal("0.10")),
                (date(2026, 6, 1), Decimal("0.20")),
            ]
        }

    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(scope="ticker", range_key="1y", ticker="DOGE")
    assert result.series_kind == "price"
    assert result.label == "DOGE"
    assert len(result.points) == 2
    assert result.meta["change_pct"] == 100.0
    assert result.meta["avg_cost_usd"] == "0.1000"
    assert result.meta["missing_tickers"] == []


def test_history_crypto_class_mocked():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="DOGE", asset_class=AssetClass.CRYPTO, qty="100", cost_usd="10"),
            _lot(ticker="BTC", asset_class=AssetClass.CRYPTO, qty="0.5", cost_usd="20000"),
            _lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="10", cost_usd="200"),
        ],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period):
        out = {}
        for ysym, our in yahoo_map.items():
            if our == "DOGE":
                out[our] = [
                    (date(2026, 1, 1), Decimal("0.10")),
                    (date(2026, 1, 2), Decimal("0.20")),
                ]
            elif our == "BTC":
                out[our] = [
                    (date(2026, 1, 1), Decimal("40000")),
                    (date(2026, 1, 2), Decimal("42000")),
                ]
        return out

    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(scope="asset_class", range_key="1y", asset_class="Crypto")
    assert result.series_kind == "market_value"
    assert result.label == "Crypto"
    assert set(result.meta["tickers"]) == {"BTC", "DOGE"}
    # Day1: 100*0.10 + 0.5*40000 = 10 + 20000 = 20010
    assert result.points[0]["value"] == "20010.00"
    # Day2: 100*0.20 + 0.5*42000 = 20 + 21000 = 21020
    assert result.points[1]["value"] == "21020.00"
    assert Decimal(result.meta["cost_basis_usd"]) == Decimal("20010.00")


def test_history_missing_open_ticker():
    repo = InMemorySheetsRepository()
    svc = PriceHistoryService(repo, fetcher=lambda *a, **k: {})
    with pytest.raises(LookupError):
        svc.history(scope="ticker", ticker="ZZZZ")


def test_history_disabled():
    repo = InMemorySheetsRepository()
    svc = PriceHistoryService(repo, enabled=False, fetcher=lambda *a, **k: {})
    with pytest.raises(RuntimeError):
        svc.history(scope="ticker", ticker="X")
