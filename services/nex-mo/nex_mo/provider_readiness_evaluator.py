from __future__ import annotations

import re
from time import perf_counter
from typing import Any, Callable, Mapping

from nex_mo.provider_readiness import (
    ProviderReadinessSnapshot,
    ProviderRouteHealth,
    build_provider_readiness_snapshot,
    utc_now,
)
from nex_mo.provider_readiness_plan import (
    ProviderReadinessProbePlan,
    ProviderReadinessProbeTarget,
)
from nex_mo.provider_telemetry import elapsed_ms
from nex_mo.provider_transport import HttpRequester
from nex_mo.remote_provider import run_remote_provider_preflight_check


SAFE_FAILURE_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
NON_RETRYABLE_FAILURE_CODES = {
    "endpoint_not_configured",
    "expected_model_missing",
    "unsupported_request_shape",
}
TRANSIENT_FAILURE_CODES = {
    "ConnectError",
    "ConnectTimeout",
    "NetworkError",
    "PoolTimeout",
    "ProxyError",
    "ReadError",
    "ReadTimeout",
    "RemoteProtocolError",
    "RequestError",
    "TimeoutException",
    "WriteError",
    "WriteTimeout",
    "response_not_json_object",
    "embedding_data_missing",
    "embedding_vector_missing",
    "rerank_results_missing",
    "rerank_result_invalid",
    "rerank_score_missing",
    "model_list_missing",
}


def evaluate_provider_readiness_plan(
    plan: ProviderReadinessProbePlan,
    *,
    checked_at: str | None = None,
    ttl_seconds: int = 30,
    requester: HttpRequester | None = None,
    clock: Callable[[], float] = perf_counter,
) -> ProviderReadinessSnapshot:
    observed_at = checked_at or utc_now()
    routes = tuple(
        _evaluate_target(
            target,
            checked_at=observed_at,
            requester=requester,
            clock=clock,
        )
        for target in plan.targets
    )
    return build_provider_readiness_snapshot(
        provider_mode=plan.provider_mode,
        routes=routes,
        checked_at=observed_at,
        ttl_seconds=ttl_seconds,
        cache_status="FRESH",
        required_capabilities=plan.required_capabilities,
    )


def _evaluate_target(
    target: ProviderReadinessProbeTarget,
    *,
    checked_at: str,
    requester: HttpRequester | None,
    clock: Callable[[], float],
) -> ProviderRouteHealth:
    if target.route_status != "READY":
        return _route_health(
            target,
            checked_at=checked_at,
            status="UNAVAILABLE",
            source=_source(target),
            latency_ms=0,
            failure_code="provider_route_not_ready",
        )
    if target.provider_mode == "mock":
        return _route_health(
            target,
            checked_at=checked_at,
            status="READY",
            source="mock_registry",
            latency_ms=0,
        )
    if target.preflight_config is None:
        return _route_health(
            target,
            checked_at=checked_at,
            status="UNKNOWN",
            source="active_preflight",
            latency_ms=0,
            failure_code="provider_preflight_config_missing",
        )

    started_at = clock()
    try:
        result = (
            run_remote_provider_preflight_check(target.preflight_config)
            if requester is None
            else run_remote_provider_preflight_check(
                target.preflight_config,
                requester=requester,
            )
        )
    except Exception:
        return _route_health(
            target,
            checked_at=checked_at,
            status="UNKNOWN",
            source="active_preflight",
            latency_ms=elapsed_ms(started_at, clock=clock),
            failure_code="provider_preflight_evaluation_failed",
        )
    status, retryable, degraded, failure_code = _preflight_health_decision(result)
    return _route_health(
        target,
        checked_at=checked_at,
        status=status,
        source="active_preflight",
        latency_ms=elapsed_ms(started_at, clock=clock),
        failure_code=failure_code,
        retryable=retryable,
        degraded=degraded,
    )


def _preflight_health_decision(
    result: Mapping[str, Any],
) -> tuple[str, bool, bool, str | None]:
    if result.get("status") == "PASS":
        return "READY", False, False, None
    failure_code = _safe_failure_code(result.get("failure_code"))
    if failure_code in NON_RETRYABLE_FAILURE_CODES:
        return "UNAVAILABLE", False, False, failure_code
    if failure_code.startswith("http_status_"):
        try:
            status_code = int(failure_code.removeprefix("http_status_"))
        except ValueError:
            return "UNKNOWN", False, False, failure_code
        if status_code == 429 or status_code >= 500:
            return "DEGRADED", True, True, failure_code
        return "UNAVAILABLE", False, False, failure_code
    if failure_code in TRANSIENT_FAILURE_CODES:
        return "DEGRADED", True, True, failure_code
    return "UNKNOWN", False, False, failure_code


def _safe_failure_code(value: Any) -> str:
    if isinstance(value, str) and SAFE_FAILURE_CODE.fullmatch(value):
        return value
    return "provider_preflight_failed"


def _source(target: ProviderReadinessProbeTarget) -> str:
    return "mock_registry" if target.provider_mode == "mock" else "active_preflight"


def _route_health(
    target: ProviderReadinessProbeTarget,
    *,
    checked_at: str,
    status: str,
    source: str,
    latency_ms: int,
    failure_code: str | None = None,
    retryable: bool = False,
    degraded: bool = False,
) -> ProviderRouteHealth:
    return ProviderRouteHealth(
        provider_capability=target.provider_capability,
        alias=target.alias,
        route_id=target.route_id,
        deployment_id=target.deployment_id,
        model_revision=target.model_revision,
        status=status,
        source=source,
        checked_at=checked_at,
        latency_ms=latency_ms,
        failure_code=failure_code,
        retryable=retryable,
        degraded=degraded,
    )
