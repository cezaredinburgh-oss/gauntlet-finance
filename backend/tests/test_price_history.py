"""Price history: range mapping, aggregate MV, service with mocked fetcher."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    Price,
    TradeSide,
)
from backend.services.holdings_timeline import build_holdings_timeline
from backend.services.price_history import (
    PriceHistoryService,
    aggregate_mv_series,
    aggregate_mv_series_time_aware,
    clear_history_cache,
    range_to_yfinance_period,
    range_to_yfinance_spec,
    _parse_ts,
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
    assert range_to_yfinance_spec("1d") == ("5d", "5m", "intraday")
    assert range_to_yfinance_spec("7d") == ("7d", "1d", "daily")
    with pytest.raises(ValueError):
        range_to_yfinance_period("2w")
    with pytest.raises(ValueError):
        range_to_yfinance_period("max")


def test_parse_ts_timezone_order():
    a = _parse_ts("2026-08-07T15:55:00-04:00")
    b = _parse_ts("2026-08-07T19:55:00+00:00")
    # Same instant (approx) — both should parse; -04 15:55 == UTC 19:55
    assert a.astimezone(timezone.utc).hour == 19
    assert b.astimezone(timezone.utc).hour == 19


def test_aggregate_skips_until_coverage():
    """Tiny early name alone must not emit; wait for 90% book weight."""
    qty = {"HEAVY": Decimal("10"), "TINY": Decimal("1")}
    closes = {
        "TINY": [
            ("2026-01-01", Decimal("1")),  # weight 1
            ("2026-01-02", Decimal("1")),
            ("2026-01-03", Decimal("1")),
        ],
        "HEAVY": [
            ("2026-01-02", Decimal("100")),  # weight 1000
            ("2026-01-03", Decimal("110")),
        ],
    }
    series, meta = aggregate_mv_series(qty, closes)
    # Day1: only TINY (weight 1/1001 < 90%) — skipped
    assert series[0][0] == "2026-01-02"
    # 10*100 + 1*1 = 1001
    assert series[0][1] == Decimal("1001.00")
    assert series[1][1] == Decimal("1101.00")


def test_aggregate_short_ipo_does_not_clip_long_range():
    """SPCX-like short history must not force the whole series to start at IPO."""
    qty = {
        "PLTR": Decimal("10"),  # weight ~1720 at last
        "SPCX": Decimal("1"),  # weight ~100
    }
    # PLTR full year of monthly-ish points; SPCX only last two
    pltr = [(f"2025-{m:02d}-15", Decimal("100") + Decimal(m)) for m in range(1, 13)]
    pltr.append(("2026-06-15", Decimal("150")))
    pltr.append(("2026-07-15", Decimal("160")))
    spcx = [
        ("2026-06-15", Decimal("100")),
        ("2026-07-15", Decimal("110")),
    ]
    series, meta = aggregate_mv_series(
        qty, {"PLTR": pltr, "SPCX": spcx}, coverage_threshold=Decimal("0.90")
    )
    assert series[0][0] == "2025-01-15"  # starts with PLTR alone
    assert any(p[0] == "2026-06-15" for p in series)
    short = {s["ticker"] for s in meta["short_history_tickers"]}
    assert "SPCX" in short


def test_aggregate_heavy_short_still_waits():
    """If short name is majority of book weight, series waits for it."""
    qty = {"OLD": Decimal("1"), "NEW": Decimal("100")}
    closes = {
        "OLD": [
            ("2025-01-01", Decimal("10")),  # weight 10
            ("2026-06-01", Decimal("10")),
            ("2026-07-01", Decimal("10")),
        ],
        "NEW": [
            ("2026-06-01", Decimal("10")),  # weight 1000
            ("2026-07-01", Decimal("11")),
        ],
    }
    series, meta = aggregate_mv_series(
        qty, closes, coverage_threshold=Decimal("0.90")
    )
    assert series[0][0] == "2026-06-01"


def test_history_ticker_mocked():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="DOGE", asset_class=AssetClass.CRYPTO, qty="100", cost_usd="10")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        our = yahoo_map[yahoo_symbols[0]]
        daily = [
            ("2026-01-01", Decimal("0.10")),
            ("2026-06-01", Decimal("0.20")),
        ]
        if period == "1d" or interval == "5m":
            return {
                our: [
                    ("2026-08-09T14:00:00+00:00", Decimal("0.15")),
                    ("2026-08-09T15:00:00+00:00", Decimal("0.16")),
                ]
                if interval == "5m" and period != "5d"
                else daily
            }
        assert period in ("1y", "5d")
        return {our: daily}

    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(scope="ticker", range_key="1y", ticker="DOGE")
    assert result.series_kind == "price"
    assert result.interval == "1d"
    assert result.label == "DOGE"
    assert len(result.points) == 2
    assert result.meta["change_pct"] == 100.0
    assert result.meta["avg_cost_usd"] == "0.1000"
    # Crypto 1Y day_open uses DayPolicy 5m; fixture daily bars still yield 100%
    assert result.meta["day_change_pct"] == pytest.approx(100.0, abs=0.02)
    assert result.meta["missing_tickers"] == []


def test_history_1d_intraday():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="10", cost_usd="100")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        # 1D range downloads 5d of 5m bars, then trims to session
        assert period == "5d"
        assert interval == "5m"
        our = yahoo_map[yahoo_symbols[0]]
        # Two bars in "today" RTH (relative to freezegun-less clock): use a fixed
        # session that trim accepts as prior if needed, still non-empty.
        return {
            our: [
                ("2026-08-07T14:30:00+00:00", Decimal("20")),  # 10:30 ET
                ("2026-08-07T15:30:00+00:00", Decimal("22")),  # 11:30 ET
            ]
        }

    from zoneinfo import ZoneInfo

    now = datetime(2026, 8, 10, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    # 10:00 ET Monday — regular; fixture is prior Friday so path is seed only
    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(
        scope="ticker", range_key="1d", ticker="PLTR", now=now
    )
    assert result.interval == "5m"
    assert result.meta["point_kind"] == "intraday"
    assert len(result.points) >= 1
    assert result.meta.get("session_status") in (
        "overnight",
        "pre_market",
        "regular",
        "after_hours",
        "prior_session",
    )
    assert result.meta["change_pct"] is not None


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
    assert result.points[0]["value"] == "210.00"
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


def _event(
    *,
    ticker: str,
    event_type: InvestmentEventType,
    event_date: date,
    qty: str,
    asset_class: AssetClass = AssetClass.STOCK,
    event_datetime: datetime | None = None,
) -> InvestmentEvent:
    return InvestmentEvent(
        id=uuid4(),
        account_id=uuid4(),
        event_type=event_type,
        event_date=event_date,
        event_datetime=event_datetime,
        ticker=ticker,
        asset_class=asset_class,
        side=TradeSide.BUY if event_type == InvestmentEventType.BUY else TradeSide.SELL,
        quantity=Decimal(qty),
        price_native=Decimal("10"),
        native_currency="USD",
        value_native=Decimal(qty) * Decimal("10"),
        value_usd=Decimal(qty) * Decimal("10"),
        source="Test",
        created_at=TS,
        updated_at=TS,
    )


def test_timeline_buy_sell_qty_as_of():
    events = [
        _event(
            ticker="AAA",
            event_type=InvestmentEventType.BUY,
            event_date=date(2021, 1, 1),
            qty="10",
        ),
        _event(
            ticker="AAA",
            event_type=InvestmentEventType.SELL,
            event_date=date(2022, 6, 1),
            qty="10",
        ),
        _event(
            ticker="BBB",
            event_type=InvestmentEventType.BUY,
            event_date=date(2023, 1, 1),
            qty="5",
        ),
    ]
    alloc = _event(
        ticker="AAA",
        event_type=InvestmentEventType.LOT_ALLOCATION,
        event_date=date(2022, 6, 1),
        qty="10",
    )
    tl = build_holdings_timeline(events + [alloc], [])
    assert tl.qty_as_of("AAA", date(2020, 12, 31)) == Decimal("0")
    assert tl.qty_as_of("AAA", date(2021, 8, 11)) == Decimal("10")
    assert tl.qty_as_of("AAA", date(2022, 6, 1)) == Decimal("0")
    assert tl.qty_as_of("BBB", date(2022, 12, 31)) == Decimal("0")
    assert tl.qty_as_of("BBB", date(2023, 2, 1)) == Decimal("5")


def test_timeline_qty_as_of_ts_not_premature_same_day():
    """Same-day buys apply only after event_datetime (not at UTC midnight)."""
    buy_dt = datetime(2026, 8, 11, 11, 45, 0, tzinfo=timezone.utc)
    events = [
        _event(
            ticker="DOGE",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 11),
            event_datetime=buy_dt,
            qty="7000",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    # Calendar day still sees end-of-day qty (daily charts)
    assert tl.qty_as_of("DOGE", date(2026, 8, 11)) == Decimal("7000")
    # Before the trade instant — zero
    assert tl.qty_as_of_ts(
        "DOGE", datetime(2026, 8, 11, 0, 10, 0, tzinfo=timezone.utc)
    ) == Decimal("0")
    assert tl.qty_as_of_ts(
        "DOGE", datetime(2026, 8, 11, 11, 40, 0, tzinfo=timezone.utc)
    ) == Decimal("0")
    # At/after the trade
    assert tl.qty_as_of_ts("DOGE", buy_dt) == Decimal("7000")
    assert tl.qty_as_of_ts(
        "DOGE", datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    ) == Decimal("7000")


def test_aggregate_1d_no_midnight_qty_spike():
    """1D MV must not jump at UTC midnight when buys happen later same day."""
    buy_dt = datetime(2026, 8, 11, 11, 45, 0, tzinfo=timezone.utc)
    events = [
        _event(
            ticker="BASE",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 1),
            event_datetime=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        ),
        _event(
            ticker="DOGE",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 11),
            event_datetime=buy_dt,
            qty="100",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    # Flat prices; DOGE buy adds 100 * 10 = 1000 only after 11:45
    closes = {
        "BASE": [
            ("2026-08-10T23:55:00+00:00", Decimal("1000")),
            ("2026-08-11T00:00:00+00:00", Decimal("1000")),
            ("2026-08-11T00:10:00+00:00", Decimal("1000")),
            ("2026-08-11T11:40:00+00:00", Decimal("1000")),
            ("2026-08-11T11:45:00+00:00", Decimal("1000")),
            ("2026-08-11T12:00:00+00:00", Decimal("1000")),
        ],
        "DOGE": [
            ("2026-08-10T23:55:00+00:00", Decimal("10")),
            ("2026-08-11T00:00:00+00:00", Decimal("10")),
            ("2026-08-11T00:10:00+00:00", Decimal("10")),
            ("2026-08-11T11:40:00+00:00", Decimal("10")),
            ("2026-08-11T11:45:00+00:00", Decimal("10")),
            ("2026-08-11T12:00:00+00:00", Decimal("10")),
        ],
    }
    series, meta = aggregate_mv_series_time_aware(
        tl, closes, coverage_threshold=Decimal("0.5"), preseed_first_marks=True
    )
    assert meta["quantity_basis"] == "holdings_as_of_each_timestamp"
    by_ts = {p[0]: p[1] for p in series}
    # Before buy: only BASE = 1000
    assert by_ts["2026-08-10T23:55:00+00:00"] == Decimal("1000.00")
    assert by_ts["2026-08-11T00:00:00+00:00"] == Decimal("1000.00")
    assert by_ts["2026-08-11T00:10:00+00:00"] == Decimal("1000.00")
    assert by_ts["2026-08-11T11:40:00+00:00"] == Decimal("1000.00")
    # After buy: BASE + DOGE = 1000 + 1000
    assert by_ts["2026-08-11T11:45:00+00:00"] == Decimal("2000.00")
    assert by_ts["2026-08-11T12:00:00+00:00"] == Decimal("2000.00")


def test_aggregate_time_aware_ignores_future_buys():
    """2021 MV must not include names only bought in 2023."""
    events = [
        _event(
            ticker="OLD",
            event_type=InvestmentEventType.BUY,
            event_date=date(2021, 1, 1),
            qty="1",
        ),
        _event(
            ticker="NEW",
            event_type=InvestmentEventType.BUY,
            event_date=date(2023, 1, 1),
            qty="100",
        ),
    ]
    tl = build_holdings_timeline(events, [])
    closes = {
        "OLD": [
            ("2021-08-11", Decimal("10")),
            ("2023-06-01", Decimal("12")),
        ],
        "NEW": [
            ("2021-08-11", Decimal("100")),
            ("2023-06-01", Decimal("110")),
        ],
    }
    series, meta = aggregate_mv_series_time_aware(
        tl, closes, coverage_threshold=Decimal("0.90")
    )
    assert meta["quantity_basis"] == "holdings_as_of_each_date"
    by_d = {p[0]: p[1] for p in series}
    assert by_d["2021-08-11"] == Decimal("10.00")
    assert by_d["2023-06-01"] == Decimal("11012.00")


def test_aggregate_time_aware_constant_matches_legacy():
    qty = {"HEAVY": Decimal("10"), "TINY": Decimal("1")}
    closes = {
        "TINY": [
            ("2026-01-01", Decimal("1")),
            ("2026-01-02", Decimal("1")),
            ("2026-01-03", Decimal("1")),
        ],
        "HEAVY": [
            ("2026-01-02", Decimal("100")),
            ("2026-01-03", Decimal("110")),
        ],
    }
    events = [
        _event(
            ticker="HEAVY",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="10",
        ),
        _event(
            ticker="TINY",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
        ),
    ]
    tl = build_holdings_timeline(events, [])
    legacy, _ = aggregate_mv_series(qty, closes)
    aware, _ = aggregate_mv_series_time_aware(tl, closes)
    assert aware == legacy


def test_trim_intraday_rth_today_or_prior():
    from backend.services.price_history import trim_intraday_series

    # Prior day full RTH-ish + two bars today after open
    series = []
    for h in range(9, 16):
        for m in (0, 30):
            if h == 9 and m < 30:
                continue
            ts = f"2026-08-07T{h:02d}:{m:02d}:00-04:00"
            # store as UTC iso via parse path — use offset form
            from backend.services.price_history import _parse_ts

            ts_utc = _parse_ts(ts).astimezone(timezone.utc).isoformat()
            series.append((ts_utc, Decimal("100")))
    series.append(
        (
            _parse_ts("2026-08-10T09:30:00-04:00").astimezone(timezone.utc).isoformat(),
            Decimal("110"),
        )
    )
    series.append(
        (
            _parse_ts("2026-08-10T09:35:00-04:00").astimezone(timezone.utc).isoformat(),
            Decimal("111"),
        )
    )
    now = _parse_ts("2026-08-10T09:36:00-04:00")
    trimmed, status = trim_intraday_series(
        series, mode="rth_today_or_prior", now=now
    )
    assert status == "regular"
    # Seed (prior RTH last) + two today RTH prints
    assert len(trimmed) == 3
    assert trimmed[0].session == "prior_close"
    assert {p.session for p in trimmed[1:]} == {"rth"}
    assert Decimal(trimmed[-1][1]) == Decimal("111")


def test_trim_intraday_prior_when_no_today():
    from backend.services.price_history import trim_intraday_series, _parse_ts

    series = []
    for h in range(10, 15):
        ts = _parse_ts(f"2026-08-07T{h:02d}:00:00-04:00").astimezone(timezone.utc).isoformat()
        series.append((ts, Decimal(str(100 + h))))
    now = _parse_ts("2026-08-10T08:00:00-04:00")  # pre-open weekday
    trimmed, status = trim_intraday_series(
        series, mode="rth_today_or_prior", now=now
    )
    assert status == "pre_market"
    # Seed only — fixture has no today pre. Zero yesterday RTH vertices besides seed.
    assert len(trimmed) == 1
    assert trimmed[0].session == "prior_close"
    assert all(p.session != "rth" for p in trimmed)


def test_intraday_coverage_allows_partial_book():
    """At open, 50% coverage should still emit when half the book is marked."""
    from backend.services.price_history import (
        COVERAGE_THRESHOLD_INTRADAY,
        aggregate_mv_series_time_aware,
    )

    events = [
        _event(
            ticker="HEAVY",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="10",
        ),
        _event(
            ticker="LIGHT",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
        ),
    ]
    tl = build_holdings_timeline(events, [])
    closes = {
        # Only HEAVY has bars (90%+ of weight) — both thresholds emit
        "HEAVY": [
            ("2026-08-10T13:30:00+00:00", Decimal("100")),
            ("2026-08-10T13:35:00+00:00", Decimal("101")),
        ],
        # LIGHT missing entirely
    }
    series, _ = aggregate_mv_series_time_aware(
        tl, closes, coverage_threshold=COVERAGE_THRESHOLD_INTRADAY
    )
    assert len(series) == 2
    assert series[0][1] == Decimal("1000.00")


def test_collect_trade_markers_buy_sell_only():
    from backend.services.price_history import collect_trade_markers

    events = [
        _event(
            ticker="AAA",
            event_type=InvestmentEventType.BUY,
            event_date=date(2021, 8, 11),
            qty="10",
        ),
        _event(
            ticker="AAA",
            event_type=InvestmentEventType.SELL,
            event_date=date(2022, 1, 15),
            qty="5",
        ),
        _event(
            ticker="AAA",
            event_type=InvestmentEventType.STAKING_REWARD,
            event_date=date(2021, 9, 1),
            qty="1",
        ),
        _event(
            ticker="BBB",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),  # outside window
            qty="1",
        ),
    ]
    series = [
        {"date": "2021-08-11", "value": "100.00"},
        {"date": "2022-01-15", "value": "120.00"},
        {"date": "2022-06-01", "value": "130.00"},
    ]
    marks = collect_trade_markers(events, series)
    sides = {(m["ticker"], m["side"], m["date"]) for m in marks}
    assert ("AAA", "buy", "2021-08-11") in sides
    assert ("AAA", "sell", "2022-01-15") in sides
    assert not any(m["side"] == "buy" and m["ticker"] == "BBB" for m in marks)
    assert not any(m["date"] == "2021-09-01" for m in marks)
    buy = next(m for m in marks if m["side"] == "buy")
    assert buy["series_value"] == "100.00"


def test_collect_trade_markers_intraday_window_and_snap():
    """1D: datetime window + snap to one series bar (not whole calendar day)."""
    from backend.services.price_history import collect_trade_markers

    # 24h window: 2026-08-09 21:00 → 2026-08-10 21:00 UTC, 5m-ish bars
    series = [
        {"date": "2026-08-09T21:00:00+00:00", "value": "1000.00"},
        {"date": "2026-08-09T21:05:00+00:00", "value": "1001.00"},
        {"date": "2026-08-10T14:30:00+00:00", "value": "1100.00"},
        {"date": "2026-08-10T14:35:00+00:00", "value": "1105.00"},
        {"date": "2026-08-10T21:00:00+00:00", "value": "1120.00"},
    ]
    events = [
        # Outside window (same calendar day as first bar, but earlier)
        _event(
            ticker="AAA",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 9),
            event_datetime=datetime(2026, 8, 9, 10, 0, 0, tzinfo=timezone.utc),
            qty="1",
        ),
        # Inside window — should snap to 14:30 bar (on or before 14:32)
        _event(
            ticker="PLTR",
            event_type=InvestmentEventType.SELL,
            event_date=date(2026, 8, 10),
            event_datetime=datetime(2026, 8, 10, 14, 32, 0, tzinfo=timezone.utc),
            qty="10",
        ),
        # Second trade same day — distinct snap if later bar
        _event(
            ticker="SPCX",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 10),
            event_datetime=datetime(2026, 8, 10, 14, 36, 0, tzinfo=timezone.utc),
            qty="12",
        ),
        _event(
            ticker="ETH",
            event_type=InvestmentEventType.STAKING_REWARD,
            event_date=date(2026, 8, 10),
            event_datetime=datetime(2026, 8, 10, 15, 0, 0, tzinfo=timezone.utc),
            qty="0.01",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    marks = collect_trade_markers(events, series)
    assert len(marks) == 2
    sell = next(m for m in marks if m["side"] == "sell")
    buy = next(m for m in marks if m["side"] == "buy")
    assert sell["ticker"] == "PLTR"
    assert sell["date"] == "2026-08-10T14:30:00+00:00"
    assert sell["series_value"] == "1100.00"
    assert buy["ticker"] == "SPCX"
    assert buy["date"] == "2026-08-10T14:35:00+00:00"
    assert buy["series_value"] == "1105.00"
    # No date-only broadcast — markers must be ISO with T
    assert all("T" in m["date"] for m in marks)


def test_collect_trade_markers_after_last_bar_still_show():
    """Statement buys after Yahoo's last bar (or today with no daily close) still mark."""
    from backend.services.price_history import collect_trade_markers

    # 1D: last bar 11:40, buys at 11:45 (Revolut crypto update case)
    series_1d = [
        {"date": "2026-08-10T12:00:00+00:00", "value": "900.00"},
        {"date": "2026-08-11T11:40:00+00:00", "value": "1000.00"},
    ]
    buys = [
        _event(
            ticker="DOGE",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 11),
            event_datetime=datetime(2026, 8, 11, 11, 45, 0, tzinfo=timezone.utc),
            qty="7000",
            asset_class=AssetClass.CRYPTO,
        ),
        _event(
            ticker="XRP",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 11),
            event_datetime=datetime(2026, 8, 11, 11, 45, 35, tzinfo=timezone.utc),
            qty="490",
            asset_class=AssetClass.CRYPTO,
        ),
        _event(
            ticker="ETH",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 11),
            event_datetime=datetime(2026, 8, 11, 11, 46, 16, tzinfo=timezone.utc),
            qty="0.25",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    marks = collect_trade_markers(buys, series_1d, asset_class=AssetClass.CRYPTO)
    assert len(marks) == 3
    assert {m["ticker"] for m in marks} == {"DOGE", "XRP", "ETH"}
    # All snap to last bar so FE exact-match attaches once
    assert all(m["date"] == "2026-08-11T11:40:00+00:00" for m in marks)
    assert all(m["side"] == "buy" for m in marks)

    # Daily: series ends yesterday, buys today
    series_d = [
        {"date": "2026-08-09", "value": "800.00"},
        {"date": "2026-08-10", "value": "900.00"},
    ]
    marks_d = collect_trade_markers(buys, series_d, asset_class=AssetClass.CRYPTO)
    assert len(marks_d) == 3
    assert all(m["date"] == "2026-08-10" for m in marks_d)

    # Too far after last bar — excluded
    far = [
        _event(
            ticker="DOGE",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 20),
            event_datetime=datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        )
    ]
    assert collect_trade_markers(far, series_1d) == []


