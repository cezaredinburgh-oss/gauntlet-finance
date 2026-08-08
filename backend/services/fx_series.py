"""Historical USD/CZK series for charts (CNB rates from FXRates)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.engines.fx import FXService
from backend.schema.models import FXRate
from backend.services.fx_amounts import build_fx_service
from backend.sheets.repository import SheetsRepository


def _q4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _usd_czk_on(fx: FXService, on: date) -> Decimal | None:
    """CZK per 1 USD on or before ``on`` (lookback handled by FXService)."""
    return fx.rate_for(on=on, base="USD", quote="CZK", max_lookback_days=14)


def build_usd_czk_series(
    repo: SheetsRepository,
    *,
    date_from: date | None,
    date_to: date | None,
    portfolio_usd: Decimal | None = None,
    max_points: int = 366,
) -> dict[str, Any]:
    """
    Daily-ish USD→CZK series from stored FXRates.

    When ``portfolio_usd`` is set, each point also includes
    ``portfolio_czk = portfolio_usd * rate`` — a counterfactual of *today's*
    USD market value expressed in CZK at that day's rate (isolates pure FX
    impact on the CZK reading of wealth).
    """
    today = date.today()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - timedelta(days=180)
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    fx = build_fx_service(repo)
    rates = [r for r in repo.list_rows("FXRates") if isinstance(r, FXRate) and not r.archived]

    # Prefer exact daily USD/CZK rows in window (and a short lookback seed)
    seed_from = date_from - timedelta(days=21)
    daily: dict[date, Decimal] = {}
    for r in rates:
        b = r.base_currency.upper()
        q = r.quote_currency.upper()
        if b == "USD" and q == "CZK":
            daily[r.rate_date] = r.rate
        elif b == "CZK" and q == "USD" and r.rate != 0:
            daily[r.rate_date] = _q4(Decimal("1") / r.rate)

    # Walk calendar; fill via FXService lookback so weekends still chart
    series: list[dict[str, Any]] = []
    d = date_from
    while d <= date_to:
        rate = daily.get(d) or _usd_czk_on(fx, d)
        if rate is not None:
            point: dict[str, Any] = {
                "date": d.isoformat(),
                "rate": str(_q4(rate)),
            }
            if portfolio_usd is not None:
                point["portfolio_czk"] = str(_q2(portfolio_usd * rate))
            series.append(point)
        d += timedelta(days=1)

    # Downsample dense windows for chart payload size
    if len(series) > max_points:
        step = max(1, len(series) // max_points)
        sampled = series[::step]
        if sampled[-1] is not series[-1]:
            sampled.append(series[-1])
        # Always keep first
        if sampled[0] is not series[0]:
            sampled = [series[0]] + sampled
        series = sampled

    first = series[0] if series else None
    last = series[-1] if series else None
    rate_start = Decimal(first["rate"]) if first else None
    rate_end = Decimal(last["rate"]) if last else None

    change_abs: Decimal | None = None
    change_pct: Decimal | None = None
    if rate_start is not None and rate_end is not None:
        change_abs = _q4(rate_end - rate_start)
        if rate_start != 0:
            change_pct = _q4((rate_end - rate_start) / rate_start * Decimal("100"))

    portfolio_block: dict[str, Any] | None = None
    if portfolio_usd is not None and rate_end is not None:
        czk_now = _q2(portfolio_usd * rate_end)
        czk_at_start = (
            _q2(portfolio_usd * rate_start) if rate_start is not None else None
        )
        fx_delta_czk = (
            _q2(czk_now - czk_at_start) if czk_at_start is not None else None
        )
        portfolio_block = {
            "portfolio_usd": str(_q2(portfolio_usd)),
            "portfolio_czk_now": str(czk_now),
            "portfolio_czk_at_period_start_rate": (
                str(czk_at_start) if czk_at_start is not None else None
            ),
            "fx_delta_czk": str(fx_delta_czk) if fx_delta_czk is not None else None,
            "note": (
                "CZK portfolio path holds today's USD market value fixed and "
                "revalues it at each day's CNB USD/CZK rate — pure FX effect "
                "on the CZK reading of current wealth, not historical holdings."
            ),
        }

    return {
        "pair": "USD/CZK",
        "unit": "CZK per 1 USD",
        "source": "CNB (stored FXRates)",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "point_count": len(series),
        "rate_start": str(rate_start) if rate_start is not None else None,
        "rate_end": str(rate_end) if rate_end is not None else None,
        "change_abs": str(change_abs) if change_abs is not None else None,
        "change_pct": str(change_pct) if change_pct is not None else None,
        "portfolio": portfolio_block,
        "series": series,
        "rates_in_sheet": len(daily),
        "seed_from": seed_from.isoformat(),
    }
