"""Tests for historical amount_usd / amount_czk enrichment."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from backend.engines.fx import FXService
from backend.schema.models import Transaction
from backend.services.fx_amounts import enrich_transaction_amounts
from backend.services.maintenance import backfill_amount_usd
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import TS, fx_rate


def _tx(
    *,
    amount: str,
    currency: str,
    on: date = date(2026, 6, 19),
    amount_usd: Decimal | None = None,
    amount_czk: Decimal | None = None,
) -> Transaction:
    return Transaction(
        id=uuid4(),
        account_id=uuid4(),
        booking_date=on,
        amount=Decimal(amount),
        currency=currency,
        amount_usd=amount_usd,
        amount_czk=amount_czk,
        source_institution="Revolut",
        created_at=TS,
        updated_at=TS,
    )


def test_enrich_usd_native_fills_czk_from_historical_cnb():
    fx = FXService()
    fx.load_rates([fx_rate(rate_date=date(2026, 6, 19), base="USD", rate="21.07")])
    tx = _tx(amount="-854.46", currency="USD", amount_usd=Decimal("-854.46"))
    out, dirty = enrich_transaction_amounts(tx, fx)
    assert dirty is True
    assert out.amount_usd == Decimal("-854.46")
    assert out.amount_czk == Decimal("-18003.47")  # 854.46 * 21.07
    assert out.amount == Decimal("-854.46")
    assert out.currency == "USD"


def test_enrich_czk_native_fills_usd_from_historical_cnb():
    fx = FXService()
    fx.load_rates([fx_rate(rate_date=date(2026, 6, 19), base="USD", rate="21.07")])
    tx = _tx(amount="-18000", currency="CZK", amount_czk=Decimal("-18000"))
    out, dirty = enrich_transaction_amounts(tx, fx)
    assert dirty is True
    assert out.amount_czk == Decimal("-18000")
    # 18000 / 21.07 ≈ 854.2957 → 854.30 (ROUND_HALF_UP)
    assert out.amount_usd == Decimal("-854.30")


def test_enrich_never_overwrites_existing_converted_legs():
    fx = FXService()
    fx.load_rates([fx_rate(rate_date=date(2026, 6, 19), base="USD", rate="21.07")])
    tx = _tx(
        amount="-854.46",
        currency="USD",
        amount_usd=Decimal("-854.46"),
        amount_czk=Decimal("-18000"),
    )
    out, dirty = enrich_transaction_amounts(tx, fx)
    assert dirty is False
    assert out.amount_czk == Decimal("-18000")


def test_enrich_missing_rate_leaves_null():
    fx = FXService()
    tx = _tx(amount="-10", currency="EUR")
    out, dirty = enrich_transaction_amounts(tx, fx)
    assert dirty is False
    assert out.amount_usd is None
    assert out.amount_czk is None


def test_backfill_prioritizes_missing_czk_on_usd_rows():
    """USD-native rows with amount_usd set but amount_czk null must be filled."""
    repo = InMemorySheetsRepository()
    rate = fx_rate(rate_date=date(2026, 6, 19), base="USD", rate="21.07")
    repo.upsert_rows("FXRates", [rate])
    tx = _tx(
        amount="-854.46",
        currency="USD",
        amount_usd=Decimal("-854.46"),
        amount_czk=None,
    )
    repo.upsert_rows("Transactions", [tx])
    result = backfill_amount_usd(repo, limit=100, fetch_missing_rates=False)
    assert result["missing_czk_before"] == 1
    assert result["filled_czk_approx"] == 1
    stored = repo.list_rows("Transactions")[0]
    assert isinstance(stored, Transaction)
    assert stored.amount_czk == Decimal("-18003.47")
