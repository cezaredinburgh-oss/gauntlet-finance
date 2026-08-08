"""Price refresh endpoint (UI button)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.api.schemas import PriceRefreshResponse
from backend.services.prices import PriceService
from backend.services.response_cache import cache_invalidate

router = APIRouter(tags=["prices"])


@router.post("/prices/refresh", response_model=PriceRefreshResponse)
async def refresh_prices(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    force: bool = Query(False, description="Bypass TTL cache"),
) -> PriceRefreshResponse:
    if not settings.yfinance_enabled:
        raise HTTPException(status_code=503, detail="yfinance disabled")
    svc = PriceService(
        repo,
        cache_ttl_seconds=settings.price_cache_ttl_seconds,
        enabled=True,
    )
    try:
        result = svc.refresh_and_store(force=force)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Price fetch failed: {exc}") from exc

    # Point-in-time MV history (one row per day; best-effort)
    try:
        from backend.services.portfolio_history import record_portfolio_snapshot
        from backend.services.portfolio_snapshot import portfolio_snapshot

        snap = portfolio_snapshot(
            repo, exemption_days=settings.holding_period_exemption_days
        )
        record_portfolio_snapshot(
            repo,
            source="price_refresh",
            snap=snap,
            exemption_days=settings.holding_period_exemption_days,
        )
    except Exception:  # noqa: BLE001
        pass

    cache_invalidate("snap:")
    cache_invalidate("dash:")
    # Digests include mark-to-market ROI; must not serve pre-refresh unpriced payloads
    cache_invalidate("ticker-digests:")

    return PriceRefreshResponse(
        as_of=result.as_of.isoformat(),
        quote_count=len(result.quotes),
        total_market_value_usd=(
            str(result.total_market_value_usd)
            if result.total_market_value_usd is not None
            else None
        ),
        quotes=[
            {
                "ticker": q.ticker,
                "price": str(q.price),
                "currency": q.currency,
                "as_of": q.as_of.isoformat(),
                "source": q.source,
            }
            for q in result.quotes
        ],
        positions=result.positions,
        errors=result.errors,
    )
