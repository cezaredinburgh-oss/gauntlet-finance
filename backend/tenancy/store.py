"""SQLite control-plane store for multi-tenant users and invites."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.config import Settings, get_settings
from backend.tenancy.models import Invite, TenantUser, UserRole

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    google_sub TEXT,
    name TEXT,
    picture TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    spreadsheet_id TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invites (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL COLLATE NOCASE,
    invited_by TEXT,
    token_hash TEXT,
    expires_at TEXT,
    accepted_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invites_email ON invites(email);
CREATE INDEX IF NOT EXISTS idx_users_spreadsheet ON users(spreadsheet_id);
"""

# Separate locks: never hold singleton lock while taking db lock (deadlock).
_db_lock = threading.Lock()
_singleton_lock = threading.Lock()
_STORE: ControlStore | None = None
_STORE_PATH: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def default_control_db_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    raw = (settings.control_db_path or "").strip()
    if raw:
        return Path(raw)
    data = Path("/data")
    if data.is_dir():
        return data / "gauntlet_control.db"
    return _PROJECT_ROOT / "data" / "gauntlet_control.db"


class ControlStore:
    """Thread-safe SQLite access for users + invites."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        with _db_lock:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with _db_lock:
            self._conn.close()

    def _user_from_row(self, row: sqlite3.Row | None) -> TenantUser | None:
        if row is None:
            return None
        role: UserRole = "platform_admin" if row["role"] == "platform_admin" else "user"
        return TenantUser(
            id=row["id"],
            email=row["email"],
            google_sub=row["google_sub"],
            name=row["name"],
            picture=row["picture"],
            role=role,
            spreadsheet_id=row["spreadsheet_id"],
            disabled_at=row["disabled_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _invite_from_row(self, row: sqlite3.Row | None) -> Invite | None:
        if row is None:
            return None
        return Invite(
            id=row["id"],
            email=row["email"],
            invited_by=row["invited_by"],
            token_hash=row["token_hash"],
            expires_at=row["expires_at"],
            accepted_at=row["accepted_at"],
            created_at=row["created_at"],
        )

    def get_user_by_id(self, user_id: str) -> TenantUser | None:
        with _db_lock:
            cur = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            return self._user_from_row(cur.fetchone())

    def get_user_by_email(self, email: str) -> TenantUser | None:
        em = normalize_email(email)
        if not em:
            return None
        with _db_lock:
            cur = self._conn.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
                (em,),
            )
            return self._user_from_row(cur.fetchone())

    def list_users(self) -> list[TenantUser]:
        with _db_lock:
            cur = self._conn.execute("SELECT * FROM users ORDER BY created_at ASC")
            return [u for r in cur.fetchall() if (u := self._user_from_row(r))]

    def upsert_user_from_oauth(
        self,
        *,
        email: str,
        google_sub: str | None,
        name: str | None,
        picture: str | None,
        role: UserRole | None = None,
    ) -> TenantUser:
        em = normalize_email(email)
        if not em:
            raise ValueError("email required")
        now = _utc_now_iso()
        existing = self.get_user_by_email(em)
        if existing:
            new_role = role or existing.role
            with _db_lock:
                self._conn.execute(
                    """
                    UPDATE users
                    SET google_sub = COALESCE(?, google_sub),
                        name = COALESCE(?, name),
                        picture = COALESCE(?, picture),
                        role = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (google_sub, name, picture, new_role, now, existing.id),
                )
            user = self.get_user_by_id(existing.id)
            assert user is not None
            return user

        uid = str(uuid4())
        use_role: UserRole = role or "user"
        with _db_lock:
            self._conn.execute(
                """
                INSERT INTO users (
                    id, email, google_sub, name, picture, role,
                    spreadsheet_id, disabled_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (uid, em, google_sub, name, picture, use_role, now, now),
            )
        user = self.get_user_by_id(uid)
        assert user is not None
        return user

    def set_spreadsheet_id(self, user_id: str, spreadsheet_id: str) -> TenantUser:
        now = _utc_now_iso()
        with _db_lock:
            self._conn.execute(
                """
                UPDATE users SET spreadsheet_id = ?, updated_at = ? WHERE id = ?
                """,
                (spreadsheet_id.strip(), now, user_id),
            )
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError(f"user not found: {user_id}")
        return user

    def set_role(self, user_id: str, role: UserRole) -> TenantUser:
        now = _utc_now_iso()
        with _db_lock:
            self._conn.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                (role, now, user_id),
            )
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError(f"user not found: {user_id}")
        return user

    def create_invite(
        self,
        email: str,
        *,
        invited_by: str | None = None,
        expires_at: str | None = None,
    ) -> Invite:
        em = normalize_email(email)
        if not em:
            raise ValueError("email required")
        # One pending invite per email
        with _db_lock:
            self._conn.execute(
                "DELETE FROM invites WHERE email = ? COLLATE NOCASE AND accepted_at IS NULL",
                (em,),
            )
        inv_id = str(uuid4())
        now = _utc_now_iso()
        token = secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with _db_lock:
            self._conn.execute(
                """
                INSERT INTO invites (
                    id, email, invited_by, token_hash, expires_at, accepted_at, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (inv_id, em, invited_by, token_hash, expires_at, now),
            )
        inv = self.get_invite_by_id(inv_id)
        assert inv is not None
        # Attach raw token only for response layer via attribute (not persisted)
        inv_public = Invite(
            id=inv.id,
            email=inv.email,
            invited_by=inv.invited_by,
            token_hash=token,  # temporary: raw token for admin API one-shot display
            expires_at=inv.expires_at,
            accepted_at=inv.accepted_at,
            created_at=inv.created_at,
        )
        return inv_public

    def get_invite_by_id(self, invite_id: str) -> Invite | None:
        with _db_lock:
            cur = self._conn.execute("SELECT * FROM invites WHERE id = ?", (invite_id,))
            return self._invite_from_row(cur.fetchone())

    def list_invites(self, *, pending_only: bool = False) -> list[Invite]:
        with _db_lock:
            if pending_only:
                cur = self._conn.execute(
                    "SELECT * FROM invites WHERE accepted_at IS NULL ORDER BY created_at DESC"
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM invites ORDER BY created_at DESC"
                )
            return [i for r in cur.fetchall() if (i := self._invite_from_row(r))]

    def get_pending_invite_for_email(self, email: str) -> Invite | None:
        em = normalize_email(email)
        with _db_lock:
            cur = self._conn.execute(
                """
                SELECT * FROM invites
                WHERE email = ? COLLATE NOCASE AND accepted_at IS NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (em,),
            )
            return self._invite_from_row(cur.fetchone())

    def accept_invite_for_email(self, email: str) -> Invite | None:
        inv = self.get_pending_invite_for_email(email)
        if inv is None:
            return None
        now = _utc_now_iso()
        with _db_lock:
            self._conn.execute(
                "UPDATE invites SET accepted_at = ? WHERE id = ?",
                (now, inv.id),
            )
        return self.get_invite_by_id(inv.id)

    def delete_invite(self, invite_id: str) -> bool:
        with _db_lock:
            cur = self._conn.execute("DELETE FROM invites WHERE id = ?", (invite_id,))
            return cur.rowcount > 0

    def is_email_allowed(self, email: str) -> bool:
        """Existing user (not disabled) or pending invite."""
        user = self.get_user_by_email(email)
        if user is not None and not user.disabled_at:
            return True
        return self.get_pending_invite_for_email(email) is not None

    def ensure_platform_admins(self, admin_emails: list[str]) -> None:
        """Promote configured platform admin emails (create stub users if needed)."""
        for raw in admin_emails:
            em = normalize_email(raw)
            if not em:
                continue
            user = self.get_user_by_email(em)
            if user is None:
                self.upsert_user_from_oauth(
                    email=em,
                    google_sub=None,
                    name=None,
                    picture=None,
                    role="platform_admin",
                )
            elif user.role != "platform_admin":
                self.set_role(user.id, "platform_admin")


def get_control_store(settings: Settings | None = None) -> ControlStore:
    """Process singleton store; re-opens if path changes."""
    global _STORE, _STORE_PATH
    settings = settings or get_settings()
    path = str(default_control_db_path(settings).resolve())
    created: ControlStore | None = None
    with _singleton_lock:
        if _STORE is not None and _STORE_PATH == path:
            return _STORE
        if _STORE is not None:
            try:
                _STORE.close()
            except Exception:  # noqa: BLE001
                pass
            _STORE = None
            _STORE_PATH = None
        # Construct outside nested db work held by singleton only (ControlStore uses _db_lock)
        created = ControlStore(Path(path))
        _STORE = created
        _STORE_PATH = path

    admins = [
        e.strip()
        for e in (settings.platform_admin_emails or "").split(",")
        if e.strip()
    ]
    if admins and created is not None:
        created.ensure_platform_admins(admins)
    assert _STORE is not None
    return _STORE


def reset_control_store_for_tests() -> None:
    """Close and drop singleton (tests only)."""
    global _STORE, _STORE_PATH
    with _singleton_lock:
        if _STORE is not None:
            try:
                _STORE.close()
            except Exception:  # noqa: BLE001
                pass
        _STORE = None
        _STORE_PATH = None


def control_user_to_dict(user: TenantUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "role": user.role,
        "spreadsheet_id": user.spreadsheet_id,
        "disabled_at": user.disabled_at,
        "created_at": user.created_at,
        "tenant_ready": bool(user.spreadsheet_id),
    }
