from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_oa.identity_lifecycle import (
    OaIdentityLifecycleError,
    plan_subject_status_transition,
)
from nex_oa.identity_lifecycle_repository import OaIdentityLifecycleRepository
from nex_oa.subjects import OaSubjectRegistry, SubjectRegistryError
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_IDENTITY_LIFECYCLE_WRITE_SCOPE = "identity:lifecycle:write"
OA_SUBJECT_LIFECYCLE_RESPONSE_SCHEMA_VERSION = "oa_subject_lifecycle_response.v1"
_SUBJECT_TRANSITION_FIELDS = frozenset(
    ("target_status", "expected_revision", "reason_code")
)


@dataclass
class OaIdentityLifecycleService:
    subject_registry: OaSubjectRegistry
    repository: OaIdentityLifecycleRepository

    def transition_subject(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        payload: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        request = _normalize_subject_transition_payload(payload)
        try:
            snapshot = self.subject_registry.get_subject(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except SubjectRegistryError as exc:
            raise OaIdentityLifecycleError(
                status_code=exc.status_code,
                error_code=exc.error_code,
                detail=exc.detail,
            ) from exc
        if snapshot is None:
            raise OaIdentityLifecycleError(
                status_code=404,
                error_code="oa.lifecycle_target_not_found",
                detail="subject lifecycle target was not found.",
            )
        plan = plan_subject_status_transition(
            snapshot,
            target_status=request["target_status"],
            expected_revision=request["expected_revision"],
            reason_code=request.get("reason_code"),
        )
        result = self.repository.transition_subject(plan, context=context)
        return {
            "response_schema_version": OA_SUBJECT_LIFECYCLE_RESPONSE_SCHEMA_VERSION,
            **result,
        }


def register_identity_lifecycle_routes(
    app: FastAPI, *, service: OaIdentityLifecycleService
) -> None:
    @app.patch(
        "/internal/v1/identity/tenants/{tenant_id}/subjects/{subject_id}/lifecycle",
        response_model=None,
    )
    def transition_subject_lifecycle(
        tenant_id: str,
        subject_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        claims, auth_problem = _authorize_lifecycle_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        assert claims is not None
        context = {
            "actor_ref_type": "nex.service",
            "actor_ref_id": claims.service_id,
            "request_id": request_id_from_headers(request),
            "trace_id": trace_id_from_headers(request),
        }
        try:
            response = service.transition_subject(
                tenant_id=tenant_id,
                subject_id=subject_id,
                payload=payload,
                context=context,
            )
        except OaIdentityLifecycleError as exc:
            return _lifecycle_problem_response(request, exc)
        return {
            **response,
            "request_id": context["request_id"],
            "trace_id": context["trace_id"],
        }


def _normalize_subject_transition_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    unexpected = sorted(set(payload) - _SUBJECT_TRANSITION_FIELDS)
    if unexpected:
        raise OaIdentityLifecycleError(
            status_code=400,
            error_code="oa.lifecycle_payload_invalid",
            detail=f"unsupported lifecycle field: {unexpected[0]}",
        )
    missing = [
        field for field in ("target_status", "expected_revision") if field not in payload
    ]
    if missing:
        raise OaIdentityLifecycleError(
            status_code=400,
            error_code="oa.lifecycle_payload_invalid",
            detail=f"required lifecycle field is missing: {missing[0]}",
        )
    return dict(payload)


def _authorize_lifecycle_request(
    request: Request, authorization: str | None
) -> tuple[Any | None, JSONResponse | None]:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=[DEFAULT_SERVICE_SCOPE, OA_IDENTITY_LIFECYCLE_WRITE_SCOPE],
    )
    if result.ok:
        return result.claims, None
    status_code = 403 if result.error_code == "TOKEN_SCOPE_MISSING" else 401
    return None, problem_response(
        request,
        status_code=status_code,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authorization failed" if status_code == 403 else "Authentication failed",
        detail=result.detail or "OA lifecycle requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/identity-lifecycle-authorization",
    )


def _lifecycle_problem_response(
    request: Request, exc: OaIdentityLifecycleError
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Identity lifecycle request failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/identity-lifecycle-request-failed",
    )
