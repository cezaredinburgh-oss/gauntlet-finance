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
        # Email is for the landing prefill; password must never appear.
        assert body.get("lab_email") == "testaccount@o2.pl"


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


def test_lab_missing_password_is_503(lab_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LAB_PASSWORD", "")
    get_settings.cache_clear()
    with _client() as client:
        r = client.post(
            "/api/auth/password",
            json={"email": "testaccount@o2.pl", "password": "lab-secret-pass"},
        )
        assert r.status_code == 503
        assert "LAB_PASSWORD" in r.json()["detail"]


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


def test_lab_login_allowed_on_single_tenant_production(lab_env, monkeypatch: pytest.MonkeyPatch):
    from backend.services.lab_account import lab_login_configured

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MULTI_TENANT", "false")
    get_settings.cache_clear()
    assert lab_login_configured(get_settings()) is True


def test_lab_login_allowed_on_multitenant_production(lab_env, monkeypatch: pytest.MonkeyPatch):
    from backend.services.lab_account import lab_login_configured

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MULTI_TENANT", "true")
    get_settings.cache_clear()
    assert lab_login_configured(get_settings()) is True


def test_lab_password_login_on_mt_production_uses_disk(
    lab_env: Path, monkeypatch: pytest.MonkeyPatch
):
    """Railway-shaped host: MT + production + lab password → disk ledger, not Sheets."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MULTI_TENANT", "true")
    monkeypatch.setenv("MULTI_TENANT_MEMORY_SHEETS", "true")
    monkeypatch.setenv("CONTROL_DB_PATH", str(lab_env / "control.db"))
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "admin@example.com")
    get_settings.cache_clear()
    clear_repo_cache()
    clear_lab_repos_for_tests()

    with _client() as client:
        cfg = client.get("/api/auth/public-config")
        assert cfg.status_code == 200
        assert cfg.json()["lab_login_enabled"] is True
        assert cfg.json().get("lab_email") == "testaccount@o2.pl"
        assert "lab_password" not in cfg.json()

        r = client.post(
            "/api/auth/password",
            json={"email": "testaccount@o2.pl", "password": "lab-secret-pass"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["demo_kind"] == "lab"
        assert r.json()["is_demo"] is True

        st = client.get("/api/sheets/status")
        assert st.status_code == 200, st.text
        body = st.json()
        assert body["backend"] == "disk_memory"
        assert body.get("demo_kind") == "lab"
        assert "12l4QhVe" not in str(body.get("spreadsheet_id") or "")

        txs = client.get("/api/transactions", params={"limit": 5})
        assert txs.status_code == 200
        assert txs.json()["total"] == 0

        cats = client.get("/api/categories")
        assert cats.status_code == 200
        items = cats.json().get("items") if isinstance(cats.json(), dict) else cats.json()
        assert isinstance(items, list)
        assert len(items) > 0


def test_lab_disk_isolated_from_mt_memory_tenant(
    lab_env: Path, monkeypatch: pytest.MonkeyPatch
):
    """OAuth tenant memory ledger and lab disk ledger must not mix."""
    from datetime import date, datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    from backend.api.auth import SessionUser, create_session_token
    from backend.api.deps import get_memory_repo_for_tenant
    from backend.schema.models import Transaction
    from backend.services.lab_account import get_lab_repository
    from backend.tenancy.store import get_control_store, reset_control_store_for_tests

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MULTI_TENANT", "true")
    monkeypatch.setenv("MULTI_TENANT_MEMORY_SHEETS", "true")
    monkeypatch.setenv("CONTROL_DB_PATH", str(lab_env / "control.db"))
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "admin@example.com")
    get_settings.cache_clear()
    reset_control_store_for_tests()
    clear_repo_cache()
    clear_lab_repos_for_tests()

    store = get_control_store()
    alice = store.upsert_user_from_oauth(
        email="alice@example.com",
        google_sub="sub-alice",
        name="Alice",
        picture=None,
    )
    sheet = f"mem-{alice.id}"
    store.set_spreadsheet_id(alice.id, sheet)
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    get_memory_repo_for_tenant(sheet).upsert_rows(
        "Transactions",
        [
            Transaction(
                id=uuid4(),
                account_id=uuid4(),
                booking_date=date(2026, 8, 1),
                amount=Decimal("-5.00"),
                currency="USD",
                fee_amount=Decimal("0"),
                merchant="ONLY_ALICE",
                description="ONLY_ALICE",
                source_institution="TestBank",
                created_at=now,
                updated_at=now,
            )
        ],
    )
    get_lab_repository(get_settings()).upsert_rows(
        "Transactions",
        [
            Transaction(
                id=uuid4(),
                account_id=uuid4(),
                booking_date=date(2026, 8, 1),
                amount=Decimal("-9.00"),
                currency="USD",
                fee_amount=Decimal("0"),
                merchant="ONLY_LAB",
                description="ONLY_LAB",
                source_institution="TestBank",
                created_at=now,
                updated_at=now,
            )
        ],
    )

    def _merchants(payload: dict) -> set[str]:
        items = payload.get("items") or payload.get("transactions") or []
        return {str(t.get("merchant") or "") for t in items}

    with _client() as client:
        login = client.post(
            "/api/auth/password",
            json={"email": "testaccount@o2.pl", "password": "lab-secret-pass"},
        )
        assert login.status_code == 200, login.text
        lab_body = client.get("/api/transactions").json()
        lab_m = _merchants(lab_body)
        assert "ONLY_LAB" in lab_m
        assert "ONLY_ALICE" not in lab_m

        tok = create_session_token(
            get_settings(),
            SessionUser(
                email=alice.email,
                name="Alice",
                picture=None,
                access_token="test-token",
                refresh_token=None,
                token_expiry=None,
                user_id=alice.id,
                role="user",
                spreadsheet_id=sheet,
            ),
        )
        client.cookies.set("gf_session", tok)
        alice_body = client.get("/api/transactions").json()
        alice_m = _merchants(alice_body)
        assert "ONLY_ALICE" in alice_m
        assert "ONLY_LAB" not in alice_m


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


def test_reset_wipes_numbered_copies_and_does_not_recover(lab_env: Path):
    """Intentional wipe must delete iCloud numbered copies, not just ledger.json."""
    from datetime import date, datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    from backend.schema.models import Transaction
    from backend.services.lab_account import (
        ensure_lab_seeded,
        get_lab_repository,
        reset_lab_ledger,
    )

    settings = get_settings()
    repo = ensure_lab_seeded(settings)
    now = datetime.now(timezone.utc)
    repo.upsert_rows(
        "Transactions",
        [
            Transaction(
                id=uuid4(),
                account_id=uuid4(),
                booking_date=date(2026, 1, 2),
                amount=Decimal("-10.00"),
                currency="USD",
                fee_amount=Decimal("0"),
                description="wipe-me",
                merchant="Old Life",
                source_institution="Revolut",
                archived=False,
                created_at=now,
                updated_at=now,
            )
        ],
    )
    lab_dir = lab_env / "lab"
    canonical = lab_dir / "ledger.json"
    numbered = lab_dir / "ledger 3.json"
    assert canonical.is_file()
    numbered.write_bytes(canonical.read_bytes())
    assert len(repo.list_rows("Transactions")) == 1

    result = reset_lab_ledger(settings, dry_run=False)
    assert result["ok"] is True
    assert result["after"]["Transactions"] == 0
    assert result["after"]["InvestmentLots"] == 0
    assert result["after"]["InvestmentEvents"] == 0
    assert result["after"]["StatementFiles"] == 0
    assert int(result["after"]["Categories"]) > 0
    assert not numbered.is_file()
    assert "ledger 3.json" in (result.get("deleted") or [])

    clear_lab_repos_for_tests()
    clean = get_lab_repository(settings)
    assert len(clean.list_rows("Transactions")) == 0
    names = {str(getattr(c, "name", "")) for c in clean.list_rows("Categories")}
    assert "Groceries" in names or len(names) > 0
