"""Unit tests for GoogleSheetsRepository row-patch write path (mocked API)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call
from uuid import uuid4

import pytest

from backend.schema.models import Transaction
from backend.sheets.google_sheets import GoogleSheetsRepository
from backend.sheets.codec import model_to_row
from backend.schema.models import SHEET_HEADERS


def _tx(**kwargs) -> Transaction:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = dict(
        id=uuid4(),
        account_id=uuid4(),
        booking_date=date(2026, 1, 2),
        amount=Decimal("-10.00"),
        currency="CZK",
        fee_amount=Decimal("0"),
        description="test",
        merchant="Shop",
        category_id=None,
        category_override=False,
        is_internal_transfer=False,
        source_institution="Revolut",
        archived=False,
        created_at=now,
        updated_at=now,
    )
    base.update(kwargs)
    return Transaction(**base)


class _FakeValues:
    def __init__(self, parent: "_FakeService") -> None:
        self.parent = parent

    def get(self, **kwargs):
        self.parent.calls.append(("get", kwargs))
        return self

    def update(self, **kwargs):
        self.parent.calls.append(("update", kwargs))
        return self

    def clear(self, **kwargs):
        self.parent.calls.append(("clear", kwargs))
        return self

    def batchUpdate(self, **kwargs):
        self.parent.calls.append(("batchUpdate", kwargs))
        return self

    def execute(self):
        op = self.parent.calls[-1][0]
        if op == "get":
            return {"values": self.parent.grid}
        return {}


class _FakeSpreadsheets:
    def __init__(self, parent: "_FakeService") -> None:
        self.parent = parent

    def values(self):
        return _FakeValues(self.parent)

    def get(self, **kwargs):
        self.parent.calls.append(("spreadsheets.get", kwargs))
        return self

    def batchUpdate(self, **kwargs):
        self.parent.calls.append(("spreadsheets.batchUpdate", kwargs))
        return self

    def execute(self):
        # Large grid so capacity expand is a no-op in unit tests
        return {
            "sheets": [
                {
                    "properties": {
                        "sheetId": 1,
                        "title": "Transactions",
                        "gridProperties": {"rowCount": 50000, "columnCount": 50},
                    }
                },
                {
                    "properties": {
                        "sheetId": 2,
                        "title": "FXRates",
                        "gridProperties": {"rowCount": 50000, "columnCount": 50},
                    }
                },
            ]
        }


class _FakeService:
    def __init__(self, grid: list[list[str]]) -> None:
        self.grid = grid
        self.calls: list[tuple[str, dict]] = []

    def spreadsheets(self):
        return _FakeSpreadsheets(self)


def _repo_with_grid(grid: list[list[str]]) -> tuple[GoogleSheetsRepository, _FakeService]:
    svc = _FakeService(grid)
    repo = GoogleSheetsRepository.__new__(GoogleSheetsRepository)
    repo.spreadsheet_id = "sheet-id"
    repo._creds = None
    repo._service = svc
    repo._cache = {}
    repo._cache_loaded_at = {}
    repo._row_index = {}
    repo._next_row = {}
    repo._dirty = set()
    repo._tab_cache_ttl_seconds = 600.0
    from threading import Lock

    repo._load_lock = Lock()
    repo._tab_locks = {}
    repo._tab_locks_guard = Lock()
    return repo, svc


def test_upsert_patches_existing_row_without_clear():
    headers = SHEET_HEADERS["Transactions"]
    t1 = _tx(merchant="Old")
    t2 = _tx(merchant="Keep")
    grid = [headers, model_to_row(t1, headers), model_to_row(t2, headers)]
    repo, svc = _repo_with_grid(grid)

    updated = t1.model_copy(update={"merchant": "New", "category_override": True})
    repo.upsert_rows("Transactions", [updated])

    ops = [c[0] for c in svc.calls]
    assert "clear" not in ops
    assert "batchUpdate" in ops
    batch = next(c[1] for c in svc.calls if c[0] == "batchUpdate")
    data = batch["body"]["data"]
    assert len(data) == 1
    assert data[0]["range"] == "'Transactions'!A2"
    assert data[0]["values"][0][headers.index("merchant")] == "New"

    # Second row untouched in cache
    assert repo.get_by_id("Transactions", t2.id).merchant == "Keep"
    assert repo.get_by_id("Transactions", t1.id).merchant == "New"


def test_upsert_appends_new_row():
    headers = SHEET_HEADERS["Transactions"]
    t1 = _tx()
    grid = [headers, model_to_row(t1, headers)]
    repo, svc = _repo_with_grid(grid)

    t_new = _tx(merchant="BrandNew")
    repo.upsert_rows("Transactions", [t_new])

    ops = [c[0] for c in svc.calls]
    assert "clear" not in ops
    assert "update" in ops  # append via values.update at next free row
    update_calls = [c[1] for c in svc.calls if c[0] == "update"]
    last = update_calls[-1]
    assert last["range"] == "'Transactions'!A3"
    assert last["body"]["values"][0][headers.index("merchant")] == "BrandNew"
    assert repo._row_index["Transactions"][t_new.id] == 3


def test_bulk_upsert_batches_patches():
    headers = SHEET_HEADERS["Transactions"]
    txs = [_tx(merchant=f"M{i}") for i in range(5)]
    grid = [headers] + [model_to_row(t, headers) for t in txs]
    repo, svc = _repo_with_grid(grid)

    updated = [t.model_copy(update={"merchant": f"U{i}"}) for i, t in enumerate(txs)]
    repo.upsert_rows("Transactions", updated)

    ops = [c[0] for c in svc.calls]
    assert "clear" not in ops
    batch = next(c[1] for c in svc.calls if c[0] == "batchUpdate")
    assert len(batch["body"]["data"]) == 5


def test_replace_all_still_uses_full_clear():
    headers = SHEET_HEADERS["Transactions"]
    t1 = _tx()
    repo, svc = _repo_with_grid([headers, model_to_row(t1, headers)])
    # Load first so cache is populated
    assert len(repo.list_rows("Transactions")) == 1
    svc.calls.clear()

    t2 = _tx(merchant="Only")
    repo.replace_all_rows("Transactions", [t2])
    ops = [c[0] for c in svc.calls]
    assert "clear" in ops
    assert "update" in ops
