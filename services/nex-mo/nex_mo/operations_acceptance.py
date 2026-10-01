from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.engine import make_url

from nex_mo.remote_provider import build_remote_provider_preflight_configs
from nex_mo.runtime_observability_plan import build_runtime_observation_plan


OPERATIONS_ACCEPTANCE_ENV = "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE"
OPERATIONS_ACCEPTANCE_PROFILE_ENV = "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE_PROFILE"
EXPECTED_DATABASE = "nex_mo_test"
EXPECTED_ROLE = "nex_mo_user"
EXPECTED_REQUEST_SHAPES = {
    "embedding": "openai_embeddings",
    "reranking": "rerank",
    "generation": "openai_models",
}


@dataclass(frozen=True)
class OperationsAcceptanceTarget:
    provider_capability: str
    alias: str
    endpoint_env: str
    configured: bool
    request_shape: str
    expected_models: tuple[str, ...]
    authorization_env: str | None
    authorization_configured: bool
    timeout_seconds: float

    def to_wire(self) -> dict[str, Any]:
        return {
            "provider_capability": self.provider_capability,
            "alias": self.alias,
            "endpoint_env": self.endpoint_env,
            "configured": self.configured,
            "request_shape": self.request_shape,
            "expected_models": list(self.expected_models),
            "authorization_env": self.authorization_env,
            "authorization_configured": self.authorization_configured,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class OperationsAcceptancePlan:
    profile: str
    provider_mode: str
    database_configured: bool
    database_name: str | None
    database_role: str | None
    runtime_observation_mode: str
    runtime_observation_configured: bool
    targets: tuple[OperationsAcceptanceTarget, ...]
    issues: tuple[str, ...]

    @property
    def admission_status(self) -> str:
        return "READY" if not self.issues else "BLOCKED"

    def to_wire(self) -> dict[str, Any]:
        return {
            "acceptance_plan_schema_version": "mo_operations_acceptance_plan.v1",
            "profile": self.profile,
            "provider_mode": self.provider_mode,
            "admission_status": self.admission_status,
            "database": {
                "configured": self.database_configured,
                "name": self.database_name,
                "role": self.database_role,
            },
            "runtime_observation": {
                "mode": self.runtime_observation_mode,
                "configured": self.runtime_observation_configured,
            },
            "targets": [target.to_wire() for target in self.targets],
            "issues": list(self.issues),
            "redaction": {
                "status": "PASS",
                "excluded": [
                    "provider_endpoint_value",
                    "provider_api_key_value",
                    "database_url",
                    "database_password",
                    "ssh_target_value",
                ],
            },
        }


def build_operations_acceptance_plan(
    environ: Mapping[str, str],
) -> OperationsAcceptancePlan:
    env = dict(environ)
    issues: list[str] = []
    if env.get(OPERATIONS_ACCEPTANCE_ENV) != "1":
        issues.append("acceptance_not_enabled")
    profile = env.get(OPERATIONS_ACCEPTANCE_PROFILE_ENV, "")
    if profile != "test":
        issues.append("acceptance_profile_not_allowed")
    provider_mode = env.get("NEX_MO_PROVIDER_MODE", "mock")
    if provider_mode != "live":
        issues.append("provider_mode_not_live")

    database_configured, database_name, database_role = _database_identity(
        env.get("NEX_MO_TEST_DATABASE_URL")
    )
    if not database_configured:
        issues.append("test_database_not_configured")
    elif database_name != EXPECTED_DATABASE or database_role != EXPECTED_ROLE:
        issues.append("test_database_identity_not_allowed")

    targets: tuple[OperationsAcceptanceTarget, ...] = ()
    try:
        aliases = {
            "embedding": "mock-embedding-default",
            "reranking": "mock-reranker-default",
            "generation": "general-llm-default",
        }
        targets = tuple(
            OperationsAcceptanceTarget(
                provider_capability=config.capability,
                alias=aliases[config.capability],
                endpoint_env=config.endpoint_env,
                configured=config.configured,
                request_shape=config.request_shape,
                expected_models=config.expected_models,
                authorization_env=config.api_key_env,
                authorization_configured=config.authorization_configured,
                timeout_seconds=config.timeout_seconds,
            )
            for config in build_remote_provider_preflight_configs(env)
        )
        for target in targets:
            if not target.configured:
                issues.append(f"{target.provider_capability}_endpoint_not_configured")
            if not target.authorization_configured:
                issues.append(
                    f"{target.provider_capability}_authorization_not_configured"
                )
            if target.request_shape != EXPECTED_REQUEST_SHAPES[
                target.provider_capability
            ]:
                issues.append(f"{target.provider_capability}_request_shape_invalid")
            if not target.expected_models:
                issues.append(f"{target.provider_capability}_expected_model_missing")
    except (KeyError, TypeError, ValueError):
        issues.append("provider_acceptance_configuration_invalid")

    runtime_mode = env.get("NEX_MO_RUNTIME_OBSERVABILITY_MODE", "mock")
    runtime_configured = False
    try:
        runtime_plan = build_runtime_observation_plan(env)
        runtime_mode = runtime_plan.mode
        runtime_configured = runtime_plan.configured and runtime_plan.mode == "live"
        if not runtime_configured:
            issues.append("runtime_observation_not_live")
    except ValueError:
        issues.append("runtime_observation_configuration_invalid")

    return OperationsAcceptancePlan(
        profile=profile,
        provider_mode=provider_mode,
        database_configured=database_configured,
        database_name=database_name,
        database_role=database_role,
        runtime_observation_mode=runtime_mode,
        runtime_observation_configured=runtime_configured,
        targets=targets,
        issues=tuple(dict.fromkeys(issues)),
    )


def _database_identity(value: str | None) -> tuple[bool, str | None, str | None]:
    if not value:
        return False, None, None
    try:
        url = make_url(value)
    except Exception:
        return False, None, None
    return bool(url.database and url.username), url.database, url.username
