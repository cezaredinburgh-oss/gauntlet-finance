from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.engines.statements import StatementService
from backend.parsers.revolut_expenses import (
    _revolut_row_external_id,
    parse_revolut_expenses,
)

FIXTURES = Path(__file__).parent / "fixtures"
BANK = Path(__file__).resolve().parents[2] / "Bank statements"


def test_parse_revolut_expenses_skips_reverted_and_multi_currency():
    text = (FIXTURES / "revolut_expenses_sample.csv").read_text(encoding="utf-8")
    czk = uuid4()
    inr = uuid4()
    result = parse_revolut_expenses(
        text,
        account_ids={"CZK": czk, "INR": inr, "default": czk},
        file_hash="b" * 64,
    )
    assert result.parser_key == "revolut_expenses"
    # 5 data rows but 1 REVERTED skipped from ledger
    assert result.row_count == 5
    assert len(result.transactions) == 4

    currencies = {t.currency for t in result.transactions}
    assert "INR" in currencies
    assert "CZK" in currencies

    card = next(t for t in result.transactions if t.merchant == "Bad Jeffs Barbecue")
    assert card.amount == Decimal("-2500.00")
    assert card.account_id == czk
    assert card.booking_date.isoformat() == "2020-07-09"
    assert card.value_date.isoformat() == "2020-07-08"

    assert all(t.notes is None or "REVERTED" not in t.notes for t in result.transactions)


def test_external_id_ignores_balance():
    """Same logical row with different Balance → same external_id."""
    base = {
        "Type": "Card Payment",
        "Product": "Current",
        "Started Date": "2026-01-13 10:00:00",
        "Completed Date": "2026-01-13 10:01:00",
        "Description": "Shop",
        "State": "COMPLETED",
        "Balance": "1000.00",
    }
    other = {**base, "Balance": "42.50"}
    amount = Decimal("-12.34")
    fee = Decimal("0")
    a = _revolut_row_external_id(base, amount, fee, "USD")
    b = _revolut_row_external_id(other, amount, fee, "USD")
    assert a == b
    assert a.startswith("rev:")


def test_checking_first_import_keeps_all_unique_external_ids():
    """
    Regression: within one all-time parse, hard-distinct rev: rows must not
    soft-collapse (was 487 false drops when soft lacked wall-clock times).

    True hard-duplicate external_ids in the CSV (if any) may still drop; soft
    must not add extra collapses.
    """
    from collections import Counter

    all_time = BANK / "revolut daily expenses all.csv"
    if not all_time.is_file():
        pytest.skip("Bank statements fixtures not present")

    acc = uuid4()
    account_ids = {"default": acc, "USD": acc, "CZK": acc, "EUR": acc}
    txs = parse_revolut_expenses(
        all_time.read_text(encoding="utf-8-sig"),
        account_ids=account_ids,
        file_hash="1" * 64,
    ).transactions
    assert txs
    ext_ids = [t.external_id for t in txs if t.external_id]
    hard_extra = sum(c - 1 for c in Counter(ext_ids).values() if c > 1)
    result = StatementService.dedupe_transactions([], txs)
    assert result.dropped_transactions == hard_extra, (
        f"first-import dropped {result.dropped_transactions} but only "
        f"{hard_extra} hard-duplicate extras (soft over-collapse?)"
    )
    assert len(result.transactions) == len(txs) - hard_extra


def test_checking_tax_year_after_all_time_dedupes_heavily():
    """
    Golden: tax-year checking after all-time expenses drops ≥95% of tax rows;
    every kept external_id is absent from the all-time set (true new rows).
    """
    all_time = BANK / "revolut daily expenses all.csv"
    tax = BANK / "Tax year test Revolut checking account.csv"
    if not all_time.is_file() or not tax.is_file():
        pytest.skip("Bank statements fixtures not present")

    acc = uuid4()
    account_ids = {"default": acc, "USD": acc, "CZK": acc, "EUR": acc}
    existing = parse_revolut_expenses(
        all_time.read_text(encoding="utf-8-sig"),
        account_ids=account_ids,
        file_hash="1" * 64,
    ).transactions
    incoming = parse_revolut_expenses(
        tax.read_text(encoding="utf-8-sig"),
        account_ids=account_ids,
        file_hash="2" * 64,
    ).transactions
    assert incoming, "tax-year checking fixture produced no transactions"
    result = StatementService.dedupe_transactions(existing, incoming)
    drop_rate = result.dropped_transactions / len(incoming)
    assert drop_rate >= 0.95, (
        f"expected ≥95% drop, got {result.dropped_transactions}/{len(incoming)} "
        f"({drop_rate:.1%})"
    )
    existing_ext = {t.external_id for t in existing if t.external_id}
    for t in result.transactions:
        assert t.external_id not in existing_ext, (
            f"kept row still in all-time set: {t.external_id} {t.description}"
        )
