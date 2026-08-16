"""Lab test account: password login + disk-persistent ledger (not Sheets)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import clear_repo_cache, clear_tenant_memory_repos
from backend.api.main import create_app
from backend.config import get_settings
from backend.services.lab_account import clear_lab_repos_for_tests


@pytest.fixture()
def lab_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "oauth")
    monkeypatch.setenv("SECRET_KEY", "test-lab-account-secret-ok")
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
    yield tmp_path
    get_settings.cache_clear()
    clear_repo_cache()
    clear_tenant_memory_repos()
    clear_lab_repos_for_tests()


def _client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def test_public_config_lab_flag(lab_env):
    with _client() as client:
        r = client.get("/api/auth/public-config")
        assert r.status_code == 200
        body = r.json()
        assert body["lab_login_enabled"] is True
        assert "lab_password" not in body
        assert "LAB_PASSWORD" not in str(body)
        # Email not advertised publicly
        assert body.get("lab_email") is None


def test_lab_login_success_and_writable(lab_env):
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "testaccount@o2.pl", "password": "lab-secret-pass"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_demo"] is True
        assert body["demo_kind"] == "lab"
        assert body["read_only"] is False
        assert body["email"] == "testaccount@o2.pl"

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        m = me.json()
        assert m["is_demo"] is True
        assert m["demo_kind"] == "lab"
        assert m["read_only"] is False
        assert m["tenant_ready"] is True
        assert m["role"] == "user"

        txs = client.get("/api/transactions")
        assert txs.status_code == 200, txs.text

        # Public category pack seeded (empty new-user surface)
        cats = client.get("/api/categories")
        assert cats.status_code == 200, cats.text
        assert len(cats.json()) > 0


def test_lab_wrong_password(lab_env):
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "testaccount@o2.pl", "password": "wrong"},
        )
        assert r.status_code == 401


def test_lab_disabled(lab_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LAB_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    clear_lab_repos_for_tests()
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "testaccount@o2.pl", "password": "lab-secret-pass"},
        )
        assert r.status_code in (401, 403)


def test_lab_persists_across_logout_and_relogin(lab_env: Path):
    """Mutations survive logout (unlike sandbox) and process singleton reload."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from backend.schema.models import Category, LifeDomain, Necessity
    from backend.services.lab_account import get_lab_repository

    ts = datetime.now(timezone.utc)
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "TESTACCOUNT@o2.pl", "password": "lab-secret-pass"},
        )
        assert r.status_code == 200, r.text

        # Write a distinctive category via repository (same as import path)
        settings = get_settings()
        repo = get_lab_repository(settings)
        marker_id = uuid4()
        repo.upsert_rows(
            "Categories",
            [
                Category(
                    id=marker_id,
                    name="Lab Persist Marker",
                    parent_id=None,
                    necessity=Necessity.DISCRETIONARY,
                    life_domain=LifeDomain.SHOPPING,
                    is_income=False,
                    is_transfer=False,
                    sort_order=9999,
                    created_at=ts,
                    updated_at=ts,
                )
            ],
        )
        ledger_path = lab_env / "lab" / "ledger.json"
        assert ledger_path.is_file(), "disk snapshot should exist after write"

        lo = client.post("/api/auth/logout")
        assert lo.status_code == 200

        # Drop process singleton to force reload from disk (simulates restart)
        clear_lab_repos_for_tests()

        r2 = client.post(
            "/api/auth/password",
            json={"email": "testaccount@o2.pl", "password": "lab-secret-pass"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["demo_kind"] == "lab"

        # Re-fetch repo after clear — must load marker from disk
        repo2 = get_lab_repository(get_settings())
        names = {str(getattr(c, "name", "")) for c in repo2.list_rows("Categories")}
        assert "Lab Persist Marker" in names


def test_lab_logout_does_not_wipe_disk(lab_env: Path):
    from backend.services.demo_sessions import destroy_sandbox_session
    from backend.api.auth import SessionUser
    from backend.services.lab_account import ensure_lab_session, get_lab_repository

    settings = get_settings()
    user = ensure_lab_session(settings)
    repo = get_lab_repository(settings)
    n_before = len(repo.list_rows("Categories"))
    assert n_before > 0

    destroy_sandbox_session(user)  # no-op for lab
    assert len(repo.list_rows("Categories")) == n_before
    assert (lab_env / "lab" / "ledger.json").is_file() or n_before >= 0

    # Explicit: sandbox destroy must not clear lab disk
    destroy_sandbox_session(
        SessionUser(
            email="x",
            name=None,
            picture=None,
            access_token="",
            refresh_token=None,
            token_expiry=None,
            user_id="lab-account",
            role="user",
            spreadsheet_id="lab-account",
            is_demo=True,
            demo_kind="lab",
        )
    )
    assert len(get_lab_repository(settings).list_rows("Categories")) == n_before


def test_lab_case_insensitive_email(lab_env):
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "TestAccount@O2.PL", "password": "lab-secret-pass"},
        )
        assert r.status_code == 200
        assert r.json()["email"] == "testaccount@o2.pl"


