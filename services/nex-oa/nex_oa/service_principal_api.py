from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.service_principals import OaServicePrincipalError
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    OperationalEventEmitter,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_SERVICE_PRINCIPAL_READ_SCOPE = "service-principal:read"
OA_SERVICE_PRINCIPAL_ADMIN_SCOPE = "service-principal:admin"
_PRINCIPAL_FIELDS = frozenset(
    {
        "principal_id",
        "service_id",
        "display_name",
        "status",
        "allowed_audiences",
        "allowed_scopes",
        "expected_revision",
    }
)
_STATUS_FIELDS = frozenset({"target_status", "expected_revision"})
_ISSUE_FIELDS = frozenset({"lifetime_days"})
_ROTATE_FIELDS = frozenset(
    {"expected_revision", "lifetime_days", "grace_seconds"}
)


def register_service_principal_routes(
    app: FastAPI,
    *,
    service: OaServicePrincipalService,
    audit_emitter: OperationalEventEmitter,
) -> None:
    @app.post("/internal/v1/service-principals", response_model=None)
    def upsert_principal(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=True)
        if auth_problem is not None:
            return auth_problem
        try:
            result = service.upsert_principal(
                _payload(payload, allowed=_PRINCIPAL_FIELDS, required=(
                    "principal_id", "service_id", "display_name",
                    "allowed_audiences", "allowed_scopes", "expected_revision",
                ))
            )
        except OaServicePrincipalError as exc:
            return _problem(request, exc)
        return _with_audit(
            result,
            request=request,
            emitter=audit_emitter,
            event_type="SERVICE_PRINCIPAL_UPSERTED",
            subject_type="oa.service_principal",
            subject_id=result["principal"]["principal_id"],
            details={"status": result["principal"]["status"]},
        )

    @app.get("/internal/v1/service-principals", response_model=None)
    def list_principals(
        request: Request,
        service_id: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=False)
        if auth_problem is not None:
            return auth_problem
        try:
            return _with_context(
                service.list_principals(service_id=service_id), request
            )
        except OaServicePrincipalError as exc:
            return _problem(request, exc)

    @app.get("/internal/v1/service-principals/{principal_id}", response_model=None)
    def get_principal(
        principal_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=False)
        if auth_problem is not None:
            return auth_problem
        try:
            return _with_context(service.get_principal(principal_id), request)
        except OaServicePrincipalError as exc:
            return _problem(request, exc)

    @app.patch(
        "/internal/v1/service-principals/{principal_id}/status",
        response_model=None,
    )
    def set_principal_status(
        principal_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=True)
        if auth_problem is not None:
            return auth_problem
        try:
            body = _payload(
                payload,
                allowed=_STATUS_FIELDS,
                required=("target_status", "expected_revision"),
            )
            result = service.set_principal_status(
                principal_id,
                target_status=body["target_status"],
                expected_revision=body["expected_revision"],
            )
        except OaServicePrincipalError as exc:
            return _problem(request, exc)
        return _with_audit(
            result,
            request=request,
            emitter=audit_emitter,
            event_type="SERVICE_PRINCIPAL_STATUS_CHANGED",
            subject_type="oa.service_principal",
            subject_id=result["principal"]["principal_id"],
            details={"status": result["principal"]["status"]},
        )

    @app.post(
        "/internal/v1/service-principals/{principal_id}/credentials",
        response_model=None,
    )
    def issue_credential(
        principal_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=True)
        if auth_problem is not None:
            return auth_problem
        try:
            body = _payload(
                payload, allowed=_ISSUE_FIELDS, required=("lifetime_days",)
            )
            result = service.issue_credential(
                principal_id, lifetime_days=body["lifetime_days"]
            )
        except OaServicePrincipalError as exc:
            return _problem(request, exc)
        return _with_audit(
            result,
            request=request,
            emitter=audit_emitter,
            event_type="SERVICE_CREDENTIAL_ISSUED",
            subject_type="oa.service_credential",
            subject_id=result["credential"]["credential_id"],
            details={"status": result["credential"]["status"]},
        )

    @app.get(
        "/internal/v1/service-principals/{principal_id}/credentials",
        response_model=None,
    )
    def list_credentials(
        principal_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=False)
        if auth_problem is not None:
            return auth_problem
        try:
            return _with_context(service.list_credentials(principal_id), request)
        except OaServicePrincipalError as exc:
            return _problem(request, exc)

    @app.get("/internal/v1/service-credentials/{credential_id}", response_model=None)
    def get_credential(
        credential_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=False)
        if auth_problem is not None:
            return auth_problem
        try:
            return _with_context(service.get_credential(credential_id), request)
        except OaServicePrincipalError as exc:
            return _problem(request, exc)

    @app.post(
        "/internal/v1/service-credentials/{credential_id}/rotate",
        response_model=None,
    )
    def rotate_credential(
        credential_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=True)
        if auth_problem is not None:
            return auth_problem
        try:
            body = _payload(
                payload,
                allowed=_ROTATE_FIELDS,
                required=("expected_revision", "lifetime_days", "grace_seconds"),
            )
            result = service.rotate_credential(
                credential_id,
                expected_revision=body["expected_revision"],
                lifetime_days=body["lifetime_days"],
                grace_seconds=body["grace_seconds"],
            )
        except OaServicePrincipalError as exc:
            return _problem(request, exc)
        return _with_audit(
            result,
            request=request,
            emitter=audit_emitter,
            event_type="SERVICE_CREDENTIAL_ROTATED",
            subject_type="oa.service_credential",
            subject_id=result["credential"]["credential_id"],
            details={"status": result["credential"]["status"]},
        )

    @app.patch(
        "/internal/v1/service-credentials/{credential_id}/status",
        response_model=None,
    )
    def set_credential_status(
        credential_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize(request, authorization, write=True)
        if auth_problem is not None:
            return auth_problem
        try:
            body = _payload(
                payload,
                allowed=_STATUS_FIELDS,
                required=("target_status", "expected_revision"),
            )
            result = service.set_credential_status(
                credential_id,
                target_status=body["target_status"],
                expected_revision=body["expected_revision"],
            )
        except OaServicePrincipalError as exc:
            return _problem(request, exc)
        return _with_audit(
            result,
            request=request,
            emitter=audit_emitter,
            event_type="SERVICE_CREDENTIAL_STATUS_CHANGED",
            subject_type="oa.service_credential",
            subject_id=result["credential"]["credential_id"],
            details={"status": result["credential"]["status"]},
        )


def _authorize(
    request: Request,
    authorization: str | None,
    *,
    write: bool,
) -> JSONResponse | None:
    scope = OA_SERVICE_PRINCIPAL_ADMIN_SCOPE if write else OA_SERVICE_PRINCIPAL_READ_SCOPE
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=(DEFAULT_SERVICE_SCOPE, scope),
    )
    if result.ok:
        return None
    status = 403 if result.error_code == "TOKEN_SCOPE_MISSING" else 401
    return problem_response(
        request,
        status_code=status,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authorization failed" if status == 403 else "Authentication failed",
        detail=result.detail or "service-principal access requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/service-principal-authorization",
    )


