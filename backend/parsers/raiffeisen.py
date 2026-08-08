"""Raiffeisenbank CZ CSV parser (semicolon, Czech dates)."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from backend.common.money import parse_decimal
from backend.common.timeutil import parse_czech_date, utc_now
from backend.parsers.base import ParseResult, empty_to_none, resolve_account_id
from backend.schema.models import ParserKey, Transaction


def _clean_header(name: str) -> str:
    return (name or "").replace("\ufeff", "").strip()


def _unique_headers(headers: list[str]) -> list[str]:
    """
    Make duplicate Raiffeisen headers unique.

    Real files repeat ``Note`` and ``Original Amount and Currency``.
    First Note keeps name ``Note``; later ones become ``Note_2``, …
    """
    seen: dict[str, int] = {}
    out: list[str] = []
    for h in headers:
        base = _clean_header(h)
        n = seen.get(base, 0) + 1
        seen[base] = n
        out.append(base if n == 1 else f"{base}_{n}")
    return out


def _row_get(row: dict[str, str], *names: str) -> str:
    """Get first non-empty field among possible header names."""
    wanted = {n.lower() for n in names}
    # Prefer first match among renamed keys (Note before Note_2)
    for key in sorted(row.keys(), key=lambda k: (k.lower(), k)):
        clean = _clean_header(key).lower()
        # strip _2 suffix for matching preferred names only when exact
        base = clean.rsplit("_", 1)[0] if clean[-1:].isdigit() and "_" in clean else clean
        # only map numeric suffixes like note_2
        if clean in wanted or base in wanted:
            val = row.get(key) or ""
            if val.strip():
                return val
    for name in names:
        for key, val in row.items():
            if _clean_header(key).lower() == name.lower() and (val or "").strip():
                return val or ""
    return ""


def _iter_raiffeisen_rows(text: str) -> list[dict[str, str]]:
    stream = io.StringIO(text)
    reader = csv.reader(stream, delimiter=";")
    try:
        header = next(reader)
    except StopIteration:
        return []
    fields = _unique_headers(header)
    rows: list[dict[str, str]] = []
    for raw in reader:
        if not raw or not any((c or "").strip() for c in raw):
            continue
        # pad / trim to header length
        if len(raw) < len(fields):
            raw = raw + [""] * (len(fields) - len(raw))
        row = {fields[i]: raw[i] for i in range(len(fields))}
        rows.append(row)
    return rows


def parse_raiffeisen(
    text: str,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    """
    Parse Raiffeisen statement CSV text into :class:`Transaction` rows.

    Header includes duplicated ``Original Amount and Currency`` and ``Note``
    columns; duplicates are renamed (``Note``, ``Note_2``, …).
    """
    ts = now or utc_now()
    transactions: list[Transaction] = []
    data_rows = 0

    for row in _iter_raiffeisen_rows(text):
        data_rows += 1

        booking_raw = _row_get(row, "Booking Date")
        tx_date_raw = _row_get(row, "Transaction Date")
        if not booking_raw and not tx_date_raw:
            continue

        booking_date = parse_czech_date(booking_raw or tx_date_raw)
        value_date = parse_czech_date(tx_date_raw) if tx_date_raw else booking_date

        amount = parse_decimal(_row_get(row, "Booked amount") or "0")
        currency = (_row_get(row, "Account Currency") or "CZK").strip().upper() or "CZK"
        fee_raw = _row_get(row, "Fee")
        try:
            fee_amount = parse_decimal(fee_raw) if fee_raw.strip() else Decimal("0")
        except ValueError:
            fee_amount = Decimal("0")

        merchant = empty_to_none(_row_get(row, "Merchant"))
        message = empty_to_none(_row_get(row, "Message"))
        # Prefer first Note (statement note); fall back to Note_2 if needed
        note = empty_to_none(_row_get(row, "Note", "Note_2"))
        tx_type = empty_to_none(_row_get(row, "Transaction type"))
        category = empty_to_none(_row_get(row, "Transaction Category"))

        description_parts = [p for p in (tx_type, message, merchant) if p]
        description = " — ".join(dict.fromkeys(description_parts)) or None
        original_description = message or note or tx_type

        account_id = resolve_account_id(account_ids, currency=currency)

        # amount_czk when already CZK
        amount_czk = amount if currency == "CZK" else None

        transactions.append(
            Transaction(
                id=uuid4(),
                account_id=account_id,
                booking_date=booking_date,
                value_date=value_date,
                amount=amount,
                currency=currency,
                amount_czk=amount_czk,
                amount_usd=None,
                fee_amount=fee_amount,
                fee_currency=currency if fee_amount != 0 else currency,
                merchant=merchant,
                description=description,
                original_description=original_description,
                source_institution="Raiffeisen",
                external_id=empty_to_none(_row_get(row, "Transaction ID")),
                counterparty_account=empty_to_none(
                    _row_get(row, "Accocunt Number", "Account Number")
                ),
                counterparty_name=empty_to_none(_row_get(row, "Name of Account")),
                category_id=None,
                is_internal_transfer=False,
                transfer_group_id=None,
                original_file_hash=file_hash,
                source_file_id=source_file_id,
                notes=category,
                created_at=ts,
                updated_at=ts,
            )
        )

    return ParseResult(
        parser_key=ParserKey.RAIFFEISEN_CZ.value,
        institution="Raiffeisen",
        row_count=data_rows,
        transactions=transactions,
    )


def parse_raiffeisen_bytes(
    file_bytes: bytes,
    *,
    account_ids: Mapping[str, UUID],
    source_file_id: UUID | None = None,
    file_hash: str | None = None,
    now: datetime | None = None,
) -> ParseResult:
    from backend.parsers.detect import decode_statement_text

    return parse_raiffeisen(
        decode_statement_text(file_bytes),
        account_ids=account_ids,
        source_file_id=source_file_id,
        file_hash=file_hash,
        now=now,
    )
