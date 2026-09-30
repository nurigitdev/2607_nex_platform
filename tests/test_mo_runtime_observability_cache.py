from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread

import pytest

from nex_mo.runtime_observability import build_mock_model_runtime_snapshot
from nex_mo.runtime_observability_cache import (
    InMemoryRuntimeObservationStore,
    RuntimeObservationCacheLookup,
    with_runtime_cache_status,
)


NOW = datetime(2026, 9, 30, tzinfo=UTC)


def snapshot(*, observed_at: str = "2026-09-30T00:00:00Z"):
    return build_mock_model_runtime_snapshot(observed_at=observed_at, ttl_seconds=30)


def test_store_read_save_clear_and_expiry() -> None:
    store = InMemoryRuntimeObservationStore()
    assert store.read(now=NOW).status == "MISS"
    store.save(snapshot())
    assert store.read(now=NOW).status == "FRESH"
    expired = store.read(now=NOW + timedelta(seconds=30))
    assert expired.status == "STALE"
    assert expired.snapshot is not None
    assert expired.snapshot.runtime_status == "UNKNOWN"
    assert store.read(now=NOW + timedelta(seconds=31)).status == "STALE"
    store.clear()
    assert store.read(now=NOW).status == "MISS"


def test_resolve_reuses_refreshes_and_falls_back_to_stale() -> None:
    store = InMemoryRuntimeObservationStore()
    calls = 0

    def refresh():
        nonlocal calls
        calls += 1
        return snapshot()

    first = store.resolve(refresh, now=NOW)
    cached = store.resolve(refresh, now=NOW)
    forced = store.resolve(refresh, now=NOW, force_refresh=True)
    stale = store.resolve(
        lambda: (_ for _ in ()).throw(RuntimeError("failed")),
        now=NOW + timedelta(seconds=31),
    )

    assert first.cache_status == "FRESH"
    assert cached is first
    assert forced.cache_status == "REFRESHED"
    assert stale.cache_status == "STALE"
    assert stale.failure_code == "runtime_observation_stale"
    assert calls == 2


def test_resolve_raises_initial_refresh_failure() -> None:
    store = InMemoryRuntimeObservationStore()
    with pytest.raises(RuntimeError, match="failed"):
        store.resolve(
            lambda: (_ for _ in ()).throw(RuntimeError("failed")), now=NOW
        )


def test_store_single_flight_refreshes_once() -> None:
    store = InMemoryRuntimeObservationStore()
    barrier = Barrier(4)
    calls = 0
    results = []

    def refresh():
        nonlocal calls
        calls += 1
        return snapshot()

    def worker() -> None:
        barrier.wait()
        results.append(store.resolve(refresh, now=NOW))

    threads = [Thread(target=worker) for unused in range(3)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert calls == 1
    assert len(results) == 3


def test_cache_contract_rejects_invalid_state_and_time() -> None:
    with pytest.raises(ValueError, match="lookup status"):
        RuntimeObservationCacheLookup("OTHER", None)
    with pytest.raises(ValueError, match="miss"):
        RuntimeObservationCacheLookup("MISS", snapshot())
    with pytest.raises(ValueError, match="cache status"):
        with_runtime_cache_status(snapshot(), "OTHER")
    with pytest.raises(ValueError, match="timezone"):
        InMemoryRuntimeObservationStore().read(now=datetime(2026, 9, 30))