def _payload(
    payload: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    required: tuple[str, ...],
) -> dict[str, Any]:
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise OaServicePrincipalError(
            400,
            "oa.service_principal_payload_invalid",
            f"unsupported field: {unexpected[0]}",
        )
    missing = [field for field in required if field not in payload]
    if missing:
        raise OaServicePrincipalError(
            400,
            "oa.service_principal_payload_invalid",
            f"required field is missing: {missing[0]}",
        )
    return dict(payload)


def _with_context(result: Mapping[str, Any], request: Request) -> dict[str, Any]:
    return {
        **result,
        "request_id": request_id_from_headers(request),
        "trace_id": trace_id_from_headers(request),
    }


def _with_audit(
    result: Mapping[str, Any],
    *,
    request: Request,
    emitter: OperationalEventEmitter,
    event_type: str,
    subject_type: str,
    subject_id: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    request_id = request_id_from_headers(request)
    trace_id = trace_id_from_headers(request)
    audit = emitter.safe_emit(
        event_type=event_type,
        severity="INFO",
        message="OA service-principal lifecycle mutation",
        request_id=request_id,
        trace_id=trace_id,
        subject_ref={"type": subject_type, "id": subject_id},
        details=details,
    )
    return {
        **result,
        "request_id": request_id,
        "trace_id": trace_id,
        "audit_event": audit.to_summary(),
    }


def _problem(request: Request, exc: OaServicePrincipalError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Service-principal lifecycle request failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/service-principal-lifecycle",
    )