def test_collect_trade_markers_interior_gap_day_snaps():
    """Trade on a missing Yahoo day (e.g. Aug 11 hole) snaps to prior bar day."""
    from backend.services.price_history import collect_trade_markers

    series = [
        {"date": "2026-08-06", "value": "0.10"},
        {"date": "2026-08-07", "value": "0.11"},
        {"date": "2026-08-08", "value": "0.12"},
        {"date": "2026-08-09", "value": "0.13"},
        {"date": "2026-08-10", "value": "0.14"},
        # Aug 11 missing (Yahoo hole)
        {"date": "2026-08-12", "value": "0.15"},
    ]
    buys = [
        _event(
            ticker="DOGE",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 11),
            qty="7000",
            asset_class=AssetClass.CRYPTO,
        ),
        _event(
            ticker="ETH",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 11),
            qty="0.25",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    marks = collect_trade_markers(buys, series, asset_class=AssetClass.CRYPTO)
    assert len(marks) == 2
    assert all(m["date"] == "2026-08-10" for m in marks)
    assert all(m["series_value"] == "0.14" for m in marks)


def test_densify_daily_closes_fills_gap():
    from backend.services.price_history import densify_daily_closes

    series = [
        ("2026-08-10", Decimal("1.00")),
        ("2026-08-12", Decimal("1.20")),
    ]
    filled = densify_daily_closes(series)
    days = [d for d, _ in filled]
    assert days == ["2026-08-10", "2026-08-11", "2026-08-12"]
    assert filled[1][1] == Decimal("1.00")  # forward-fill
    assert filled[2][1] == Decimal("1.20")


