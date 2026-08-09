"""Self-education category + exact course-payment rule (no name false positives)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from backend.engines.categorize import apply_category_rules, rule_matches
from backend.schema.default_categories import CAT_EXTERNAL_XFER, CAT_SELF_EDUCATION
from backend.schema.ensure_defaults import ensure_self_education_rule
from backend.schema.models import (
    CategoryRule,
    MatchField,
    MatchType,
    Transaction,
)
from backend.services.categorization import (
    apply_self_education_course_payments,
    ensure_default_categories,
)
from backend.sheets.repository import InMemorySheetsRepository

TS = datetime(2026, 8, 9, tzinfo=timezone.utc)


def _tx(
    *,
    original_description: str | None,
    description: str | None = None,
    category_id=None,
    category_override: bool = False,
    amount: str = "-49000",
) -> Transaction:
    return Transaction(
        id=uuid4(),
        account_id=uuid4(),
        booking_date=date(2026, 6, 4),
        amount=Decimal(amount),
        currency="CZK",
        fee_amount=Decimal("0"),
        merchant=None,
        description=description,
        original_description=original_description,
        source_institution="Raiffeisen",
        counterparty_name="Cezary Biernat",
        category_id=category_id,
        category_override=category_override,
        is_internal_transfer=False,
        created_at=TS,
        updated_at=TS,
    )


def test_exact_case_message_matches_course_not_title_case():
    rule = CategoryRule(
        id=uuid4(),
        priority=12,
        match_field=MatchField.ORIGINAL_DESCRIPTION,
        match_type=MatchType.EXACT_CASE,
        match_value="CEZARY BIERNAT",
        category_id=CAT_SELF_EDUCATION,
        set_internal_transfer=False,
        is_active=True,
        created_at=TS,
        updated_at=TS,
    )
    course = _tx(
        original_description="CEZARY BIERNAT",
        description="Outgoing instant payment — CEZARY BIERNAT",
    )
    title_case = _tx(
        original_description="Cezary Biernat",
        description="Outgoing instant payment — Cezary Biernat",
        amount="-312",
    )
    tax = _tx(
        original_description="Tax 2025, Cezary Biernat",
        description="Outgoing instant payment — Tax 2025, Cezary Biernat",
        amount="-8228",
    )
    plain = _tx(
        original_description=None,
        description="Outgoing instant payment",
        amount="-100",
    )
    assert rule_matches(course, rule) is True
    assert rule_matches(title_case, rule) is False
    assert rule_matches(tax, rule) is False
    assert rule_matches(plain, rule) is False

    external = CategoryRule(
        id=uuid4(),
        priority=15,
        match_field=MatchField.DESCRIPTION,
        match_type=MatchType.CONTAINS,
        match_value="Outgoing instant payment",
        category_id=CAT_EXTERNAL_XFER,
        set_internal_transfer=False,
        is_active=True,
        created_at=TS,
        updated_at=TS,
    )
    # Priority 12 beats 15 → Self-education
    out = apply_category_rules(course, [external, rule])
    assert out.category_id == CAT_SELF_EDUCATION


def test_apply_repairs_prior_external_transfer_and_clears_false_positives():
    repo = InMemorySheetsRepository()
    ensure_self_education_rule(repo)
    course = _tx(
        original_description="CEZARY BIERNAT",
        description="Outgoing instant payment — CEZARY BIERNAT",
        category_id=CAT_EXTERNAL_XFER,
    )
    false_pos = _tx(
        original_description="Cezary Biernat",
        description="Outgoing instant payment — Cezary Biernat",
        amount="-312",
        category_id=CAT_SELF_EDUCATION,
    )
    tax = _tx(
        original_description="Tax 2025, Cezary Biernat",
        description="Outgoing instant payment — Tax 2025, Cezary Biernat",
        amount="-8228",
        category_id=None,
    )
    repo.replace_all_rows("Transactions", [course, false_pos, tax])
    stats = apply_self_education_course_payments(repo)
    assert stats["assigned"] == 1
    assert stats["cleared_false_positives"] == 1
    by_id = {
        t.id: t
        for t in repo.list_rows("Transactions")
        if isinstance(t, Transaction)
    }
    assert by_id[course.id].category_id == CAT_SELF_EDUCATION
    assert by_id[false_pos.id].category_id is None
    assert by_id[tax.id].category_id is None


def test_ensure_default_categories_creates_self_education():
    repo = InMemorySheetsRepository()
    stats = ensure_default_categories(repo)
    assert stats["total_defaults"] >= 1
    names = {
        c.name
        for c in repo.list_rows("Categories")
        if hasattr(c, "name")
    }
    assert "Self-education" in names
