from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
import time

import pytest

from nex_mo.provider_readiness import build_mock_provider_readiness_snapshot
from nex_mo.provider_readiness_cache import (
    InMemoryProviderReadinessStore,
    ProviderReadinessCacheLookup,
    with_cache_status,
)
import run_mo_provider_readiness_cache as runner


NOW = datetime(2026, 9, 30, tzinfo=UTC)


def snapshot(*, checked_at: datetime = NOW):
    return build_mock_provider_readiness_snapshot(
        checked_at=checked_at.isoformat().replace("+00:00", "Z")
    )


def test_store_miss_save_read_and_clear() -> None:
    store = InMemoryProviderReadinessStore()
    assert store.read(now=NOW).status == "MISS"

    expected = snapshot()
    store.save(expected)
    lookup = store.read(now=NOW + timedelta(seconds=1))
    assert lookup.status == "FRESH"
    assert lookup.snapshot is expected

    store.clear()
    assert store.read(now=NOW).snapshot is None


def test_resolve_uses_fresh_cache_and_supports_forced_refresh() -> None:
    store = InMemoryProviderReadinessStore()
    calls = 0

    def refresh():
        nonlocal calls
        calls += 1
        return snapshot(checked_at=NOW + timedelta(seconds=calls))

    first = store.resolve(refresh, now=NOW)
    hit = store.resolve(refresh, now=NOW + timedelta(seconds=2))
    forced = store.resolve(
        refresh,
        now=NOW + timedelta(seconds=3),
        force_refresh=True,
    )

    assert first.cache_status == "FRESH"
    assert hit is first
    assert forced.cache_status == "REFRESHED"
    assert calls == 2


def test_expired_snapshot_refreshes_automatically() -> None:
    store = InMemoryProviderReadinessStore()
    store.save(snapshot())

    refreshed = store.resolve(
        lambda: snapshot(checked_at=NOW + timedelta(seconds=31)),
        now=NOW + timedelta(seconds=30),
    )

    assert refreshed.cache_status == "REFRESHED"
    assert refreshed.checked_at == "2026-09-30T00:00:31Z"


def test_refresh_failure_returns_stale_snapshot_and_never_ready() -> None:
    store = InMemoryProviderReadinessStore()
    store.save(snapshot())

    def fail():
        raise RuntimeError("secret provider detail")

    stale = store.resolve(fail, now=NOW, force_refresh=True)
    lookup = store.read(now=NOW)

    assert stale.cache_status == "STALE"
    assert stale.readiness_status == "NOT_READY"
    assert stale.failure_code == "provider_readiness_snapshot_stale"
    assert lookup.status == "STALE"
    assert lookup.snapshot is stale


def test_initial_refresh_failure_is_not_hidden() -> None:
    store = InMemoryProviderReadinessStore()

    with pytest.raises(RuntimeError, match="initial failure"):
        store.resolve(
            lambda: (_ for _ in ()).throw(RuntimeError("initial failure")),
            now=NOW,
        )


def test_concurrent_cache_miss_uses_single_flight_refresh() -> None:
    store = InMemoryProviderReadinessStore()
    start = Barrier(5)
    counter_lock = Lock()
    calls = 0

    def refresh():
        nonlocal calls
        with counter_lock:
            calls += 1
        time.sleep(0.02)
        return snapshot()

    def resolve():
        start.wait()
        return store.resolve(refresh, now=NOW)

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: resolve(), range(5)))

    assert calls == 1
    assert all(item is results[0] for item in results)


def test_cache_validates_status_and_timezone() -> None:
    with pytest.raises(ValueError, match="lookup status"):
        ProviderReadinessCacheLookup("OTHER", None)
    with pytest.raises(ValueError, match="cache miss"):
        ProviderReadinessCacheLookup("MISS", snapshot())
    with pytest.raises(ValueError, match="cache miss"):
        ProviderReadinessCacheLookup("FRESH", None)
    with pytest.raises(ValueError, match="cache status"):
        with_cache_status(snapshot(), "OTHER")
    with pytest.raises(ValueError, match="timezone"):
        InMemoryProviderReadinessStore().read(now=datetime(2026, 9, 30))


def test_cache_uses_current_utc_time_when_not_injected() -> None:
    store = InMemoryProviderReadinessStore()
    future = snapshot(checked_at=datetime.now(UTC) + timedelta(seconds=1))
    store.save(future)

    assert store.read().status == "FRESH"


def test_cache_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_readiness_cache()
    assert "readiness_cache=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_provider_readiness_cache", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "cache=STALE" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_readiness_cache",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
