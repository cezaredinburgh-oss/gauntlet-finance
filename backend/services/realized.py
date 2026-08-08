"""Realized P&L helpers (FIFO LotAllocation-based)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from backend.schema.models import InvestmentEvent, InvestmentEventType


def iter_unique_allocations(
    events: Iterable[InvestmentEvent],
) -> list[InvestmentEvent]:
    """
    Return LotAllocation events with ghost duplicates removed.

    Duplicates appear when rebuilds upserted new allocation UUIDs without
    deleting prior children of the same sell (same parent, qty, gain → 2×).
    Keep one row per (parent_event_id, quantity, realized_gain_usd, ticker).
    Prefer the newest ``updated_at`` / ``created_at`` when ties exist.
    """
    best: dict[tuple, InvestmentEvent] = {}
    for e in events:
        if e.archived:
            continue
        if e.event_type != InvestmentEventType.LOT_ALLOCATION:
            continue
        key = (
            str(e.parent_event_id) if e.parent_event_id else str(e.id),
            str(e.quantity),
            str(e.realized_gain_usd),
            (e.ticker or "").upper(),
        )
        prev = best.get(key)
        if prev is None:
            best[key] = e
            continue
        # Prefer later update
        prev_ts = prev.updated_at or prev.created_at
        cur_ts = e.updated_at or e.created_at
        if cur_ts and prev_ts and cur_ts >= prev_ts:
            best[key] = e
        elif not prev_ts:
            best[key] = e
    return list(best.values())


def sum_realized_usd(events: Iterable[InvestmentEvent]) -> Decimal:
    total = Decimal("0")
    for e in iter_unique_allocations(events):
        if e.realized_gain_usd is not None:
            total += e.realized_gain_usd
    return total


def realized_usd_by_ticker(events: Iterable[InvestmentEvent]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for e in iter_unique_allocations(events):
        if e.realized_gain_usd is None:
            continue
        tk = (e.ticker or "").upper()
        if not tk:
            continue
        out[tk] += e.realized_gain_usd
    return out
