"""Demo password login: fixed env credentials → isolated demo principal."""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict

from backend.api.auth import SessionUser
from backend.config import Settings
from backend.tenancy.store import get_control_store, normalize_email

# Simple in-process rate limit: email+ip → timestamps
_RATE_LOCK = threading.Lock()
_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 20
_WINDOW_SEC = 300.0


class DemoAuthError(Exception):
    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _rate_key(email: str, client_ip: str) -> str:
    return f"{normalize_email(email)}|{client_ip or 'unknown'}"


def check_password_rate_limit(email: str, client_ip: str) -> None:
    now = time.monotonic()
    key = _rate_key(email, client_ip)
    with _RATE_LOCK:
        window = [t for t in _ATTEMPTS[key] if now - t < _WINDOW_SEC]
        if len(window) >= _MAX_ATTEMPTS:
            _ATTEMPTS[key] = window
            raise DemoAuthError(
                "Too many login attempts. Try again later.",
                status_code=429,
            )
        window.append(now)
        _ATTEMPTS[key] = window


def ensure_demo_tenant(settings: Settings) -> SessionUser:
    """
    Ensure demo control-plane user + isolated memory spreadsheet binding.

    Demo is never platform_admin.
    """
    email = normalize_email(settings.demo_email) or "demo@gauntlet.local"
    store = get_control_store(settings)
    user = store.upsert_user_from_oauth(
        email=email,
        google_sub="demo-local",
        name="Demo User",
        picture=None,
        role="user",
    )
    # Never elevate demo
    if user.role != "user":
        user = store.set_role(user.id, "user")
    sheet_id = f"mem-demo-{user.id}"
    if not user.spreadsheet_id:
        try:
            user = store.claim_spreadsheet_id(user.id, sheet_id, only_if_empty=True)
        except ValueError as exc:
            if str(exc) == "already_provisioned":
                refreshed = store.get_user_by_id(user.id)
                if refreshed:
                    user = refreshed
            else:
                # conflict: force unique demo sheet
                user = store.claim_spreadsheet_id(
                    user.id, f"mem-demo-{user.id}-v2", only_if_empty=False
                )
        from backend.api.deps import get_memory_repo_for_tenant
        from backend.services.categorization import ensure_default_categories

        repo = get_memory_repo_for_tenant(user.spreadsheet_id or sheet_id)
        try:
            ensure_default_categories(repo)
        except Exception:  # noqa: BLE001
            pass
    return SessionUser(
        email=user.email,
        name=user.name or "Demo User",
        picture=None,
        access_token="",
        refresh_token=None,
        token_expiry=None,
        user_id=user.id,
        role="user",
        spreadsheet_id=user.spreadsheet_id,
        is_demo=True,
    )


def authenticate_demo_password(
    settings: Settings,
    *,
    email: str,
    password: str,
    client_ip: str = "",
) -> SessionUser:
    """
    Validate demo credentials and return a SessionUser.

    Raises DemoAuthError on failure.
    """
    if not settings.demo_login_enabled:
        raise DemoAuthError("Demo login is disabled.", status_code=403)
    expected_pw = (settings.demo_password or "").strip()
    if not expected_pw:
        raise DemoAuthError(
            "Demo login is not configured (set DEMO_PASSWORD).",
            status_code=503,
        )

    check_password_rate_limit(email, client_ip)

    expected_email = normalize_email(settings.demo_email) or "demo@gauntlet.local"
    got_email = normalize_email(email)
    email_ok = secrets.compare_digest(got_email, expected_email)
    # Pad to reduce trivial length oracle (compare_digest needs same length)
    pw = password or ""
    if len(pw) != len(expected_pw):
        # Still burn a compare of equal length material
        secrets.compare_digest(expected_pw, expected_pw)
        pw_ok = False
    else:
        pw_ok = secrets.compare_digest(pw, expected_pw)

    if not (email_ok and pw_ok):
        raise DemoAuthError("Invalid email or password.")

    if settings.multi_tenant:
        return ensure_demo_tenant(settings)

    # Single-tenant: demo session without control-plane (memory ledger via empty sheet path
    # is process-wide — flag is_demo for UI; ops should use MULTI_TENANT for isolation).
    return SessionUser(
        email=expected_email,
        name="Demo User",
        picture=None,
        access_token="",
        refresh_token=None,
        token_expiry=None,
        user_id=None,
        role="user",
        spreadsheet_id=None,
        is_demo=True,
    )
