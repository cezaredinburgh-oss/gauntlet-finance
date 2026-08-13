"""Persistent lab test account: empty new-user surface, disk ledger, full writes."""

from __future__ import annotations

import logging
from pathlib import Path

from backend.api.auth import SessionUser
from backend.config import Settings, project_root
from backend.sheets.disk_memory import DiskBackedSheetsRepository

logger = logging.getLogger(__name__)

LAB_SHEET_ID = "lab-account"
LAB_USER_ID = "lab-account"
LAB_NAME = "Lab Account"

# Process singleton (path → repo)
_LAB_REPOS: dict[str, DiskBackedSheetsRepository] = {}


def lab_data_dir(settings: Settings) -> Path:
    raw = (settings.lab_data_dir or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else project_root() / p
    return project_root() / "data" / "lab"


def lab_ledger_path(settings: Settings) -> Path:
    return lab_data_dir(settings) / "ledger.json"


def get_lab_repository(settings: Settings) -> DiskBackedSheetsRepository:
    """Disk-backed ledger for the single shared lab principal."""
    path = lab_ledger_path(settings)
    key = str(path.resolve())
    repo = _LAB_REPOS.get(key)
    if repo is None:
        repo = DiskBackedSheetsRepository(path)
        _LAB_REPOS[key] = repo
    return repo


def clear_lab_repos_for_tests() -> None:
    """Drop process lab singletons (tests only)."""
    _LAB_REPOS.clear()


def ensure_lab_seeded(settings: Settings) -> DiskBackedSheetsRepository:
    """
    Ensure lab ledger exists with public default categories (empty new-user pack).

    Idempotent: only seeds when Categories tab is empty.
    """
    repo = get_lab_repository(settings)
    try:
        cats = repo.list_rows("Categories")
    except Exception:  # noqa: BLE001
        cats = []
    if not cats:
        from backend.schema.demo_public import ensure_public_demo_categories

        try:
            ensure_public_demo_categories(repo)
        except Exception:
            logger.exception("lab ensure_public_demo_categories failed")
            raise
    return repo


def ensure_lab_session(settings: Settings) -> SessionUser:
    """Return the fixed lab SessionUser and ensure disk ledger is ready."""
    ensure_lab_seeded(settings)
    email = (settings.lab_email or "testaccount@o2.pl").strip().lower()
    return SessionUser(
        email=email,
        name=LAB_NAME,
        picture=None,
        access_token="",
        refresh_token=None,
        token_expiry=None,
        user_id=LAB_USER_ID,
        role="user",
        spreadsheet_id=LAB_SHEET_ID,
        is_demo=True,
        demo_kind="lab",
    )


def lab_login_configured(settings: Settings) -> bool:
    return bool(
        settings.lab_login_enabled and (settings.lab_password or "").strip()
    )
