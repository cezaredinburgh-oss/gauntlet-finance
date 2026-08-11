"""Dashboard cashflow: is_internal_transfer txs excluded from income/expense."""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

from backend.schema.models import (
    Category,
    LifeDomain,
    Necessity,
    Transaction,
)
from backend.services.dashboard import dashboard_summary
from backend.sheets.repository import InMemorySheetsRepository


TS = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)


def _cat(name: str, *, is_income: bool = False) -> Category:
    return Category(
        id=uuid4(),
        name=name,
        parent_id=None,
        necessity=Necessity.DISCRETIONARY,
        life_domain=LifeDomain.OTHER,
        is_income=is_income,
        is_transfer=False,
        sort_order=0,
        created_at=TS,
        updated_at=TS,
    )


def _tx(
    *,
    booking_date: date,
    amount: str,
    category_id,
    is_internal_transfer: bool = False,
    currency: str = "USD",
) -> Transaction:
    return Transaction(
        id=uuid4(),
        account_id=uuid4(),
        booking_date=booking_date,
        amount=Decimal(amount),
        currency=currency,
        fee_amount=Decimal("0"),
        merchant="Test",
        description=None,
        original_description=None,
        source_institution="Test",
        external_id=None,
        category_id=category_id,
        category_override=False,
        is_internal_transfer=is_internal_transfer,
        transfer_group_id=None,
        created_at=TS,
        updated_at=TS,
    )


def test_internal_transfers_excluded_from_income_and_expense_usd():
    """H15: is_internal_transfer=True must not affect income_usd / expense_usd."""
    spend_cat = _cat("Groceries")
    income_cat = _cat("Salary", is_income=True)

    today = date.today()
    txs = [
        # Real expense: counts
        _tx(
            booking_date=today - timedelta(days=2),
            amount="-100",
            category_id=spend_cat.id,
            is_internal_transfer=False,
        ),
        # Internal transfer outflow: excluded
        _tx(
            booking_date=today - timedelta(days=3),
            amount="-200",
            category_id=spend_cat.id,
            is_internal_transfer=True,
        ),
        # Real income: counts
        _tx(
            booking_date=today - timedelta(days=1),
            amount="50",
            category_id=income_cat.id,
            is_internal_transfer=False,
        ),
        # Internal transfer inflow: excluded
        _tx(
            booking_date=today - timedelta(days=4),
            amount="75",
            category_id=income_cat.id,
            is_internal_transfer=True,
        ),
    ]

    repo = InMemorySheetsRepository()
    repo.replace_all_rows("Categories", [spend_cat, income_cat])
    repo.replace_all_rows("Transactions", txs)
    repo.replace_all_rows("FXRates", [])
    repo.replace_all_rows("InvestmentLots", [])
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("Prices", [])
    repo.replace_all_rows("Accounts", [])

    summary = dashboard_summary(
        repo,
        date_from=today - timedelta(days=30),
        date_to=today,
        period_key="last_30d",
    )

    cf = summary["cashflow"]
    assert Decimal(cf["expense_usd"]) == Decimal("100.00")
    assert Decimal(cf["income_usd"]) == Decimal("50.00")
    assert Decimal(cf["net_usd"]) == Decimal("-50.00")
    # legacy aliases also USD and exclude internals
    assert Decimal(cf["expense"]) == Decimal("100.00")
    assert Decimal(cf["income"]) == Decimal("50.00")
    # both internal legs counted as transfers, not as cashflow
    assert cf["internal_transfer_count"] == 2
    assert cf["transaction_count"] == 4


def test_internal_transfers_excluded_from_pace_spend():
    """Pace windows also skip is_internal_transfer expenses."""
    spend_cat = _cat("Rent")
    today = date.today()
    txs = [
        _tx(
            booking_date=today - timedelta(days=5),
            amount="-80",
            category_id=spend_cat.id,
            is_internal_transfer=False,
        ),
        _tx(
            booking_date=today - timedelta(days=6),
            amount="-500",
            category_id=spend_cat.id,
            is_internal_transfer=True,
        ),
    ]

    repo = InMemorySheetsRepository()
    repo.replace_all_rows("Categories", [spend_cat])
    repo.replace_all_rows("Transactions", txs)
    repo.replace_all_rows("FXRates", [])
    repo.replace_all_rows("InvestmentLots", [])
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("Prices", [])
    repo.replace_all_rows("Accounts", [])

    summary = dashboard_summary(
        repo,
        date_from=today - timedelta(days=30),
        date_to=today,
        period_key="last_30d",
    )
    pace = summary["pace"]
    assert Decimal(pace["spend_30d_usd"]) == Decimal("80.00")
    # 80/6 quantized to 2dp (same path as dashboard pace strip)
    assert Decimal(pace["avg_monthly_6m_usd"]) == Decimal("13.33")
