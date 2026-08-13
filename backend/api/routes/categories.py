"""Categories, rules CRUD, bootstrap, and bulk apply."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import RepoDep, UserDep
from backend.api.schemas import (
    BulkCategoryOverrideRequest,
    BulkCategoryOverrideResponse,
    CategoryOverrideRequest,
    CategoryOverrideResponse,
    RestoreAssignmentsRequest,
    RestoreAssignmentsResponse,
)
from backend.common.timeutil import utc_now
from backend.schema.default_categories import CAT_INTERNAL
from backend.schema.models import Category, Transaction
from backend.services.categorization import (
    apply_match_to_all_transactions,
    apply_merchant_queue_item,
    apply_rules_fill_blanks,
    archive_category,
    bootstrap_rules_from_data,
    coverage_stats,
    create_category,
    create_rule,
    deactivate_rule,
    ensure_default_categories,
    list_rules,
    merchant_queue,
    rule_suggestions,
    update_category,
    update_rule,
)
from backend.services.response_cache import cache_invalidate

router = APIRouter(tags=["categories"])


def _category_implies_internal_transfer(cat: Category) -> bool:
    """
    Assigning this category should also set is_internal_transfer=True.

    Only true Internal transfer (not External transfer / Broker funding).
    """
    if cat.id == CAT_INTERNAL:
        return True
    name = (cat.name or "").strip().lower()
    if cat.is_transfer and "internal" in name and "external" not in name:
        return True
    return False


class RuleBody(BaseModel):
    priority: int = 100
    match_field: str
    match_type: str
    match_value: str
    category_id: UUID
    set_internal_transfer: bool = False
    institution_scope: str | None = None
    is_active: bool = True
    notes: str | None = None


class RulePatchBody(BaseModel):
    priority: int | None = None
    match_field: str | None = None
    match_type: str | None = None
    match_value: str | None = None
    category_id: UUID | None = None
    set_internal_transfer: bool | None = None
    institution_scope: str | None = None
    is_active: bool | None = None
    notes: str | None = None


class BootstrapBody(BaseModel):
    also_apply: bool = True


class CategoryCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    necessity: str
    life_domain: str
    parent_id: UUID | None = None
    is_income: bool = False
    is_transfer: bool = False
    sort_order: int = 500


class CategoryPatchBody(BaseModel):
    name: str | None = None
    necessity: str | None = None
    life_domain: str | None = None
    parent_id: UUID | None = None
    is_income: bool | None = None
    is_transfer: bool | None = None
    sort_order: int | None = None


class CategoryDeleteBody(BaseModel):
    reassign_to: UUID | None = None
    cascade_children: bool = False


class MerchantQueueApplyBody(BaseModel):
    label: str = Field(..., min_length=1)
    category_id: UUID
    match_field: str | None = None
    match_value: str | None = None
    create_rule: bool = True
    also_apply: bool = True


@router.get("/categories")
async def list_categories(repo: RepoDep, _user: UserDep) -> dict[str, Any]:
    rows = [r for r in repo.list_rows("Categories") if isinstance(r, Category)]
    rows = [c for c in rows if not c.archived]
    rows.sort(key=lambda c: (c.sort_order, c.name))
    return {"items": [c.model_dump(mode="json") for c in rows]}


@router.post("/categories")
async def post_category(
    repo: RepoDep, _user: UserDep, body: CategoryCreateBody
) -> dict[str, Any]:
    try:
        cat = create_category(
            repo,
            name=body.name,
            necessity=body.necessity,
            life_domain=body.life_domain,
            parent_id=body.parent_id,
            is_income=body.is_income,
            is_transfer=body.is_transfer,
            sort_order=body.sort_order,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": cat.model_dump(mode="json")}


@router.patch("/categories/{category_id}")
async def patch_category(
    repo: RepoDep,
    _user: UserDep,
    category_id: UUID,
    body: CategoryPatchBody,
) -> dict[str, Any]:
    try:
        cat = update_category(
            repo, category_id, **body.model_dump(exclude_unset=True)
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Category not found") from None
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": cat.model_dump(mode="json")}


@router.delete("/categories/{category_id}")
async def delete_category(
    repo: RepoDep,
    _user: UserDep,
    category_id: UUID,
    reassign_to: UUID | None = None,
    cascade_children: bool = False,
) -> dict[str, Any]:
    try:
        return archive_category(
            repo,
            category_id,
            reassign_to=reassign_to,
            cascade_children=cascade_children,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Category not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/categories/ensure-defaults")
async def ensure_defaults(repo: RepoDep, user: UserDep) -> dict[str, Any]:
    """Ensure default categories + seed rules; fill blanks so new rules apply."""
    if user.is_demo:
        # Public demos: generic tree + Digital Assets only (no personal name rules).
        from backend.schema.demo_public import ensure_public_demo_categories

        cat_stats = ensure_public_demo_categories(repo)
        fill = apply_rules_fill_blanks(repo)
        return {**cat_stats, "fill_blanks": fill, "public_demo": True}
    cat_stats = ensure_default_categories(repo)
    fill = apply_rules_fill_blanks(repo)
    return {**cat_stats, "fill_blanks": fill}


@router.get("/categories/coverage")
async def get_coverage(
    repo: RepoDep,
    _user: UserDep,
    days: int = 180,
) -> dict[str, Any]:
    return coverage_stats(repo, days=days)


@router.get("/categories/merchant-queue")
async def get_merchant_queue(
    repo: RepoDep,
    _user: UserDep,
    days: int = 180,
    limit: int = 40,
) -> dict[str, Any]:
    return merchant_queue(repo, days=days, limit=limit)


@router.get("/categories/rule-suggestions")
async def get_rule_suggestions(
    repo: RepoDep,
    _user: UserDep,
    days: int = 180,
    limit: int = 20,
) -> dict[str, Any]:
    """Ranked residual rule proposals (heuristics; human apply only)."""
    return rule_suggestions(repo, days=days, limit=limit)


@router.post("/categories/merchant-queue/apply")
async def post_merchant_queue_apply(
    repo: RepoDep,
    _user: UserDep,
    body: MerchantQueueApplyBody,
) -> dict[str, Any]:
    try:
        return apply_merchant_queue_item(
            repo,
            label=body.label,
            category_id=body.category_id,
            match_field=body.match_field,
            match_value=body.match_value,
            make_rule=body.create_rule,
            also_apply=body.also_apply,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/categories/bootstrap-rules")
async def bootstrap_rules(
    repo: RepoDep,
    user: UserDep,
    body: BootstrapBody | None = None,
) -> dict[str, Any]:
    # Sample portfolio (tour) is educational read-only; sandbox may bootstrap.
    if user.is_demo and user.demo_kind == "tour":
        raise HTTPException(
            status_code=403,
            detail=(
                "Bootstrap rules are disabled in the sample portfolio walkthrough. "
                "Use the sandbox demo or a real account to try rules."
            ),
        )
    also = True if body is None else body.also_apply
    return bootstrap_rules_from_data(repo, also_apply=also)


@router.post("/categories/apply-rules")
async def apply_rules(repo: RepoDep, _user: UserDep) -> dict[str, Any]:
    return apply_rules_fill_blanks(repo)


class ApplyMatchBody(BaseModel):
    category_id: UUID
    match_field: str = "merchant"
    match_type: str = "contains"
    match_value: str
    institution_scope: str | None = None
    set_internal_transfer: bool = False
    # fill_blanks | reclassify_non_override | force
    mode: str = "reclassify_non_override"
    mark_override: bool = True


@router.post("/categories/apply-match")
async def apply_match(
    body: ApplyMatchBody,
    repo: RepoDep,
    _user: UserDep,
) -> dict[str, Any]:
    """
    Apply a match pattern to all transactions in the ledger (global, not UI filter).

    Default mode reclassifies non-override rows (e.g. External transfer → Utilities)
    so a newly created rule can fix historical auto-tags outside the current list.
    """
    try:
        return apply_match_to_all_transactions(
            repo,
            category_id=body.category_id,
            match_field=body.match_field,
            match_type=body.match_type,
            match_value=body.match_value,
            institution_scope=body.institution_scope,
            set_internal_transfer=body.set_internal_transfer,
            mode=body.mode,
            mark_override=body.mark_override,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/category-rules")
async def get_rules(repo: RepoDep, _user: UserDep) -> dict[str, Any]:
    rows = list_rules(repo)
    return {"items": [r.model_dump(mode="json") for r in rows]}


@router.post("/category-rules")
async def post_rule(repo: RepoDep, _user: UserDep, body: RuleBody) -> dict[str, Any]:
    try:
        rule = create_rule(repo, body.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return rule.model_dump(mode="json")


@router.patch("/category-rules/{rule_id}")
async def patch_rule(
    rule_id: UUID,
    body: RulePatchBody,
    repo: RepoDep,
    _user: UserDep,
) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    # allow clearing institution_scope with empty string via explicit null — handled in service
    if "institution_scope" in body.model_fields_set:
        data["institution_scope"] = body.institution_scope
    updated = update_rule(repo, rule_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return updated.model_dump(mode="json")


@router.delete("/category-rules/{rule_id}")
async def delete_rule(rule_id: UUID, repo: RepoDep, _user: UserDep) -> dict[str, Any]:
    ok = deactivate_rule(repo, rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deactivated", "id": str(rule_id)}


@router.post(
    "/categories/{category_id}/override",
    response_model=CategoryOverrideResponse,
)
async def override_category(
    category_id: UUID,
    body: CategoryOverrideRequest,
    repo: RepoDep,
    _user: UserDep,
) -> CategoryOverrideResponse:
    cat = repo.get_by_id("Categories", category_id)
    if cat is None or not isinstance(cat, Category) or cat.archived:
        raise HTTPException(status_code=404, detail="Category not found")
    tx = repo.get_by_id("Transactions", body.transaction_id)
    if tx is None or not isinstance(tx, Transaction):
        raise HTTPException(status_code=404, detail="Transaction not found")
    updates: dict[str, Any] = {
        "category_id": category_id,
        "category_override": True,
        "updated_at": utc_now(),
    }
    if _category_implies_internal_transfer(cat):
        updates["is_internal_transfer"] = True
    updated = tx.model_copy(update=updates)
    repo.upsert_rows("Transactions", [updated])
    cache_invalidate()
    return CategoryOverrideResponse(
        transaction_id=updated.id,
        category_id=category_id,
        category_override=True,
    )


@router.post(
    "/categories/bulk-override",
    response_model=BulkCategoryOverrideResponse,
)
async def bulk_override_category(
    body: BulkCategoryOverrideRequest,
    repo: RepoDep,
    _user: UserDep,
) -> BulkCategoryOverrideResponse:
    """Assign a category to many transactions (manual overrides)."""
    cat = repo.get_by_id("Categories", body.category_id)
    if cat is None or not isinstance(cat, Category) or cat.archived:
        raise HTTPException(status_code=404, detail="Category not found")

    # De-dupe while preserving order
    seen: set[UUID] = set()
    ids: list[UUID] = []
    for tid in body.transaction_ids:
        if tid not in seen:
            seen.add(tid)
            ids.append(tid)

    by_id = {
        r.id: r
        for r in repo.list_rows("Transactions")
        if isinstance(r, Transaction) and r.id in seen
    }
    ts = utc_now()
    updated_rows: list[Transaction] = []
    updated_ids: list[UUID] = []
    force_internal = _category_implies_internal_transfer(cat)
    for tid in ids:
        tx = by_id.get(tid)
        if tx is None or tx.archived:
            continue
        updates: dict[str, Any] = {
            "category_id": body.category_id,
            "category_override": True,
            "updated_at": ts,
        }
        if force_internal:
            updates["is_internal_transfer"] = True
        updated_rows.append(tx.model_copy(update=updates))
        updated_ids.append(tid)

    if updated_rows:
        repo.upsert_rows("Transactions", updated_rows)
        cache_invalidate()

    return BulkCategoryOverrideResponse(
        category_id=body.category_id,
        updated=len(updated_ids),
        missing=len(ids) - len(updated_ids),
        transaction_ids=updated_ids,
    )


@router.post(
    "/categories/restore-assignments",
    response_model=RestoreAssignmentsResponse,
)
async def restore_assignments(
    body: RestoreAssignmentsRequest,
    repo: RepoDep,
    _user: UserDep,
) -> RestoreAssignmentsResponse:
    """
    Restore prior category fields (undo). Supports clearing category_id.

    Does not invent FX or touch amounts — assignment metadata only.
    """
    wanted = {item.transaction_id: item for item in body.items}
    by_id = {
        r.id: r
        for r in repo.list_rows("Transactions")
        if isinstance(r, Transaction) and r.id in wanted
    }
    ts = utc_now()
    updated_rows: list[Transaction] = []
    updated_ids: list[UUID] = []
    for tid, item in wanted.items():
        tx = by_id.get(tid)
        if tx is None or tx.archived:
            continue
        if item.category_id is not None:
            cat = repo.get_by_id("Categories", item.category_id)
            if cat is None or not isinstance(cat, Category) or cat.archived:
                continue
        updates: dict[str, Any] = {
            "category_id": item.category_id,
            "category_override": bool(item.category_override),
            "updated_at": ts,
        }
        if item.is_internal_transfer is not None:
            updates["is_internal_transfer"] = bool(item.is_internal_transfer)
        updated_rows.append(tx.model_copy(update=updates))
        updated_ids.append(tid)

    if updated_rows:
        repo.upsert_rows("Transactions", updated_rows)
        cache_invalidate()

    return RestoreAssignmentsResponse(
        updated=len(updated_ids),
        missing=len(wanted) - len(updated_ids),
        transaction_ids=updated_ids,
    )
