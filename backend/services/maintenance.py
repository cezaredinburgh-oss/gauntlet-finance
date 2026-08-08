"""Maintenance helpers: cache warm, USD backfill, CNB range fetch."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.engines.fx import FXService
from backend.schema.models import FXRate, FXSource, Transaction
from backend.services.fx_amounts import build_fx_service, enrich_and_backfill_transactions
from backend.services.response_cache import cache_invalidate
from backend.sheets.repository import SheetsRepository

_HEAVY_TABS = (
    "Transactions",
    "InvestmentEvents",
    "InvestmentLots",
    "Prices",
    "Categories",
    "CategoryRules",
    "FXRates",
    "Accounts",
)


def warm_cache(repo: SheetsRepository) -> dict[str, Any]:
    """Force-read heavy tabs so subsequent GETs hit memory/TTL cache."""
    counts: dict[str, Any] = {}
    for tab in _HEAVY_TABS:
        try:
            rows = repo.list_rows(tab)
            counts[tab] = len(rows)
        except Exception as exc:  # noqa: BLE001
            counts[tab] = {"error": str(exc)}
    return {"ok": True, "counts": counts}


def backfill_amount_usd(
    repo: SheetsRepository, *, limit: int = 5000
) -> dict[str, Any]:
    """Convert and persist missing amount_usd / amount_czk (batch)."""
    raw = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    # Prefer rows still missing USD conversion
    priority = [
        t
        for t in raw
        if not t.archived and t.amount_usd is None
    ][:limit]
    rest = [t for t in raw if t not in priority]
    ordered = priority + rest

    missing_before = sum(
        1 for t in raw if not t.archived and t.amount_usd is None
    )
    fx = build_fx_service(repo)
    enrich_and_backfill_transactions(ordered, repo, fx, persist=True)
    after = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    missing_after = sum(
        1 for t in after if not t.archived and t.amount_usd is None
    )
    cache_invalidate()
    return {
        "scanned": len(raw),
        "priority_attempted": len(priority),
        "missing_before": missing_before,
        "missing_after": missing_after,
        "filled_approx": max(0, missing_before - missing_after),
    }


def fetch_cnb_range(
    repo: SheetsRepository,
    *,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """Fetch CNB rates day-by-day and upsert into FXRates tab."""
    fx_svc = FXService(preferred_source=FXSource.CNB.value)
    existing = [
        r for r in repo.list_rows("FXRates") if isinstance(r, FXRate) and not r.archived
    ]
    if existing:
        fx_svc.load_rates(existing)

    all_new: list[FXRate] = []
    errors: list[str] = []
    d = date_from
    while d <= date_to:
        try:
            created = fx_svc.fetch_cnb_rates_for_date(d)
            all_new.extend(created)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{d.isoformat()}: {exc}")
        d += timedelta(days=1)

    if all_new:
        repo.upsert_rows("FXRates", all_new)
    cache_invalidate()
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "rates_upserted": len(all_new),
        "errors": errors[:20],
        "error_count": len(errors),
    }
