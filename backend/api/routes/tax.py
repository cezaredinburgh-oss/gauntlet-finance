"""Tax report JSON / CSV endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.services.tax_report import (
    build_tax_report,
    disposals_csv,
    list_tax_years,
    summary_by_year,
)

router = APIRouter(tags=["tax"])


@router.get("/tax-report/years")
async def tax_years(repo: RepoDep, _user: UserDep) -> dict[str, Any]:
    return list_tax_years(repo)


@router.get("/tax-report/summary-by-year")
async def tax_summary_by_year(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    as_of: date | None = None,
) -> dict[str, Any]:
    return summary_by_year(
        repo,
        as_of=as_of,
        exemption_days=settings.holding_period_exemption_days,
    )


@router.get("/tax-report")
async def tax_report(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    year: int | None = Query(None, description="Tax year (default: current year)"),
    as_of: date | None = Query(None),
    format: Literal["json", "csv"] = Query("json"),
    table: Literal["taxable", "exempt", "all"] = Query(
        "taxable",
        description="Which disposal table when format=csv",
    ),
) -> Any:
    report = build_tax_report(
        repo,
        year=year,
        as_of=as_of,
        exemption_days=settings.holding_period_exemption_days,
    )
    if format == "json":
        return report

    if table == "exempt":
        rows = report["exempt_disposals"]
        name = "exempt"
    elif table == "all":
        rows = report["disposals"]
        name = "all"
    else:
        rows = report["taxable_disposals"]
        name = "taxable"

    y = report["meta"]["tax_year"]
    csv_body = disposals_csv(rows)
    return Response(
        content=csv_body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="tax-{y}-{name}-disposals.csv"'
        },
    )
