from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.schema.models import (
    Account,
    AccountType,
    AssetClass,
    Category,
    CategoryRule,
    Institution,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LifeDomain,
    LotStatus,
    MatchField,
    MatchType,
    Necessity,
    StatementFile,
    StatementFileStatus,
    Transaction,
)
from backend.services.cleanup import (
    CONFIRM_TOKEN,
    expand_scopes,
    preview_cleanup,
    run_cleanup,
)
from backend.sheets.repository import InMemorySheetsRepository


def _ts() -> datetime:
    return datetime(2026, 8, 6, tzinfo=timezone.utc)


def _seed(repo: InMemorySheetsRepository) -> None:
    ts = _ts()
    acc = Account(
        id=uuid4(),
        name="Checking",
        institution=Institution.REVOLUT,
        account_type=AccountType.CHECKING,
        currency="USD",
        is_active=True,
        created_at=ts,
        updated_at=ts,
    )
    cat = Category(
        id=uuid4(),
        name="Food",
        parent_id=None,
        necessity=Necessity.VARIABLE_NECESSITY,
        life_domain=LifeDomain.FOOD,
        is_income=False,
        is_transfer=False,
        sort_order=1,
        created_at=ts,
        updated_at=ts,
    )
    rule = CategoryRule(
        id=uuid4(),
        priority=10,
        match_field=MatchField.MERCHANT,
        match_type=MatchType.CONTAINS,
        match_value="BILLA",
        category_id=cat.id,
        set_internal_transfer=False,
        institution_scope=None,
        is_active=True,
        created_at=ts,
        updated_at=ts,
    )
    tx = Transaction(
        id=uuid4(),
        account_id=acc.id,
        booking_date=date(2026, 1, 1),
        value_date=date(2026, 1, 1),
        amount=Decimal("-10"),
        currency="USD",
        merchant="BILLA",
        description="groceries",
        source_institution="Revolut",
        category_id=cat.id,
        category_override=True,
        is_internal_transfer=False,
        created_at=ts,
        updated_at=ts,
    )
    lot = InvestmentLot(
        id=uuid4(),
        account_id=acc.id,
        ticker="PLTR",
        asset_class=AssetClass.STOCK,
        source="Revolut",
        acquisition_date=date(2024, 1, 1),
        quantity_opened=Decimal("10"),
        quantity_remaining=Decimal("10"),
        cost_basis_native=Decimal("100"),
        cost_basis_czk=Decimal("0"),
        cost_basis_usd=Decimal("100"),
        native_currency="USD",
        status=LotStatus.OPEN,
        created_at=ts,
        updated_at=ts,
    )
    ev = InvestmentEvent(
        id=uuid4(),
        account_id=acc.id,
        event_type=InvestmentEventType.BUY,
        event_date=date(2024, 1, 1),
        ticker="PLTR",
        asset_class=AssetClass.STOCK,
        quantity=Decimal("10"),
        native_currency="USD",
        value_native=Decimal("100"),
        source="Revolut",
        created_at=ts,
        updated_at=ts,
    )
    sf = StatementFile(
        id=uuid4(),
        original_filename="x.csv",
        uploaded_at=ts,
        content_sha256="a" * 64,
        institution="Revolut",
        row_count=1,
        parser_key="revolut_expenses",
        status=StatementFileStatus.IMPORTED,
        created_at=ts,
        updated_at=ts,
    )
    repo.upsert_rows("Accounts", [acc])
    repo.upsert_rows("Categories", [cat])
    repo.upsert_rows("CategoryRules", [rule])
    repo.upsert_rows("Transactions", [tx])
    repo.upsert_rows("InvestmentLots", [lot])
    repo.upsert_rows("InvestmentEvents", [ev])
    repo.upsert_rows("StatementFiles", [sf])


def test_expand_composites():
    assert expand_scopes(["all_ledger"]) == [
        "transactions",
        "investments",
        "statement_files",
    ]
    with pytest.raises(ValueError):
        expand_scopes(["nope"])


def test_cleanup_transactions_only():
    repo = InMemorySheetsRepository()
    _seed(repo)
    r = run_cleanup(repo, ["transactions"])
    assert r.tabs_cleared.get("Transactions") == 1
    assert len(repo.list_rows("Transactions")) == 0
    assert len(repo.list_rows("InvestmentLots")) == 1
    assert len(repo.list_rows("Categories")) == 1


