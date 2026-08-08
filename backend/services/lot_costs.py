"""Enrich InvestmentLot cost_basis_usd / cost_basis_czk from native cost + FX."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from backend.common.timeutil import utc_now
from backend.engines.fx import FXService
from backend.schema.models import FXRate, InvestmentLot
from backend.services.fx_amounts import build_fx_service
from backend.sheets.repository import SheetsRepository


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def resolve_lot_costs(
    lot: InvestmentLot,
    fx: FXService,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Return (cost_native, cost_czk, cost_usd).

    Prefer converting remaining cost_basis_native on acquisition_date.
    Falls back to stored legs when conversion fails.
    """
    native = lot.cost_basis_native
    ccy = (lot.native_currency or "USD").upper()
    on = lot.acquisition_date

    if ccy == "USD":
        usd = native
        czk = fx.convert(native, "USD", "CZK", on)
        if czk is None:
            czk = lot.cost_basis_czk if lot.cost_basis_czk else Decimal("0")
        return native, _q2(czk), _q2(usd)

    if ccy == "CZK":
        czk = native
        usd = fx.convert(native, "CZK", "USD", on)
        if usd is None:
            usd = lot.cost_basis_usd if lot.cost_basis_usd else Decimal("0")
        return native, _q2(czk), _q2(usd)

    # Other currencies: cross via FX service
    czk = fx.convert(native, ccy, "CZK", on)
    usd = fx.convert(native, ccy, "USD", on)
    if czk is None:
        czk = lot.cost_basis_czk if lot.cost_basis_czk else Decimal("0")
    if usd is None:
        usd = lot.cost_basis_usd if lot.cost_basis_usd else Decimal("0")
    return native, _q2(czk), _q2(usd)


def ensure_fx_coverage(
    fx: FXService,
    dates: Iterable[date],
    *,
    repo: SheetsRepository | None = None,
    fetch: bool = True,
) -> int:
    """
    Best-effort: fetch CNB rates for dates that lack a USD/CZK path.
    Returns number of new FXRate rows loaded into ``fx`` (and optionally repo).
    """
    if not fetch:
        return 0
    needed = sorted({d for d in dates if d is not None})
    created: list[FXRate] = []
    for on in needed:
        # Already have a USD→CZK (or inverse) path?
        if fx.rate_for(on=on, base="USD", quote="CZK") is not None:
            continue
        try:
            rows = fx.fetch_cnb_rates_for_date(on)
            created.extend(rows)
        except Exception:
            # try previous weekdays
            from datetime import timedelta

            for back in range(1, 6):
                try:
                    rows = fx.fetch_cnb_rates_for_date(on - timedelta(days=back))
                    created.extend(rows)
                    break
                except Exception:
                    continue
    if created and repo is not None:
        repo.upsert_rows("FXRates", created)
    return len(created)


def enrich_lots(
    lots: list[InvestmentLot],
    fx: FXService | None = None,
    *,
    repo: SheetsRepository | None = None,
    persist: bool = False,
    fetch_missing_rates: bool = True,
) -> list[InvestmentLot]:
    """
    Fill missing/zero converted cost legs from native cost.

    A lot is considered dirty when stored cost_basis_usd is 0 while native cost > 0
    and native currency is not USD, or cost_basis_czk is 0 while native is not CZK.
    """
    if repo is not None and fx is None:
        fx = build_fx_service(repo)
    if fx is None:
        fx = FXService()

    ensure_fx_coverage(
        fx,
        (lot.acquisition_date for lot in lots),
        repo=repo,
        fetch=fetch_missing_rates,
    )

    out: list[InvestmentLot] = []
    dirty: list[InvestmentLot] = []
    now = utc_now()
    for lot in lots:
        native, czk, usd = resolve_lot_costs(lot, fx)
        needs = False
        # Fix zero/missing converted legs when we computed a positive value
        if usd > 0 and (lot.cost_basis_usd is None or lot.cost_basis_usd == 0):
            needs = True
        if czk > 0 and (lot.cost_basis_czk is None or lot.cost_basis_czk == 0):
            needs = True
        # Also rewrite if native currency is CZK and usd was left at 0 incorrectly
        if (
            lot.native_currency.upper() == "CZK"
            and lot.cost_basis_native > 0
            and (lot.cost_basis_usd or 0) == 0
            and usd > 0
        ):
            needs = True
        if needs:
            updated = lot.model_copy(
                update={
                    "cost_basis_czk": czk,
                    "cost_basis_usd": usd,
                    "updated_at": now,
                }
            )
            out.append(updated)
            dirty.append(updated)
        else:
            out.append(lot)

    if persist and dirty and repo is not None:
        repo.upsert_rows("InvestmentLots", dirty)
    return out