def _price_row(ticker: str, price: str) -> Price:
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


def test_history_1d_portfolio_path_not_pinned_exposes_book_meta():
    """1D path tip stays Yahoo; desk book exposed in meta (no cliff rewrite)."""
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="10", cost_usd="200"),
            _lot(ticker="DOGE", asset_class=AssetClass.CRYPTO, qty="100", cost_usd="10"),
        ],
    )
    # Desk book: 10*30 + 100*0.50 = 350
    repo.upsert_rows(
        "Prices",
        [_price_row("PLTR", "30"), _price_row("DOGE", "0.50")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        assert interval == "5m"
        now = datetime.now(timezone.utc)
        out: dict[str, list[tuple[str, Decimal]]] = {}
        for _ysym, our in yahoo_map.items():
            series: list[tuple[str, Decimal]] = []
            for i in range(12):
                ts = (now - timedelta(minutes=5 * (11 - i))).replace(
                    microsecond=0
                ).isoformat()
                # Yahoo inflated vs book (constant qty → path tip 500)
                if our == "PLTR":
                    series.append((ts, Decimal("40")))
                else:
                    series.append((ts, Decimal("1.00")))
            out[our] = series
        return out

    svc = PriceHistoryService(repo, fetcher=fake_fetch, cache_ttl_seconds=0)
    result = svc.history(scope="all", range_key="1d")
    assert result.series_kind == "market_value"
    assert result.meta["point_kind"] == "intraday"
    assert len(result.points) >= 2
    # Pure Yahoo tip (not rewritten to book)
    assert result.points[-1]["value"] != "350.00"
    assert result.meta.get("book_market_value_usd") == "350.00"
    path_last = Decimal(result.points[-1]["value"])
    assert Decimal(result.meta["book_vs_path_abs"]) == path_last - Decimal("350.00")
    assert "yahoo" in (result.meta.get("note") or "").lower()


def test_history_1d_ticker_path_not_pinned_exposes_book_meta():
    """1D last price stays Yahoo; book_price_usd in meta for desk comparison."""
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="10", cost_usd="200")],
    )
    repo.upsert_rows("Prices", [_price_row("PLTR", "25.50")])

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        assert interval == "5m"
        now = datetime.now(timezone.utc)
        our = yahoo_map[yahoo_symbols[0]]
        series = []
        for i in range(8):
            ts = (now - timedelta(minutes=5 * (7 - i))).replace(microsecond=0).isoformat()
            series.append((ts, Decimal("22.00")))
        return {our: series}

    svc = PriceHistoryService(repo, fetcher=fake_fetch, cache_ttl_seconds=0)
    result = svc.history(scope="ticker", range_key="1d", ticker="PLTR")
    assert result.points[-1]["value"] == "22.0000"
    assert result.meta.get("book_price_usd") == "25.5000"
    assert result.meta.get("book_vs_path_abs") == "-3.5000"


