from __future__ import annotations

from types import SimpleNamespace

import pytest

import nex_mo.remote_provider as remote_provider
from nex_mo.provider_telemetry import (
    DEFAULT_TELEMETRY_STORE,
    InMemoryProviderTelemetryStore,
)
from nex_mo.provider_telemetry_runtime import (
    ProviderTelemetryRuntimeError,
    build_provider_telemetry_store,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore


@pytest.fixture(autouse=True)
def restore_default_store():
    prior = remote_provider.current_remote_provider_telemetry_store()
    yield
    remote_provider.configure_remote_provider_telemetry_store(prior)


def test_memory_runtime_reuses_compatible_default_store() -> None:
    store = build_provider_telemetry_store(
        SimpleNamespace(mode="memory", api_session_factory=None)
    )

    assert store is DEFAULT_TELEMETRY_STORE


def test_postgres_runtime_builds_durable_store() -> None:
    session_factory = object()
    store = build_provider_telemetry_store(
        SimpleNamespace(mode="postgres", api_session_factory=session_factory)
    )

    assert isinstance(store, DurableProviderTelemetryStore)
    assert store._repository._session_factory is session_factory


@pytest.mark.parametrize(
    ("runtime", "message"),
    [
        (SimpleNamespace(mode="unknown"), "memory or postgres"),
        (
            SimpleNamespace(mode="postgres", api_session_factory=None),
            "requires an API session factory",
        ),
    ],
)
def test_runtime_rejects_invalid_persistence(runtime, message: str) -> None:
    with pytest.raises(ProviderTelemetryRuntimeError, match=message):
        build_provider_telemetry_store(runtime)


def test_remote_provider_uses_configured_store_for_snapshot_and_reset() -> None:
    store = InMemoryProviderTelemetryStore()
    remote_provider.configure_remote_provider_telemetry_store(store)

    assert remote_provider.current_remote_provider_telemetry_store() is store
    assert len(remote_provider.list_remote_provider_telemetry(environ={})) == 3
    remote_provider.reset_remote_provider_telemetry()
    assert store._buckets == {}


def test_remote_provider_records_request_and_retry_through_configured_store() -> None:
    store = InMemoryProviderTelemetryStore()
    remote_provider.configure_remote_provider_telemetry_store(store)
    config = remote_provider.build_remote_embedding_execution_config(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.test/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "model",
        }
    )

    result = remote_provider._recorded_remote_provider_call(
        config,
        lambda: {"ok": True},
    )
    remote_provider.record_provider_retry(
        config,
        SimpleNamespace(delay_seconds=0.1, failure_kind="upstream_5xx"),
    )

    assert result == {"ok": True}
    item = remote_provider.list_remote_provider_telemetry(
        capability="embedding",
        environ={
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://provider.test/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "model",
        },
    )[0]
    assert item["request_count"] == 1
    assert item["attempt_count"] == 2
    assert item["retry_count"] == 1


def test_mo_main_exposes_telemetry_store_on_app_state() -> None:
    from nex_mo.main import PROVIDER_TELEMETRY_STORE, app

    assert app.state.provider_telemetry_store is PROVIDER_TELEMETRY_STORE
