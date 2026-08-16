"""Persistent lab test account: empty new-user surface, disk ledger, full writes."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from backend.api.auth import SessionUser
from backend.config import Settings, project_root
from backend.sheets.disk_memory import DiskBackedSheetsRepository

logger = logging.getLogger(__name__)

LAB_SHEET_ID = "lab-account"
LAB_USER_ID = "lab-account"
LAB_NAME = "Lab Account"
LAB_RESET_CONFIRM = "WIPE LAB"

# Process singleton (path → repo)
_LAB_REPOS: dict[str, DiskBackedSheetsRepository] = {}

_CLOUD_DIR_MARKERS = ("iclouddrive", "icloud drive", "onedrive", "dropbox")


def path_is_cloud_synced(path: Path) -> bool:
    """True when *path* lives under iCloud / OneDrive / Dropbox (conflict-prone)."""
    try:
        parts = [p.lower() for p in path.resolve().parts]
    except OSError:
        return False
    return any(marker in parts for marker in _CLOUD_DIR_MARKERS)


def local_lab_data_dir() -> Path:
    """Machine-local lab dir (not iCloud). Windows: %LOCALAPPDATA%\\GauntletFinance\\lab."""
    raw = os.environ.get("LOCALAPPDATA", "").strip()
    if raw:
        return Path(raw) / "GauntletFinance" / "lab"
    return Path.home() / ".gauntlet-finance" / "lab"


def newest_ledger_snapshot(directory: Path) -> Path | None:
    """Newest ``ledger*.json`` in *directory* (canonical or iCloud numbered copies)."""
    if not directory.is_dir():
        return None
    candidates: list[Path] = []
    try:
        names = list(directory.iterdir())
    except OSError:
        return None
    for p in names:
        if not p.is_file():
            continue
        name = p.name.lower()
        if not name.startswith("ledger") or not name.endswith(".json"):
            continue
        if ".tmp" in name:
            continue
        try:
            if p.stat().st_size <= 0:
                continue
        except OSError:
            continue
        candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.stat().st_size))


def recover_canonical_ledger(dest: Path, *search_dirs: Path) -> Path | None:
    """
    If *dest* is missing/empty, copy the newest ledger snapshot from *search_dirs*.

    iCloud Drive on Windows renames ``ledger.json`` to ``ledger 2.json`` on
    concurrent sync, so the app would otherwise boot an empty ledger.
    """
    try:
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
    except OSError:
        pass
    found: Path | None = None
    for directory in search_dirs:
        cand = newest_ledger_snapshot(directory)
        if cand is None:
            continue
        if found is None:
            found = cand
            continue
        try:
            if cand.stat().st_mtime > found.stat().st_mtime:
                found = cand
        except OSError:
            continue
    if found is None:
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(found.read_bytes())
    except OSError:
        logger.exception("lab ledger recover failed from %s to %s", found, dest)
        return None
    logger.warning("recovered lab ledger from %s -> %s", found, dest)
    return dest


def _normalize_lab_data_dir_raw(raw: str) -> str:
    """Strip quotes and a pasted ``LAB_DATA_DIR=`` prefix from the env value."""
    s = (raw or "").strip().strip('"').strip("'")
    if "=" in s:
        key, _, val = s.partition("=")
        if key.strip().replace("-", "_").upper() == "LAB_DATA_DIR":
            s = val.strip().strip('"').strip("'")
    return s


def _volume_lab_dir() -> Path | None:
    volume = Path("/data")
    if not volume.is_dir():
        return None
    try:
        if os.access(volume, os.W_OK) if hasattr(os, "access") else True:
            return volume / "lab"
    except OSError:
        return volume / "lab"
    return volume / "lab"


def lab_data_dir(settings: Settings) -> Path:
    """
    Directory for the lab disk ledger.

    Prefer explicit ``LAB_DATA_DIR``. Otherwise use ``/data/lab`` when a
    Railway (or similar) volume is mounted at ``/data``. If the project tree
    is on iCloud/OneDrive, use a local AppData path so sync cannot steal
    ``ledger.json``. Else project ``data/lab``.
    """
    raw = _normalize_lab_data_dir_raw(settings.lab_data_dir or "")
    volume_lab = _volume_lab_dir()
    if raw:
        p = Path(raw)
        candidate = p if p.is_absolute() else project_root() / p
        if path_is_cloud_synced(candidate):
            logger.warning(
                "LAB_DATA_DIR resolves onto a cloud-synced drive (%s); using local AppData",
                candidate,
            )
            return local_lab_data_dir()
        # Relative ``data/lab`` on Railway would land on the ephemeral image FS.
        if volume_lab is not None and not _path_is_under(candidate, Path("/data")):
            logger.warning(
                "LAB_DATA_DIR %s is not on the /data volume; using %s",
                candidate,
                volume_lab,
            )
            return volume_lab
        return candidate
    if volume_lab is not None:
        return volume_lab
    project_lab = project_root() / "data" / "lab"
    if path_is_cloud_synced(project_root()):
        return local_lab_data_dir()
    return project_lab


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def lab_ledger_path(settings: Settings) -> Path:
    return lab_data_dir(settings) / "ledger.json"


def wipe_lab_ledger_files(directory: Path) -> list[str]:
    """Delete canonical + numbered + tmp ``ledger*`` snapshots in *directory* only."""
    deleted: list[str] = []
    if not directory.is_dir():
        return deleted
    try:
        names = list(directory.iterdir())
    except OSError:
        return deleted
    for p in names:
        if not p.is_file():
            continue
        name = p.name.lower()
        if not name.startswith("ledger"):
            continue
        if not (name.endswith(".json") or ".tmp" in name):
            continue
        try:
            p.unlink()
        except OSError:
            logger.exception("lab ledger wipe failed: %s", p)
            raise
        deleted.append(p.name)
    return deleted


def get_lab_repository(
    settings: Settings, *, skip_recover: bool = False
) -> DiskBackedSheetsRepository:
    """Disk-backed ledger for the single shared lab principal."""
    path = lab_ledger_path(settings)
    if not skip_recover:
        project_lab = project_root() / "data" / "lab"
        recover_canonical_ledger(path, path.parent, project_lab)
    key = str(path.resolve())
    repo = _LAB_REPOS.get(key)
    if repo is None:
        repo = DiskBackedSheetsRepository(path)
        _LAB_REPOS[key] = repo
    return repo


def clear_lab_repos_for_tests() -> None:
    """Drop process lab singletons (tests only)."""
    _LAB_REPOS.clear()


def ensure_lab_seeded(
    settings: Settings, *, skip_recover: bool = False
) -> DiskBackedSheetsRepository:
    """
    Ensure lab ledger exists with public default categories (empty new-user pack).

    Idempotent: only seeds when Categories tab is empty.
    Never copies owner Google Sheets data.
    """
    repo = get_lab_repository(settings, skip_recover=skip_recover)
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


def _empty_money_tabs(stats: dict[str, int]) -> bool:
    return all(
        int(stats.get(tab, 0) or 0) == 0
        for tab in (
            "Transactions",
            "InvestmentLots",
            "InvestmentEvents",
            "StatementFiles",
        )
    )


def reset_lab_ledger(settings: Settings, *, dry_run: bool = False) -> dict[str, object]:
    """
    Wipe lab disk ledger and re-seed public categories only (true empty new-user).

    Deletes every ``ledger*.json`` (canonical + numbered iCloud copies) in the
    lab data dir so recover cannot resurrect the old account. Does not touch
    the iCloud archive folder or Google Sheets.

    Clears process singleton so the next request reloads from disk.
    """
    path = lab_ledger_path(settings)
    directory = path.parent
    before = lab_ledger_stats(settings) if path.is_file() or _LAB_REPOS else {}
    existing = []
    if directory.is_dir():
        existing = [
            p.name
            for p in directory.iterdir()
            if p.is_file()
            and p.name.lower().startswith("ledger")
            and (p.name.lower().endswith(".json") or ".tmp" in p.name.lower())
        ]
    result: dict[str, object] = {
        "path": str(path),
        "dry_run": dry_run,
        "before": before,
        "would_delete": existing,
    }
    if dry_run:
        result["after"] = before
        return result

    clear_lab_repos_for_tests()
    result["deleted"] = wipe_lab_ledger_files(directory)

    # Skip recover so a leftover project-tree snapshot cannot undo the wipe.
    ensure_lab_seeded(settings, skip_recover=True)
    after = lab_ledger_stats(settings)
    result["after"] = after
    cats = int(after.get("Categories", 0) or 0)
    result["ok"] = _empty_money_tabs(after) and cats > 0
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
    """
    Lab password login is one optional tester principal.

    On when LAB_LOGIN_ENABLED and LAB_PASSWORD are set — including Railway
    multi-tenant production. Ledger is DiskBackedSheetsRepository on the
    volume (``/data/lab``), never a Google Sheet. Invited OAuth tenants stay
    on their own Sheets; they do not share this JSON.
    """
    return bool(settings.lab_login_enabled and (settings.lab_password or "").strip())
