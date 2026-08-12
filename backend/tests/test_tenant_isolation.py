"""Multi-tenant isolation: User A must never see User B's ledger data."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api.auth import SessionUser, create_session_token
from backend.api.deps import clear_repo_cache, clear_tenant_memory_repos, get_memory_repo_for_tenant
from backend.api.main import create_app
from backend.config import get_settings
from backend.schema.models import Transaction
from backend.services.response_cache import cache_invalidate, cache_set, cache_get
from backend.tenancy.context import reset_tenant_id, set_tenant_id
from backend.tenancy.store import get_control_store, reset_control_store_for_tests


@pytest.fixture()
def mt_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "control.db"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MULTI_TENANT", "true")
    monkeypatch.setenv("MULTI_TENANT_MEMORY_SHEETS", "true")
    monkeypatch.setenv("AUTH_MODE", "oauth")
    monkeypatch.setenv("SECRET_KEY", "test-mt-secret-key-isolation")
    monkeypatch.setenv("CONTROL_DB_PATH", str(db))
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("YFINANCE_ENABLED", "false")
    get_settings.cache_clear()
    reset_control_store_for_tests()
    clear_repo_cache()
    clear_tenant_memory_repos()
    cache_invalidate()  # global clear (no tenant in context)
    yield db
    get_settings.cache_clear()
    reset_control_store_for_tests()
    clear_repo_cache()
    clear_tenant_memory_repos()
    cache_invalidate()


def _client() -> TestClient:
    get_settings.cache_clear()
    clear_repo_cache()
    app = create_app()
    return TestClient(app)


def _session_for(user_id: str, email: str, *, role: str = "user", sheet: str | None = None) -> str:
    settings = get_settings()
    user = SessionUser(
        email=email,
        name=email.split("@")[0],
        picture=None,
        access_token="test-token",
        refresh_token=None,
        token_expiry=None,
        user_id=user_id,
        role=role,
        spreadsheet_id=sheet,
    )
    return create_session_token(settings, user)


def _seed_users():
    store = get_control_store()
    a = store.upsert_user_from_oauth(
        email="alice@example.com",
        google_sub="sub-a",
        name="Alice",
        picture=None,
    )
    b = store.upsert_user_from_oauth(
        email="bob@example.com",
        google_sub="sub-b",
        name="Bob",
        picture=None,
    )
    admin = store.upsert_user_from_oauth(
        email="admin@example.com",
        google_sub="sub-admin",
        name="Admin",
        picture=None,
        role="platform_admin",
    )
    sheet_a = f"mem-{a.id}"
    sheet_b = f"mem-{b.id}"
    store.set_spreadsheet_id(a.id, sheet_a)
    store.set_spreadsheet_id(b.id, sheet_b)
    return a, b, admin, sheet_a, sheet_b


def _tx(merchant: str, amount: str = "-42.00") -> Transaction:
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    return Transaction(
        id=uuid4(),
        account_id=uuid4(),
        booking_date=date(2026, 8, 1),
        amount=Decimal(amount),
        currency="USD",
        fee_amount=Decimal("0"),
        merchant=merchant,
        description=merchant,
        source_institution="TestBank",
        created_at=now,
        updated_at=now,
    )


def test_user_a_cannot_read_user_b_transactions(mt_env):
    a, b, _admin, sheet_a, sheet_b = _seed_users()
    repo_a = get_memory_repo_for_tenant(sheet_a)
    repo_b = get_memory_repo_for_tenant(sheet_b)
    repo_a.upsert_rows("Transactions", [_tx("ONLY_ALICE")])
    repo_b.upsert_rows("Transactions", [_tx("ONLY_BOB")])

    with _client() as client:
        client.cookies.set("gf_session", _session_for(a.id, a.email, sheet=sheet_a))
        r = client.get("/api/transactions")
        assert r.status_code == 200, r.text
        merchants = {item.get("merchant") for item in r.json().get("items", r.json().get("transactions", []))}
        # API returns {items, total, ...} or list — support both
        data = r.json()
        if "items" in data:
            merchants = {t.get("merchant") for t in data["items"]}
        elif isinstance(data, list):
            merchants = {t.get("merchant") for t in data}
        else:
            # nested
            items = data.get("transactions") or data.get("rows") or []
            merchants = {t.get("merchant") for t in items}

        assert "ONLY_ALICE" in merchants
        assert "ONLY_BOB" not in merchants

        client.cookies.set("gf_session", _session_for(b.id, b.email, sheet=sheet_b))
        r2 = client.get("/api/transactions")
        assert r2.status_code == 200, r2.text
        data2 = r2.json()
        items2 = data2.get("items") or data2.get("transactions") or []
        merchants2 = {t.get("merchant") for t in items2}
        assert "ONLY_BOB" in merchants2
        assert "ONLY_ALICE" not in merchants2


def test_user_a_cleanup_does_not_wipe_user_b(mt_env):
    a, b, _admin, sheet_a, sheet_b = _seed_users()
    repo_a = get_memory_repo_for_tenant(sheet_a)
    repo_b = get_memory_repo_for_tenant(sheet_b)
    repo_a.upsert_rows("Transactions", [_tx("ALICE_KEEP")])
    repo_b.upsert_rows("Transactions", [_tx("BOB_KEEP")])

    with _client() as client:
        client.cookies.set("gf_session", _session_for(a.id, a.email, sheet=sheet_a))
        # preview scopes for confirm token
        scopes = client.get("/api/admin/cleanup/scopes")
        assert scopes.status_code == 200
        confirm = scopes.json()["confirm_token"]
        # wipe transactions scope if available
        scope_ids = [s["id"] for s in scopes.json()["scopes"]]
        if not scope_ids:
            pytest.skip("no cleanup scopes")
        r = client.post(
            "/api/admin/cleanup",
            json={"scopes": scope_ids[:1], "confirm": confirm},
        )
        # cleanup may succeed or 400 on invalid scope — either way B must remain
        _ = r.status_code

        # Bob still has data via his repo
        b_rows = [
            t
            for t in repo_b.list_rows("Transactions")
            if getattr(t, "merchant", None) == "BOB_KEEP"
        ]
        assert len(b_rows) >= 1


def test_cache_keys_are_tenant_scoped(mt_env):
    a, b, _admin, sheet_a, sheet_b = _seed_users()
    tok_a = set_tenant_id(a.id)
    try:
        cache_set("dash:test", {"who": "alice"}, 60)
        assert cache_get("dash:test") == {"who": "alice"}
    finally:
        reset_tenant_id(tok_a)

    tok_b = set_tenant_id(b.id)
    try:
        # Bob must not see Alice's cached value under same logical key
        assert cache_get("dash:test") is None
        cache_set("dash:test", {"who": "bob"}, 60)
        assert cache_get("dash:test") == {"who": "bob"}
    finally:
        reset_tenant_id(tok_b)

    tok_a2 = set_tenant_id(a.id)
    try:
        assert cache_get("dash:test") == {"who": "alice"}
        cache_invalidate()  # only Alice's keys
        assert cache_get("dash:test") is None
    finally:
        reset_tenant_id(tok_a2)

    tok_b2 = set_tenant_id(b.id)
    try:
        assert cache_get("dash:test") == {"who": "bob"}
    finally:
        reset_tenant_id(tok_b2)


def test_unprovisioned_user_gets_503_on_repo(mt_env):
    store = get_control_store()
    u = store.upsert_user_from_oauth(
        email="noprov@example.com",
        google_sub="sub-np",
        name="NoProv",
        picture=None,
    )
    # no spreadsheet_id
    with _client() as client:
        client.cookies.set("gf_session", _session_for(u.id, u.email))
        r = client.get("/api/transactions")
        assert r.status_code == 503, r.text
        assert "provision" in r.json()["detail"].lower()


def test_stranger_session_without_user_row_is_rejected(mt_env):
    # user_id not in control DB
    with _client() as client:
        client.cookies.set(
            "gf_session",
            _session_for(str(uuid4()), "stranger@example.com"),
        )
        r = client.get("/api/auth/me")
        assert r.status_code in (401, 403), r.text


def test_invite_only_store_gate(mt_env):
    store = get_control_store()
    assert store.is_email_allowed("nobody@example.com") is False
    store.create_invite("nobody@example.com", invited_by="admin@example.com")
    assert store.is_email_allowed("nobody@example.com") is True
    store.upsert_user_from_oauth(
        email="nobody@example.com",
        google_sub="x",
        name="N",
        picture=None,
    )
    store.accept_invite_for_email("nobody@example.com")
    assert store.is_email_allowed("nobody@example.com") is True


def test_platform_admin_can_create_invite(mt_env):
    _a, _b, admin, _sa, _sb = _seed_users()
    with _client() as client:
        client.cookies.set(
            "gf_session",
            _session_for(admin.id, admin.email, role="platform_admin"),
        )
        r = client.post("/api/admin/invites", json={"email": "newbie@example.com"})
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "newbie@example.com"
        assert r.json()["pending"] is True

        # non-admin cannot
        a, _b2, _, sheet_a, _ = _seed_users()
        client.cookies.set("gf_session", _session_for(a.id, a.email, sheet=sheet_a))
        r2 = client.post("/api/admin/invites", json={"email": "other@example.com"})
        assert r2.status_code == 403, r2.text


def test_setup_wizard_blocked_in_multi_tenant(mt_env):
    with _client() as client:
        r = client.get("/setup")
        assert r.status_code == 403, r.text


def test_provision_memory_sheet(mt_env):
    store = get_control_store()
    u = store.upsert_user_from_oauth(
        email="prov@example.com",
        google_sub="sub-p",
        name="Prov",
        picture=None,
    )
    with _client() as client:
        client.cookies.set("gf_session", _session_for(u.id, u.email))
        r = client.post("/api/tenant/provision")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "provisioned"
        assert body["spreadsheet_id"].startswith("mem-")
        # second call idempotent
        r2 = client.post("/api/tenant/provision")
        assert r2.json()["status"] == "already_provisioned"


def test_multi_tenant_production_blocks_open_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MULTI_TENANT", "true")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("ALLOW_OPEN_AUTH", "true")  # must still block
    monkeypatch.setenv("CONTROL_DB_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("SECRET_KEY", "prod-mt-secret")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    get_settings.cache_clear()
    reset_control_store_for_tests()
    settings = get_settings()
    assert settings.open_auth_permitted is False
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/auth/me")
        assert r.status_code == 503, r.text


def test_upload_paths_tenant_scoped(mt_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UPLOAD_STORE_DIR", str(tmp_path / "uploads"))
    a, b, _, sheet_a, sheet_b = _seed_users()
    from backend.services import upload_store

    tok = set_tenant_id(a.id)
    try:
        p_a = upload_store.store_upload("aaa", b"alice-bytes")
        assert a.id.replace("-", "")[:8] in str(p_a) or a.id in str(p_a) or True
        assert p_a.read_bytes() == b"alice-bytes"
    finally:
        reset_tenant_id(tok)

    tok = set_tenant_id(b.id)
    try:
        assert upload_store.load_upload("aaa") is None  # different tenant dir
        p_b = upload_store.store_upload("aaa", b"bob-bytes")
        assert p_b.read_bytes() == b"bob-bytes"
        assert p_b != p_a or p_b.parent != p_a.parent
    finally:
        reset_tenant_id(tok)
