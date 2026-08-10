"""DCA opportunity alert logic: cost discount, pullback, 52w average, gates."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    Price,
    TradeSide,
)
from backend.services.dca_opportunities import (
    DCA_MAX_ALERTS,
    PositionDcaRow,
    build_dca_alerts,
    build_dca_board,
    build_position_dca_rows,
    evaluate_dca_opportunity,
    history_stats_from_closes,
    select_top_dca_candidates,
)
from backend.sheets.repository import InMemorySheetsRepository

TS = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 8, 9)
ACCT = uuid4()


def _lot(
    ticker: str,
    *,
    qty: str = "10",
    cost_usd: str = "1000",
    acq: date | None = None,
    asset_class: AssetClass = AssetClass.STOCK,
) -> InvestmentLot:
    q = Decimal(qty)
    c = Decimal(cost_usd)
    return InvestmentLot(
        id=uuid4(),
        account_id=ACCT,
        ticker=ticker,
        asset_class=asset_class,
        source="Test",
        acquisition_date=acq or (AS_OF - timedelta(days=40)),
        quantity_opened=q,
        quantity_remaining=q,
        cost_basis_native=c,
        cost_basis_czk=c,
        cost_basis_usd=c,
        native_currency="USD",
        status=LotStatus.OPEN,
        created_at=TS,
        updated_at=TS,
    )


def _price(
    ticker: str,
    price: str,
    *,
    as_of: datetime | None = None,
) -> Price:
    return Price(
        id=uuid4(),
        ticker=ticker,
        price=Decimal(price),
        currency="USD",
        as_of=as_of or datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
        created_at=TS,
        updated_at=TS,
    )


def _row(
    *,
    ticker: str = "AAA",
    asset_class: str = "Stock",
    qty: str = "10",
    cost: str = "1000",
    mark: str = "850",
    last_buy_days: int = 40,
    weight_pct: float = 10.0,
    price_age_days: int = 0,
) -> PositionDcaRow:
    qty_d = Decimal(qty)
    cost_d = Decimal(cost)
    mark_d = Decimal(mark)
    avg = cost_d / qty_d
    mv = qty_d * mark_d
    return PositionDcaRow(
        ticker=ticker,
        asset_class=asset_class,
        qty=qty_d,
        cost_usd=cost_d,
        avg_cost=avg,
        mark=mark_d,
        price_as_of=AS_OF - timedelta(days=price_age_days),
        last_buy=AS_OF - timedelta(days=last_buy_days),
        days_since_buy=last_buy_days,
        position_usd=max(mv, cost_d),
        weight_pct=weight_pct,
        mv_usd=mv,
    )


def test_signal_a_stock_15pct_under_cost_fires_info():
    # avg cost 100, mark 85 → 15% discount
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="85"),
        as_of=AS_OF,
    )
    assert c is not None
    assert c.signal_a is True
    assert c.level == "info"
    assert "15%" in c.body or "below your average cost" in c.body
    assert c.ticker == "AAA"


def test_signal_a_shallow_5pct_no_fire():
    # 5% under cost — below 10% stock threshold
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="95"),
        as_of=AS_OF,
    )
    assert c is None


def test_cooldown_blocks_recent_buy():
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="80", last_buy_days=5),
        as_of=AS_OF,
    )
    assert c is None


def test_crypto_needs_deeper_cost_discount():
    # 12% under — not enough for crypto (18%)
    c = evaluate_dca_opportunity(
        _row(asset_class="Crypto", qty="1", cost="1000", mark="880"),
        as_of=AS_OF,
    )
    assert c is None
    # 20% under — fires
    c2 = evaluate_dca_opportunity(
        _row(asset_class="Crypto", qty="1", cost="1000", mark="800"),
        as_of=AS_OF,
    )
    assert c2 is not None
    assert c2.signal_a is True


def test_concentration_gate():
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="80", weight_pct=50.0),
        as_of=AS_OF,
    )
    assert c is None


def test_dust_position_gate():
    # $50 position
    c = evaluate_dca_opportunity(
        _row(qty="1", cost="50", mark="40"),
        as_of=AS_OF,
    )
    assert c is None


def test_stale_price_gate():
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="80", price_age_days=14),
        as_of=AS_OF,
    )
    assert c is None


def test_signal_b_3m_pullback_near_cost():
    # Mark slightly above avg cost (+3%) but 15% off 3M high
    # avg=100, mark=103, high_3m=121.18 → pullback ~15%
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="103"),
        as_of=AS_OF,
        high_3m=Decimal("121.18"),
    )
    assert c is not None
    assert c.signal_b is True
    assert c.signal_a is False
    assert "3M pullback" in c.body


def test_signal_b_no_fire_without_history_when_above_cost_shallow():
    # Above cost, no history → no signal
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="103"),
        as_of=AS_OF,
        high_3m=None,
        avg_52w=None,
    )
    assert c is None


def test_signal_b_below_52w_average():
    """
    Drawdown below 52-week average: mark under the long-run mean while near book cost.
    avg cost 100, mark 98 (+ not extended), avg_52w 110 → ~10.9% under 52w avg.
    """
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="98"),
        as_of=AS_OF,
        high_3m=None,
        avg_52w=Decimal("110"),
    )
    assert c is not None
    assert c.signal_b is True
    assert c.below_52w_avg_pct is not None and c.below_52w_avg_pct >= 5.0
    assert "52-week average" in c.body


def test_signal_b_52w_requires_clear_margin():
    # Only 2% under 52w avg — below stock 5% bar
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="98"),
        as_of=AS_OF,
        avg_52w=Decimal("100"),
    )
    assert c is None


def test_signal_b_blocks_extended_meltup_pullback():
    # 20% off high but 15% *above* avg cost — chasing
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="115"),
        as_of=AS_OF,
        high_3m=Decimal("144"),
        avg_52w=Decimal("130"),
    )
    assert c is None


def test_deep_discount_warn_level():
    # 30% under stock → warn
    c = evaluate_dca_opportunity(
        _row(qty="10", cost="1000", mark="70"),
        as_of=AS_OF,
    )
    assert c is not None
    assert c.level == "warn"


def test_ranking_caps_at_three():
    cands = []
    for i, disc in enumerate([30, 25, 20, 18, 15]):
        mark = 100 - disc
        c = evaluate_dca_opportunity(
            _row(ticker=f"T{i}", qty="10", cost="1000", mark=str(mark)),
            as_of=AS_OF,
        )
        assert c is not None
        cands.append(c)
    top = select_top_dca_candidates(cands)
    assert len(top) == DCA_MAX_ALERTS
    assert top[0].score >= top[1].score >= top[2].score


def test_history_stats_from_closes():
    series = []
    base = AS_OF - timedelta(days=200)
    for i in range(200):
        day = base + timedelta(days=i)
        # rising then falling: peak mid, end lower
        px = Decimal("100") + Decimal(i % 50)
        series.append((day.isoformat(), px))
    # Force a high peak in last 90d and a higher mean
    series.append(((AS_OF - timedelta(days=10)).isoformat(), Decimal("200")))
    series.append((AS_OF.isoformat(), Decimal("90")))
    stats = history_stats_from_closes(series, as_of=AS_OF)
    assert stats["high_3m"] == Decimal("200")
    assert stats["avg_52w"] is not None
    assert stats["avg_52w"] > 0


def test_build_dca_alerts_with_injected_history():
    lots = [
        _lot("AAA", qty="10", cost_usd="1000", acq=AS_OF - timedelta(days=40)),
        # second small position so AAA weight stays under 35%
        _lot("BBB", qty="20", cost_usd="2000", acq=AS_OF - timedelta(days=40)),
    ]
    prices = {
        "AAA": _price("AAA", "85"),  # 15% under $100 avg
        "BBB": _price("BBB", "100"),  # flat
    }
    # Book MV: AAA 850 + BBB 2000 = 2850; AAA weight ~30%

    def fake_hist(tickers, _ac):
        return {t: {"high_3m": None, "avg_52w": None, "high_52w": None} for t in tickers}

    alerts = build_dca_alerts(
        lots,
        [],
        prices,
        as_of=AS_OF,
        history_fetcher=fake_hist,
        fetch_history=True,
    )
    ids = [a["id"] for a in alerts]
    assert "dca_opportunity_AAA" in ids
    assert "dca_opportunity_BBB" not in ids


def test_build_alerts_integration_includes_dca():
    from backend.services.alerts import build_alerts

    repo = InMemorySheetsRepository()
    # Diversified book so AAA weight < 35%
    lots = [
        _lot("AAA", qty="10", cost_usd="1000", acq=AS_OF - timedelta(days=50)),
        _lot("ZZZ", qty="50", cost_usd="5000", acq=AS_OF - timedelta(days=50)),
    ]
    prices = [
        _price("AAA", "80"),  # 20% under
        _price("ZZZ", "100"),
    ]
    repo.replace_all_rows("Categories", [])
    repo.replace_all_rows("Transactions", [])
    repo.replace_all_rows("FXRates", [])
    repo.replace_all_rows("InvestmentLots", lots)
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("Prices", prices)
    repo.replace_all_rows("Accounts", [])

    # Avoid network: patch build_dca path by ensuring fetch works offline —
    # build_alerts calls build_dca_alerts with fetch_history=True which may hit yfinance.
    # Monkeypatch at module level.
    import backend.services.alerts as alerts_mod
    import backend.services.dca_opportunities as dca_mod

    orig = dca_mod.build_dca_alerts

    def offline_dca(*args, **kwargs):
        kwargs["fetch_history"] = True
        kwargs["history_fetcher"] = lambda tickers, ac: {
            t: {"high_3m": None, "avg_52w": None} for t in tickers
        }
        return orig(*args, **kwargs)

    alerts_mod.build_dca_alerts = offline_dca  # type: ignore[attr-defined]
    try:
        result = build_alerts(repo, persist_fx=False)
    finally:
        alerts_mod.build_dca_alerts = orig  # type: ignore[attr-defined]

    dca = [a for a in result["items"] if str(a["id"]).startswith("dca_opportunity_")]
    assert any(a["id"] == "dca_opportunity_AAA" for a in dca)


def test_build_dca_board_splits_and_ranks():
    lots = [
        _lot("AAA", qty="10", cost_usd="1000", acq=AS_OF - timedelta(days=40)),
        _lot(
            "BTC",
            qty="1",
            cost_usd="2000",
            acq=AS_OF - timedelta(days=40),
            asset_class=AssetClass.CRYPTO,
        ),
        _lot("BBB", qty="5", cost_usd="500", acq=AS_OF - timedelta(days=40)),
    ]
    prices = {
        "AAA": _price("AAA", "70"),  # 30% under — strong
        "BTC": _price("BTC", "1600"),  # 20% under crypto
        "BBB": _price("BBB", "95"),  # 5% under — weak
    }

    def fake_hist(tickers, _ac):
        return {t: {"high_3m": None, "avg_52w": None} for t in tickers}

    board = build_dca_board(
        lots,
        [],
        prices,
        as_of=AS_OF,
        history_fetcher=fake_hist,
        fetch_history=True,
    )
    assert [x["ticker"] for x in board["stocks"]][0] == "AAA"
    assert board["stocks"][0]["score"] >= board["stocks"][1]["score"]
    assert len(board["crypto"]) == 1
    assert board["crypto"][0]["ticker"] == "BTC"
    assert board["stocks"][0]["eligible"] is True
    # BBB shallow discount not eligible but still on board
    bbb = next(x for x in board["stocks"] if x["ticker"] == "BBB")
    assert bbb["eligible"] is False


def test_build_position_rows_prefers_buy_event_date():
    lots = [_lot("AAA", qty="10", cost_usd="1000", acq=AS_OF - timedelta(days=100))]
    events = [
        InvestmentEvent(
            id=uuid4(),
            account_id=ACCT,
            event_type=InvestmentEventType.BUY,
            event_date=AS_OF - timedelta(days=10),
            ticker="AAA",
            asset_class=AssetClass.STOCK,
            side=TradeSide.BUY,
            quantity=Decimal("1"),
            price_native=Decimal("100"),
            native_currency="USD",
            value_native=Decimal("100"),
            value_usd=Decimal("100"),
            source="Test",
            created_at=TS,
            updated_at=TS,
        )
    ]
    prices = {"AAA": _price("AAA", "90")}
    rows = build_position_dca_rows(lots, events, prices, as_of=AS_OF)
    assert len(rows) == 1
    # max(lot 100d ago, event 10d ago) = 10 days ago
    assert rows[0].days_since_buy == 10
