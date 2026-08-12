"""Google OAuth login routes."""

from __future__ import annotations

import secrets
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from backend.api.auth import (
    create_session_token,
    exchange_code,
    fetch_userinfo,
    google_authorize_url,
    session_from_token_response,
)
from backend.api.deps import SettingsDep, UserDep
from backend.api.schemas import AuthMeResponse
from backend.tenancy.store import get_control_store, normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])


def _spa_origin(settings) -> str:
    if settings.cors_origin_list:
        return settings.cors_origin_list[0].rstrip("/")
    return ""


@router.get("/login")
async def login(settings: SettingsDep) -> RedirectResponse:
    if settings.auth_mode != "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"OAuth login disabled (auth_mode={settings.auth_mode}). Set AUTH_MODE=oauth.",
        )
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="GOOGLE_CLIENT_ID/SECRET not configured")
    state = secrets.token_urlsafe(24)
    url = google_authorize_url(settings, state)
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie("gf_oauth_state", state, httponly=True, max_age=600, samesite="lax")
    return resp


@router.get("/callback")
async def callback(
    request: Request,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    expected = request.cookies.get("gf_oauth_state")
    if not expected or not state or state != expected:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    tokens = await exchange_code(settings, code)
    userinfo = await fetch_userinfo(tokens["access_token"])
    email = normalize_email(userinfo.get("email") or "")
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    origin = _spa_origin(settings)

    if settings.multi_tenant:
        store = get_control_store(settings)
        if not store.is_email_allowed(email):
            # Not invited — do not create a session that can access data
            dest = f"{origin}/?auth_error=not_invited&email={quote(email)}" if origin else "/"
            resp = RedirectResponse(url=dest, status_code=302)
            resp.delete_cookie("gf_oauth_state")
            return resp

        # Promote platform admins from env; accept invite; upsert user
        admins = {
            normalize_email(e)
            for e in (settings.platform_admin_emails or "").split(",")
            if e.strip()
        }
        role = "platform_admin" if email in admins else None
        record = store.upsert_user_from_oauth(
            email=email,
            google_sub=userinfo.get("sub"),
            name=userinfo.get("name"),
            picture=userinfo.get("picture"),
            role=role,  # type: ignore[arg-type]
        )
        store.accept_invite_for_email(email)
        # refresh after accept / role
        record = store.get_user_by_id(record.id) or record
        session_user = session_from_token_response(
            tokens,
            userinfo,
            user_id=record.id,
            role=record.role,
            spreadsheet_id=record.spreadsheet_id,
        )
    else:
        session_user = session_from_token_response(tokens, userinfo)

    token = create_session_token(settings, session_user)
    dest = f"{origin}/" if origin else "/"
    resp = RedirectResponse(url=dest, status_code=302)
    resp.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        max_age=settings.session_max_age_seconds,
        samesite="lax",
        secure=settings.app_env == "production",
    )
    resp.delete_cookie("gf_oauth_state")
    return resp


@router.get("/me", response_model=AuthMeResponse)
async def me(
    settings: SettingsDep,
    user: UserDep,
) -> AuthMeResponse:
    ready = bool(user.spreadsheet_id) if settings.multi_tenant else settings.spreadsheet_configured
    return AuthMeResponse(
        email=user.email,
        name=user.name,
        picture=user.picture,
        auth_mode=settings.auth_mode,
        multi_tenant=settings.multi_tenant,
        user_id=user.user_id,
        role=user.role if settings.multi_tenant else None,
        tenant_ready=ready,
        spreadsheet_bound=bool(user.spreadsheet_id) if settings.multi_tenant else settings.spreadsheet_configured,
    )


@router.post("/logout")
async def logout(settings: SettingsDep) -> JSONResponse:
    resp = JSONResponse({"status": "logged_out"})
    resp.delete_cookie(settings.session_cookie_name)
    return resp
