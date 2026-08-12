"""Demo password login (landing page)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import clear_repo_cache, clear_tenant_memory_repos
from backend.api.main import create_app
from backend.config import get_settings
from backend.tenancy.store import reset_control_store_for_tests


@pytest.fixture()
def demo_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "oauth")
    monkeypatch.setenv("SECRET_KEY", "test-demo-password-secret")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("YFINANCE_ENABLED", "false")
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEMO_EMAIL", "demo@gauntlet.local")
    monkeypatch.setenv("DEMO_PASSWORD", "demo")
    monkeypatch.setenv("MULTI_TENANT", "true")
    monkeypatch.setenv("MULTI_TENANT_MEMORY_SHEETS", "true")
    monkeypatch.setenv("CONTROL_DB_PATH", str(tmp_path / "control.db"))
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "admin@example.com")
    get_settings.cache_clear()
    reset_control_store_for_tests()
    clear_repo_cache()
    clear_tenant_memory_repos()
    yield
    get_settings.cache_clear()
    reset_control_store_for_tests()
    clear_repo_cache()
    clear_tenant_memory_repos()


def _client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def test_public_config_exposes_demo_flag(demo_env):
    with _client() as client:
        r = client.get("/api/auth/public-config")
        assert r.status_code == 200
        body = r.json()
        assert body["demo_login_enabled"] is True
        assert body["demo_email"] == "demo@gauntlet.local"
        assert "password" not in body


def test_demo_password_login_success(demo_env):
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "demo@gauntlet.local", "password": "demo"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_demo"] is True
        assert body["email"] == "demo@gauntlet.local"
        assert "gf_session" in r.cookies or client.cookies.get("gf_session")

        me = client.get("/api/auth/me")
        assert me.status_code == 200, me.text
        m = me.json()
        assert m["is_demo"] is True
        assert m["role"] == "user"
        assert m["tenant_ready"] is True

        # Can hit domain API
        txs = client.get("/api/transactions")
        assert txs.status_code == 200, txs.text


def test_demo_wrong_password(demo_env):
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "demo@gauntlet.local", "password": "wrong"},
        )
        assert r.status_code == 401


def test_demo_disabled(demo_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "demo@gauntlet.local", "password": "demo"},
        )
        assert r.status_code == 403


def test_demo_cannot_be_admin_role(demo_env):
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "DEMO@gauntlet.local", "password": "demo"},
        )
        assert r.status_code == 200
        me = client.get("/api/auth/me").json()
        assert me["role"] == "user"
        assert me["is_demo"] is True
        # Admin invites forbidden
        inv = client.post(
            "/api/admin/invites",
            json={"email": "x@example.com"},
        )
        assert inv.status_code == 403
