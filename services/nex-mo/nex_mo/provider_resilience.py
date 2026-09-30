from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from nex_mo.provider_readiness import REQUIRED_PROVIDER_CAPABILITIES
from nex_mo.provider_retry import ProviderRetryPolicy


RESILIENCE_STATUSES = ("HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN")


def compose_provider_resilience(
    readiness: Mapping[str, Any],
    telemetry: Sequence[Mapping[str, Any]],
    policies: Sequence[ProviderRetryPolicy],
) -> dict[str, Any]:
    """Compose current route readiness with safe process-local request signals."""
    required = tuple(
        readiness.get("required_capabilities") or REQUIRED_PROVIDER_CAPABILITIES
    )
    if required != REQUIRED_PROVIDER_CAPABILITIES:
        raise ValueError("provider resilience requires the canonical capabilities")
    routes = _index_by_capability(readiness.get("routes") or (), "provider_capability")
    telemetry_by_capability = _index_by_capability(telemetry, "capability")
    policy_by_capability = {policy.capability: policy for policy in policies}
    if set(policy_by_capability) != set(required):
        raise ValueError("provider resilience requires one retry policy per capability")

    providers = [
        _project_capability(
            capability,
            route=routes.get(capability),
            telemetry=telemetry_by_capability.get(capability),
            policy=policy_by_capability[capability],
        )
        for capability in required
    ]
    status_counts = Counter(item["resilience_status"] for item in providers)
    overall_status = _overall_status(providers)
    return {
        "provider_resilience_schema_version": "mo_provider_resilience.v1",
        "ok": overall_status == "HEALTHY",
        "resilience_status": overall_status,
        "readiness_status": readiness.get("readiness_status", "NOT_READY"),
        "readiness_checked_at": readiness.get("checked_at"),
        "readiness_cache_status": readiness.get("cache_status", "MISS"),
        "summary": {
            "capability_count": len(providers),
            "request_count": sum(item["request_count"] for item in providers),
            "attempt_count": sum(item["attempt_count"] for item in providers),
            "retry_count": sum(item["retry_count"] for item in providers),
            "status_counts": {
                status: status_counts.get(status, 0)
                for status in RESILIENCE_STATUSES
            },
        },
        "providers": providers,
    }


def _project_capability(
    capability: str,
    *,
    route: Mapping[str, Any] | None,
    telemetry: Mapping[str, Any] | None,
    policy: ProviderRetryPolicy,
) -> dict[str, Any]:
    route_status = str((route or {}).get("status") or "UNKNOWN")
    last_outcome = (telemetry or {}).get("last_outcome")
    resilience_status = _capability_status(route_status, last_outcome)
    request_count = _safe_count(telemetry, "request_count")
    attempt_count = _safe_count(telemetry, "attempt_count")
    retry_count = _safe_count(telemetry, "retry_count")
    return {
        "capability": capability,
        "deployment_id": (route or {}).get("deployment_id"),
        "model_revision": (route or {}).get("model_revision"),
        "readiness_status": route_status,
        "resilience_status": resilience_status,
        "ok": resilience_status == "HEALTHY",
        "request_count": request_count,
        "attempt_count": attempt_count,
        "retry_count": retry_count,
        "retry_observed": retry_count > 0,
        "last_outcome": last_outcome,
        "last_failure_kind": (telemetry or {}).get("last_failure_kind"),
        "retry_policy": policy.to_safe_summary(),
    }


def _capability_status(route_status: str, last_outcome: Any) -> str:
    if route_status == "UNAVAILABLE":
        return "UNAVAILABLE"
    if route_status == "DEGRADED" or (
        route_status == "READY" and last_outcome == "failure"
    ):
        return "DEGRADED"
    if route_status == "READY":
        return "HEALTHY"
    return "UNKNOWN"


def _overall_status(providers: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(item["resilience_status"]) for item in providers}
    for status in ("UNAVAILABLE", "DEGRADED", "UNKNOWN"):
        if status in statuses:
            return status
    return "HEALTHY"


def _index_by_capability(
    items: Sequence[Mapping[str, Any]],
    key: str,
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in items:
        capability = str(item.get(key) or "")
        if capability not in REQUIRED_PROVIDER_CAPABILITIES:
            continue
        if capability in indexed:
            raise ValueError(f"duplicate provider capability: {capability}")
        indexed[capability] = item
    return indexed


def _safe_count(item: Mapping[str, Any] | None, key: str) -> int:
    value = (item or {}).get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value
