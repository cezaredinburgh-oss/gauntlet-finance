"""Idempotent ensure of default categories + seed category rules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from backend.schema.default_categories import (
    CAT_CRYPTO_FUND,
    CAT_SELF_EDUCATION,
    DEFAULT_CATEGORIES,
)
from backend.schema.models import Category, CategoryRule, MatchField, MatchType
from backend.schema.seed_data import RULE_DIGITAL_ASSETS, RULE_SELF_EDUCATION_BIERNAT

if TYPE_CHECKING:
    from backend.sheets.repository import SheetsRepository

UTC = timezone.utc
_DIGITAL_ASSETS_VALUE = "Revolut Digital Assets Europe Ltd"
_DIGITAL_ASSETS_NEEDLE = "revolut digital assets europe"
# Exact original_description for the June 2026 course payment (Raiffeisen message field).
# Do NOT use contains on "Cezary Biernat" — account holder name appears on almost every RB row.
_SELF_EDUCATION_EXACT = "CEZARY BIERNAT"


def ensure_default_categories(repo: SheetsRepository) -> int:
    """Upsert missing DEFAULT_CATEGORIES by id. Returns count written."""
    existing = {
        r.id: r
        for r in repo.list_rows("Categories")
        if isinstance(r, Category) and not r.archived
    }
    to_write: list[Category] = []
    for cat in DEFAULT_CATEGORIES:
        if cat.id not in existing:
            to_write.append(cat)
    if to_write:
        repo.upsert_rows("Categories", to_write)
    return len(to_write)


def ensure_digital_assets_rule(repo: SheetsRepository) -> bool:
    """
    Ensure priority-6 Digital Assets Europe rule exists.

    Returns True if a rule was created or updated.
    """
    ensure_default_categories(repo)
    now = datetime.now(tz=UTC)
    rules = [
        r
        for r in repo.list_rows("CategoryRules")
        if isinstance(r, CategoryRule) and not r.archived
    ]
    for r in rules:
        needle = (r.match_value or "").lower()
        if _DIGITAL_ASSETS_NEEDLE not in needle:
            continue
        needs = (
            r.category_id != CAT_CRYPTO_FUND
            or not r.set_internal_transfer
            or not r.is_active
            or r.priority > 10
        )
        if needs:
            repo.upsert_rows(
                "CategoryRules",
                [
                    r.model_copy(
                        update={
                            "category_id": CAT_CRYPTO_FUND,
                            "set_internal_transfer": True,
                            "is_active": True,
                            "priority": min(r.priority, 6),
                            "notes": (
                                (r.notes or "") + "; ensure:digital_assets_crypto_pot"
                            ).strip("; "),
                            "updated_at": now,
                        }
                    )
                ],
            )
            return True
        return False

    repo.upsert_rows(
        "CategoryRules",
        [
            CategoryRule(
                id=RULE_DIGITAL_ASSETS if RULE_DIGITAL_ASSETS else uuid4(),
                priority=6,
                match_field=MatchField.DESCRIPTION,
                match_type=MatchType.CONTAINS,
                match_value=_DIGITAL_ASSETS_VALUE,
                category_id=CAT_CRYPTO_FUND,
                set_internal_transfer=True,
                institution_scope=None,
                is_active=True,
                notes="seed:digital_assets_crypto_pot",
                created_at=now,
                updated_at=now,
            )
        ],
    )
    return True


def ensure_self_education_rule(repo: SheetsRepository) -> bool:
    """
    Ensure case-sensitive exact-message rule for the course payment.

    Match: original_description EXACT_CASE ``CEZARY BIERNAT`` (all caps only).
    Title-case ``Cezary Biernat`` (account/Vodafone messages) must NOT match.
    Returns True if a rule was created or updated.
    """
    ensure_default_categories(repo)
    now = datetime.now(tz=UTC)
    rules = [
        r
        for r in repo.list_rows("CategoryRules")
        if isinstance(r, CategoryRule) and not r.archived
    ]
    for r in rules:
        # Identify our seed rule by id or by all-caps needle + original_description
        is_ours = r.id == RULE_SELF_EDUCATION_BIERNAT or (
            (r.match_value or "").strip() == _SELF_EDUCATION_EXACT
            and r.match_field == MatchField.ORIGINAL_DESCRIPTION
        )
        if not is_ours:
            continue
        needs = (
            r.category_id != CAT_SELF_EDUCATION
            or r.match_type != MatchType.EXACT_CASE
            or not r.is_active
            or r.priority > 12
            or r.set_internal_transfer
            or (r.match_value or "").strip() != _SELF_EDUCATION_EXACT
        )
        if needs:
            repo.upsert_rows(
                "CategoryRules",
                [
                    r.model_copy(
                        update={
                            "category_id": CAT_SELF_EDUCATION,
                            "match_type": MatchType.EXACT_CASE,
                            "match_field": MatchField.ORIGINAL_DESCRIPTION,
                            "match_value": _SELF_EDUCATION_EXACT,
                            "set_internal_transfer": False,
                            "is_active": True,
                            "priority": min(r.priority, 12),
                            "notes": (
                                (r.notes or "") + "; ensure:self_education_course"
                            ).strip("; "),
                            "updated_at": now,
                        }
                    )
                ],
            )
            return True
        return False

    repo.upsert_rows(
        "CategoryRules",
        [
            CategoryRule(
                id=RULE_SELF_EDUCATION_BIERNAT,
                priority=12,
                match_field=MatchField.ORIGINAL_DESCRIPTION,
                match_type=MatchType.EXACT_CASE,
                match_value=_SELF_EDUCATION_EXACT,
                category_id=CAT_SELF_EDUCATION,
                set_internal_transfer=False,
                institution_scope=None,
                is_active=True,
                notes="seed:self_education_course_exact_case_message",
                created_at=now,
                updated_at=now,
            )
        ],
    )
    return True
