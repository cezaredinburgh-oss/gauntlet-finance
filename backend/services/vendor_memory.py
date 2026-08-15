"""Learned vendor → category map from user assigns (per ledger)."""

from __future__ import annotations

import re
from uuid import UUID, uuid4

from backend.common.timeutil import utc_now
from backend.schema.models import Transaction, VendorMemory
from backend.sheets.repository import SheetsRepository

_SPACE = re.compile(r"\s+")
MEMORY_MIN_ASSIGNS = 2


def _norm(s: str) -> str:
    return _SPACE.sub(" ", (s or "").strip())


def vendor_key(tx: Transaction) -> str | None:
    if tx.merchant and tx.merchant.strip():
        return f"m:{_norm(tx.merchant).lower()}"
    if tx.description and tx.description.strip():
        d = _norm(tx.description)
        return f"d:{(d[:48] if len(d) > 48 else d).lower()}"
    return None


def vendor_label(tx: Transaction) -> str:
    if tx.merchant and tx.merchant.strip():
        return _norm(tx.merchant)
    if tx.description and tx.description.strip():
        d = _norm(tx.description)
        return d[:48] if len(d) > 48 else d
    return "Unknown"


def load_index(repo: SheetsRepository) -> dict[str, VendorMemory]:
    out: dict[str, VendorMemory] = {}
    for row in repo.list_rows("VendorMemory"):
        if isinstance(row, VendorMemory) and not row.archived:
            out[row.vendor_key] = row
    return out


def record_assignments(
    repo: SheetsRepository,
    txs: list[Transaction],
    category_id: UUID,
    *,
    source: str = "user",
) -> None:
    """Upsert memory for each vendor in ``txs``. One increment per transaction."""
    if not txs:
        return
    now = utc_now()
    by_key = load_index(repo)
    dirty: list[VendorMemory] = []
    for tx in txs:
        key = vendor_key(tx)
        if not key:
            continue
        prev = by_key.get(key)
        rejected = bool(
            tx.suggest_category_id
            and tx.suggest_category_id != category_id
        )
        if prev is None:
            row = VendorMemory(
                id=uuid4(),
                vendor_key=key,
                label=vendor_label(tx),
                category_id=category_id,
                assign_count=1,
                reject_count=1 if rejected else 0,
                source=source,
                created_at=now,
                updated_at=now,
            )
        else:
            row = prev.model_copy(
                update={
                    "category_id": category_id,
                    "label": vendor_label(tx) or prev.label,
                    "assign_count": prev.assign_count + 1,
                    "reject_count": prev.reject_count + (1 if rejected else 0),
                    "source": source,
                    "updated_at": now,
                }
            )
        by_key[key] = row
        dirty.append(row)
    if dirty:
        repo.upsert_rows("VendorMemory", dirty)


def memory_lookup(repo: SheetsRepository, key: str) -> VendorMemory | None:
    if not key:
        return None
    return load_index(repo).get(key)


def export_memory(repo: SheetsRepository) -> list[dict[str, object]]:
    rows = [
        r
        for r in repo.list_rows("VendorMemory")
        if isinstance(r, VendorMemory) and not r.archived
    ]
    rows.sort(key=lambda r: (-r.assign_count, r.label.lower()))
    return [
        {
            "vendor_key": r.vendor_key,
            "label": r.label,
            "category_id": str(r.category_id),
            "assign_count": r.assign_count,
            "reject_count": r.reject_count,
            "source": r.source,
        }
        for r in rows
    ]
