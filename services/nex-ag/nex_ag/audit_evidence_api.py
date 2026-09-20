from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_ag.audit_correlation import build_audit_correlation_continuity_report
from nex_ag.audit_evidence_package import (
    AuditEvidencePackageError,
    build_audit_evidence_package,
    verify_audit_evidence_package,
)
from nex_ag.audit_evidence_operations import (
    AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
    AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
    build_audit_evidence_operations_projection,
)
from nex_ag.audit_integrity import (
    MAX_AUDIT_INTEGRITY_EVENTS,
    AuditIntegrityError,
    build_audit_event_integrity_report,
)
from nex_ag.operator_reviews import OperatorReviewNoteError
from nex_ag.resilience_performance import AgStablePaginationError
from nex_ag.resilience_performance import (
    AgAdmissionRejectedError,
    AgConcurrencyAdmissionGuard,
    AgSourceIsolationExecutor,
    build_ag_concurrency_admission_guard,
    build_ag_source_isolation_executor,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    OperationalEventEmitter,
    OperationalEventStore,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
    validate_user_authorization_header,
)


AUDIT_EVIDENCE_PACKAGE_RESPONSE_SCHEMA_VERSION = (
    "ag_audit_evidence_package_response.v1"
)
AUDIT_EVIDENCE_VERIFY_RESPONSE_SCHEMA_VERSION = (
    "ag_audit_evidence_verify_response.v1"
)
_CREATE_FIELDS = {"trace_id", "expected_event_ids", "required_event_types"}


@dataclass(frozen=True)
class AuditEvidenceApiError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


class AuditEvidencePackageService:
    def __init__(
        self,
        *,
        event_store: OperationalEventStore,
        export_store: Any,
    ) -> None:
        self._event_store = event_store
        self._export_store = export_store

    def create_package(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str,
        request_trace_id: str | None,
    ) -> dict[str, Any]:
        normalized = _create_payload(payload)
        source_trace_id = normalized["trace_id"]
        events = self._event_store.list_events(
            trace_id=source_trace_id,
            limit=MAX_AUDIT_INTEGRITY_EVENTS,
        )
        exports = self._export_store.list_exports(
            trace_id=source_trace_id,
            limit=MAX_AUDIT_INTEGRITY_EVENTS,
        )
        integrity = build_audit_event_integrity_report(
            events,
            expected_event_ids=normalized["expected_event_ids"],
        )
        correlation = build_audit_correlation_continuity_report(
            events,
            evidence_exports=exports,
            expected_event_ids=normalized["expected_event_ids"],
            expected_trace_ids=[source_trace_id],
            required_event_types=normalized["required_event_types"],
        )
        package = build_audit_evidence_package(
            integrity_report=integrity,
            correlation_report=correlation,
            evidence_exports=exports,
        )
        verification = verify_audit_evidence_package(package)
        return {
            "response_schema_version": (
                AUDIT_EVIDENCE_PACKAGE_RESPONSE_SCHEMA_VERSION
            ),
            "request_id": request_id,
            "request_trace_id": request_trace_id,
            "source_trace_id": source_trace_id,
            "selection": {
                "server_selected": True,
                "event_count": len(events),
                "evidence_export_count": len(exports),
                "expected_event_count": len(normalized["expected_event_ids"]),
                "required_event_type_count": len(
                    normalized["required_event_types"]
                ),
            },
            "package": package,
            "verification": verification,
        }

    def verify_package(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str,
        request_trace_id: str | None,
    ) -> dict[str, Any]:
        if set(payload) != {"package"}:
            raise AuditEvidenceApiError(
                error_code="ag.audit_evidence.verify_payload_invalid",
                detail="Verification payload must contain only package.",
            )
        verification = verify_audit_evidence_package(payload["package"])
        return {
            "response_schema_version": (
                AUDIT_EVIDENCE_VERIFY_RESPONSE_SCHEMA_VERSION
            ),
            "request_id": request_id,
            "request_trace_id": request_trace_id,
            "verification": verification,
        }