def test_portfolio_1d_aligned_grid_full_book_and_additive():
    """Shared 5m grid: full book from first bar; Δ ≈ stock session + crypto local day."""
    from zoneinfo import ZoneInfo

    from backend.services.price_history import (
        COVERAGE_THRESHOLD_INTRADAY,
        build_portfolio_1d_aligned_closes,
        aggregate_mv_series_time_aware,
        _change_meta,
    )

    now = datetime(2026, 8, 10, 21, 30, 0, tzinfo=timezone.utc)
    zone = ZoneInfo("Europe/Prague")
    cutoff = now - timedelta(hours=24)

    stock_full = [
        ("2026-08-09T19:55:00+00:00", Decimal("100")),  # prior close
        ("2026-08-10T13:30:00+00:00", Decimal("100")),
        ("2026-08-10T21:25:00+00:00", Decimal("110")),  # +10/sh session
    ]
    crypto_full = []
    t0 = cutoff
    for i in range(0, 24 * 12 + 1):
        ts = (t0 + timedelta(minutes=5 * i)).replace(microsecond=0).isoformat()
        px = Decimal("1000") - Decimal(i) * Decimal("0.5")  # −144 over 24h
        crypto_full.append((ts, px))

    closes_raw = {"STK": stock_full, "CRY": crypto_full}
    ac_map = {"STK": "Stock", "CRY": "Crypto"}
    aligned, status = build_portfolio_1d_aligned_closes(
        closes_raw, ac_map, now=now, zone=zone
    )
    assert status == "local_day"
    assert aligned["STK"][0][0] == "2026-08-09T22:00:00+00:00"
    # Identical timestamps for stock and crypto
    assert [p[0] for p in aligned["STK"]] == [p[0] for p in aligned["CRY"]]
    assert len(aligned["STK"]) >= 200

    events = [
        _event(
            ticker="STK",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="10",
            asset_class=AssetClass.STOCK,
        ),
        _event(
            ticker="CRY",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    series, _ = aggregate_mv_series_time_aware(
        tl,
        aligned,
        coverage_threshold=COVERAGE_THRESHOLD_INTRADAY,
        preseed_first_marks=True,
    )
    assert len(series) > 10
    assert _parse_ts(series[0][0]) < _parse_ts("2026-08-10T13:00:00+00:00")

    # First two bars full book — tiny jump
    if len(series) >= 2:
        jump = abs(series[1][1] - series[0][1])
        assert jump < series[0][1] * Decimal("0.05")

    # First MV = 10*100 + 1*~1000 = ~2000 (full book, not stocks-only 1000)
    assert series[0][1] > Decimal("1500")
    assert series[0][1] < Decimal("3000")

    ch = _change_meta(series[0][1], series[-1][1])
    assert ch["change_abs"] is not None
    net = Decimal(ch["change_abs"])
    # +100 stock, about -144 crypto → net negative, modest
    assert net < Decimal("50")
    assert net > Decimal("-200")


def test_performance_excludes_window_buys():
    """Flat prices + mid-window buy: mark performance 0; MV Δ = purchase."""
    from backend.services.price_history import (
        aggregate_mv_series_time_aware,
        performance_change_meta,
        window_mark_performance,
    )

    buy_dt = datetime(2026, 8, 11, 11, 45, 0, tzinfo=timezone.utc)
    events = [
        _event(
            ticker="BASE",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 1),
            event_datetime=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        ),
        _event(
            ticker="DOGE",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 11),
            event_datetime=buy_dt,
            qty="100",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    closes = {
        "BASE": [
            ("2026-08-11T10:00:00+00:00", Decimal("1000")),
            ("2026-08-11T11:45:00+00:00", Decimal("1000")),
            ("2026-08-11T12:00:00+00:00", Decimal("1000")),
        ],
        "DOGE": [
            ("2026-08-11T10:00:00+00:00", Decimal("10")),
            ("2026-08-11T11:45:00+00:00", Decimal("10")),
            ("2026-08-11T12:00:00+00:00", Decimal("10")),
        ],
    }
    series, _ = aggregate_mv_series_time_aware(
        tl, closes, coverage_threshold=Decimal("0.5"), preseed_first_marks=True
    )
    mark = window_mark_performance(
        tl,
        closes,
        chart_first_ts=series[0][0],
        chart_last_ts=series[-1][0],
    )
    ch = performance_change_meta(
        series[0][1],
        series[-1][1],
        performance_abs=mark["performance_abs"],
        open_basis_usd=mark["open_basis_usd"],
        performance_pct=mark["performance_pct"],
    )
    # Headline = book Δ (line); mark P&L excludes mid-window buy
    assert Decimal(ch["change_abs"]) == Decimal("1000.00")
    assert Decimal(ch["mv_change_abs"]) == Decimal("1000.00")
    assert Decimal(ch["mark_pnl_abs"]) == Decimal("0.00")
    assert Decimal(ch["net_capital_abs"]) == Decimal("1000.00")
    assert ch["change_basis"] == "book_with_mark_reconciliation"
    # Identity: book = mark + net capital
    assert (
        Decimal(ch["change_abs"])
        == Decimal(ch["mark_pnl_abs"]) + Decimal(ch["net_capital_abs"])
    )


def test_book_mark_net_capital_identity_on_sell():
    """
    Sell toy model (user's $8.8k gap):
      open 100 @ 100 → end 20 @ 110 after selling 80
      book Δ = 20*110 − 100*100 = −7800
      mark   = 100*(110−100) = +1000  (held-through open qty)
      net capital = book − mark = −8800
    """
    from backend.services.price_history import (
        performance_change_meta,
        window_mark_performance,
    )

    events = [
        _event(
            ticker="XYZ",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            event_datetime=datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            qty="100",
            asset_class=AssetClass.STOCK,
        ),
        _event(
            ticker="XYZ",
            event_type=InvestmentEventType.SELL,
            event_date=date(2026, 8, 8),
            event_datetime=datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc),
            qty="80",
            asset_class=AssetClass.STOCK,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    closes = {
        "XYZ": [
            ("2026-08-05", Decimal("100")),
            ("2026-08-08", Decimal("105")),
            ("2026-08-11", Decimal("110")),
        ]
    }
    # Book endpoints from holdings × prices
    book_first = Decimal("100") * Decimal("100")  # 10000
    book_last = Decimal("20") * Decimal("110")  # 2200
    mark = window_mark_performance(
        tl,
        closes,
        chart_first_ts="2026-08-05",
        chart_last_ts="2026-08-11",
    )
    assert mark["performance_abs"] == Decimal("1000.00")  # 100 * 10
    ch = performance_change_meta(
        book_first,
        book_last,
        performance_abs=mark["performance_abs"],
        open_basis_usd=mark["open_basis_usd"],
        performance_pct=mark["performance_pct"],
    )
    assert Decimal(ch["change_abs"]) == Decimal("-7800.00")
    assert Decimal(ch["mark_pnl_abs"]) == Decimal("1000.00")
    assert Decimal(ch["net_capital_abs"]) == Decimal("-8800.00")
    assert (
        Decimal(ch["change_abs"])
        == Decimal(ch["mark_pnl_abs"]) + Decimal(ch["net_capital_abs"])
    )


def test_mark_performance_price_move_held_through():
    """Held qty × price change; mid-window buy excluded from performance."""
    from backend.services.price_history import window_mark_performance

    events = [
        _event(
            ticker="ETH",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            event_datetime=datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            qty="10",
            asset_class=AssetClass.CRYPTO,
        ),
        _event(
            ticker="ETH",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 8),
            event_datetime=datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc),
            qty="5",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    # no value_usd on second buy — must not matter
    events[1] = events[1].model_copy(update={"value_usd": None, "value_native": None})
    tl = build_holdings_timeline(events, [])
    closes = {
        "ETH": [
            ("2026-08-05", Decimal("3000")),
            ("2026-08-08", Decimal("3100")),
            ("2026-08-11", Decimal("3200")),
        ]
    }
    mark = window_mark_performance(
        tl,
        closes,
        chart_first_ts="2026-08-05",
        chart_last_ts="2026-08-11",
    )
    # open qty before 2026-08-05 = 10; mid buy excluded
    # perf = 10 * (3200 - 3000) = 2000
    assert mark["performance_abs"] == Decimal("2000.00")


def test_mark_performance_ignores_buy_even_if_yahoo_starts_after_buy():
    """New ticker mid-window: performance 0 even when prices exist for full range."""
    from backend.services.price_history import window_mark_performance

    events = [
        _event(
            ticker="OLD",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
            asset_class=AssetClass.STOCK,
        ),
        _event(
            ticker="NEW",
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 8, 8),
            qty="100",
            asset_class=AssetClass.STOCK,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    closes = {
        "OLD": [
            ("2026-08-05", Decimal("100")),
            ("2026-08-11", Decimal("110")),
        ],
        "NEW": [
            ("2026-08-05", Decimal("50")),
            ("2026-08-11", Decimal("60")),  # would look like +1000 if q counted
        ],
    }
    mark = window_mark_performance(
        tl,
        closes,
        chart_first_ts="2026-08-05",
        chart_last_ts="2026-08-11",
    )
    # Only OLD: 1*(110-100)=10; NEW open qty before Aug 5 = 0
    assert mark["performance_abs"] == Decimal("10.00")


def test_portfolio_window_components_additive():
    """Portfolio window performance = stock RTH + crypto local day (ex-flows)."""
    from backend.services.price_history import portfolio_window_from_components

    now = datetime(2026, 8, 10, 21, 30, 0, tzinfo=timezone.utc)
    # Patch "now" indirectly via series dates relative to AS_OF-style fixed window
    stock = [
        ("2026-08-09T19:55:00+00:00", Decimal("100")),
        ("2026-08-10T13:30:00+00:00", Decimal("100")),
        ("2026-08-10T21:25:00+00:00", Decimal("110")),
    ]
    crypto = []
    t0 = now - timedelta(hours=24)
    for i in range(0, 24 * 12 + 1):
        ts = (t0 + timedelta(minutes=5 * i)).replace(microsecond=0).isoformat()
        crypto.append((ts, Decimal("1000") - Decimal(i) * Decimal("0.5")))

    closes = {"STK": stock, "CRY": crypto}
    ac = {"STK": "Stock", "CRY": "Crypto"}
    events = [
        _event(
            ticker="STK",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="10",
            asset_class=AssetClass.STOCK,
        ),
        _event(
            ticker="CRY",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    # Freeze trim "now" by using series that encode windows; portfolio_window uses date.today
    # so we only assert structure and that sum = stock + crypto legs
    comp = portfolio_window_from_components(
        tl,
        closes,
        ac,
        ["STK", "CRY"],
        is_intraday=True,
        coverage_threshold=Decimal("0.5"),
    )
    s = Decimal(comp["stocks"]["change_usd"])
    c = Decimal(comp["crypto"]["change_usd"])
    total = Decimal(comp["sum_change_usd"])
    assert total == s + c


def test_window_performance_mocked():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="AAA", asset_class=AssetClass.STOCK, qty="10", cost_usd="100"),
            _lot(ticker="BBB", asset_class=AssetClass.STOCK, qty="5", cost_usd="50"),
            _lot(ticker="CCC", asset_class=AssetClass.CRYPTO, qty="1", cost_usd="10"),
        ],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        out = {}
        for y in yahoo_symbols:
            our = yahoo_map[y]
            if our == "AAA":
                out[our] = [
                    ("2025-01-01", Decimal("10")),
                    ("2025-06-01", Decimal("15")),
                ]
            elif our == "BBB":
                out[our] = [
                    ("2025-01-01", Decimal("100")),
                    ("2025-06-01", Decimal("80")),
                ]
            # CCC missing
        return out

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.window_performance(range_key="1y")
    assert result["range"] == "1y"
    by_t = {i["ticker"]: i for i in result["items"]}
    assert by_t["AAA"]["change_pct"] == 50.0
    assert by_t["BBB"]["change_pct"] == -20.0
    assert by_t["CCC"]["change_pct"] is None
    # Sorted best first
    assert result["items"][0]["ticker"] == "AAA"


def test_history_all_uses_as_of_holdings():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="OLD", asset_class=AssetClass.STOCK, qty="1", cost_usd="10"),
            _lot(ticker="NEW", asset_class=AssetClass.STOCK, qty="100", cost_usd="1000"),
        ],
    )
    repo.upsert_rows(
        "InvestmentEvents",
        [
            _event(
                ticker="OLD",
                event_type=InvestmentEventType.BUY,
                event_date=date(2021, 1, 1),
                qty="1",
            ),
            _event(
                ticker="NEW",
                event_type=InvestmentEventType.BUY,
                event_date=date(2024, 6, 1),
                qty="100",
            ),
        ],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        out = {}
        for y in yahoo_symbols:
            our = yahoo_map[y]
            out[our] = [
                ("2021-08-11", Decimal("10") if our == "OLD" else Decimal("100")),
                ("2025-01-15", Decimal("12") if our == "OLD" else Decimal("11")),
            ]
        return out

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.history(scope="all", range_key="5y")
    assert result.meta.get("quantity_basis") == "holdings_as_of_each_date"
    by_d = {p["date"]: Decimal(p["value"]) for p in result.points}
    assert by_d["2021-08-11"] == Decimal("10.00")
    assert by_d["2025-01-15"] == Decimal("1112.00")


def _five_min_series(
    start: datetime,
    end: datetime,
    px_at,
) -> list[tuple[str, Decimal]]:
    out: list[tuple[str, Decimal]] = []
    t = start.astimezone(timezone.utc).replace(second=0, microsecond=0)
    end_u = end.astimezone(timezone.utc)
    i = 0
    while t <= end_u:
        out.append((t.isoformat(), px_at(i, t)))
        t += timedelta(minutes=5)
        i += 1
    return out


def test_trim_intraday_local_day_prague():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import trim_intraday_series

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)
    start = now - timedelta(hours=36)
    series = _five_min_series(
        start, now, lambda i, _t: Decimal("100") + Decimal(i) * Decimal("0.01")
    )
    trimmed, status = trim_intraday_series(
        series, mode="local_day_or_prior", now=now, zone=zone
    )
    assert status == "local_day"
    assert trimmed[0][0] == "2026-08-09T22:00:00+00:00"
    midnight = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    for ts, _px in trimmed:
        assert _parse_ts(ts) >= midnight


def test_trim_intraday_prior_local_day_after_midnight():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import trim_intraday_series

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 0, 10, tzinfo=zone)
    start = datetime(2026, 8, 9, 0, 0, tzinfo=zone)
    end = datetime(2026, 8, 9, 23, 55, tzinfo=zone)
    series = _five_min_series(start, end, lambda i, _t: Decimal("50") + Decimal(i))
    trimmed, status = trim_intraday_series(
        series, mode="local_day_or_prior", now=now, zone=zone
    )
    assert status == "prior_local_day"
    assert trimmed
    for ts, _px in trimmed:
        assert _parse_ts(ts).astimezone(zone).date() == date(2026, 8, 9)


