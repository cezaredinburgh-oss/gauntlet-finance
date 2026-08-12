"""
In-process daily token quotas for platform Grok usage.

Not durable across restarts (acceptable for testing). Multi-process deploys
should replace with Redis/control-DB later.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone

_lock = threading.Lock()
# day_iso -> principal -> tokens used
_usage: dict[str, dict[str, int]] = {}
_global: dict[str, int] = {}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _prune(day: str) -> None:
    stale = [k for k in _usage if k != day]
    for k in stale:
        del _usage[k]
    stale_g = [k for k in _global if k != day]
    for k in stale_g:
        del _global[k]


@dataclass(frozen=True)
class QuotaSnapshot:
    principal: str
    day: str
    used: int
    cap: int
    global_used: int
    global_cap: int

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    @property
    def global_remaining(self) -> int:
        return max(0, self.global_cap - self.global_used)


def snapshot(principal: str, *, cap: int, global_cap: int) -> QuotaSnapshot:
    day = _today()
    with _lock:
        _prune(day)
        used = _usage.get(day, {}).get(principal, 0)
        g_used = _global.get(day, 0)
    return QuotaSnapshot(
        principal=principal,
        day=day,
        used=used,
        cap=cap,
        global_used=g_used,
        global_cap=global_cap,
    )


def check_and_reserve(
    principal: str,
    estimate: int,
    *,
    cap: int,
    global_cap: int,
) -> QuotaSnapshot:
    """
    Reserve ``estimate`` tokens for this call.

    Raises ValueError with a safe UI message if over cap.
    """
    if estimate < 0:
        estimate = 0
    day = _today()
    with _lock:
        _prune(day)
        bucket = _usage.setdefault(day, {})
        used = bucket.get(principal, 0)
        g_used = _global.get(day, 0)
        if used + estimate > cap:
            raise ValueError(
                f"Daily AI token limit reached ({used}/{cap}). Try again tomorrow "
                "or raise AI_DAILY_TOKEN_CAP."
            )
        if g_used + estimate > global_cap:
            raise ValueError(
                "Platform AI daily limit reached. Try again tomorrow or raise "
                "AI_GLOBAL_DAILY_TOKEN_CAP."
            )
        bucket[principal] = used + estimate
        _global[day] = g_used + estimate
        return QuotaSnapshot(
            principal=principal,
            day=day,
            used=bucket[principal],
            cap=cap,
            global_used=_global[day],
            global_cap=global_cap,
        )


def settle(principal: str, reserved: int, actual: int) -> None:
    """Adjust reservation to actual usage (can free unused estimate)."""
    delta = actual - reserved
    if delta == 0:
        return
    day = _today()
    with _lock:
        _prune(day)
        bucket = _usage.setdefault(day, {})
        used = bucket.get(principal, 0)
        bucket[principal] = max(0, used + delta)
        g_used = _global.get(day, 0)
        _global[day] = max(0, g_used + delta)


def reset_for_tests() -> None:
    """Clear all usage (pytest only)."""
    with _lock:
        _usage.clear()
        _global.clear()


def principal_key(user_id: str | None, email: str | None) -> str:
    uid = (user_id or "").strip()
    if uid:
        return f"u:{uid}"
    em = (email or "").strip().lower()
    if em:
        return f"e:{em}"
    return "anonymous"
