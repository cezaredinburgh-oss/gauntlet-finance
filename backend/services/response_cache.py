"""Tiny in-process TTL cache for expensive read endpoints.

``cached()`` single-flights concurrent misses for the same key so only one
factory runs; waiters share the result (or re-raise the same exception).

Multi-tenant: keys and invalidation are automatically scoped with
``t:{tenant_id}:`` when :func:`backend.tenancy.context.get_tenant_id` is set.
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


def _scoped_key(key: str) -> str:
    try:
        from backend.tenancy.context import get_tenant_id

        tid = get_tenant_id()
    except Exception:  # noqa: BLE001
        tid = None
    if tid:
        return f"t:{tid}:{key}"
    return key


def cache_get(key: str) -> Any | None:
    sk = _scoped_key(key)
    with _lock:
        item = _store.get(sk)
        if item is None:
            return None
        expires, value = item
        if time.monotonic() > expires:
            _store.pop(sk, None)
            return None
        return value


def cache_set(key: str, value: Any, ttl_seconds: float) -> None:
    sk = _scoped_key(key)
    with _lock:
        _store[sk] = (time.monotonic() + ttl_seconds, value)


def cache_invalidate(prefix: str | None = None) -> None:
    """
    Invalidate cache entries.

    When a tenant is in context, only that tenant's keys are cleared
    (optionally filtered by logical prefix). Without tenant context,
    behaviour matches the global single-tenant store.
    """
    try:
        from backend.tenancy.context import get_tenant_id

        tid = get_tenant_id()
    except Exception:  # noqa: BLE001
        tid = None

    with _lock:
        if tid:
            tenant_prefix = f"t:{tid}:"
            if prefix is None:
                for k in list(_store):
                    if k.startswith(tenant_prefix):
                        _store.pop(k, None)
                return
            full = tenant_prefix + prefix
            for k in list(_store):
                if k.startswith(full):
                    _store.pop(k, None)
            return

        if prefix is None:
            _store.clear()
            return
        for k in list(_store):
            if k.startswith(prefix):
                _store.pop(k, None)


def cached(key: str, ttl_seconds: float, factory: Callable[[], T]) -> T:
    """Return cached value or run factory once per key (single-flight)."""
    sk = _scoped_key(key)
    hit = cache_get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]

    # Register as leader or wait on existing in-flight for this key.
    with _lock:
        hit = _store.get(sk)
        if hit is not None:
            expires, value = hit
            if time.monotonic() <= expires:
                return value  # type: ignore[return-value]
            _store.pop(sk, None)

        entry = _inflight.get(sk)
        if entry is None:
            cond = Condition(_lock)
            box: dict[str, Any] = {"done": False}
            _inflight[sk] = (cond, box)
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
            _inflight.pop(sk, None)
            cond.notify_all()
        raise

    with _lock:
        _store[sk] = (time.monotonic() + ttl_seconds, value)
        box["value"] = value
        box["done"] = True
        _inflight.pop(sk, None)
        cond.notify_all()
    return value
