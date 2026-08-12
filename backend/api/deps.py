"""FastAPI dependencies: settings, auth, repository."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from backend.api.auth import SessionUser, load_session_token, user_credentials_from_session
from backend.config import Settings, get_settings
from backend.sheets.google_sheets import build_repository_from_settings
from backend.sheets.repository import InMemorySheetsRepository, SheetsRepository
from backend.tenancy.context import set_tenant_id
from backend.tenancy.store import get_control_store, normalize_email

# Dev/test singleton so in-memory mode persists across requests
_DEV_MEMORY_REPO: InMemorySheetsRepository | None = None
_TENANT_MEMORY_REPOS: dict[str, InMemorySheetsRepository] = {}
_REPO_CACHE: dict[str, SheetsRepository] = {}


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]

_OPEN_AUTH_BLOCKED_DETAIL = (
    "Open authentication is not allowed in production. "
    "Set AUTH_MODE=oauth, or set ALLOW_OPEN_AUTH=true only for "
    "trusted single-user deploys."
)

_MT_OPEN_AUTH_DETAIL = (
    "Multi-tenant production requires AUTH_MODE=oauth. "
    "Open authentication is disabled."
)


def _reject_unpermitted_open_auth(settings: Settings) -> None:
    """Block AUTH_MODE=dev/disabled when open auth is not permitted."""
    if settings.auth_mode in {"dev", "disabled"} and not settings.open_auth_permitted:
        detail = (
            _MT_OPEN_AUTH_DETAIL
            if settings.multi_tenant and settings.is_production
            else _OPEN_AUTH_BLOCKED_DETAIL
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )


def get_session_user(
    request: Request,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
    gf_session: Annotated[str | None, Cookie(alias="gf_session")] = None,
) -> SessionUser | None:
    if settings.auth_mode in {"dev", "disabled"}:
        _reject_unpermitted_open_auth(settings)
        if settings.multi_tenant:
            # Multi-tenant open modes only allowed in non-production (tests/dev).
            # Prefer signed session / Bearer so isolation tests can use real users.
            token = None
            if authorization and authorization.lower().startswith("bearer "):
                token = authorization.split(" ", 1)[1].strip()
            elif gf_session:
                token = gf_session
            if not token:
                token = request.cookies.get(settings.session_cookie_name)
            if token:
                user = load_session_token(settings, token)
                if user is not None:
                    return _hydrate_tenant_user(settings, user)
            # Fall back to synthetic single principal (not usable for multi-user isolation)
            return SessionUser(
                email="dev@localhost",
                name="Dev User",
                picture=None,
                access_token="",
                refresh_token=None,
                token_expiry=None,
            )
        return SessionUser(
            email="dev@localhost",
            name="Dev User",
            picture=None,
            access_token="",
            refresh_token=None,
            token_expiry=None,
        )

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif gf_session:
        token = gf_session
    if not token:
        token = request.cookies.get(settings.session_cookie_name)

    if not token:
        return None
    user = load_session_token(settings, token)
    if user is None:
        return None
    if settings.multi_tenant:
        return _hydrate_tenant_user(settings, user)
    return user


def _hydrate_tenant_user(settings: Settings, user: SessionUser) -> SessionUser | None:
    """Refresh role / spreadsheet_id from control plane; reject disabled users."""
    store = get_control_store(settings)
    record = None
    if user.user_id:
        record = store.get_user_by_id(user.user_id)
    if record is None and user.email:
        record = store.get_user_by_email(user.email)
    if record is None:
        # Session without control-plane row (e.g. revoked) — treat as unauthenticated
        return None
    if record.disabled_at:
        return None
    user.user_id = record.id
    user.role = record.role
    user.spreadsheet_id = record.spreadsheet_id
    user.email = record.email
    if record.name:
        user.name = record.name
    if record.picture:
        user.picture = record.picture
    return user


def require_user(
    user: Annotated[SessionUser | None, Depends(get_session_user)],
    settings: SettingsDep,
) -> SessionUser:
    _reject_unpermitted_open_auth(settings)
    if settings.auth_mode == "disabled" and not settings.multi_tenant:
        return SessionUser(
            email="anonymous@localhost",
            name="Anonymous",
            picture=None,
            access_token="",
            refresh_token=None,
            token_expiry=None,
        )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Visit /api/auth/login",
        )
    if settings.multi_tenant:
        if not user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not registered. An invite is required.",
            )
        set_tenant_id(user.user_id)
    return user


UserDep = Annotated[SessionUser, Depends(require_user)]


def require_platform_admin(user: UserDep, settings: SettingsDep) -> SessionUser:
    if not settings.multi_tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Multi-tenant admin APIs are disabled.",
        )
    if user.role != "platform_admin":
        # Also allow env allowlist match
        admins = {
            normalize_email(e)
            for e in (settings.platform_admin_emails or "").split(",")
            if e.strip()
        }
        if normalize_email(user.email) not in admins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform admin required.",
            )
    return user


PlatformAdminDep = Annotated[SessionUser, Depends(require_platform_admin)]


def _use_memory_repo(settings: Settings) -> bool:
    """InMemory only for explicit memory backend, tests, or unconfigured Sheets status path."""
    backend = (os.environ.get("REPO_BACKEND") or "").strip().lower()
    if backend in {"memory", "inmemory", "mem"}:
        return True
    if settings.app_env == "test":
        return True
    if settings.multi_tenant and settings.multi_tenant_memory_sheets:
        return True
    # Unconfigured single-tenant: empty memory so /sheets/status can report
    if not settings.multi_tenant and not settings.spreadsheet_id:
        return True
    return False


def get_memory_repo_for_tenant(tenant_key: str) -> InMemorySheetsRepository:
    """Isolated in-memory ledger per tenant/spreadsheet key."""
    key = (tenant_key or "default").strip() or "default"
    repo = _TENANT_MEMORY_REPOS.get(key)
    if repo is None:
        repo = InMemorySheetsRepository()
        _TENANT_MEMORY_REPOS[key] = repo
    return repo


def get_repository(
    settings: SettingsDep,
    user: Annotated[SessionUser | None, Depends(get_session_user)],
) -> SheetsRepository:
    """
    Resolve repository.

    Single-tenant:
      - REPO_BACKEND=memory / test / no SPREADSHEET_ID → empty InMemory
      - otherwise Google Sheets via service account or OAuth user token

    Multi-tenant:
      - Always bind to the authenticated user's spreadsheet_id (control plane)
      - Never fall back to env SPREADSHEET_ID for user data
      - Memory backends are keyed per spreadsheet_id / user_id
    """
    global _DEV_MEMORY_REPO

    if settings.multi_tenant:
        if user is None or not user.user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
            )
        set_tenant_id(user.user_id)
        store = get_control_store(settings)
        record = store.get_user_by_id(user.user_id)
        if record is None or record.disabled_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not available.",
            )
        sheet_id = (record.spreadsheet_id or "").strip()
        if not sheet_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Tenant spreadsheet is not provisioned. "
                    "POST /api/tenant/provision after accepting an invite."
                ),
            )
        if _use_memory_repo(settings):
            return get_memory_repo_for_tenant(sheet_id)

        cache_key = f"mt:{sheet_id}"
        if cache_key in _REPO_CACHE:
            return _REPO_CACHE[cache_key]
        try:
            # Platform SA opens the tenant sheet (never another user's env default)
            from backend.sheets.google_sheets import (
                GoogleSheetsRepository,
                credentials_from_service_account,
            )

            creds = credentials_from_service_account(
                json_path=settings.google_application_credentials,
                json_inline=settings.google_service_account_json or None,
            )
            repo = GoogleSheetsRepository(spreadsheet_id=sheet_id, credentials=creds)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Google Sheets unavailable: {exc}",
            ) from exc
        _REPO_CACHE[cache_key] = repo
        return repo

    # —— single-tenant path (unchanged behaviour) ——
    if _use_memory_repo(settings):
        if _DEV_MEMORY_REPO is None:
            _DEV_MEMORY_REPO = InMemorySheetsRepository()
        return _DEV_MEMORY_REPO

    if not settings.spreadsheet_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SPREADSHEET_ID is not configured",
        )

    cache_key = "sa"
    user_creds = None
    if settings.auth_mode == "oauth" and user and user.access_token:
        cache_key = f"user:{user.email}"
        user_creds = user_credentials_from_session(settings, user)

    if cache_key in _REPO_CACHE:
        return _REPO_CACHE[cache_key]

    try:
        repo = build_repository_from_settings(settings, user_credentials=user_creds)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Google Sheets unavailable: {exc}",
        ) from exc

    _REPO_CACHE[cache_key] = repo
    return repo


RepoDep = Annotated[SheetsRepository, Depends(get_repository)]


def clear_repo_cache(*, spreadsheet_id: str | None = None) -> None:
    """
    Drop process repo singletons.

    When spreadsheet_id is set, only that multi-tenant entry is removed.
    """
    if spreadsheet_id:
        sid = spreadsheet_id.strip()
        _REPO_CACHE.pop(f"mt:{sid}", None)
        return
    _REPO_CACHE.clear()


def clear_tenant_memory_repos() -> None:
    _TENANT_MEMORY_REPOS.clear()


def open_tenant_repository(settings: Settings, spreadsheet_id: str):
    """Open a tenant ledger for cron/background (no request session)."""
    sid = (spreadsheet_id or "").strip()
    if not sid:
        raise ValueError("spreadsheet_id required")
    if _use_memory_repo(settings):
        return get_memory_repo_for_tenant(sid)
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    cache_key = f"mt:{sid}"
    if cache_key in _REPO_CACHE:
        return _REPO_CACHE[cache_key]
    creds = credentials_from_service_account(
        json_path=settings.google_application_credentials,
        json_inline=settings.google_service_account_json or None,
    )
    repo = GoogleSheetsRepository(spreadsheet_id=sid, credentials=creds)
    _REPO_CACHE[cache_key] = repo
    return repo
