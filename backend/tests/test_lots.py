from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from backend.engines.fx import FXService
from backend.engines.lots import DEFAULT_EXEMPTION_DAYS, LotEngine
from backend.schema.models import InvestmentEventType, LotStatus
from backend.tests.helpers import fx_rate, inv_event


def test_fifo_partial_sell_creates_allocation_and_reduces_lot():
    account = uuid4()
    engine = LotEngine()
    buy = inv_event(
        account_id=account,
        event_type=InvestmentEventType.BUY,
        event_date=date(2021, 11, 18),
        ticker="ETH",
        quantity="0.172396",
        price_native="4060.42",
        value_native="700",
        fees_native="21",
        native_currency="USD",
    )
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2021, 11, 25),
        ticker="ETH",
        quantity="0.11655496",
        price_native="4289.82",
        value_native="500",
        fees_native="10.34",
        native_currency="USD",
    )
    result = engine.apply_events([], [buy, sell])
    lots = [lot for lot in result.lots if lot.ticker == "ETH"]
    assert len(lots) == 1
    lot = lots[0]
    assert lot.status == LotStatus.OPEN
    assert lot.quantity_remaining == Decimal("0.172396") - Decimal("0.11655496")
    allocs = [
        e
        for e in result.events
        if e.event_type == InvestmentEventType.LOT_ALLOCATION
    ]
    assert len(allocs) == 1
    assert allocs[0].parent_event_id == sell.id
    assert allocs[0].lot_id == lot.id
    assert allocs[0].quantity == Decimal("0.11655496")
    assert allocs[0].qualifies_3y_exemption is False
    assert allocs[0].holding_period_days == 7


def test_fifo_full_close():
    account = uuid4()
    engine = LotEngine()
    buy = inv_event(
        account_id=account,
        event_date=date(2021, 11, 15),
        ticker="VALE",
        quantity="84",
        value_native="1020",
    )
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2021, 11, 22),
        ticker="VALE",
        quantity="84",
        value_native="1020.66",
    )
    result = engine.apply_events([], [buy, sell])
    lot = result.lots[0]
    assert lot.quantity_remaining == Decimal("0")
    assert lot.status == LotStatus.CLOSED
    assert lot.cost_basis_native == Decimal("0")


def test_reverse_split_negative_qty_then_sell_closes():
    """Revolut reverse splits use negative quantity (shares removed)."""
    account = uuid4()
    engine = LotEngine()
    buy = inv_event(
        account_id=account,
        event_type=InvestmentEventType.BUY,
        event_date=date(2023, 2, 7),
        ticker="GOEVQ",
        quantity="183.4678899",
        value_native="200",
        price_native="1.09",
    )
    transfer = inv_event(
        account_id=account,
        event_type=InvestmentEventType.TRANSFER,
        event_date=date(2023, 6, 25),
        ticker="GOEVQ",
        quantity="183.4678899",
        value_native="0",
    ).model_copy(update={"notes": "legal_entity_transfer"})
    split1 = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SPLIT,
        event_date=date(2024, 3, 8),
        ticker="GOEVQ",
        quantity="-175.49102512",
        value_native="0",
    )
    split2 = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SPLIT,
        event_date=date(2024, 12, 24),
        ticker="GOEVQ",
        quantity="-7.57802155",
        value_native="0",
    )
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2025, 2, 14),
        ticker="GOEVQ",
        quantity="0.39884323",
        value_native="0.03",
        price_native="0.13",
    )
    result = engine.apply_events([], [buy, transfer, split1, split2, sell])
    open_q = sum(
        (
            lot.quantity_remaining
            for lot in result.lots
            if lot.ticker == "GOEVQ" and lot.status == LotStatus.OPEN
        ),
        Decimal("0"),
    )
    assert open_q == Decimal("0")
    closed = [lot for lot in result.lots if lot.ticker == "GOEVQ"]
    assert closed
    assert all(lot.quantity_remaining == 0 for lot in closed)


def test_forward_split_positive_qty_is_share_delta():
    """Revolut STOCK SPLIT quantity is shares *added*, not post-split total."""
    account = uuid4()
    engine = LotEngine()
    buy = inv_event(
        account_id=account,
        event_type=InvestmentEventType.BUY,
        event_date=date(2023, 1, 1),
        ticker="TSLA",
        quantity="1",
        value_native="200",
        source="Revolut",
    )
    split = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SPLIT,
        event_date=date(2023, 6, 1),
        ticker="TSLA",
        quantity="2",  # 3-for-1: +2 shares on top of 1
        value_native="0",
        source="Revolut",
    )
    result = engine.apply_events([], [buy, split])
    lot = next(lot for lot in result.lots if lot.ticker == "TSLA")
    assert lot.quantity_remaining == Decimal("3")
    assert lot.status == LotStatus.OPEN
    # Cost totals unchanged on forward split
    assert lot.cost_basis_native == Decimal("200")


