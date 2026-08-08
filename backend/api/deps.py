"""FastAPI dependencies: settings, auth, repository."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from backend.api.auth import SessionUser, load_session_token, user_credentials_from_session
from backend.config import Settings, get_settings
from backend.sheets.google_sheets import build_repository_from_settings
from backend.sheets.repository import InMemorySheetsRepository, SheetsRepository

# Dev/test singleton so in-memory mode persists across requests
_DEV_MEMORY_REPO: InMemorySheetsRepository | None = None
_REPO_CACHE: dict[str, SheetsRepository] = {}


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def get_session_user(
    request: Request,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
    gf_session: Annotated[str | None, Cookie(alias="gf_session")] = None,
) -> SessionUser | None:
    if settings.auth_mode in {"dev", "disabled"}:
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
    return load_session_token(settings, token)


def require_user(
    user: Annotated[SessionUser | None, Depends(get_session_user)],
    settings: SettingsDep,
) -> SessionUser:
    if settings.auth_mode == "disabled":
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
    return user


UserDep = Annotated[SessionUser, Depends(require_user)]


def _use_memory_repo(settings: Settings) -> bool:
    """InMemory only for explicit memory backend, tests, or unconfigured Sheets status path."""
    backend = (os.environ.get("REPO_BACKEND") or "").strip().lower()
    if backend in {"memory", "inmemory", "mem"}:
        return True
    if settings.app_env == "test":
        return True
    # Unconfigured: empty memory so /sheets/status can report (no demo seed)
    if not settings.spreadsheet_id:
        return True
    return False


def get_repository(
    settings: SettingsDep,
    user: Annotated[SessionUser | None, Depends(get_session_user)],
) -> SheetsRepository:
    """
    Resolve repository.

    - REPO_BACKEND=memory / test / no SPREADSHEET_ID → empty InMemory (no silent demo seed)
    - otherwise Google Sheets via service account or OAuth user token
    """
    global _DEV_MEMORY_REPO

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


def clear_repo_cache() -> None:
    _REPO_CACHE.clear()
