"""Portfolio market value, unrealized/realized P&L, Czech tax-free runway."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.engines.lots import LotEngine
from backend.schema.models import (
    InvestmentEvent,
    InvestmentLot,
    LotStatus,
    Price,
)
from backend.services.fx_amounts import build_fx_service
from backend.services.lot_costs import enrich_lots, resolve_lot_costs
from backend.services.portfolio_health import (
    HoldingRow,
    LotRow,
    RealizedRow,
    compute_portfolio_health,
    price_status_from_snapshot,
)
from backend.services.realized import iter_unique_allocations, sum_realized_economics
from backend.services.statement_extras import compute_statement_extras
from backend.sheets.repository import SheetsRepository


def _d(v: Decimal | None) -> Decimal:
    return v if v is not None else Decimal("0")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def portfolio_snapshot(
    repo: SheetsRepository,
    *,
    as_of: date | None = None,
    exemption_days: int = 1095,
    top_n: int = 8,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    raw_lots = [r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)]
    # Ensure CZK/PLN/etc lots contribute real USD cost (not placeholder zeros)
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

    engine = LotEngine(exemption_days=exemption_days, fx=fx)
    open_lots = [
        lot
        for lot in lots
        if lot.status == LotStatus.OPEN
        and lot.quantity_remaining > 0
        and not lot.archived
    ]
    tickers = sorted({lot.ticker.upper() for lot in open_lots})

    total_cost = Decimal("0")
    total_cost_czk = Decimal("0")
    total_mv: Decimal | None = Decimal("0") if prices else None
    has_any_price = False
    tax_free_now_mv = Decimal("0")
    tax_free_now_cost = Decimal("0")
    positions: list[dict[str, Any]] = []
    missing_quotes: list[str] = []
    prices_as_of: date | None = None

    # Per-lot contribution to tax runway buckets (by market value, fallback cost)
    # bucket key -> ticker -> {qty, amount}
    bucket_ticker: dict[str, dict[str, dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: {"qty": Decimal("0"), "amount": Decimal("0")})
    )
    bucket_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    this_year = as_of.year
    bucket_defs = [
        ("now", "Tax-free now"),
        ("later_this_year", f"Later in {this_year}"),
        ("next_year", f"Unlocks {this_year + 1}"),
        ("year_after", f"Unlocks {this_year + 2}+"),
    ]

    for t in tickers:
        s = engine.summarize_ticker(lots, t, as_of=as_of)
        px = prices.get(t)
        mv: Decimal | None = None
        price_val: Decimal | None = None
        if px is not None:
            has_any_price = True
            price_val = px.price
            mv = _q2(s.total_quantity * px.price)
            if total_mv is not None:
                total_mv += mv
            if prices_as_of is None or (
                px.as_of.date() if hasattr(px.as_of, "date") else px.as_of
            ) > prices_as_of:
                raw = px.as_of.date() if hasattr(px.as_of, "date") else px.as_of
                prices_as_of = raw  # type: ignore[assignment]
        else:
            missing_quotes.append(t)

        total_cost += s.cost_basis_usd
        total_cost_czk += s.cost_basis_czk
        unrealized = (mv - s.cost_basis_usd) if mv is not None else None

        # tax-free now at position level
        if s.total_quantity > 0:
            unit_cost = s.cost_basis_usd / s.total_quantity
            unit_mv = (mv / s.total_quantity) if mv is not None else None
            tf_cost = _q2(s.quantity_tax_free * unit_cost)
            tf_mv = _q2(s.quantity_tax_free * unit_mv) if unit_mv is not None else None
            tax_free_now_cost += tf_cost
            if tf_mv is not None:
                tax_free_now_mv += tf_mv
            else:
                tax_free_now_mv += tf_cost

        positions.append(
            {
                "ticker": t,
                "quantity": str(s.total_quantity),
                "quantity_tax_free": str(s.quantity_tax_free),
                "quantity_pending": str(s.quantity_pending),
                "cost_basis_usd": str(s.cost_basis_usd),
                "cost_basis_czk": str(s.cost_basis_czk),
                "price": str(price_val) if price_val is not None else None,
                "market_value": str(mv) if mv is not None else None,
                "unrealized_usd": str(unrealized) if unrealized is not None else None,
            }
        )

        # Lot-level runway
        for lot in open_lots:
            if lot.ticker.upper() != t:
                continue
            free_on = lot.acquisition_date + timedelta(days=exemption_days)
            qty = lot.quantity_remaining
            if qty <= 0:
                continue
            # value for this lot
            if price_val is not None:
                amt = _q2(qty * price_val)
            else:
                # Market value preferred; fall back to resolved USD cost
                _, _, lot_usd = resolve_lot_costs(lot, fx)
                amt = lot_usd if lot_usd > 0 else _d(lot.cost_basis_usd)

            if free_on <= as_of:
                bkey = "now"
            elif free_on.year == this_year:
                bkey = "later_this_year"
            elif free_on.year == this_year + 1:
                bkey = "next_year"
            else:
                bkey = "year_after"

            bucket_ticker[bkey][t]["qty"] += qty
            bucket_ticker[bkey][t]["amount"] += amt
            bucket_totals[bkey] += amt

    if not has_any_price:
        total_mv = None
        tax_free_display = tax_free_now_cost
    else:
        tax_free_display = tax_free_now_mv

    locked = Decimal("0")
    for k in ("later_this_year", "next_year", "year_after"):
        locked += bucket_totals.get(k, Decimal("0"))

    unrealized_total = (
        _q2(total_mv - total_cost) if total_mv is not None else None
    )
    unrealized_pct = None
    if unrealized_total is not None and total_cost > 0:
        unrealized_pct = float((unrealized_total / total_cost) * 100)

    # Realized lifetime from LotAllocation events (dedupe ghost double-writes)
    realized_eco = sum_realized_economics(events)
    realized = realized_eco["gain_usd"]

    buckets = []
    for key, label in bucket_defs:
        tickers_break = [
            {
                "ticker": tk,
                "quantity": str(v["qty"]),
                "amount_usd": str(_q2(v["amount"])),
            }
            for tk, v in sorted(
                bucket_ticker[key].items(),
                key=lambda x: x[1]["amount"],
                reverse=True,
            )
        ]
        buckets.append(
            {
                "key": key,
                "label": label,
                "amount_usd": str(_q2(bucket_totals.get(key, Decimal("0")))),
                "tickers": tickers_break,
            }
        )

    positions.sort(key=lambda p: Decimal(p["cost_basis_usd"]), reverse=True)
    top_tickers = [
        {
            "ticker": p["ticker"],
            "cost_usd": p["cost_basis_usd"],
            "market_value_usd": p["market_value"],
        }
        for p in positions[:top_n]
    ]

    price_map = {
        t: p.price
        for t, p in prices.items()
        if p.price is not None and p.price > 0
    }
    extras = compute_statement_extras(events, price_map, as_of=as_of, fx=fx)

    # Asset class by ticker from open lots
    class_by_ticker: dict[str, str] = {}
    for lot in open_lots:
        tk = lot.ticker.upper()
        if tk not in class_by_ticker and lot.asset_class is not None:
            class_by_ticker[tk] = lot.asset_class.value

    holding_rows: list[HoldingRow] = []
    for p in positions:
        tk = p["ticker"].upper()
        cost = _d(Decimal(p["cost_basis_usd"]))
        mv_s = p.get("market_value")
        value = Decimal(mv_s) if mv_s is not None else cost
        cls = (class_by_ticker.get(tk) or "Other").lower()
        holding_rows.append(
            HoldingRow(
                ticker=tk,
                value=value,
                cost_basis_usd=cost,
                asset_class=cls,
                is_crypto=cls == "crypto",
            )
        )

    lot_rows: list[LotRow] = []
    for lot in open_lots:
        free_on = lot.acquisition_date + timedelta(days=exemption_days)
        tax_free = free_on <= as_of
        days_left = (free_on - as_of).days if not tax_free else 0
        _, _, lot_usd = resolve_lot_costs(lot, fx)
        lot_rows.append(
            LotRow(
                ticker=lot.ticker.upper(),
                cost_basis_usd=lot_usd if lot_usd > 0 else _d(lot.cost_basis_usd),
                tax_free=tax_free,
                days_until_tax_free=None if tax_free else max(0, days_left),
            )
        )

    realized_rows: list[RealizedRow] = []
    for e in iter_unique_allocations(events):
        realized_rows.append(
            RealizedRow(
                tax_free=bool(e.qualifies_3y_exemption),
                gain_usd=_d(e.realized_gain_usd),
            )
        )

    # Tax-free open basis ≈ cost of tax-free qty (position-level)
    tax_free_open_basis = tax_free_now_cost
    health = compute_portfolio_health(
        holding_rows,
        lot_rows,
        realized_rows,
        tax_free_open_basis=tax_free_open_basis,
        open_cost_basis=total_cost if total_cost > 0 else Decimal("1"),
    )

    price_status = price_status_from_snapshot(
        quote_count=len(prices),
        open_ticker_count=len(tickers),
        missing_quotes=missing_quotes,
        prices_as_of=prices_as_of,
        as_of=as_of,
    )

    return {
        "as_of": as_of.isoformat(),
        "ticker_count": len(tickers),
        "total_cost_basis_usd": str(_q2(total_cost)),
        "total_cost_basis_czk": str(_q2(total_cost_czk)),
        "total_market_value_usd": str(total_mv) if total_mv is not None else None,
        "unrealized_usd": str(unrealized_total) if unrealized_total is not None else None,
        "unrealized_pct": unrealized_pct,
        "realized_lifetime_usd": str(_q2(realized)),
        "realized_cost_basis_usd": str(_q2(realized_eco["cost_basis_usd"])),
        "realized_proceeds_usd": str(_q2(realized_eco["proceeds_usd"])),
        "realized_roi_pct": realized_eco["roi_pct"],
        "realized_holding_years": realized_eco.get("holding_years"),
        "realized_annualized_pct": realized_eco.get("annualized_roi_pct"),
        "tax_free_now_usd": str(_q2(tax_free_display)),
        "tax_runway": {
            "available_usd": str(_q2(bucket_totals.get("now", Decimal("0")))),
            "locked_usd": str(_q2(locked)),
            "buckets": buckets,
        },
        "prices_as_of": prices_as_of.isoformat() if prices_as_of else None,
        "quote_count": len(prices),
        "missing_quotes": missing_quotes,
        "price_status": price_status,
        "positions": positions,
        "top_tickers_by_cost": top_tickers,
        "health": health,
        "living_draw_12m": extras["living_draw_12m"],
        "fees": extras["fees"],
        "staking": extras["staking"],
        "cashflow_monthly": extras["cashflow_monthly"],
    }
