"""Investments, lots, categories list endpoints + category override."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.engines.lots import LotEngine
from backend.schema.models import (
    InvestmentEvent,
    InvestmentLot,
    LotStatus,
)
from backend.services.dca_opportunities import build_dca_board_from_repo
from backend.services.portfolio_history import (
    compute_draw_metrics,
    list_mv_series,
    record_portfolio_snapshot,
)
from backend.services.portfolio_snapshot import portfolio_snapshot
from backend.services.response_cache import cached
from backend.services.ticker_digest import build_ticker_digests

router = APIRouter(tags=["investments"])

_SNAP_TTL = 45.0


@router.get("/investments/snapshot")
async def get_investments_snapshot(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    as_of: date | None = None,
) -> dict[str, Any]:
    key = f"snap:{as_of}:{settings.holding_period_exemption_days}"

    def _build() -> dict[str, Any]:
        return portfolio_snapshot(
            repo,
            as_of=as_of,
            exemption_days=settings.holding_period_exemption_days,
        )

    return cached(key, _SNAP_TTL, _build)


@router.get("/investments/mv-series")
async def get_mv_series(
    repo: RepoDep,
    _user: UserDep,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> dict[str, Any]:
    """Historical portfolio market value from PortfolioSnapshots (forward-only)."""
    return list_mv_series(repo, date_from=date_from, date_to=date_to)


@router.get("/investments/draw-metrics")
async def get_draw_metrics(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Living draw (12m) vs safe draw min(4% MV, tax_free_now)."""
    key = f"draw:{as_of}:{settings.holding_period_exemption_days}"

    def _build() -> dict[str, Any]:
        return compute_draw_metrics(
            repo,
            as_of=as_of,
            exemption_days=settings.holding_period_exemption_days,
        )

    return cached(key, _SNAP_TTL, _build)


@router.post("/investments/snapshots/record")
async def record_snapshot_now(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
) -> dict[str, Any]:
    """Manually append/update today's MV snapshot (no price refresh)."""
    snap = portfolio_snapshot(
        repo, exemption_days=settings.holding_period_exemption_days
    )
    row = record_portfolio_snapshot(
        repo,
        source="manual",
        snap=snap,
        exemption_days=settings.holding_period_exemption_days,
    )
    return {
        "as_of": row.as_of.isoformat(),
        "total_market_value_usd": str(row.total_market_value_usd)
        if row.total_market_value_usd is not None
        else None,
        "source": row.source,
    }


@router.get("/investments/ticker-digests")
async def get_ticker_digests(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Per-ticker verification digests (platform qty, tax MV, ROI, portfolio role)."""
    key = f"ticker-digests:{as_of}:{settings.holding_period_exemption_days}"

    def _build() -> dict[str, Any]:
        return build_ticker_digests(
            repo,
            as_of=as_of,
            exemption_days=settings.holding_period_exemption_days,
        )

    return cached(key, _SNAP_TTL, _build)


@router.get("/investments/dca-opportunities")
async def get_dca_opportunities(
    repo: RepoDep,
    _user: UserDep,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Ranked DCA board: stocks + crypto lists scored by opportunity size."""
    key = f"dca-board:v1:{as_of}"

    def _build() -> dict[str, Any]:
        return build_dca_board_from_repo(repo, as_of=as_of, fetch_history=True)

    return cached(key, _SNAP_TTL, _build)


@router.get("/investments")
async def list_investments(
    repo: RepoDep,
    _user: UserDep,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    ticker: str | None = None,
    event_type: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]
    out: list[InvestmentEvent] = []
    for e in rows:
        if e.archived:
            continue
        if date_from and e.event_date < date_from:
            continue
        if date_to and e.event_date > date_to:
            continue
        if ticker and (e.ticker or "").upper() != ticker.upper():
            continue
        if event_type and e.event_type.value != event_type:
            continue
        out.append(e)
    out.sort(key=lambda x: (x.event_date, str(x.id)), reverse=True)
    total = len(out)
    page = out[offset : offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [e.model_dump(mode="json") for e in page],
    }


@router.get("/lots")
async def list_lots(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    ticker: str | None = None,
    open_only: bool = True,
    as_of: date | None = None,
) -> dict[str, Any]:
    rows = [r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)]
    engine = LotEngine(exemption_days=settings.holding_period_exemption_days)
    as_of = as_of or date.today()
    items = []
    for lot in rows:
        if lot.archived:
            continue
        if open_only and (
            lot.status != LotStatus.OPEN or lot.quantity_remaining <= 0
        ):
            continue
        if ticker and lot.ticker.upper() != ticker.upper():
            continue
        from datetime import timedelta

        held = (as_of - lot.acquisition_date).days
        tax_free_on = lot.acquisition_date + timedelta(
            days=settings.holding_period_exemption_days
        )
        items.append(
            {
                **lot.model_dump(mode="json"),
                "holding_period_days": held,
                "tax_free_on": tax_free_on.isoformat(),
                "qualifies_3y_exemption": held >= settings.holding_period_exemption_days,
            }
        )
    items.sort(key=lambda x: (x["ticker"], x["acquisition_date"]))
    # Optional ticker summaries
    tickers = sorted({i["ticker"].upper() for i in items})
    summaries = [
        engine.summarize_ticker(rows, t, as_of=as_of).__dict__
        for t in tickers
    ]
    # Convert non-json types in summaries
    clean_summaries = []
    for s in summaries:
        lots_el = []
        for l in s.get("lots") or []:
            lots_el.append(
                {
                    "lot_id": str(l.lot_id),
                    "ticker": l.ticker,
                    "quantity_remaining": str(l.quantity_remaining),
                    "acquisition_date": l.acquisition_date.isoformat(),
                    "tax_free_on": l.tax_free_on.isoformat(),
                    "holding_period_days": l.holding_period_days,
                    "qualifies_3y_exemption": l.qualifies_3y_exemption,
                    "cost_basis_native": str(l.cost_basis_native),
                    "cost_basis_czk": str(l.cost_basis_czk),
                    "cost_basis_usd": str(l.cost_basis_usd),
                    "native_currency": l.native_currency,
                }
            )
        clean_summaries.append(
            {
                "ticker": s["ticker"],
                "total_quantity": str(s["total_quantity"]),
                "quantity_tax_free": str(s["quantity_tax_free"]),
                "quantity_pending": str(s["quantity_pending"]),
                "cost_basis_native": str(s["cost_basis_native"]),
                "cost_basis_czk": str(s["cost_basis_czk"]),
                "cost_basis_usd": str(s["cost_basis_usd"]),
                "native_currency": s["native_currency"],
                "as_of": s["as_of"].isoformat() if hasattr(s["as_of"], "isoformat") else s["as_of"],
                "lots": lots_el,
            }
        )
    return {"items": items, "summaries": clean_summaries}


# Category list / override live in backend.api.routes.categories
