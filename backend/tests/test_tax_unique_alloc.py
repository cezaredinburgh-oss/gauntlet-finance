"""Tax report: ghost LotAllocation dedupe + transfer_out exclusion."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from backend.schema.models import InvestmentEvent, InvestmentEventType
from backend.services.tax_report import (
    _allocation_years,
    _is_taxable_disposal_allocation,
    build_tax_report,
    summary_by_year,
)
from backend.sheets.repository import InMemorySheetsRepository

TS = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _alloc(
    *,
    year: int = 2024,
    parent_id=None,
    qty: str = "1",
    gain_czk: str = "1000",
    gain_usd: str = "50",
    ticker: str = "PLTR",
    notes: str | None = None,
    exempt: bool = False,
    updated_at: datetime | None = None,
) -> InvestmentEvent:
    return InvestmentEvent(
        id=uuid4(),
        account_id=uuid4(),
        event_type=InvestmentEventType.LOT_ALLOCATION,
        event_date=date(year, 6, 15),
        ticker=ticker,
        quantity=Decimal(qty),
        value_native=Decimal("200"),
        value_usd=Decimal("200"),
        value_czk=Decimal("4500"),
        realized_gain_czk=Decimal(gain_czk),
        realized_gain_usd=Decimal(gain_usd),
        qualifies_3y_exemption=exempt,
        holding_period_days=1200 if exempt else 100,
        parent_event_id=parent_id or uuid4(),
        lot_id=uuid4(),
        source="test",
        notes=notes,
        created_at=TS,
        updated_at=updated_at or TS,
    )


def test_ghost_duplicate_allocations_counted_once():
    """C5: two LotAllocation same parent/qty/gain → disposal_count 1, gains not doubled."""
    parent = uuid4()
    a = _alloc(parent_id=parent, qty="10", gain_czk="500", gain_usd="25")
    b = _alloc(
        parent_id=parent,
        qty="10",
        gain_czk="500",
        gain_usd="25",
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    repo = InMemorySheetsRepository()
    repo.upsert_rows("InvestmentEvents", [a, b])

    report = build_tax_report(repo, year=2024)
    assert report["summary"]["disposal_count"] == 1
    assert report["summary"]["total_realized_gain_czk"] == "500"
    assert report["summary"]["total_realized_gain_usd"] == "25"

    by_year = summary_by_year(repo)
    row_2024 = next(r for r in by_year["years"] if r["year"] == 2024)
    assert row_2024["disposal_count"] == 1
    assert row_2024["total_realized_gain_czk"] == "500"


def test_transfer_out_notes_excluded_from_tax_disposals():
    """M8: transfer-out allocations are not tax disposals."""
    sale = _alloc(year=2024, gain_czk="1000", gain_usd="40", notes=None)
    xfer = _alloc(
        year=2024,
        gain_czk="0",
        gain_usd="0",
        notes="transfer_out",
        qty="5",
    )
    # also case-insensitive
    xfer2 = _alloc(
        year=2024,
        gain_czk="999",
        gain_usd="99",
        notes="FIFO Transfer_Out partial",
        qty="2",
    )
    repo = InMemorySheetsRepository()
    repo.upsert_rows("InvestmentEvents", [sale, xfer, xfer2])

    report = build_tax_report(repo, year=2024)
    assert report["summary"]["disposal_count"] == 1
    assert report["summary"]["total_realized_gain_czk"] == "1000"
    assert report["summary"]["total_realized_gain_usd"] == "40"
    assert all(
        "transfer_out" not in (d.get("notes") or "").lower()
        for d in report["disposals"]
    )

    years = _allocation_years([sale, xfer, xfer2])
    assert 2024 in years  # sale still contributes

    assert _is_taxable_disposal_allocation(sale) is True
    assert _is_taxable_disposal_allocation(xfer) is False
    assert _is_taxable_disposal_allocation(xfer2) is False


def test_transfer_out_year_only_does_not_list_year_without_sales():
    """Years list ignores transfer-only years (except current year via list_tax_years)."""
    xfer = _alloc(year=2019, notes="transfer_out", gain_czk="0", gain_usd="0")
    years = _allocation_years([xfer])
    assert 2019 not in years
