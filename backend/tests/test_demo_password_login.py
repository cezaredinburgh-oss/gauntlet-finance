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
        cfg = client.get("/api/auth/public-config").json()
        assert cfg["open_auth"] is False
        assert cfg["demo_login_enabled"] is True
        assert "owner_email" not in cfg
        assert "password" not in cfg
        assert "DEMO_PASSWORD" not in str(cfg)


def test_owner_password_login_not_demo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("ALLOW_OPEN_AUTH", "false")
    monkeypatch.setenv("SECRET_KEY", "prod-owner-secret-ok12")
    monkeypatch.setenv("SPREADSHEET_ID", "owner-sheet-id")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("MULTI_TENANT", "false")
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "false")
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("OWNER_PASSWORD", "owner-secret-pass")
    monkeypatch.setenv("DEBUG", "false")
    get_settings.cache_clear()
    clear_repo_cache()
    clear_tenant_memory_repos()
    with _client() as client:
        cfg = client.get("/api/auth/public-config").json()
        assert cfg["owner_login_enabled"] is True
        assert "owner_email" not in cfg
        assert cfg["open_auth"] is False

        bad = client.post(
            "/api/auth/password",
            json={"email": "owner@example.com", "password": "wrong"},
        )
        assert bad.status_code == 401

        # Different-length email must not 500
        bad2 = client.post(
            "/api/auth/password",
            json={"email": "x@y.z", "password": "owner-secret-pass"},
        )
        assert bad2.status_code in (401, 403)

        r = client.post(
            "/api/auth/password",
            json={"email": "OWNER@example.com", "password": "owner-secret-pass"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["is_demo"] is False
        me = client.get("/api/auth/me").json()
        assert me["is_demo"] is False
        assert me["email"] == "owner@example.com"


def test_demo_never_calls_google_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Even with a real SPREADSHEET_ID, demo must not open SA repository."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("ALLOW_OPEN_AUTH", "false")
    monkeypatch.setenv("SECRET_KEY", "prod-demo-sa-secret12")
    monkeypatch.setenv("SPREADSHEET_ID", "should-not-open")
    monkeypatch.setenv("REPO_BACKEND", "")  # not forced memory via REPO_BACKEND
    monkeypatch.setenv("MULTI_TENANT", "false")
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEMO_EMAIL", "demo@gauntlet.local")
    monkeypatch.setenv("DEMO_PASSWORD", "demo")
    monkeypatch.setenv("DEBUG", "false")
    # APP_ENV=production alone would use Google unless is_demo short-circuits
    get_settings.cache_clear()
    clear_repo_cache()
    clear_tenant_memory_repos()

    calls: list[str] = []

    def boom(*_a, **_k):
        calls.append("build")
        raise AssertionError("build_repository_from_settings must not run for demo")

    monkeypatch.setattr(
        "backend.api.deps.build_repository_from_settings",
        boom,
    )
    # production + no REPO_BACKEND=memory + test app_env is production
    # _use_memory_repo still true for app_env=test only; here production so would use SA
    # unless is_demo path wins.
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "demo@gauntlet.local", "password": "demo"},
        )
        assert r.status_code == 200, r.text
        # Force repository resolution
        assert client.get("/api/transactions").status_code == 200
    assert calls == []


def test_password_rate_limit_429(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from backend.services.demo_auth import (
        _MAX_ATTEMPTS,
        clear_password_rate_limits_for_tests,
    )

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "oauth")
    monkeypatch.setenv("SECRET_KEY", "rate-limit-secret-key")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("MULTI_TENANT", "true")
    monkeypatch.setenv("MULTI_TENANT_MEMORY_SHEETS", "true")
    monkeypatch.setenv("CONTROL_DB_PATH", str(tmp_path / "rl.db"))
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEMO_EMAIL", "demo@gauntlet.local")
    monkeypatch.setenv("DEMO_PASSWORD", "demo")
    get_settings.cache_clear()
    reset_control_store_for_tests()
    clear_password_rate_limits_for_tests()
    with _client() as client:
        for _ in range(_MAX_ATTEMPTS):
            r = client.post(
                "/api/auth/password",
                json={"email": "demo@gauntlet.local", "password": "wrong"},
            )
            assert r.status_code == 401
        blocked = client.post(
            "/api/auth/password",
            json={"email": "demo@gauntlet.local", "password": "demo"},
        )
        assert blocked.status_code == 429, blocked.text
    clear_password_rate_limits_for_tests()


def test_local_dev_forbidden_when_open_auth_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("ALLOW_OPEN_AUTH", "false")
    monkeypatch.setenv("SECRET_KEY", "prod-localdev-secret12")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    get_settings.cache_clear()
    with _client() as client:
        r = client.post("/api/auth/local-dev")
        assert r.status_code == 403, r.text
