"""Living draw, fees, staking statement extras (incl. Revolut fee-net cash side)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    TradeSide,
)
from backend.services.statement_extras import (
    compute_cashflow_monthly,
    compute_fee_summary,
    compute_living_draw_12m,
    compute_staking_summary,
    compute_statement_extras,
)

TS = datetime(2026, 8, 6, tzinfo=timezone.utc)
AS_OF = date(2026, 8, 7)
ACCT = uuid4()


def _ev(
    *,
    event_type: InvestmentEventType,
    event_date: date,
    value_usd: str | None = None,
    fees_usd: str | None = None,
    quantity: str | None = None,
    ticker: str | None = "DOGE",
    source: str = "Revolut",
    description: str | None = None,
    side: TradeSide | None = None,
) -> InvestmentEvent:
    return InvestmentEvent(
        id=uuid4(),
        account_id=ACCT,
        event_type=event_type,
        event_date=event_date,
        ticker=ticker,
        asset_class=AssetClass.CRYPTO,
        side=side,
        quantity=Decimal(quantity) if quantity is not None else None,
        native_currency="USD",
        value_native=Decimal(value_usd) if value_usd is not None else None,
        value_usd=Decimal(value_usd) if value_usd is not None else None,
        fees_native=Decimal(fees_usd or "0"),
        fees_usd=Decimal(fees_usd) if fees_usd is not None else None,
        source=source,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


def test_living_draw_empty():
    out = compute_living_draw_12m([], as_of=AS_OF)
    assert out["sold_usd"] == "0.00"
    assert out["bought_usd"] == "0.00"
    assert out["draw_usd"] == "0.00"
    assert out["by_ticker"] == []


def test_living_draw_buy_and_sell_window():
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 1, 15),
            value_usd="100.00",
            fees_usd="0.99",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2026, 6, 1),
            value_usd="150.00",
            side=TradeSide.SELL,
            ticker="DOGE",
        ),
    ]
    out = compute_living_draw_12m(events, as_of=AS_OF)
    assert out["sold_usd"] == "150.00"
    assert out["bought_usd"] == "100.00"  # value only, not +fees
    assert out["draw_usd"] == "50.00"


def test_living_draw_ignores_old_and_non_trades():
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2024, 1, 1),
            value_usd="999.00",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.STAKING_REWARD,
            event_date=date(2026, 3, 1),
            value_usd="0",
            quantity="100",
            ticker="SOL",
        ),
        _ev(
            event_type=InvestmentEventType.LOT_ALLOCATION,
            event_date=date(2026, 3, 2),
            value_usd="50.00",
            side=TradeSide.SELL,
            ticker="XRP",
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2026, 3, 2),
            value_usd="50.00",
            side=TradeSide.SELL,
            ticker="XRP",
        ),
    ]
    out = compute_living_draw_12m(events, as_of=AS_OF)
    assert out["sold_usd"] == "50.00"
    assert out["bought_usd"] == "0.00"
    assert out["draw_usd"] == "50.00"


def test_living_draw_ticker_sums():
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 2, 1),
            value_usd="40",
            ticker="DOGE",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 2, 2),
            value_usd="60",
            ticker="XRP",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2026, 4, 1),
            value_usd="30",
            ticker="DOGE",
            side=TradeSide.SELL,
        ),
    ]
    out = compute_living_draw_12m(events, as_of=AS_OF)
    assert out["bought_usd"] == "100.00"
    assert out["sold_usd"] == "30.00"
    by = {r["ticker"]: r for r in out["by_ticker"]}
    assert by["DOGE"]["draw_usd"] == "-10.00"  # 30 - 40
    assert by["XRP"]["draw_usd"] == "-60.00"


def test_fee_summary_revolut_buy_service_fee():
    """Revolut crypto ~0.99% service fee on Buy must count as trade fees (DOGE/XRP)."""
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2025, 5, 1),
            value_usd="100.00",
            fees_usd="0.99",
            ticker="DOGE",
            side=TradeSide.BUY,
            source="Revolut",
        ),
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2025, 5, 2),
            value_usd="200.00",
            fees_usd="1.98",
            ticker="XRP",
            side=TradeSide.BUY,
            source="Revolut",
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2025, 6, 1),
            value_usd="50.00",
            fees_usd="0.10",
            ticker="DOGE",
            side=TradeSide.SELL,
            source="Revolut",
        ),
        _ev(
            event_type=InvestmentEventType.FEE,
            event_date=date(2025, 7, 1),
            value_usd="5.00",
            fees_usd="5.00",
            ticker=None,
            source="Revolut",
            description="CUSTODY FEE",
        ),
        _ev(
            event_type=InvestmentEventType.DEPOSIT,
            event_date=date(2025, 1, 1),
            value_usd="1000.00",
            source="Revolut",
            ticker=None,
        ),
    ]
    out = compute_fee_summary(events)
    assert out["trade_fees_usd"] == "3.07"  # 0.99 + 1.98 + 0.10
    assert out["explicit_fee_events_usd"] == "5.00"
    assert out["total_fees_usd"] == "8.07"
    assert out["deposits_usd"] == "1000.00"
    labels = {x["label"]: x for x in out["fees_by_event_type"]}
    assert "Buy fees" in labels
    assert labels["Buy fees"]["amount_usd"] == "2.97"
    assert labels["Custody fee"]["amount_usd"] == "5.00"
    plats = {x["platform"]: x for x in out["fees_by_platform"]}
    assert "Revolut" in plats
    assert plats["Revolut"]["amount_usd"] == "8.07"


def test_fee_summary_empty():
    out = compute_fee_summary([])
    assert out["total_fees_usd"] == "0.00"
    assert out["fees_by_event_type"] == []


def test_staking_broker_and_live_marks():
    events = [
        _ev(
            event_type=InvestmentEventType.STAKING_REWARD,
            event_date=date(2025, 1, 10),
            value_usd="12.50",
            quantity="1",
            ticker="SOL",
            source="eToro",
        ),
        _ev(
            event_type=InvestmentEventType.STAKING_REWARD,
            event_date=date(2025, 2, 10),
            value_usd=None,
            quantity="10",
            ticker="ADA",
            source="Revolut",
        ),
    ]
    out = compute_staking_summary(events, {"ADA": Decimal("0.50")})
    assert out["reward_rows"] == 2
    assert out["broker_mark_usd"] == "12.50"
    assert out["live_mark_usd"] == "5.00"  # 10 * 0.50
    assert out["mark_usd_total"] == "17.50"
    by = {r["ticker"]: r for r in out["by_ticker"]}
    assert by["SOL"]["mark_source"] == "broker"
    assert by["ADA"]["mark_source"] == "live"


def test_staking_excludes_buys():
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2025, 1, 1),
            value_usd="100",
            quantity="50",
            ticker="SOL",
            side=TradeSide.BUY,
        )
    ]
    out = compute_staking_summary(events, {"SOL": Decimal("2")})
    assert out["reward_rows"] == 0
    assert out["mark_usd_total"] == "0.00"


def test_compute_statement_extras_bundle():
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2026, 1, 1),
            value_usd="100",
            fees_usd="0.99",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.STAKING_REWARD,
            event_date=date(2026, 2, 1),
            value_usd="1",
            quantity="0.01",
            ticker="ETH",
        ),
    ]
    out = compute_statement_extras(events, {"ETH": Decimal("3000")}, as_of=AS_OF)
    assert "living_draw_12m" in out
    assert "fees" in out
    assert "staking" in out
    assert out["living_draw_12m"]["bought_usd"] == "100.00"
    assert out["fees"]["trade_fees_usd"] == "0.99"
    assert out["staking"]["reward_rows"] == 1


def test_cashflow_monthly_cumulative_reinvest():
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2025, 1, 10),
            value_usd="1000",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2025, 1, 20),
            value_usd="500",
            side=TradeSide.SELL,
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2025, 2, 5),
            value_usd="100",
            side=TradeSide.SELL,
        ),
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2025, 2, 8),
            value_usd="50",
            side=TradeSide.BUY,
        ),
    ]
    rows = compute_cashflow_monthly(events, as_of=date(2025, 2, 28), months=2)
    assert len(rows) == 2
    jan = rows[0]
    assert jan["month"] == "2025-01"
    assert jan["bought_usd"] == "1000.00"
    assert jan["sold_usd"] == "500.00"
    # monthly rate 200% (spike), unbounded cum ratio also 200% after Jan
    assert jan["reinvestment_rate_pct"] == 200.0
    assert jan["cumulative_reinvestment_rate_pct"] == 200.0
    # coverage capped at 100% (buys exceed sells)
    assert jan["proceeds_coverage_pct"] == 100.0
    assert jan["cumulative_net_capital_usd"] == "500.00"
    feb = rows[1]
    assert feb["bought_usd"] == "50.00"
    assert feb["sold_usd"] == "100.00"
    assert feb["reinvestment_rate_pct"] == 50.0
    # cum buys 1050 / cum sells 600 = 175% unbounded
    assert feb["cumulative_reinvestment_rate_pct"] == 175.0
    # coverage still 100% (1050 > 600)
    assert feb["proceeds_coverage_pct"] == 100.0
    assert feb["cumulative_net_capital_usd"] == "450.00"


def test_cashflow_proceeds_coverage_partial_and_null_before_sells():
    """Coverage is null until first sell; partial when buys < sells."""
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2025, 1, 10),
            value_usd="500",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2025, 2, 5),
            value_usd="1000",
            side=TradeSide.SELL,
        ),
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2025, 2, 8),
            value_usd="200",
            side=TradeSide.BUY,
        ),
    ]
    rows = compute_cashflow_monthly(events, as_of=date(2025, 2, 28), months=2)
    jan, feb = rows[0], rows[1]
    assert jan["sold_usd"] == "0.00"
    assert jan["reinvestment_rate_pct"] is None
    assert jan["proceeds_coverage_pct"] is None
    assert jan["cumulative_reinvestment_rate_pct"] is None
    # Feb: cum buys 700 / cum sells 1000 → coverage 70%, unbounded 70%
    assert feb["proceeds_coverage_pct"] == 70.0
    assert feb["cumulative_reinvestment_rate_pct"] == 70.0
    assert feb["cumulative_net_capital_usd"] == "-300.00"


def test_cashflow_monthly_auto_history_spans_years():
    """Default months=None returns first buy/sell → as_of (capped 120), >24 when multi-year."""
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2020, 3, 15),
            value_usd="100",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2023, 6, 1),
            value_usd="50",
            side=TradeSide.SELL,
        ),
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2025, 1, 10),
            value_usd="25",
            side=TradeSide.BUY,
        ),
    ]
    rows = compute_cashflow_monthly(events, as_of=date(2025, 2, 28))
    # Mar 2020 → Feb 2025 inclusive = 60 months
    assert len(rows) == 60
    assert rows[0]["month"] == "2020-03"
    assert rows[0]["bought_usd"] == "100.00"
    assert rows[-1]["month"] == "2025-02"
    # Explicit months=2 still short (existing callers/tests)
    short = compute_cashflow_monthly(events, as_of=date(2025, 2, 28), months=2)
    assert len(short) == 2


def test_cashflow_monthly_auto_history_capped_at_120():
    """Span longer than 120 months truncates to last 120 ending at as_of."""
    events = [
        _ev(
            event_type=InvestmentEventType.BUY,
            event_date=date(2005, 1, 10),
            value_usd="999",
            side=TradeSide.BUY,
        ),
        _ev(
            event_type=InvestmentEventType.SELL,
            event_date=date(2025, 2, 5),
            value_usd="50",
            side=TradeSide.SELL,
        ),
    ]
    as_of = date(2025, 2, 28)
    # Disable trim so we can assert the raw 120-month window math
    rows = compute_cashflow_monthly(
        events, as_of=as_of, trim_leading_zeros=False
    )
    assert len(rows) == 120
    assert rows[-1]["month"] == "2025-02"
    # First month is ~120 months before as_of, not 2005-01
    assert rows[0]["month"] == "2015-03"
    # 2005 buy is outside the window — not in first month totals
    assert rows[0]["bought_usd"] == "0.00"
    assert rows[-1]["sold_usd"] == "50.00"
    # Default auto trims leading zeros → only months from first activity
    trimmed = compute_cashflow_monthly(events, as_of=as_of)
    assert len(trimmed) == 1
    assert trimmed[0]["month"] == "2025-02"
    assert trimmed[0]["sold_usd"] == "50.00"


def test_cashflow_uses_value_native_usd_when_value_usd_missing():
    ev = InvestmentEvent(
        id=uuid4(),
        account_id=ACCT,
        event_type=InvestmentEventType.BUY,
        event_date=date(2024, 6, 1),
        ticker="PATH",
        asset_class=AssetClass.STOCK,
        side=TradeSide.BUY,
        quantity=Decimal("10"),
        native_currency="USD",
        value_native=Decimal("500.00"),
        value_usd=None,
        fees_native=Decimal("0"),
        source="Revolut",
        created_at=TS,
        updated_at=TS,
    )
    rows = compute_cashflow_monthly([ev], as_of=date(2024, 6, 30), months=1)
    assert rows[0]["bought_usd"] == "500.00"


def test_cashflow_converts_czk_via_fx_when_value_usd_missing():
    from backend.engines.fx import FXService
    from backend.tests.helpers import fx_rate

    # CNB-style: quote CZK per 1 USD; 2300 CZK → 100 USD at 23 CZK/USD
    fx2 = FXService()
    fx2.load_rates(
        [fx_rate(rate_date=date(2024, 3, 15), base="USD", rate="23.00")]
    )
    ev = InvestmentEvent(
        id=uuid4(),
        account_id=ACCT,
        event_type=InvestmentEventType.BUY,
        event_date=date(2024, 3, 15),
        ticker="SOL",
        asset_class=AssetClass.CRYPTO,
        side=TradeSide.BUY,
        quantity=Decimal("1"),
        native_currency="CZK",
        value_native=Decimal("2300.00"),
        value_usd=None,
        fees_native=Decimal("0"),
        source="Revolut",
        created_at=TS,
        updated_at=TS,
    )
    rows = compute_cashflow_monthly(
        [ev], as_of=date(2024, 3, 31), months=1, fx=fx2
    )
    assert rows[0]["bought_usd"] == "100.00"


def test_cashflow_czk_without_fx_stays_zero():
    ev = InvestmentEvent(
        id=uuid4(),
        account_id=ACCT,
        event_type=InvestmentEventType.BUY,
        event_date=date(2024, 3, 15),
        ticker="SOL",
        asset_class=AssetClass.CRYPTO,
        side=TradeSide.BUY,
        quantity=Decimal("1"),
        native_currency="CZK",
        value_native=Decimal("2300.00"),
        value_usd=None,
        fees_native=Decimal("0"),
        source="Revolut",
        created_at=TS,
        updated_at=TS,
    )
    rows = compute_cashflow_monthly([ev], as_of=date(2024, 3, 31), months=1)
    assert rows[0]["bought_usd"] == "0.00"
