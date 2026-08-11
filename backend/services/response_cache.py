"""Tiny in-process TTL cache for expensive read endpoints.

``cached()`` single-flights concurrent misses for the same key so only one
factory runs; waiters share the result (or re-raise the same exception).
"""

from __future__ import annotations

import time
from threading import Condition, Lock
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_lock = Lock()
_store: dict[str, tuple[float, Any]] = {}
# Per-key in-flight: Condition (under global lock for map only) + result box.
_inflight: dict[str, tuple[Condition, dict[str, Any]]] = {}


def cache_get(key: str) -> Any | None:
    with _lock:
        item = _store.get(key)
        if item is None:
            return None
        expires, value = item
        if time.monotonic() > expires:
            _store.pop(key, None)
            return None
        return value


def cache_set(key: str, value: Any, ttl_seconds: float) -> None:
    with _lock:
        _store[key] = (time.monotonic() + ttl_seconds, value)


def cache_invalidate(prefix: str | None = None) -> None:
    with _lock:
        if prefix is None:
            _store.clear()
            return
        for k in list(_store):
            if k.startswith(prefix):
                _store.pop(k, None)


def cached(key: str, ttl_seconds: float, factory: Callable[[], T]) -> T:
    """Return cached value or run factory once per key (single-flight)."""
    hit = cache_get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]

    # Register as leader or wait on existing in-flight for this key.
    with _lock:
        hit = _store.get(key)
        if hit is not None:
            expires, value = hit
            if time.monotonic() <= expires:
                return value  # type: ignore[return-value]
            _store.pop(key, None)

        entry = _inflight.get(key)
        if entry is None:
            cond = Condition(_lock)
            box: dict[str, Any] = {"done": False}
            _inflight[key] = (cond, box)
            is_leader = True
        else:
            cond, box = entry
            is_leader = False

        if not is_leader:
            while not box["done"]:
                cond.wait()
            if "error" in box:
                raise box["error"]
            return box["value"]  # type: ignore[return-value]

    # Leader: run factory outside the global lock (avoid deadlock / long holds).
    try:
        value = factory()
    except Exception as exc:
        with _lock:
            box["error"] = exc
            box["done"] = True
            _inflight.pop(key, None)
            cond.notify_all()
        raise

    with _lock:
        _store[key] = (time.monotonic() + ttl_seconds, value)
        box["value"] = value
        box["done"] = True
        _inflight.pop(key, None)
        cond.notify_all()
    return value