def test_trim_intraday_dst_midnight():
    from zoneinfo import ZoneInfo

    from backend.common.timeutil import local_midnight
    from backend.services.price_history import trim_intraday_series

    zone = ZoneInfo("Europe/Prague")

    def _assert_local_day(now: datetime) -> None:
        start = now.astimezone(timezone.utc) - timedelta(hours=40)
        series = _five_min_series(
            start, now, lambda i, _t: Decimal("10") + Decimal(i) * Decimal("0.01")
        )
        trimmed, status = trim_intraday_series(
            series, mode="local_day_or_prior", now=now, zone=zone
        )
        assert status == "local_day"
        mid = local_midnight(now, zone)
        mid_utc = mid.astimezone(timezone.utc).replace(microsecond=0)
        assert _parse_ts(trimmed[0][0]) == mid_utc
        ago_24h = now.astimezone(timezone.utc) - timedelta(hours=24)
        assert mid_utc != ago_24h.replace(second=0, microsecond=0)
        for ts, _px in trimmed:
            assert _parse_ts(ts) >= mid
        span = _parse_ts(trimmed[-1][0]) - _parse_ts(trimmed[0][0])
        assert span < timedelta(hours=24)

    _assert_local_day(datetime(2026, 3, 29, 15, 0, tzinfo=zone))
    _assert_local_day(datetime(2026, 10, 25, 15, 0, tzinfo=zone))


def test_day_open_is_midnight_print():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import trim_intraday_series

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)
    midnight_px = Decimal("80.25")
    series = [
        ("2026-08-09T21:55:00+00:00", midnight_px),
        ("2026-08-09T22:05:00+00:00", Decimal("81.00")),
        ("2026-08-10T12:55:00+00:00", Decimal("82.00")),
    ]
    trimmed, status = trim_intraday_series(
        series, mode="local_day_or_prior", now=now, zone=zone
    )
    assert status == "local_day"
    assert trimmed[0][0] == "2026-08-09T22:00:00+00:00"
    assert trimmed[0][1] == midnight_px
    assert trimmed[1][0] == "2026-08-09T22:05:00+00:00"


def test_portfolio_1d_grid_from_local_midnight():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import (
        COVERAGE_THRESHOLD_INTRADAY,
        aggregate_mv_series_time_aware,
        build_portfolio_1d_aligned_closes,
    )

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 21, 30, 0, tzinfo=timezone.utc)
    stock_full = [
        ("2026-08-09T19:55:00+00:00", Decimal("100")),
        ("2026-08-10T13:30:00+00:00", Decimal("100")),
        ("2026-08-10T21:25:00+00:00", Decimal("110")),
    ]
    crypto_full = _five_min_series(
        now - timedelta(hours=30),
        now,
        lambda i, _t: Decimal("1000") - Decimal(i) * Decimal("0.5"),
    )
    aligned, status = build_portfolio_1d_aligned_closes(
        {"STK": stock_full, "CRY": crypto_full},
        {"STK": "Stock", "CRY": "Crypto"},
        now=now,
        zone=zone,
    )
    assert status == "local_day"
    first_ts = aligned["STK"][0][0]
    assert first_ts == "2026-08-09T22:00:00+00:00"
    assert first_ts != (now - timedelta(hours=24)).replace(microsecond=0).isoformat()
    assert [p[0] for p in aligned["STK"]] == [p[0] for p in aligned["CRY"]]

    events = [
        _event(
            ticker="STK",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="10",
            asset_class=AssetClass.STOCK,
        ),
        _event(
            ticker="CRY",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    series, _ = aggregate_mv_series_time_aware(
        tl,
        aligned,
        coverage_threshold=COVERAGE_THRESHOLD_INTRADAY,
        preseed_first_marks=True,
    )
    d_stk = (aligned["STK"][-1][1] - aligned["STK"][0][1]) * Decimal("10")
    d_cry = (aligned["CRY"][-1][1] - aligned["CRY"][0][1]) * Decimal("1")
    d_chart = series[-1][1] - series[0][1]
    assert abs(d_chart - (d_stk + d_cry)) <= Decimal("0.01")


def test_portfolio_window_components_local_day():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import (
        COVERAGE_THRESHOLD_INTRADAY,
        build_portfolio_1d_aligned_closes,
        portfolio_window_from_components,
    )

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 21, 30, 0, tzinfo=timezone.utc)
    stock = [
        ("2026-08-09T19:55:00+00:00", Decimal("100")),
        ("2026-08-10T13:30:00+00:00", Decimal("100")),
        ("2026-08-10T21:25:00+00:00", Decimal("110")),
    ]
    crypto = _five_min_series(
        now - timedelta(hours=30),
        now,
        lambda i, _t: Decimal("1000") - Decimal(i) * Decimal("0.5"),
    )
    closes = {"STK": stock, "CRY": crypto}
    ac = {"STK": "Stock", "CRY": "Crypto"}
    events = [
        _event(
            ticker="STK",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="10",
            asset_class=AssetClass.STOCK,
        ),
        _event(
            ticker="CRY",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    aligned, _st = build_portfolio_1d_aligned_closes(
        closes, ac, now=now, zone=zone
    )
    assert [p[0] for p in aligned["STK"]] == [p[0] for p in aligned["CRY"]]
    comp = portfolio_window_from_components(
        tl,
        closes,
        ac,
        ["STK", "CRY"],
        is_intraday=True,
        coverage_threshold=COVERAGE_THRESHOLD_INTRADAY,
        now=now,
        zone=zone,
    )
    assert comp["method"] == "stocks_extended_plus_crypto_local_day_mark"
    s = Decimal(comp["stocks"]["change_usd"])
    c = Decimal(comp["crypto"]["change_usd"])
    assert Decimal(comp["sum_change_usd"]) == s + c
    smv = Decimal(comp["stocks"]["mv_change_usd"])
    cmv = Decimal(comp["crypto"]["mv_change_usd"])
    assert Decimal(comp["sum_mv_change_usd"]) == smv + cmv
    d_stk = (aligned["STK"][-1][1] - aligned["STK"][0][1]) * Decimal("10")
    d_cry = (aligned["CRY"][-1][1] - aligned["CRY"][0][1]) * Decimal("1")
    assert abs(smv + cmv - (d_stk + d_cry)) <= Decimal("0.50")


def test_window_performance_1d_matches_history_trim():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="BTC", asset_class=AssetClass.CRYPTO, qty="1", cost_usd="10")],
    )
    series = [
        ("2026-08-09T21:55:00+00:00", Decimal("100.00")),
        ("2026-08-09T22:05:00+00:00", Decimal("101.00")),
        ("2026-08-10T12:55:00+00:00", Decimal("110.00")),
    ]

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        assert interval == "5m"
        our = yahoo_map[yahoo_symbols[0]]
        return {our: list(series)}

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    hist = svc.history(
        scope="ticker", range_key="1d", ticker="BTC", now=now, zone=zone
    )
    wperf = svc.window_performance(range_key="1d", now=now, zone=zone)
    item = next(i for i in wperf["items"] if i["ticker"] == "BTC")
    assert hist.points[0]["value"] == hist.meta["day_open"]
    assert item["first_value"] == hist.points[0]["value"]
    assert item["day_open"] == hist.meta["day_open"]
    assert item["last_value"] == hist.points[-1]["value"]
    assert item["change_pct"] == hist.meta["change_pct"]


