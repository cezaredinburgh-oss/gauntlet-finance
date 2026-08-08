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
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    out: list[Transaction] = []
    for t in rows:
        if t.archived:
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
        out.append(t)
    out.sort(key=lambda x: (x.booking_date, str(x.id)), reverse=True)
    total = len(out)
    page = out[offset : offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [t.model_dump(mode="json") for t in page],
    }
