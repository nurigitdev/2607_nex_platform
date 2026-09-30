from __future__ import annotations

from typing import Any, Callable, Sequence

from nex_mo.provider_telemetry import (
    DEFAULT_TELEMETRY_STORE,
    ProviderExecutionConfigView,
    ProviderTelemetryStore,
    list_provider_telemetry,
    record_provider_retry,
    recorded_provider_call,
    reset_provider_telemetry,
)
from nex_mo.provider_retry import ProviderRetryEvent
from nex_mo.provider_telemetry_repository import (
    SqlAlchemyDurableProviderTelemetryRepository,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore


class ProviderTelemetryRuntimeError(RuntimeError):
    pass


_PROVIDER_TELEMETRY_STORE: ProviderTelemetryStore = DEFAULT_TELEMETRY_STORE


def configure_remote_provider_telemetry_store(
    store: ProviderTelemetryStore,
) -> None:
    global _PROVIDER_TELEMETRY_STORE
    _PROVIDER_TELEMETRY_STORE = store


def current_remote_provider_telemetry_store() -> ProviderTelemetryStore:
    return _PROVIDER_TELEMETRY_STORE


def reset_remote_provider_telemetry() -> None:
    reset_provider_telemetry(_PROVIDER_TELEMETRY_STORE)


def recorded_remote_provider_call(
    config: ProviderExecutionConfigView,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    return recorded_provider_call(
        config,
        operation,
        store=_PROVIDER_TELEMETRY_STORE,
    )


def record_remote_provider_retry(
    config: ProviderExecutionConfigView,
    event: ProviderRetryEvent,
) -> None:
    record_provider_retry(
        config,
        event,
        store=_PROVIDER_TELEMETRY_STORE,
    )


def list_remote_provider_telemetry_configs(
    configs: Sequence[ProviderExecutionConfigView],
    *,
    capability: str | None = None,
) -> list[dict[str, Any]]:
    return list_provider_telemetry(
        configs,
        capability=capability,
        store=_PROVIDER_TELEMETRY_STORE,
    )


def build_provider_telemetry_store(runtime: Any) -> ProviderTelemetryStore:
    mode = getattr(runtime, "mode", None)
    if mode == "memory":
        return DEFAULT_TELEMETRY_STORE
    if mode != "postgres":
        raise ProviderTelemetryRuntimeError(
            "provider telemetry requires memory or postgres persistence mode"
        )
    session_factory = getattr(runtime, "api_session_factory", None)
    if session_factory is None:
        raise ProviderTelemetryRuntimeError(
            "postgres provider telemetry requires an API session factory"
        )
    return DurableProviderTelemetryStore(
        SqlAlchemyDurableProviderTelemetryRepository(session_factory)
    )