def test_tsla_revolut_split_matches_broker_total():
    """
    Live-shaped TSLA history: pre-split buys + delta split + post-split buys
    must land on the Revolut UI total (49.19079462).
    """
    account = uuid4()
    engine = LotEngine()
    events = [
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2021, 11, 10),
            ticker="TSLA",
            quantity="2",
            value_native="2000",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2021, 12, 10),
            ticker="TSLA",
            quantity="0.45804616",
            value_native="400",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2022, 2, 7),
            ticker="TSLA",
            quantity="0.81170588",
            value_native="700",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2022, 4, 27),
            ticker="TSLA",
            quantity="0.7489162",
            value_native="600",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2022, 5, 13),
            ticker="TSLA",
            quantity="0.54489076",
            value_native="400",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2022, 6, 2),
            ticker="TSLA",
            quantity="0.31482772",
            value_native="200",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.SPLIT,
            event_date=date(2022, 8, 25),
            ticker="TSLA",
            quantity="9.75677344",  # Revolut delta (3-for-1)
            value_native="0",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2022, 11, 7),
            ticker="TSLA",
            quantity="3",
            value_native="600",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2022, 12, 14),
            ticker="TSLA",
            quantity="18.15652672",
            value_native="3000",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2023, 1, 9),
            ticker="TSLA",
            quantity="8.18175853",
            value_native="1000",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2023, 8, 7),
            ticker="TSLA",
            quantity="1.98854597",
            value_native="500",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2024, 1, 3),
            ticker="TSLA",
            quantity="1.04480106",
            value_native="250",
            source="Revolut",
        ),
        inv_event(
            account_id=account,
            event_type=InvestmentEventType.BUY,
            event_date=date(2024, 2, 2),
            ticker="TSLA",
            quantity="2.18400218",
            value_native="400",
            source="Revolut",
        ),
    ]
    result = engine.apply_events([], events)
    open_q = sum(
        (
            lot.quantity_remaining
            for lot in result.lots
            if lot.ticker == "TSLA" and lot.status == LotStatus.OPEN
        ),
        Decimal("0"),
    )
    assert open_q == Decimal("49.19079462")


def test_fifo_consumes_oldest_lot_first():
    account = uuid4()
    engine = LotEngine()
    buy_old = inv_event(
        account_id=account,
        event_date=date(2020, 1, 1),
        ticker="PLTR",
        quantity="10",
        value_native="100",
    )
    buy_new = inv_event(
        account_id=account,
        event_date=date(2022, 1, 1),
        ticker="PLTR",
        quantity="10",
        value_native="200",
    )
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2023, 1, 1),
        ticker="PLTR",
        quantity="10",
        value_native="300",
    )
    result = engine.apply_events([], [buy_new, buy_old, sell])  # out of order input ok
    lots = {lot.open_event_id: lot for lot in result.lots}
    assert lots[buy_old.id].quantity_remaining == Decimal("0")
    assert lots[buy_old.id].status == LotStatus.CLOSED
    assert lots[buy_new.id].quantity_remaining == Decimal("10")
    alloc = next(
        e for e in result.events if e.event_type == InvestmentEventType.LOT_ALLOCATION
    )
    assert alloc.lot_id == lots[buy_old.id].id


def test_three_year_boundary_exact_exemption_days():
    """Lot acquired exactly exemption_days ago qualifies; one day less does not."""
    engine = LotEngine(exemption_days=DEFAULT_EXEMPTION_DAYS)
    account = uuid4()
    as_of = date(2026, 8, 5)
    acq_eligible = as_of - timedelta(days=DEFAULT_EXEMPTION_DAYS)
    acq_pending = as_of - timedelta(days=DEFAULT_EXEMPTION_DAYS - 1)

    buy_ok = inv_event(
        account_id=account,
        event_date=acq_eligible,
        ticker="PLTR",
        quantity="11",
        value_native="110",
    )
    buy_no = inv_event(
        account_id=account,
        event_date=acq_pending,
        ticker="PLTR",
        quantity="22",
        value_native="220",
    )
    state = engine.apply_events([], [buy_ok, buy_no])
    summary = engine.summarize_ticker(state.lots, "PLTR", as_of=as_of)

    assert summary.total_quantity == Decimal("33")
    assert summary.quantity_tax_free == Decimal("11")
    assert summary.quantity_pending == Decimal("22")

    by_acq = {lot.acquisition_date: lot for lot in summary.lots}
    assert by_acq[acq_eligible].qualifies_3y_exemption is True
    assert by_acq[acq_eligible].tax_free_on == acq_eligible + timedelta(
        days=DEFAULT_EXEMPTION_DAYS
    )
    assert by_acq[acq_pending].qualifies_3y_exemption is False
    assert by_acq[acq_pending].tax_free_on == acq_pending + timedelta(
        days=DEFAULT_EXEMPTION_DAYS
    )


