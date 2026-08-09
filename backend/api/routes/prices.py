"""Price refresh + historical series endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.api.schemas import PriceHistoryResponse, PriceRefreshResponse
from backend.services.price_history import PriceHistoryService
from backend.services.prices import PriceService
from backend.services.response_cache import cache_invalidate

router = APIRouter(tags=["prices"])


@router.get("/prices/history", response_model=PriceHistoryResponse)
async def price_history(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    scope: Literal["ticker", "asset_class", "all"] = Query(...),
    range_key: str = Query(
        "1y",
        alias="range",
        description="1d|1m|3m|6m|ytd|1y|5y|max",
    ),
    ticker: str | None = Query(None),
    asset_class: str | None = Query(
        None, description="Stock or Crypto when scope=asset_class"
    ),
) -> PriceHistoryResponse:
    """Google Finance–style history for open positions (yfinance daily / 5m)."""
    if not settings.yfinance_enabled:
        raise HTTPException(status_code=503, detail="yfinance disabled")
    svc = PriceHistoryService(
        repo,
        cache_ttl_seconds=settings.price_history_cache_ttl_seconds,
        intraday_cache_ttl_seconds=settings.price_history_intraday_cache_ttl_seconds,
        enabled=True,
    )
    try:
        result = svc.history(
            scope=scope,
            range_key=range_key,
            ticker=ticker,
            asset_class=asset_class,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Price history fetch failed: {exc}"
        ) from exc

    return PriceHistoryResponse(
        scope=result.scope,
        label=result.label,
        range=result.range,
        currency=result.currency,
        series_kind=result.series_kind,
        interval=result.interval,
        as_of=result.as_of.isoformat(),
        points=[{"date": p["date"], "value": p["value"]} for p in result.points],
        meta=result.meta,
    )


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

    # Portfolio MV charts use /prices/history (current holdings × market series).
    # No longer write PortfolioSnapshots on refresh.

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
