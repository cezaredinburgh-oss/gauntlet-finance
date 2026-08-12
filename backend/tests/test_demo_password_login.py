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


def test_logout_allows_demo_login_after_session(demo_env):
    """Sign out must clear session + guest mode so demo form can take over."""
    from backend.api.auth import SessionUser, create_session_token
    from backend.tenancy.store import get_control_store

    store = get_control_store()
    admin = store.upsert_user_from_oauth(
        email="admin@example.com",
        google_sub="admin",
        name="Admin",
        picture=None,
        role="platform_admin",
    )
    store.set_spreadsheet_id(admin.id, f"mem-{admin.id}")
    settings = get_settings()
    token = create_session_token(
        settings,
        SessionUser(
            email=admin.email,
            name="Admin",
            picture=None,
            access_token="x",
            refresh_token=None,
            token_expiry=None,
            user_id=admin.id,
            role="platform_admin",
            spreadsheet_id=admin.spreadsheet_id,
            is_demo=False,
        ),
    )
    with _client() as client:
        client.cookies.set("gf_session", token)
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "admin@example.com"

        lo = client.post("/api/auth/logout")
        assert lo.status_code == 200
        assert lo.json().get("guest") is True

        # Guest: no open re-auth as previous admin
        me2 = client.get("/api/auth/me")
        assert me2.status_code == 401, me2.text

        # Demo login works after logout
        demo = client.post(
            "/api/auth/password",
            json={"email": "demo@gauntlet.local", "password": "demo"},
        )
        assert demo.status_code == 200, demo.text
        me3 = client.get("/api/auth/me")
        assert me3.status_code == 200
        assert me3.json()["is_demo"] is True
        assert me3.json()["email"] == "demo@gauntlet.local"


def test_open_auth_logout_stays_guest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("SECRET_KEY", "test-guest-logout-secret")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("MULTI_TENANT", "false")
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    clear_repo_cache()
    with _client() as client:
        # Open auth (test env): me works without cookie
        assert client.get("/api/auth/me").status_code == 200
        assert client.post("/api/auth/logout").status_code == 200
        # Guest cookie blocks synthetic user
        assert client.get("/api/auth/me").status_code == 401
        # Resume local dev
        assert client.post("/api/auth/local-dev").status_code == 200
        assert client.get("/api/auth/me").status_code == 200


def test_public_production_no_open_ledger_demo_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Public host: no cookie → 401; demo password → isolated session."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("ALLOW_OPEN_AUTH", "false")
    monkeypatch.setenv("SECRET_KEY", "prod-public-secret-ok12")
    monkeypatch.setenv("SPREADSHEET_ID", "real-sheet-id-not-for-demo")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("MULTI_TENANT", "false")
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEMO_EMAIL", "demo@gauntlet.local")
    monkeypatch.setenv("DEMO_PASSWORD", "demo")
    monkeypatch.setenv("DEBUG", "false")
    get_settings.cache_clear()
    clear_repo_cache()
    clear_tenant_memory_repos()
    with _client() as client:
        assert client.get("/api/auth/me").status_code == 401
        dash = client.get("/api/dashboard-summary", params={"period_key": "this_month"})
        assert dash.status_code == 401
        r = client.post(
            "/api/auth/password",
            json={"email": "demo@gauntlet.local", "password": "demo"},
        )
        assert r.status_code == 200
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["is_demo"] is True
        # Demo can load domain data (isolated memory), not 401
        assert client.get("/api/transactions").status_code == 200
