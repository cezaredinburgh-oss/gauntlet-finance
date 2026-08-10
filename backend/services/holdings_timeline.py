"""Statement-native holdings qty as-of each date (for historical portfolio MV).

Rebuilds share quantities from InvestmentEvents so charts mark the book you
actually held, not today's open lots × past prices.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable, Sequence

from backend.engines.lots import LotEngine
from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
)

# Ignore residual dust after sells/splits
_QTY_EPS = Decimal("0.00000001")


def _event_sort_key(e: InvestmentEvent) -> tuple:
    """Match LotEngine chronological order."""
    dt = e.event_datetime
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    else:
        dt = datetime(
            e.event_date.year,
            e.event_date.month,
            e.event_date.day,
            tzinfo=timezone.utc,
        )
    return (dt, e.event_date, str(e.id))


def _clamp_qty(q: Decimal) -> Decimal:
    if q < 0 and abs(q) < _QTY_EPS * 10:
        return Decimal("0")
    if q < 0:
        return Decimal("0")
    if q < _QTY_EPS:
        return Decimal("0")
    return q


@dataclass
class HoldingsTimeline:
    """Per-ticker step functions of (date → qty after events on that date)."""

    # ticker -> sorted (as_of_date, qty) points (last write wins same day)
    steps: dict[str, list[tuple[date, Decimal]]] = field(default_factory=dict)
    asset_class: dict[str, str | None] = field(default_factory=dict)

    def qty_as_of(self, ticker: str, as_of: date) -> Decimal:
        t = ticker.upper()
        pts = self.steps.get(t)
        if not pts:
            return Decimal("0")
        # Last point with date <= as_of
        lo, hi = 0, len(pts) - 1
        best: Decimal | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            d, q = pts[mid]
            if d <= as_of:
                best = q
                lo = mid + 1
            else:
                hi = mid - 1
        return best if best is not None else Decimal("0")

    def qty_map_as_of(self, as_of: date) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for t in self.steps:
            q = self.qty_as_of(t, as_of)
            if q > 0:
                out[t] = q
        return out

    def tickers(self) -> list[str]:
        return sorted(self.steps.keys())

    def tickers_for_asset_class(self, asset_class: AssetClass | str | None) -> list[str]:
        if asset_class is None:
            return self.tickers()
        want = (
            asset_class.value
            if isinstance(asset_class, AssetClass)
            else str(asset_class)
        )
        return sorted(
            t
            for t in self.steps
            if (self.asset_class.get(t) or "").lower() == want.lower()
        )


def build_holdings_timeline(
    events: Sequence[InvestmentEvent],
    lots: Sequence[InvestmentLot] = (),
) -> HoldingsTimeline:
    """
    Replay Buy/Sell/StakingReward/Split and inventory-exit Transfers.

    LotAllocation is ignored (child of Sell). Legal-entity transfers that do
    not exit inventory are ignored (same heuristic as LotEngine).

    Fallback: open lots for tickers with no events contribute
    ``quantity_remaining`` from ``acquisition_date`` (when event history missing).
    """
    running: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    steps: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    ac_map: dict[str, str | None] = {}
    tickers_with_events: set[str] = set()

    ordered = sorted(
        (e for e in events if not e.archived),
        key=_event_sort_key,
    )

    for e in ordered:
        if not e.ticker:
            continue
        t = e.ticker.upper()
        if e.asset_class is not None:
            ac_map[t] = e.asset_class.value
        et = e.event_type

        if et == InvestmentEventType.LOT_ALLOCATION:
            continue
        if et in (
            InvestmentEventType.FEE,
            InvestmentEventType.DEPOSIT,
            InvestmentEventType.WITHDRAWAL,
        ):
            continue

        delta = Decimal("0")
        if et in (InvestmentEventType.BUY, InvestmentEventType.STAKING_REWARD):
            if e.quantity is None or e.quantity <= 0:
                continue
            delta = e.quantity
        elif et == InvestmentEventType.SELL:
            if e.quantity is None or e.quantity <= 0:
                continue
            delta = -e.quantity
        elif et == InvestmentEventType.SPLIT:
            # Revolut: signed share delta
            if e.quantity is None or e.quantity == 0:
                continue
            delta = e.quantity
        elif et == InvestmentEventType.TRANSFER:
            if not LotEngine._is_inventory_exit_transfer(e):
                continue
            if e.quantity is None or e.quantity <= 0:
                continue
            delta = -e.quantity
        else:
            continue

        tickers_with_events.add(t)
        new_q = _clamp_qty(running[t] + delta)
        running[t] = new_q
        # Collapse same-day updates: replace last point if same date
        pts = steps[t]
        if pts and pts[-1][0] == e.event_date:
            pts[-1] = (e.event_date, new_q)
        else:
            pts.append((e.event_date, new_q))

    # Fallback open lots when no events for that ticker
    for lot in lots:
        if lot.archived:
            continue
        t = lot.ticker.upper()
        if t in tickers_with_events:
            if lot.asset_class is not None and t not in ac_map:
                ac_map[t] = lot.asset_class.value
            continue
        if lot.status != LotStatus.OPEN or lot.quantity_remaining <= 0:
            if lot.asset_class is not None and t not in ac_map:
                ac_map[t] = lot.asset_class.value
            continue
        if lot.asset_class is not None:
            ac_map[t] = lot.asset_class.value
        q = _clamp_qty(lot.quantity_remaining)
        if q <= 0:
            continue
        # Single step from acquisition
        existing = steps.get(t)
        if existing:
            continue
        steps[t] = [(lot.acquisition_date, q)]
        running[t] = q

    # Ensure asset class from any lot
    for lot in lots:
        if lot.archived:
            continue
        t = lot.ticker.upper()
        if t not in ac_map and lot.asset_class is not None:
            ac_map[t] = lot.asset_class.value

    # Drop empty tickers
    clean = {t: pts for t, pts in steps.items() if pts}
    return HoldingsTimeline(steps=clean, asset_class=ac_map)
