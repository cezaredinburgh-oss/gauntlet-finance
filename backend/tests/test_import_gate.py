from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.common.hashing import sha256_hex
from backend.parsers.import_file import parse_statement_bytes
from backend.schema.models import StatementFile, StatementFileStatus

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_statement_bytes_auto_detect_and_idempotent():
    path = FIXTURES / "raiffeisen_sample.csv"
    data = path.read_bytes()
    account_id = uuid4()
    accounts = {"CZK": account_id, "default": account_id}

    first = parse_statement_bytes(
        data,
        account_ids=accounts,
        filename=path.name,
    )
    assert first.status == "parsed"
    assert first.parser_key == "raiffeisen_cz"
    assert first.institution == "Raiffeisen"
    assert first.content_sha256 == sha256_hex(data)
    assert len(first.transactions) == 4
    assert first.row_count == 4

    second = parse_statement_bytes(
        data,
        account_ids=accounts,
        existing_hashes={first.content_sha256},
    )
    assert second.status == "already_imported"
    assert second.message == "already imported"
    assert second.transactions == []
    assert second.investment_events == []
    assert second.investment_lots == []


def test_already_imported_from_statement_file_rows():
    path = FIXTURES / "etoro_sample.csv"
    data = path.read_bytes()
    h = sha256_hex(data)
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    existing = [
        StatementFile(
            id=uuid4(),
            original_filename="etoro_activity_import.csv",
            uploaded_at=now,
            content_sha256=h,
            institution="eToro",
            row_count=4,
            parser_key="etoro_activity",
            status=StatementFileStatus.IMPORTED,
            created_at=now,
            updated_at=now,
        )
    ]
    result = parse_statement_bytes(
        data,
        account_ids={"default": uuid4()},
        existing_statement_files=existing,
    )
    assert result.status == "already_imported"


def test_revolut_stocks_via_top_level():
    data = (FIXTURES / "revolut_stocks_sample.csv").read_bytes()
    result = parse_statement_bytes(
        data,
        account_ids={"default": uuid4()},
    )
    assert result.status == "parsed"
    assert result.parser_key == "revolut_stocks"
    assert any(e.ticker == "PATH" for e in result.investment_events)
