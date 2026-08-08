"""
Top-level pure import entrypoint: hash gate + auto-detect + parse.

No Google Sheets I/O — call from FastAPI later with repo persistence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping
from uuid import UUID, uuid4

from backend.common.hashing import sha256_hex
from backend.common.timeutil import utc_now
from backend.parsers.base import ImportGateResult
from backend.parsers.detect import (
    decode_statement_text,
    detect_parser_key,
    institution_for_parser_key,
)
from backend.parsers.etoro import parse_etoro
from backend.parsers.etoro_account_statement import parse_etoro_account_statement_bytes
from backend.parsers.raiffeisen import parse_raiffeisen
from backend.parsers.revolut_crypto import parse_revolut_crypto
from backend.parsers.revolut_expenses import parse_revolut_expenses
from backend.parsers.revolut_stocks import parse_revolut_stocks
from backend.schema.models import ParserKey, StatementFile, StatementFileStatus


def existing_hashes_from_statement_files(
    rows: Iterable[StatementFile],
) -> set[str]:
    """Collect non-archived content hashes (Imported or any stored hash)."""
    out: set[str] = set()
    for row in rows:
        if row.archived:
            continue
        if row.content_sha256:
            out.add(row.content_sha256.lower())
    return out


def parse_statement_bytes(
    file_bytes: bytes,
    *,
    account_ids: Mapping[str, UUID],
    existing_hashes: Iterable[str] | None = None,
    existing_statement_files: Iterable[StatementFile] | None = None,
    filename: str = "upload.csv",
    source_file_id: UUID | None = None,
    now: datetime | None = None,
) -> ImportGateResult:
    """
    Hash → idempotency gate → detect → parse.

    Parameters
    ----------
    account_ids:
        Map of currency code or ``default`` → Accounts.id UUID.
    existing_hashes:
        SHA-256 hex strings already present in StatementFiles.
    existing_statement_files:
        Optional full StatementFile rows; hashes are unioned with
        ``existing_hashes``.
    source_file_id:
        If provided, stamped on produced rows; otherwise a new UUID is used
        for the proposed StatementFile only (row FKs still set when parsed).
    """
    ts = now or utc_now()
    content_hash = sha256_hex(file_bytes)

    known: set[str] = set()
    if existing_hashes:
        known.update(h.lower() for h in existing_hashes)
    if existing_statement_files is not None:
        known |= existing_hashes_from_statement_files(existing_statement_files)

    if content_hash.lower() in known:
        return ImportGateResult(
            status="already_imported",
            content_sha256=content_hash,
            message="already imported",
        )

    parser_key = detect_parser_key(file_bytes)
    institution = institution_for_parser_key(parser_key)
    file_id = source_file_id or uuid4()

    parse_kwargs = dict(
        account_ids=account_ids,
        source_file_id=file_id,
        file_hash=content_hash,
        now=ts,
    )

    # Binary xlsx parsers receive raw bytes; CSV parsers receive decoded text
    if parser_key == ParserKey.ETORO_ACCOUNT_STATEMENT.value:
        result = parse_etoro_account_statement_bytes(file_bytes, **parse_kwargs)
    elif parser_key == ParserKey.RAIFFEISEN_CZ.value:
        result = parse_raiffeisen(decode_statement_text(file_bytes), **parse_kwargs)
    elif parser_key == ParserKey.REVOLUT_EXPENSES.value:
        result = parse_revolut_expenses(decode_statement_text(file_bytes), **parse_kwargs)
    elif parser_key == ParserKey.REVOLUT_CRYPTO.value:
        result = parse_revolut_crypto(decode_statement_text(file_bytes), **parse_kwargs)
    elif parser_key == ParserKey.REVOLUT_STOCKS.value:
        result = parse_revolut_stocks(decode_statement_text(file_bytes), **parse_kwargs)
    elif parser_key == ParserKey.ETORO_ACTIVITY.value:
        result = parse_etoro(decode_statement_text(file_bytes), **parse_kwargs)
    else:
        raise ValueError(f"no parser registered for {parser_key!r}")

    return ImportGateResult(
        status="parsed",
        content_sha256=content_hash,
        parser_key=result.parser_key,
        institution=result.institution,
        row_count=result.row_count,
        transactions=result.transactions,
        investment_events=result.investment_events,
        investment_lots=result.investment_lots,
        message="ok",
    )


def build_statement_file_row(
    *,
    filename: str,
    content_sha256: str,
    institution: str,
    row_count: int,
    parser_key: str,
    status: StatementFileStatus = StatementFileStatus.IMPORTED,
    now: datetime | None = None,
    statement_id: UUID | None = None,
) -> StatementFile:
    """Helper for the next phase to persist a StatementFiles row."""
    ts = now or utc_now()
    return StatementFile(
        id=statement_id or uuid4(),
        original_filename=filename,
        uploaded_at=ts,
        content_sha256=content_sha256,
        institution=institution,
        row_count=row_count,
        parser_key=parser_key,
        status=status,
        created_at=ts,
        updated_at=ts,
    )
