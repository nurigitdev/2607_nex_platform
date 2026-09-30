from __future__ import annotations

from datetime import UTC, datetime
import os
from threading import Lock
from typing import Any, Callable, Mapping

from nex_mo.runtime_observability import REQUIRED_RUNTIME_CAPABILITIES
from nex_mo.runtime_observability_cache import InMemoryRuntimeObservationStore
from nex_mo.runtime_observability_collector import collect_runtime_observations
from nex_mo.runtime_observability_plan import (
    RuntimeObservationPlan,
    build_runtime_observation_plan,
)
from nex_mo.runtime_observability_policy import runtime_observation_thresholds


RUNTIME_OBSERVATION_TTL_ENV = "NEX_MO_RUNTIME_OBSERVABILITY_TTL_SECONDS"
DEFAULT_RUNTIME_OBSERVATION_TTL_SECONDS = 30
MAX_RUNTIME_OBSERVATION_TTL_SECONDS = 300
RuntimeCollector = Callable[..., Any]


class RuntimeObservabilityService:
    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        store: InMemoryRuntimeObservationStore | None = None,
        collector: RuntimeCollector = collect_runtime_observations,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._environ = environ
        self._store = store or InMemoryRuntimeObservationStore()
        self._collector = collector
        self._now = now or (lambda: datetime.now(UTC))
        self._configuration_identity: tuple[Any, ...] | None = None
        self._lock = Lock()

    def observe(self, *, force_refresh: bool = False) -> dict[str, Any]:
        try:
            observed_at = self._now()
            observed_at_text = _iso_timestamp(observed_at)
        except Exception:
            return failed_runtime_observation(observed_at=datetime.now(UTC))
        try:
            with self._lock:
                env = dict(os.environ if self._environ is None else self._environ)
                ttl_seconds = runtime_observation_ttl_seconds(env)
                plan = build_runtime_observation_plan(env)
                thresholds = runtime_observation_thresholds(env)
                identity = (
                    _private_plan_identity(plan),
                    thresholds.gpu_memory_warn_percent,
                    thresholds.gpu_temperature_warn_c,
                )
                if identity != self._configuration_identity:
                    self._store.clear()
                    self._configuration_identity = identity
                snapshot = self._store.resolve(
                    lambda: self._collector(
                        plan,
                        observed_at=observed_at_text,
                        ttl_seconds=ttl_seconds,
                        thresholds=thresholds,
                    ),
                    now=observed_at,
                    force_refresh=force_refresh,
                )
        except Exception:
            return failed_runtime_observation(observed_at=observed_at)
        return snapshot.to_wire()

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._configuration_identity = None


def failed_runtime_observation(*, observed_at: datetime) -> dict[str, Any]:
    timestamp = _iso_timestamp(observed_at)
    return {
        "runtime_observability_schema_version": "mo_runtime_observability.v1",
        "observation_mode": "unknown",
        "runtime_status": "UNKNOWN",
        "observed_at": timestamp,
        "expires_at": timestamp,
        "cache_status": "MISS",
        "required_capabilities": list(REQUIRED_RUNTIME_CAPABILITIES),
        "summary": {
            "required_count": len(REQUIRED_RUNTIME_CAPABILITIES),
            "model_count": 0,
            "status_counts": {
                "HEALTHY": 0,
                "DEGRADED": 0,
                "UNAVAILABLE": 0,
                "UNKNOWN": 0,
            },
        },
        "models": [],
        "failure_code": "runtime_observation_failed",
    }


def runtime_observation_ttl_seconds(environ: Mapping[str, str]) -> int:
    raw_value = environ.get(RUNTIME_OBSERVATION_TTL_ENV)
    if raw_value is None or raw_value == "":
        return DEFAULT_RUNTIME_OBSERVATION_TTL_SECONDS
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("runtime observation TTL must be an integer") from exc
    if not 1 <= value <= MAX_RUNTIME_OBSERVATION_TTL_SECONDS:
        raise ValueError("runtime observation TTL must be between 1 and 300")
    return value


def _private_plan_identity(plan: RuntimeObservationPlan) -> tuple[Any, ...]:
    return (
        plan.mode,
        plan.ssh_target,
        plan.collector_protocol,
        plan.connect_timeout_seconds,
        plan.command_timeout_seconds,
        tuple(
            (
                target.provider_capability,
                target.alias,
                target.deployment_id,
                target.model_revision,
                target.requested_dtype,
                target.process_port,
            )
            for target in plan.targets
        ),
    )


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("runtime observation time must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
