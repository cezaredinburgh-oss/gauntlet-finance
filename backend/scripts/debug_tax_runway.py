"""Diagnose tax-free runway vs expected market values."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.config import get_settings
from backend.schema.models import InvestmentLot, LotStatus, Price
from backend.services.portfolio_snapshot import portfolio_snapshot
from backend.sheets.google_sheets import (
    GoogleSheetsRepository,
    credentials_from_service_account,
)


def main() -> None:
    get_settings.cache_clear()
    s = get_settings()
    repo = GoogleSheetsRepository(
        s.spreadsheet_id,
        credentials_from_service_account(
            json_path=s.google_application_credentials or None,
            json_inline=s.google_service_account_json or None,
        ),
        ensure_tabs=False,
    )
    snap = portfolio_snapshot(repo, exemption_days=s.holding_period_exemption_days)
    print("=== SNAPSHOT ===")
    for k in [
        "total_cost_basis_usd",
        "total_market_value_usd",
        "unrealized_usd",
        "tax_free_now_usd",
        "ticker_count",
        "prices_as_of",
        "quote_count",
    ]:
        print(f"{k}: {snap.get(k)}")
    print("missing_quotes:", snap["missing_quotes"], "count", len(snap["missing_quotes"]))
    print(
        "tax_runway available",
        snap["tax_runway"]["available_usd"],
        "locked",
        snap["tax_runway"]["locked_usd"],
    )
    for b in snap["tax_runway"]["buckets"]:
        print(f"  bucket {b['key']}: ${b['amount_usd']} n={len(b['tickers'])}")
        for t in b["tickers"][:8]:
            print(f"    {t}")

    lots = [r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)]
    open_lots = [
        l
        for l in lots
        if l.status == LotStatus.OPEN and l.quantity_remaining > 0 and not l.archived
    ]
    prices = {
        p.ticker.upper(): p
        for p in repo.list_rows("Prices")
        if isinstance(p, Price) and not p.archived
    }
    print("\n=== OPEN LOTS", len(open_lots), "PRICES", len(prices), "===")
    print("price keys:", sorted(prices.keys()))
    print("lot tickers:", sorted({l.ticker.upper() for l in open_lots}))

    as_of = date.today()
    days = s.holding_period_exemption_days
    total_mv = Decimal(0)
    total_cost = Decimal(0)
    now_mv = Decimal(0)
    locked_mv = Decimal(0)
    now_cost = Decimal(0)
    locked_cost = Decimal(0)
    missing = 0
    priced = 0
    mismatches = []
    for lot in open_lots:
        t = lot.ticker.upper()
        px = prices.get(t)
        cost = lot.cost_basis_usd or Decimal(0)
        total_cost += cost
        free_on = lot.acquisition_date + timedelta(days=days)
        qualifies = free_on <= as_of
        if px:
            priced += 1
            mv = (lot.quantity_remaining * px.price).quantize(Decimal("0.01"))
            if px.currency and px.currency.upper() != "USD":
                mismatches.append((t, px.currency, px.price))
        else:
            missing += 1
            mv = cost
        total_mv += mv
        if qualifies:
            now_mv += mv
            now_cost += cost
        else:
            locked_mv += mv
            locked_cost += cost

    print(f"\nrecompute: total_cost={total_cost} total_mv={total_mv}")
    print(f"priced_lots={priced} unpriced={missing}")
    print(f"now_mv={now_mv} locked_mv={locked_mv} sum={now_mv + locked_mv}")
    print(f"now_cost={now_cost} locked_cost={locked_cost}")
    if mismatches:
        print("non-USD prices:", mismatches[:20])

    by_year_cost: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
    by_year_mv: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
    for lot in open_lots:
        t = lot.ticker.upper()
        px = prices.get(t)
        cost = lot.cost_basis_usd or Decimal(0)
        mv = (lot.quantity_remaining * px.price).quantize(Decimal("0.01")) if px else cost
        by_year_cost[lot.acquisition_date.year] += cost
        by_year_mv[lot.acquisition_date.year] += mv
    print("cost by acq year:", {k: str(v) for k, v in sorted(by_year_cost.items())})
    print("mv by acq year:", {k: str(v) for k, v in sorted(by_year_mv.items())})

    # Top positions by MV
    pos = []
    for t in sorted({l.ticker.upper() for l in open_lots}):
        q = sum((l.quantity_remaining for l in open_lots if l.ticker.upper() == t), Decimal(0))
        c = sum((l.cost_basis_usd for l in open_lots if l.ticker.upper() == t), Decimal(0))
        px = prices.get(t)
        mv = (q * px.price).quantize(Decimal("0.01")) if px else None
        pos.append((t, q, c, mv, px.price if px else None))
    pos.sort(key=lambda x: x[3] or x[2], reverse=True)
    print("\nTop positions (ticker, qty, cost, mv, price):")
    for row in pos[:15]:
        print(" ", row)


if __name__ == "__main__":
    main()
