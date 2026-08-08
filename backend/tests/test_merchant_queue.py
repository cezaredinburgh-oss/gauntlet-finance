"""Merchant review queue — field-aware apply reclassifies real txs."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from backend.schema.default_categories import CAT_GROCERIES, DEFAULT_CATEGORIES
from backend.schema.models import Transaction
from backend.services.categorization import (
    apply_merchant_queue_item,
    merchant_queue,
)
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import tx as make_tx

TS = datetime(2026, 8, 6, tzinfo=timezone.utc)


def _with_usd(t: Transaction, usd: str) -> Transaction:
    return t.model_copy(
        update={
            "amount_usd": Decimal(usd),
            "amount_czk": abs(t.amount),
            "created_at": TS,
            "updated_at": TS,
        }
    )


def _repo_with_uncat() -> InMemorySheetsRepository:
    repo = InMemorySheetsRepository()
    repo.upsert_rows("Categories", list(DEFAULT_CATEGORIES))
    t1 = _with_usd(
        make_tx(
            amount=Decimal("-250"),
            currency="CZK",
            merchant="SUPER BILLA XYZ",
            booking_date=date(2026, 7, 15),
        ),
        "-11.00",
    ).model_copy(update={"category_id": None, "category_override": False})
    t2 = _with_usd(
        make_tx(
            amount=Decimal("-100"),
            currency="CZK",
            merchant=None,
            description="Weekly moto gear order helmet",
            booking_date=date(2026, 7, 20),
        ),
        "-4.50",
    ).model_copy(update={"category_id": None, "category_override": False, "merchant": None})
    other = next(c for c in DEFAULT_CATEGORIES if c.life_domain.value == "Other")
    t3 = _with_usd(
        make_tx(
            amount=Decimal("-80"),
            currency="CZK",
            merchant="ALBERT MARKET",
            booking_date=date(2026, 7, 18),
        ),
        "-3.50",
    ).model_copy(update={"category_id": other.id, "category_override": False})
    repo.upsert_rows("Transactions", [t1, t2, t3])
    return repo


def test_queue_tracks_match_field():
    repo = _repo_with_uncat()
    q = merchant_queue(repo, days=180, limit=20)
    labels = {i["label"]: i for i in q["items"]}
    assert "SUPER BILLA XYZ" in labels
    assert labels["SUPER BILLA XYZ"]["match_field"] == "merchant"
    found_desc = [i for i in q["items"] if i["match_field"] == "description"]
    assert found_desc, "expected description-based queue item"


def test_apply_merchant_label_reclassifies():
    repo = _repo_with_uncat()
    result = apply_merchant_queue_item(
        repo,
        label="SUPER BILLA XYZ",
        category_id=CAT_GROCERIES,
        match_field="merchant",
        match_value="SUPER BILLA XYZ",
        make_rule=True,
        also_apply=True,
    )
    assert result["updated"] >= 1
    assert result["removed_from_queue"] is True
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    billa = next(t for t in txs if (t.merchant or "") == "SUPER BILLA XYZ")
    assert billa.category_id == CAT_GROCERIES


def test_apply_description_label():
    repo = _repo_with_uncat()
    result = apply_merchant_queue_item(
        repo,
        label="Weekly moto gear order helmet",
        category_id=CAT_GROCERIES,
        match_field="description",
        match_value="Weekly moto gear order helmet",
        make_rule=True,
        also_apply=True,
    )
    assert result["matched"] >= 1
    assert result["updated"] >= 1


def test_apply_reclassifies_other_domain():
    repo = _repo_with_uncat()
    result = apply_merchant_queue_item(
        repo,
        label="ALBERT MARKET",
        category_id=CAT_GROCERIES,
        match_field="merchant",
        match_value="ALBERT MARKET",
        make_rule=True,
        also_apply=True,
    )
    assert result["updated"] >= 1
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    albert = next(t for t in txs if (t.merchant or "") == "ALBERT MARKET")
    assert albert.category_id == CAT_GROCERIES
