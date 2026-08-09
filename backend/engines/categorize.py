"""
Rule-based category assignment with two-axis category model support.

Rules are pure functions over Transaction + CategoryRule lists.
``category_override=True`` always wins (manual review / user edit).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from backend.schema.models import (
    Category,
    CategoryRule,
    MatchField,
    MatchType,
    Transaction,
)


@dataclass
class CategorizeResult:
    transactions: list[Transaction]
    assigned: int
    skipped_override: int
    unmatched: int


def _field_value(tx: Transaction, field: MatchField) -> str:
    mapping = {
        MatchField.MERCHANT: tx.merchant or "",
        MatchField.DESCRIPTION: tx.description or "",
        MatchField.ORIGINAL_DESCRIPTION: tx.original_description or "",
        MatchField.COUNTERPARTY_NAME: tx.counterparty_name or "",
        MatchField.SOURCE_INSTITUTION: tx.source_institution or "",
    }
    return mapping[field]


def rule_matches(tx: Transaction, rule: CategoryRule) -> bool:
    if not rule.is_active or rule.archived:
        return False
    if rule.institution_scope:
        if (tx.source_institution or "").lower() != rule.institution_scope.lower():
            return False

    hay = _field_value(tx, rule.match_field)
    needle = rule.match_value
    mt = rule.match_type

    if mt == MatchType.EXACT:
        return hay.lower() == needle.lower()
    if mt == MatchType.EXACT_CASE:
        return hay == needle
    if mt == MatchType.CONTAINS:
        return needle.lower() in hay.lower()
    if mt == MatchType.STARTS_WITH:
        return hay.lower().startswith(needle.lower())
    if mt == MatchType.REGEX:
        try:
            return re.search(needle, hay, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def apply_category_rules(
    tx: Transaction,
    rules: list[CategoryRule],
    *,
    fallback_category_id: UUID | None = None,
) -> Transaction:
    """
    Apply the first matching rule (lowest ``priority`` wins).

    If ``tx.category_override`` is True, returns tx unchanged.
    """
    if tx.category_override:
        return tx

    ordered = sorted(
        (r for r in rules if r.is_active and not r.archived),
        key=lambda r: (r.priority, str(r.id)),
    )
    for rule in ordered:
        if rule_matches(tx, rule):
            updates: dict = {"category_id": rule.category_id}
            if rule.set_internal_transfer:
                updates["is_internal_transfer"] = True
            return tx.model_copy(update=updates)

    if fallback_category_id is not None and tx.category_id is None:
        return tx.model_copy(update={"category_id": fallback_category_id})
    return tx


class CategoryEngine:
    """Batch categorizer with optional fallback category (e.g. life_domain Other)."""

    def __init__(
        self,
        rules: list[CategoryRule] | None = None,
        categories: list[Category] | None = None,
        *,
        fallback_category_id: UUID | None = None,
    ) -> None:
        self.rules = list(rules or [])
        self.categories = list(categories or [])
        self.fallback_category_id = fallback_category_id
        if self.fallback_category_id is None:
            self.fallback_category_id = self._default_fallback()

    def _default_fallback(self) -> UUID | None:
        for c in self.categories:
            if c.name.lower() in {"other", "uncategorized"} and not c.archived:
                return c.id
        return None

    def categorize_many(
        self,
        transactions: list[Transaction],
        *,
        rules: list[CategoryRule] | None = None,
    ) -> CategorizeResult:
        use_rules = rules if rules is not None else self.rules
        out: list[Transaction] = []
        assigned = 0
        skipped = 0
        unmatched = 0
        for tx in transactions:
            if tx.category_override:
                out.append(tx)
                skipped += 1
                continue
            before = tx.category_id
            updated = apply_category_rules(
                tx,
                use_rules,
                fallback_category_id=self.fallback_category_id,
            )
            out.append(updated)
            if updated.category_id is not None and updated.category_id != before:
                assigned += 1
            elif updated.category_id is None:
                unmatched += 1
            elif before is None and updated.category_id is not None:
                assigned += 1
        return CategorizeResult(
            transactions=out,
            assigned=assigned,
            skipped_override=skipped,
            unmatched=unmatched,
        )

    @staticmethod
    def apply_manual_override(
        tx: Transaction,
        category_id: UUID,
    ) -> Transaction:
        """User override — sets category and locks further rule runs."""
        return tx.model_copy(
            update={
                "category_id": category_id,
                "category_override": True,
            }
        )
