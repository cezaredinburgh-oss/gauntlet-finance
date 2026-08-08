from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from backend.parsers.detect import detect_institution, detect_parser_key
from backend.parsers.etoro_account_statement import (
    is_etoro_account_statement_xlsx,
    parse_etoro_account_statement_bytes,
)
from backend.parsers.import_file import parse_statement_bytes
from backend.schema.models import AssetClass, InvestmentEventType, ParserKey

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "etoro_account_statement_sample.xlsx"


def test_detect_etoro_xlsx():
    data = SAMPLE.read_bytes()
    assert data[:2] == b"PK"
    assert is_etoro_account_statement_xlsx(data)
    assert detect_parser_key(data) == ParserKey.ETORO_ACCOUNT_STATEMENT.value
    assert detect_institution(data) == "eToro"


def test_parse_etoro_account_statement_core_types():
    data = SAMPLE.read_bytes()
    account_id = uuid4()
    result = parse_etoro_account_statement_bytes(
        data,
        account_ids={"default": account_id, "USD": account_id},
        file_hash="a" * 64,
    )
    assert result.parser_key == ParserKey.ETORO_ACCOUNT_STATEMENT.value
    assert result.institution == "eToro"
    assert result.row_count >= 8

    by_type = {}
    for e in result.investment_events:
        by_type.setdefault(e.event_type, []).append(e)

    assert InvestmentEventType.DEPOSIT in by_type
    assert InvestmentEventType.BUY in by_type
    assert InvestmentEventType.SELL in by_type
    assert InvestmentEventType.STAKING_REWARD in by_type
    assert InvestmentEventType.FEE in by_type
    assert InvestmentEventType.WITHDRAWAL in by_type

    buy = next(
        e
        for e in result.investment_events
        if e.event_type == InvestmentEventType.BUY and e.ticker == "ARKF"
    )
    assert buy.quantity == Decimal("7.358501")
    assert buy.value_native == Decimal("400")
    assert buy.asset_class == AssetClass.OTHER  # CFD
    # day-first: 2 Nov 2021 not 11 Feb
    assert buy.event_date.month == 11
    assert buy.event_date.day == 2

    sell = next(e for e in result.investment_events if e.event_type == InvestmentEventType.SELL)
    assert sell.ticker == "ARKF"
    assert sell.quantity == Decimal("7.358501")

    staking = next(
        e for e in result.investment_events if e.event_type == InvestmentEventType.STAKING_REWARD
    )
    assert staking.ticker == "SOL"
    assert staking.asset_class == AssetClass.CRYPTO

    # Spread fee capitalized into ARKF lot
    arkf_lot = next(lot for lot in result.investment_lots if lot.ticker == "ARKF")
    assert arkf_lot.cost_basis_native == Decimal("401")  # 400 + 1 spread
    assert arkf_lot.quantity_opened == Decimal("7.358501")

    tsla = next(
        e
        for e in result.investment_events
        if e.event_type == InvestmentEventType.BUY and e.ticker == "TSLA"
    )
    assert tsla.asset_class == AssetClass.STOCK


def test_import_gate_accepts_xlsx():
    data = SAMPLE.read_bytes()
    account_id = uuid4()
    gate = parse_statement_bytes(
        data,
        account_ids={"default": account_id, "USD": account_id},
        filename="etoro-account-statement.xlsx",
    )
    assert gate.status == "parsed"
    assert gate.parser_key == ParserKey.ETORO_ACCOUNT_STATEMENT.value
    assert gate.row_count >= 8
    assert len(gate.investment_events) >= 8
