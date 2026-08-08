"""Shared parser result types and account resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from backend.common.timeutil import utc_now
from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentLot,
    LotStatus,
    Transaction,
)


@dataclass
class ParseResult:
    """Normalized output of a single statement parse (no I/O)."""

    parser_key: str
    institution: str
    row_count: int
    transactions: list[Transaction] = field(default_factory=list)
    investment_events: list[InvestmentEvent] = field(default_factory=list)
    investment_lots: list[InvestmentLot] = field(default_factory=list)


@dataclass
class ImportGateResult:
    """
    Top-level outcome for a file upload.

    ``status`` is ``already_imported`` when content SHA-256 matches an existing
    StatementFiles hash; otherwise ``parsed``.
    """

    status: str  # "parsed" | "already_imported"
    content_sha256: str
    parser_key: str | None = None
    institution: str | None = None
    row_count: int = 0
    transactions: list[Transaction] = field(default_factory=list)
    investment_events: list[InvestmentEvent] = field(default_factory=list)
    investment_lots: list[InvestmentLot] = field(default_factory=list)
    message: str = ""


def resolve_account_id(
    account_ids: Mapping[str, UUID],
    *,
    currency: str | None = None,
    default_key: str = "default",
) -> UUID:
    """
    Resolve account UUID from a currency-keyed map.

    Accepts keys: exact currency (``CZK``), ``default``, or a single-entry map.
    """
    if currency and currency.upper() in account_ids:
        return account_ids[currency.upper()]
    if default_key in account_ids:
        return account_ids[default_key]
    if len(account_ids) == 1:
        return next(iter(account_ids.values()))
    keys = ", ".join(sorted(account_ids))
    raise KeyError(
        f"No account_id for currency={currency!r}; available keys: {keys}"
    )


def placeholder_basis(
    cost_native: Decimal,
    native_currency: str,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Split cost into native/CZK/USD slots without FX rates.

    Unknown legs are ``0``; filled later by the FX enrichment phase.
    """
    ccy = (native_currency or "").upper()
    if ccy == "CZK":
        return cost_native, cost_native, Decimal("0")
    if ccy == "USD":
        return cost_native, Decimal("0"), cost_native
    return cost_native, Decimal("0"), Decimal("0")


def open_lot_from_buy(
    *,
    account_id: UUID,
    ticker: str,
    asset_class: AssetClass,
    source: str,
    acquisition_date,
    quantity: Decimal,
    cost_native: Decimal,
    native_currency: str,
    open_event_id: UUID,
    now: datetime | None = None,
    notes: str | None = None,
) -> InvestmentLot:
    """Create an Open InvestmentLot for a Buy / StakingReward acquisition."""
    ts = now or utc_now()
    native, czk, usd = placeholder_basis(cost_native, native_currency)
    return InvestmentLot(
        id=uuid4(),
        account_id=account_id,
        ticker=ticker,
        asset_class=asset_class,
        source=source,
        acquisition_date=acquisition_date,
        quantity_opened=quantity,
        quantity_remaining=quantity,
        cost_basis_native=native,
        cost_basis_czk=czk,
        cost_basis_usd=usd,
        native_currency=native_currency.upper(),
        open_event_id=open_event_id,
        status=LotStatus.OPEN,
        notes=notes,
        created_at=ts,
        updated_at=ts,
    )


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None
