"""Transaction list endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from backend.api.deps import RepoDep, UserDep
from backend.schema.models import Transaction

router = APIRouter(tags=["transactions"])


@router.get("/transactions")
async def list_transactions(
    repo: RepoDep,
    _user: UserDep,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    currency: str | None = Query(None, min_length=3, max_length=3),
    account_id: UUID | None = None,
    is_internal_transfer: bool | None = None,
    category_id: UUID | None = None,
    source_file_ids: str | None = Query(
        None,
        description="Comma-separated StatementFiles UUIDs (source_file_id on txs)",
    ),
    latest_import_batch: bool = Query(
        False,
        description="If true, only txs from the latest import batch (~15m window)",
    ),
    ids: str | None = Query(
        None,
        description="Comma-separated transaction UUIDs (allowlist; ignores date paging)",
    ),
    tx_ids: str | None = Query(
        None,
        description="Alias of ids — comma-separated transaction UUIDs",
    ),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    from backend.services.statement_files import latest_import_batch_file_ids

    file_id_set: set[UUID] | None = None
    batch_meta: dict[str, Any] | None = None
    if latest_import_batch:
        batch = latest_import_batch_file_ids(repo)
        file_id_set = set(batch["ids"])
        batch_meta = {
            "file_ids": [str(i) for i in batch["ids"]],
            "filenames": batch["filenames"],
            "uploaded_at_max": batch["uploaded_at_max"],
        }
    elif source_file_ids:
        file_ids: list[UUID] = []
        for part in source_file_ids.split(","):
            p = part.strip()
            if not p:
                continue
            try:
                file_ids.append(UUID(p))
            except ValueError:
                continue
        file_id_set = set(file_ids) if file_ids else set()

    id_set: set[UUID] | None = None
    raw_ids = tx_ids or ids
    if raw_ids:
        parsed: list[UUID] = []
        for part in raw_ids.split(","):
            p = part.strip()
            if not p:
                continue
            try:
                parsed.append(UUID(p))
            except ValueError:
                continue
        id_set = set(parsed) if parsed else set()

    rows = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    out: list[Transaction] = []
    for t in rows:
        if t.archived:
            continue
        if id_set is not None:
            if t.id not in id_set:
                continue
            out.append(t)
            continue
        if date_from and t.booking_date < date_from:
            continue
        if date_to and t.booking_date > date_to:
            continue
        if currency and t.currency.upper() != currency.upper():
            continue
        if account_id and t.account_id != account_id:
            continue
        if is_internal_transfer is not None and t.is_internal_transfer != is_internal_transfer:
            continue
        if category_id and t.category_id != category_id:
            continue
        if file_id_set is not None:
            if t.source_file_id is None or t.source_file_id not in file_id_set:
                continue
        out.append(t)
    out.sort(key=lambda x: (x.booking_date, str(x.id)), reverse=True)
    total = len(out)
    page = out[offset : offset + limit]
    result: dict[str, Any] = {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [t.model_dump(mode="json") for t in page],
    }
    if batch_meta is not None:
        result["latest_import_batch"] = batch_meta
    return result
