"""In-process lab ledger wipe (must run on the host that owns the volume)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import SettingsDep, UserDep
from backend.services.lab_account import (
    LAB_RESET_CONFIRM,
    lab_login_configured,
    reset_lab_ledger,
)
from backend.tenancy.store import normalize_email

router = APIRouter(tags=["lab"])


class LabResetBody(BaseModel):
    confirm: str = Field(default="", description=f'Must be exactly "{LAB_RESET_CONFIRM}" unless dry_run')
    dry_run: bool = False


def _can_wipe_lab(user: Any, settings: SettingsDep) -> bool:
    if getattr(user, "is_demo", False) and getattr(user, "demo_kind", "") == "lab":
        return True
    if getattr(user, "role", None) == "platform_admin":
        return True
    admins = {
        normalize_email(e)
        for e in (settings.platform_admin_emails or "").split(",")
        if e.strip()
    }
    return normalize_email(getattr(user, "email", "") or "") in admins


@router.post("/lab/reset")
async def reset_lab_account(
    body: LabResetBody,
    user: UserDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """
    Wipe the lab disk ledger on **this** process (Railway volume or local AppData).

    Does not touch Google Sheets or other tenants. Confirm with WIPE LAB.
    """
    if not _can_wipe_lab(user, settings):
        raise HTTPException(
            status_code=403,
            detail="Only the lab account or a platform admin can wipe the lab ledger.",
        )
    if not lab_login_configured(settings) and not (
        getattr(user, "is_demo", False) and getattr(user, "demo_kind", "") == "lab"
    ):
        raise HTTPException(
            status_code=503,
            detail="Lab login is not configured on this host.",
        )
    if not body.dry_run and (body.confirm or "").strip() != LAB_RESET_CONFIRM:
        raise HTTPException(
            status_code=400,
            detail=f'Type {LAB_RESET_CONFIRM} to confirm, or set dry_run.',
        )
    result = reset_lab_ledger(settings, dry_run=body.dry_run)
    if not body.dry_run and not result.get("ok"):
        raise HTTPException(
            status_code=500,
            detail="Lab wipe did not yield an empty ledger.",
        )
    return result
