"""Year-end ZIP export pack (tax + spend + import audit)."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from backend.schema.models import Category, StatementFile, Transaction
from backend.services.fx_amounts import build_fx_service, tx_signed_usd
from backend.services.tax_report import build_tax_report, disposals_csv, summary_by_year
from backend.sheets.repository import SheetsRepository


def _csv_rows(headers: list[str], rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({h: ("" if r.get(h) is None else r.get(h)) for h in headers})
    return buf.getvalue()


def _open_lots_csv(report: dict[str, Any]) -> str:
    headers = [
        "ticker",
        "total_quantity",
        "quantity_tax_free",
        "quantity_pending",
        "cost_basis_usd",
        "cost_basis_czk",
        "native_currency",
    ]
    rows = []
    for p in report.get("open_positions") or []:
        rows.append({h: p.get(h) for h in headers})
    return _csv_rows(headers, rows)


def _realized_by_year_csv(summary: dict[str, Any]) -> str:
    headers = [
        "year",
        "disposal_count",
        "taxable_count",
        "exempt_count",
        "taxable_realized_gain_czk",
        "exempt_realized_gain_czk",
        "total_realized_gain_czk",
        "total_realized_gain_usd",
    ]
    return _csv_rows(headers, list(summary.get("years") or []))


def _category_spend_csv(
    repo: SheetsRepository,
    *,
    year: int,
) -> str:
    """Non-internal expenses in calendar year, by category (USD abs)."""
    fx = build_fx_service(repo)
    cats = {
        c.id: c
        for c in repo.list_rows("Categories")
        if isinstance(c, Category) and not c.archived
    }
    by_cat: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_count: dict[str, int] = defaultdict(int)
    uncat = Decimal("0")
    uncat_n = 0
    for t in repo.list_rows("Transactions"):
        if not isinstance(t, Transaction) or t.archived or t.is_internal_transfer:
            continue
        if t.booking_date.year != year:
            continue
        if t.amount >= 0:
            continue
        usd = tx_signed_usd(t, fx)
        if usd is None or usd >= 0:
            continue
        exp = abs(usd)
        cat = cats.get(t.category_id) if t.category_id else None
        if cat is None:
            uncat += exp
            uncat_n += 1
        else:
            by_cat[cat.name] += exp
            by_count[cat.name] += 1

    rows = [
        {
            "category": name,
            "expense_usd": str(amt.quantize(Decimal("0.01"))),
            "tx_count": by_count[name],
        }
        for name, amt in sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
    ]
    if uncat > 0 or uncat_n:
        rows.append(
            {
                "category": "(uncategorized)",
                "expense_usd": str(uncat.quantize(Decimal("0.01"))),
                "tx_count": uncat_n,
            }
        )
    return _csv_rows(["category", "expense_usd", "tx_count"], rows)


def _statement_files_json(repo: SheetsRepository) -> str:
    items = []
    for r in repo.list_rows("StatementFiles"):
        if not isinstance(r, StatementFile) or r.archived:
            continue
        items.append(
            {
                "id": str(r.id),
                "original_filename": r.original_filename,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
                "content_sha256": r.content_sha256,
                "institution": r.institution,
                "row_count": r.row_count,
                "parser_key": r.parser_key,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "notes": r.notes,
            }
        )
    items.sort(key=lambda x: x.get("uploaded_at") or "", reverse=True)
    return json.dumps({"items": items, "count": len(items)}, indent=2)


def _readme(year: int, as_of: date) -> str:
    return f"""Gauntlet Finance — year-end export pack
========================================

Tax year: {year}
Generated as of: {as_of.isoformat()}

Contents
--------
tax-report.json          Full tax report for the year (lot allocations, open lots)
taxable-disposals.csv    Disposals that do NOT qualify for 3-year exemption
exempt-disposals.csv     Disposals that qualify for 3-year exemption
open-lots.csv            Open tax lots snapshot (tax-free vs pending qty)
realized-by-year.csv     Multi-year realised gain summary (CZK/USD)
category-spend-{year}.csv  Cash expenses by category (USD, excl. internal transfers)
statement-files.json     Import audit log (filenames, status, hashes)
README.txt               This file

Methodology notes
-----------------
- Realised gains come from FIFO LotAllocation investment events only.
- Primary tax reporting currency in the JSON is CZK; USD legs included where stored.
- Czech 3-year (1095-day) exemption flags are mathematical from acquisition dates.
- Crypto and other assets may have different legal treatment — verify with an advisor.
- Category spend is a cash-expense rollup for context, not a tax schedule.
- This pack is NOT tax advice and is not a filing package for any authority.

Gauntlet Finance App
"""


def build_year_end_zip(
    repo: SheetsRepository,
    *,
    year: int | None = None,
    as_of: date | None = None,
    exemption_days: int = 1095,
) -> tuple[bytes, str]:
    """
    Build year-end ZIP bytes and suggested filename.

    Returns (zip_bytes, filename).
    """
    as_of = as_of or date.today()
    year = year or as_of.year

    report = build_tax_report(
        repo, year=year, as_of=as_of, exemption_days=exemption_days
    )
    by_year = summary_by_year(repo, as_of=as_of, exemption_days=exemption_days)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "tax-report.json",
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        )
        zf.writestr(
            "taxable-disposals.csv",
            disposals_csv(report.get("taxable_disposals") or []),
        )
        zf.writestr(
            "exempt-disposals.csv",
            disposals_csv(report.get("exempt_disposals") or []),
        )
        zf.writestr("open-lots.csv", _open_lots_csv(report))
        zf.writestr("realized-by-year.csv", _realized_by_year_csv(by_year))
        zf.writestr(
            f"category-spend-{year}.csv",
            _category_spend_csv(repo, year=year),
        )
        zf.writestr("statement-files.json", _statement_files_json(repo) + "\n")
        zf.writestr("README.txt", _readme(year, as_of))

    filename = f"gauntlet-year-end-{year}.zip"
    return buf.getvalue(), filename
