from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from typing import Any, Callable, Protocol, Sequence

from nex_mo.providers import ProviderRouteError


class ProviderExecutionConfigView(Protocol):
    capability: str
    endpoint_env: str
    configured: bool
    request_shape: str
    model_name: str
    model_revision: str
    deployment_id: str
    api_key_env: str | None
    api_key: str | None


@dataclass
class RemoteProviderTelemetryBucket:
    capability: str
    endpoint_env: str
    configured: bool
    request_shape: str
    model_name: str
    model_revision: str
    deployment_id: str
    authorization_env: str | None
    authorization_configured: bool
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    retryable_failure_count: int = 0
    degraded_count: int = 0
    last_outcome: str | None = None
    last_observed_at: str | None = None
    last_latency_ms: int | None = None
    last_status_code: int | None = None
    last_error_code: str | None = None
    last_failure_kind: str | None = None
    last_upstream_status_code: int | None = None

    @classmethod
    def from_config(
        cls,
        config: ProviderExecutionConfigView,
    ) -> RemoteProviderTelemetryBucket:
        return cls(
            capability=config.capability,
            endpoint_env=config.endpoint_env,
            configured=config.configured,
            request_shape=config.request_shape,
            model_name=config.model_name,
            model_revision=config.model_revision,
            deployment_id=config.deployment_id,
            authorization_env=config.api_key_env,
            authorization_configured=bool(config.api_key),
        )

    def record_success(self, *, latency_ms: int, observed_at: str) -> None:
        self.request_count += 1
        self.success_count += 1
        self.last_outcome = "success"
        self.last_observed_at = observed_at
        self.last_latency_ms = latency_ms
        self.last_status_code = 200
        self.last_error_code = None
        self.last_failure_kind = None
        self.last_upstream_status_code = None

    def record_failure(
        self,
        *,
        route_error: ProviderRouteError,
        latency_ms: int,
        observed_at: str,
    ) -> None:
        self.request_count += 1
        self.failure_count += 1
        if route_error.retryable:
            self.retryable_failure_count += 1
        if route_error.degraded:
            self.degraded_count += 1
        self.last_outcome = "failure"
        self.last_observed_at = observed_at
        self.last_latency_ms = latency_ms
        self.last_status_code = route_error.status_code
        self.last_error_code = route_error.error_code
        self.last_failure_kind = route_error.failure_kind or "provider_route_error"
        self.last_upstream_status_code = route_error.upstream_status_code

    def to_wire(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "endpoint_env": self.endpoint_env,
            "configured": self.configured,
            "request_shape": self.request_shape,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "deployment_id": self.deployment_id,
            "authorization_env": self.authorization_env,
            "authorization_configured": self.authorization_configured,
            "request_count": self.request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "retryable_failure_count": self.retryable_failure_count,
            "degraded_count": self.degraded_count,
            "last_outcome": self.last_outcome,
            "last_observed_at": self.last_observed_at,
            "last_latency_ms": self.last_latency_ms,
            "last_status_code": self.last_status_code,
            "last_error_code": self.last_error_code,
            "last_failure_kind": self.last_failure_kind,
            "last_upstream_status_code": self.last_upstream_status_code,
        }


class ProviderTelemetryStore(Protocol):
    def snapshot(
        self,
        configs: Sequence[ProviderExecutionConfigView],
        *,
        capability: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def reset(self) -> None: ...

    def record_success(
        self,
        config: ProviderExecutionConfigView,
        *,
        latency_ms: int,
        observed_at: str,
    ) -> None: ...

    def record_failure(
        self,
        config: ProviderExecutionConfigView,
        *,
        route_error: ProviderRouteError,
        latency_ms: int,
        observed_at: str,
    ) -> None: ...


class InMemoryProviderTelemetryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._buckets: dict[str, RemoteProviderTelemetryBucket] = {}

    def snapshot(
        self,
        configs: Sequence[ProviderExecutionConfigView],
        *,
        capability: str | None = None,
    ) -> list[dict[str, Any]]:
        configured = {
            telemetry_key(config): RemoteProviderTelemetryBucket.from_config(config)
            for config in configs
        }
        with self._lock:
            buckets = {**configured, **self._buckets}
            items = [bucket.to_wire() for bucket in buckets.values()]
        if capability is not None:
            items = [item for item in items if item["capability"] == capability]
        return sorted(
            items,
            key=lambda item: (str(item["capability"]), str(item["deployment_id"])),
        )

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def record_success(
        self,
        config: ProviderExecutionConfigView,
        *,
        latency_ms: int,
        observed_at: str,
    ) -> None:
        with self._lock:
            self._bucket(config).record_success(
                latency_ms=latency_ms,
                observed_at=observed_at,
            )

    def record_failure(
        self,
        config: ProviderExecutionConfigView,
        *,
        route_error: ProviderRouteError,
        latency_ms: int,
        observed_at: str,
    ) -> None:
        with self._lock:
            self._bucket(config).record_failure(
                route_error=route_error,
                latency_ms=latency_ms,
                observed_at=observed_at,
            )

    def _bucket(
        self,
        config: ProviderExecutionConfigView,
    ) -> RemoteProviderTelemetryBucket:
        key = telemetry_key(config)
        if key not in self._buckets:
            self._buckets[key] = RemoteProviderTelemetryBucket.from_config(config)
        return self._buckets[key]


DEFAULT_TELEMETRY_STORE = InMemoryProviderTelemetryStore()
_TELEMETRY_LOCK = DEFAULT_TELEMETRY_STORE._lock
_TELEMETRY_BUCKETS = DEFAULT_TELEMETRY_STORE._buckets


def recorded_provider_call(
    config: ProviderExecutionConfigView,
    operation: Callable[[], dict[str, Any]],
    *,
    store: ProviderTelemetryStore = DEFAULT_TELEMETRY_STORE,
    clock: Callable[[], float] = perf_counter,
    observed_at: Callable[[], str] | None = None,
) -> dict[str, Any]:
    started_at = clock()
    now = observed_at or utc_now
    try:
        result = operation()
    except ProviderRouteError as exc:
        store.record_failure(
            config,
            route_error=exc,
            latency_ms=elapsed_ms(started_at, clock=clock),
            observed_at=now(),
        )
        raise
    store.record_success(
        config,
        latency_ms=elapsed_ms(started_at, clock=clock),
        observed_at=now(),
    )
    return result


def list_provider_telemetry(
    configs: Sequence[ProviderExecutionConfigView],
    *,
    capability: str | None = None,
    store: ProviderTelemetryStore = DEFAULT_TELEMETRY_STORE,
) -> list[dict[str, Any]]:
    return store.snapshot(configs, capability=capability)


def reset_provider_telemetry(
    store: ProviderTelemetryStore = DEFAULT_TELEMETRY_STORE,
) -> None:
    store.reset()


def telemetry_key(config: ProviderExecutionConfigView) -> str:
    return "|".join(
        (
            config.capability,
            config.request_shape,
            config.deployment_id,
            config.model_revision,
        )
    )


def elapsed_ms(started_at: float, *, clock: Callable[[], float] = perf_counter) -> int:
    return max(0, int(round((clock() - started_at) * 1000)))


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
