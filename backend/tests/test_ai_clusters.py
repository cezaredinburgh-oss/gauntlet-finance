"""Unit tests for New ET AI cluster suggest (mocked HTTP; no live xAI)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from backend.config import Settings
from backend.schema.default_categories import (
    CAT_BANK_FEES,
    CAT_GROCERIES,
    CAT_INTERNAL,
    DEFAULT_CATEGORIES,
)
from backend.services import ai_clusters, ai_quota
from backend.services.ai_client import ChatResult
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import tx


@pytest.fixture(autouse=True)
def _reset_quota():
    ai_quota.reset_for_tests()
    yield
    ai_quota.reset_for_tests()


def _settings(**kwargs) -> Settings:
    base = dict(
        app_env="test",
        ai_enabled=True,
        xai_api_key="test-key-not-real",
        ai_model="grok-4.3",
        ai_daily_token_cap=50_000,
        ai_global_daily_token_cap=500_000,
        ai_max_merchants_per_request=40,
    )
    base.update(kwargs)
    return Settings(**base)


def test_disabled_returns_no_clusters():
    repo = InMemorySheetsRepository()
    r = ai_clusters.suggest_clusters(
        repo, principal="e:test@x", settings=_settings(ai_enabled=False)
    )
    assert r.enabled is False
    assert r.configured is False
    assert r.clusters == []
    assert r.message and "disabled" in r.message.lower()


def test_missing_key_never_uses_heuristic():
    repo = InMemorySheetsRepository()
    r = ai_clusters.suggest_clusters(
        repo, principal="e:test@x", settings=_settings(xai_api_key="")
    )
    assert r.enabled is True
    assert r.configured is False
    assert r.clusters == []
    assert r.message and "XAI_API_KEY" in r.message


def test_select_residual_skips_assigned_and_overrides():
    cats = list(DEFAULT_CATEGORIES)
    rows = ai_clusters.select_residual_rows(
        [
            tx(merchant="Lidl", amount="-120.49"),
            tx(merchant="Done", category_id=CAT_GROCERIES, amount="-10"),
            tx(
                merchant="Override",
                category_id=None,
                category_override=True,
                amount="-5",
            ),
            tx(merchant="Big", amount="-900.1"),
        ],
        cats,
        limit=20,
    )
    labels = {r.merchant for r in rows}
    assert labels == {"Lidl", "Big"}
    big = next(r for r in rows if r.merchant == "Big")
    assert big.amount == "900.10"
    assert big.sign == "out"
    lidl = next(r for r in rows if r.merchant == "Lidl")
    assert lidl.amount == "120.49"


def test_validate_clusters_keeps_known_ids_and_kinds():
    sent = {"aaa", "bbb", "ccc"}
    raw = {
        "clusters": [
            {
                "title": "Lidl",
                "kind": "vendor",
                "transaction_ids": ["aaa", "bbb", "ghost"],
                "category_id": str(CAT_GROCERIES),
                "confidence": 0.91,
                "reason": "grocery chain",
            },
            {
                "title": "Own pots",
                "kind": "internal_transfer",
                "transaction_ids": ["ccc"],
                "category_id": str(CAT_INTERNAL),
                "confidence": 0.8,
                "reason": "savings move",
            },
            {
                "title": "Bad kind",
                "kind": "made_up",
                "transaction_ids": ["aaa"],
                "category_id": str(CAT_GROCERIES),
                "confidence": 0.99,
                "reason": "nope",
            },
            {
                "title": "Unknown cat",
                "kind": "vendor",
                "transaction_ids": ["aaa"],
                "category_id": str(uuid4()),
                "confidence": 0.99,
                "reason": "invented",
            },
        ]
    }
    out = ai_clusters.validate_clusters(raw, sent, list(DEFAULT_CATEGORIES))
    assert [c.kind for c in out] == ["vendor", "internal_transfer"]
    assert out[0].transaction_ids == ["aaa", "bbb"]
    assert out[0].category_id == str(CAT_GROCERIES)
    assert out[1].category_id == str(CAT_INTERNAL)
    assert out[0].needs_human is False


def test_validate_clusters_normalizes_uuid_case():
    tid = "87e9b76c-9b0d-48f4-8b96-982795907090"
    raw = {
        "clusters": [
            {
                "title": "Top-up",
                "kind": "internal_transfer",
                "transaction_ids": [tid.replace("-", "").upper()],
                "category_id": str(CAT_INTERNAL),
                "confidence": 0.9,
                "reason": "pot",
            }
        ]
    }
    out = ai_clusters.validate_clusters(raw, {tid}, list(DEFAULT_CATEGORIES))
    assert len(out) == 1
    assert out[0].transaction_ids == [tid]


def test_select_residual_for_query_finds_groceries_not_whale():
    cats = list(DEFAULT_CATEGORIES)
    whale = tx(merchant="Raiffeisen", description="Revolut top-up", amount="-210000")
    lidls = [tx(merchant="Lidl", description="potraviny", amount="-15") for _ in range(4)]
    rows = ai_clusters.select_residual_for_query(
        [whale, *lidls],
        cats,
        "grocery related transactions",
        limit=10,
    )
    labels = {r.merchant for r in rows}
    assert "Lidl" in labels
    assert "Raiffeisen" not in labels


def test_select_residual_prefers_repeat_vendors_over_large_one_off():
    cats = list(DEFAULT_CATEGORIES)
    whale = tx(merchant="Raiffeisen", amount="-210000")
    lidls = [tx(merchant="Lidl", amount="-12") for _ in range(6)]
    rows = ai_clusters.select_residual_rows([whale, *lidls], cats, limit=6)
    labels = [r.merchant for r in rows]
    assert labels.count("Lidl") >= 5
    assert "Raiffeisen" not in labels


def test_select_residual_excludes_before_limit():
    cats = list(DEFAULT_CATEGORIES)
    big = tx(merchant="OldBig", amount="-210000")
    newer = [tx(merchant=f"Small{i}", amount="-10") for i in range(5)]
    rows = ai_clusters.select_residual_rows(
        [big, *newer],
        cats,
        limit=3,
        exclude_ids={str(big.id)},
    )
    labels = {r.merchant for r in rows}
    assert "OldBig" not in labels
    assert len(rows) == 3


def test_validate_needs_human_when_no_category():
    raw = {
        "clusters": [
            {
                "title": "Ambiguous shop",
                "kind": "other",
                "transaction_ids": ["aaa"],
                "category_id": "",
                "confidence": 0.4,
                "reason": "unclear",
                "needs_human": True,
            }
        ]
    }
    out = ai_clusters.validate_clusters(raw, {"aaa"}, list(DEFAULT_CATEGORIES))
    assert len(out) == 1
    assert out[0].needs_human is True
    assert out[0].category_id == ""


def test_suggest_clusters_mocked_chat():
    repo = InMemorySheetsRepository()
    for c in DEFAULT_CATEGORIES:
        repo.upsert_rows("Categories", [c])
    t1 = tx(merchant="Lidl", amount="-80")
    t2 = tx(merchant="Lidl Praha", amount="-40")
    repo.upsert_rows("Transactions", [t1, t2])

    def fake_chat(**kwargs) -> ChatResult:
        payload = {
            "clusters": [
                {
                    "title": "Lidl groceries",
                    "kind": "vendor",
                    "transaction_ids": [str(t1.id), str(t2.id)],
                    "category_id": str(CAT_GROCERIES),
                    "confidence": 0.88,
                    "reason": "same grocer",
                }
            ]
        }
        import json

        return ChatResult(
            content=json.dumps(payload),
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            model="grok-test",
        )

    r = ai_clusters.suggest_clusters(
        repo,
        principal="e:test@x",
        settings=_settings(),
        chat_fn=fake_chat,
    )
    assert r.configured is True
    assert r.enabled is True
    assert len(r.clusters) == 1
    assert r.clusters[0].kind == "vendor"
    assert r.clusters[0].sample_count == 2
    assert r.tokens_used == 30
    dumped_ids = {row["id"] for row in r.transactions}
    assert dumped_ids == {str(t1.id), str(t2.id)}


def test_preset_top_vendors_ranks_by_count_not_amount():
    cats = list(DEFAULT_CATEGORIES)
    whale = tx(merchant="Raiffeisen", amount="-210000")
    lidls = [tx(merchant="Lidl", amount="-12") for _ in range(5)]
    piles, used = ai_clusters.build_preset_piles(
        [whale, *lidls], cats, "top_vendors"
    )
    assert piles
    assert piles[0].title.startswith("Lidl")
    assert piles[0].sample_count == 5
    assert {t.merchant for t in used} >= {"Lidl"}


def test_preset_internal_uses_transfer_wording():
    cats = list(DEFAULT_CATEGORIES)
    hit = tx(merchant="Revolut", description="Top-up from Raiffeisen", amount="-500")
    miss = tx(merchant="Lidl", amount="-20")
    already = tx(
        merchant="Revolut",
        description="Transfer to savings",
        amount="-80",
        is_internal_transfer=True,
    )
    piles, used = ai_clusters.build_preset_piles(
        [hit, miss, already], cats, "internal"
    )
    assert len(piles) == 1
    assert piles[0].kind == "internal_transfer"
    assert piles[0].category_id == str(CAT_INTERNAL)
    assert str(hit.id) in piles[0].transaction_ids
    assert str(miss.id) not in piles[0].transaction_ids
    assert str(already.id) not in piles[0].transaction_ids
    assert used == [hit]


def test_preset_fees_matches_atm_wording():
    cats = list(DEFAULT_CATEGORIES)
    hit = tx(merchant="Raiffeisen", description="ATM cash withdraw", amount="-2000")
    miss = tx(merchant="Lidl", amount="-40")
    piles, used = ai_clusters.build_preset_piles([hit, miss], cats, "fees")
    assert len(piles) == 1
    assert piles[0].kind == "fee"
    assert piles[0].category_id == str(CAT_BANK_FEES)
    assert str(hit.id) in piles[0].transaction_ids
    assert used == [hit]


def test_preset_income_only_positive_residuals():
    cats = list(DEFAULT_CATEGORIES)
    pay = tx(merchant="Employer", description="Salary", amount="4200")
    spend = tx(merchant="Lidl", amount="-18")
    piles, used = ai_clusters.build_preset_piles([pay, spend], cats, "income")
    assert len(piles) == 1
    assert piles[0].kind == "income"
    assert piles[0].needs_human is True
    assert str(pay.id) in piles[0].transaction_ids
    assert str(spend.id) not in piles[0].transaction_ids
    assert used == [pay]


def test_preset_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown preset"):
        ai_clusters.build_preset_piles([], list(DEFAULT_CATEGORIES), "groceries")


def test_ask_clusters_mocked_chat():
    repo = InMemorySheetsRepository()
    for c in DEFAULT_CATEGORIES:
        repo.upsert_rows("Categories", [c])
    lidl = tx(merchant="Lidl", amount="-18")
    whale = tx(merchant="Raiffeisen", description="Revolut top-up", amount="-210000")
    repo.upsert_rows("Transactions", [lidl, whale])

    def fake_chat(**kwargs):
        import json

        payload = {
            "reply": "Found 1 grocery pile.",
            "clusters": [
                {
                    "title": "Lidl groceries",
                    "kind": "vendor",
                    "transaction_ids": [str(lidl.id)],
                    "category_id": str(CAT_GROCERIES),
                    "confidence": 0.9,
                    "reason": "supermarket",
                }
            ],
        }
        return ChatResult(
            content=json.dumps(payload),
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            model="grok-test",
        )

    r = ai_clusters.ask_clusters(
        repo,
        principal="e:test@x",
        question="grocery related transactions",
        settings=_settings(),
        chat_fn=fake_chat,
    )
    assert r.reply == "Found 1 grocery pile."
    assert len(r.clusters) == 1
    assert r.clusters[0].transaction_ids == [str(lidl.id)]
    assert {row["id"] for row in r.transactions} == {str(lidl.id)}


def test_payload_has_no_account_numbers():
    cats = list(DEFAULT_CATEGORIES)
    rows = ai_clusters.select_residual_rows(
        [tx(merchant="Cafe", description="IBAN CZ6508000000192000145399", amount="-12")],
        cats,
        limit=5,
    )
    payload = ai_clusters.build_user_payload(rows, [{"id": str(CAT_GROCERIES), "name": "Groceries", "life_domain": "Food"}])
    assert "account" not in payload.lower()
    assert "IBAN" not in payload
    assert "Cafe" in payload
    assert Decimal(rows[0].amount) == Decimal("12.00")
