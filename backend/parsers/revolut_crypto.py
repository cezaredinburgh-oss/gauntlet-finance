"""Revolut crypto activity CSV parser."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from backend.common.money import parse_decimal_optional, parse_money_with_currency
from backend.common.timeutil import parse_flexible_datetime, utc_now
from backend.engines.statements import revolut_event_external_id
from backend.parsers.base import (
    ParseResult,
    empty_to_none,
    open_lot_from_buy,
    resolve_account_id,
)
from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    ParserKey,
    TradeSide,
)

_TYPE_MAP = {
    "buy": InvestmentEventType.BUY,
    "sell": InvestmentEventType.SELL,
    "stake": InvestmentEventType.STAKE,
    "staking reward": InvestmentEventType.STAKING_REWARD,
}

# Marker in event/lot notes after fee-netting Buy quantity
REVOLUT_BUY_FEE_NET_TAG = "revolut_buy_fee_net"


def net_revolut_crypto_buy_quantity(
    qty_gross: Decimal,
    value: Decimal | None,
    fees: Decimal | None,
) -> tuple[Decimal, Decimal | None]:
    """
    Revolut crypto statement Buy quantity is **gross**.

    Support confirms the app balance is **net of service fee**. Fees appear in
    fiat on the Fees column (often ~0.99% of Value on Metal). Credited crypto:

        qty_net = qty_gross * (1 - fees / value)

    Returns (qty_net, fee_rate or None if not applied).
    """
    if qty_gross <= 0:
        return qty_gross, None
    if value is None or value <= 0:
        return qty_gross, None
    fee_amt = fees if fees is not None else Decimal("0")
    if fee_amt < 0:
        fee_amt = Decimal("0")
    fee_rate = fee_amt / value
    if fee_rate <= 0:
        return qty_gross, Decimal("0")
    if fee_rate >= 1:
        # Pathological row — do not zero out inventory
        return qty_gross, None
    return qty_gross * (Decimal("1") - fee_rate), fee_rate


def parse_revolut_crypto(
    text: str,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    """
    Parse Revolut crypto CSV.

    Handles messy US dates with narrow spaces, mixed USD/CZK money cells,
    and empty Price/Value/Fees on staking rewards.

    **Buy quantity:** statement qty is gross; we store **net of service fee**
    using ``qty * (1 - fees/value)`` so open lots track app balances.
    Cost basis remains ``value + fees`` (total fiat paid).
    """
    ts = now or utc_now()
    reader = csv.DictReader(io.StringIO(text))
    events: list[InvestmentEvent] = []
    lots = []
    data_rows = 0
    account_id = resolve_account_id(account_ids, currency=None)

    for row in reader:
        if not row or not any((v or "").strip() for v in row.values()):
            continue
        data_rows += 1

        symbol = empty_to_none(row.get("Symbol"))
        type_raw = (row.get("Type") or "").strip()
        event_type = _TYPE_MAP.get(type_raw.lower())
        if event_type is None:
            # Unknown type — skip but count
            continue

        dt = parse_flexible_datetime(row["Date"])
        qty_gross = parse_decimal_optional(row.get("Quantity"))

        price, price_ccy = parse_money_with_currency(row.get("Price"))
        value, value_ccy = parse_money_with_currency(row.get("Value"))
        fees, fees_ccy = parse_money_with_currency(row.get("Fees"))
        if fees is None:
            fees = Decimal("0")

        native_currency = (
            value_ccy or price_ccy or fees_ccy or "USD"
        ).upper()

        # Cost for lot open: value + fees when present; 0 for empty staking reward
        cost_native = (value or Decimal("0")) + (fees or Decimal("0"))
        if event_type == InvestmentEventType.BUY and value is not None:
            cost_native = value + fees
        elif event_type == InvestmentEventType.STAKING_REWARD:
            cost_native = value if value is not None else Decimal("0")

        # Inventory quantity: net service fee on Buys only
        qty = qty_gross
        fee_rate: Decimal | None = None
        buy_notes: str | None = None
        if (
            event_type == InvestmentEventType.BUY
            and qty_gross is not None
            and qty_gross > 0
        ):
            qty, fee_rate = net_revolut_crypto_buy_quantity(qty_gross, value, fees)
            if fee_rate is not None and fee_rate > 0:
                buy_notes = (
                    f"{REVOLUT_BUY_FEE_NET_TAG}; gross_qty={qty_gross}; "
                    f"fee_rate={fee_rate}"
                )
            else:
                buy_notes = f"{REVOLUT_BUY_FEE_NET_TAG}; gross_qty={qty_gross}"

        side = None
        if event_type in {
            InvestmentEventType.BUY,
            InvestmentEventType.STAKING_REWARD,
        }:
            side = TradeSide.BUY
        elif event_type == InvestmentEventType.SELL:
            side = TradeSide.SELL

        event_id = uuid4()
        lot_id = None
        if (
            event_type
            in {InvestmentEventType.BUY, InvestmentEventType.STAKING_REWARD}
            and symbol
            and qty is not None
            and qty > 0
        ):
            lot_notes = (
                "staking reward FMV basis"
                if event_type == InvestmentEventType.STAKING_REWARD
                else buy_notes
            )
            lot = open_lot_from_buy(
                account_id=account_id,
                ticker=symbol,
                asset_class=AssetClass.CRYPTO,
                source="Revolut",
                acquisition_date=dt.date(),
                quantity=qty,
                cost_native=cost_native,
                native_currency=native_currency,
                open_event_id=event_id,
                now=ts,
                notes=lot_notes,
            )
            lots.append(lot)
            lot_id = lot.id

        original = ",".join(
            [
                symbol or "",
                type_raw,
                str(row.get("Quantity") or ""),
                str(row.get("Price") or ""),
                str(row.get("Value") or ""),
                str(row.get("Fees") or ""),
                str(row.get("Date") or ""),
            ]
        )

        external_id = revolut_event_external_id(
            event_type=event_type.value,
            ticker=symbol,
            event_datetime=dt,
            quantity=qty,
            value_native=value,
            fees_native=fees,
            currency=native_currency,
        )

        events.append(
            InvestmentEvent(
                id=event_id,
                account_id=account_id,
                event_type=event_type,
                event_date=dt.date(),
                event_datetime=dt,
                ticker=symbol,
                asset_class=AssetClass.CRYPTO,
                side=side,
                quantity=qty,
                price_native=price,
                native_currency=native_currency,
                value_native=value,
                fees_native=fees,
                value_usd=value if native_currency == "USD" else None,
                value_czk=value if native_currency == "CZK" else None,
                fees_usd=fees if native_currency == "USD" else None,
                fees_czk=fees if native_currency == "CZK" else None,
                lot_id=lot_id,
                source="Revolut",
                external_id=external_id,
                description=f"{type_raw} {symbol or ''}".strip(),
                original_description=original,
                notes=buy_notes if event_type == InvestmentEventType.BUY else None,
                source_file_id=source_file_id,
                original_file_hash=file_hash,
                created_at=ts,
                updated_at=ts,
            )
        )

    return ParseResult(
        parser_key=ParserKey.REVOLUT_CRYPTO.value,
        institution="Revolut",
        row_count=data_rows,
        investment_events=events,
        investment_lots=lots,
    )


def parse_revolut_crypto_bytes(
    file_bytes: bytes,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    from backend.parsers.detect import decode_statement_text

    return parse_revolut_crypto(
        decode_statement_text(file_bytes),
        account_ids=account_ids,
        source_file_id=source_file_id,
        file_hash=file_hash,
        now=now,
    )
