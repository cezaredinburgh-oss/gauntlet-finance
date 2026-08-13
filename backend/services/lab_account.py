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
    Never copies owner Google Sheets data.
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


def lab_ledger_stats(settings: Settings) -> dict[str, int]:
    """Row counts per major tab (for reset scripts / health)."""
    repo = get_lab_repository(settings)
    tabs = (
        "Categories",
        "CategoryRules",
        "Transactions",
        "InvestmentLots",
        "InvestmentEvents",
        "StatementFiles",
        "Accounts",
        "Prices",
        "Settings",
    )
    out: dict[str, int] = {}
    for tab in tabs:
        try:
            out[tab] = len(repo.list_rows(tab))
        except Exception:  # noqa: BLE001
            out[tab] = -1
    return out


def reset_lab_ledger(settings: Settings, *, dry_run: bool = False) -> dict[str, object]:
    """
    Wipe lab disk ledger and re-seed public categories only (true empty new-user).

    Clears process singleton so the next request reloads from disk.
    """
    path = lab_ledger_path(settings)
    before = lab_ledger_stats(settings) if path.is_file() or _LAB_REPOS else {}
    result: dict[str, object] = {
        "path": str(path),
        "dry_run": dry_run,
        "before": before,
    }
    if dry_run:
        result["would_delete"] = path.is_file()
        result["after"] = before
        return result

    clear_lab_repos_for_tests()
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            logger.exception("lab ledger delete failed: %s", exc)
            raise
    # Drop tmp siblings if any
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.is_file():
        try:
            tmp.unlink()
        except OSError:
            pass

    ensure_lab_seeded(settings)
    after = lab_ledger_stats(settings)
    result["after"] = after
    result["ok"] = after.get("Transactions", 0) == 0 and after.get("InvestmentLots", 0) == 0
    try:
        from backend.services.response_cache import cache_invalidate
        from backend.tenancy.context import reset_tenant_id, set_tenant_id

        tok = set_tenant_id(LAB_USER_ID)
        try:
            cache_invalidate()
        finally:
            reset_tenant_id(tok)
    except Exception:  # noqa: BLE001
        logger.debug("lab cache invalidate skipped", exc_info=True)
    logger.info("lab ledger reset path=%s after=%s", path, after)
    return result


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
