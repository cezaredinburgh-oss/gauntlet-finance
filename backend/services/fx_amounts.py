"""Resolve and optionally backfill amount_usd / amount_czk on transactions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from backend.common.timeutil import utc_now
from backend.engines.fx import FXService
from backend.schema.models import FXRate, Transaction
from backend.sheets.repository import SheetsRepository


def build_fx_service(repo: SheetsRepository) -> FXService:
    rates = [r for r in repo.list_rows("FXRates") if isinstance(r, FXRate)]
    return FXService(rates=rates)


def resolve_usd(
    amount: Decimal,
    currency: str,
    on: date,
    fx: FXService,
    *,
    amount_usd: Decimal | None = None,
) -> Decimal | None:
    """Return USD equivalent or None if conversion is impossible."""
    if amount_usd is not None:
        return amount_usd
    ccy = (currency or "").upper()
    if ccy == "USD":
        return amount
    return fx.convert(amount, ccy, "USD", on)


def resolve_czk(
    amount: Decimal,
    currency: str,
    on: date,
    fx: FXService,
    *,
    amount_czk: Decimal | None = None,
) -> Decimal | None:
    if amount_czk is not None:
        return amount_czk
    ccy = (currency or "").upper()
    if ccy == "CZK":
        return amount
    return fx.convert(amount, ccy, "CZK", on)


def enrich_transaction_amounts(
    tx: Transaction,
    fx: FXService,
) -> tuple[Transaction, bool]:
    """
    Fill missing amount_usd / amount_czk from historical FX.

    Returns (tx, dirty) where dirty means fields were filled and should be persisted.
    Never overwrites native amount/currency. Never overwrites existing converted fields.
    """
    updates: dict = {}
    on = tx.booking_date

    if tx.amount_usd is None:
        usd = resolve_usd(tx.amount, tx.currency, on, fx, amount_usd=None)
        if usd is not None:
            updates["amount_usd"] = usd

    if tx.amount_czk is None:
        czk = resolve_czk(tx.amount, tx.currency, on, fx, amount_czk=None)
        if czk is not None:
            updates["amount_czk"] = czk

    if not updates:
        return tx, False

    updates["updated_at"] = utc_now()
    return tx.model_copy(update=updates), True


def enrich_and_backfill_transactions(
    txs: Iterable[Transaction],
    repo: SheetsRepository,
    fx: FXService | None = None,
    *,
    persist: bool = True,
) -> list[Transaction]:
    """Enrich list; optionally upsert dirty rows in one batch."""
    fx = fx or build_fx_service(repo)
    out: list[Transaction] = []
    dirty: list[Transaction] = []
    for tx in txs:
        enriched, is_dirty = enrich_transaction_amounts(tx, fx)
        out.append(enriched)
        if is_dirty:
            dirty.append(enriched)
    if persist and dirty:
        repo.upsert_rows("Transactions", dirty)
    return out


def tx_usd_abs(tx: Transaction, fx: FXService) -> Decimal | None:
    """Absolute USD magnitude of tx.amount, or None if unconverted."""
    usd = resolve_usd(
        abs(tx.amount),
        tx.currency,
        tx.booking_date,
        fx,
        amount_usd=abs(tx.amount_usd) if tx.amount_usd is not None else None,
    )
    return usd


def tx_signed_usd(tx: Transaction, fx: FXService) -> Decimal | None:
    """Signed USD amount (preserves income/expense sign)."""
    if tx.amount_usd is not None:
        # amount_usd may be stored as absolute or signed — normalize to amount sign
        mag = abs(tx.amount_usd)
        return mag if tx.amount >= 0 else -mag
    usd = resolve_usd(tx.amount, tx.currency, tx.booking_date, fx, amount_usd=None)
    return usd


def tx_signed_czk(tx: Transaction, fx: FXService) -> Decimal | None:
    if tx.amount_czk is not None:
        mag = abs(tx.amount_czk)
        return mag if tx.amount >= 0 else -mag
    return resolve_czk(tx.amount, tx.currency, tx.booking_date, fx, amount_czk=None)
