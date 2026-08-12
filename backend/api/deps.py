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


def _session_token_from_request(
    request: Request,
    settings: Settings,
    authorization: str | None,
    gf_session: str | None,
) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip() or None
    if gf_session:
        return gf_session
    return request.cookies.get(settings.session_cookie_name) or request.cookies.get(
        "gf_session"
    )


def get_session_user(
    request: Request,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
    gf_session: Annotated[str | None, Cookie(alias="gf_session")] = None,
) -> SessionUser | None:
    from backend.api.session_cookies import is_guest_request

    token = _session_token_from_request(request, settings, authorization, gf_session)
    guest = is_guest_request(request.cookies)

    # Explicit Sign out: ignore leftover session cookies until the next login.
    # (Login clears gf_guest via set_session_cookie.)
    if guest:
        return None

    if settings.auth_mode in {"dev", "disabled"}:
        # Prefer real session cookie (demo / owner password / explicit login).
        if token:
            user = load_session_token(settings, token)
            if user is not None:
                if settings.multi_tenant and not user.is_demo:
                    return _hydrate_tenant_user(settings, user)
                return user
        # Open-auth synthetic ONLY when explicitly allowed (never on public production
        # unless ALLOW_OPEN_AUTH=true — do not auto-expose the real ledger).
        if settings.open_auth_permitted:
            return SessionUser(
                email="dev@localhost" if settings.auth_mode == "dev" else "anonymous@localhost",
                name="Dev User" if settings.auth_mode == "dev" else "Anonymous",
                picture=None,
                access_token="",
                refresh_token=None,
                token_expiry=None,
            )
        return None

    if not token:
        return None
    user = load_session_token(settings, token)
    if user is None:
        return None
    # Public demos use isolated memory keys in the JWT — never control-plane hydrate
    # (sandbox ids are not control users; tour is a fixed principal).
    if user.is_demo:
        return user
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
    is_demo = user.is_demo
    demo_kind = user.demo_kind
    user.user_id = record.id
    # Demo principal must never become platform_admin via env promote
    if is_demo:
        user.role = "user"
        # Preserve sandbox/tour kind from the session cookie
        user.demo_kind = demo_kind or "sandbox"
    else:
        user.role = record.role
        user.demo_kind = ""
    user.spreadsheet_id = record.spreadsheet_id
    user.email = record.email
    user.is_demo = is_demo
    if record.name:
        user.name = record.name
    if record.picture and not is_demo:
        user.picture = record.picture
    return user


def require_user(
    user: Annotated[SessionUser | None, Depends(get_session_user)],
    settings: SettingsDep,
) -> SessionUser:
    # Open-auth synthetic is created in get_session_user only when open_auth_permitted.
    # No session → 401 (login required), not silent full ledger access.
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Visit /login",
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


def drop_memory_repo_key(tenant_key: str) -> None:
    """Remove one in-memory ledger (sandbox logout)."""
    key = (tenant_key or "").strip()
    if key:
        _TENANT_MEMORY_REPOS.pop(key, None)


def require_writable(user: UserDep) -> SessionUser:
    """Block mutations for the public tour (sample portfolio) principal."""
    if user.is_demo and user.demo_kind == "tour":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sample portfolio is read-only. Use Try with your statements to upload.",
        )
    return user


WritableUserDep = Annotated[SessionUser, Depends(require_writable)]


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

    # Demo sessions never touch the production Google Sheet (isolated memory ledger).
    if user is not None and user.is_demo:
        # Tour data is process-local: after redeploy / multi-worker, memory is empty
        # while the session cookie still says "tour". Re-seed on every repo resolve
        # (idempotent when already full).
        if user.demo_kind == "tour":
            from backend.services.demo_sessions import ensure_tour_seeded

            ensure_tour_seeded()
        set_tenant_id(user.user_id or "demo")
        key = (user.spreadsheet_id or user.user_id or "demo-public").strip()
        return get_memory_repo_for_tenant(f"demo:{key}")

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
