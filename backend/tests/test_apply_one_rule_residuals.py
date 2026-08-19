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

# --- PR3 residual tests ---

import asyncio
from datetime import date
from decimal import Decimal

from backend.api.auth import SessionUser
from backend.api.routes.categories import bulk_override_category
from backend.api.schemas import BulkCategoryOverrideRequest
from backend.schema.default_categories import (
    CAT_FUEL_CAR,
    CAT_OTHER,
    CAT_UNCATEGORIZED,
    DEFAULT_CATEGORIES,
)
from backend.schema.models import LifeDomain, MatchField, MatchType
from backend.services.ai_categorize import is_blank_category
from backend.services.alerts import build_alerts
from backend.services.categorization import (
    _is_blank_or_other_category,
    apply_rules_fill_blanks,
    coverage_stats,
    ledger_tx_counts,
)
from backend.services.dashboard import dashboard_summary
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import category, rule, tx as make_tx

_USER = SessionUser(
    email="dev@localhost",
    name="Dev",
    picture=None,
    access_token="",
    refresh_token=None,
    token_expiry=None,
)


def _usd_tx(**kwargs):
    t = make_tx(currency="USD", booking_date=date.today(), **kwargs)
    amt = t.amount
    return t.model_copy(update={"amount_usd": amt, "amount_czk": None})


def _repo(cats, txs, rules=None) -> InMemorySheetsRepository:
    repo = InMemorySheetsRepository()
    repo.replace_all_rows("Categories", cats)
    repo.replace_all_rows("Transactions", txs)
    repo.replace_all_rows("CategoryRules", rules or [])
    repo.replace_all_rows("FXRates", [])
    repo.replace_all_rows("InvestmentLots", [])
    repo.replace_all_rows("InvestmentEvents", [])
    repo.replace_all_rows("Prices", [])
    repo.replace_all_rows("Accounts", [])
    repo.replace_all_rows("VendorMemory", [])
    return repo


def test_travel_as_other_is_not_residual():
    travel = category(name="Travel", life_domain=LifeDomain.OTHER)
    cats = {c.id: c for c in [*DEFAULT_CATEGORIES, travel]}
    row = _usd_tx(amount=Decimal("-42.50"), merchant="Hotel", category_id=travel.id)
    assert _is_blank_or_other_category(row, cats) is False
    counts = ledger_tx_counts([row], cats)
    assert counts["tx_uncategorized"] == 0
    assert counts["tx_categorized"] == 1
    # Grok+ was already catch-all-only; leftover now matches.
    assert is_blank_category(row, cats) is False


def test_catchall_uuid_and_blank_still_residual():
    cats = {c.id: c for c in DEFAULT_CATEGORIES}
    other_row = _usd_tx(amount=Decimal("-10.00"), merchant="Misc", category_id=CAT_OTHER)
    uncat_row = _usd_tx(
        amount=Decimal("-11.00"), merchant="Misc2", category_id=CAT_UNCATEGORIZED
    )
    blank = _usd_tx(amount=Decimal("-12.00"), merchant="Blank", category_id=None)
    assert _is_blank_or_other_category(other_row, cats) is True
    assert _is_blank_or_other_category(uncat_row, cats) is True
    assert _is_blank_or_other_category(blank, cats) is True
    counts = ledger_tx_counts([other_row, uncat_row, blank], cats)
    assert counts["tx_uncategorized"] == 3
    assert counts["tx_categorized"] == 0


def test_travel_spend_is_categorized_other_uuid_stays_uncategorized_decimal():
    travel = category(name="Travel", life_domain=LifeDomain.OTHER)
    cats = [*DEFAULT_CATEGORIES, travel]
    travel_amt = Decimal("-69.40")
    other_amt = Decimal("-20.10")
    txs = [
        _usd_tx(amount=travel_amt, merchant="Hotel", category_id=travel.id),
        _usd_tx(amount=other_amt, merchant="Misc", category_id=CAT_OTHER),
    ]
    repo = _repo(cats, txs)

    cov = coverage_stats(repo, days=180)
    assert Decimal(cov["expense_usd_categorized"]) == abs(travel_amt).quantize(
        Decimal("0.01")
    )
    assert Decimal(cov["uncategorized_expense_usd"]) == abs(other_amt).quantize(
        Decimal("0.01")
    )
    assert "catch-alls count as leftover" in cov["progress_note"]
    assert "non-Other" not in cov["progress_note"]
    by_domain = {row["name"]: Decimal(row["amount_usd"]) for row in cov["by_domain"]}
    assert by_domain.get("Other") == abs(travel_amt).quantize(Decimal("0.01"))

    summary = dashboard_summary(repo, date_from=date.today(), date_to=date.today())
    uncat = Decimal(summary["spending"]["uncategorized_expense_usd"])
    assert uncat == abs(other_amt).quantize(Decimal("0.01"))
    dash_domains = {
        row["name"]: Decimal(row["amount_usd"]) for row in summary["spending"]["by_domain"]
    }
    assert dash_domains.get("Other") == (abs(travel_amt) + abs(other_amt)).quantize(
        Decimal("0.01")
    )

    alerts = build_alerts(repo)
    ids = {a["id"] for a in alerts["items"]}
    assert "uncategorized_high" not in ids


def test_fuel_rule_does_not_overwrite_travel_as_other():
    travel = category(name="Travel", life_domain=LifeDomain.OTHER)
    fuel = next(c for c in DEFAULT_CATEGORIES if c.id == CAT_FUEL_CAR)
    row = _usd_tx(amount=Decimal("-30.00"), merchant="EuroOil", category_id=travel.id)
    fuel_rule = rule(
        priority=10,
        category_id=fuel.id,
        match_field=MatchField.MERCHANT,
        match_type=MatchType.CONTAINS,
        match_value="EuroOil",
    )
    repo = _repo([*DEFAULT_CATEGORIES, travel], [row], [fuel_rule])
    stats = apply_rules_fill_blanks(repo)
    assert stats["filled"] == 0
    assert stats["skipped_already"] == 1
    kept = repo.get_by_id("Transactions", row.id)
    assert kept is not None
    assert kept.category_id == travel.id
    assert kept.category_override is False


def test_bulk_override_travel_as_other_sets_override():
    travel = category(name="Travel", life_domain=LifeDomain.OTHER)
    fuel = next(c for c in DEFAULT_CATEGORIES if c.id == CAT_FUEL_CAR)
    row = _usd_tx(amount=Decimal("-30.00"), merchant="EuroOil", category_id=travel.id)
    other_row = _usd_tx(amount=Decimal("-8.00"), merchant="Lidl", category_id=CAT_OTHER)
    repo = _repo([*DEFAULT_CATEGORIES, travel], [row, other_row])

    travel_result = asyncio.run(
        bulk_override_category(
            body=BulkCategoryOverrideRequest(
                category_id=fuel.id, transaction_ids=[row.id]
            ),
            repo=repo,
            _user=_USER,
        )
    )
    assert travel_result.updated == 1
    moved = repo.get_by_id("Transactions", row.id)
    assert moved is not None
    assert moved.category_id == fuel.id
    assert moved.category_override is True

    other_result = asyncio.run(
        bulk_override_category(
            body=BulkCategoryOverrideRequest(
                category_id=fuel.id, transaction_ids=[other_row.id]
            ),
            repo=repo,
            _user=_USER,
        )
    )
    assert other_result.updated == 1
    first_assign = repo.get_by_id("Transactions", other_row.id)
    assert first_assign is not None
    assert first_assign.category_id == fuel.id
    assert first_assign.category_override is False