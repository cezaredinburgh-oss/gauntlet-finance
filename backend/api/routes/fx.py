"""FX history endpoints for charts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.api.deps import RepoDep, UserDep
from backend.services.fx_series import build_usd_czk_series
from backend.services.response_cache import cached

router = APIRouter(tags=["fx"])

_FX_TTL = 120.0


@router.get("/fx/usd-czk")
async def get_usd_czk_series(
    repo: RepoDep,
    _user: UserDep,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    portfolio_usd: str | None = Query(
        None,
        description="Optional current portfolio MV in USD for CZK context series",
    ),
) -> dict[str, Any]:
    """Historical CZK per 1 USD (CNB) for the selected window."""
    if date_from and date_to and date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to must be >= date_from")
    if date_from and date_to and (date_to - date_from).days > 4000:
        raise HTTPException(status_code=400, detail="range max ~11 years")

    mv: Decimal | None = None
    if portfolio_usd is not None and str(portfolio_usd).strip() != "":
        try:
            mv = Decimal(str(portfolio_usd).replace(",", "").strip())
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="portfolio_usd must be a number"
            ) from exc
        if mv < 0:
            raise HTTPException(status_code=400, detail="portfolio_usd must be >= 0")

    key = f"fx:usd-czk:{date_from}:{date_to}:{mv}"

    def _build() -> dict[str, Any]:
        return build_usd_czk_series(
            repo,
            date_from=date_from,
            date_to=date_to,
            portfolio_usd=mv,
        )

    return cached(key, _FX_TTL, _build)
