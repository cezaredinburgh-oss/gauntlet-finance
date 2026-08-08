"""Maintenance helpers: cache warm, FX amount backfill, CNB range fetch."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.engines.fx import FXService
from backend.schema.models import FXRate, FXSource, Transaction
from backend.services.fx_amounts import build_fx_service, enrich_and_backfill_transactions
from backend.services.lot_costs import ensure_fx_coverage
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


def _missing_fx_legs(tx: Transaction) -> bool:
    """True when either converted leg still needs filling."""
    return tx.amount_usd is None or tx.amount_czk is None


def backfill_amount_usd(
    repo: SheetsRepository,
    *,
    limit: int = 5000,
    fetch_missing_rates: bool = True,
) -> dict[str, Any]:
    """
    Convert and persist missing amount_usd / amount_czk (batch).

    Priority: active rows missing either converted leg. Optionally fetch CNB
    for booking dates that lack a USD/CZK path before enriching.
    """
    raw = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    active = [t for t in raw if not t.archived]

    missing_usd_before = sum(1 for t in active if t.amount_usd is None)
    missing_czk_before = sum(1 for t in active if t.amount_czk is None)

    priority = [t for t in active if _missing_fx_legs(t)][:limit]
    priority_ids = {t.id for t in priority}
    # Still walk a slice of the rest so partial runs can complete over time
    rest = [t for t in active if t.id not in priority_ids][: max(0, limit - len(priority))]
    ordered = priority + rest

    fx = build_fx_service(repo)
    rates_fetched = 0
    if fetch_missing_rates and ordered:
        rates_fetched = ensure_fx_coverage(
            fx,
            (t.booking_date for t in ordered if _missing_fx_legs(t)),
            repo=repo,
            fetch=True,
        )

    dirty_before = sum(1 for t in ordered if _missing_fx_legs(t))
    enriched = enrich_and_backfill_transactions(ordered, repo, fx, persist=True)

    after_map = {t.id: t for t in enriched}
    # Re-count from enriched batch + untouched actives
    missing_usd_after = 0
    missing_czk_after = 0
    for t in active:
        cur = after_map.get(t.id, t)
        if cur.amount_usd is None:
            missing_usd_after += 1
        if cur.amount_czk is None:
            missing_czk_after += 1

    filled_usd = max(0, missing_usd_before - missing_usd_after)
    filled_czk = max(0, missing_czk_before - missing_czk_after)
    cache_invalidate()
    return {
        "scanned": len(raw),
        "active": len(active),
        "priority_attempted": len(priority),
        "rest_attempted": len(rest),
        "missing_usd_before": missing_usd_before,
        "missing_usd_after": missing_usd_after,
        "missing_czk_before": missing_czk_before,
        "missing_czk_after": missing_czk_after,
        "filled_usd_approx": filled_usd,
        "filled_czk_approx": filled_czk,
        "rates_fetched": rates_fetched,
        "candidates_with_missing_legs": dirty_before,
        # Back-compat keys used by older callers/scripts
        "missing_before": missing_usd_before,
        "missing_after": missing_usd_after,
        "filled_approx": filled_usd,
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
