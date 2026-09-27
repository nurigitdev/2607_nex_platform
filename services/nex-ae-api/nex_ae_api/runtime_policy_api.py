from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import problem_response
from nex_ae_api.prompt_persistence import PromptRepositoryError
from nex_ae_api.prompts import build_default_ae_prompt_store
from nex_ae_api.route_auth import authorize_ae_facade_route_request
from nex_ae_api.runtime_policy import (
    DEFAULT_AE_RUNTIME_POLICY_RULES,
    RuntimePolicyError,
    resolve_runtime_policy,
)


RUNTIME_POLICY_CATALOG_SCHEMA_VERSION = "ae_runtime_policy_catalog.v1"
PROMPT_BINDING_PROJECTION_SCHEMA_VERSION = "ae_prompt_binding_projection.v1"


@dataclass(frozen=True)
class RuntimePolicyApiError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def register_runtime_policy_routes(
    app: FastAPI,
    *,
    store: Any | None = None,
    rules: Sequence[Mapping[str, Any]] = DEFAULT_AE_RUNTIME_POLICY_RULES,
) -> None:
    prompt_store = store or build_default_ae_prompt_store(app)
    app.state.ae_prompt_store = prompt_store

    @app.get("/api/v1/runtime-policies", response_model=None)
    def list_runtime_policies(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        return {
            "runtime_policy_catalog_schema_version": (
                RUNTIME_POLICY_CATALOG_SCHEMA_VERSION
            ),
            "policies": [safe_runtime_policy_rule(rule) for rule in rules],
        }

    @app.post("/api/v1/runtime-policies/resolve", response_model=None)
    def resolve_runtime_policy_request(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        try:
            resolved = resolve_runtime_policy(payload, rules=rules)
            binding = resolve_safe_prompt_binding(
                prompt_store,
                binding_key=resolved["prompt_contract_ref"]["prompt_binding_key"],
                prompt_version=resolved["prompt_contract_ref"]["prompt_version"],
            )
        except (RuntimePolicyError, RuntimePolicyApiError, PromptRepositoryError) as exc:
            return _runtime_policy_problem_response(request, exc)
        return {**resolved, "prompt_binding": binding}

    @app.get(
        "/api/v1/runtime-policies/prompt-bindings/{binding_key}",
        response_model=None,
    )
    def get_runtime_policy_prompt_binding(
        binding_key: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        try:
            return resolve_safe_prompt_binding(prompt_store, binding_key=binding_key)
        except (RuntimePolicyApiError, PromptRepositoryError) as exc:
            return _runtime_policy_problem_response(request, exc)


def safe_runtime_policy_rule(rule: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_schema_version": rule["rule_schema_version"],
        "rule_id": rule["rule_id"],
        "rule_version": rule["rule_version"],
        "rule_hash": rule["rule_hash"],
        "status": rule["status"],
        "execution_mode": rule["execution_mode"],
        "template_ref": {
            "template_id": rule["template_id"],
            "template_version": rule["template_version"],
        },
        "prompt_contract_ref": {
            "prompt_binding_key": rule["prompt_binding_key"],
            "prompt_version": rule["prompt_version"],
        },
        "output_contract": {
            "output_contract_id": rule["output_contract_id"],
            "output_contract_version": rule["output_contract_version"],
            "artifact_intent": rule["artifact_intent"],
            "preferred_export_format": rule["preferred_export_format"],
        },
        "generation_profile": rule["generation_profile"],
        "provider_capability": rule["provider_capability"],
        "generation_parameters": dict(rule["generation_parameters"]),
        "quality_policy": dict(rule["quality_policy"]),
        "raw_prompt_included": False,
        "provider_runtime_included": False,
    }


def resolve_safe_prompt_binding(
    store: Any,
    *,
    binding_key: str,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    binding = store.get_binding(binding_key)
    if binding is None:
        raise RuntimePolicyApiError(
            404,
            "ae.prompt_binding_not_found",
            f"Active prompt binding was not found: {binding_key}",
        )
    if binding.get("status") != "ACTIVE":
        raise RuntimePolicyApiError(
            409,
            "ae.prompt_binding_inactive",
            f"Prompt binding is not active: {binding_key}",
        )

    version = store.get_template_version(binding["prompt_template_version_id"])
    if version is None:
        raise RuntimePolicyApiError(
            409,
            "ae.prompt_version_not_found",
            f"Bound prompt version was not found: {binding_key}",
        )
    if version.get("status") != "ACTIVE":
        raise RuntimePolicyApiError(
            409,
            "ae.prompt_version_inactive",
            f"Bound prompt version is not active: {binding_key}",
        )
    if prompt_version is not None and version.get("version") != prompt_version:
        raise RuntimePolicyApiError(
            409,
            "ae.prompt_version_mismatch",
            f"Prompt binding does not resolve to version {prompt_version}: {binding_key}",
        )

    return {
        "prompt_binding_projection_schema_version": (
            PROMPT_BINDING_PROJECTION_SCHEMA_VERSION
        ),
        "prompt_binding_id": binding["prompt_binding_id"],
        "binding_key": binding["binding_key"],
        "prompt_template_version_id": binding["prompt_template_version_id"],
        "service_id": binding["service_id"],
        "purpose": binding["purpose"],
        "status": binding["status"],
        "prompt_version": version["version"],
        "role": version["role"],
        "segment_order": version["segment_order"],
        "content_sha256": version["content_sha256"],
        "model_capability": version["model_capability"],
        "content_included": False,
    }


def _runtime_policy_problem_response(
    request: Request,
    exc: RuntimePolicyError | RuntimePolicyApiError | PromptRepositoryError,
) -> JSONResponse:
    status_code = getattr(exc, "status_code", 503)
    return problem_response(
        request,
        status_code=status_code,
        error_code=exc.error_code,
        title="AE runtime policy request failed",
        detail=exc.detail,
        retryable=getattr(exc, "retryable", False),
        type_uri="https://nex-platform.local/problems/ae-runtime-policy-request-failed",
    )
