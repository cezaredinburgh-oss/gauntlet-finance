from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from backend.parsers.etoro import parse_etoro
from backend.schema.models import AssetClass, InvestmentEventType

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_etoro_buy_commission_capitalized_into_lot():
    text = (FIXTURES / "etoro_sample.csv").read_text(encoding="utf-8")
    account_id = uuid4()
    result = parse_etoro(
        text,
        account_ids={"default": account_id},
        file_hash="e" * 64,
    )
    assert result.parser_key == "etoro_activity"
    assert result.row_count == 4

    types = [e.event_type for e in result.investment_events]
    assert InvestmentEventType.STAKING_REWARD in types
    assert InvestmentEventType.DEPOSIT in types
    assert InvestmentEventType.BUY in types
    assert InvestmentEventType.FEE in types

    buy = next(e for e in result.investment_events if e.event_type == InvestmentEventType.BUY)
    assert buy.ticker == "SPCX"
    assert buy.quantity == Decimal("9")
    assert buy.asset_class == AssetClass.STOCK

    fee = next(e for e in result.investment_events if e.event_type == InvestmentEventType.FEE)
    assert fee.parent_event_id == buy.id
    assert fee.value_native == Decimal("-1.00")

    spcx_lot = next(lot for lot in result.investment_lots if lot.ticker == "SPCX")
    # 1088.60 + 1.00 commission
    assert spcx_lot.cost_basis_native == Decimal("1089.60")
    assert spcx_lot.cost_basis_usd == Decimal("1089.60")

    ada = next(
        e
        for e in result.investment_events
        if e.event_type == InvestmentEventType.STAKING_REWARD
    )
    assert ada.ticker == "ADA"
    assert ada.asset_class == AssetClass.CRYPTO
