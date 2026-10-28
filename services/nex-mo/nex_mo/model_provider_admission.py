from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime.dependency_readiness import (
    DependencyReadinessRequirement,
    PlatformDependencyReadiness,
    aggregate_dependency_readiness,
    normalize_dependency_readiness,
)

from nex_mo.provider_readiness_plan import (
    ProviderReadinessProbeTarget,
    build_provider_readiness_probe_plan,
)
from nex_mo.provider_readiness_service import ProviderReadinessService
from nex_mo.provider_transport import HttpRequester

MODEL_PROVIDER_ADMISSION_SCHEMA_VERSION = "model_provider_admission.v1"
MODEL_PROVIDER_PROFILE_ENV = "NEX_MO_PROVIDER_DEPENDENCY_PROFILE"
DEFAULT_MODEL_PROVIDER_PROFILE = "rag"
MAX_PROVIDER_TIMEOUT_SECONDS = 300.0


class ModelProviderAdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class ModelProviderRequirement:
    capability: str
    required: bool
    minimum_timeout_seconds: float

    @property
    def dependency_id(self) -> str:
        return f"provider:{self.capability}"

    def to_projection(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "capability": self.capability,
            "required": self.required,
            "minimum_timeout_seconds": self.minimum_timeout_seconds,
        }


MODEL_PROVIDER_PROFILES: dict[str, tuple[ModelProviderRequirement, ...]] = {
    "rag": (
        ModelProviderRequirement("embedding", True, 10.0),
        ModelProviderRequirement("reranking", True, 10.0),
        ModelProviderRequirement("generation", True, 30.0),
    ),
    "semantic_planning": (
        ModelProviderRequirement("embedding", False, 10.0),
        ModelProviderRequirement("reranking", False, 10.0),
        ModelProviderRequirement("generation", True, 30.0),
    ),
}


def admit_model_provider_readiness(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    now: Callable[[], datetime] | None = None,
    require_live: bool = True,
) -> dict[str, Any]:
    """Admit the profile-required model providers through active readiness."""

    env = dict(os.environ if environ is None else environ)
    profile_name, requirements = resolve_model_provider_profile(env)
    required_capabilities = tuple(
        item.capability for item in requirements if item.required
    )
    plan = build_provider_readiness_probe_plan(
        env,
        required_capabilities=required_capabilities,
    )
    service = ProviderReadinessService(
        environ=env,
        required_capabilities=required_capabilities,
        requester=requester,
        now=now,
    )
    owner_readiness = service.check(force_refresh=True)
    routes = {
        str(route.get("provider_capability")): route
        for route in owner_readiness.get("routes", [])
        if isinstance(route, Mapping)
    }
    checked_at = _checked_at(owner_readiness.get("checked_at"))

    checks: list[dict[str, Any]] = []
    observations: list[PlatformDependencyReadiness] = []
    for requirement in requirements:
        if not requirement.required:
            continue
        target = plan.target_for(requirement.capability)
        route = routes.get(requirement.capability, {})
        check = _admit_target(
            requirement,
            target,
            route,
            provider_mode=plan.provider_mode,
            require_live=require_live,
        )
        checks.append(check)
        observations.append(
            normalize_dependency_readiness(
                _dependency_requirement(requirement),
                configured=check["configured"],
                provisioned=(
                    check["model_identity_admitted"]
                    and check["timeout_policy_valid"]
                ),
                reachable=(
                    check["bounded_request_succeeded"]
                    and check["response_observed"]
                    and check["provider_mode_admitted"]
                ),
                authorized=check["authorized"],
                checked_at=checked_at,
            )
        )

    dependency_requirements = tuple(
        _dependency_requirement(item) for item in requirements
    )
    aggregate = aggregate_dependency_readiness(
        dependency_requirements,
        tuple(observations),
    )
    admitted = (
        owner_readiness.get("readiness_status") == "READY"
        and aggregate["readiness_status"] == "READY"
        and all(check["status"] == "PASS" for check in checks)
    )
    return {
        "schema_version": MODEL_PROVIDER_ADMISSION_SCHEMA_VERSION,
        "status": "PASS" if admitted else "FAIL",
        "admission_status": "ADMITTED" if admitted else "BLOCKED",
        "failure_code": None if admitted else "model_provider_admission_blocked",
        "profile": profile_name,
        "provider_mode": plan.provider_mode,
        "required_capabilities": list(required_capabilities),
        "requirements": [item.to_projection() for item in requirements],
        "checks": checks,
        "dependency_readiness": [item.to_projection() for item in observations],
        "dependency_readiness_aggregate": aggregate,
        "readiness_status": aggregate["readiness_status"],
        "checked_at": checked_at,
        "raw_provider_endpoint_included": False,
        "raw_provider_api_key_included": False,
        "prompt_content_included": False,
        "raw_response_included": False,
    }


