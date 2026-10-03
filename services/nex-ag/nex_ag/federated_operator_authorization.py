from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_ag.federated_operator_context import (
    AG_FEDERATED_OPERATOR_CONTEXT_HEADER,
    AgFederatedOperatorContext,
    AgFederatedOperatorContextError,
    adopt_ag_federated_operator_context,
    decode_ag_federated_operator_context_header,
)
from nex_runtime import AdmittedServiceClaims, DEFAULT_USER_SCOPE, problem_response


AG_FEDERATED_AUTHORIZATION_AUDIT_STATE_KEY = (
    "ag_federated_operator_authorization_audit"
)
AG_FEDERATED_AUTHORIZATION_TELEMETRY_STATE_KEY = (
    "ag_federated_operator_authorization_telemetry"
)
AG_FEDERATED_OPERATOR_CALLER = "nex-ae-api"
_TELEMETRY_KEYS = (
    "authorized",
    "denied_caller",
    "denied_context",
    "denied_scope",
    "denied_role",
)


@dataclass(frozen=True)
class AgFederatedAuthorizationAudit:
    outcome: str
    reason_code: str
    caller_service_id: str | None
    tenant_id: str | None
    subject_id: str | None
    auth_method: str | None
    session_id_digest: str | None
    required_role: str = "admin"
    required_scope: str = DEFAULT_USER_SCOPE
    raw_context_included: bool = False
    external_identity_included: bool = False

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


class AgFederatedAuthorizationTelemetry:
    def __init__(self) -> None:
        self._counts = {name: 0 for name in _TELEMETRY_KEYS}
        self._lock = Lock()

    def record(self, outcome: str) -> None:
        if outcome not in self._counts:
            raise ValueError("unsupported federated authorization outcome")
        with self._lock:
            self._counts[outcome] += 1

    def public_snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts = dict(self._counts)
        return {
            "runtime_schema_version": "ag_federated_auth_runtime.v1",
            "service_id": "nex-ag",
            "context_source": "oa_normalized_via_nex_ae_api",
            "required_role": "admin",
            "required_scope": DEFAULT_USER_SCOPE,
            "counts": counts,
            "raw_context_included": False,
            "subject_identifiers_included": False,
            "external_identity_included": False,
        }


def authorize_ag_federated_operator_context(
    request: Request,
    *,
    service_claims: AdmittedServiceClaims,
    encoded_context: object,
    admin_error_code: str,
    admin_error_detail: str,
    telemetry: AgFederatedAuthorizationTelemetry | None = None,
) -> JSONResponse | None:
    if service_claims.service_id != AG_FEDERATED_OPERATOR_CALLER:
        _record_audit(
            request,
            outcome="DENIED",
            reason_code="AG_FEDERATED_OPERATOR_CALLER_FORBIDDEN",
            caller_service_id=service_claims.service_id,
        )
        _record_telemetry(telemetry, "denied_caller")
        return _problem(
            request,
            status_code=403,
            error_code="AG_FEDERATED_OPERATOR_CALLER_FORBIDDEN",
            detail="Federated operator context requires the AE facade caller.",
        )
    try:
        context = decode_ag_federated_operator_context_header(encoded_context)
    except AgFederatedOperatorContextError:
        _record_audit(
            request,
            outcome="DENIED",
            reason_code="AG_FEDERATED_OPERATOR_CONTEXT_INVALID",
            caller_service_id=service_claims.service_id,
        )
        _record_telemetry(telemetry, "denied_context")
        return _problem(
            request,
            status_code=401,
            error_code="AG_FEDERATED_OPERATOR_CONTEXT_INVALID",
            detail="Federated operator context is invalid.",
        )
    if DEFAULT_USER_SCOPE not in context.scopes:
        _record_context_audit(
            request,
            context=context,
            caller_service_id=service_claims.service_id,
            outcome="DENIED",
            reason_code="AG_FEDERATED_OPERATOR_SCOPE_REQUIRED",
        )
        _record_telemetry(telemetry, "denied_scope")
        return _problem(
            request,
            status_code=403,
            error_code="AG_FEDERATED_OPERATOR_SCOPE_REQUIRED",
            detail="Federated operator context lacks the required scope.",
        )
    if "admin" not in context.roles:
        _record_context_audit(
            request,
            context=context,
            caller_service_id=service_claims.service_id,
            outcome="DENIED",
            reason_code=admin_error_code,
        )
        _record_telemetry(telemetry, "denied_role")
        return _problem(
            request,
            status_code=403,
            error_code=admin_error_code,
            detail=admin_error_detail,
        )
    adopt_ag_federated_operator_context(request, context.to_wire())
    _record_context_audit(
        request,
        context=context,
        caller_service_id=service_claims.service_id,
        outcome="AUTHORIZED",
        reason_code="AG_FEDERATED_OPERATOR_AUTHORIZED",
    )
    _record_telemetry(telemetry, "authorized")
    return None


def ag_federated_authorization_audit_from_request(
    request: Request,
) -> AgFederatedAuthorizationAudit | None:
    audit = getattr(
        request.state,
        AG_FEDERATED_AUTHORIZATION_AUDIT_STATE_KEY,
        None,
    )
    return audit if isinstance(audit, AgFederatedAuthorizationAudit) else None


def federated_operator_context_header(request: Request) -> str | None:
    return request.headers.get(AG_FEDERATED_OPERATOR_CONTEXT_HEADER)


def federated_authorization_telemetry_from_request(
    request: Request,
) -> AgFederatedAuthorizationTelemetry | None:
    telemetry = getattr(
        request.app.state,
        AG_FEDERATED_AUTHORIZATION_TELEMETRY_STATE_KEY,
        None,
    )
    return telemetry if isinstance(telemetry, AgFederatedAuthorizationTelemetry) else None


def _record_context_audit(
    request: Request,
    *,
    context: AgFederatedOperatorContext,
    caller_service_id: str,
    outcome: str,
    reason_code: str,
) -> None:
    _record_audit(
        request,
        outcome=outcome,
        reason_code=reason_code,
        caller_service_id=caller_service_id,
        tenant_id=context.tenant_id,
        subject_id=context.subject_id,
        auth_method=context.auth_method,
        session_id_digest=context.session_id_digest,
    )


def _record_audit(
    request: Request,
    *,
    outcome: str,
    reason_code: str,
    caller_service_id: str | None,
    tenant_id: str | None = None,
    subject_id: str | None = None,
    auth_method: str | None = None,
    session_id_digest: str | None = None,
) -> None:
    setattr(
        request.state,
        AG_FEDERATED_AUTHORIZATION_AUDIT_STATE_KEY,
        AgFederatedAuthorizationAudit(
            outcome=outcome,
            reason_code=reason_code,
            caller_service_id=caller_service_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            auth_method=auth_method,
            session_id_digest=session_id_digest,
        ),
    )


def _record_telemetry(
    telemetry: AgFederatedAuthorizationTelemetry | None,
    outcome: str,
) -> None:
    if telemetry is not None:
        telemetry.record(outcome)


def _problem(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    detail: str,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=status_code,
        error_code=error_code,
        title="Federated operator authorization failed",
        detail=detail,
        type_uri=(
            "https://nex-platform.local/problems/"
            "federated-operator-authorization-failed"
        ),
    )
