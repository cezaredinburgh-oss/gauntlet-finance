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

    svc = PriceHistoryService(repo, fetcher=fake_fetch)
    result = svc.history(scope="ticker", range_key="1d", ticker="PLTR")
    assert result.interval == "5m"
    assert result.meta["point_kind"] == "intraday"
    assert len(result.points) >= 1
    assert result.meta.get("session_status") in ("regular", "prior_session")
    # Window change on the trimmed series (prior session if "today" not in fixture)
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
) -> InvestmentEvent:
    return InvestmentEvent(
        id=uuid4(),
        account_id=uuid4(),
        event_type=event_type,
        event_date=event_date,
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
    assert len(trimmed) == 2
    assert Decimal(trimmed[-1][1]) == Decimal("111")


def test_trim_intraday_prior_when_no_today():
    from backend.services.price_history import trim_intraday_series, _parse_ts

    series = []
    for h in range(10, 15):
        ts = _parse_ts(f"2026-08-07T{h:02d}:00:00-04:00").astimezone(timezone.utc).isoformat()
        series.append((ts, Decimal(str(100 + h))))
    now = _parse_ts("2026-08-10T08:00:00-04:00")  # pre-open
    trimmed, status = trim_intraday_series(
        series, mode="rth_today_or_prior", now=now
    )
    assert status == "prior_session"
    assert len(trimmed) == 5


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


def test_inject_equity_prior_close_makes_portfolio_span_24h():
    """Overnight crypto move enters portfolio window when equities carry prior close."""
    from backend.services.price_history import (
        COVERAGE_THRESHOLD_INTRADAY,
        inject_equity_prior_close_for_24h,
        trim_closes_map,
        aggregate_mv_series_time_aware,
        _change_meta,
    )

    now = datetime(2026, 8, 10, 21, 30, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(hours=24)

    # Prior RTH bar for stock (yesterday afternoon ET)
    stock_full = [
        ("2026-08-09T19:55:00+00:00", Decimal("100")),  # prior close ~3:55pm ET
        ("2026-08-10T13:30:00+00:00", Decimal("100")),  # open flat
        ("2026-08-10T21:25:00+00:00", Decimal("110")),  # +10/sh session
    ]
    # Crypto declines over 24h
    crypto_full = []
    t0 = cutoff
    for i in range(0, 24 * 12 + 1):
        ts = (t0 + timedelta(minutes=5 * i)).replace(microsecond=0).isoformat()
        px = Decimal("1000") - Decimal(i) * Decimal("0.5")  # −144 over 24h
        crypto_full.append((ts, px))

    closes_raw = {"STK": stock_full, "CRY": crypto_full}
    ac_map = {"STK": "Stock", "CRY": "Crypto"}
    trimmed, _ = trim_closes_map(closes_raw, mode="last_24h", now=now)
    seeded = inject_equity_prior_close_for_24h(
        closes_raw, trimmed, ac_map, now=now
    )
    assert seeded["STK"][0][1] == Decimal("100")
    # Seed should be at/near window start, before RTH open
    assert _parse_ts(seeded["STK"][0][0]) < _parse_ts("2026-08-10T13:30:00+00:00")

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
        seeded,
        coverage_threshold=COVERAGE_THRESHOLD_INTRADAY,
        preseed_first_marks=True,
    )
    assert len(series) > 10
    # Series should start near 24h window (not only at stock open)
    assert _parse_ts(series[0][0]) < _parse_ts("2026-08-10T13:00:00+00:00")

    # First point must be full book (not stocks-only partial) — no huge jump on bar 2
    if len(series) >= 2:
        jump = abs(series[1][1] - series[0][1])
        assert jump < series[0][1] * Decimal("0.15")  # <15% jump on second bar

    ch = _change_meta(series[0][1], series[-1][1])
    # Stock +10*10 = +100; crypto first≈1000 last≈1000-144 = −144 → net ≈ −44
    assert ch["change_abs"] is not None
    net = Decimal(ch["change_abs"])
    assert net < Decimal("0")  # crypto loss dominates overnight+session
    assert net > Decimal("-200")  # not only stock session (+100)


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
