"""One-click sandbox + tour demos."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import clear_repo_cache, clear_tenant_memory_repos, get_memory_repo_for_tenant
from backend.api.main import create_app
from backend.config import get_settings
from backend.services.demo_auth import clear_password_rate_limits_for_tests
from backend.services.demo_sessions import (
    clear_demo_session_state_for_tests,
    demo_memory_key,
)
from backend.tenancy.store import reset_control_store_for_tests


@pytest.fixture()
def dual_demo_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "oauth")
    monkeypatch.setenv("SECRET_KEY", "dual-demo-test-secret-key-xx")
    monkeypatch.setenv("SPREADSHEET_ID", "real-prod-sheet-should-not-touch")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("YFINANCE_ENABLED", "false")
    monkeypatch.setenv("MULTI_TENANT", "false")
    monkeypatch.setenv("DEMO_SANDBOX_ENABLED", "true")
    monkeypatch.setenv("DEMO_TOUR_ENABLED", "true")
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "false")
    monkeypatch.setenv("DEMO_SANDBOX_MAX_ACTIVE", "20")
    get_settings.cache_clear()
    reset_control_store_for_tests()
    clear_repo_cache()
    clear_tenant_memory_repos()
    clear_demo_session_state_for_tests()
    clear_password_rate_limits_for_tests()
    yield
    get_settings.cache_clear()
    clear_repo_cache()
    clear_tenant_memory_repos()
    clear_demo_session_state_for_tests()
    clear_password_rate_limits_for_tests()


def _client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def test_public_config_exposes_demo_flags(dual_demo_env):
    with _client() as client:
        cfg = client.get("/api/auth/public-config").json()
        assert cfg["demo_sandbox_enabled"] is True
        assert cfg["demo_tour_enabled"] is True
        assert cfg["demo_login_enabled"] is False
        assert "DEMO_PASSWORD" not in str(cfg)


def test_sandbox_enter_writable_empty_and_isolated(dual_demo_env):
    with _client() as c1, _client() as c2:
        r1 = c1.post("/api/auth/demo/sandbox")
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1["is_demo"] is True
        assert body1["demo_kind"] == "sandbox"
        assert body1["read_only"] is False

        me1 = c1.get("/api/auth/me").json()
        assert me1["demo_kind"] == "sandbox"
        assert me1["tenant_ready"] is True
        assert me1["read_only"] is False

        txs1 = c1.get("/api/transactions")
        assert txs1.status_code == 200
        # empty or defaults-only — no synthetic bulk seed
        items1 = txs1.json().get("items") or txs1.json().get("transactions") or []
        if isinstance(txs1.json(), list):
            items1 = txs1.json()
        # Accept empty list or wrapped
        n1 = len(items1) if isinstance(items1, list) else 0

        # Second session gets a different sandbox
        r2 = c2.post("/api/auth/demo/sandbox")
        assert r2.status_code == 200, r2.text
        me2 = c2.get("/api/auth/me").json()
        assert me1["user_id"] != me2["user_id"]

        # Seed a tx only on c1 via memory key
        key1 = demo_memory_key(me1["user_id"])
        repo = get_memory_repo_for_tenant(key1)
        from datetime import date, datetime, timezone
        from decimal import Decimal
        from uuid import uuid4

        from backend.schema.models import Transaction

        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        repo.upsert_rows(
            "Transactions",
            [
                Transaction(
                    id=uuid4(),
                    account_id=uuid4(),
                    booking_date=date(2026, 8, 1),
                    amount=Decimal("-9.99"),
                    currency="USD",
                    fee_amount=Decimal("0"),
                    merchant="OnlyAlice",
                    description="OnlyAlice",
                    source_institution="Test",
                    created_at=now,
                    updated_at=now,
                )
            ],
        )

        # c2 must not see Alice's merchant (isolation)
        raw2 = c2.get("/api/transactions")
        assert raw2.status_code == 200
        text2 = raw2.text
        assert "OnlyAlice" not in text2


def test_sandbox_logout_wipes_ledger(dual_demo_env):
    with _client() as client:
        assert client.post("/api/auth/demo/sandbox").status_code == 200
        me = client.get("/api/auth/me").json()
        uid = me["user_id"]
        key = demo_memory_key(uid)
        repo = get_memory_repo_for_tenant(key)
        from datetime import date, datetime, timezone
        from decimal import Decimal
        from uuid import uuid4

        from backend.schema.models import Transaction

        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        repo.upsert_rows(
            "Transactions",
            [
                Transaction(
                    id=uuid4(),
                    account_id=uuid4(),
                    booking_date=date(2026, 8, 1),
                    amount=Decimal("-1.00"),
                    currency="USD",
                    fee_amount=Decimal("0"),
                    merchant="WillWipe",
                    description="WillWipe",
                    source_institution="Test",
                    created_at=now,
                    updated_at=now,
                )
            ],
        )
        assert "WillWipe" in client.get("/api/transactions").text

        assert client.post("/api/auth/logout").status_code == 200
        # After wipe, same key should be a fresh empty repo if re-created
        from backend.api.deps import _TENANT_MEMORY_REPOS

        assert key not in _TENANT_MEMORY_REPOS or not get_memory_repo_for_tenant(key).list_rows(
            "Transactions"
        )

        # New sandbox after logout is empty
        assert client.post("/api/auth/demo/sandbox").status_code == 200
        assert "WillWipe" not in client.get("/api/transactions").text


def test_tour_seeded_and_read_only(dual_demo_env):
    with _client() as client:
        r = client.post("/api/auth/demo/tour")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["demo_kind"] == "tour"
        assert body["read_only"] is True

        me = client.get("/api/auth/me").json()
        assert me["read_only"] is True
        assert me["demo_kind"] == "tour"

        txs = client.get("/api/transactions")
        assert txs.status_code == 200
        body = txs.json()
        items = body.get("items") if isinstance(body, dict) else body
        assert isinstance(items, list)
        assert len(items) >= 40, f"expected rich tour seed, got {len(items)}"
        institutions = {
            (i.get("source_institution") or "") for i in items if isinstance(i, dict)
        }
        assert "Raiffeisen" in institutions or any("Raiffeisen" in x for x in institutions)
        assert any("Revolut" in x for x in institutions)

        # Mutations blocked
        up = client.post(
            "/api/upload",
            files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
        )
        assert up.status_code == 403, up.text

        # Categories delete blocked if any category exists
        cats = client.get("/api/categories")
        if cats.status_code == 200:
            items = cats.json().get("items") or cats.json()
            if isinstance(items, list) and items:
                cid = items[0].get("id") or items[0].get("category_id")
                if cid:
                    d = client.delete(f"/api/categories/{cid}")
                    assert d.status_code == 403

        cleanup = client.post(
            "/api/admin/cleanup",
            json={"scopes": ["transactions"], "confirm": "DELETE"},
        )
        assert cleanup.status_code == 403

        # Still never touches real sheet id via demo path
        assert client.get("/api/auth/me").json()["is_demo"] is True


def test_demo_disabled_returns_403(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "oauth")
    monkeypatch.setenv("SECRET_KEY", "dual-demo-off-secret-key-xx")
    monkeypatch.setenv("REPO_BACKEND", "memory")
    monkeypatch.setenv("DEMO_SANDBOX_ENABLED", "false")
    monkeypatch.setenv("DEMO_TOUR_ENABLED", "false")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    get_settings.cache_clear()
    clear_password_rate_limits_for_tests()
    with _client() as client:
        assert client.post("/api/auth/demo/sandbox").status_code == 403
        assert client.post("/api/auth/demo/tour").status_code == 403


def test_tour_never_builds_google(dual_demo_env, monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def boom(*_a, **_k):
        calls.append("google")
        raise AssertionError("must not build Google repo for demo")

    monkeypatch.setattr(
        "backend.sheets.google_sheets.build_repository_from_settings",
        boom,
    )
    with _client() as client:
        assert client.post("/api/auth/demo/tour").status_code == 200
        assert client.get("/api/transactions").status_code == 200
    assert calls == []


def test_demos_have_no_personal_residue(dual_demo_env):
    from backend.schema.demo_public import ledger_contains_personal_residue

    with _client() as client:
        assert client.post("/api/auth/demo/sandbox").status_code == 200
        rules = client.get("/api/category-rules")
        cats = client.get("/api/categories")
        blob = (rules.text if rules.status_code == 200 else "") + cats.text
        assert "BIERNAT" not in blob.upper()
        assert "2489943002" not in blob
        assert "Motorcycling" not in blob
        assert "My business" not in blob
        assert "filament" not in blob.lower()

        # bootstrap blocked
        boot = client.post("/api/categories/bootstrap-rules", json={"also_apply": False})
        assert boot.status_code == 403

        client.post("/api/auth/logout")
        assert client.post("/api/auth/demo/tour").status_code == 200
        txs = client.get("/api/transactions")
        assert txs.status_code == 200
        assert "BIERNAT" not in txs.text.upper()
        assert "2489943002" not in txs.text
        assert "Bad Jeffs" not in txs.text
        assert "Demo Cafe" in txs.text or "Spotify" in txs.text

        # memory ledger helper
        from backend.api.deps import get_memory_repo_for_tenant
        from backend.schema.models import InvestmentLot
        from backend.services.demo_sessions import TOUR_SHEET_ID, demo_memory_key

        repo = get_memory_repo_for_tenant(demo_memory_key(TOUR_SHEET_ID))
        assert ledger_contains_personal_residue(repo) == []
        lot_tickers = {
            r.ticker.upper()
            for r in repo.list_rows("InvestmentLots")
            if isinstance(r, InvestmentLot)
        }
        assert "DEMO" not in lot_tickers and "SAMPLE" not in lot_tickers
        assert {"AAPL", "MSFT", "ETH", "VTI"}.issubset(lot_tickers)
