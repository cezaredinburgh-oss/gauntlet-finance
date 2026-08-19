"""Date/time parsing for Czech and multi-institution statement formats."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser

_CZECH_DATE = re.compile(
    r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$"
)

# Revolut CSV clocks are wall time without a zone; Gauntlet defaults to Prague
# (matches seed Settings.timezone and Raiffeisen CZ usage).
DEFAULT_STATEMENT_TIMEZONE = "Europe/Prague"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=32)
def resolve_zone(name: str | None = None) -> ZoneInfo:
    """Resolve an IANA zone; fall back to Europe/Prague on unknown names."""
    raw = (name or DEFAULT_STATEMENT_TIMEZONE).strip() or DEFAULT_STATEMENT_TIMEZONE
    try:
        return ZoneInfo(raw)
    except Exception:  # noqa: BLE001
        return ZoneInfo(DEFAULT_STATEMENT_TIMEZONE)


def local_midnight(now: datetime, zone: ZoneInfo | str | None = None) -> datetime:
    """Timezone-aware local midnight of ``now`` in ``zone`` (default Prague)."""
    tz = zone if isinstance(zone, ZoneInfo) else resolve_zone(
        zone if isinstance(zone, str) else None
    )
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def resolve_day_timezone(repo: Any) -> str:
    """Sheets ``Settings.timezone``, else env ``statement_timezone``."""
    try:
        rows = repo.list_rows("Settings")
    except Exception:  # noqa: BLE001
        rows = []
    for row in rows:
        key = getattr(row, "key", None)
        if key is None and isinstance(row, dict):
            key = row.get("key")
        if str(key or "").strip() != "timezone":
            continue
        value = getattr(row, "value", None)
        if value is None and isinstance(row, dict):
            value = row.get("value")
        raw = str(value or "").strip()
        if raw:
            return resolve_zone(raw).key
    from backend.config import get_settings

    return resolve_zone(get_settings().statement_timezone).key


def parse_czech_date(raw: str) -> date:
    """Parse ``dd.mm.yyyy`` or ``dd.mm.yyyy HH:MM[:SS]`` into a date."""
    m = _CZECH_DATE.match(raw or "")
    if not m:
        raise ValueError(f"not a Czech date: {raw!r}")
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(year, month, day)


def parse_czech_datetime(
    raw: str,
    *,
    default_tz: str | ZoneInfo | None = None,
) -> datetime:
    """Parse Czech date/time; missing time → midnight in statement timezone."""
    m = _CZECH_DATE.match(raw or "")
    if not m:
        raise ValueError(f"not a Czech datetime: {raw!r}")
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    tz = default_tz if isinstance(default_tz, ZoneInfo) else resolve_zone(
        default_tz if isinstance(default_tz, str) else None
    )
    return datetime(year, month, day, hour, minute, second, tzinfo=tz).astimezone(
        timezone.utc
    )


def parse_flexible_datetime(
    raw: str,
    *,
    default_tz: str | ZoneInfo | None = None,
) -> datetime:
    """
    Parse ISO, Revolut US dates, and Czech formats → UTC.

    Naive clocks (Revolut CSV has no zone) are interpreted in ``default_tz``
    (default ``Europe/Prague``). Explicit offsets / ``Z`` are absolute.
    """
    if raw is None or not str(raw).strip():
        raise ValueError("empty datetime")
    s = str(raw).strip()
    s = s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    # Normalize odd question-mark replacements sometimes seen in exports
    s = s.replace("?PM", " PM").replace("?AM", " AM")

    if _CZECH_DATE.match(s):
        return parse_czech_datetime(s, default_tz=default_tz)

    # ISO with Z
    if s.endswith("Z") and "T" in s:
        return datetime.fromisoformat(s[:-1] + "+00:00").astimezone(timezone.utc)

    dt = date_parser.parse(s)
    if dt.tzinfo is None:
        tz = default_tz if isinstance(default_tz, ZoneInfo) else resolve_zone(
            default_tz if isinstance(default_tz, str) else None
        )
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def parse_flexible_date(
    raw: str,
    *,
    default_tz: str | ZoneInfo | None = None,
) -> date:
    return parse_flexible_datetime(raw, default_tz=default_tz).date()


def reinterpret_naive_utc_wall_as_zone(
    dt: datetime,
    *,
    zone: str | ZoneInfo | None = None,
) -> datetime:
    """
    One-shot migration helper: values that were stored by tagging a wall clock
    as UTC are re-read as wall clock in ``zone`` and converted to true UTC.

    Example (summer): 11:45+00:00 (wrong) → wall 11:45 Europe/Prague → 09:45+00:00.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    wall = dt.replace(tzinfo=None)
    tz = zone if isinstance(zone, ZoneInfo) else resolve_zone(
        zone if isinstance(zone, str) else None
    )
    return wall.replace(tzinfo=tz).astimezone(timezone.utc)
