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


def test_wipe_clears_assigns_keeps_tags_and_internal():
    from backend.schema.default_categories import CAT_INTERNAL

    repo = InMemorySheetsRepository()
    kept = tx(
        merchant="To pocket",
        suggest_category_id=CAT_INTERNAL,
        suggest_reason="Own pot / FX / vault",
        is_internal_transfer=True,
    )
    assigned = tx(merchant="Lidl", category_id=CAT_GROCERIES, category_override=True)
    repo.upsert_rows("Transactions", [kept, assigned])
    vm.record_assignments(repo, [assigned], CAT_GROCERIES)
    out = vm.wipe_user_assignments(repo)
    assert out["cleared_assignments"] == 1
    rows = {t.merchant: t for t in repo.list_rows("Transactions")}
    assert rows["Lidl"].category_id is None
    assert rows["Lidl"].category_override is False
    assert rows["To pocket"].is_internal_transfer is True
    assert rows["To pocket"].suggest_category_id == CAT_INTERNAL
    assert repo.list_rows("VendorMemory") == []
