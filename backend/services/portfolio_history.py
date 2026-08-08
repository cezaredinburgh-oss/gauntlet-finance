"""Portfolio market-value history + living/safe draw metrics."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from backend.common.timeutil import utc_now
from backend.schema.models import PortfolioSnapshot
from backend.services.portfolio_snapshot import portfolio_snapshot
from backend.sheets.repository import SheetsRepository

SAFE_DRAW_PCT = Decimal("0.04")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def record_portfolio_snapshot(
    repo: SheetsRepository,
    *,
    as_of: date | None = None,
    source: str = "price_refresh",
    snap: dict[str, Any] | None = None,
    exemption_days: int = 1095,
) -> PortfolioSnapshot:
    """
    Upsert one PortfolioSnapshots row for ``as_of`` (one point per day).

    Prefer passing a prebuilt ``snap`` from portfolio_snapshot() to avoid double work.
    """
    day = as_of or date.today()
    if snap is None:
        snap = portfolio_snapshot(repo, as_of=day, exemption_days=exemption_days)

    mv = _dec(snap.get("total_market_value_usd"))
    cost = _dec(snap.get("total_cost_basis_usd"))
    unr = _dec(snap.get("unrealized_usd"))
    tf = _dec(snap.get("tax_free_now_usd"))

    existing = [
        r
        for r in repo.list_rows("PortfolioSnapshots")
        if isinstance(r, PortfolioSnapshot) and not r.archived and r.as_of == day
    ]
    ts = utc_now()
    prev = existing[0] if existing else None
    row = PortfolioSnapshot(
        id=prev.id if prev else uuid4(),
        as_of=day,
        total_market_value_usd=mv,
        total_cost_basis_usd=cost,
        unrealized_usd=unr,
        tax_free_now_usd=tf,
        source=source,
        notes=prev.notes if prev else None,
        created_at=prev.created_at if prev else ts,
        updated_at=ts,
    )
    repo.upsert_rows("PortfolioSnapshots", [row])
    return row


def list_mv_series(
    repo: SheetsRepository,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    today = date.today()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=365)
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    try:
        raw = repo.list_rows("PortfolioSnapshots")
    except Exception as exc:  # noqa: BLE001
        # Missing tab / transient Sheets error — empty series, not 500
        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "point_count": 0,
            "series": [],
            "error": str(exc)[:300],
        }

    rows = [
        r
        for r in raw
        if isinstance(r, PortfolioSnapshot)
        and not r.archived
        and date_from <= r.as_of <= date_to
    ]
    rows.sort(key=lambda r: r.as_of)
    series = [
        {
            "date": r.as_of.isoformat(),
            "total_market_value_usd": str(r.total_market_value_usd)
            if r.total_market_value_usd is not None
            else None,
            "total_cost_basis_usd": str(r.total_cost_basis_usd)
            if r.total_cost_basis_usd is not None
            else None,
            "unrealized_usd": str(r.unrealized_usd)
            if r.unrealized_usd is not None
            else None,
            "tax_free_now_usd": str(r.tax_free_now_usd)
            if r.tax_free_now_usd is not None
            else None,
            "source": r.source,
        }
        for r in rows
    ]
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "point_count": len(series),
        "series": series,
    }


def compute_draw_metrics(
    repo: SheetsRepository,
    *,
    as_of: date | None = None,
    exemption_days: int = 1095,
    safe_draw_pct: Decimal = SAFE_DRAW_PCT,
    snap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Living draw (trailing 12m sold−bought) vs safe draw capacity.

    safe_annual = min(safe_draw_pct * MV, tax_free_now_usd)
    """
    day = as_of or date.today()
    if snap is None:
        snap = portfolio_snapshot(repo, as_of=day, exemption_days=exemption_days)

    mv = _dec(snap.get("total_market_value_usd")) or Decimal("0")
    tax_free = _dec(snap.get("tax_free_now_usd")) or Decimal("0")
    living = snap.get("living_draw_12m") or {}
    living_draw = _dec(living.get("draw_usd")) or Decimal("0")

    four_pct = _q2(mv * safe_draw_pct)
    safe_annual = min(four_pct, tax_free)
    # If both constraints are zero, safe is 0
    if mv <= 0 and tax_free <= 0:
        safe_annual = Decimal("0")

    ratio: Decimal | None = None
    if safe_annual > 0:
        ratio = (living_draw / safe_annual).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    # Status: living draw is cash extracted; positive living_draw = net sold more than bought
    # OVER if living exceeds safe capacity
    status = "n/a"
    if safe_annual <= 0:
        status = "n/a"
    elif living_draw <= 0:
        status = "ok"  # net reinvesting or flat
    elif ratio is not None and ratio <= Decimal("1"):
        status = "ok"
    elif ratio is not None and ratio <= Decimal("1.25"):
        status = "warn"
    else:
        status = "over"

    binding = (
        "tax_free"
        if tax_free <= four_pct
        else "pct_rule"
    )

    return {
        "as_of": day.isoformat(),
        "portfolio_mv_usd": str(_q2(mv)),
        "tax_free_now_usd": str(_q2(tax_free)),
        "safe_draw_pct": str(safe_draw_pct),
        "safe_draw_from_pct_usd": str(four_pct),
        "safe_draw_annual_usd": str(_q2(safe_annual)),
        "safe_draw_binding_constraint": binding,
        "living_draw_12m_usd": str(_q2(living_draw)),
        "living_sold_usd": living.get("sold_usd"),
        "living_bought_usd": living.get("bought_usd"),
        "living_over_safe_ratio": str(ratio) if ratio is not None else None,
        "status": status,
        "formula": "safe_annual = min(4% × MV, tax_free_now_usd); living = sold − bought (365d)",
        "note": (
            "Heuristic capacity only — not financial or tax advice. "
            "Living draw is investment cash (sells − buys), not living expenses."
        ),
    }


def run_portfolio_snapshot_job(
    repo: SheetsRepository, params: dict[str, Any]
) -> dict[str, Any]:
    """Job runner: refresh snapshot row from current portfolio_snapshot."""
    del params
    snap = portfolio_snapshot(repo)
    row = record_portfolio_snapshot(repo, source="job", snap=snap)
    return {
        "as_of": row.as_of.isoformat(),
        "total_market_value_usd": str(row.total_market_value_usd)
        if row.total_market_value_usd is not None
        else None,
        "tax_free_now_usd": str(row.tax_free_now_usd)
        if row.tax_free_now_usd is not None
        else None,
        "source": row.source,
    }
