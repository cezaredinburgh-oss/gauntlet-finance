"""Tax report years / summary-by-year endpoints."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ["AUTH_MODE"] = "dev"
os.environ["SPREADSHEET_ID"] = ""
os.environ["SECRET_KEY"] = "test-secret"
os.environ["YFINANCE_ENABLED"] = "false"

from backend.api.deps import clear_repo_cache
from backend.api.main import create_app
from backend.config import get_settings
from backend.schema.models import InvestmentEvent, InvestmentEventType
from backend.tests.helpers import TS


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
        yield c, deps
    deps._DEV_MEMORY_REPO = None
    clear_repo_cache()
    get_settings.cache_clear()


def _alloc(
    *,
    year: int,
    gain_czk: str,
    exempt: bool,
    ticker: str = "AAA",
) -> InvestmentEvent:
    return InvestmentEvent(
        id=uuid4(),
        account_id=uuid4(),
        event_type=InvestmentEventType.LOT_ALLOCATION,
        event_date=date(year, 6, 15),
        ticker=ticker,
        quantity=Decimal("1"),
        realized_gain_czk=Decimal(gain_czk),
        realized_gain_usd=Decimal("10"),
        qualifies_3y_exemption=exempt,
        holding_period_days=1200 if exempt else 100,
        source="test",
        created_at=TS,
        updated_at=TS,
    )


def test_tax_years_and_summary(client):
    c, deps = client
    # touch repo
    assert c.get("/api/tax-report/years").status_code == 200
    repo = deps._DEV_MEMORY_REPO
    assert repo is not None
    repo.upsert_rows(
        "InvestmentEvents",
        [
            _alloc(year=2024, gain_czk="1000", exempt=False),
            _alloc(year=2024, gain_czk="500", exempt=True),
            _alloc(year=2025, gain_czk="200", exempt=True),
        ],
    )
    r = c.get("/api/tax-report/years")
    assert r.status_code == 200
    years = r.json()["years"]
    assert 2024 in years and 2025 in years

    s = c.get("/api/tax-report/summary-by-year").json()
    by = {row["year"]: row for row in s["years"]}
    assert by[2024]["taxable_realized_gain_czk"] == "1000"
    assert by[2024]["exempt_realized_gain_czk"] == "500"
    assert by[2025]["exempt_realized_gain_czk"] == "200"

    rep = c.get("/api/tax-report", params={"year": 2024})
    assert rep.status_code == 200
    body = rep.json()
    assert body["summary"]["taxable_disposal_count"] == 1
    assert body["summary"]["exempt_disposal_count"] == 1

    csv_r = c.get("/api/tax-report", params={"year": 2024, "format": "csv", "table": "taxable"})
    assert csv_r.status_code == 200
    assert "text/csv" in csv_r.headers.get("content-type", "")
    assert "realized_gain_czk" in csv_r.text