def test_window_performance_pnl_usd():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    now = datetime(2026, 8, 10, 14, 0, tzinfo=zone)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="AAA", asset_class=AssetClass.STOCK, qty="2", cost_usd="20")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        our = yahoo_map[yahoo_symbols[0]]
        return {
            our: [
                # Friday 15:55 ET prior RTH last
                ("2026-08-07T19:55:00+00:00", Decimal("9")),
                ("2026-08-10T13:30:00+00:00", Decimal("10")),
                ("2026-08-10T17:00:00+00:00", Decimal("11")),
            ]
        }

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.window_performance(range_key="1d", now=now, zone=zone)
    item = next(i for i in result["items"] if i["ticker"] == "AAA")
    # qty 2 × (11 − 9 prior close)
    assert item["pnl_usd"] == "4.00"
    assert item["change_abs"] == "2.0000"
    assert item["prior_close"] == "9.0000"
    assert item["day_open"] == "10.0000"


def test_window_performance_pnl_usd_no_prior_rth_fallback():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    now = datetime(2026, 8, 10, 14, 0, tzinfo=zone)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="AAA", asset_class=AssetClass.STOCK, qty="2", cost_usd="20")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        our = yahoo_map[yahoo_symbols[0]]
        return {
            our: [
                ("2026-08-10T13:30:00+00:00", Decimal("10")),
                ("2026-08-10T17:00:00+00:00", Decimal("11")),
            ]
        }

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.window_performance(range_key="1d", now=now, zone=zone)
    item = next(i for i in result["items"] if i["ticker"] == "AAA")
    # Fallback (2) last − first plotted (vs 09:30)
    assert item["pnl_usd"] == "2.00"
    assert item["change_abs"] is not None
    assert item["prior_close"] is None
    assert item["day_open"] == "10.0000"


def test_resolve_day_change_1d_uses_trimmed_series():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="BTC", asset_class=AssetClass.CRYPTO, qty="1", cost_usd="10")],
    )
    print_24h_ago = Decimal("50.00")
    midnight_print = Decimal("80.00")

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        our = yahoo_map[yahoo_symbols[0]]
        return {
            our: [
                ("2026-08-09T13:00:00+00:00", print_24h_ago),
                ("2026-08-09T21:55:00+00:00", midnight_print),
                ("2026-08-09T22:05:00+00:00", Decimal("81.00")),
                ("2026-08-10T12:55:00+00:00", Decimal("90.00")),
            ]
        }

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.history(
        scope="ticker", range_key="1d", ticker="BTC", now=now, zone=zone
    )
    assert result.meta["day_open"] != "50.0000"
    assert result.meta["day_open"] == "80.0000"
    assert result.meta["session_status"] == "local_day"
    assert result.points
    assert all(p.get("session") == "local" for p in result.points)
    assert result.points[0]["value"] == result.meta["day_open"]


def test_resolve_day_change_mixed_mv_not_last_two_daily():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="STK", asset_class=AssetClass.STOCK, qty="10", cost_usd="800"),
            _lot(ticker="CRY", asset_class=AssetClass.CRYPTO, qty="1", cost_usd="800"),
        ],
    )
    repo.upsert_rows(
        "InvestmentEvents",
        [
            _event(
                ticker="STK",
                event_type=InvestmentEventType.BUY,
                event_date=date(2020, 1, 1),
                qty="10",
                asset_class=AssetClass.STOCK,
            ),
            _event(
                ticker="CRY",
                event_type=InvestmentEventType.BUY,
                event_date=date(2020, 1, 1),
                qty="1",
                asset_class=AssetClass.CRYPTO,
            ),
        ],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        out: dict[str, list[tuple[str, Decimal]]] = {}
        for _y, our in yahoo_map.items():
            if interval == "5m":
                if our == "CRY":
                    out[our] = [
                        ("2026-08-09T21:55:00+00:00", Decimal("980")),
                        ("2026-08-09T22:05:00+00:00", Decimal("990")),
                        ("2026-08-10T14:55:00+00:00", Decimal("1000")),
                    ]
            elif our == "STK":
                out[our] = [
                    ("2026-08-07", Decimal("90")),
                    ("2026-08-08", Decimal("92")),
                    ("2026-08-09", Decimal("95")),
                    ("2026-08-10", Decimal("100")),
                ]
            else:
                out[our] = [
                    ("2026-08-07", Decimal("900")),
                    ("2026-08-08", Decimal("920")),
                    ("2026-08-09", Decimal("950")),
                    ("2026-08-10", Decimal("1000")),
                ]
        return out

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.history(scope="all", range_key="1y", now=now, zone=zone)
    # last-two-daily MV open would be 10*95 + 1*950 = 1900
    assert result.meta["day_open"] != "1900.00"
    # T_open = 2026-08-09T22:00Z: stock last daily ≤ T = 95; crypto 5m ≤ T = 980
    assert result.meta["day_open"] == "1930.00"


def _et(y: int, m: int, d: int, hh: int, mm: int):
    from zoneinfo import ZoneInfo

    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York"))


def _stock_extended_bars() -> list[tuple[str, Decimal]]:
    """Prior Friday 15:55 + Mon 04:30 / 10:00 / 15:55 / 16:00 / 17:00 ET."""
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")

    def iso(day: int, hh: int, mm: int) -> str:
        return (
            datetime(2026, 8, day, hh, mm, tzinfo=et)
            .astimezone(timezone.utc)
            .isoformat()
        )

    return [
        (iso(7, 15, 55), Decimal("100")),
        (iso(10, 4, 30), Decimal("101")),
        (iso(10, 10, 0), Decimal("102")),
        (iso(10, 15, 55), Decimal("103")),
        (iso(10, 16, 0), Decimal("104")),
        (iso(10, 17, 0), Decimal("105")),
    ]


def test_classify_us_session_rth_excludes_1600():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import classify_us_session

    et = ZoneInfo("America/New_York")

    def iso(hh: int, mm: int) -> str:
        return (
            datetime(2026, 8, 10, hh, mm, tzinfo=et)
            .astimezone(timezone.utc)
            .isoformat()
        )

    assert classify_us_session(iso(4, 0)) == "pre"
    assert classify_us_session(iso(9, 29)) == "pre"
    assert classify_us_session(iso(9, 30)) == "rth"
    assert classify_us_session(iso(15, 55)) == "rth"
    assert classify_us_session(iso(16, 0)) == "ah"
    assert classify_us_session(iso(17, 0)) == "ah"
    assert classify_us_session(iso(20, 0)) == "ah"
    assert classify_us_session(iso(2, 0)) is None


def test_trim_extended_clocks():
    from backend.services.price_history import trim_intraday_series

    series = _stock_extended_bars()

    def run(now):
        return trim_intraday_series(series, mode="rth_today_or_prior", now=now)

    trimmed, status = run(_et(2026, 8, 10, 2, 0))
    assert status == "overnight"
    assert [p.session for p in trimmed] == ["prior_close"]
    assert trimmed[0].px == Decimal("100")

    trimmed, status = run(_et(2026, 8, 10, 8, 0))
    assert status == "pre_market"
    assert [p.session for p in trimmed] == ["prior_close", "pre"]
    assert all(p.session != "rth" for p in trimmed)

    trimmed, status = run(_et(2026, 8, 10, 10, 0))
    assert status == "regular"
    assert trimmed[0].session == "prior_close"
    assert "pre" in {p.session for p in trimmed}
    assert "rth" in {p.session for p in trimmed}

    trimmed, status = run(_et(2026, 8, 10, 16, 0))
    assert status == "after_hours"
    assert trimmed[-1].session == "ah"
    rth_last = [p for p in trimmed if p.session == "rth"][-1]
    assert rth_last.px == Decimal("103")

    trimmed, status = run(_et(2026, 8, 9, 2, 0))  # Sunday
    assert status == "prior_session"
    assert [p.session for p in trimmed] == ["prior_close"]
    assert trimmed[0].px == Decimal("100")

    trimmed, status = run(_et(2026, 8, 8, 10, 0))  # Saturday
    assert status == "prior_session"
    assert [p.session for p in trimmed] == ["prior_close"]

    from zoneinfo import ZoneInfo

    prague = datetime(2026, 8, 10, 8, 0, tzinfo=ZoneInfo("Europe/Prague"))
    trimmed, status = run(prague)
    assert status == "overnight"
    assert [p.session for p in trimmed] == ["prior_close"]


def test_window_performance_1d_matches_history_stock_extended():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import extended_change_meta, trim_intraday_series

    zone = ZoneInfo("America/New_York")
    bars = _stock_extended_bars()
    clocks = [
        _et(2026, 8, 10, 4, 30),
        _et(2026, 8, 10, 10, 0),
        _et(2026, 8, 10, 15, 55),
        _et(2026, 8, 10, 16, 0),
        _et(2026, 8, 10, 17, 0),
    ]
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="3", cost_usd="30")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        our = yahoo_map[yahoo_symbols[0]]
        return {our: list(bars)}

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    for now in clocks:
        hist = svc.history(
            scope="ticker", range_key="1d", ticker="PLTR", now=now, zone=zone
        )
        wperf = svc.window_performance(range_key="1d", now=now, zone=zone)
        item = next(i for i in wperf["items"] if i["ticker"] == "PLTR")
        for key in (
            "last_value",
            "change_pct",
            "change_abs",
            "day_open",
            "prior_close",
            "change_rth_abs",
            "change_rth_pct",
            "session_status",
        ):
            assert item[key] == hist.meta[key], (now, key, item[key], hist.meta[key])
        assert item["last_value"] == hist.points[-1]["value"]
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            assert item["change_rth_abs"] is None
            assert hist.meta["day_open"] is None
        trimmed, _ = trim_intraday_series(
            bars, mode="rth_today_or_prior", now=now
        )
        ext = extended_change_meta(trimmed, qty=Decimal("3"), places=4)
        assert item["change_abs"] == ext["change_abs"]
        assert item["pnl_usd"] == ext["pnl_usd"]
        if now.hour == 4:
            assert hist.points[0].get("session") == "prior_close"
            assert all(p.get("session") != "rth" for p in hist.points)


