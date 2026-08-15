"""VendorMemory upsert + threshold."""

from __future__ import annotations

from backend.schema.default_categories import CAT_GROCERIES, CAT_RESTAURANTS
from backend.schema.models import VendorMemory
from backend.services import vendor_memory as vm
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import tx


def test_record_assignments_increments_and_rejects():
    repo = InMemorySheetsRepository()
    a = tx(merchant="Lidl", suggest_category_id=CAT_RESTAURANTS)
    b = tx(merchant="Lidl")
    vm.record_assignments(repo, [a], CAT_GROCERIES, source="user")
    vm.record_assignments(repo, [b], CAT_GROCERIES, source="user")
    rows = [r for r in repo.list_rows("VendorMemory") if isinstance(r, VendorMemory)]
    assert len(rows) == 1
    assert rows[0].assign_count == 2
    assert rows[0].reject_count == 1
    assert rows[0].category_id == CAT_GROCERIES
    assert rows[0].vendor_key == "m:lidl"


def test_lookup_requires_two_assigns():
    repo = InMemorySheetsRepository()
    t = tx(merchant="Lidl")
    vm.record_assignments(repo, [t], CAT_GROCERIES)
    row = vm.memory_lookup(repo, "m:lidl")
    assert row is not None
    assert row.assign_count < vm.MEMORY_MIN_ASSIGNS
    vm.record_assignments(repo, [tx(merchant="Lidl")], CAT_GROCERIES)
    row = vm.memory_lookup(repo, "m:lidl")
    assert row is not None
    assert row.assign_count >= vm.MEMORY_MIN_ASSIGNS
