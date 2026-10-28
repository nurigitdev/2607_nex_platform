from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from typing import Any

from nex_mo.provider_readiness import (
    REQUIRED_PROVIDER_CAPABILITIES,
    ProviderReadinessSnapshot,
)
from nex_mo.provider_readiness_cache import InMemoryProviderReadinessStore
from nex_mo.provider_readiness_evaluator import evaluate_provider_readiness_plan
from nex_mo.provider_readiness_plan import (
    ProviderReadinessProbePlan,
    build_provider_readiness_probe_plan,
)
from nex_mo.provider_transport import HttpRequester

PROVIDER_READINESS_TTL_ENV = "NEX_MO_PROVIDER_READINESS_TTL_SECONDS"
DEFAULT_PROVIDER_READINESS_TTL_SECONDS = 30
MAX_PROVIDER_READINESS_TTL_SECONDS = 300


class ProviderReadinessService:
    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        required_capabilities: tuple[str, ...] = REQUIRED_PROVIDER_CAPABILITIES,
        store: InMemoryProviderReadinessStore | None = None,
        requester: HttpRequester | None = None,
        now: Callable[[], datetime] | None = None,
        latency_clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._environ = environ
        self._required_capabilities = required_capabilities
        self._store = store or InMemoryProviderReadinessStore()
        self._requester = requester
        self._now = now or (lambda: datetime.now(UTC))
        self._latency_clock = latency_clock
        self._configuration_identity: tuple[Any, ...] | None = None
        self._lock = Lock()

    def check(self, *, force_refresh: bool = False) -> dict[str, Any]:
        try:
            observed_at = self._now()
            _iso_timestamp(observed_at)
        except Exception:  # noqa: BLE001 - readiness must fail closed
            return failed_provider_readiness_check(
                checked_at=datetime.now(UTC),
                required_capabilities=self._required_capabilities,
            )
        try:
            with self._lock:
                env = dict(os.environ if self._environ is None else self._environ)
                ttl_seconds = provider_readiness_ttl_seconds(env)
                plan = build_provider_readiness_probe_plan(
                    env,
                    required_capabilities=self._required_capabilities,
                )
                identity = _private_plan_identity(plan)
                if identity != self._configuration_identity:
                    self._store.clear()
                    self._configuration_identity = identity
                snapshot = self._store.resolve(
                    lambda: evaluate_provider_readiness_plan(
                        plan,
                        checked_at=_iso_timestamp(observed_at),
                        ttl_seconds=ttl_seconds,
                        requester=self._requester,
                        clock=self._latency_clock,
                    ),
                    now=observed_at,
                    force_refresh=force_refresh,
                )
        except Exception:  # noqa: BLE001 - readiness must fail closed
            return failed_provider_readiness_check(
                checked_at=observed_at,
                required_capabilities=self._required_capabilities,
            )
        return project_provider_readiness_check(snapshot)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._configuration_identity = None


def project_provider_readiness_check(
    snapshot: ProviderReadinessSnapshot,
) -> dict[str, Any]:
    payload = snapshot.to_wire()
    return {
        "name": "provider_routes",
        "ok": snapshot.readiness_status == "READY",
        **payload,
        "error_code": (
            None
            if snapshot.readiness_status == "READY"
            else "PROVIDER_ROUTE_NOT_READY"
        ),
    }


def failed_provider_readiness_check(
    *,
    checked_at: datetime,
    required_capabilities: tuple[str, ...] = REQUIRED_PROVIDER_CAPABILITIES,
) -> dict[str, Any]:
    return {
        "name": "provider_routes",
        "ok": False,
        "provider_readiness_schema_version": "mo_provider_readiness.v1",
        "provider_mode": "unknown",
        "readiness_status": "NOT_READY",
        "checked_at": _iso_timestamp(checked_at),
        "expires_at": _iso_timestamp(checked_at),
        "cache_status": "MISS",
        "required_capabilities": list(required_capabilities),
        "summary": {
            "required_count": len(required_capabilities),
            "route_count": 0,
            "status_counts": {
                "READY": 0,
                "DEGRADED": 0,
                "UNAVAILABLE": 0,
                "UNKNOWN": 0,
            },
        },
        "routes": [],
        "failure_code": "provider_readiness_evaluation_failed",
        "error_code": "PROVIDER_READINESS_EVALUATION_FAILED",
    }


def provider_readiness_ttl_seconds(environ: Mapping[str, str]) -> int:
    raw_value = environ.get(PROVIDER_READINESS_TTL_ENV)
    if raw_value is None or raw_value == "":
        return DEFAULT_PROVIDER_READINESS_TTL_SECONDS
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("provider readiness TTL must be an integer") from exc
    if not 1 <= value <= MAX_PROVIDER_READINESS_TTL_SECONDS:
        raise ValueError("provider readiness TTL must be between 1 and 300")
    return value


def _private_plan_identity(plan: ProviderReadinessProbePlan) -> tuple[Any, ...]:
    targets: list[tuple[Any, ...]] = []
    for target in plan.targets:
        preflight = target.preflight_config
        targets.append(
            (
                target.provider_capability,
                target.alias,
                target.route_id,
                target.deployment_id,
                target.model_revision,
                target.route_status,
                target.provider_mode,
                target.configured,
                target.method,
                target.request_shape,
                target.timeout_seconds,
                target.expected_models,
                preflight.url if preflight is not None else None,
                preflight.api_key if preflight is not None else None,
            )
        )
    return (plan.provider_mode, plan.required_capabilities, tuple(targets))


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("readiness time must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
