"""Shared builders for domain-service unit tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from backend.schema.models import (
    AssetClass,
    Category,
    CategoryRule,
    FXRate,
    FXSource,
    InvestmentEvent,
    InvestmentEventType,
    LifeDomain,
    MatchField,
    MatchType,
    Necessity,
    TradeSide,
    Transaction,
)

TS = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


def tx(
    *,
    account_id: UUID | None = None,
    booking_date: date = date(2026, 7, 20),
    amount: str | Decimal = "-100",
    currency: str = "CZK",
    description: str | None = None,
    original_description: str | None = None,
    merchant: str | None = None,
    source_institution: str = "Raiffeisen",
    external_id: str | None = None,
    is_internal_transfer: bool = False,
    transfer_group_id: UUID | None = None,
    category_id: UUID | None = None,
    category_override: bool = False,
    counterparty_account: str | None = None,
    suggest_category_id: UUID | None = None,
    suggest_source: str | None = None,
    suggest_reason: str | None = None,
) -> Transaction:
    return Transaction(
        id=uuid4(),
        account_id=account_id or uuid4(),
        booking_date=booking_date,
        amount=Decimal(amount) if not isinstance(amount, Decimal) else amount,
        currency=currency,
        fee_amount=Decimal("0"),
        merchant=merchant,
        description=description,
        original_description=original_description,
        source_institution=source_institution,
        external_id=external_id,
        counterparty_account=counterparty_account,
        category_id=category_id,
        category_override=category_override,
        is_internal_transfer=is_internal_transfer,
        transfer_group_id=transfer_group_id,
        suggest_category_id=suggest_category_id,
        suggest_source=suggest_source,
        suggest_reason=suggest_reason,
        created_at=TS,
        updated_at=TS,
    )


def inv_event(
    *,
    account_id: UUID | None = None,
    event_type: InvestmentEventType = InvestmentEventType.BUY,
    event_date: date = date(2021, 11, 10),
    ticker: str | None = "PLTR",
    quantity: str | Decimal | None = "10",
    price_native: str | Decimal | None = "20",
    value_native: str | Decimal | None = "200",
    fees_native: str | Decimal = "0",
    native_currency: str = "USD",
    asset_class: AssetClass = AssetClass.STOCK,
    lot_id: UUID | None = None,
    parent_event_id: UUID | None = None,
    source: str = "Revolut",
) -> InvestmentEvent:
    def d(v: str | Decimal | None) -> Decimal | None:
        if v is None:
            return None
        return Decimal(v) if not isinstance(v, Decimal) else v

    side = None
    if event_type == InvestmentEventType.BUY:
        side = TradeSide.BUY
    elif event_type == InvestmentEventType.SELL:
        side = TradeSide.SELL

    return InvestmentEvent(
        id=uuid4(),
        account_id=account_id or uuid4(),
        event_type=event_type,
        event_date=event_date,
        ticker=ticker,
        asset_class=asset_class,
        side=side,
        quantity=d(quantity),
        price_native=d(price_native),
        native_currency=native_currency,
        value_native=d(value_native),
        fees_native=d(fees_native) or Decimal("0"),
        lot_id=lot_id,
        parent_event_id=parent_event_id,
        source=source,
        created_at=TS,
        updated_at=TS,
    )


def fx_rate(
    *,
    rate_date: date,
    base: str,
    quote: str = "CZK",
    rate: str | Decimal,
    source: FXSource = FXSource.CNB,
) -> FXRate:
    return FXRate(
        id=uuid4(),
        rate_date=rate_date,
        base_currency=base,
        quote_currency=quote,
        rate=Decimal(rate) if not isinstance(rate, Decimal) else rate,
        source=source,
        created_at=TS,
        updated_at=TS,
    )


def category(
    *,
    name: str,
    necessity: Necessity = Necessity.DISCRETIONARY,
    life_domain: LifeDomain = LifeDomain.OTHER,
    is_income: bool = False,
    is_transfer: bool = False,
) -> Category:
    return Category(
        id=uuid4(),
        name=name,
        necessity=necessity,
        life_domain=life_domain,
        is_income=is_income,
        is_transfer=is_transfer,
        created_at=TS,
        updated_at=TS,
    )


def rule(
    *,
    priority: int,
    category_id: UUID,
    match_field: MatchField = MatchField.MERCHANT,
    match_type: MatchType = MatchType.CONTAINS,
    match_value: str,
    set_internal_transfer: bool = False,
    institution_scope: str | None = None,
) -> CategoryRule:
    return CategoryRule(
        id=uuid4(),
        priority=priority,
        match_field=match_field,
        match_type=match_type,
        match_value=match_value,
        category_id=category_id,
        set_internal_transfer=set_internal_transfer,
        institution_scope=institution_scope,
        created_at=TS,
        updated_at=TS,
    )
