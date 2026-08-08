"""Per-ticker verification digests: platform split, tax tranches, ROI, portfolio role."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.schema.models import (
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    Price,
)
from backend.services.fx_amounts import build_fx_service
from backend.services.lot_costs import enrich_lots, resolve_lot_costs
from backend.services.realized import realized_usd_by_ticker
from backend.sheets.repository import SheetsRepository


def _d(v: Decimal | None) -> Decimal:
    return v if v is not None else Decimal("0")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def _q4(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.0001"))


def _str_dec(v: Decimal, places: int = 2) -> str:
    if places == 4:
        return str(_q4(v))
    return str(_q2(v))


def roi_grade(unrealized_pct: float | None) -> tuple[str, str]:
    """Return (letter, label) from unrealized ROI %."""
    if unrealized_pct is None:
        return "—", "Unpriced"
    if unrealized_pct >= 50:
        return "A", "Excellent"
    if unrealized_pct >= 20:
        return "B", "Strong"
    if unrealized_pct >= 0:
        return "C", "Steady"
    if unrealized_pct >= -20:
        return "D", "Soft"
    return "F", "Underwater"


def _tax_bucket_key(free_on: date, as_of: date) -> str:
    this_year = as_of.year
    if free_on <= as_of:
        return "now"
    if free_on.year == this_year:
        return "later_this_year"
    if free_on.year == this_year + 1:
        return "next_year"
    return "year_after"


def _bucket_labels(as_of: date) -> list[tuple[str, str]]:
    y = as_of.year
    return [
        ("now", "Tax-free now"),
        ("later_this_year", f"Later in {y}"),
        ("next_year", f"Unlocks {y + 1}"),
        ("year_after", f"Unlocks {y + 2}+"),
    ]


def build_ticker_digests(
    repo: SheetsRepository,
    *,
    as_of: date | None = None,
    exemption_days: int = 1095,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    raw_lots = [r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)]
    fx = build_fx_service(repo)
    needs_fx = any(
        (lot.native_currency or "").upper() != "USD"
        and lot.cost_basis_native > 0
        and (lot.cost_basis_usd or 0) == 0
        for lot in raw_lots
        if not lot.archived
    )
    lots = enrich_lots(
        raw_lots,
        fx,
        repo=repo,
        persist=needs_fx,
        fetch_missing_rates=needs_fx,
    )
    events = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]
    prices = {
        p.ticker.upper(): p
        for p in repo.list_rows("Prices")
        if isinstance(p, Price) and not p.archived
    }

    open_lots = [
        lot
        for lot in lots
        if lot.status == LotStatus.OPEN
        and lot.quantity_remaining > 0
        and not lot.archived
    ]

    # Realized lifetime by ticker (dedupe ghost double-written allocations)
    realized_by_ticker = realized_usd_by_ticker(events)

    # Group lots by ticker
    by_ticker: dict[str, list[InvestmentLot]] = defaultdict(list)
    for lot in open_lots:
        by_ticker[lot.ticker.upper()].append(lot)

    labels = _bucket_labels(as_of)
    digests: list[dict[str, Any]] = []
    prices_as_of: date | None = None

    total_cost = Decimal("0")
    total_mv = Decimal("0")
    has_any_price = False

    # First pass: build per-ticker stats without portfolio-relative fields
    raw_rows: list[dict[str, Any]] = []

    for ticker in sorted(by_ticker.keys()):
        t_lots = by_ticker[ticker]
        px = prices.get(ticker)
        price_val: Decimal | None = None
        price_as_of: date | None = None
        if px is not None:
            has_any_price = True
            price_val = px.price
            raw = px.as_of.date() if hasattr(px.as_of, "date") else px.as_of
            price_as_of = raw  # type: ignore[assignment]
            if prices_as_of is None or (price_as_of and price_as_of > prices_as_of):
                prices_as_of = price_as_of

        qty_total = Decimal("0")
        cost_total = Decimal("0")
        platform: dict[str, dict[str, Any]] = {}
        tranche_qty: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        tranche_mv: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        first_acq: date | None = None
        last_acq: date | None = None
        next_unlock: date | None = None
        next_unlock_qty = Decimal("0")

        for lot in t_lots:
            qty = lot.quantity_remaining
            if qty <= 0:
                continue
            qty_total += qty
            _, _, lot_usd = resolve_lot_costs(lot, fx)
            if lot_usd <= 0:
                lot_usd = _d(lot.cost_basis_usd)
            cost_total += lot_usd

            src = (lot.source or "Unknown").strip() or "Unknown"
            if src not in platform:
                platform[src] = {
                    "source": src,
                    "quantity": Decimal("0"),
                    "cost_basis_usd": Decimal("0"),
                    "market_value_usd": Decimal("0"),
                    "lot_count": 0,
                }
            platform[src]["quantity"] += qty
            platform[src]["cost_basis_usd"] += lot_usd
            platform[src]["lot_count"] += 1
            if price_val is not None:
                platform[src]["market_value_usd"] += qty * price_val
            else:
                platform[src]["market_value_usd"] += lot_usd

            free_on = lot.acquisition_date + timedelta(days=exemption_days)
            bkey = _tax_bucket_key(free_on, as_of)
            if price_val is not None:
                amt = qty * price_val
            else:
                amt = lot_usd
            tranche_qty[bkey] += qty
            tranche_mv[bkey] += amt

            if first_acq is None or lot.acquisition_date < first_acq:
                first_acq = lot.acquisition_date
            if last_acq is None or lot.acquisition_date > last_acq:
                last_acq = lot.acquisition_date

            if free_on > as_of:
                if next_unlock is None or free_on < next_unlock:
                    next_unlock = free_on
                    next_unlock_qty = qty
                elif free_on == next_unlock:
                    next_unlock_qty += qty

        mv: Decimal | None = None
        if price_val is not None:
            mv = _q2(qty_total * price_val)
            total_mv += mv
        else:
            # cost as stand-in so weight still works when mixed pricing
            total_mv += _q2(cost_total)

        total_cost += cost_total
        unrealized = (mv - cost_total) if mv is not None else None
        unrealized_pct: float | None = None
        if unrealized is not None and cost_total > 0:
            unrealized_pct = float((unrealized / cost_total) * 100)
        grade, grade_label = roi_grade(unrealized_pct)

        avg_cost = (cost_total / qty_total) if qty_total > 0 else Decimal("0")

        by_platform = [
            {
                "source": p["source"],
                "quantity": _str_dec(p["quantity"], 4),
                "cost_basis_usd": _str_dec(p["cost_basis_usd"]),
                "market_value_usd": _str_dec(p["market_value_usd"]),
                "lot_count": p["lot_count"],
            }
            for p in sorted(platform.values(), key=lambda x: x["quantity"], reverse=True)
        ]

        tax_tranches = []
        for key, label in labels:
            tax_tranches.append(
                {
                    "key": key,
                    "label": label,
                    "quantity": _str_dec(tranche_qty.get(key, Decimal("0")), 4),
                    "market_value_usd": _str_dec(tranche_mv.get(key, Decimal("0"))),
                }
            )

        raw_rows.append(
            {
                "ticker": ticker,
                "quantity_total": qty_total,
                "cost_basis_usd": cost_total,
                "market_value_usd": mv,
                "unrealized_usd": unrealized,
                "unrealized_pct": unrealized_pct,
                "avg_cost_usd": avg_cost,
                "price_val": price_val,
                "price_as_of": price_as_of,
                "grade": grade,
                "grade_label": grade_label,
                "by_platform": by_platform,
                "multi_platform": len(by_platform) >= 2,
                "tax_tranches": tax_tranches,
                "next_unlock": next_unlock,
                "next_unlock_qty": next_unlock_qty,
                "first_acq": first_acq,
                "last_acq": last_acq,
                "open_lot_count": len(t_lots),
                "realized": realized_by_ticker.get(ticker, Decimal("0")),
                "missing_price": price_val is None,
            }
        )

    portfolio_unrealized = (
        _q2(total_mv - total_cost) if has_any_price or total_cost > 0 else None
    )
    # Prefer true MV-based unrealized when we have prices; total_mv includes cost fallbacks
    true_mv_sum = sum(
        (r["market_value_usd"] for r in raw_rows if r["market_value_usd"] is not None),
        Decimal("0"),
    )
    true_cost_with_price = sum(
        (r["cost_basis_usd"] for r in raw_rows if r["market_value_usd"] is not None),
        Decimal("0"),
    )
    if true_mv_sum > 0:
        portfolio_unrealized = _q2(true_mv_sum - true_cost_with_price)
        portfolio_mv_for_weight = true_mv_sum
        # For weight of unpriced: use cost share of (true_mv + unpriced costs)
        unpriced_cost = sum(
            (r["cost_basis_usd"] for r in raw_rows if r["market_value_usd"] is None),
            Decimal("0"),
        )
        weight_denom = true_mv_sum + unpriced_cost
    else:
        portfolio_mv_for_weight = total_cost
        weight_denom = total_cost if total_cost > 0 else Decimal("1")

    portfolio_unrealized_pct = None
    if portfolio_unrealized is not None and total_cost > 0:
        portfolio_unrealized_pct = float((portfolio_unrealized / total_cost) * 100)

    for r in raw_rows:
        t_cost = r["cost_basis_usd"]
        t_mv = r["market_value_usd"] if r["market_value_usd"] is not None else t_cost
        t_unreal = r["unrealized_usd"]

        weight = float((t_mv / weight_denom) * 100) if weight_denom > 0 else 0.0
        growth_pp = float((t_unreal / total_cost) * 100) if (
            t_unreal is not None and total_cost > 0
        ) else None
        unreal_share = None
        if (
            t_unreal is not None
            and portfolio_unrealized is not None
            and portfolio_unrealized != 0
        ):
            unreal_share = float((t_unreal / portfolio_unrealized) * 100)

        digests.append(
            {
                "ticker": r["ticker"],
                "quantity_total": _str_dec(r["quantity_total"], 4),
                "by_platform": r["by_platform"],
                "multi_platform": r["multi_platform"],
                "price_usd": _str_dec(r["price_val"]) if r["price_val"] is not None else None,
                "price_as_of": r["price_as_of"].isoformat() if r["price_as_of"] else None,
                "cost_basis_usd": _str_dec(t_cost),
                "avg_cost_usd": _str_dec(r["avg_cost_usd"], 4),
                "market_value_usd": _str_dec(r["market_value_usd"])
                if r["market_value_usd"] is not None
                else None,
                "unrealized_usd": _str_dec(t_unreal) if t_unreal is not None else None,
                "unrealized_pct": round(r["unrealized_pct"], 2)
                if r["unrealized_pct"] is not None
                else None,
                "roi_grade": r["grade"],
                "roi_grade_label": r["grade_label"],
                "portfolio_weight_pct": round(weight, 2),
                "unrealized_share_pct": round(unreal_share, 2)
                if unreal_share is not None
                else None,
                "growth_contribution_pp": round(growth_pp, 2)
                if growth_pp is not None
                else None,
                "tax_tranches": r["tax_tranches"],
                "next_unlock_date": r["next_unlock"].isoformat()
                if r["next_unlock"]
                else None,
                "next_unlock_quantity": _str_dec(r["next_unlock_qty"], 4)
                if r["next_unlock"]
                else None,
                "realized_lifetime_usd": _str_dec(r["realized"]),
                "first_acquired": r["first_acq"].isoformat() if r["first_acq"] else None,
                "last_acquired": r["last_acq"].isoformat() if r["last_acq"] else None,
                "open_lot_count": r["open_lot_count"],
                "missing_price": r["missing_price"],
            }
        )

    # Sort by market value (priced) then cost
    def _sort_key(d: dict[str, Any]) -> tuple:
        mv = Decimal(d["market_value_usd"]) if d["market_value_usd"] else Decimal("0")
        cost = Decimal(d["cost_basis_usd"])
        return (-mv, -cost, d["ticker"])

    digests.sort(key=_sort_key)

    return {
        "as_of": as_of.isoformat(),
        "prices_as_of": prices_as_of.isoformat() if prices_as_of else None,
        "portfolio": {
            "total_cost_basis_usd": _str_dec(total_cost),
            "total_market_value_usd": _str_dec(true_mv_sum) if true_mv_sum > 0 else (
                _str_dec(total_mv) if has_any_price else None
            ),
            "unrealized_usd": _str_dec(portfolio_unrealized)
            if portfolio_unrealized is not None
            else None,
            "unrealized_pct": round(portfolio_unrealized_pct, 2)
            if portfolio_unrealized_pct is not None
            else None,
        },
        "tickers": digests,
    }
