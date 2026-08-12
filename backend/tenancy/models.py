"""Control-plane dataclasses (not finance ledger rows)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

UserRole = Literal["user", "platform_admin"]


@dataclass
class TenantUser:
    id: str
    email: str
    google_sub: str | None
    name: str | None
    picture: str | None
    role: UserRole
    spreadsheet_id: str | None
    disabled_at: str | None
    created_at: str
    updated_at: str


@dataclass
class Invite:
    id: str
    email: str
    invited_by: str | None
    token_hash: str | None
    expires_at: str | None
    accepted_at: str | None
    created_at: str
