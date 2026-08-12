"""Multi-tenant tenant lifecycle: provision spreadsheet binding."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import PlatformAdminDep, SettingsDep, UserDep, clear_repo_cache
from backend.services.categorization import ensure_default_categories
from backend.tenancy.store import control_user_to_dict, get_control_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenant", tags=["tenant"])


class BindBody(BaseModel):
    spreadsheet_id: str = Field(..., min_length=5)
    user_id: str | None = Field(
        default=None,
        description="Target user (platform admin only). Defaults to self.",
    )


@router.get("/status")
async def tenant_status(settings: SettingsDep, user: UserDep) -> dict[str, Any]:
    if not settings.multi_tenant:
        return {
            "multi_tenant": False,
            "message": "Single-tenant mode",
        }
    store = get_control_store(settings)
    record = store.get_user_by_id(user.user_id or "")
    if record is None:
        raise HTTPException(status_code=403, detail="Account not registered.")
    return {
        "multi_tenant": True,
        "user": control_user_to_dict(record),
    }


@router.post("/provision")
async def provision_tenant(settings: SettingsDep, user: UserDep) -> dict[str, Any]:
    """
    Ensure the authenticated user has a bound spreadsheet.

    - Memory / test: assigns ``mem-{user_id}`` ledger key
    - Live: creates a Google Spreadsheet via platform service account and shares it
    """
    if not settings.multi_tenant:
        raise HTTPException(status_code=404, detail="Multi-tenant mode is disabled.")
    if not user.user_id:
        raise HTTPException(status_code=403, detail="Account not registered.")

    store = get_control_store(settings)
    record = store.get_user_by_id(user.user_id)
    if record is None:
        raise HTTPException(status_code=403, detail="Account not registered.")
    if record.disabled_at:
        raise HTTPException(status_code=403, detail="Account disabled.")

    if record.spreadsheet_id:
        return {
            "status": "already_provisioned",
            "spreadsheet_id": record.spreadsheet_id,
            "user": control_user_to_dict(record),
        }

    use_memory = (
        settings.multi_tenant_memory_sheets
        or settings.app_env == "test"
        or (os.environ.get("REPO_BACKEND") or "").strip().lower()
        in {"memory", "inmemory", "mem"}
    )

    if use_memory:
        sheet_id = f"mem-{record.id}"
        try:
            updated = store.claim_spreadsheet_id(
                record.id, sheet_id, only_if_empty=True
            )
        except ValueError as exc:
            msg = str(exc)
            if msg == "already_provisioned":
                refreshed = store.get_user_by_id(record.id)
                assert refreshed is not None
                return {
                    "status": "already_provisioned",
                    "spreadsheet_id": refreshed.spreadsheet_id,
                    "user": control_user_to_dict(refreshed),
                }
            if msg == "spreadsheet_already_bound":
                raise HTTPException(
                    status_code=409,
                    detail="That spreadsheet is already bound to another account.",
                ) from exc
            raise HTTPException(status_code=400, detail=msg) from exc

        from backend.api.deps import get_memory_repo_for_tenant

        repo = get_memory_repo_for_tenant(sheet_id)
        try:
            ensure_default_categories(repo)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_default_categories on provision: %s", exc)
        clear_repo_cache(spreadsheet_id=sheet_id)
        return {
            "status": "provisioned",
            "backend": "memory",
            "spreadsheet_id": sheet_id,
            "user": control_user_to_dict(updated),
        }

    # Live Google Sheets path — claim only after create; use only_if_empty
    try:
        from backend.sheets.google_sheets import (
            GoogleSheetsRepository,
            create_spreadsheet,
            credentials_from_service_account,
        )

        # Re-check empty under race
        record = store.get_user_by_id(user.user_id)
        if record and record.spreadsheet_id:
            return {
                "status": "already_provisioned",
                "spreadsheet_id": record.spreadsheet_id,
                "user": control_user_to_dict(record),
            }

        creds = credentials_from_service_account(
            json_path=settings.google_application_credentials,
            json_inline=settings.google_service_account_json or None,
        )
        title = f"Gauntlet Finance — {record.email if record else user.email}"
        created = create_spreadsheet(
            creds,
            title=title,
            share_with_email=(record.email if record else user.email),
        )
        sheet_id = created["spreadsheet_id"]
        try:
            updated = store.claim_spreadsheet_id(
                user.user_id, sheet_id, only_if_empty=True
            )
        except ValueError as exc:
            msg = str(exc)
            if msg == "already_provisioned":
                # Concurrent provision won — leave orphan sheet (logged)
                logger.warning(
                    "provision race: orphan sheet %s for user %s",
                    sheet_id,
                    user.user_id,
                )
                refreshed = store.get_user_by_id(user.user_id)
                assert refreshed is not None
                return {
                    "status": "already_provisioned",
                    "spreadsheet_id": refreshed.spreadsheet_id,
                    "user": control_user_to_dict(refreshed),
                    "orphan_spreadsheet_id": sheet_id,
                }
            raise

        repo = GoogleSheetsRepository(spreadsheet_id=sheet_id, credentials=creds)
        try:
            ensure_default_categories(repo)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_default_categories: %s", exc)
        clear_repo_cache(spreadsheet_id=sheet_id)
        return {
            "status": "provisioned",
            "backend": "google",
            "spreadsheet_id": sheet_id,
            "url": created.get("url"),
            "shared_with": created.get("shared_with"),
            "user": control_user_to_dict(updated),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("tenant provision failed for %s", user.email)
        raise HTTPException(
            status_code=503,
            detail=f"Could not provision spreadsheet: {exc}",
        ) from exc


@router.post("/bind")
async def bind_spreadsheet(
    body: BindBody,
    settings: SettingsDep,
    admin: PlatformAdminDep,
) -> dict[str, Any]:
    """
    Platform-admin only: attach an existing spreadsheet id to a user.

    Used for migrating a legacy single-tenant sheet onto a control-plane user.
    Normal users must use POST /api/tenant/provision.
    """
    if not settings.multi_tenant:
        raise HTTPException(status_code=404, detail="Multi-tenant mode is disabled.")

    target_id = (body.user_id or admin.user_id or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="user_id required")

    sheet_id = body.spreadsheet_id.strip()
    if "/d/" in sheet_id:
        try:
            sheet_id = sheet_id.split("/d/")[1].split("/")[0]
        except IndexError:
            pass

    store = get_control_store(settings)
    target = store.get_user_by_id(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        updated = store.claim_spreadsheet_id(target_id, sheet_id, only_if_empty=False)
    except ValueError as exc:
        if str(exc) == "spreadsheet_already_bound":
            raise HTTPException(
                status_code=409,
                detail="That spreadsheet is already bound to another account.",
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    clear_repo_cache(spreadsheet_id=sheet_id)
    return {
        "status": "bound",
        "spreadsheet_id": sheet_id,
        "user": control_user_to_dict(updated),
        "bound_by": admin.email,
    }