def resolve_model_provider_profile(
    environ: Mapping[str, str],
) -> tuple[str, tuple[ModelProviderRequirement, ...]]:
    profile_name = str(
        environ.get(MODEL_PROVIDER_PROFILE_ENV) or DEFAULT_MODEL_PROVIDER_PROFILE
    ).strip()
    try:
        requirements = MODEL_PROVIDER_PROFILES[profile_name]
    except KeyError:
        raise ModelProviderAdmissionError(
            "Model-provider dependency profile is unsupported"
        ) from None
    return profile_name, requirements


def _admit_target(
    requirement: ModelProviderRequirement,
    target: ProviderReadinessProbeTarget,
    route: Mapping[str, Any],
    *,
    provider_mode: str,
    require_live: bool,
) -> dict[str, Any]:
    route_ready = route.get("status") == "READY"
    expected_source = "active_preflight" if provider_mode == "live" else "mock_registry"
    mode_admitted = provider_mode == "live" or not require_live
    identity_admitted = (
        route.get("provider_capability") == target.provider_capability
        and route.get("alias") == target.alias
        and route.get("deployment_id") == target.deployment_id
        and route.get("model_revision") == target.model_revision
        and bool(target.model_revision)
        and bool(target.expected_models)
    )
    timeout_valid = (
        target.timeout_seconds == 0.0
        if provider_mode == "mock" and not require_live
        else requirement.minimum_timeout_seconds
        <= target.timeout_seconds
        <= MAX_PROVIDER_TIMEOUT_SECONDS
    )
    bounded_request_succeeded = (
        route_ready and route.get("source") == expected_source
    )
    authorized = bounded_request_succeeded and mode_admitted
    checks = {
        "configured": target.configured,
        "authorized": authorized,
        "model_identity_admitted": identity_admitted,
        "bounded_request_succeeded": bounded_request_succeeded,
        "timeout_policy_valid": timeout_valid,
        "response_observed": bounded_request_succeeded,
        "provider_mode_admitted": mode_admitted,
    }
    passed = all(checks.values())
    result = {
        "capability": requirement.capability,
        "required": requirement.required,
        "status": "PASS" if passed else "FAIL",
        **checks,
        "authorization_configured": target.authorization_configured,
        "request_shape": target.request_shape,
        "timeout_seconds": target.timeout_seconds,
        "expected_models": list(target.expected_models),
        "model_revision": target.model_revision,
        "deployment_id": target.deployment_id,
        "source": route.get("source"),
        "failure_code": route.get("failure_code") or (
            None if passed else "provider_admission_check_failed"
        ),
    }
    if route.get("failure_code") == "expected_model_missing":
        result["missing_expected_models"] = list(target.expected_models)
    return result


def _dependency_requirement(
    requirement: ModelProviderRequirement,
) -> DependencyReadinessRequirement:
    return DependencyReadinessRequirement(
        dependency_id=requirement.dependency_id,
        dependency_type="MODEL_PROVIDER",
        owner="nex-mo",
        required=requirement.required,
    )


def _checked_at(value: object) -> str:
    if not isinstance(value, str):
        raise ModelProviderAdmissionError(
            "Model-provider readiness timestamp is missing"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ModelProviderAdmissionError(
            "Model-provider readiness timestamp is invalid"
        ) from None
    if parsed.tzinfo is None:
        raise ModelProviderAdmissionError(
            "Model-provider readiness timestamp must include a timezone"
        )
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