def test_pre_market_change_rth_is_none():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    now = _et(2026, 8, 10, 8, 0)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="1", cost_usd="10")],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        our = yahoo_map[yahoo_symbols[0]]
        return {our: list(_stock_extended_bars())}

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    hist = svc.history(scope="ticker", range_key="1d", ticker="PLTR", now=now, zone=zone)
    assert hist.meta["session_status"] == "pre_market"
    assert hist.meta["change_rth_abs"] is None
    assert hist.meta["change_rth_pct"] is None
    assert hist.meta["day_open"] is None
    assert hist.points[0]["session"] == "prior_close"
    assert hist.meta["change_abs"] == "1.0000"  # 101 − 100


def _iso_et(day: int, hh: int, mm: int, *, month: int = 8, year: int = 2026) -> str:
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    return (
        datetime(year, month, day, hh, mm, tzinfo=et)
        .astimezone(timezone.utc)
        .isoformat()
    )


def test_portfolio_grid_0430_et_live_pre_not_stuck_on_prior_rth():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import (
        _prior_rth_close,
        build_portfolio_1d_aligned_closes,
    )

    zone = ZoneInfo("Europe/Prague")
    now = _et(2026, 8, 10, 4, 30)
    stock = [
        (_iso_et(7, 15, 55), Decimal("100")),
        (_iso_et(10, 4, 30), Decimal("120")),
    ]
    crypto = [
        ("2026-08-09T22:00:00+00:00", Decimal("1000")),
        ("2026-08-10T08:30:00+00:00", Decimal("1000")),
    ]
    aligned, status = build_portfolio_1d_aligned_closes(
        {"STK": stock, "CRY": crypto},
        {"STK": "Stock", "CRY": "Crypto"},
        now=now,
        zone=zone,
    )
    assert status == "local_day"
    window_open = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    prior = _prior_rth_close(stock, before=window_open)
    assert prior == Decimal("100")
    assert aligned["STK"][0][1] == Decimal("100")
    assert aligned["STK"][-1][1] == Decimal("120")
    pre_ts = _parse_ts(_iso_et(10, 4, 30))
    for ts, px in aligned["STK"]:
        if _parse_ts(ts) < pre_ts:
            assert px == Decimal("100")
        else:
            assert px == Decimal("120")


def test_portfolio_grid_prague_midnight_seed_is_friday_ah():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import build_portfolio_1d_aligned_closes

    zone = ZoneInfo("Europe/Prague")
    # Sat 08:00 Prague = Fri 18:00 ET window already closed; seed is Fri 17:00 AH.
    now = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)
    stock = [
        (_iso_et(7, 15, 55), Decimal("100")),
        (_iso_et(7, 17, 0), Decimal("110")),
    ]
    crypto = [
        ("2026-08-07T22:00:00+00:00", Decimal("1000")),
        ("2026-08-08T05:55:00+00:00", Decimal("1000")),
    ]
    aligned, status = build_portfolio_1d_aligned_closes(
        {"STK": stock, "CRY": crypto},
        {"STK": "Stock", "CRY": "Crypto"},
        now=now,
        zone=zone,
    )
    assert status == "local_day"
    assert aligned["STK"][0][0] == "2026-08-07T22:00:00+00:00"
    assert aligned["STK"][0][1] == Decimal("110")
    assert aligned["STK"][0][1] != Decimal("100")
    assert aligned["STK"][-1][1] == Decimal("110")


def test_portfolio_grid_extended_additive_identity():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import (
        COVERAGE_THRESHOLD_INTRADAY,
        aggregate_mv_series_time_aware,
        build_portfolio_1d_aligned_closes,
    )

    zone = ZoneInfo("Europe/Prague")
    now = _et(2026, 8, 10, 17, 0)
    stock = [
        (_iso_et(7, 15, 55), Decimal("100")),
        (_iso_et(7, 17, 0), Decimal("105")),
        (_iso_et(10, 4, 30), Decimal("108")),
        (_iso_et(10, 17, 0), Decimal("112")),
    ]
    crypto = _five_min_series(
        datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc),
        now,
        lambda i, _t: Decimal("1000") + Decimal(i) * Decimal("0.25"),
    )
    aligned, status = build_portfolio_1d_aligned_closes(
        {"STK": stock, "CRY": crypto},
        {"STK": "Stock", "CRY": "Crypto"},
        now=now,
        zone=zone,
    )
    assert status == "local_day"
    assert [p[0] for p in aligned["STK"]] == [p[0] for p in aligned["CRY"]]
    assert aligned["STK"][0][1] == Decimal("105")
    assert aligned["STK"][-1][1] == Decimal("112")

    events = [
        _event(
            ticker="STK",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="10",
            asset_class=AssetClass.STOCK,
        ),
        _event(
            ticker="CRY",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])
    series, _ = aggregate_mv_series_time_aware(
        tl,
        aligned,
        coverage_threshold=COVERAGE_THRESHOLD_INTRADAY,
        preseed_first_marks=True,
    )
    d_stk = (aligned["STK"][-1][1] - aligned["STK"][0][1]) * Decimal("10")
    d_cry = (aligned["CRY"][-1][1] - aligned["CRY"][0][1]) * Decimal("1")
    d_chart = series[-1][1] - series[0][1]
    assert d_stk == Decimal("70")
    assert abs(d_chart - (d_stk + d_cry)) <= Decimal("0.01")


def test_portfolio_grid_monday_0200_et_is_friday_last_ah():
    from zoneinfo import ZoneInfo

    from backend.services.price_history import (
        _prior_rth_close,
        build_portfolio_1d_aligned_closes,
    )

    zone = ZoneInfo("Europe/Prague")
    now = _et(2026, 8, 10, 2, 0)
    stock = [
        (_iso_et(7, 15, 55), Decimal("100")),
        (_iso_et(7, 17, 0), Decimal("110")),
    ]
    crypto = [
        ("2026-08-09T22:00:00+00:00", Decimal("1000")),
        ("2026-08-10T06:00:00+00:00", Decimal("1000")),
    ]
    aligned, status = build_portfolio_1d_aligned_closes(
        {"STK": stock, "CRY": crypto},
        {"STK": "Stock", "CRY": "Crypto"},
        now=now,
        zone=zone,
    )
    assert status == "local_day"
    prior = _prior_rth_close(
        stock,
        before=datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc),
    )
    assert prior == Decimal("100")
    assert all(p[1] == Decimal("110") for p in aligned["STK"])
    assert aligned["STK"][-1][1] != Decimal("100")


