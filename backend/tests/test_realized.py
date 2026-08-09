"""Dedupe ghost LotAllocation rows for realized lifetime + cost economics."""

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
from backend.services.realized import (
    iter_unique_allocations,
    realized_economics_by_ticker,
    realized_usd_by_ticker,
    sum_realized_economics,
    sum_realized_usd,
)

TS = datetime(2026, 8, 6, tzinfo=timezone.utc)


def _alloc(
    *,
    parent_id,
    lot_id,
    qty: str,
    gain: str,
    ticker: str = "PLTR",
    proceeds: str | None = None,
) -> InvestmentEvent:
    gain_d = Decimal(gain)
    # Default: invent proceeds so cost = 100 for simple cases when not passed
    if proceeds is None:
        # cost 100 → proceeds = cost + gain
        proc = Decimal("100") + gain_d
    else:
        proc = Decimal(proceeds)
    return InvestmentEvent(
        id=uuid4(),
        account_id=uuid4(),
        event_type=InvestmentEventType.LOT_ALLOCATION,
        event_date=date(2026, 6, 1),
        ticker=ticker,
        asset_class=AssetClass.STOCK,
        side=TradeSide.SELL,
        quantity=Decimal(qty),
        native_currency="USD",
        value_native=proc,
        value_usd=proc,
        fees_native=Decimal("0"),
        lot_id=lot_id,
        parent_event_id=parent_id,
        realized_gain_usd=gain_d,
        source="Revolut",
        created_at=TS,
        updated_at=TS,
    )


def test_dedupe_identical_parent_qty_gain():
    parent = uuid4()
    lot_a = uuid4()
    lot_b = uuid4()
    # Ghost double-write: same sell, same numbers, different lot ids
    a = _alloc(parent_id=parent, lot_id=lot_a, qty="10", gain="500")
    b = _alloc(parent_id=parent, lot_id=lot_b, qty="10", gain="500")
    uniq = iter_unique_allocations([a, b])
    assert len(uniq) == 1
    assert sum_realized_usd([a, b]) == Decimal("500")


def test_keep_distinct_lots_same_parent_different_qty():
    parent = uuid4()
    a = _alloc(parent_id=parent, lot_id=uuid4(), qty="7", gain="300")
    b = _alloc(parent_id=parent, lot_id=uuid4(), qty="3", gain="100")
    assert sum_realized_usd([a, b]) == Decimal("400")
    by = realized_usd_by_ticker([a, b])
    assert by["PLTR"] == Decimal("400")


def test_economics_cost_and_roi():
    # Sell: proceeds 1500, cost 500 → gain 1000 → ROI 200%
    a = _alloc(
        parent_id=uuid4(),
        lot_id=uuid4(),
        qty="10",
        gain="1000",
        proceeds="1500",
    )
    eco = sum_realized_economics([a])
    assert eco["gain_usd"] == Decimal("1000.00")
    assert eco["proceeds_usd"] == Decimal("1500.00")
    assert eco["cost_basis_usd"] == Decimal("500.00")
    assert eco["roi_pct"] == 200.0


def test_economics_skips_cost_without_proceeds():
    e = InvestmentEvent(
        id=uuid4(),
        account_id=uuid4(),
        event_type=InvestmentEventType.LOT_ALLOCATION,
        event_date=date(2026, 6, 1),
        ticker="PATH",
        asset_class=AssetClass.STOCK,
        side=TradeSide.SELL,
        quantity=Decimal("5"),
        native_currency="USD",
        value_native=None,
        value_usd=None,
        fees_native=Decimal("0"),
        lot_id=uuid4(),
        parent_event_id=uuid4(),
        realized_gain_usd=Decimal("50"),
        source="Revolut",
        created_at=TS,
        updated_at=TS,
    )
    eco = sum_realized_economics([e])
    assert eco["gain_usd"] == Decimal("50.00")
    assert eco["cost_basis_usd"] == Decimal("0.00")
    assert eco["roi_pct"] is None
    assert eco["gain_only_rows"] == 1


def test_economics_by_ticker():
    a = _alloc(
        parent_id=uuid4(),
        lot_id=uuid4(),
        qty="2",
        gain="100",
        proceeds="400",
        ticker="PLTR",
    )
    b = _alloc(
        parent_id=uuid4(),
        lot_id=uuid4(),
        qty="1",
        gain="-20",
        proceeds="80",
        ticker="PATH",
    )
    by = realized_economics_by_ticker([a, b])
    assert by["PLTR"]["cost_basis_usd"] == Decimal("300.00")
    assert by["PLTR"]["roi_pct"] == round(100 / 300 * 100, 2)
    assert by["PATH"]["cost_basis_usd"] == Decimal("100.00")
    assert by["PATH"]["gain_usd"] == Decimal("-20.00")
