"""Downloadable export packs."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import Response

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.services.year_end_export import build_year_end_zip

router = APIRouter(tags=["exports"])


@router.get("/exports/year-end")
async def export_year_end(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    year: int | None = Query(None, description="Tax/calendar year (default: current)"),
    as_of: date | None = Query(None),
) -> Response:
    """ZIP: tax report, disposals CSVs, open lots, multi-year gains, category spend, statements."""
    payload, filename = build_year_end_zip(
        repo,
        year=year,
        as_of=as_of,
        exemption_days=settings.holding_period_exemption_days,
    )
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )
