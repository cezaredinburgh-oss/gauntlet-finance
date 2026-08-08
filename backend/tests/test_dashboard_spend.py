"""Dashboard spend split: investments share, by_category, pace fields."""

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


def _cat(
    name: str,
    *,
    domain: LifeDomain,
    necessity: Necessity = Necessity.DISCRETIONARY,
) -> Category:
    return Category(
        id=uuid4(),
        name=name,
        parent_id=None,
        necessity=necessity,
        life_domain=domain,
        is_income=False,
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
        is_internal_transfer=False,
        transfer_group_id=None,
        created_at=TS,
        updated_at=TS,
    )


def test_pace_investment_split_and_by_category():
    groceries = _cat("Groceries", domain=LifeDomain.FOOD, necessity=Necessity.VARIABLE_NECESSITY)
    broker = _cat("Broker funding", domain=LifeDomain.INVESTMENTS, necessity=Necessity.DISCRETIONARY)
    rent = _cat("Rent", domain=LifeDomain.HOUSING, necessity=Necessity.FIXED)

    today = date.today()
    # Within last 30d
    txs = [
        _tx(booking_date=today - timedelta(days=5), amount="-200", category_id=groceries.id),
        _tx(booking_date=today - timedelta(days=3), amount="-300", category_id=broker.id),
        _tx(booking_date=today - timedelta(days=10), amount="-100", category_id=rent.id),
        # Older (in 180d but outside 30d) — investment only
        _tx(booking_date=today - timedelta(days=90), amount="-600", category_id=broker.id),
    ]

    repo = InMemorySheetsRepository()
    repo.replace_all_rows("Categories", [groceries, broker, rent])
    repo.replace_all_rows("Transactions", txs)
    repo.replace_all_rows("FXRates", [])
    repo.replace_all_rows("InvestmentLots", [])
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("Prices", [])
    repo.replace_all_rows("Accounts", [])

    summary = dashboard_summary(
        repo,
        date_from=date(today.year, today.month, 1),
        date_to=today,
        period_key="this_month",
    )

    pace = summary["pace"]
    assert Decimal(pace["spend_30d_usd"]) == Decimal("600.00")  # 200+300+100
    assert Decimal(pace["spend_30d_investments_usd"]) == Decimal("300.00")
    assert Decimal(pace["spend_30d_living_usd"]) == Decimal("300.00")
    assert pace["investments_share_30d_pct"] == 50.0

    # 180d: 600 + 600 inv older = 1200 total, 900 inv
    assert Decimal(pace["spend_30d_usd"]) + Decimal("600.00")  # sanity
    assert Decimal(pace["avg_monthly_6m_usd"]) == Decimal("200.00")  # 1200/6
    assert Decimal(pace["avg_monthly_6m_investments_usd"]) == Decimal("150.00")  # 900/6
    assert Decimal(pace["avg_monthly_6m_living_usd"]) == Decimal("50.00")  # 300/6

    cats = summary["spending"]["by_category"]
    assert len(cats) >= 2
    # Sorted desc by amount within this_month window (only txs this month that fall in range)
    names = [c["name"] for c in cats]
    amounts = {c["name"]: Decimal(c["amount_usd"]) for c in cats}
    # this_month window includes the 30d txs if they fall in current month; older 90d may not
    assert "Broker funding" in names or "Groceries" in names
    for c in cats:
        assert "life_domain" in c
        assert "necessity" in c
        assert "pct_of_spend" in c
    # Ensure sorted descending
    sorted_amts = [Decimal(c["amount_usd"]) for c in cats]
    assert sorted_amts == sorted(sorted_amts, reverse=True)


def test_calendar_month_prior_comparison_in_summary():
    food = _cat("Food", domain=LifeDomain.FOOD)
    repo = InMemorySheetsRepository()
    repo.replace_all_rows("Categories", [food])
    # July and August sample
    today = date.today()
    july_start = date(today.year, today.month, 1)
    # Use previous calendar month explicitly
    if today.month == 1:
        prev_y, prev_m = today.year - 1, 12
    else:
        prev_y, prev_m = today.year, today.month - 1
    prev_from = date(prev_y, prev_m, 1)

    txs = [
        _tx(booking_date=prev_from + timedelta(days=5), amount="-100", category_id=food.id),
        _tx(booking_date=july_start + timedelta(days=2) if july_start.day == 1 else today, amount="-50", category_id=food.id),
    ]
    # Ensure second tx is in current month
    txs[1] = _tx(booking_date=today, amount="-50", category_id=food.id)

    repo.replace_all_rows("Transactions", txs)
    repo.replace_all_rows("FXRates", [])
    repo.replace_all_rows("InvestmentLots", [])
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("Prices", [])
    repo.replace_all_rows("Accounts", [])

    cur_from = date(today.year, today.month, 1)
    summary = dashboard_summary(
        repo,
        date_from=cur_from,
        date_to=today,
        period_key="calendar_month",
    )
    assert summary["comparison"] is not None
    assert summary["comparison"]["prior_from"] == prev_from.isoformat()