def test_cleanup_investments_only():
    repo = InMemorySheetsRepository()
    _seed(repo)
    r = run_cleanup(repo, ["investments"])
    assert r.tabs_cleared.get("InvestmentLots") == 1
    assert r.tabs_cleared.get("InvestmentEvents") == 1
    assert len(repo.list_rows("InvestmentLots")) == 0
    assert len(repo.list_rows("InvestmentEvents")) == 0
    assert len(repo.list_rows("Transactions")) == 1


def test_cleanup_categories_clears_tx_assignments():
    repo = InMemorySheetsRepository()
    _seed(repo)
    r = run_cleanup(repo, ["categories"])
    assert len(repo.list_rows("Categories")) == 0
    assert len(repo.list_rows("CategoryRules")) == 0
    assert r.transactions_uncategorized == 1
    txs = repo.list_rows("Transactions")
    assert len(txs) == 1
    assert isinstance(txs[0], Transaction)
    assert txs[0].category_id is None
    assert txs[0].category_override is False


def test_cleanup_categories_preserves_statement_data():
    """Categories/rules wipe must not delete txs, statement registry, or investments."""
    repo = InMemorySheetsRepository()
    _seed(repo)
    before = {
        "Transactions": len(repo.list_rows("Transactions")),
        "StatementFiles": len(repo.list_rows("StatementFiles")),
        "InvestmentLots": len(repo.list_rows("InvestmentLots")),
        "InvestmentEvents": len(repo.list_rows("InvestmentEvents")),
        "Accounts": len(repo.list_rows("Accounts")),
    }
    assert before["Transactions"] >= 1
    assert before["StatementFiles"] >= 1

    r = run_cleanup(repo, ["categories"])
    assert "Transactions" not in r.tabs_cleared
    assert "StatementFiles" not in r.tabs_cleared
    assert r.tabs_cleared.get("Categories", 0) >= 1
    assert r.tabs_cleared.get("CategoryRules", 0) >= 1

    assert len(repo.list_rows("Transactions")) == before["Transactions"]
    assert len(repo.list_rows("StatementFiles")) == before["StatementFiles"]
    assert len(repo.list_rows("InvestmentLots")) == before["InvestmentLots"]
    assert len(repo.list_rows("InvestmentEvents")) == before["InvestmentEvents"]
    assert len(repo.list_rows("Accounts")) == before["Accounts"]
    # Still have the statement file row + cash tx identity
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    assert txs[0].merchant == "BILLA"
    assert txs[0].amount is not None


def test_cleanup_categories_uses_upsert_not_replace_all_on_transactions():
    """Regression: replace_all on Transactions is clear+rewrite and can wipe Sheets."""
    repo = InMemorySheetsRepository()
    _seed(repo)

    calls: list[str] = []
    orig_replace = repo.replace_all_rows
    orig_upsert = repo.upsert_rows

    def spy_replace(tab: str, rows) -> None:  # type: ignore[no-untyped-def]
        calls.append(f"replace:{tab}:{len(rows)}")
        return orig_replace(tab, rows)

    def spy_upsert(tab: str, rows) -> None:  # type: ignore[no-untyped-def]
        calls.append(f"upsert:{tab}:{len(rows)}")
        return orig_upsert(tab, rows)

    repo.replace_all_rows = spy_replace  # type: ignore[method-assign]
    repo.upsert_rows = spy_upsert  # type: ignore[method-assign]

    run_cleanup(repo, ["categories"])

    assert not any(c.startswith("replace:Transactions") for c in calls), calls
    assert any(c.startswith("upsert:Transactions") for c in calls), calls
    # Categories/rules still use full clear (empty replace)
    assert any(c.startswith("replace:Categories") for c in calls)
    assert any(c.startswith("replace:CategoryRules") for c in calls)


def test_cleanup_all_ledger():
    repo = InMemorySheetsRepository()
    _seed(repo)
    run_cleanup(repo, ["all_ledger"])
    assert len(repo.list_rows("Transactions")) == 0
    assert len(repo.list_rows("InvestmentLots")) == 0
    assert len(repo.list_rows("InvestmentEvents")) == 0
    assert len(repo.list_rows("StatementFiles")) == 0
    assert len(repo.list_rows("Categories")) == 1
    assert len(repo.list_rows("Accounts")) == 1


def test_preview_has_counts():
    repo = InMemorySheetsRepository()
    _seed(repo)
    p = preview_cleanup(repo)
    assert p["confirm_token"] == CONFIRM_TOKEN
    by_id = {s["id"]: s for s in p["scopes"]}
    assert by_id["transactions"]["total_rows"] == 1
    assert by_id["investments"]["total_rows"] == 2
