"""Tax report JSON endpoint."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.services.tax_report import build_tax_report

router = APIRouter(tags=["tax"])


@router.get("/tax-report")
async def tax_report(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    year: int | None = Query(None, description="Tax year (default: current year)"),
    as_of: date | None = Query(None),
) -> dict[str, Any]:
    return build_tax_report(
        repo,
        year=year,
        as_of=as_of,
        exemption_days=settings.holding_period_exemption_days,
    )
