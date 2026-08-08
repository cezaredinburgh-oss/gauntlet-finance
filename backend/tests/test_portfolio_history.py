"""Portfolio MV history + living vs safe draw metrics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    PortfolioSnapshot,
)
from backend.services.portfolio_history import (
    compute_draw_metrics,
    list_mv_series,
    record_portfolio_snapshot,
)
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import TS


def test_record_and_list_mv_series():
    repo = InMemorySheetsRepository()
    snap = {
        "total_market_value_usd": "100000.00",
        "total_cost_basis_usd": "80000.00",
        "unrealized_usd": "20000.00",
        "tax_free_now_usd": "10000.00",
    }
    row = record_portfolio_snapshot(
        repo, as_of=date(2026, 8, 1), source="test", snap=snap
    )
    assert row.total_market_value_usd == Decimal("100000.00")
    # second write same day upserts
    record_portfolio_snapshot(
        repo,
        as_of=date(2026, 8, 1),
        source="test",
        snap={**snap, "total_market_value_usd": "101000.00"},
    )
    series = list_mv_series(
        repo, date_from=date(2026, 7, 1), date_to=date(2026, 8, 31)
    )
    assert series["point_count"] == 1
    assert series["series"][0]["total_market_value_usd"] == "101000.00"


def test_safe_draw_min_of_four_pct_and_tax_free():
    repo = InMemorySheetsRepository()
    # MV 100k → 4% = 4k; tax free 2k → safe = 2k
    snap = {
        "total_market_value_usd": "100000",
        "tax_free_now_usd": "2000",
        "living_draw_12m": {
            "draw_usd": "1500",
            "sold_usd": "5000",
            "bought_usd": "3500",
        },
    }
    m = compute_draw_metrics(repo, snap=snap)
    assert m["safe_draw_annual_usd"] == "2000.00"
    assert m["safe_draw_binding_constraint"] == "tax_free"
    assert m["status"] == "ok"

    # living over safe
    snap2 = {
        **snap,
        "living_draw_12m": {"draw_usd": "3000", "sold_usd": "3000", "bought_usd": "0"},
    }
    m2 = compute_draw_metrics(repo, snap=snap2)
    assert m2["status"] == "over"
    assert Decimal(m2["living_over_safe_ratio"]) == Decimal("1.50")


def test_safe_draw_bound_by_pct_when_tax_free_large():
    repo = InMemorySheetsRepository()
    snap = {
        "total_market_value_usd": "100000",
        "tax_free_now_usd": "50000",
        "living_draw_12m": {"draw_usd": "1000", "sold_usd": "1000", "bought_usd": "0"},
    }
    m = compute_draw_metrics(repo, snap=snap)
    assert m["safe_draw_annual_usd"] == "4000.00"
    assert m["safe_draw_binding_constraint"] == "pct_rule"
