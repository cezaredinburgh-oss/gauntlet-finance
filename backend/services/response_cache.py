"""Tiny in-process TTL cache for expensive read endpoints."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_lock = Lock()
_store: dict[str, tuple[float, Any]] = {}


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
    hit = cache_get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    value = factory()
    cache_set(key, value, ttl_seconds)
    return value
