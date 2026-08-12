"""Consistent session / guest cookie helpers (path/samesite/secure must match)."""

from __future__ import annotations

import os

from fastapi.responses import Response

from backend.config import Settings

# When value is "1", open-auth synthetic user and leftover sessions are ignored.
GUEST_COOKIE_NAME = "gf_guest"
GUEST_COOKIE_VALUE = "1"
GUEST_OFF_VALUE = "0"


def _cookie_common(settings: Settings) -> dict:
    # Secure cookies are not stored by HTTP TestClient; skip Secure under pytest.
    secure = settings.is_production and "PYTEST_CURRENT_TEST" not in os.environ
    return {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
    }


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_max_age_seconds,
        **_cookie_common(settings),
    )
    # Successful login ends guest mode (set 0 so clients update jar reliably)
    clear_guest_cookie(response, settings)


def clear_session_cookie(response: Response, settings: Settings) -> None:
    # Empty + Max-Age=0 (and explicit expires via Starlette)
    response.set_cookie(
        settings.session_cookie_name,
        "",
        max_age=0,
        **_cookie_common(settings),
    )
    if settings.session_cookie_name != "gf_session":
        response.set_cookie(
            "gf_session",
            "",
            max_age=0,
            **_cookie_common(settings),
        )


def set_guest_cookie(response: Response, settings: Settings) -> None:
    """Mark browser as explicitly signed out."""
    response.set_cookie(
        GUEST_COOKIE_NAME,
        GUEST_COOKIE_VALUE,
        max_age=settings.session_max_age_seconds,
        **_cookie_common(settings),
    )


def clear_guest_cookie(response: Response, settings: Settings) -> None:
    """Exit guest mode (login / local-dev resume)."""
    response.set_cookie(
        GUEST_COOKIE_NAME,
        GUEST_OFF_VALUE,
        max_age=settings.session_max_age_seconds,
        **_cookie_common(settings),
    )


def is_guest_request(request_cookies: dict[str, str] | None) -> bool:
    if not request_cookies:
        return False
    return request_cookies.get(GUEST_COOKIE_NAME) == GUEST_COOKIE_VALUE
