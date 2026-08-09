"""Google OAuth login routes."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, Response
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

router = APIRouter(prefix="/auth", tags=["auth"])


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
    session_user = session_from_token_response(tokens, userinfo)
    if not session_user.email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    token = create_session_token(settings, session_user)
    # Always land on the SPA dashboard (not /settings, /docs, or a deep link).
    if settings.cors_origin_list:
        dest = settings.cors_origin_list[0].rstrip("/") + "/"
    else:
        dest = "/"
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
    return AuthMeResponse(
        email=user.email,
        name=user.name,
        picture=user.picture,
        auth_mode=settings.auth_mode,
    )


@router.post("/logout")
async def logout(settings: SettingsDep) -> JSONResponse:
    resp = JSONResponse({"status": "logged_out"})
    resp.delete_cookie(settings.session_cookie_name)
    return resp
