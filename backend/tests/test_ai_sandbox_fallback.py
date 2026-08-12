"""Sandbox demo AI fallback (no XAI key)."""

from __future__ import annotations

from backend.config import Settings
from backend.schema.default_categories import CAT_GROCERIES, DEFAULT_CATEGORIES
from backend.services import ai_categorize, ai_quota, ai_statement_map
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import tx


def setup_function() -> None:
    ai_quota.reset_for_tests()


def teardown_function() -> None:
    ai_quota.reset_for_tests()


def _sandbox_settings(**kwargs) -> Settings:
    base = dict(
        app_env="test",
        ai_enabled=False,
        xai_api_key="",
        ai_sandbox_fallback=True,
    )
    base.update(kwargs)
    return Settings(**base)


def test_sandbox_suggest_without_key():
    repo = InMemorySheetsRepository()
    repo.upsert_rows("Categories", list(DEFAULT_CATEGORIES))
    t1 = tx(merchant="Lidl Praha")
    t2 = tx(merchant="Lidl Praha")
    repo.upsert_rows("Transactions", [t1, t2])

    r = ai_categorize.suggest_categories(
        repo,
        principal="u:sandbox-1",
        settings=_sandbox_settings(),
        sandbox=True,
    )
    assert r.configured is True
    assert r.model == "sandbox-heuristic"
    assert r.merchants_suggested >= 1
    assert r.suggestions[0].category_id == str(CAT_GROCERIES)


def test_non_sandbox_without_key_stays_off():
    repo = InMemorySheetsRepository()
    r = ai_categorize.suggest_categories(
        repo,
        principal="e:user@x",
        settings=_sandbox_settings(),
        sandbox=False,
    )
    assert r.configured is False
    assert r.suggestions == []


def test_sandbox_map_csv_without_key():
    csv = (
        b"Datum;Castka;Mena;Popis\n"
        b"01.08.2026;-12,00;CZK;Cafe\n"
        b"02.08.2026;-5,00;CZK;Lidl\n"
    )
    r = ai_statement_map.map_statement_bytes(
        csv,
        principal="u:sandbox-1",
        settings=_sandbox_settings(),
        sandbox=True,
    )
    assert r.configured is True
    assert r.mapping is not None
    assert r.mapping.columns["Datum"] == "booking_date"
    assert r.mapping.columns["Castka"] == "amount"
    assert len(r.preview) >= 1


def test_status_sandbox_mode():
    st = ai_categorize.status_payload(_sandbox_settings(), sandbox=True)
    assert st["mode"] == "sandbox_demo"
    assert st["configured"] is True
    assert st["sandbox_fallback"] is True
