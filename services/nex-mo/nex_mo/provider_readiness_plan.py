from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from nex_mo.provider_readiness import REQUIRED_PROVIDER_CAPABILITIES
from nex_mo.provider_registry import DEFAULT_PROVIDER_ROUTES, ProviderRoute
from nex_mo.remote_provider import (
    RemoteProviderExecutionConfig,
    RemoteProviderPreflightConfig,
    build_remote_embedding_execution_config,
    build_remote_generation_execution_config,
    build_remote_provider_preflight_configs,
    build_remote_reranker_execution_config,
)


@dataclass(frozen=True)
class ProviderReadinessPlanError(Exception):
    failure_code: str

    def __str__(self) -> str:
        return self.failure_code


@dataclass(frozen=True)
class ProviderReadinessProbeTarget:
    provider_capability: str
    alias: str
    route_id: str
    deployment_id: str
    model_revision: str
    route_status: str
    provider_mode: str
    configured: bool
    method: str
    request_shape: str
    timeout_seconds: float
    expected_models: tuple[str, ...]
    authorization_configured: bool
    preflight_config: RemoteProviderPreflightConfig | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def to_safe_summary(self) -> dict[str, Any]:
        return {
            "provider_capability": self.provider_capability,
            "alias": self.alias,
            "route_id": self.route_id,
            "deployment_id": self.deployment_id,
            "model_revision": self.model_revision,
            "route_status": self.route_status,
            "provider_mode": self.provider_mode,
            "configured": self.configured,
            "method": self.method,
            "request_shape": self.request_shape,
            "timeout_seconds": self.timeout_seconds,
            "expected_models": list(self.expected_models),
            "authorization_configured": self.authorization_configured,
        }


@dataclass(frozen=True)
class ProviderReadinessProbePlan:
    provider_mode: str
    required_capabilities: tuple[str, ...]
    targets: tuple[ProviderReadinessProbeTarget, ...]

    def target_for(self, capability: str) -> ProviderReadinessProbeTarget:
        matches = [
            target
            for target in self.targets
            if target.provider_capability == capability
        ]
        if len(matches) != 1:
            raise ProviderReadinessPlanError("probe_target_not_unique")
        return matches[0]

    def to_safe_summary(self) -> dict[str, Any]:
        return {
            "probe_plan_schema_version": "mo_provider_readiness_probe_plan.v1",
            "provider_mode": self.provider_mode,
            "required_capabilities": list(self.required_capabilities),
            "target_count": len(self.targets),
            "targets": [target.to_safe_summary() for target in self.targets],
        }


def build_provider_readiness_probe_plan(
    environ: Mapping[str, str] | None = None,
    *,
    routes: Sequence[ProviderRoute] = DEFAULT_PROVIDER_ROUTES,
    required_capabilities: tuple[str, ...] = REQUIRED_PROVIDER_CAPABILITIES,
) -> ProviderReadinessProbePlan:
    env = dict(os.environ if environ is None else environ)
    provider_mode = env.get("NEX_MO_PROVIDER_MODE", "mock")
    if provider_mode not in {"mock", "live"}:
        raise ProviderReadinessPlanError("provider_mode_invalid")
    route_by_capability = _unique_routes(routes, required_capabilities)
    if provider_mode == "mock":
        targets = tuple(
            _mock_target(route_by_capability[capability])
            for capability in required_capabilities
        )
    else:
        preflight_by_capability = {
            config.capability: config
            for config in build_remote_provider_preflight_configs(env)
        }
        execution_by_capability = {
            config.capability: config for config in _execution_configs(env)
        }
        targets = tuple(
            _live_target(
                route_by_capability[capability],
                _required_config(preflight_by_capability, capability),
                _required_config(execution_by_capability, capability),
            )
            for capability in required_capabilities
        )
    return ProviderReadinessProbePlan(
        provider_mode=provider_mode,
        required_capabilities=required_capabilities,
        targets=targets,
    )


def _unique_routes(
    routes: Sequence[ProviderRoute],
    required_capabilities: tuple[str, ...],
) -> dict[str, ProviderRoute]:
    if not required_capabilities or len(set(required_capabilities)) != len(
        required_capabilities
    ):
        raise ProviderReadinessPlanError("required_capabilities_invalid")
    result: dict[str, ProviderRoute] = {}
    for capability in required_capabilities:
        matches = [
            route for route in routes if route.provider_capability == capability
        ]
        if not matches:
            raise ProviderReadinessPlanError("provider_route_missing")
        if len(matches) != 1:
            raise ProviderReadinessPlanError("provider_route_not_unique")
        result[capability] = matches[0]
    return result


def _mock_target(route: ProviderRoute) -> ProviderReadinessProbeTarget:
    return ProviderReadinessProbeTarget(
        provider_capability=route.provider_capability,
        alias=route.alias,
        route_id=route.route_id,
        deployment_id=route.deployment_id,
        model_revision=route.model_revision,
        route_status=route.status,
        provider_mode="mock",
        configured=True,
        method="LOCAL",
        request_shape="deterministic_mock",
        timeout_seconds=0.0,
        expected_models=(route.model_revision,),
        authorization_configured=False,
    )


def _live_target(
    route: ProviderRoute,
    preflight: RemoteProviderPreflightConfig,
    execution: RemoteProviderExecutionConfig,
) -> ProviderReadinessProbeTarget:
    return ProviderReadinessProbeTarget(
        provider_capability=route.provider_capability,
        alias=route.alias,
        route_id=route.route_id,
        deployment_id=execution.deployment_id,
        model_revision=execution.model_revision,
        route_status=route.status,
        provider_mode="live",
        configured=preflight.configured,
        method=preflight.method,
        request_shape=preflight.request_shape,
        timeout_seconds=preflight.timeout_seconds,
        expected_models=preflight.expected_models,
        authorization_configured=preflight.authorization_configured,
        preflight_config=preflight,
    )


def _execution_configs(
    env: dict[str, str],
) -> tuple[RemoteProviderExecutionConfig, ...]:
    return (
        build_remote_embedding_execution_config(env),
        build_remote_reranker_execution_config(env),
        build_remote_generation_execution_config(env),
    )


def _required_config(
    configs: Mapping[str, Any],
    capability: str,
) -> Any:
    try:
        return configs[capability]
    except KeyError as exc:
        raise ProviderReadinessPlanError("provider_config_missing") from exc
