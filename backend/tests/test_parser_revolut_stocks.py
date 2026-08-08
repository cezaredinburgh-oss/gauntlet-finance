from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.engines.statements import StatementService
from backend.parsers.revolut_stocks import parse_revolut_stocks
from backend.schema.models import InvestmentEventType

FIXTURES = Path(__file__).parent / "fixtures"
BANK = Path(__file__).resolve().parents[2] / "Bank statements"


def test_parse_revolut_stocks_types_and_no_transfer_as_buy():
    text = (FIXTURES / "revolut_stocks_sample.csv").read_text(encoding="utf-8")
    account_id = uuid4()
    result = parse_revolut_stocks(
        text,
        account_ids={"default": account_id},
        file_hash="d" * 64,
    )
    assert result.parser_key == "revolut_stocks"
    assert result.row_count == 6

    by_type = {}
    for e in result.investment_events:
        by_type.setdefault(e.event_type, []).append(e)

    assert len(by_type[InvestmentEventType.DEPOSIT]) == 1
    assert by_type[InvestmentEventType.DEPOSIT][0].value_native == Decimal("1290.48")

    buy = by_type[InvestmentEventType.BUY][0]
    assert buy.ticker == "PLTR"
    assert buy.quantity == Decimal("44")
    assert buy.price_native == Decimal("22.36")
    assert buy.value_native == Decimal("986.26")
    assert buy.external_id and buy.external_id.startswith("ext:Revolut:")

    sell = by_type[InvestmentEventType.SELL][0]
    assert sell.ticker == "VALE"
    assert sell.quantity == Decimal("84")

    fee = by_type[InvestmentEventType.FEE][0]
    assert fee.value_native == Decimal("-0.63")

    split = by_type[InvestmentEventType.SPLIT][0]
    assert split.ticker == "TSLA"
    assert split.quantity == Decimal("9.75677344")

    xfer = by_type[InvestmentEventType.TRANSFER][0]
    assert xfer.ticker == "PATH"
    assert xfer.event_type == InvestmentEventType.TRANSFER
    assert xfer.side is None
    assert "legal_entity_transfer" in (xfer.notes or "")

    # Only BUY opens a lot
    assert len(result.investment_lots) == 1
    assert result.investment_lots[0].ticker == "PLTR"
    assert result.investment_lots[0].quantity_opened == Decimal("44")

    assert all(
        e.external_id and e.external_id.startswith("ext:Revolut:")
        for e in result.investment_events
    )


def test_stocks_tax_year_after_all_time_dedupes_heavily():
    """Golden: tax-year stocks after all-time stocks should drop nearly all overlap."""
    all_time = BANK / "All time stocks revolut.csv"
    tax = BANK / "Tax year test Revolut stocks_.csv"
    if not all_time.is_file() or not tax.is_file():
        pytest.skip("Bank statements fixtures not present")

    acc = uuid4()
    existing = parse_revolut_stocks(
        all_time.read_text(encoding="utf-8-sig"),
        account_ids={"default": acc},
        file_hash="1" * 64,
    ).investment_events
    incoming = parse_revolut_stocks(
        tax.read_text(encoding="utf-8-sig"),
        account_ids={"default": acc},
        file_hash="2" * 64,
    ).investment_events
    assert incoming, "tax-year stocks fixture produced no events"
    result = StatementService.dedupe_events(existing, incoming)
    drop_rate = result.dropped_events / len(incoming)
    assert drop_rate >= 0.95, (
        f"expected ≥95% drop, got {result.dropped_events}/{len(incoming)} "
        f"({drop_rate:.1%}) kept={len(result.investment_events)}"
    )
