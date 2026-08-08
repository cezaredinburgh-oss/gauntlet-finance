"""Date/time parsing for Czech and multi-institution statement formats."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from dateutil import parser as date_parser

_CZECH_DATE = re.compile(
    r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_czech_date(raw: str) -> date:
    """Parse ``dd.mm.yyyy`` or ``dd.mm.yyyy HH:MM[:SS]`` into a date."""
    m = _CZECH_DATE.match(raw or "")
    if not m:
        raise ValueError(f"not a Czech date: {raw!r}")
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(year, month, day)


def parse_czech_datetime(raw: str) -> datetime:
    """Parse Czech date/time; missing time → midnight UTC."""
    m = _CZECH_DATE.match(raw or "")
    if not m:
        raise ValueError(f"not a Czech datetime: {raw!r}")
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def parse_flexible_datetime(raw: str) -> datetime:
    """
    Parse ISO, Revolut crypto US dates, and Czech formats.

    Revolut crypto uses narrow no-break spaces before AM/PM (``\\u202f``).
    """
    if raw is None or not str(raw).strip():
        raise ValueError("empty datetime")
    s = str(raw).strip()
    s = s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    # Normalize odd question-mark replacements sometimes seen in exports
    s = s.replace("?PM", " PM").replace("?AM", " AM")

    if _CZECH_DATE.match(s):
        return parse_czech_datetime(s)

    # ISO with Z
    if s.endswith("Z") and "T" in s:
        return datetime.fromisoformat(s[:-1] + "+00:00")

    dt = date_parser.parse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_flexible_date(raw: str) -> date:
    return parse_flexible_datetime(raw).date()
