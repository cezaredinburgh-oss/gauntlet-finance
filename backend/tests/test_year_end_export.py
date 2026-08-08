"""Year-end ZIP export pack."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import os

os.environ.setdefault("AUTH_MODE", "dev")
os.environ.setdefault("SPREADSHEET_ID", "")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("YFINANCE_ENABLED", "false")

from backend.api.deps import clear_repo_cache
from backend.api.main import create_app
from backend.config import get_settings
from backend.schema.models import InvestmentEvent, InvestmentEventType
from backend.services.year_end_export import build_year_end_zip
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import TS, tx


def test_build_year_end_zip_contents():
    repo = InMemorySheetsRepository()
    repo.upsert_rows(
        "InvestmentEvents",
        [
            InvestmentEvent(
                id=uuid4(),
                account_id=uuid4(),
                event_type=InvestmentEventType.LOT_ALLOCATION,
                event_date=date(2025, 6, 1),
                ticker="AAA",
                quantity=Decimal("1"),
                realized_gain_czk=Decimal("1000"),
                realized_gain_usd=Decimal("40"),
                qualifies_3y_exemption=False,
                holding_period_days=100,
                source="test",
                created_at=TS,
                updated_at=TS,
            )
        ],
    )
    repo.upsert_rows(
        "Transactions",
        [tx(merchant="Shop", amount="-25", currency="USD", booking_date=date(2025, 3, 1))],
    )
    raw, name = build_year_end_zip(repo, year=2025, as_of=date(2026, 8, 8))
    assert name == "gauntlet-year-end-2025.zip"
    assert raw[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = set(zf.namelist())
        assert "tax-report.json" in names
        assert "taxable-disposals.csv" in names
        assert "exempt-disposals.csv" in names
        assert "open-lots.csv" in names
        assert "realized-by-year.csv" in names
        assert "category-spend-2025.csv" in names
        assert "statement-files.json" in names
        assert "README.txt" in names
        tax = zf.read("tax-report.json").decode("utf-8")
        assert "1000" in tax
        spend = zf.read("category-spend-2025.csv").decode("utf-8")
        assert "uncategorized" in spend or "expense_usd" in spend


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("SPREADSHEET_ID", "")
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


def test_year_end_endpoint(client: TestClient):
    r = client.get("/api/exports/year-end", params={"year": 2025})
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/zip")
    assert "gauntlet-year-end-2025.zip" in r.headers.get("content-disposition", "")
    assert r.content[:2] == b"PK"
