"""Unit tests for dashboard period helpers."""

from datetime import date

from backend.services.periods import prior_range, resolve_range


def test_this_month_and_prior():
    today = date(2026, 8, 15)
    f, t = resolve_range("this_month", today=today)
    assert f == date(2026, 8, 1)
    assert t == today
    p = prior_range("this_month", f, t, today=today)
    assert p == (date(2026, 7, 1), date(2026, 7, 31))


def test_last_30d_prior_equal_length():
    today = date(2026, 8, 15)
    f, t = resolve_range("last_30d", today=today)
    assert (t - f).days == 29
    p = prior_range("last_30d", f, t, today=today)
    assert p is not None
    pf, pt = p
    assert (pt - pf).days == 29
    assert pt == f - __import__("datetime").timedelta(days=1)


def test_all_time_no_prior():
    f, t = resolve_range("all_time", today=date(2026, 8, 5))
    assert f is None
    assert prior_range("all_time", f, t) is None


def test_last_year():
    f, t = resolve_range("last_year", today=date(2026, 8, 5))
    assert f == date(2025, 1, 1)
    assert t == date(2025, 12, 31)


def test_calendar_month_prior():
    today = date(2026, 8, 15)
    # Selected July 2026 via calendar_month stepper
    f, t = date(2026, 7, 1), date(2026, 7, 31)
    p = prior_range("calendar_month", f, t, today=today)
    assert p == (date(2026, 6, 1), date(2026, 6, 30))


def test_calendar_month_prior_january():
    f, t = date(2026, 1, 1), date(2026, 1, 31)
    p = prior_range("calendar_month", f, t, today=date(2026, 1, 20))
    assert p == (date(2025, 12, 1), date(2025, 12, 31))
