"""
Ticker-scoped FIFO lot rebuild for the import path.

Rebuilds InvestmentLots for selected tickers from all non-allocation
InvestmentEvents (existing + new), starting from empty lots. Other tickers'
lots are left unchanged. Callers must drop old lots/LotAllocations for the
touched tickers before/when persisting the result.

No dependency on backend.scripts.*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from backend.engines.lots import FifoResult, LotEngine
from backend.schema.models import (
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
)


def _ticker_key(ticker: str | None) -> str:
    return (ticker or "").strip().upper()


@dataclass
class TickerRebuildPlan:
    """Result of a ticker-scoped FIFO rebuild ready for persistence."""

    # Lots for non-touched tickers + freshly rebuilt lots for touched tickers
    lots: list[InvestmentLot] = field(default_factory=list)
    # Non-allocation events (with lot_id links) + new LotAllocation children
    events: list[InvestmentEvent] = field(default_factory=list)
    # Prior LotAllocation ids for touched tickers (caller should delete)
    stale_allocation_ids: list[UUID] = field(default_factory=list)
    # Prior lot ids for touched tickers (caller should delete)
    stale_lot_ids: list[UUID] = field(default_factory=list)
    allocations_created: int = 0
    touched_tickers: frozenset[str] = field(default_factory=frozenset)

    @property
    def fifo(self) -> FifoResult:
        return FifoResult(
            lots=self.lots,
            events=self.events,
            allocations_created=self.allocations_created,
        )


def collect_tickers(events: list[InvestmentEvent]) -> set[str]:
    """Uppercase tickers from non-allocation, non-archived events."""
    out: set[str] = set()
    for e in events:
        if e.archived:
            continue
        if e.event_type == InvestmentEventType.LOT_ALLOCATION:
            continue
        t = _ticker_key(e.ticker)
        if t:
            out.add(t)
    return out


def rebuild_lots_for_tickers(
    *,
    existing_lots: list[InvestmentLot],
    existing_events: list[InvestmentEvent],
    new_events: list[InvestmentEvent],
    touched_tickers: set[str],
    engine: LotEngine,
    now: datetime | None = None,
) -> TickerRebuildPlan:
    """
    Rebuild lots for ``touched_tickers`` from all non-allocation events
    (repo + new, deduped by id), from empty lots for those tickers.

    - Clears ``lot_id`` on inputs so FIFO opens lots purely from buys.
    - Drops existing LotAllocation rows for touched tickers from consideration
      (ids returned in ``stale_allocation_ids`` for the caller to delete).
    - Lots for other tickers are preserved in ``lots``.
    """
    touched = {_ticker_key(t) for t in touched_tickers if t and _ticker_key(t)}
    if not touched:
        return TickerRebuildPlan(
            lots=list(existing_lots),
            events=[],
            stale_allocation_ids=[],
            stale_lot_ids=[],
            allocations_created=0,
            touched_tickers=frozenset(),
        )

    by_id: dict[UUID, InvestmentEvent] = {}
    for e in existing_events + new_events:
        if e.archived:
            continue
        if e.event_type == InvestmentEventType.LOT_ALLOCATION:
            continue
        if _ticker_key(e.ticker) not in touched:
            continue
        by_id[e.id] = e

    cleaned = [e.model_copy(update={"lot_id": None}) for e in by_id.values()]
    fifo = engine.apply_events([], cleaned, now=now)

    other_lots = [
        lot for lot in existing_lots if _ticker_key(lot.ticker) not in touched
    ]
    stale_lot_ids = [
        lot.id for lot in existing_lots if _ticker_key(lot.ticker) in touched
    ]
    stale_allocation_ids = [
        e.id
        for e in existing_events
        if not e.archived
        and e.event_type == InvestmentEventType.LOT_ALLOCATION
        and _ticker_key(e.ticker) in touched
    ]

    return TickerRebuildPlan(
        lots=other_lots + list(fifo.lots),
        events=list(fifo.events),
        stale_allocation_ids=stale_allocation_ids,
        stale_lot_ids=stale_lot_ids,
        allocations_created=fifo.allocations_created,
        touched_tickers=frozenset(touched),
    )


def should_rebuild_tickers(
    *,
    touched_tickers: set[str],
    existing_lots: list[InvestmentLot],
    existing_events: list[InvestmentEvent],
    force: bool = False,
) -> bool:
    """
    True when touched tickers already have lots or non-allocation events
    in the ledger (incremental import or ERROR retry), or when ``force``.
    """
    if force:
        return True
    touched = {_ticker_key(t) for t in touched_tickers if t}
    if not touched:
        return False
    for lot in existing_lots:
        if _ticker_key(lot.ticker) in touched:
            return True
    for e in existing_events:
        if e.archived:
            continue
        if e.event_type == InvestmentEventType.LOT_ALLOCATION:
            continue
        if _ticker_key(e.ticker) in touched:
            return True
    return False
