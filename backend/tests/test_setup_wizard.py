"""Tests for the Google Sheets setup wizard API."""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

os.environ["AUTH_MODE"] = "dev"
os.environ["SPREADSHEET_ID"] = ""
os.environ["SECRET_KEY"] = "test-secret"

from backend.api.deps import clear_repo_cache
from backend.api.main import create_app
from backend.config import get_settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("SPREADSHEET_ID", "")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    clear_repo_cache()
    import backend.api.deps as deps

    deps._DEV_MEMORY_REPO = None

    import backend.setup_wizard.env_file as env_file

    monkeypatch.setattr(env_file, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "secrets").mkdir()
    (tmp_path / ".env").write_text("AUTH_MODE=dev\n", encoding="utf-8")

    app = create_app()
    with TestClient(app) as c:
        yield c, tmp_path
    deps._DEV_MEMORY_REPO = None
    clear_repo_cache()
    get_settings.cache_clear()


def test_wizard_page(client):
    c, _ = client
    r = c.get("/setup")
    assert r.status_code == 200
    assert "Google Sheets setup wizard" in r.text


def test_wizard_status(client):
    c, _ = client
    r = c.get("/setup/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "steps" in body
    assert "progress" in body
    assert "required_tabs" in body


def test_upload_credentials_and_save_sheet(client):
    c, tmp = client
    fake_sa = {
        "type": "service_account",
        "project_id": "demo",
        "private_key_id": "x",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n",
        "client_email": "finance-sheets@demo.iam.gserviceaccount.com",
        "client_id": "123",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    files = {
        "file": ("sa.json", json.dumps(fake_sa).encode("utf-8"), "application/json"),
    }
    r = c.post("/setup/api/upload-credentials", files=files)
    assert r.status_code == 200, r.text
    assert r.json()["client_email"].startswith("finance-sheets@")
    assert (tmp / "secrets" / "service-account.json").is_file()

    r2 = c.post(
        "/setup/api/save-spreadsheet",
        json={
            "spreadsheet_id": "https://docs.google.com/spreadsheets/d/abcDEF1234567890xyz/edit#gid=0"
        },
    )
    assert r2.status_code == 200
    assert r2.json()["spreadsheet_id"] == "abcDEF1234567890xyz"
    env_text = (tmp / ".env").read_text(encoding="utf-8")
    assert "SPREADSHEET_ID=abcDEF1234567890xyz" in env_text
