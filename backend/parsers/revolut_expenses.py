"""Revolut daily expenses (multi-currency cash) CSV parser."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from backend.common.money import parse_decimal
from backend.common.timeutil import parse_flexible_datetime, utc_now
from backend.parsers.base import ParseResult, empty_to_none, resolve_account_id
from backend.schema.models import ParserKey, Transaction

# Only COMPLETED rows hit the ledger; REVERTED etc. are skipped.
_IMPORTABLE_STATES = {"COMPLETED"}


def _revolut_row_external_id(row: dict[str, str], amount: Decimal, fee: Decimal, currency: str) -> str:
    """
    Stable per-row id so same-day identical FX amounts stay distinct.

    Uses type, product, started/completed timestamps, description, amount,
    fee, currency, and state. Balance is intentionally omitted — export
    windows can show different running balances for the same logical row.
    """
    blob = "|".join(
        [
            (row.get("Type") or "").strip(),
            (row.get("Product") or "").strip(),
            (row.get("Started Date") or "").strip(),
            (row.get("Completed Date") or "").strip(),
            (row.get("Description") or "").strip(),
            format(amount, "f"),
            format(fee, "f"),
            currency,
            (row.get("State") or "").strip(),
        ]
    )
    return "rev:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def parse_revolut_expenses(
    text: str,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
    include_non_completed: bool = False,
) -> ParseResult:
    """
    Parse Revolut account statement expenses CSV into Transactions.

    ``account_ids`` should map ISO currency → account UUID (and/or ``default``).
    """
    ts = now or utc_now()
    reader = csv.DictReader(io.StringIO(text))
    transactions: list[Transaction] = []
    data_rows = 0

    for row in reader:
        if not row or not any((v or "").strip() for v in row.values()):
            continue
        data_rows += 1

        state = (row.get("State") or "").strip().upper()
        if not include_non_completed and state not in _IMPORTABLE_STATES:
            continue

        completed = empty_to_none(row.get("Completed Date"))
        started = empty_to_none(row.get("Started Date"))
        if not completed and not started:
            continue

        booking_dt = parse_flexible_datetime(completed or started)  # type: ignore[arg-type]
        value_dt = parse_flexible_datetime(started) if started else booking_dt

        currency = (row.get("Currency") or "").strip().upper()
        if len(currency) != 3:
            raise ValueError(f"invalid currency on Revolut expenses row: {currency!r}")

        amount = parse_decimal(row.get("Amount") or "0")
        fee_raw = row.get("Fee") or "0"
        fee_amount = parse_decimal(fee_raw) if str(fee_raw).strip() else Decimal("0")

        description = empty_to_none(row.get("Description"))
        tx_type = empty_to_none(row.get("Type"))
        product = empty_to_none(row.get("Product"))

        # Heuristic merchant: description for card payments
        merchant = description if tx_type in {"Card Payment", "ATM", "Rev Payment"} else None

        account_id = resolve_account_id(account_ids, currency=currency)
        amount_czk = amount if currency == "CZK" else None
        amount_usd = amount if currency == "USD" else None

        notes_parts = [p for p in (tx_type, product, state) if p]
        # Preserve full timestamps for audit (booking_date is date-only)
        notes_parts.append(f"completed={booking_dt.isoformat()}")
        if value_dt != booking_dt:
            notes_parts.append(f"started={value_dt.isoformat()}")
        bal = empty_to_none(row.get("Balance"))
        if bal is not None:
            notes_parts.append(f"balance={bal}")
        notes = " | ".join(notes_parts) if notes_parts else None

        external_id = _revolut_row_external_id(row, amount, fee_amount, currency)

        transactions.append(
            Transaction(
                id=uuid4(),
                account_id=account_id,
                booking_date=booking_dt.date(),
                value_date=value_dt.date(),
                amount=amount,
                currency=currency,
                amount_czk=amount_czk,
                amount_usd=amount_usd,
                fee_amount=fee_amount,
                fee_currency=currency,
                merchant=merchant,
                description=description or tx_type,
                original_description=description,
                source_institution="Revolut",
                external_id=external_id,
                counterparty_account=None,
                counterparty_name=None,
                is_internal_transfer=False,
                original_file_hash=file_hash,
                source_file_id=source_file_id,
                notes=notes,
                created_at=ts,
                updated_at=ts,
            )
        )

    return ParseResult(
        parser_key=ParserKey.REVOLUT_EXPENSES.value,
        institution="Revolut",
        row_count=data_rows,
        transactions=transactions,
    )


def parse_revolut_expenses_bytes(
    file_bytes: bytes,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    from backend.parsers.detect import decode_statement_text

    return parse_revolut_expenses(
        decode_statement_text(file_bytes),
        account_ids=account_ids,
        source_file_id=source_file_id,
        file_hash=file_hash,
        now=now,
    )