def test_summarize_unrealized_pnl_with_price():
    engine = LotEngine()
    buy = inv_event(
        event_date=date(2024, 1, 1),
        ticker="SPCX",
        quantity="9",
        value_native="900",
    )
    state = engine.apply_events([], [buy])
    summary = engine.summarize_ticker(
        state.lots,
        "SPCX",
        as_of=date(2026, 8, 5),
        market_price_native=Decimal("120"),
    )
    assert summary.market_value_native == Decimal("1080.00")
    assert summary.unrealized_pnl_native == Decimal("180.00")
    assert summary.cost_basis_native == Decimal("900")


def test_sell_realized_gain_with_fx():
    fx = FXService()
    fx.load_rates(
        [
            fx_rate(rate_date=date(2021, 11, 10), base="USD", rate="20.00"),
            fx_rate(rate_date=date(2024, 11, 10), base="USD", rate="22.00"),
        ]
    )
    engine = LotEngine(fx=fx, exemption_days=1095)
    account = uuid4()
    buy = inv_event(
        account_id=account,
        event_date=date(2021, 11, 10),
        ticker="X",
        quantity="10",
        value_native="100",  # $10/sh
        native_currency="USD",
    )
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2024, 11, 10),
        ticker="X",
        quantity="10",
        value_native="150",
        native_currency="USD",
    )
    result = engine.apply_events([], [buy, sell])
    alloc = next(
        e for e in result.events if e.event_type == InvestmentEventType.LOT_ALLOCATION
    )
    # cost 100 USD → 2000 CZK; proceeds 150 → 3300 CZK; gain 1300 CZK
    assert alloc.realized_gain_usd == Decimal("50.00")
    assert alloc.realized_gain_czk == Decimal("1300.00")
    assert alloc.qualifies_3y_exemption is True
    assert alloc.holding_period_days >= 1095


def test_specific_lot_id_on_sell():
    account = uuid4()
    engine = LotEngine()
    buy_a = inv_event(
        account_id=account, event_date=date(2020, 1, 1), ticker="T", quantity="5", value_native="50"
    )
    buy_b = inv_event(
        account_id=account, event_date=date(2021, 1, 1), ticker="T", quantity="5", value_native="100"
    )
    mid = engine.apply_events([], [buy_a, buy_b])
    lot_b = next(lot for lot in mid.lots if lot.open_event_id == buy_b.id)
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2022, 1, 1),
        ticker="T",
        quantity="5",
        value_native="120",
        lot_id=lot_b.id,
    )
    result = engine.apply_events(mid.lots, [sell])
    lots = {lot.open_event_id: lot for lot in result.lots}
    assert lots[buy_b.id].quantity_remaining == Decimal("0")
    assert lots[buy_a.id].quantity_remaining == Decimal("5")


def test_missing_fx_does_not_invent_phantom_realized_loss():
    """C4: sell in non-USD/CZK without FX rates → realized_gain_usd/czk is None, not -cost."""
    account = uuid4()
    engine = LotEngine(fx=None)  # no FX table at all
    buy = inv_event(
        account_id=account,
        event_date=date(2023, 1, 1),
        ticker="SAP",
        quantity="10",
        value_native="1000",
        native_currency="USD",
    )
    # Sell denominated in EUR with no FX available
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2024, 6, 1),
        ticker="SAP",
        quantity="10",
        value_native="900",
        native_currency="EUR",
    )
    result = engine.apply_events([], [buy, sell])
    alloc = next(
        e for e in result.events if e.event_type == InvestmentEventType.LOT_ALLOCATION
    )
    # Cost was USD 1000 → cost_basis_usd on lot is 1000; without EUR→USD rates,
    # must NOT report gain = 0 - 1000 as a phantom loss.
    assert alloc.realized_gain_usd is None
    assert alloc.realized_gain_czk is None
    assert alloc.value_usd is None
    assert alloc.value_czk is None
    # Native proceeds still recorded
    assert alloc.value_native == Decimal("900.00")


