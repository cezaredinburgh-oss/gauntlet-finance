"""Dedupe ghost LotAllocation rows for realized lifetime."""

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
    realized_usd_by_ticker,
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
) -> InvestmentEvent:
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
        value_native=Decimal("100"),
        fees_native=Decimal("0"),
        lot_id=lot_id,
        parent_event_id=parent_id,
        realized_gain_usd=Decimal(gain),
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
