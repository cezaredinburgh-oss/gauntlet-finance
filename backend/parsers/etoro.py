"""eToro activity CSV parser."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from backend.common.money import parse_decimal_optional
from backend.common.timeutil import parse_flexible_date, utc_now
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


def _map_event_type(raw: str) -> InvestmentEventType | None:
    t = (raw or "").strip().lower()
    mapping = {
        "buy": InvestmentEventType.BUY,
        "sell": InvestmentEventType.SELL,
        "staking reward": InvestmentEventType.STAKING_REWARD,
        "deposit": InvestmentEventType.DEPOSIT,
        "withdrawal": InvestmentEventType.WITHDRAWAL,
        "commission": InvestmentEventType.FEE,
        "fee": InvestmentEventType.FEE,
        "transfer": InvestmentEventType.TRANSFER,
        "split": InvestmentEventType.SPLIT,
        "stake": InvestmentEventType.STAKE,
    }
    return mapping.get(t)


def _map_asset_class(raw: str | None) -> AssetClass | None:
    if not raw:
        return None
    t = raw.strip().lower()
    if t in {"stocks", "stock"}:
        return AssetClass.STOCK
    if t in {"crypto", "cryptocurrency"}:
        return AssetClass.CRYPTO
    if t in {"cash"}:
        return AssetClass.CASH
    if t in {"etf", "etfs"}:
        return AssetClass.ETF
    return AssetClass.OTHER


def parse_etoro(
    text: str,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    """
    Parse eToro activity import CSV.

    Commission rows become Fee events; when a matching Buy for the same ticker
    appears earlier in the file, ``parent_event_id`` points at that Buy and the
    fee is capitalized into the open lot cost basis.
    """
    ts = now or utc_now()
    reader = csv.DictReader(io.StringIO(text))
    events: list[InvestmentEvent] = []
    lots = []
    data_rows = 0
    account_id = resolve_account_id(account_ids, currency=None)

    # ticker -> last buy event id / lot for fee capitalization within this file
    last_buy: dict[str, tuple[UUID, int]] = {}  # ticker -> (event_id, lot_index)

    for row in reader:
        if not row or not any((v or "").strip() for v in row.values()):
            continue
        data_rows += 1

        type_raw = row.get("EventType") or ""
        event_type = _map_event_type(type_raw)
        if event_type is None:
            continue

        event_date = parse_flexible_date(row["Date"])
        ticker = empty_to_none(row.get("Ticker"))
        asset_class = _map_asset_class(row.get("Class"))
        side_raw = empty_to_none(row.get("Side"))
        side = None
        if side_raw:
            if side_raw.lower() == "buy":
                side = TradeSide.BUY
            elif side_raw.lower() == "sell":
                side = TradeSide.SELL

        units = parse_decimal_optional(row.get("Units"))
        price = parse_decimal_optional(row.get("PriceNative"))
        value = parse_decimal_optional(row.get("ValueNative"))
        fees = parse_decimal_optional(row.get("FeesNative")) or Decimal("0")
        currency = (empty_to_none(row.get("Currency")) or "USD").upper()
        comments = empty_to_none(row.get("Comments"))
        platform = empty_to_none(row.get("Platform")) or "eToro"

        event_id = uuid4()
        parent_event_id = None
        lot_id = None

        if event_type in {InvestmentEventType.BUY, InvestmentEventType.STAKING_REWARD}:
            if ticker and units is not None and units > 0:
                cost = (value or Decimal("0")) + fees
                # price 0 / empty still ok for rewards with value
                lot = open_lot_from_buy(
                    account_id=account_id,
                    ticker=ticker,
                    asset_class=asset_class or AssetClass.OTHER,
                    source="eToro",
                    acquisition_date=event_date,
                    quantity=units,
                    cost_native=cost,
                    native_currency=currency,
                    open_event_id=event_id,
                    now=ts,
                    notes=comments,
                )
                lots.append(lot)
                lot_id = lot.id
                if event_type == InvestmentEventType.BUY:
                    last_buy[ticker] = (event_id, len(lots) - 1)

        elif event_type == InvestmentEventType.FEE and ticker:
            if ticker in last_buy:
                parent_event_id, lot_idx = last_buy[ticker]
                # Capitalize commission into lot (value often negative)
                fee_abs = abs(value) if value is not None else fees
                lot = lots[lot_idx]
                new_native = lot.cost_basis_native + fee_abs
                from backend.parsers.base import placeholder_basis

                n, czk, usd = placeholder_basis(new_native, lot.native_currency)
                lots[lot_idx] = lot.model_copy(
                    update={
                        "cost_basis_native": n,
                        "cost_basis_czk": czk,
                        "cost_basis_usd": usd,
                        "updated_at": ts,
                        "notes": ((lot.notes or "") + f"; +commission {fee_abs}").strip(
                            "; "
                        ),
                    }
                )

        if event_type == InvestmentEventType.BUY:
            side = side or TradeSide.BUY
        elif event_type == InvestmentEventType.SELL:
            side = side or TradeSide.SELL
        elif event_type == InvestmentEventType.STAKING_REWARD:
            side = side or TradeSide.BUY

        events.append(
            InvestmentEvent(
                id=event_id,
                account_id=account_id,
                event_type=event_type,
                event_date=event_date,
                event_datetime=None,
                ticker=ticker,
                asset_class=asset_class,
                side=side,
                quantity=units,
                price_native=price,
                native_currency=currency,
                value_native=value,
                fees_native=fees,
                value_usd=value if currency == "USD" else None,
                value_czk=value if currency == "CZK" else None,
                lot_id=lot_id,
                parent_event_id=parent_event_id,
                source=platform,
                description=comments or type_raw,
                original_description=comments,
                external_id=None,
                source_file_id=source_file_id,
                original_file_hash=file_hash,
                created_at=ts,
                updated_at=ts,
            )
        )

    return ParseResult(
        parser_key=ParserKey.ETORO_ACTIVITY.value,
        institution="eToro",
        row_count=data_rows,
        investment_events=events,
        investment_lots=lots,
    )


def parse_etoro_bytes(
    file_bytes: bytes,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    from backend.parsers.detect import decode_statement_text

    return parse_etoro(
        decode_statement_text(file_bytes),
        account_ids=account_ids,
        source_file_id=source_file_id,
        file_hash=file_hash,
        now=now,
    )
