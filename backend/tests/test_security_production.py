"""Production security gates: open auth, deploy-env redaction, SPA path sandbox."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import clear_repo_cache
from backend.api.main import _safe_dist_file, create_app
from backend.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    clear_repo_cache()
    yield
    get_settings.cache_clear()
    clear_repo_cache()
    import backend.api.deps as deps

    deps._DEV_MEMORY_REPO = None


def _make_client(monkeypatch: pytest.MonkeyPatch, **env: str) -> TestClient:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Defaults that keep tests off live Sheets
    monkeypatch.setenv("SPREADSHEET_ID", env.get("SPREADSHEET_ID", ""))
    monkeypatch.setenv("YFINANCE_ENABLED", "false")
    monkeypatch.setenv("SECRET_KEY", env.get("SECRET_KEY", "test-secret-security"))
    get_settings.cache_clear()
    clear_repo_cache()
    import backend.api.deps as deps

    deps._DEV_MEMORY_REPO = None
    app = create_app()
    return TestClient(app)


def test_production_dev_auth_blocked_without_allow_open_auth(monkeypatch: pytest.MonkeyPatch):
    client = _make_client(
        monkeypatch,
        APP_ENV="production",
        AUTH_MODE="dev",
        ALLOW_OPEN_AUTH="false",
        DEBUG="false",
    )
    with client:
        # No session cookie → login required (not open synthetic user / not full ledger)
        r_me = client.get("/api/auth/me")
        assert r_me.status_code == 401, r_me.text

        r_dash = client.get("/api/dashboard-summary", params={"period_key": "this_month"})
        assert r_dash.status_code == 401, r_dash.text


def test_production_disabled_auth_blocked(monkeypatch: pytest.MonkeyPatch):
    client = _make_client(
        monkeypatch,
        APP_ENV="production",
        AUTH_MODE="disabled",
        ALLOW_OPEN_AUTH="false",
    )
    with client:
        r = client.get("/api/auth/me")
        assert r.status_code == 401


def test_production_allow_open_auth_works(monkeypatch: pytest.MonkeyPatch):
    client = _make_client(
        monkeypatch,
        APP_ENV="production",
        AUTH_MODE="dev",
        ALLOW_OPEN_AUTH="true",
        DEBUG="false",
    )
    with client:
        r = client.get("/api/auth/me")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["auth_mode"] == "dev"
        assert body["email"]


def test_app_env_test_still_works_with_disabled(monkeypatch: pytest.MonkeyPatch):
    """conftest uses APP_ENV=test + AUTH_MODE=disabled — open auth must work."""
    client = _make_client(
        monkeypatch,
        APP_ENV="test",
        AUTH_MODE="disabled",
        ALLOW_OPEN_AUTH="false",
    )
    with client:
        r = client.get("/api/auth/me")
        assert r.status_code == 200, r.text


def test_development_open_auth_works_without_allow(monkeypatch: pytest.MonkeyPatch):
    client = _make_client(
        monkeypatch,
        APP_ENV="development",
        AUTH_MODE="dev",
        ALLOW_OPEN_AUTH="false",
    )
    with client:
        r = client.get("/api/auth/me")
        assert r.status_code == 200, r.text


def test_open_auth_permitted_property():
    s_prod_blocked = Settings(
        app_env="production",
        auth_mode="dev",
        allow_open_auth=False,
    )
    assert s_prod_blocked.is_production is True
    assert s_prod_blocked.open_auth_permitted is False

    s_prod_allowed = Settings(
        app_env="production",
        auth_mode="dev",
        allow_open_auth=True,
    )
    assert s_prod_allowed.open_auth_permitted is True

    s_test = Settings(app_env="test", auth_mode="disabled", allow_open_auth=False)
    assert s_test.open_auth_permitted is True

    s_oauth = Settings(app_env="production", auth_mode="oauth", allow_open_auth=False)
    assert s_oauth.open_auth_permitted is True


def test_deploy_env_never_returns_private_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    sa = {
        "type": "service_account",
        "project_id": "demo",
        "private_key_id": "x",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEsecret\n-----END PRIVATE KEY-----\n",
        "client_email": "finance-sheets@demo.iam.gserviceaccount.com",
        "client_id": "123",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    sa_path = tmp_path / "service-account.json"
    sa_path.write_text(json.dumps(sa), encoding="utf-8")

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("SPREADSHEET_ID", "abcDEF1234567890xyz")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(sa_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    get_settings.cache_clear()

    # Resolve path via settings file that exists
    from backend.sheets import google_sheets as gs_mod

    monkeypatch.setattr(
        gs_mod,
        "resolve_service_account_path",
        lambda path: sa_path if path else None,
    )

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/setup/api/deploy-env")
        assert r.status_code == 200, r.text
        body = r.json()
        blob = json.dumps(body)
        assert "BEGIN PRIVATE KEY" not in blob
        assert "MIIEsecret" not in blob
        assert body.get("has_service_account") is True
        env = body["env"]
        assert env.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        assert "BEGIN PRIVATE KEY" not in env["GOOGLE_SERVICE_ACCOUNT_JSON"]
        assert "not returned by API" in env["GOOGLE_SERVICE_ACCOUNT_JSON"]
        # Explicit open-auth flag for trusted single-user template
        assert env.get("ALLOW_OPEN_AUTH") == "true"
        assert env.get("AUTH_MODE") == "dev"
        assert "BEGIN PRIVATE KEY" not in body.get("env_file_text", "")


def test_wizard_blocked_in_production_when_sheet_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    client = _make_client(
        monkeypatch,
        APP_ENV="production",
        AUTH_MODE="dev",
        ALLOW_OPEN_AUTH="true",
        ALLOW_SETUP_WIZARD="false",
        SPREADSHEET_ID="alreadyConfiguredSheetId123",
        DEBUG="true",  # even with debug, must block
    )
    with client:
        r = client.get("/setup/api/status")
        assert r.status_code == 403, r.text


def test_wizard_allowed_in_production_first_time(monkeypatch: pytest.MonkeyPatch):
    client = _make_client(
        monkeypatch,
        APP_ENV="production",
        AUTH_MODE="dev",
        ALLOW_OPEN_AUTH="true",
        ALLOW_SETUP_WIZARD="false",
        SPREADSHEET_ID="",
        DEBUG="false",
    )
    with client:
        r = client.get("/setup/api/status")
        assert r.status_code == 200, r.text


def test_safe_dist_file_blocks_path_traversal(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    (dist / "app.js").write_text("ok", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")

    assert _safe_dist_file(dist, "app.js") == (dist / "app.js").resolve()
    assert _safe_dist_file(dist, "missing.js") is None
    assert _safe_dist_file(dist, "") is None
    # Classic traversal
    assert _safe_dist_file(dist, "../secret.txt") is None
    assert _safe_dist_file(dist, "..\\secret.txt") is None
    # Nested legit file
    assets = dist / "assets"
    assets.mkdir()
    (assets / "x.css").write_text("body{}", encoding="utf-8")
    assert _safe_dist_file(dist, "assets/x.css") is not None
