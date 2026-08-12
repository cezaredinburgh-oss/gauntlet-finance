"""Google OAuth + demo password login routes."""

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
from backend.api.schemas import (
    AuthMeResponse,
    PasswordLoginRequest,
    PasswordLoginResponse,
)
from backend.api.session_cookies import (
    clear_guest_cookie,
    clear_session_cookie,
    set_guest_cookie,
    set_session_cookie,
)
from backend.services.demo_auth import DemoAuthError, authenticate_password_login
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
            dest = (
                f"{origin}/login?auth_error=not_invited&email={quote(email)}"
                if origin
                else "/login?auth_error=not_invited"
            )
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
    set_session_cookie(resp, settings, token)
    resp.delete_cookie("gf_oauth_state", path="/", samesite="lax")
    return resp


@router.post("/password", response_model=PasswordLoginResponse)
async def password_login(
    body: PasswordLoginRequest,
    request: Request,
    settings: SettingsDep,
) -> JSONResponse:
    """
    Demo (or configured) password login.

    Issues the same httpOnly session cookie as OAuth. Demo principal is never admin.
    """
    client_ip = ""
    if request.client:
        client_ip = request.client.host or ""
    try:
        session_user = authenticate_password_login(
            settings,
            email=body.email,
            password=body.password,
            client_ip=client_ip,
        )
    except DemoAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    token = create_session_token(settings, session_user)
    payload = PasswordLoginResponse(
        status="ok",
        email=session_user.email,
        is_demo=session_user.is_demo,
        role=session_user.role,
    )
    resp = JSONResponse(payload.model_dump())
    set_session_cookie(resp, settings, token)
    return resp


@router.get("/me", response_model=AuthMeResponse)
async def me(
    settings: SettingsDep,
    user: UserDep,
) -> AuthMeResponse:
    ready = bool(user.spreadsheet_id) if settings.multi_tenant else settings.spreadsheet_configured
    if user.is_demo and settings.multi_tenant:
        ready = bool(user.spreadsheet_id)
    return AuthMeResponse(
        email=user.email,
        name=user.name,
        picture=user.picture,
        auth_mode=settings.auth_mode,
        multi_tenant=settings.multi_tenant,
        user_id=user.user_id,
        role=user.role if (settings.multi_tenant or user.is_demo) else None,
        tenant_ready=ready if not user.is_demo else bool(user.spreadsheet_id or not settings.multi_tenant),
        spreadsheet_bound=bool(user.spreadsheet_id) if settings.multi_tenant else settings.spreadsheet_configured,
        is_demo=user.is_demo,
        demo_login_enabled=settings.demo_login_enabled,
    )


@router.get("/public-config")
async def public_auth_config(settings: SettingsDep) -> dict:
    """Unauthenticated flags for the landing page (no secrets)."""
    # In AUTH_MODE=dev the API always returns a session — demo/Google login UIs are secondary.
    return {
        "auth_mode": settings.auth_mode,
        "multi_tenant": settings.multi_tenant,
        "demo_login_enabled": bool(
            settings.demo_login_enabled and (settings.demo_password or "").strip()
        ),
        "demo_email": (
            (settings.demo_email or "demo@gauntlet.local").strip().lower()
            if settings.demo_login_enabled
            else None
        ),
        "owner_login_enabled": bool(
            (settings.owner_email or "").strip() and (settings.owner_password or "").strip()
        ),
        "owner_email": (
            (settings.owner_email or "").strip().lower()
            if (settings.owner_email or "").strip() and (settings.owner_password or "").strip()
            else None
        ),
        "google_login_available": (
            settings.auth_mode == "oauth"
            and bool(settings.google_client_id and settings.google_client_secret)
        ),
        # True only when the host allows unauthenticated full access (dangerous on public URLs)
        "open_auth": bool(settings.open_auth_permitted)
        and settings.auth_mode in {"dev", "disabled"},
    }


@router.post("/logout")
async def logout(settings: SettingsDep) -> JSONResponse:
    """
    Clear session cookie and enter guest mode.

    Guest mode suppresses AUTH_MODE=dev synthetic auto-login so the landing
    page can show demo/Google forms after Sign out.
    """
    resp = JSONResponse({"status": "logged_out", "guest": True})
    clear_session_cookie(resp, settings)
    set_guest_cookie(resp, settings)
    return resp


@router.post("/local-dev")
async def resume_local_dev(settings: SettingsDep) -> JSONResponse:
    """
    Exit guest mode under open auth (dev/disabled) so synthetic local user returns.
    """
    if settings.auth_mode not in {"dev", "disabled"}:
        raise HTTPException(
            status_code=400,
            detail="Local dev resume only applies when AUTH_MODE is dev or disabled.",
        )
    resp = JSONResponse({"status": "ok", "auth_mode": settings.auth_mode})
    clear_guest_cookie(resp, settings)
    clear_session_cookie(resp, settings)
    return resp
