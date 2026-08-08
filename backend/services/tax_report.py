"""JSON tax report payload for a future PDF layer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from backend.engines.lots import LotEngine
from backend.schema.models import (
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
)
from backend.sheets.repository import SheetsRepository


def build_tax_report(
    repo: SheetsRepository,
    *,
    year: int | None = None,
    as_of: date | None = None,
    exemption_days: int = 1095,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    year = year or as_of.year

    lots = [r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)]
    events = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]

    engine = LotEngine(exemption_days=exemption_days)

    # Realized disposals in year (LotAllocation with gains)
    disposals: list[dict[str, Any]] = []
    exempt_disposals: list[dict[str, Any]] = []
    taxable_disposals: list[dict[str, Any]] = []

    total_gain_czk = Decimal("0")
    total_gain_usd = Decimal("0")
    exempt_gain_czk = Decimal("0")
    taxable_gain_czk = Decimal("0")

    for e in events:
        if e.event_type != InvestmentEventType.LOT_ALLOCATION:
            continue
        if e.event_date.year != year:
            continue
        if e.archived:
            continue
        row = {
            "id": str(e.id),
            "date": e.event_date.isoformat(),
            "ticker": e.ticker,
            "quantity": str(e.quantity) if e.quantity is not None else None,
            "value_native": str(e.value_native) if e.value_native is not None else None,
            "value_czk": str(e.value_czk) if e.value_czk is not None else None,
            "value_usd": str(e.value_usd) if e.value_usd is not None else None,
            "realized_gain_czk": str(e.realized_gain_czk)
            if e.realized_gain_czk is not None
            else None,
            "realized_gain_usd": str(e.realized_gain_usd)
            if e.realized_gain_usd is not None
            else None,
            "holding_period_days": e.holding_period_days,
            "qualifies_3y_exemption": e.qualifies_3y_exemption,
            "lot_id": str(e.lot_id) if e.lot_id else None,
            "parent_event_id": str(e.parent_event_id) if e.parent_event_id else None,
            "source": e.source,
            "notes": e.notes,
        }
        disposals.append(row)
        g_czk = e.realized_gain_czk or Decimal("0")
        g_usd = e.realized_gain_usd or Decimal("0")
        total_gain_czk += g_czk
        total_gain_usd += g_usd
        if e.qualifies_3y_exemption:
            exempt_disposals.append(row)
            exempt_gain_czk += g_czk
        else:
            taxable_disposals.append(row)
            taxable_gain_czk += g_czk

    # Open positions eligibility snapshot
    open_lots = [
        lot
        for lot in lots
        if lot.status == LotStatus.OPEN
        and lot.quantity_remaining > 0
        and not lot.archived
    ]
    tickers = sorted({lot.ticker.upper() for lot in open_lots})
    open_summaries = []
    for t in tickers:
        s = engine.summarize_ticker(lots, t, as_of=as_of, exemption_days=exemption_days)
        open_summaries.append(
            {
                "ticker": s.ticker,
                "total_quantity": str(s.total_quantity),
                "quantity_tax_free": str(s.quantity_tax_free),
                "quantity_pending": str(s.quantity_pending),
                "cost_basis_native": str(s.cost_basis_native),
                "cost_basis_czk": str(s.cost_basis_czk),
                "cost_basis_usd": str(s.cost_basis_usd),
                "native_currency": s.native_currency,
                "lots": [
                    {
                        "lot_id": str(l.lot_id),
                        "quantity_remaining": str(l.quantity_remaining),
                        "acquisition_date": l.acquisition_date.isoformat(),
                        "tax_free_on": l.tax_free_on.isoformat(),
                        "holding_period_days": l.holding_period_days,
                        "qualifies_3y_exemption": l.qualifies_3y_exemption,
                        "cost_basis_czk": str(l.cost_basis_czk),
                        "cost_basis_usd": str(l.cost_basis_usd),
                    }
                    for l in s.lots
                ],
            }
        )

    return {
        "meta": {
            "tax_year": year,
            "as_of": as_of.isoformat(),
            "exemption_days": exemption_days,
            "currency_primary_reporting": "CZK",
            "notes": (
                "JSON payload for PDF layer. Crypto exemption eligibility is "
                "stored mathematically; legal treatment may differ — verify with advisor."
            ),
        },
        "summary": {
            "disposal_count": len(disposals),
            "exempt_disposal_count": len(exempt_disposals),
            "taxable_disposal_count": len(taxable_disposals),
            "total_realized_gain_czk": str(total_gain_czk),
            "total_realized_gain_usd": str(total_gain_usd),
            "exempt_realized_gain_czk": str(exempt_gain_czk),
            "taxable_realized_gain_czk": str(taxable_gain_czk),
        },
        "disposals": disposals,
        "exempt_disposals": exempt_disposals,
        "taxable_disposals": taxable_disposals,
        "open_positions": open_summaries,
    }


def _allocation_years(events: list[InvestmentEvent]) -> list[int]:
    years = {
        e.event_date.year
        for e in events
        if not e.archived
        and e.event_type == InvestmentEventType.LOT_ALLOCATION
        and e.event_date is not None
    }
    return sorted(years)


def list_tax_years(repo: SheetsRepository) -> dict[str, Any]:
    """Years that have lot-allocation disposals, plus current calendar year."""
    events = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]
    years = _allocation_years(events)
    today_y = date.today().year
    if today_y not in years:
        years = sorted(set(years) | {today_y})
    return {"years": years, "default_year": today_y}


def summary_by_year(
    repo: SheetsRepository,
    *,
    as_of: date | None = None,
    exemption_days: int = 1095,
) -> dict[str, Any]:
    """Aggregate realised gains per calendar year (LotAllocation only)."""
    del exemption_days  # reserved for future cost adjustments
    as_of = as_of or date.today()
    events = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]
    by: dict[int, dict[str, Decimal | int]] = {}
    for e in events:
        if e.archived or e.event_type != InvestmentEventType.LOT_ALLOCATION:
            continue
        y = e.event_date.year
        bucket = by.setdefault(
            y,
            {
                "disposal_count": 0,
                "exempt_count": 0,
                "taxable_count": 0,
                "total_gain_czk": Decimal("0"),
                "total_gain_usd": Decimal("0"),
                "exempt_gain_czk": Decimal("0"),
                "taxable_gain_czk": Decimal("0"),
            },
        )
        g_czk = e.realized_gain_czk or Decimal("0")
        g_usd = e.realized_gain_usd or Decimal("0")
        bucket["disposal_count"] = int(bucket["disposal_count"]) + 1
        bucket["total_gain_czk"] = Decimal(str(bucket["total_gain_czk"])) + g_czk
        bucket["total_gain_usd"] = Decimal(str(bucket["total_gain_usd"])) + g_usd
        if e.qualifies_3y_exemption:
            bucket["exempt_count"] = int(bucket["exempt_count"]) + 1
            bucket["exempt_gain_czk"] = Decimal(str(bucket["exempt_gain_czk"])) + g_czk
        else:
            bucket["taxable_count"] = int(bucket["taxable_count"]) + 1
            bucket["taxable_gain_czk"] = Decimal(str(bucket["taxable_gain_czk"])) + g_czk

    years_out = []
    for y in sorted(by.keys()):
        b = by[y]
        years_out.append(
            {
                "year": y,
                "disposal_count": int(b["disposal_count"]),
                "exempt_count": int(b["exempt_count"]),
                "taxable_count": int(b["taxable_count"]),
                "total_realized_gain_czk": str(b["total_gain_czk"]),
                "total_realized_gain_usd": str(b["total_gain_usd"]),
                "exempt_realized_gain_czk": str(b["exempt_gain_czk"]),
                "taxable_realized_gain_czk": str(b["taxable_gain_czk"]),
            }
        )
    return {"as_of": as_of.isoformat(), "years": years_out}


def disposals_csv(rows: list[dict[str, Any]]) -> str:
    """Minimal CSV for tax disposal tables."""
    headers = [
        "date",
        "ticker",
        "quantity",
        "value_czk",
        "value_usd",
        "realized_gain_czk",
        "realized_gain_usd",
        "holding_period_days",
        "qualifies_3y_exemption",
        "source",
    ]
    lines = [",".join(headers)]
    for r in rows:
        cells = []
        for h in headers:
            v = r.get(h)
            s = "" if v is None else str(v)
            if any(c in s for c in (",", '"', "\n")):
                s = '"' + s.replace('"', '""') + '"'
            cells.append(s)
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"
