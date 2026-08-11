"""Revolut stocks / securities CSV parser."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from backend.common.money import parse_decimal_optional, parse_money_with_currency
from backend.common.timeutil import parse_flexible_datetime, utc_now
from backend.config import get_settings
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


def _map_event_type(type_raw: str) -> InvestmentEventType | None:
    t = (type_raw or "").strip().upper()
    if not t:
        return None
    if t.startswith("BUY"):
        return InvestmentEventType.BUY
    if t.startswith("SELL"):
        return InvestmentEventType.SELL
    if "CASH TOP-UP" in t or t == "CASH TOP-UP":
        return InvestmentEventType.DEPOSIT
    if "CASH WITHDRAWAL" in t or t == "CASH WITHDRAWAL":
        return InvestmentEventType.WITHDRAWAL
    if "CUSTODY FEE" in t or (t.endswith("FEE") and "TRANSFER" not in t):
        return InvestmentEventType.FEE
    if "STOCK SPLIT" in t or t == "SPLIT":
        return InvestmentEventType.SPLIT
    if t.startswith("TRANSFER"):
        return InvestmentEventType.TRANSFER
    return None


def parse_revolut_stocks(
    text: str,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    """
    Parse Revolut stocks CSV.

    Legal-entity transfers (``TRANSFER FROM …``) become ``Transfer`` events —
    never Buy/Sell. Stock splits become ``Split``. Cash top-ups/withdrawals
    become Deposit/Withdrawal.
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

        type_raw = (row.get("Type") or "").strip()
        event_type = _map_event_type(type_raw)
        if event_type is None:
            continue

        dt = parse_flexible_datetime(
            row["Date"],
            default_tz=get_settings().statement_timezone,
        )
        ticker = empty_to_none(row.get("Ticker"))
        qty = parse_decimal_optional(row.get("Quantity"))

        price, _ = parse_money_with_currency(
            row.get("Price per share"),
            default_currency=empty_to_none(row.get("Currency")),
        )
        value, value_ccy = parse_money_with_currency(
            row.get("Total Amount"),
            default_currency=empty_to_none(row.get("Currency")),
        )
        currency = (
            empty_to_none(row.get("Currency")) or value_ccy or "USD"
        ).upper()

        fees = Decimal("0")
        # Custody fee amounts are negative in Total Amount
        if event_type == InvestmentEventType.FEE and value is not None:
            fees = abs(value)

        side = None
        asset_class: AssetClass | None
        if event_type in {InvestmentEventType.BUY, InvestmentEventType.SELL}:
            side = TradeSide.BUY if event_type == InvestmentEventType.BUY else TradeSide.SELL
            asset_class = AssetClass.STOCK
        elif event_type in {
            InvestmentEventType.DEPOSIT,
            InvestmentEventType.WITHDRAWAL,
            InvestmentEventType.FEE,
        }:
            asset_class = AssetClass.CASH if not ticker else AssetClass.STOCK
        elif event_type == InvestmentEventType.SPLIT:
            asset_class = AssetClass.STOCK
        elif event_type == InvestmentEventType.TRANSFER:
            asset_class = AssetClass.STOCK if ticker else AssetClass.OTHER
        else:
            asset_class = AssetClass.OTHER

        event_id = uuid4()
        lot_id = None
        # Only market buys open lots; transfers/splits never invent cost basis here.
        if (
            event_type == InvestmentEventType.BUY
            and ticker
            and qty is not None
            and qty > 0
        ):
            cost = value if value is not None else Decimal("0")
            lot = open_lot_from_buy(
                account_id=account_id,
                ticker=ticker,
                asset_class=AssetClass.STOCK,
                source="Revolut",
                acquisition_date=dt.date(),
                quantity=qty,
                cost_native=cost,
                native_currency=currency,
                open_event_id=event_id,
                now=ts,
            )
            lots.append(lot)
            lot_id = lot.id

        fx_rate = parse_decimal_optional(row.get("FX Rate"))
        notes = None
        if fx_rate is not None:
            notes = f"fx_rate={fx_rate}"
        if event_type == InvestmentEventType.TRANSFER:
            notes = (notes + "; " if notes else "") + "legal_entity_transfer"

        original = "|".join(
            [
                str(row.get("Date") or ""),
                ticker or "",
                type_raw,
                str(row.get("Quantity") or ""),
                str(row.get("Price per share") or ""),
                str(row.get("Total Amount") or ""),
                currency,
            ]
        )

        fees_for_event = fees if event_type == InvestmentEventType.FEE else Decimal("0")
        external_id = revolut_event_external_id(
            event_type=event_type.value,
            ticker=ticker,
            event_datetime=dt,
            quantity=qty,
            value_native=value,
            fees_native=fees_for_event,
            currency=currency,
        )

        events.append(
            InvestmentEvent(
                id=event_id,
                account_id=account_id,
                event_type=event_type,
                event_date=dt.date(),
                event_datetime=dt,
                ticker=ticker,
                asset_class=asset_class,
                side=side,
                quantity=qty,
                price_native=price,
                native_currency=currency,
                value_native=value,
                fees_native=fees_for_event,
                value_usd=value if currency == "USD" else None,
                value_czk=value if currency == "CZK" else None,
                lot_id=lot_id,
                source="Revolut",
                external_id=external_id,
                description=type_raw if not ticker else f"{type_raw} {ticker}",
                original_description=original,
                source_file_id=source_file_id,
                original_file_hash=file_hash,
                notes=notes,
                created_at=ts,
                updated_at=ts,
            )
        )

    return ParseResult(
        parser_key=ParserKey.REVOLUT_STOCKS.value,
        institution="Revolut",
        row_count=data_rows,
        investment_events=events,
        investment_lots=lots,
    )


def parse_revolut_stocks_bytes(
    file_bytes: bytes,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    from backend.parsers.detect import decode_statement_text

    return parse_revolut_stocks(
        decode_statement_text(file_bytes),
        account_ids=account_ids,
        source_file_id=source_file_id,
        file_hash=file_hash,
        now=now,
    )
