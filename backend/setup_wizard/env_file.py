"""Safe .env read/update helpers for the setup wizard."""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    return _PROJECT_ROOT


def env_path() -> Path:
    return _PROJECT_ROOT / ".env"


def secrets_dir() -> Path:
    d = _PROJECT_ROOT / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_credentials_path() -> Path:
    return secrets_dir() / "service-account.json"


def extract_spreadsheet_id(raw: str) -> str:
    s = (raw or "").strip()
    if "/d/" in s:
        try:
            s = s.split("/d/")[1].split("/")[0]
        except IndexError:
            pass
    # strip query fragments
    s = s.split("?")[0].split("#")[0].strip()
    return s


def upsert_env_vars(updates: dict[str, str], *, path: Path | None = None) -> Path:
    """
    Create or update keys in .env without removing unrelated lines/comments.

    Returns path written.
    """
    path = path or env_path()
    existing: list[str] = []
    if path.is_file():
        existing = path.read_text(encoding="utf-8").splitlines()

    keys_written: set[str] = set()
    out: list[str] = []
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                keys_written.add(key)
                continue
        out.append(line)

    if keys_written != set(updates):
        if out and out[-1].strip():
            out.append("")
        out.append("# --- updated by setup wizard ---")
        for key, value in updates.items():
            if key not in keys_written:
                out.append(f"{key}={value}")
                keys_written.add(key)

    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path
