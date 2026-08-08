"""Dashboard summary + alerts endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Query

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.services.alerts import build_alerts
from backend.services.dashboard import dashboard_summary
from backend.services.response_cache import cached

router = APIRouter(tags=["dashboard"])

PeriodKeyParam = Literal[
    "this_month",
    "last_month",
    "last_30d",
    "last_6m",
    "this_year",
    "last_year",
    "all_time",
    "custom",
    "calendar_month",
]

# Short TTL: timeframe toggles re-hit the same windows often
_DASH_TTL = 45.0
_ALERTS_TTL = 60.0


@router.get("/dashboard-summary")
async def get_dashboard_summary(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    currency: str | None = Query(None, min_length=3, max_length=3),
    period_key: PeriodKeyParam | None = Query(None),
) -> dict[str, Any]:
    key = (
        f"dash:{date_from}:{date_to}:{currency}:{period_key}:"
        f"{settings.holding_period_exemption_days}"
    )

    def _build() -> dict[str, Any]:
        return dashboard_summary(
            repo,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
            period_key=period_key,
            exemption_days=settings.holding_period_exemption_days,
            persist_fx=False,
        )

    return cached(key, _DASH_TTL, _build)


@router.get("/alerts")
async def get_alerts(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
) -> dict[str, Any]:
    days = settings.holding_period_exemption_days
    return cached(
        f"alerts:v2:{days}",
        _ALERTS_TTL,
        lambda: build_alerts(repo, persist_fx=False, exemption_days=days),
    )
