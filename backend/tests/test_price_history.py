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
    range_to_yfinance_spec,
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
    assert range_to_yfinance_spec("1d") == ("1d", "5m", "intraday")
    with pytest.raises(ValueError):
        range_to_yfinance_period("2w")


def test_aggregate_mv_forward_fill():
    qty = {"AAA": Decimal("10"), "BBB": Decimal("2")}
    closes = {
        "AAA": [
            ("2026-01-01", Decimal("1")),
            ("2026-01-02", Decimal("2")),
            ("2026-01-03", Decimal("2")),
        ],
        "BBB": [
            ("2026-01-02", Decimal("100")),
            ("2026-01-03", Decimal("110")),
        ],
    }
    series = aggregate_mv_series(qty, closes)
    assert series[0] == ("2026-01-01", Decimal("10.00"))
    assert series[1] == ("2026-01-02", Decimal("220.00"))
    assert series[2] == ("2026-01-03", Decimal("240.00"))


def test_history_ticker_mocked():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="DOGE", asset_class=AssetClass.CRYPTO, qty="100", cost_usd="10")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        our = yahoo_map[yahoo_symbols[0]]
        if period == "1d":
            return {
                our: [
                    ("2026-08-09T14:00:00+00:00", Decimal("0.15")),
                    ("2026-08-09T15:00:00+00:00", Decimal("0.16")),
                ]
            }
        assert period == "1y"
        assert interval == "1d"
        return {
            our: [
                ("2026-01-01", Decimal("0.10")),
                ("2026-06-01", Decimal("0.20")),
            ]
        }

    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(scope="ticker", range_key="1y", ticker="DOGE")
    assert result.series_kind == "price"
    assert result.interval == "1d"
    assert result.label == "DOGE"
    assert len(result.points) == 2
    assert result.meta["change_pct"] == 100.0
    assert result.meta["avg_cost_usd"] == "0.1000"
    assert result.meta["day_change_pct"] == pytest.approx(6.67, abs=0.02)
    assert result.meta["missing_tickers"] == []


def test_history_1d_intraday():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="10", cost_usd="100")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        assert period == "1d"
        assert interval == "5m"
        our = yahoo_map[yahoo_symbols[0]]
        return {
            our: [
                ("2026-08-09T14:30:00+00:00", Decimal("20")),
                ("2026-08-09T15:30:00+00:00", Decimal("22")),
            ]
        }

    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(scope="ticker", range_key="1d", ticker="PLTR")
    assert result.interval == "5m"
    assert result.meta["point_kind"] == "intraday"
    assert result.meta["day_change_pct"] == 10.0
    assert result.meta["change_pct"] == 10.0


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

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        out = {}
        for ysym, our in yahoo_map.items():
            if our == "DOGE":
                out[our] = [
                    ("2026-01-01", Decimal("0.10")),
                    ("2026-01-02", Decimal("0.20")),
                ]
            elif our == "BTC":
                out[our] = [
                    ("2026-01-01", Decimal("40000")),
                    ("2026-01-02", Decimal("42000")),
                ]
            elif our == "PLTR":
                out[our] = [
                    ("2026-01-01", Decimal("20")),
                    ("2026-01-02", Decimal("21")),
                ]
        return out

    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(scope="asset_class", range_key="1y", asset_class="Crypto")
    assert result.series_kind == "market_value"
    assert result.label == "Crypto"
    assert set(result.meta["tickers"]) == {"BTC", "DOGE"}
    assert result.points[0]["value"] == "20010.00"
    assert result.points[1]["value"] == "21020.00"
    assert Decimal(result.meta["cost_basis_usd"]) == Decimal("20010.00")


def test_history_all_portfolio():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="DOGE", asset_class=AssetClass.CRYPTO, qty="100", cost_usd="10"),
            _lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="10", cost_usd="200"),
        ],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        out = {}
        for ysym, our in yahoo_map.items():
            if our == "DOGE":
                out[our] = [("2026-01-01", Decimal("0.10")), ("2026-01-02", Decimal("0.20"))]
            elif our == "PLTR":
                out[our] = [("2026-01-01", Decimal("20")), ("2026-01-02", Decimal("25"))]
        return out

    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(scope="all", range_key="1y")
    assert result.scope == "all"
    assert result.label == "Portfolio"
    # Day1: 100*0.10 + 10*20 = 210
    assert result.points[0]["value"] == "210.00"
    # Day2: 100*0.20 + 10*25 = 270
    assert result.points[1]["value"] == "270.00"


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
