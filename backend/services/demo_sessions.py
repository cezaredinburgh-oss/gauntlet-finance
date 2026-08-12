"""One-click public demos: ephemeral sandbox + read-only synthetic tour."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

from backend.api.auth import SessionUser
from backend.config import Settings
from backend.services.demo_auth import DemoAuthError, check_password_rate_limit

logger = logging.getLogger(__name__)

TOUR_SHEET_ID = "tour-shared"
TOUR_USER_ID = "tour"
TOUR_EMAIL = "tour@gauntlet.local"
SANDBOX_EMAIL = "sandbox@gauntlet.local"

# sandbox_id → last enter monotonic time
_SANDBOX_LOCK = threading.Lock()
_ACTIVE_SANDBOXES: dict[str, float] = {}
_TOUR_SEEDED = False
_TOUR_LOCK = threading.Lock()


def clear_demo_session_state_for_tests() -> None:
    """Reset process-local demo session tracking (tests only)."""
    global _TOUR_SEEDED
    with _SANDBOX_LOCK:
        _ACTIVE_SANDBOXES.clear()
    with _TOUR_LOCK:
        _TOUR_SEEDED = False


def demo_memory_key(spreadsheet_or_user_id: str) -> str:
    return f"demo:{(spreadsheet_or_user_id or '').strip()}"


def drop_demo_memory_repo(spreadsheet_or_user_id: str) -> None:
    from backend.api.deps import drop_memory_repo_key

    drop_memory_repo_key(demo_memory_key(spreadsheet_or_user_id))


def _purge_sandbox_uploads(user_id: str) -> None:
    """Best-effort delete of on-disk upload blobs for a sandbox tenant."""
    try:
        from backend.services import upload_store

        # uploads_dir() is tenant-scoped via context; set then resolve parent layout.
        from backend.tenancy.context import reset_tenant_id, set_tenant_id

        tok = set_tenant_id(user_id)
        try:
            path = upload_store.uploads_dir()
            if path.is_dir() and path.name and path.name != "uploads":
                shutil.rmtree(path, ignore_errors=True)
        finally:
            reset_tenant_id(tok)
    except Exception as exc:  # noqa: BLE001
        logger.debug("sandbox upload purge skipped: %s", exc)


def destroy_sandbox_session(user: SessionUser) -> None:
    """Wipe memory ledger + uploads for a sandbox principal."""
    if not user.is_demo or user.demo_kind != "sandbox":
        return
    sid = (user.spreadsheet_id or user.user_id or "").strip()
    if not sid:
        return
    drop_demo_memory_repo(sid)
    with _SANDBOX_LOCK:
        _ACTIVE_SANDBOXES.pop(sid, None)
    _purge_sandbox_uploads(user.user_id or sid)


def _count_active_sandboxes() -> int:
    with _SANDBOX_LOCK:
        return len(_ACTIVE_SANDBOXES)


def ensure_tour_seeded() -> None:
    """Load synthetic seed into the shared tour memory ledger once per process."""
    global _TOUR_SEEDED
    with _TOUR_LOCK:
        if _TOUR_SEEDED:
            return
        from backend.api.deps import get_memory_repo_for_tenant
        from backend.scripts.seed_dev_repo import seed_full_demo

        repo = get_memory_repo_for_tenant(demo_memory_key(TOUR_SHEET_ID))
        try:
            seed_full_demo(repo)
        except Exception:
            logger.exception("tour seed failed")
            raise
        _TOUR_SEEDED = True


def enter_sandbox(settings: Settings, *, client_ip: str = "") -> SessionUser:
    """Create a fresh empty (defaults-only) per-session sandbox ledger."""
    if not settings.demo_sandbox_enabled:
        raise DemoAuthError(
            "Sandbox demo is disabled on this host.",
            status_code=403,
        )
    # Reuse password rate-limit bucket key with a fixed email identity for IP.
    check_password_rate_limit(SANDBOX_EMAIL, client_ip)

    max_active = max(1, int(settings.demo_sandbox_max_active or 50))
    if _count_active_sandboxes() >= max_active:
        raise DemoAuthError(
            "Too many active sandboxes. Try again later.",
            status_code=503,
        )

    sid = f"sandbox-{uuid4()}"
    with _SANDBOX_LOCK:
        _ACTIVE_SANDBOXES[sid] = time.monotonic()

    from backend.api.deps import get_memory_repo_for_tenant
    from backend.services.categorization import ensure_default_categories

    repo = get_memory_repo_for_tenant(demo_memory_key(sid))
    try:
        ensure_default_categories(repo)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sandbox ensure_default_categories: %s", exc)

    return SessionUser(
        email=SANDBOX_EMAIL,
        name="Sandbox",
        picture=None,
        access_token="",
        refresh_token=None,
        token_expiry=None,
        user_id=sid,
        role="user",
        spreadsheet_id=sid,
        is_demo=True,
        demo_kind="sandbox",
    )


def enter_tour(settings: Settings, *, client_ip: str = "") -> SessionUser:
    """Enter the shared synthetic read-only portfolio."""
    if not settings.demo_tour_enabled:
        raise DemoAuthError(
            "Sample portfolio tour is disabled on this host.",
            status_code=403,
        )
    check_password_rate_limit(TOUR_EMAIL, client_ip)
    ensure_tour_seeded()
    return SessionUser(
        email=TOUR_EMAIL,
        name="Sample portfolio",
        picture=None,
        access_token="",
        refresh_token=None,
        token_expiry=None,
        user_id=TOUR_USER_ID,
        role="user",
        spreadsheet_id=TOUR_SHEET_ID,
        is_demo=True,
        demo_kind="tour",
    )