def test_missing_fx_with_fx_service_but_no_rates():
    """C4: FXService present but convert returns None for EUR → same as no FX."""
    account = uuid4()
    fx = FXService()  # empty rates
    engine = LotEngine(fx=fx)
    buy = inv_event(
        account_id=account,
        event_date=date(2023, 1, 1),
        ticker="SAP",
        quantity="5",
        value_native="500",
        native_currency="USD",
    )
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2024, 6, 1),
        ticker="SAP",
        quantity="5",
        value_native="12000",
        native_currency="CZK",
    )
    # Sell is CZK native → proc_czk set from native; USD still needs convert
    result = engine.apply_events([], [buy, sell])
    alloc = next(
        e for e in result.events if e.event_type == InvestmentEventType.LOT_ALLOCATION
    )
    assert alloc.value_czk == Decimal("12000.00")
    assert alloc.realized_gain_czk is not None  # CZK proceeds known
    # USD leg: no CZK→USD rate → None (not 0 - cost_usd)
    assert alloc.value_usd is None
    assert alloc.realized_gain_usd is None


def test_short_sell_annotates_unallocated_qty():
    """H5: sell more than held → allocate available only; tag short_sell_unallocated."""
    account = uuid4()
    engine = LotEngine()
    buy = inv_event(
        account_id=account,
        event_date=date(2023, 1, 1),
        ticker="SHORT",
        quantity="1",
        value_native="100",
        native_currency="USD",
    )
    sell = inv_event(
        account_id=account,
        event_type=InvestmentEventType.SELL,
        event_date=date(2024, 1, 1),
        ticker="SHORT",
        quantity="2",
        value_native="200",
        native_currency="USD",
    )
    result = engine.apply_events([], [buy, sell])
    allocs = [
        e
        for e in result.events
        if e.event_type == InvestmentEventType.LOT_ALLOCATION
    ]
    assert len(allocs) == 1
    assert allocs[0].quantity == Decimal("1")
    sell_out = next(
        e for e in result.events if e.event_type == InvestmentEventType.SELL
    )
    notes = (sell_out.notes or "").lower()
    assert "unallocated_qty=" in notes
    assert "short_sell_unallocated" in notes
    assert "1" in notes  # remaining 1
    lot = result.lots[0]
    assert lot.quantity_remaining == Decimal("0")
    assert lot.status == LotStatus.CLOSED


def test_cross_currency_fee_does_not_pollute_native_cost():
    """H6: EUR fee on USD lot without FX → native cost unchanged; no EUR into USD."""
    account = uuid4()
    engine = LotEngine(fx=None)
    buy = inv_event(
        account_id=account,
        event_date=date(2023, 1, 1),
        ticker="AAPL",
        quantity="10",
        value_native="1000",
        native_currency="USD",
    )
    mid = engine.apply_events([], [buy])
    lot = mid.lots[0]
    assert lot.cost_basis_native == Decimal("1000")
    fee = inv_event(
        account_id=account,
        event_type=InvestmentEventType.FEE,
        event_date=date(2023, 1, 2),
        ticker="AAPL",
        quantity=None,
        value_native="15",
        fees_native="15",
        native_currency="EUR",
        parent_event_id=buy.id,
    )
    result = engine.apply_events(mid.lots, [fee])
    lot2 = next(lot for lot in result.lots if lot.id == mid.lots[0].id)
    # Must not add 15 EUR into USD cost_basis_native
    assert lot2.cost_basis_native == Decimal("1000")


def test_cross_currency_fee_converts_when_fx_available():
    """H6: EUR fee on USD lot with FX → add converted amount to native cost."""
    account = uuid4()
    fx = FXService()
    fx.load_rates(
        [
            # 1 EUR = 1.10 USD (via CZK path: EUR/CZK and USD/CZK)
            fx_rate(rate_date=date(2023, 1, 1), base="EUR", rate="25.00"),
            fx_rate(rate_date=date(2023, 1, 1), base="USD", rate="22.00"),
            fx_rate(rate_date=date(2023, 1, 2), base="EUR", rate="25.00"),
            fx_rate(rate_date=date(2023, 1, 2), base="USD", rate="22.00"),
        ]
    )
    engine = LotEngine(fx=fx)
    buy = inv_event(
        account_id=account,
        event_date=date(2023, 1, 1),
        ticker="AAPL",
        quantity="10",
        value_native="1000",
        native_currency="USD",
    )
    mid = engine.apply_events([], [buy])
    fee = inv_event(
        account_id=account,
        event_type=InvestmentEventType.FEE,
        event_date=date(2023, 1, 2),
        ticker="AAPL",
        quantity=None,
        value_native="22",  # 22 EUR → 22 * 25/22 = 25 USD
        fees_native="22",
        native_currency="EUR",
        parent_event_id=buy.id,
    )
    result = engine.apply_events(mid.lots, [fee])
    lot2 = result.lots[0]
    # 22 EUR * (25 CZK/EUR) / (22 CZK/USD) = 25 USD
    assert lot2.cost_basis_native == Decimal("1025.00")
