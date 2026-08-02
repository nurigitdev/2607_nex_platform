from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime.auth import DEFAULT_SERVICE_SCOPE, validate_authorization_header
from nex_runtime.problem import problem_response


@dataclass(frozen=True)
class GenerationRecoveryPolicyError(Exception):
    status_code: int
    error_code: str
    detail: str


DEFAULT_GENERATION_RECOVERY_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "recovery_policy_schema_version": "generation_recovery_policy.v1",
        "recovery_policy_id": "recovery-mo-provider-timeout-retry-v1",
        "status": "ACTIVE",
        "failure_code": "mo.provider_timeout",
        "failure_class": "provider_timeout",
        "owner_service": "nex-cx",
        "default_action": "retry",
        "allowed_actions": ["retry", "cancel"],
        "retryable": True,
        "max_attempts": 2,
        "retry_after_seconds": 5,
        "lineage_type": "retry",
        "preserves_retrieval_package": True,
        "preserves_artifact_source_hash": True,
        "changed_fields_allowed": [],
        "progress_event_types": [
            "generation.failed",
            "generation.retry.scheduled",
        ],
        "operator_override_allowed": False,
        "metadata": {
            "slice": "0046",
            "owner": "cx-mo-recovery",
        },
    },
    {
        "recovery_policy_schema_version": "generation_recovery_policy.v1",
        "recovery_policy_id": "recovery-citation-validation-repair-v1",
        "status": "ACTIVE",
        "failure_code": "cx.citation_validation_failed",
        "failure_class": "citation_validation_failed",
        "owner_service": "nex-cx",
        "default_action": "repair",
        "allowed_actions": ["repair", "sectional_retry", "regenerate", "cancel"],
        "retryable": True,
        "max_attempts": 1,
        "retry_after_seconds": None,
        "lineage_type": "repair",
        "preserves_retrieval_package": True,
        "preserves_artifact_source_hash": True,
        "changed_fields_allowed": ["citation_map", "section_blocks"],
        "progress_event_types": [
            "generation.failed",
            "generation.repair.started",
            "generation.repair.completed",
        ],
        "operator_override_allowed": False,
        "metadata": {
            "slice": "0046",
            "owner": "cx-validation-recovery",
        },
    },
    {
        "recovery_policy_schema_version": "generation_recovery_policy.v1",
        "recovery_policy_id": "recovery-ae-render-failed-retry-v1",
        "status": "ACTIVE",
        "failure_code": "ae.render_job_failed",
        "failure_class": "artifact_render_failed",
        "owner_service": "nex-ae-api",
        "default_action": "retry",
        "allowed_actions": ["retry", "cancel"],
        "retryable": True,
        "max_attempts": 2,
        "retry_after_seconds": 0,
        "lineage_type": "retry",
        "preserves_retrieval_package": True,
        "preserves_artifact_source_hash": True,
        "changed_fields_allowed": ["render_policy"],
        "progress_event_types": [
            "generation.failed",
            "generation.retry.scheduled",
        ],
        "operator_override_allowed": False,
        "metadata": {
            "slice": "0046",
            "owner": "ae-artifact-recovery",
        },
    },
    {
        "recovery_policy_schema_version": "generation_recovery_policy.v1",
        "recovery_policy_id": "recovery-low-confidence-fresh-retrieval-v1",
        "status": "ACTIVE",
        "failure_code": "cx.low_confidence_generation_blocked",
        "failure_class": "low_confidence",
        "owner_service": "nex-ae-api",
        "default_action": "fresh_retrieval_regenerate",
        "allowed_actions": [
            "fresh_retrieval_regenerate",
            "manual_accept_with_warning",
            "cancel",
        ],
        "retryable": False,
        "max_attempts": 0,
        "retry_after_seconds": None,
        "lineage_type": "fresh_retrieval_regenerate",
        "preserves_retrieval_package": False,
        "preserves_artifact_source_hash": False,
        "changed_fields_allowed": ["retrieval_scope", "quality_policy"],
        "progress_event_types": [
            "generation.failed",
            "generation.regenerate.started",
            "generation.manual_accept_with_warning",
        ],
        "operator_override_allowed": True,
        "metadata": {
            "slice": "0046",
            "owner": "ae-quality-recovery",
        },
    },
)


def register_generation_recovery_policy_routes(
    app: FastAPI,
    *,
    expected_audience: str,
    policies: tuple[dict[str, Any], ...] = DEFAULT_GENERATION_RECOVERY_POLICIES,
) -> None:
    @app.get("/api/v1/recovery/generation-policies", response_model=None)
    def list_generation_recovery_policies(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_request(
            request,
            authorization,
            expected_audience=expected_audience,
        )
        if auth_problem is not None:
            return auth_problem
        return {"policies": list(policies)}

    @app.get(
        "/api/v1/recovery/generation-policies/{failure_code}",
        response_model=None,
    )
    def get_generation_recovery_policy(
        failure_code: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_request(
            request,
            authorization,
            expected_audience=expected_audience,
        )
        if auth_problem is not None:
            return auth_problem
        try:
            return select_generation_recovery_policy(failure_code, policies=policies)
        except GenerationRecoveryPolicyError as exc:
            return _recovery_problem_response(request, exc)


def select_generation_recovery_policy(
    failure_code: str,
    *,
    policies: tuple[dict[str, Any], ...] = DEFAULT_GENERATION_RECOVERY_POLICIES,
) -> dict[str, Any]:
    if not isinstance(failure_code, str) or not failure_code.strip():
        raise GenerationRecoveryPolicyError(
            status_code=400,
            error_code="generation.recovery_failure_code_invalid",
            detail="failure_code must be a non-empty string.",
        )
    normalized_failure_code = failure_code.strip()
    for policy in policies:
        if policy.get("status") != "ACTIVE":
            continue
        if policy["failure_code"] == normalized_failure_code:
            return policy
    raise GenerationRecoveryPolicyError(
        status_code=404,
        error_code="generation.recovery_policy_not_found",
        detail=f"No active recovery policy matched {normalized_failure_code}.",
    )


def recovery_policy_hash(policy: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def recovery_action_allowed(policy: dict[str, Any], action: str) -> bool:
    return action in policy.get("allowed_actions", [])


def _authorize_request(
    request: Request,
    authorization: str | None,
    *,
    expected_audience: str,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience=expected_audience,
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or f"{expected_audience} requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _recovery_problem_response(
    request: Request,
    exc: GenerationRecoveryPolicyError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Generation recovery policy failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/generation-recovery-policy-failed",
    )
