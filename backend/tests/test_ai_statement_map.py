"""Tests for AI cash statement column mapping (mocked Grok)."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from backend.config import Settings
from backend.services import ai_quota, ai_statement_map
from backend.services.ai_client import ChatResult
from backend.services.ai_statement_map import (
    ColumnMap,
    apply_mapping_to_bytes,
    extract_csv_table,
    is_unknown_format_error,
    map_statement_bytes,
)


@pytest.fixture(autouse=True)
def _reset_quota():
    ai_quota.reset_for_tests()
    yield
    ai_quota.reset_for_tests()


def _settings(**kwargs) -> Settings:
    base = dict(
        app_env="test",
        ai_enabled=True,
        xai_api_key="test-key",
        ai_model="grok-4.3",
        ai_daily_token_cap=100_000,
        ai_global_daily_token_cap=500_000,
    )
    base.update(kwargs)
    return Settings(**base)


SAMPLE_CSV = (
    "Datum;Castka;Mena;Popis\n"
    "01.08.2026;-120,50;CZK;Lidl Praha\n"
    "02.08.2026;-45,00;CZK;Cafe Nova\n"
    "03.08.2026;1500,00;CZK;Salary\n"
).encode("utf-8")


def test_is_unknown_format_error():
    assert is_unknown_format_error(
        "unrecognized statement format; header scores={'a': 1}"
    )
    assert not is_unknown_format_error("Sheets API quota exceeded")


def test_extract_csv_table():
    t = extract_csv_table(SAMPLE_CSV)
    assert t.delimiter == ";"
    assert "Datum" in t.headers
    assert t.row_count == 3
    assert len(t.rows) == 3


def test_apply_mapping_parses_rows():
    mapping = ColumnMap(
        institution="TestBank",
        default_currency="CZK",
        amount_sign="as_is",
        columns={
            "Datum": "booking_date",
            "Castka": "amount",
            "Mena": "currency",
            "Popis": "merchant",
        },
        confidence=0.9,
    )
    acc = {"default": uuid4(), "CZK": uuid4(), "USD": uuid4()}
    parsed = apply_mapping_to_bytes(SAMPLE_CSV, mapping, account_ids=acc)
    assert parsed.parser_key == "ai_cash_map"
    assert parsed.row_count == 3
    assert len(parsed.transactions) == 3
    # Czech decimal + expense negative
    amounts = sorted(float(t.amount) for t in parsed.transactions)
    assert amounts[0] == pytest.approx(-120.50)
    assert any(t.merchant and "Lidl" in t.merchant for t in parsed.transactions)


def test_map_statement_with_mock_chat():
    def fake_chat(**kwargs) -> ChatResult:
        body = {
            "institution": "TestBank",
            "default_currency": "CZK",
            "amount_sign": "as_is",
            "columns": {
                "Datum": "booking_date",
                "Castka": "amount",
                "Mena": "currency",
                "Popis": "merchant",
            },
            "confidence": 0.88,
            "notes": "ok",
        }
        return ChatResult(
            content=json.dumps(body),
            prompt_tokens=200,
            completion_tokens=80,
            total_tokens=280,
            model="grok-4.3",
        )

    r = map_statement_bytes(
        SAMPLE_CSV,
        principal="e:map@x",
        settings=_settings(),
        chat_fn=fake_chat,
    )
    assert r.configured is True
    assert r.mapping is not None
    assert r.mapping.columns["Datum"] == "booking_date"
    assert len(r.preview) >= 1
    assert r.tokens_used == 280


def test_xlsx_rejected():
    with pytest.raises(ValueError, match="xlsx"):
        extract_csv_table(b"PK\x03\x04fake")
