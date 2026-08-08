"""Date range helpers for dashboard timeframes and prior-period comparison."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

PeriodKey = Literal[
    "this_month",
    "last_month",
    "last_30d",
    "last_6m",
    "this_year",
    "last_year",
    "all_time",
    "custom",
    "calendar_month",
]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def resolve_range(
    key: PeriodKey,
    *,
    today: date | None = None,
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> tuple[date | None, date | None]:
    """
    Return inclusive (date_from, date_to).

    all_time → (None, today).
    """
    today = today or date.today()
    if key == "this_month":
        start, _ = _month_bounds(today.year, today.month)
        return start, today
    if key == "last_month":
        y, m = today.year, today.month
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
        return _month_bounds(y, m)
    if key == "last_30d":
        return today - timedelta(days=29), today
    if key == "last_6m":
        return today - timedelta(days=179), today
    if key == "this_year":
        return date(today.year, 1, 1), today
    if key == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if key == "all_time":
        return None, today
    # custom
    if custom_from is None or custom_to is None:
        start, _ = _month_bounds(today.year, today.month)
        return start, today
    return custom_from, custom_to


def prior_range(
    key: PeriodKey,
    date_from: date | None,
    date_to: date | None,
    *,
    today: date | None = None,
) -> tuple[date | None, date | None] | None:
    """
    Prior comparison window for a selected range.

    Returns None when comparison is not defined (all_time or missing bounds).
    """
    today = today or date.today()
    if key == "all_time":
        return None
    if key == "this_month":
        y, m = today.year, today.month
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
        return _month_bounds(y, m)
    if key == "calendar_month":
        # Prior is the calendar month immediately before the selected window.
        if date_from is None:
            return None
        y, m = date_from.year, date_from.month
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
        return _month_bounds(y, m)
    if key == "last_month":
        # month before last month
        start, _ = resolve_range("last_month", today=today)
        assert start is not None
        y, m = start.year, start.month
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
        return _month_bounds(y, m)
    if key == "this_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if key == "last_year":
        return date(today.year - 2, 1, 1), date(today.year - 2, 12, 31)
    if key in ("last_30d", "last_6m", "custom") or date_from is not None:
        if date_from is None or date_to is None:
            return None
        days = (date_to - date_from).days + 1
        prior_to = date_from - timedelta(days=1)
        prior_from = prior_to - timedelta(days=days - 1)
        return prior_from, prior_to
    return None


def pct_change(current: float, prior: float) -> float | None:
    if prior == 0:
        return None if current == 0 else 100.0 if current > 0 else -100.0
    return (current / prior - 1.0) * 100.0
