"""Background job registry + admin job endpoints."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

os.environ["AUTH_MODE"] = "dev"
os.environ["SPREADSHEET_ID"] = ""
os.environ["SECRET_KEY"] = "test-secret"
os.environ["YFINANCE_ENABLED"] = "false"

from backend.api.deps import clear_repo_cache
from backend.api.main import create_app
from backend.config import get_settings
from backend.services.jobs import (
    KIND_RUNNERS,
    run_fx_backfill_amounts,
    start_known_job,
)
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import TS, fx_rate
from backend.schema.models import Transaction
from uuid import uuid4


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("CRON_SECRET", "cron-test-secret")
    get_settings.cache_clear()
    clear_repo_cache()
    import backend.api.deps as deps

    deps._DEV_MEMORY_REPO = None
    app = create_app()
    with TestClient(app) as c:
        yield c
    deps._DEV_MEMORY_REPO = None
    clear_repo_cache()
    get_settings.cache_clear()


def test_known_job_kinds():
    assert "fx-full" in KIND_RUNNERS
    assert "fx-fetch-cnb" in KIND_RUNNERS
    assert "fx-backfill-amounts" in KIND_RUNNERS


def test_backfill_job_runner_fills_czk():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "FXRates",
        [fx_rate(rate_date=date(2026, 6, 19), base="USD", rate="21.00")],
    )
    tx = Transaction(
        id=uuid4(),
        account_id=uuid4(),
        booking_date=date(2026, 6, 19),
        amount=Decimal("-100"),
        currency="USD",
        amount_usd=Decimal("-100"),
        amount_czk=None,
        source_institution="Revolut",
        created_at=TS,
        updated_at=TS,
    )
    repo.upsert_rows("Transactions", [tx])
    out = run_fx_backfill_amounts(repo, {"limit": 10, "max_passes": 1, "fetch_missing_rates": False})
    assert out["last"]["filled_czk_approx"] == 1
    stored = repo.list_rows("Transactions")[0]
    assert isinstance(stored, Transaction)
    assert stored.amount_czk == Decimal("-2100.00")


def test_admin_jobs_list_and_start_unknown(client: TestClient):
    r = client.get("/api/admin/jobs")
    assert r.status_code == 200
    body = r.json()
    assert "fx-full" in body["kinds"]
    assert isinstance(body["items"], list)

    r2 = client.post("/api/admin/jobs/not-a-real-job")
    assert r2.status_code == 400


def test_jobs_tick_requires_secret(client: TestClient):
    r = client.post("/api/admin/jobs/tick")
    assert r.status_code == 401
    r2 = client.post(
        "/api/admin/jobs/tick",
        headers={"X-Cron-Secret": "cron-test-secret"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body.get("tick") in {"started", "skipped"}
    if body.get("job_id"):
        # poll once
        j = client.get(f"/api/admin/jobs/{body['job_id']}")
        assert j.status_code == 200
