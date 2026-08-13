"""Fresh empty ledgers must not surface residual/owner-style alerts."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import clear_repo_cache, clear_tenant_memory_repos
from backend.api.main import create_app
from backend.config import get_settings
from backend.schema.demo_public import ensure_public_demo_categories
from backend.services.alerts import build_alerts
from backend.services.lab_account import (
    clear_lab_repos_for_tests,
    ensure_lab_seeded,
    reset_lab_ledger,
)
from backend.sheets.repository import InMemorySheetsRepository


def test_empty_memory_ledger_has_zero_alerts():
    repo = InMemorySheetsRepository()
    ensure_public_demo_categories(repo)
    result = build_alerts(repo, persist_fx=False)
    assert result["total"] == 0
    assert result["items"] == []
    assert result["warn_count"] == 0
    assert result["danger_count"] == 0


def test_lab_reset_yields_zero_alerts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LAB_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LAB_EMAIL", "testaccount@o2.pl")
    monkeypatch.setenv("LAB_PASSWORD", "lab-secret-pass")
    monkeypatch.setenv("LAB_DATA_DIR", str(tmp_path / "lab"))
    get_settings.cache_clear()
    clear_lab_repos_for_tests()

    settings = get_settings()
    # Contaminate with a fake write, then reset
    repo = ensure_lab_seeded(settings)
    from datetime import datetime, timezone
    from uuid import uuid4

    from backend.schema.models import Category, LifeDomain, Necessity

    ts = datetime.now(timezone.utc)
    repo.upsert_rows(
        "Categories",
        [
            Category(
                id=uuid4(),
                name="Noise",
                necessity=Necessity.DISCRETIONARY,
                life_domain=LifeDomain.SHOPPING,
                created_at=ts,
                updated_at=ts,
            )
        ],
    )
    assert len(repo.list_rows("Categories")) > 1

    result = reset_lab_ledger(settings, dry_run=False)
    assert result["ok"] is True
    assert result["after"]["Transactions"] == 0
    assert result["after"]["InvestmentLots"] == 0

    clear_lab_repos_for_tests()
    clean = ensure_lab_seeded(get_settings())
    alerts = build_alerts(clean, persist_fx=False)
    assert alerts["total"] == 0
    assert alerts["items"] == []


def test_lab_api_alerts_empty_after_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "oauth")
    monkeypatch.setenv("SECRET_KEY", "empty-alerts-secret-ok")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("YFINANCE_ENABLED", "false")
    monkeypatch.setenv("MULTI_TENANT", "false")
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "false")
    monkeypatch.setenv("LAB_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LAB_EMAIL", "testaccount@o2.pl")
    monkeypatch.setenv("LAB_PASSWORD", "lab-secret-pass")
    monkeypatch.setenv("LAB_DATA_DIR", str(tmp_path / "lab"))
    get_settings.cache_clear()
    clear_repo_cache()
    clear_tenant_memory_repos()
    clear_lab_repos_for_tests()
    reset_lab_ledger(get_settings(), dry_run=False)

    with TestClient(create_app()) as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "testaccount@o2.pl", "password": "lab-secret-pass"},
        )
        assert r.status_code == 200, r.text
        alerts = client.get("/api/alerts")
        assert alerts.status_code == 200, alerts.text
        body = alerts.json()
        assert body["total"] == 0
        assert body["items"] == []

        txs = client.get("/api/transactions", params={"limit": 5})
        assert txs.status_code == 200
        assert txs.json()["total"] == 0

        st = client.get("/api/sheets/status")
        assert st.status_code == 200
        sj = st.json()
        assert sj["backend"] == "disk_memory"
        assert sj.get("demo_kind") == "lab"
        # Must not advertise the host's real spreadsheet id as lab's sheet
        assert sj.get("spreadsheet_id") in (None, "lab-account")
