"""Idempotent ensure of default categories + Digital Assets seed rule."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from backend.schema.default_categories import (
    CAT_CRYPTO_FUND,
    DEFAULT_CATEGORIES,
)
from backend.schema.models import Category, CategoryRule, MatchField, MatchType
from backend.schema.seed_data import RULE_DIGITAL_ASSETS

if TYPE_CHECKING:
    from backend.sheets.repository import SheetsRepository

UTC = timezone.utc
_DIGITAL_ASSETS_VALUE = "Revolut Digital Assets Europe Ltd"
_DIGITAL_ASSETS_NEEDLE = "revolut digital assets europe"


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
