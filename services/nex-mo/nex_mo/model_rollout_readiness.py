from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from nex_mo.model_capacity_scheduler import CapacityAdmissionDecision
from nex_mo.model_rollout import ModelRevisionIdentity
from nex_mo.provider_readiness import ProviderRouteHealth
from nex_mo.runtime_observability import ModelRuntimeObservation


def evaluate_revision_readiness(
    identity: ModelRevisionIdentity,
    route: ProviderRouteHealth,
    runtime: ModelRuntimeObservation,
    capacity: CapacityAdmissionDecision,
    *,
    evaluated_at: str,
    evidence_ttl_seconds: int = 60,
    require_live: bool = False,
) -> dict[str, Any]:
    if not 1 <= evidence_ttl_seconds <= 300:
        raise ValueError("evidence_ttl_seconds must be between 1 and 300")
    instant = _timestamp(evaluated_at)
    route_time = _timestamp(route.checked_at)
    runtime_time = _timestamp(runtime.observed_at)
    checks = {
        "provider_identity_matches": _provider_identity_matches(identity, route),
        "provider_route_ready": route.status == "READY" and not route.degraded,
        "provider_evidence_fresh": _fresh(
            route_time,
            instant,
            ttl_seconds=evidence_ttl_seconds,
        ),
        "provider_source_admitted": (
            route.source == "active_preflight" if require_live else True
        ),
        "runtime_identity_matches": _runtime_identity_matches(identity, runtime),
        "runtime_healthy": (
            runtime.runtime_status == "HEALTHY"
            and runtime.precision_status == "MATCH"
            and runtime.process_count == 1
            and runtime.gpu_count >= 1
        ),
        "runtime_evidence_fresh": _fresh(
            runtime_time,
            instant,
            ttl_seconds=evidence_ttl_seconds,
        ),
        "runtime_source_admitted": (
            runtime.source == "protected_ssh" if require_live else True
        ),
        "capacity_admitted": capacity.status == "ADMITTED",
        "capacity_identity_matches": (
            capacity.reservation is not None
            and capacity.reservation.identity_fingerprint == identity.fingerprint
            and capacity.reservation.state == "RESERVED"
        ),
    }
    failures = tuple(name for name, passed in checks.items() if not passed)
    status = "READY" if not failures else "BLOCKED"
    evidence = {
        "provider": {
            "route_id": route.route_id,
            "status": route.status,
            "source": route.source,
            "checked_at": route.checked_at,
        },
        "runtime": {
            "status": runtime.runtime_status,
            "precision_status": runtime.precision_status,
            "source": runtime.source,
            "observed_at": runtime.observed_at,
        },
        "capacity": {
            "status": capacity.status,
            "reservation_id": (
                capacity.reservation.reservation_id
                if capacity.reservation is not None
                else None
            ),
        },
    }
    return {
        "schema_version": "mo_revision_readiness.v1",
        "status": status,
        "failure_code": None if not failures else "revision_readiness_blocked",
        "failure_checks": list(failures),
        "identity_fingerprint": identity.fingerprint,
        "provider_capability": identity.provider_capability,
        "alias": identity.alias,
        "model_revision": identity.model_revision,
        "deployment_id": identity.deployment_id,
        "evaluated_at": evaluated_at,
        "evidence_ttl_seconds": evidence_ttl_seconds,
        "checks": checks,
        "evidence": evidence,
        "evidence_digest": _digest(evidence),
    }


def _provider_identity_matches(
    identity: ModelRevisionIdentity,
    route: ProviderRouteHealth,
) -> bool:
    return (
        route.provider_capability == identity.provider_capability
        and route.alias == identity.alias
        and route.model_revision == identity.model_revision
        and route.deployment_id == identity.deployment_id
    )


def _runtime_identity_matches(
    identity: ModelRevisionIdentity,
    runtime: ModelRuntimeObservation,
) -> bool:
    return (
        runtime.provider_capability == identity.provider_capability
        and runtime.alias == identity.alias
        and runtime.model_revision == identity.model_revision
        and runtime.deployment_id == identity.deployment_id
    )


def _fresh(observed: datetime, evaluated: datetime, *, ttl_seconds: int) -> bool:
    age = (evaluated - observed).total_seconds()
    return 0 <= age <= ttl_seconds


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
