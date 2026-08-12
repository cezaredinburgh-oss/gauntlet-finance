"""Unit tests for Grok categorize assist (mocked HTTP; no live xAI)."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from backend.config import Settings
from backend.schema.default_categories import (
    CAT_GROCERIES,
    CAT_OTHER,
    DEFAULT_CATEGORIES,
)
from backend.services import ai_categorize, ai_client, ai_quota
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


def test_cluster_skips_override_and_assigned():
    cats = list(DEFAULT_CATEGORIES)
    txs = [
        tx(merchant="Lidl", category_id=None),
        tx(merchant="Lidl", category_id=None),
        tx(merchant="Netflix", category_id=CAT_OTHER),
        tx(merchant="Salary Co", amount="1000", category_id=None, category_override=True),
        tx(merchant="Already", category_id=CAT_GROCERIES),
    ]
    clusters = ai_categorize.cluster_blank_merchants(txs, cats, limit=20)
    keys = {c.merchant_key for c in clusters}
    assert "m:lidl" in keys
    assert "m:netflix" in keys
    assert "m:salary co" not in keys
    assert "m:already" not in keys
    lidl = next(c for c in clusters if c.merchant_key == "m:lidl")
    assert lidl.sample_count == 2
    assert lidl.amount_sign == "out"


def test_validate_suggestions_rejects_unknown_category():
    cats = list(DEFAULT_CATEGORIES)
    clusters = [
        ai_categorize.MerchantCluster(
            merchant_key="m:lidl",
            label="Lidl",
            amount_sign="out",
            currency="CZK",
            sample_count=2,
            transaction_ids=["a", "b"],
        )
    ]
    raw = {
        "suggestions": [
            {
                "merchant_key": "m:lidl",
                "category_id": str(CAT_GROCERIES),
                "confidence": 0.9,
                "reason": "grocery",
            },
            {
                "merchant_key": "m:lidl",
                "category_id": str(uuid4()),
                "confidence": 0.99,
                "reason": "dup ignored",
            },
            {
                "merchant_key": "m:ghost",
                "category_id": str(CAT_GROCERIES),
                "confidence": 1.0,
                "reason": "unknown merchant",
            },
        ]
    }
    out = ai_categorize._validate_suggestions(raw, clusters, cats)
    assert len(out) == 1
    assert out[0].category_id == str(CAT_GROCERIES)
    assert out[0].transaction_ids == ["a", "b"]


def test_suggest_disabled():
    repo = InMemorySheetsRepository()
    r = ai_categorize.suggest_categories(
        repo,
        principal="e:test@x",
        settings=_settings(ai_enabled=False),
    )
    assert r.enabled is False
    assert r.suggestions == []
    assert r.message and "disabled" in r.message.lower()


def test_suggest_missing_key():
    repo = InMemorySheetsRepository()
    r = ai_categorize.suggest_categories(
        repo,
        principal="e:test@x",
        settings=_settings(xai_api_key=""),
    )
    assert r.enabled is True
    assert r.configured is False
    assert r.message and "XAI_API_KEY" in r.message


def test_suggest_with_mock_chat():
    repo = InMemorySheetsRepository()
    repo.upsert_rows("Categories", list(DEFAULT_CATEGORIES))
    t1 = tx(merchant="Lidl")
    t2 = tx(merchant="Lidl")
    repo.upsert_rows("Transactions", [t1, t2])

    def fake_chat(**kwargs) -> ChatResult:
        assert "Lidl" in kwargs["user"] or "lidl" in kwargs["user"].lower()
        # Minimized payload: no counterparty-style fields
        assert "account" not in kwargs["user"].lower()
        body = {
            "suggestions": [
                {
                    "merchant_key": "m:lidl",
                    "category_id": str(CAT_GROCERIES),
                    "confidence": 0.91,
                    "reason": "supermarket",
                }
            ]
        }
        return ChatResult(
            content=json.dumps(body),
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="grok-4.3",
        )

    r = ai_categorize.suggest_categories(
        repo,
        principal="e:test@x",
        settings=_settings(),
        chat_fn=fake_chat,
    )
    assert r.configured is True
    assert r.merchants_considered == 1
    assert r.merchants_suggested == 1
    assert r.tokens_used == 150
    assert len(r.suggestions) == 1
    assert r.suggestions[0].category_name  # resolved
    assert str(t1.id) in r.suggestions[0].transaction_ids


def test_quota_blocks_second_call():
    repo = InMemorySheetsRepository()
    repo.upsert_rows("Categories", list(DEFAULT_CATEGORIES))
    repo.upsert_rows("Transactions", [tx(merchant="Cafe")])

    def fake_chat(**kwargs) -> ChatResult:
        return ChatResult(
            content=json.dumps({"suggestions": []}),
            prompt_tokens=1000,
            completion_tokens=10,
            total_tokens=1010,
            model="grok-4.3",
        )

    s = _settings(ai_daily_token_cap=1200)
    r1 = ai_categorize.suggest_categories(
        repo, principal="e:quota@x", settings=s, chat_fn=fake_chat
    )
    assert r1.message is None or "no valid" in (r1.message or "").lower() or r1.merchants_considered >= 1
    r2 = ai_categorize.suggest_categories(
        repo, principal="e:quota@x", settings=s, chat_fn=fake_chat
    )
    assert r2.suggestions == []
    assert r2.message and "limit" in r2.message.lower()


def test_parse_json_object_fence():
    raw = '```json\n{"suggestions":[]}\n```'
    data = ai_client.parse_json_object(raw)
    assert data == {"suggestions": []}


def test_status_payload():
    st = ai_categorize.status_payload(_settings())
    assert st["configured"] is True
    assert st["mode"] == "platform"
    st2 = ai_categorize.status_payload(_settings(ai_enabled=False))
    assert st2["mode"] == "off"