def register_audit_evidence_routes(
    app: FastAPI,
    *,
    event_store: OperationalEventStore,
    export_store: Any,
    audit_event_store: OperationalEventStore | None = None,
    admission_guard: AgConcurrencyAdmissionGuard | None = None,
    source_executor: AgSourceIsolationExecutor | None = None,
) -> None:
    service = AuditEvidencePackageService(
        event_store=event_store,
        export_store=export_store,
    )
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=audit_event_store or event_store,
    )
    selected_admission_guard = (
        admission_guard or build_ag_concurrency_admission_guard()
    )
    selected_source_executor = (
        source_executor or build_ag_source_isolation_executor()
    )

    @app.get("/admin/v1/operations/audit-integrity", response_model=None)
    def get_audit_evidence_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        recent_limit: int = 5,
        cursor: str | None = None,
    ):
        auth_problem = _authorize_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            with selected_admission_guard.admit("audit_integrity_read"):
                return build_audit_evidence_operations_projection(
                    event_store=event_store,
                    export_store=export_store,
                    service_id=service_id,
                    recent_limit=recent_limit,
                    action_cursor=cursor,
                    source_executor=selected_source_executor,
                    request_trace_id=trace_id_from_headers(request),
                )
        except (AgStablePaginationError, AgAdmissionRejectedError) as exc:
            return _problem_response(request, exc)

    @app.post("/admin/v1/audit-integrity/evidence-packages", response_model=None)
    def create_audit_evidence_package(
        request: Request,
        authorization: str | None = Header(default=None),
        payload: dict[str, Any] = Body(...),
    ):
        auth_problem = _authorize_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            with selected_admission_guard.admit("audit_evidence_create"):
                response = service.create_package(
                    payload,
                    request_id=request_id_from_headers(request),
                    request_trace_id=trace_id_from_headers(request),
                )
        except (
            AgAdmissionRejectedError,
            AuditEvidenceApiError,
            AuditEvidencePackageError,
            AuditIntegrityError,
            OperatorReviewNoteError,
        ) as exc:
            return _problem_response(request, exc)
        package = response["package"]
        audit_emitter.safe_emit(
            event_type=AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
            severity="INFO",
            message="AG audit evidence package generated.",
            trace_id=trace_id_from_headers(request),
            request_id=request_id_from_headers(request),
            subject_ref={
                "type": "audit_evidence_package",
                "id": package["package_id"],
            },
            details={
                "package_id": package["package_id"],
                "package_hash": package["package_hash"],
                "verification_status": package["verification_status"],
                "source_trace_id": response["source_trace_id"],
                "event_count": response["selection"]["event_count"],
                "evidence_export_count": response["selection"][
                    "evidence_export_count"
                ],
            },
        )
        return response

    @app.post(
        "/admin/v1/audit-integrity/evidence-packages/verify",
        response_model=None,
    )
    def verify_audit_evidence_package_route(
        request: Request,
        authorization: str | None = Header(default=None),
        payload: dict[str, Any] = Body(...),
    ):
        auth_problem = _authorize_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            with selected_admission_guard.admit("audit_evidence_verify"):
                response = service.verify_package(
                    payload,
                    request_id=request_id_from_headers(request),
                    request_trace_id=trace_id_from_headers(request),
                )
        except (AgAdmissionRejectedError, AuditEvidenceApiError) as exc:
            return _problem_response(request, exc)
        verification = response["verification"]
        audit_emitter.safe_emit(
            event_type=AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
            severity=(
                "INFO"
                if verification["verification_status"] == "VERIFIED"
                else "WARNING"
            ),
            message="AG audit evidence package verification completed.",
            trace_id=trace_id_from_headers(request),
            request_id=request_id_from_headers(request),
            subject_ref={
                "type": "audit_evidence_package",
                "id": str(verification.get("package_id") or "unknown"),
            },
            details={
                "package_id": verification.get("package_id"),
                "verification_status": verification["verification_status"],
                "issue_count": verification["issue_count"],
            },
        )
        return response


def _create_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(payload) - _CREATE_FIELDS)
    if unknown:
        raise AuditEvidenceApiError(
            error_code="ag.audit_evidence.create_fields_unsupported",
            detail=f"Unsupported create fields: {', '.join(unknown)}",
        )
    trace_id = _required_text(payload.get("trace_id"), "trace_id")
    return {
        "trace_id": trace_id,
        "expected_event_ids": _text_list(
            payload.get("expected_event_ids"),
            "expected_event_ids",
        ),
        "required_event_types": _text_list(
            payload.get("required_event_types"),
            "required_event_types",
        ),
    }


def _text_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AuditEvidenceApiError(
            error_code=f"ag.audit_evidence.{field}_invalid",
            detail=f"{field} must be a list when supplied.",
        )
    result: list[str] = []
    for item in value:
        normalized = _optional_text(item)
        if normalized is None:
            raise AuditEvidenceApiError(
                error_code=f"ag.audit_evidence.{field}_item_invalid",
                detail=f"{field} items must be non-empty strings.",
            )
        if normalized not in result:
            result.append(normalized)
    return sorted(result)


def _required_text(value: object, field: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise AuditEvidenceApiError(
            error_code=f"ag.audit_evidence.{field}_required",
            detail=f"{field} is required.",
        )
    return normalized


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _authorize_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    service_result = validate_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if service_result.ok:
        return None
    user_result = validate_user_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_USER_SCOPE],
    )
    if user_result.ok:
        roles = set(user_result.claims.roles if user_result.claims else ())
        if "admin" in roles:
            return None
        return problem_response(
            request,
            status_code=403,
            error_code="AG_AUDIT_EVIDENCE_ADMIN_ROLE_REQUIRED",
            title="Authorization failed",
            detail="AG audit evidence routes require an admin user role.",
            type_uri="https://nex-platform.local/problems/authorization-failed",
        )
    return problem_response(
        request,
        status_code=401,
        error_code=service_result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=service_result.detail or "AG requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _problem_response(
    request: Request,
    exc: AuditEvidenceApiError
    | AuditEvidencePackageError
    | AuditIntegrityError
    | OperatorReviewNoteError
    | AgStablePaginationError
    | AgAdmissionRejectedError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Audit evidence request rejected",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/audit-evidence-rejected",
    )


__all__ = [
    "AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE",
    "AUDIT_EVIDENCE_PACKAGE_RESPONSE_SCHEMA_VERSION",
    "AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE",
    "AUDIT_EVIDENCE_VERIFY_RESPONSE_SCHEMA_VERSION",
    "AuditEvidenceApiError",
    "AuditEvidencePackageService",
    "register_audit_evidence_routes",
]
