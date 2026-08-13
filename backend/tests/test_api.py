"""API smoke tests using in-memory repository (AUTH_MODE=dev)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Force dev memory mode before app import
os.environ["AUTH_MODE"] = "dev"
os.environ["SPREADSHEET_ID"] = ""
os.environ["SECRET_KEY"] = "test-secret"
os.environ["YFINANCE_ENABLED"] = "false"

from backend.api.deps import clear_repo_cache, get_settings
from backend.api.main import create_app
from backend.config import get_settings as gs

get_settings.cache_clear()
gs.cache_clear()
clear_repo_cache()

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("YFINANCE_ENABLED", "false")
    get_settings.cache_clear()
    gs.cache_clear()
    clear_repo_cache()
    # reset memory repo
    import backend.api.deps as deps

    deps._DEV_MEMORY_REPO = None
    app = create_app()
    with TestClient(app) as c:
        yield c
    deps._DEV_MEMORY_REPO = None
    clear_repo_cache()


def test_health(client: TestClient):
    for path in ("/health", "/api/health"):
        r = client.get(path)
        assert r.status_code == 200, path
        body = r.json()
        assert body["status"] == "ok"
        assert body["auth_mode"] == "dev"


def _poll_upload_job(client: TestClient, job_id: str, *, timeout_s: float = 30.0):
    import time

    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        j = client.get(f"/api/upload/jobs/{job_id}")
        assert j.status_code == 200, j.text
        last = j.json()
        if last["status"] in {"done", "error"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"upload job {job_id} did not finish: {last}")


def test_upload_and_list_transactions(client: TestClient):
    path = FIXTURES / "raiffeisen_sample.csv"
    with path.open("rb") as f:
        r = client.post(
            "/api/upload",
            files={"file": ("raiffeisen_sample.csv", f, "text/csv")},
        )
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted.get("job_id")
    job = _poll_upload_job(client, accepted["job_id"])
    assert job["status"] == "done", job
    body = job["result"]
    assert body["status"] in {"imported", "already_imported"}
    if body["status"] == "imported":
        assert body["rows_parsed"] == 4
        assert body["transactions_written"] >= 1
        assert body["parser_key"] == "raiffeisen_cz"

    # re-upload → already_imported (async job still)
    with path.open("rb") as f:
        r2 = client.post(
            "/api/upload",
            files={"file": ("raiffeisen_sample.csv", f, "text/csv")},
        )
    assert r2.status_code == 200
    job2 = _poll_upload_job(client, r2.json()["job_id"])
    assert job2["status"] == "done", job2
    assert job2["result"]["status"] == "already_imported"

    r3 = client.get("/api/transactions")
    assert r3.status_code == 200
    assert r3.json()["total"] >= 1


def test_list_transactions_by_ids(client: TestClient):
    path = FIXTURES / "raiffeisen_sample.csv"
    with path.open("rb") as f:
        r = client.post(
            "/api/upload",
            files={"file": ("raiffeisen_sample.csv", f, "text/csv")},
        )
    assert r.status_code == 200, r.text
    job = _poll_upload_job(client, r.json()["job_id"])
    assert job["status"] == "done", job

    listed = client.get("/api/transactions?limit=50")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) >= 2
    want = [items[0]["id"], items[1]["id"]]
    fetched = client.get("/api/transactions", params={"ids": ",".join(want)})
    assert fetched.status_code == 200
    got = {row["id"] for row in fetched.json()["items"]}
    assert got == set(want)
    assert fetched.json()["total"] == 2


def test_categories_and_dashboard(client: TestClient):
    r = client.get("/api/categories")
    assert r.status_code == 200
    assert "items" in r.json()

    r2 = client.get("/api/dashboard-summary", params={"period_key": "this_month"})
    assert r2.status_code == 200
    body = r2.json()
    assert "cashflow" in body
    assert "portfolio" in body
    assert "pace" in body
    assert "spending" in body
    assert "portfolio_compact" in body
    assert "income_usd" in body["cashflow"]


def test_alerts_and_snapshot(client: TestClient):
    r = client.get("/api/alerts")
    assert r.status_code == 200
    assert "items" in r.json()

    r2 = client.get("/api/investments/snapshot")
    assert r2.status_code == 200
    body = r2.json()
    assert "tax_runway" in body
    assert "realized_lifetime_usd" in body
    assert "living_draw_12m" in body
    assert "sold_usd" in body["living_draw_12m"]
    assert "draw_usd" in body["living_draw_12m"]
    assert "fees" in body
    assert "total_fees_usd" in body["fees"]
    assert "fees_by_event_type" in body["fees"]
    assert "staking" in body
    assert "mark_usd_total" in body["staking"]
    assert "by_ticker" in body["staking"]
    assert "health" in body
    assert "grade" in body["health"]
    assert "concentration" in body["health"]
    assert "price_status" in body
    assert "mode" in body["price_status"]
    assert "cashflow_monthly" in body
    assert isinstance(body["cashflow_monthly"], list)


def test_tax_report(client: TestClient):
    r = client.get("/api/tax-report")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert "disposals" in body
    assert "open_positions" in body


def test_openapi_available(client: TestClient):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/upload" in paths
    assert "/api/transactions" in paths
    assert "/api/prices/refresh" in paths
    assert "/api/tax-report" in paths
    assert "/api/sheets/status" in paths
    assert "/api/alerts" in paths
    assert "/api/investments/snapshot" in paths
    assert "/api/categories/bulk-override" in paths
    assert "/api/health" in paths
    assert "/health" in paths


def test_bulk_override_category(client: TestClient):
    import backend.api.deps as deps
    from backend.tests.helpers import tx as make_tx

    r = client.post("/api/categories/ensure-defaults")
    assert r.status_code == 200
    cats = client.get("/api/categories").json()["items"]
    assert cats
    cat_id = cats[0]["id"]

    repo = deps._DEV_MEMORY_REPO
    assert repo is not None
    t1 = make_tx(merchant="Cafe A", description="latte")
    t2 = make_tx(merchant="Cafe B", description="tea")
    repo.upsert_rows("Transactions", [t1, t2])

    r = client.post(
        "/api/categories/bulk-override",
        json={
            "category_id": cat_id,
            "transaction_ids": [str(t1.id), str(t2.id)],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 2
    assert body["missing"] == 0
    assert body["category_id"] == cat_id

    items = {
        str(t["id"]): t
        for t in client.get("/api/transactions?limit=50").json()["items"]
    }
    assert items[str(t1.id)]["category_id"] == cat_id
    assert items[str(t1.id)]["category_override"] is True
    assert items[str(t2.id)]["category_override"] is True


def test_bulk_override_can_force_internal_transfer(client: TestClient):
    import backend.api.deps as deps
    from backend.schema.default_categories import CAT_GROCERIES
    from backend.tests.helpers import tx as make_tx

    r = client.post("/api/categories/ensure-defaults")
    assert r.status_code == 200
    repo = deps._DEV_MEMORY_REPO
    assert repo is not None
    t1 = make_tx(merchant="Raiffeisen", description="Revolut top-up", amount="-210000")
    repo.upsert_rows("Transactions", [t1])

    r = client.post(
        "/api/categories/bulk-override",
        json={
            "category_id": str(CAT_GROCERIES),
            "transaction_ids": [str(t1.id)],
            "is_internal_transfer": True,
        },
    )
    assert r.status_code == 200, r.text
    items = {
        str(t["id"]): t
        for t in client.get(
            "/api/transactions", params={"tx_ids": str(t1.id), "limit": 1}
        ).json()["items"]
    }
    assert items[str(t1.id)]["is_internal_transfer"] is True
    assert items[str(t1.id)]["category_id"] == str(CAT_GROCERIES)


def test_restore_assignments_undo(client: TestClient):
    import backend.api.deps as deps
    from backend.tests.helpers import tx as make_tx

    r = client.post("/api/categories/ensure-defaults")
    assert r.status_code == 200
    cats = client.get("/api/categories").json()["items"]
    cat_id = cats[0]["id"]

    repo = deps._DEV_MEMORY_REPO
    assert repo is not None
    t1 = make_tx(merchant="Undo Me", description="x")
    repo.upsert_rows("Transactions", [t1])

    r = client.post(
        "/api/categories/bulk-override",
        json={"category_id": cat_id, "transaction_ids": [str(t1.id)]},
    )
    assert r.status_code == 200

    r = client.post(
        "/api/categories/restore-assignments",
        json={
            "items": [
                {
                    "transaction_id": str(t1.id),
                    "category_id": None,
                    "category_override": False,
                    "is_internal_transfer": False,
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1

    items = {
        str(t["id"]): t
        for t in client.get("/api/transactions?limit=50").json()["items"]
    }
    assert items[str(t1.id)]["category_id"] in (None, "")
    assert items[str(t1.id)]["category_override"] is False


def test_sheets_status_memory_mode(client: TestClient):
    r = client.get("/api/sheets/status")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "memory"
