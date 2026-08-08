"""Persist uploaded statement bytes for ERROR retry without re-selecting the file."""

from __future__ import annotations

import os
from pathlib import Path

from backend.config import get_settings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def uploads_dir() -> Path:
    raw = (os.environ.get("UPLOAD_STORE_DIR") or "").strip()
    if raw:
        p = Path(raw)
    else:
        # Prefer /data on Railway volume when present
        data = Path("/data/uploads")
        if data.parent.is_dir() and os.access(data.parent, os.W_OK):
            p = data
        else:
            p = _PROJECT_ROOT / "data" / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def store_upload(content_sha256: str, file_bytes: bytes) -> Path:
    path = uploads_dir() / f"{content_sha256.lower()}.bin"
    path.write_bytes(file_bytes)
    return path


def load_upload(content_sha256: str) -> bytes | None:
    path = uploads_dir() / f"{content_sha256.lower()}.bin"
    if not path.is_file():
        return None
    return path.read_bytes()


def has_upload(content_sha256: str) -> bool:
    return (uploads_dir() / f"{content_sha256.lower()}.bin").is_file()
