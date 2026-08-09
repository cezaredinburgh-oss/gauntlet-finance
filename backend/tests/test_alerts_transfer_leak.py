"""Transfer-leak alert resolves when flagged internal or categorized as transfer/investments."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from backend.schema.default_categories import CAT_BROKER, CAT_EXTERNAL_XFER, CAT_INTERNAL
from backend.schema.models import Category, LifeDomain, Necessity, Transaction
from backend.services.alerts import build_alerts, transfer_leak_resolved
from backend.sheets.repository import InMemorySheetsRepository

TS = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)


def _cat(
    name: str,
    *,
    domain: LifeDomain,
    is_transfer: bool = False,
    cat_id=None,
) -> Category:
    return Category(
        id=cat_id or uuid4(),
        name=name,
        parent_id=None,
        necessity=Necessity.FIXED if is_transfer else Necessity.DISCRETIONARY,
        life_domain=domain,
        is_income=False,
        is_transfer=is_transfer,
        sort_order=0,
        created_at=TS,
        updated_at=TS,
    )


def _tx(
    *,
    description: str = "Transfer to my other account",
    amount: str = "-200",
    currency: str = "USD",
    is_internal_transfer: bool = False,
    category_id=None,
    booking_date: date | None = None,
) -> Transaction:
    return Transaction(
        id=uuid4(),
        account_id=uuid4(),
        booking_date=booking_date or date.today() - timedelta(days=3),
        amount=Decimal(amount),
        currency=currency,
        fee_amount=Decimal("0"),
        merchant=None,
        description=description,
        original_description=None,
        source_institution="Revolut",
        external_id=None,
        category_id=category_id,
        category_override=bool(category_id),
        is_internal_transfer=is_internal_transfer,
        transfer_group_id=None,
        created_at=TS,
        updated_at=TS,
    )


def _repo(cats: list[Category], txs: list[Transaction]) -> InMemorySheetsRepository:
    repo = InMemorySheetsRepository()
    repo.replace_all_rows("Categories", cats)
    repo.replace_all_rows("Transactions", txs)
    repo.replace_all_rows("FXRates", [])
    repo.replace_all_rows("InvestmentLots", [])
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("Prices", [])
    repo.replace_all_rows("Accounts", [])
    return repo


def _has_transfer_leak(result: dict) -> bool:
    return any(a.get("id") == "transfer_leak" for a in result.get("items", []))


def test_transfer_leak_resolved_helper():
    food = _cat("Groceries", domain=LifeDomain.FOOD)
    external = _cat(
        "External transfer",
        domain=LifeDomain.TRANSFERS,
        is_transfer=True,
        cat_id=CAT_EXTERNAL_XFER,
    )
    broker = _cat(
        "Broker funding",
        domain=LifeDomain.INVESTMENTS,
        cat_id=CAT_BROKER,
    )
    unflagged = _tx(category_id=None)
    assert transfer_leak_resolved(unflagged, None) is False
    assert transfer_leak_resolved(unflagged, food) is False
    assert transfer_leak_resolved(_tx(is_internal_transfer=True), None) is True
    assert transfer_leak_resolved(_tx(category_id=external.id), external) is True
    assert transfer_leak_resolved(_tx(category_id=broker.id), broker) is True


def test_alert_fires_for_unreviewed_transfer_like_expense():
    food = _cat("Groceries", domain=LifeDomain.FOOD)
    tx = _tx(category_id=None)
    result = build_alerts(_repo([food], [tx]), persist_fx=False)
    assert _has_transfer_leak(result)


def test_alert_clears_when_flagged_internal():
    tx = _tx(is_internal_transfer=True)
    result = build_alerts(_repo([], [tx]), persist_fx=False)
    assert not _has_transfer_leak(result)


def test_alert_clears_when_categorized_external_transfer_without_flag():
    external = _cat(
        "External transfer",
        domain=LifeDomain.TRANSFERS,
        is_transfer=True,
        cat_id=CAT_EXTERNAL_XFER,
    )
    tx = _tx(category_id=external.id, is_internal_transfer=False)
    result = build_alerts(_repo([external], [tx]), persist_fx=False)
    assert not _has_transfer_leak(result)


def test_alert_clears_when_categorized_broker_funding():
    broker = _cat(
        "Broker funding",
        domain=LifeDomain.INVESTMENTS,
        cat_id=CAT_BROKER,
    )
    tx = _tx(category_id=broker.id, is_internal_transfer=False)
    result = build_alerts(_repo([broker], [tx]), persist_fx=False)
    assert not _has_transfer_leak(result)


def test_alert_still_fires_when_wrongly_categorized_as_living():
    food = _cat("Groceries", domain=LifeDomain.FOOD)
    tx = _tx(category_id=food.id, is_internal_transfer=False)
    result = build_alerts(_repo([food], [tx]), persist_fx=False)
    assert _has_transfer_leak(result)


def test_override_to_internal_sets_flag():
    """API-level: assigning CAT_INTERNAL forces is_internal_transfer."""
    from backend.api.routes.categories import _category_implies_internal_transfer

    internal = _cat(
        "Internal transfer",
        domain=LifeDomain.TRANSFERS,
        is_transfer=True,
        cat_id=CAT_INTERNAL,
    )
    external = _cat(
        "External transfer",
        domain=LifeDomain.TRANSFERS,
        is_transfer=True,
        cat_id=CAT_EXTERNAL_XFER,
    )
    assert _category_implies_internal_transfer(internal) is True
    assert _category_implies_internal_transfer(external) is False
