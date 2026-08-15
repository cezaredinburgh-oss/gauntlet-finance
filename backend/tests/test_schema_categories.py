"""Default categories + Digital Assets seed + InMemory repository."""

from __future__ import annotations

from uuid import UUID

from backend.schema.default_categories import (
    CAT_BIZ_INCOME,
    CAT_BIZ_MATERIALS,
    CAT_BIZ_OTHER,
    CAT_BIZ_SHIPPING,
    CAT_BIZ_TOOLS,
    CAT_BUSINESS,
    CAT_CRYPTO_FUND,
    CAT_FITNESS,
    CAT_HEALTH,
    CAT_SELF_EDUCATION,
    DEFAULT_CATEGORIES,
)
from backend.schema.ensure_defaults import (
    ensure_default_categories,
    ensure_digital_assets_rule,
    ensure_self_education_rule,
)
from backend.schema.models import LifeDomain
from backend.schema.models import Category, CategoryRule, SHEET_HEADERS, TAB_MODEL
from backend.schema.seed_data import RULE_DIGITAL_ASSETS, SEED_CATEGORY_RULES
from backend.sheets.repository import InMemorySheetsRepository


def test_sheet_tabs_complete() -> None:
    expected = {
        "Accounts",
        "Transactions",
        "InvestmentLots",
        "InvestmentEvents",
        "Categories",
        "CategoryRules",
        "VendorMemory",
        "FXRates",
        "StatementFiles",
        "Settings",
        "Prices",
        "PortfolioSnapshots",
    }
    assert set(SHEET_HEADERS.keys()) == expected
    assert set(TAB_MODEL.keys()) == expected


def test_fitness_under_health() -> None:
    by_id = {c.id: c for c in DEFAULT_CATEGORIES}
    fitness = by_id[CAT_FITNESS]
    assert fitness.name == "Fitness"
    assert fitness.parent_id == CAT_HEALTH
    assert by_id[CAT_HEALTH].name == "Health"


def test_my_business_tree() -> None:
    by_id = {c.id: c for c in DEFAULT_CATEGORIES}
    assert by_id[CAT_BUSINESS].name == "My business"
    for cid, name_part in [
        (CAT_BIZ_MATERIALS, "materials"),
        (CAT_BIZ_TOOLS, "tools"),
        (CAT_BIZ_SHIPPING, "shipping"),
        (CAT_BIZ_OTHER, "other"),
    ]:
        c = by_id[cid]
        assert c.parent_id == CAT_BUSINESS
        assert name_part in c.name.lower()
    assert by_id[CAT_BIZ_INCOME].name == "Business income"
    assert by_id[CAT_BIZ_INCOME].is_income is True


def test_crypto_funding_category() -> None:
    by_id = {c.id: c for c in DEFAULT_CATEGORIES}
    assert by_id[CAT_CRYPTO_FUND].name == "Crypto funding"


def test_self_education_category() -> None:
    by_id = {c.id: c for c in DEFAULT_CATEGORIES}
    se = by_id[CAT_SELF_EDUCATION]
    assert se.name == "Self-education"
    assert se.parent_id is None
    assert se.life_domain == LifeDomain.EDUCATION
    assert se.is_transfer is False


def test_digital_assets_seed_rule() -> None:
    rule = next(r for r in SEED_CATEGORY_RULES if r.id == RULE_DIGITAL_ASSETS)
    assert rule.priority == 6
    assert rule.set_internal_transfer is True
    assert rule.category_id == CAT_CRYPTO_FUND
    assert "Digital Assets Europe" in rule.match_value


def test_ensure_defaults_idempotent() -> None:
    repo = InMemorySheetsRepository()
    n1 = ensure_default_categories(repo)
    assert n1 == len(DEFAULT_CATEGORIES)
    n2 = ensure_default_categories(repo)
    assert n2 == 0
    cats = [r for r in repo.list_rows("Categories") if isinstance(r, Category)]
    names = {c.name for c in cats}
    assert "Fitness" in names
    assert "My business" in names
    assert "Crypto funding" in names


def test_ensure_digital_assets_rule() -> None:
    repo = InMemorySheetsRepository()
    assert ensure_digital_assets_rule(repo) is True
    assert ensure_digital_assets_rule(repo) is False  # already ok
    rules = [r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule)]
    assert len(rules) == 1
    r = rules[0]
    assert r.priority == 6
    assert r.set_internal_transfer is True
    assert r.category_id == CAT_CRYPTO_FUND
    assert r.id == RULE_DIGITAL_ASSETS


def test_ensure_self_education_rule() -> None:
    repo = InMemorySheetsRepository()
    assert ensure_self_education_rule(repo) is True
    assert ensure_self_education_rule(repo) is False
    rules = [r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule)]
    assert len(rules) == 1
    r = rules[0]
    assert r.category_id == CAT_SELF_EDUCATION
    assert r.match_type.value == "exact_case"
    assert r.match_value == "CEZARY BIERNAT"
    assert r.priority == 12
    cats = {c.id: c for c in repo.list_rows("Categories") if isinstance(c, Category)}
    assert CAT_SELF_EDUCATION in cats


def test_inmemory_upsert_and_hash() -> None:
    from datetime import datetime, timezone
    from backend.schema.models import (
        Institution,
        ParserKey,
        StatementFile,
        StatementFileStatus,
    )

    repo = InMemorySheetsRepository()
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sha = "a" * 64
    sf = StatementFile(
        id=UUID("f1000001-0000-4000-8000-000000000099"),
        original_filename="test.csv",
        uploaded_at=ts,
        content_sha256=sha,
        institution=Institution.REVOLUT.value,
        row_count=1,
        parser_key=ParserKey.REVOLUT_EXPENSES.value,
        status=StatementFileStatus.IMPORTED,
        created_at=ts,
        updated_at=ts,
    )
    repo.upsert_rows("StatementFiles", [sf])
    found = repo.find_statement_by_hash(sha)
    assert found is not None
    assert found.id == sf.id
    assert repo.find_statement_by_hash("b" * 64) is None
