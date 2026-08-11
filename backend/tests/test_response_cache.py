"""Unit tests for in-process response_cache get/set/invalidate."""

from __future__ import annotations

import time

from backend.services import response_cache as rc


def setup_function() -> None:
    rc.cache_invalidate()


def teardown_function() -> None:
    rc.cache_invalidate()


def test_cache_set_get_and_miss():
    assert rc.cache_get("k1") is None
    rc.cache_set("k1", {"a": 1}, ttl_seconds=60)
    assert rc.cache_get("k1") == {"a": 1}
    assert rc.cache_get("missing") is None


def test_cache_invalidate_all_and_prefix():
    rc.cache_set("dash:m1", 1, ttl_seconds=60)
    rc.cache_set("dash:m2", 2, ttl_seconds=60)
    rc.cache_set("alerts:x", 3, ttl_seconds=60)

    rc.cache_invalidate(prefix="dash:")
    assert rc.cache_get("dash:m1") is None
    assert rc.cache_get("dash:m2") is None
    assert rc.cache_get("alerts:x") == 3

    rc.cache_invalidate()
    assert rc.cache_get("alerts:x") is None


def test_cache_ttl_expiry():
    rc.cache_set("ttl", "v", ttl_seconds=0.05)
    assert rc.cache_get("ttl") == "v"
    time.sleep(0.08)
    assert rc.cache_get("ttl") is None


def test_cached_factory_runs_once():
    calls = {"n": 0}

    def factory() -> str:
        calls["n"] += 1
        return "built"

    assert rc.cached("once", 60, factory) == "built"
    assert rc.cached("once", 60, factory) == "built"
    assert calls["n"] == 1


def test_cached_single_flight_concurrent():
    """Concurrent misses for the same key share one factory run."""
    import threading

    calls = {"n": 0}
    gate = threading.Barrier(8)
    release = threading.Event()

    def factory() -> str:
        calls["n"] += 1
        release.wait(timeout=5)
        return "shared"

    results: list[str] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def worker() -> None:
        try:
            gate.wait(timeout=5)
            value = rc.cached("sf", 60, factory)
            with results_lock:
                results.append(value)
        except BaseException as exc:  # noqa: BLE001
            with results_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    # Leader holds factory on release; give followers time to attach.
    time.sleep(0.15)
    release.set()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    assert results == ["shared"] * 8
    assert calls["n"] == 1
