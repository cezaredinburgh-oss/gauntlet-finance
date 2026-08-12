"""Google OAuth + session JWT helpers."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.config import Settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

OAUTH_SCOPES = " ".join(
    [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]
)

DemoKind = Literal["sandbox", "tour", ""]


@dataclass
class SessionUser:
    email: str
    name: str | None
    picture: str | None
    access_token: str
    refresh_token: str | None
    token_expiry: float | None  # unix ts
    # Multi-tenant control-plane fields (optional in single-tenant)
    user_id: str | None = None
    role: str = "user"
    spreadsheet_id: str | None = None
    is_demo: bool = False
    # Public demos: "sandbox" (writable ephemeral) | "tour" (read-only seed) | ""
    demo_kind: DemoKind = ""

    @property
    def read_only(self) -> bool:
        """Tour demo is server-enforced read-only."""
        return bool(self.is_demo and self.demo_kind == "tour")


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="gf-session-v1")


def create_session_token(settings: Settings, user: SessionUser) -> str:
    payload = {
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "access_token": user.access_token,
        "refresh_token": user.refresh_token,
        "token_expiry": user.token_expiry,
        "user_id": user.user_id,
        "role": user.role,
        "spreadsheet_id": user.spreadsheet_id,
        "is_demo": user.is_demo,
        "demo_kind": user.demo_kind or "",
    }
    return _serializer(settings).dumps(payload)


def load_session_token(
    settings: Settings,
    token: str,
) -> SessionUser | None:
    try:
        data = _serializer(settings).loads(
            token,
            max_age=settings.session_max_age_seconds,
        )
    except (BadSignature, SignatureExpired):
        return None
    raw_kind = (data.get("demo_kind") or "").strip().lower()
    kind: DemoKind = (
        "sandbox" if raw_kind == "sandbox" else "tour" if raw_kind == "tour" else ""
    )
    # Legacy password-demo sessions: is_demo without kind → treat as sandbox (writable).
    is_demo = bool(data.get("is_demo"))
    if is_demo and not kind:
        kind = "sandbox"
    return SessionUser(
        email=data["email"],
        name=data.get("name"),
        picture=data.get("picture"),
        access_token=data.get("access_token") or "",
        refresh_token=data.get("refresh_token"),
        token_expiry=data.get("token_expiry"),
        user_id=data.get("user_id"),
        role=data.get("role") or "user",
        spreadsheet_id=data.get("spreadsheet_id"),
        is_demo=is_demo,
        demo_kind=kind if is_demo else "",
    )


def google_authorize_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(settings: Settings, code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(settings: Settings, refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()


def session_from_token_response(
    tokens: dict[str, Any],
    userinfo: dict[str, Any],
    *,
    user_id: str | None = None,
    role: str = "user",
    spreadsheet_id: str | None = None,
) -> SessionUser:
    expires_in = tokens.get("expires_in")
    expiry = time.time() + int(expires_in) if expires_in else None
    return SessionUser(
        email=userinfo.get("email") or "",
        name=userinfo.get("name"),
        picture=userinfo.get("picture"),
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        token_expiry=expiry,
        user_id=user_id,
        role=role,
        spreadsheet_id=spreadsheet_id,
    )


def user_credentials_from_session(settings: Settings, user: SessionUser):
    from backend.sheets.google_sheets import credentials_from_user_token

    return credentials_from_user_token(
        token=user.access_token,
        refresh_token=user.refresh_token,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
