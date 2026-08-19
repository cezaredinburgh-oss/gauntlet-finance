"""apply_one_rule_fill_residuals — one stored rule fills leftover residuals."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from backend.schema.default_categories import (
    CAT_FUEL_CAR,
    CAT_GROCERIES,
    CAT_INTERNAL,
    CAT_OTHER,
    DEFAULT_CATEGORIES,
)
from backend.schema.models import Category, CategoryRule, MatchField, Transaction
from backend.services.categorization import (
    apply_one_rule_fill_residuals,
    create_rule,
)
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import rule, tx


class _TrackingRepo(InMemorySheetsRepository):
    """Records tab list/upsert so tests can prove no Transactions write."""

    def __init__(self) -> None:
        super().__init__()
        self.listed: list[str] = []
        self.upserted: list[str] = []

    def list_rows(self, tab: str) -> list:
        self.listed.append(tab)
        return super().list_rows(tab)

    def upsert_rows(self, tab: str, rows: list) -> None:
        self.upserted.append(tab)
        super().upsert_rows(tab, rows)


def _repo(*rows: Transaction) -> _TrackingRepo:
    repo = _TrackingRepo()
    repo.upsert_rows("Categories", list(DEFAULT_CATEGORIES))
    if rows:
        repo.upsert_rows("Transactions", list(rows))
    repo.listed.clear()
    repo.upserted.clear()
    return repo


def _fuel_rule() -> CategoryRule:
    return rule(
        priority=10,
        category_id=CAT_FUEL_CAR,
        match_field=MatchField.MERCHANT,
        match_value="EuroOil",
    )


def _tx_by_id(repo: InMemorySheetsRepository, tx_id: UUID) -> Transaction:
    row = repo.get_by_id("Transactions", tx_id)
    assert isinstance(row, Transaction)
    return row


def test_outside_bucket_fill():
    already = tx(merchant="EuroOil Praha", amount=Decimal("-80"), category_id=CAT_FUEL_CAR)
    outside = tx(merchant="EuroOil Brno", amount=Decimal("-40"))
    lidl = tx(merchant="Lidl", amount=Decimal("-25"))
    applied = _fuel_rule()
    repo = _repo(already, outside, lidl)

    stats = apply_one_rule_fill_residuals(repo, applied)

    assert stats["updated"] == 1
    assert stats["skipped_already"] == 1
    assert stats["matched"] == 2
    assert stats["rule_id"] == str(applied.id)
    assert stats["category_id"] == str(CAT_FUEL_CAR)
    assert _tx_by_id(repo, outside.id).category_id == CAT_FUEL_CAR
    assert _tx_by_id(repo, lidl.id).category_id is None
    assert _tx_by_id(repo, already.id).category_id == CAT_FUEL_CAR
    assert repo.listed.count("Transactions") == 1
    assert repo.upserted.count("Transactions") == 1


def test_residual_other_not_just_null():
    lidl = tx(merchant="Lidl Vinohrady", amount=Decimal("-30"), category_id=CAT_OTHER)
    repo = _repo(lidl)
    groceries = rule(
        priority=10,
        category_id=CAT_GROCERIES,
        match_field=MatchField.MERCHANT,
        match_value="Lidl",
    )

    stats = apply_one_rule_fill_residuals(repo, groceries)

    assert stats["updated"] == 1
    filled = _tx_by_id(repo, lidl.id)
    assert filled.category_id == CAT_GROCERIES
    assert filled.category_override is False


def test_override_skipped():
    locked = tx(
        merchant="EuroOil",
        amount=Decimal("-55"),
        category_id=CAT_GROCERIES,
        category_override=True,
    )
    repo = _repo(locked)

    stats = apply_one_rule_fill_residuals(repo, _fuel_rule())

    assert stats["updated"] == 0
    assert stats["skipped_override"] == 1
    after = _tx_by_id(repo, locked.id)
    assert after.category_id == CAT_GROCERIES
    assert after.category_override is True
    assert "Transactions" not in repo.upserted


def test_non_matching_vendor_untouched():
    tmobile = tx(merchant="T-Mobile", amount=Decimal("-19.90"))
    repo = _repo(tmobile)

    stats = apply_one_rule_fill_residuals(repo, _fuel_rule())

    assert stats["updated"] == 0
    assert stats["matched"] == 0
    assert _tx_by_id(repo, tmobile.id).category_id is None
    assert "Transactions" not in repo.upserted


def test_no_override_lock():
    blank = tx(merchant="EuroOil", amount=Decimal("-12.50"))
    repo = _repo(blank)

    apply_one_rule_fill_residuals(repo, _fuel_rule())

    filled = _tx_by_id(repo, blank.id)
    assert filled.category_id == CAT_FUEL_CAR
    assert filled.category_override is False


def test_internal_flag_from_rule_and_category():
    via_flag = tx(merchant="To CZK pot", amount=Decimal("-1000"), description="To CZK")
    via_cat = tx(merchant="Internal hop", amount=Decimal("-250.75"), description="wallet")
    repo = _repo(via_flag, via_cat)

    flag_rule = rule(
        priority=5,
        category_id=CAT_GROCERIES,
        match_field=MatchField.MERCHANT,
        match_value="To CZK",
        set_internal_transfer=True,
    )
    cat_rule = rule(
        priority=5,
        category_id=CAT_INTERNAL,
        match_field=MatchField.MERCHANT,
        match_value="Internal hop",
    )

    flag_stats = apply_one_rule_fill_residuals(repo, flag_rule)
    cat_stats = apply_one_rule_fill_residuals(repo, cat_rule)

    assert flag_stats["updated"] == 1
    assert cat_stats["updated"] == 1
    flagged = _tx_by_id(repo, via_flag.id)
    assert flagged.category_id == CAT_GROCERIES
    assert flagged.is_internal_transfer is True
    assert flagged.amount == Decimal("-1000")
    categorized = _tx_by_id(repo, via_cat.id)
    assert categorized.category_id == CAT_INTERNAL
    assert categorized.is_internal_transfer is True
    assert categorized.amount == Decimal("-250.75")
    assert isinstance(categorized.amount, Decimal)


def test_inactive_rule_is_noop():
    blank = tx(merchant="EuroOil", amount=Decimal("-10"))
    repo = _repo(blank)
    inactive = _fuel_rule().model_copy(update={"is_active": False})

    stats = apply_one_rule_fill_residuals(repo, inactive)

    assert stats["updated"] == 0
    assert stats["scanned"] == 0
    assert _tx_by_id(repo, blank.id).category_id is None
    assert "Transactions" not in repo.listed
    assert "Transactions" not in repo.upserted


def test_archived_rule_is_noop():
    blank = tx(merchant="EuroOil", amount=Decimal("-10"))
    repo = _repo(blank)
    archived = _fuel_rule().model_copy(update={"archived": True})

    stats = apply_one_rule_fill_residuals(repo, archived)

    assert stats["updated"] == 0
    assert _tx_by_id(repo, blank.id).category_id is None
    assert "Transactions" not in repo.upserted


def test_create_rule_does_not_scan_transactions():
    blank = tx(merchant="EuroOil", amount=Decimal("-10"))
    repo = _repo(blank)

    created = create_rule(
        repo,
        {
            "priority": 10,
            "match_field": "merchant",
            "match_type": "contains",
            "match_value": "EuroOil",
            "category_id": CAT_FUEL_CAR,
        },
    )

    assert created.match_value == "EuroOil"
    assert "Transactions" not in repo.listed
    assert repo.upserted == ["CategoryRules"]
    assert _tx_by_id(repo, blank.id).category_id is None


@pytest.mark.parametrize("needle", ["", "   ", "\t"])
def test_empty_needle_does_not_write_txs(needle: str):
    blank = tx(merchant="EuroOil", amount=Decimal("-10"))
    repo = _repo(blank)
    bad = _fuel_rule().model_copy(update={"match_value": needle})

    with pytest.raises(ValueError, match="match_value"):
        apply_one_rule_fill_residuals(repo, bad)

    assert _tx_by_id(repo, blank.id).category_id is None
    assert "Transactions" not in repo.upserted


def test_missing_category_does_not_write_txs():
    blank = tx(merchant="EuroOil", amount=Decimal("-10"))
    repo = _repo(blank)
    missing = _fuel_rule().model_copy(update={"category_id": uuid4()})

    with pytest.raises(ValueError, match="Category not found"):
        apply_one_rule_fill_residuals(repo, missing)

    assert _tx_by_id(repo, blank.id).category_id is None
    assert "Transactions" not in repo.upserted


def test_archived_category_does_not_write_txs():
    blank = tx(merchant="EuroOil", amount=Decimal("-10"))
    repo = _repo(blank)
    fuel = repo.get_by_id("Categories", CAT_FUEL_CAR)
    assert isinstance(fuel, Category)
    repo.upsert_rows("Categories", [fuel.model_copy(update={"archived": True})])
    repo.listed.clear()
    repo.upserted.clear()

    with pytest.raises(ValueError, match="Category not found"):
        apply_one_rule_fill_residuals(repo, _fuel_rule())

    assert _tx_by_id(repo, blank.id).category_id is None
    assert "Transactions" not in repo.upserted