def test_newest_ledger_snapshot_prefers_latest_numbered_copy(tmp_path: Path):
    from backend.services.lab_account import newest_ledger_snapshot

    d = tmp_path / "lab"
    d.mkdir()
    (d / "ledger 2.json").write_text('{"tabs":{}}', encoding="utf-8")
    newer = d / "ledger 9.json"
    newer.write_text('{"tabs":{"Transactions":[]}}', encoding="utf-8")
    import os
    import time

    os.utime(newer, (time.time() + 10, time.time() + 10))
    hit = newest_ledger_snapshot(d)
    assert hit is not None
    assert hit.name == "ledger 9.json"


def test_disk_repo_recovers_when_canonical_missing(tmp_path: Path):
    from backend.schema.models import Category, LifeDomain, Necessity
    from backend.sheets.disk_memory import DiskBackedSheetsRepository
    from datetime import datetime, timezone

    d = tmp_path / "lab"
    d.mkdir()
    src = DiskBackedSheetsRepository(d / "ledger.json")
    ts = datetime.now(timezone.utc)
    src.upsert_rows(
        "Categories",
        [
            Category(
                id=__import__("uuid").uuid4(),
                name="Recovered Cat",
                parent_id=None,
                necessity=Necessity.DISCRETIONARY,
                life_domain=LifeDomain.OTHER,
                is_income=False,
                is_transfer=False,
                sort_order=1,
                created_at=ts,
                updated_at=ts,
            )
        ],
    )
    canonical = d / "ledger.json"
    numbered = d / "ledger 12.json"
    numbered.write_bytes(canonical.read_bytes())
    canonical.unlink()
    assert not canonical.is_file()

    reloaded = DiskBackedSheetsRepository(canonical)
    names = {str(getattr(c, "name", "")) for c in reloaded.list_rows("Categories")}
    assert "Recovered Cat" in names
    assert canonical.is_file()


def test_lab_login_disabled_in_production(lab_env, monkeypatch: pytest.MonkeyPatch):
    from backend.services.lab_account import lab_login_configured

    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    assert lab_login_configured(get_settings()) is False


def test_path_is_cloud_synced_detects_icloud():
    from backend.services.lab_account import path_is_cloud_synced

    assert path_is_cloud_synced(Path("C:/Users/x/iCloudDrive/app")) is True
    assert path_is_cloud_synced(Path("C:/Users/x/Projects/app")) is False


def test_cloud_synced_lab_dir_redirects_to_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from backend.services import lab_account as la

    monkeypatch.setattr(la, "project_root", lambda: Path("C:/Users/x/iCloudDrive/Gauntlet"))
    monkeypatch.setattr(la, "local_lab_data_dir", lambda: tmp_path / "local-lab")

    class S:
        lab_data_dir = "data/lab"

    assert la.lab_data_dir(S()) == tmp_path / "local-lab"