def test_yfinance_history_batch_prepost_kwarg(monkeypatch):
    import sys
    import types

    import backend.services.price_history as ph

    calls: list[tuple[str, bool | None, str | None]] = []

    class DummyDF:
        empty = True
        columns: list[str] = []

    fake_yf = types.ModuleType("yfinance")

    def download(**kwargs):
        calls.append(("download", kwargs.get("prepost"), kwargs.get("interval")))
        return DummyDF()

    class Ticker:
        def __init__(self, _s: str) -> None:
            pass

        def history(self, **kwargs):
            calls.append(("history", kwargs.get("prepost"), kwargs.get("interval")))
            return DummyDF()

    fake_yf.download = download  # type: ignore[attr-defined]
    fake_yf.Ticker = Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    ph._yfinance_history_batch(
        ["PLTR"], {"PLTR": "PLTR"}, "5d", "5m", prepost=True
    )
    ph._yfinance_history_batch(
        ["BTC-USD"], {"BTC-USD": "BTC"}, "5d", "5m", prepost=False
    )
    ph._yfinance_history_batch(
        ["PLTR"], {"PLTR": "PLTR"}, "1y", "1d", prepost=False
    )

    preposts = [(kind, pre, iv) for kind, pre, iv in calls]
    assert ("download", True, "5m") in preposts
    assert ("download", False, "5m") in preposts
    assert ("download", False, "1d") in preposts


def test_fetch_closes_equity_5m_passes_prepost(monkeypatch):
    import backend.services.price_history as ph

    seen: list[tuple[list[str], str, bool]] = []

    def wrapper(syms, m, period, interval, *, prepost=False):
        seen.append((list(syms), interval, prepost))
        return {
            m[s]: [ph.SeriesPoint("2026-08-10T13:30:00+00:00", Decimal("1"))]
            for s in syms
        }

    monkeypatch.setattr(ph, "_yfinance_history_batch", wrapper)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="1", cost_usd="10"),
            _lot(ticker="BTC", asset_class=AssetClass.CRYPTO, qty="1", cost_usd="10"),
        ],
    )
    svc = PriceHistoryService(repo, enabled=True)
    svc._fetch_closes(
        ["PLTR", "BTC"],
        {"PLTR": "Stock", "BTC": "Crypto"},
        "5d",
        "5m",
    )
    eq = [c for c in seen if c[2] is True]
    cr = [c for c in seen if c[2] is False]
    assert eq and eq[0][1] == "5m"
    assert cr and cr[0][1] == "5m"
    assert "PLTR" in eq[0][0] or any("PLTR" in s for s in eq[0][0])


_PRAGUE_MIDNIGHT_TS = "2026-08-09T22:00:00+00:00"  # 00:00 Prague / 18:00 ET
_RTH_OPEN_TS = "2026-08-10T13:30:00+00:00"  # 09:30 ET


def test_aggregate_crypto_only_book_keeps_local_session():
    """Crypto-only MV must pass through local tags, not US-classify T22:00Z as ah."""
    from backend.services.price_history import SeriesPoint, classify_us_session

    local_bars = [
        SeriesPoint(_PRAGUE_MIDNIGHT_TS, Decimal("80.00"), "local"),
        SeriesPoint("2026-08-10T12:00:00+00:00", Decimal("85.00"), "local"),
        SeriesPoint(_RTH_OPEN_TS, Decimal("90.00"), "local"),
    ]
    qty = {"BTC": Decimal("1")}
    closes = {"BTC": local_bars}

    events = [
        _event(
            ticker="BTC",
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 1, 1),
            qty="1",
            asset_class=AssetClass.CRYPTO,
        ),
    ]
    tl = build_holdings_timeline(events, [])

    constant, _ = aggregate_mv_series(qty, closes)
    aware, _ = aggregate_mv_series_time_aware(tl, closes, tickers=["BTC"])
    assert constant and aware
    for series in (constant, aware):
        assert all(p.session == "local" for p in series)
        by_ts = {p.ts: p.session for p in series}
        assert by_ts[_PRAGUE_MIDNIGHT_TS] == "local"
        assert by_ts[_PRAGUE_MIDNIGHT_TS] != "ah"
        assert by_ts[_RTH_OPEN_TS] == "local"
        assert by_ts[_RTH_OPEN_TS] != "rth"

    # Untagged same timestamps still classify on the US clock (no invented local).
    untagged = [SeriesPoint(p.ts, p.px, None) for p in local_bars]
    us_series, _ = aggregate_mv_series(qty, {"BTC": untagged})
    by_ts = {p.ts: p.session for p in us_series}
    assert classify_us_session(_PRAGUE_MIDNIGHT_TS) == "ah"
    assert by_ts[_PRAGUE_MIDNIGHT_TS] == "ah"
    assert by_ts[_RTH_OPEN_TS] == "rth"


def test_history_crypto_class_1d_local_session_and_midnight_day_open():
    """Crypto book 1D (timeline path): solid local tape, day_open = midnight seed."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="BTC", asset_class=AssetClass.CRYPTO, qty="1", cost_usd="10")],
    )
    repo.upsert_rows(
        "InvestmentEvents",
        [
            _event(
                ticker="BTC",
                event_type=InvestmentEventType.BUY,
                event_date=date(2020, 1, 1),
                qty="1",
                asset_class=AssetClass.CRYPTO,
            ),
        ],
    )
    midnight_px = Decimal("80.00")
    rth_px = Decimal("90.00")

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        assert interval == "5m"
        our = yahoo_map[yahoo_symbols[0]]
        return {
            our: [
                ("2026-08-09T21:55:00+00:00", Decimal("79.00")),
                (_PRAGUE_MIDNIGHT_TS, midnight_px),
                ("2026-08-10T12:00:00+00:00", Decimal("85.00")),
                (_RTH_OPEN_TS, rth_px),
            ]
        }

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.history(
        scope="asset_class",
        range_key="1d",
        asset_class="Crypto",
        now=now,
        zone=zone,
    )
    assert result.meta["session_status"] == "local_day"
    assert result.points
    assert all(p.get("session") == "local" for p in result.points)
    assert result.meta["day_open"] == result.points[0]["value"]
    assert result.meta["day_open"] == "80.00"
    assert result.points[0]["date"] == _PRAGUE_MIDNIGHT_TS
    assert result.meta["day_open"] != "90.00"


def test_history_stock_class_1d_keeps_us_session_tags():
    """Stocks book 1D still prior_close / pre / rth / ah — not local."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    now = _et(2026, 8, 10, 10, 0)
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [_lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="3", cost_usd="30")],
    )
    repo.upsert_rows(
        "InvestmentEvents",
        [
            _event(
                ticker="PLTR",
                event_type=InvestmentEventType.BUY,
                event_date=date(2020, 1, 1),
                qty="3",
                asset_class=AssetClass.STOCK,
            ),
        ],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        our = yahoo_map[yahoo_symbols[0]]
        return {our: list(_stock_extended_bars())}

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.history(
        scope="asset_class",
        range_key="1d",
        asset_class="Stock",
        now=now,
        zone=zone,
    )
    sessions = {p.get("session") for p in result.points}
    allowed = {"prior_close", "pre", "rth", "ah"}
    assert sessions <= allowed
    assert "local" not in sessions
    assert "prior_close" in sessions
    assert sessions & {"pre", "rth", "ah"}


def test_history_mixed_all_1d_serialized_points_have_no_session():
    """scope=all 1D stays serialize-stripped (no local or US tags on points)."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 8, 10, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="PLTR", asset_class=AssetClass.STOCK, qty="10", cost_usd="200"),
            _lot(ticker="BTC", asset_class=AssetClass.CRYPTO, qty="1", cost_usd="80"),
        ],
    )
    repo.upsert_rows(
        "InvestmentEvents",
        [
            _event(
                ticker="PLTR",
                event_type=InvestmentEventType.BUY,
                event_date=date(2020, 1, 1),
                qty="10",
                asset_class=AssetClass.STOCK,
            ),
            _event(
                ticker="BTC",
                event_type=InvestmentEventType.BUY,
                event_date=date(2020, 1, 1),
                qty="1",
                asset_class=AssetClass.CRYPTO,
            ),
        ],
    )

    def fake_fetch(yahoo_symbols, yahoo_map, period, interval):
        out: dict[str, list[tuple[str, Decimal]]] = {}
        for _y, our in yahoo_map.items():
            if our == "BTC":
                out[our] = [
                    ("2026-08-09T21:55:00+00:00", Decimal("80.00")),
                    (_PRAGUE_MIDNIGHT_TS, Decimal("80.00")),
                    (_RTH_OPEN_TS, Decimal("90.00")),
                    ("2026-08-10T17:55:00+00:00", Decimal("91.00")),
                ]
            else:
                out[our] = list(_stock_extended_bars())
        return out

    svc = PriceHistoryService(repo, enabled=True, fetcher=fake_fetch)
    result = svc.history(scope="all", range_key="1d", now=now, zone=zone)
    assert result.points
    for p in result.points:
        assert "session" not in p


def test_day_change_from_series_local_tagged_day_open_is_first_px():
    """Local-tagged crypto tape parks day_open on the midnight seed, not 09:30 ET."""
    from backend.services.price_history import SeriesPoint, _day_change_from_series

    series = [
        SeriesPoint(_PRAGUE_MIDNIGHT_TS, Decimal("80.00"), "local"),
        SeriesPoint(_RTH_OPEN_TS, Decimal("90.00"), "local"),
        SeriesPoint("2026-08-10T12:55:00+00:00", Decimal("91.00"), "local"),
    ]
    meta = _day_change_from_series(series, places=2)
    assert meta["day_open"] == "80.00"

    # Contrast: the same prices US-tagged would jump day_open to first RTH.
    us_tagged = [
        SeriesPoint(_PRAGUE_MIDNIGHT_TS, Decimal("80.00"), "ah"),
        SeriesPoint(_RTH_OPEN_TS, Decimal("90.00"), "rth"),
        SeriesPoint("2026-08-10T12:55:00+00:00", Decimal("91.00"), "rth"),
    ]
    us_meta = _day_change_from_series(us_tagged, places=2)
    assert us_meta["day_open"] == "90.00"
