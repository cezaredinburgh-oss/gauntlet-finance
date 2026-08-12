"""Platform-admin invite management (multi-tenant)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import PlatformAdminDep, SettingsDep
from backend.tenancy.store import control_user_to_dict, get_control_store, normalize_email

router = APIRouter(prefix="/admin/invites", tags=["admin-invites"])


class InviteCreateBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


@router.get("")
async def list_invites(
    settings: SettingsDep,
    _admin: PlatformAdminDep,
    pending_only: bool = False,
) -> dict[str, Any]:
    store = get_control_store(settings)
    invites = store.list_invites(pending_only=pending_only)
    return {
        "items": [
            {
                "id": i.id,
                "email": i.email,
                "invited_by": i.invited_by,
                "expires_at": i.expires_at,
                "accepted_at": i.accepted_at,
                "created_at": i.created_at,
                "pending": i.accepted_at is None,
            }
            for i in invites
        ]
    }


@router.post("")
async def create_invite(
    body: InviteCreateBody,
    settings: SettingsDep,
    admin: PlatformAdminDep,
) -> dict[str, Any]:
    store = get_control_store(settings)
    em = normalize_email(body.email)
    if not em or "@" not in em:
        raise HTTPException(status_code=400, detail="Valid email required")
    inv = store.create_invite(em, invited_by=admin.email)
    return {
        "id": inv.id,
        "email": inv.email,
        "invited_by": inv.invited_by,
        "created_at": inv.created_at,
        "pending": True,
        # One-shot raw token (not re-fetchable as raw)
        "invite_token": inv.token_hash,
    }


@router.delete("/{invite_id}")
async def delete_invite(
    invite_id: str,
    settings: SettingsDep,
    _admin: PlatformAdminDep,
) -> dict[str, Any]:
    store = get_control_store(settings)
    ok = store.delete_invite(invite_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"status": "deleted", "id": invite_id}


@router.get("/users")
async def list_tenant_users(
    settings: SettingsDep,
    _admin: PlatformAdminDep,
) -> dict[str, Any]:
    store = get_control_store(settings)
    return {"items": [control_user_to_dict(u) for u in store.list_users()]}
