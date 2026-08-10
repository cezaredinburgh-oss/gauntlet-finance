"""Realized P&L helpers (FIFO LotAllocation-based)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable

from backend.schema.models import InvestmentEvent, InvestmentEventType


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


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


def allocation_proceeds_cost_gain(
    e: InvestmentEvent,
) -> tuple[Decimal, Decimal, Decimal] | None:
    """
    Recover (proceeds_usd, cost_usd, gain_usd) for one LotAllocation.

    FIFO writes value_usd = net proceeds and realized_gain_usd = proceeds − cost,
    so cost = proceeds − gain when both legs exist. Incomplete rows return None
    (do not invent cost).
    """
    if e.realized_gain_usd is None or e.value_usd is None:
        return None
    proceeds = e.value_usd
    gain = e.realized_gain_usd
    cost = proceeds - gain
    return proceeds, cost, gain


# Min cost-weighted hold before quoting CAGR on realized sells
MIN_ANNUALIZE_DAYS = 90


def _empty_economics() -> dict[str, Any]:
    return {
        "gain_usd": Decimal("0"),
        "proceeds_usd": Decimal("0"),
        "cost_basis_usd": Decimal("0"),
        "roi_pct": None,
        "holding_years": None,
        "annualized_roi_pct": None,
        "complete_rows": 0,
        "gain_only_rows": 0,
    }


def annualized_realized_roi_pct(
    total_return_ratio: float,
    holding_years: float | None,
    *,
    min_days: int = MIN_ANNUALIZE_DAYS,
) -> float | None:
    """CAGR from cost→proceeds: ``(1+R)^(1/t) - 1`` as percent."""
    if holding_years is None or holding_years <= 0:
        return None
    if holding_years * 365.25 < min_days:
        return None
    if total_return_ratio <= -1.0:
        return None
    try:
        ann = (1.0 + total_return_ratio) ** (1.0 / holding_years) - 1.0
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    return round(ann * 100.0, 2)


def _finalize_economics(
    gain: Decimal,
    proceeds: Decimal,
    cost: Decimal,
    *,
    complete_rows: int = 0,
    gain_only_rows: int = 0,
    weighted_hold_days: Decimal | None = None,
    hold_cost_weight: Decimal | None = None,
) -> dict[str, Any]:
    roi: float | None = None
    if cost > 0:
        roi = round(float((gain / cost) * 100), 2)
    holding_years: float | None = None
    annualized: float | None = None
    if (
        hold_cost_weight is not None
        and hold_cost_weight > 0
        and weighted_hold_days is not None
    ):
        avg_days = float(weighted_hold_days / hold_cost_weight)
        holding_years = avg_days / 365.25
        if cost > 0:
            annualized = annualized_realized_roi_pct(
                float(gain / cost), holding_years
            )
    return {
        "gain_usd": _q2(gain),
        "proceeds_usd": _q2(proceeds),
        "cost_basis_usd": _q2(cost),
        "roi_pct": roi,
        "holding_years": round(holding_years, 3) if holding_years is not None else None,
        "annualized_roi_pct": annualized,
        "complete_rows": complete_rows,
        "gain_only_rows": gain_only_rows,
    }


def sum_realized_economics(events: Iterable[InvestmentEvent]) -> dict[str, Any]:
    """
    Lifetime FIFO economics from unique LotAllocations.

    - gain_usd: all rows with realized_gain_usd (matches sum_realized_usd)
    - proceeds/cost: only rows with both value_usd and gain (no fake cost)
    - roi_pct: gain / cost when cost > 0 (uses full gain over known cost)
    - holding_years: cost-weighted average hold from allocation holding_period_days
    - annualized_roi_pct: CAGR over that weighted hold (min 90d)
    """
    gain = Decimal("0")
    proceeds = Decimal("0")
    cost = Decimal("0")
    complete = 0
    gain_only = 0
    weighted_days = Decimal("0")
    hold_weight = Decimal("0")
    for e in iter_unique_allocations(events):
        if e.realized_gain_usd is None:
            continue
        gain += e.realized_gain_usd
        legs = allocation_proceeds_cost_gain(e)
        if legs is None:
            gain_only += 1
            continue
        p, c, _g = legs
        proceeds += p
        cost += c
        complete += 1
        if c > 0 and e.holding_period_days is not None and e.holding_period_days >= 0:
            weighted_days += c * Decimal(e.holding_period_days)
            hold_weight += c
    return _finalize_economics(
        gain,
        proceeds,
        cost,
        complete_rows=complete,
        gain_only_rows=gain_only,
        weighted_hold_days=weighted_days if hold_weight > 0 else None,
        hold_cost_weight=hold_weight if hold_weight > 0 else None,
    )


def realized_economics_by_ticker(
    events: Iterable[InvestmentEvent],
) -> dict[str, dict[str, Any]]:
    """Per-ticker lifetime FIFO economics (same shape as sum_realized_economics)."""
    gain_m: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    proc_m: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    cost_m: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    complete_m: dict[str, int] = defaultdict(int)
    gain_only_m: dict[str, int] = defaultdict(int)
    wdays_m: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    wcost_m: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for e in iter_unique_allocations(events):
        if e.realized_gain_usd is None:
            continue
        tk = (e.ticker or "").upper()
        if not tk:
            continue
        gain_m[tk] += e.realized_gain_usd
        legs = allocation_proceeds_cost_gain(e)
        if legs is None:
            gain_only_m[tk] += 1
            continue
        p, c, _g = legs
        proc_m[tk] += p
        cost_m[tk] += c
        complete_m[tk] += 1
        if c > 0 and e.holding_period_days is not None and e.holding_period_days >= 0:
            wdays_m[tk] += c * Decimal(e.holding_period_days)
            wcost_m[tk] += c

    out: dict[str, dict[str, Any]] = {}
    for tk in gain_m:
        hw = wcost_m[tk]
        out[tk] = _finalize_economics(
            gain_m[tk],
            proc_m[tk],
            cost_m[tk],
            complete_rows=complete_m[tk],
            gain_only_rows=gain_only_m[tk],
            weighted_hold_days=wdays_m[tk] if hw > 0 else None,
            hold_cost_weight=hw if hw > 0 else None,
        )
    return out


def sum_realized_usd(events: Iterable[InvestmentEvent]) -> Decimal:
    return sum_realized_economics(events)["gain_usd"]


def realized_usd_by_ticker(events: Iterable[InvestmentEvent]) -> dict[str, Decimal]:
    return {
        tk: eco["gain_usd"] for tk, eco in realized_economics_by_ticker(events).items()
    }
