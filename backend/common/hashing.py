"""Content hashing for idempotent statement imports."""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes) -> str:
    """Return lowercase hex SHA-256 of raw file bytes."""
    return hashlib.sha256(data).hexdigest()
