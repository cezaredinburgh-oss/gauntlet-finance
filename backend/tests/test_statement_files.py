"""Statement files list + retry with stored bytes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["AUTH_MODE"] = "dev"
os.environ["SPREADSHEET_ID"] = ""
os.environ["SECRET_KEY"] = "test-secret"
os.environ["YFINANCE_ENABLED"] = "false"

from backend.api.deps import clear_repo_cache
from backend.api.main import create_app
from backend.config import get_settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("UPLOAD_STORE_DIR", str(tmp_path / "uploads"))
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


def test_statement_files_after_upload(client: TestClient):
    path = FIXTURES / "raiffeisen_sample.csv"
    with path.open("rb") as f:
        r = client.post(
            "/api/upload",
            files={"file": ("raiffeisen_sample.csv", f, "text/csv")},
        )
    assert r.status_code == 200, r.text

    hist = client.get("/api/statement-files")
    assert hist.status_code == 200
    body = hist.json()
    assert body["total"] >= 1
    item = body["items"][0]
    assert item["original_filename"] == "raiffeisen_sample.csv"
    assert item["status"].upper() in {"IMPORTED", "ERROR", "PENDING"}
    assert item["has_stored_bytes"] is True

    # Successful import is not retryable
    if item["status"].upper() == "IMPORTED":
        bad = client.post(f"/api/statement-files/{item['id']}/retry")
        assert bad.status_code == 400
