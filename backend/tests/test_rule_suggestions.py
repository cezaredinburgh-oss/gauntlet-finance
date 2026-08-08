"""Residual rule suggestion heuristics."""

from __future__ import annotations

from datetime import date

from backend.schema.models import Category
from backend.services.categorization import (
    ensure_default_categories,
    rule_suggestions,
)
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import tx


def test_rule_suggestions_affinity_to_existing_merchant_category():
    repo = InMemorySheetsRepository()
    ensure_default_categories(repo)
    cats = [c for c in repo.list_rows("Categories") if isinstance(c, Category)]
    groceries = next(c for c in cats if "Grocer" in c.name or c.name == "Groceries")
    repo.upsert_rows(
        "Transactions",
        [
            tx(
                merchant="Albert Hypermarket",
                amount="-200",
                currency="USD",
                booking_date=date(2026, 7, 1),
                category_id=groceries.id,
            ),
            tx(
                merchant="Albert Hypermarket",
                amount="-100",
                currency="USD",
                booking_date=date(2026, 7, 2),
                category_id=groceries.id,
            ),
            tx(
                merchant="Albert Praha Vinohrady",
                amount="-50",
                currency="USD",
                booking_date=date(2026, 7, 10),
            ),
            tx(
                merchant="ZZZ Unique Residual Shop",
                amount="-20",
                currency="USD",
                booking_date=date(2026, 7, 11),
            ),
        ],
    )
    out = rule_suggestions(repo, days=180, limit=20)
    assert out["items"]
    by_label = {i["label"]: i for i in out["items"]}
    albert = by_label.get("Albert Praha Vinohrady")
    assert albert is not None
    assert albert["suggested_category_id"] == str(groceries.id)
    assert albert["score"] > 0
