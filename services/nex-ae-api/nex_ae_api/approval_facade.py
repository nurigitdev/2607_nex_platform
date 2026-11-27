from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_runtime.semantic_hashes import validate_hash_ref

from nex_ae_api.approval_projection import (
    ApprovalProjectionError,
    build_user_approval_projection,
)
from nex_ae_api.oa_session_client import OaUserSessionClient
from nex_ae_api.route_auth import (
    AeFacadeRouteAuthContext,
    authorize_ae_facade_route_request,
)
from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

DEFAULT_WC_APPROVAL_BASE_URL = (
    f"http://127.0.0.1:{SERVICE_SPECS['nex-wc'].default_port}"
)
DEFAULT_EOS_ACCOUNTING_BASE_URL = (
    f"http://127.0.0.1:{SERVICE_SPECS['nex-eos'].default_port}"
)


class WcApprovalClient(Protocol):
    def list_gates(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> Mapping[str, Any]: ...

    def get_gate(
        self,
        approval_work_item_id: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> Mapping[str, Any]: ...

    def decide_gate(
        self,
        approval_work_item_id: str,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> tuple[Mapping[str, Any], int]: ...


class EosAccountingDisplayClient(Protocol):
    def get_case_display(
        self,
        case_id: str,
        *,
        tenant_id: str,
        request_id: str,
        trace_id: str,
    ) -> Mapping[str, Any]: ...

    def get_candidate_display(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        expected_hash: str,
        tenant_id: str,
        request_id: str,
        trace_id: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ApprovalFacadeError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpWcApprovalClient:
    base_url: str = DEFAULT_WC_APPROVAL_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 15.0

    def list_gates(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> Mapping[str, Any]:
        body = self._request(
            "GET",
            "/api/v1/approval-gates",
            tenant_id=tenant_id,
            subject_id=subject_id,
            request_id=request_id,
            trace_id=trace_id,
            params={"limit": limit},
        )[0]
        _require_safe_approval_inbox(body)
        return body

    def get_gate(
        self,
        approval_work_item_id: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> Mapping[str, Any]:
        body = self._request(
            "GET",
            f"/api/v1/approval-gates/{approval_work_item_id}",
            tenant_id=tenant_id,
            subject_id=subject_id,
            request_id=request_id,
            trace_id=trace_id,
        )[0]
        _require_safe_approval_detail(body)
        return body

    def decide_gate(
        self,
        approval_work_item_id: str,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
    ) -> tuple[Mapping[str, Any], int]:
        body, status_code = self._request(
            "POST",
            f"/api/v1/approval-gates/{approval_work_item_id}/decisions",
            tenant_id=tenant_id,
            subject_id=subject_id,
            request_id=request_id,
            trace_id=trace_id,
            json=dict(payload),
        )
        _require_safe_approval_decision(body)
        return body, status_code

    def _request(
        self,
        method: str,
        path: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> tuple[Mapping[str, Any], int]:
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-wc",
            )
            response = httpx.request(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-NeX-Tenant-Id": tenant_id,
                    "X-NeX-Subject-Id": subject_id,
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ae-api",
                },
                params=params,
                json=json,
                timeout=self.timeout_seconds,
            )
        except (httpx.HTTPError, AeOutboundServiceTokenError) as exc:
            raise ApprovalFacadeError(
                503,
                "ae.wc_approval_unavailable",
                "WC approval service is unavailable.",
                True,
            ) from exc

        body = _safe_response_json(response)
        if response.status_code >= 400:
            problem = body or {}
            raise ApprovalFacadeError(
                response.status_code,
                str(problem.get("error_code") or "ae.wc_approval_request_failed"),
                str(problem.get("detail") or "WC approval request failed."),
                bool(problem.get("retryable", response.status_code >= 500)),
            )
        if body is None:
            raise ApprovalFacadeError(
                502,
                "ae.wc_approval_response_invalid",
                "WC approval response is invalid.",
                True,
            )
        return dict(body), response.status_code


def build_default_wc_approval_client() -> HttpWcApprovalClient:
    return HttpWcApprovalClient(
        base_url=os.getenv("NEX_WC_BASE_URL", DEFAULT_WC_APPROVAL_BASE_URL),
        service_token=os.getenv("NEX_AE_TO_WC_SERVICE_TOKEN"),
    )


@dataclass(frozen=True)
class HttpEosAccountingDisplayClient:
    base_url: str = DEFAULT_EOS_ACCOUNTING_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 15.0

    def get_case_display(self, case_id: str, **context) -> Mapping[str, Any]:
        return self._request(
            f"/internal/v2/finance/accounting-approval-cases/{case_id}/display",
            **context,
        )

    def get_candidate_display(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        expected_hash: str,
        **context,
    ) -> Mapping[str, Any]:
        return self._request(
            f"/internal/v2/finance/voucher-candidates/{candidate_id}/accounting-display",
            params={
                "expected_revision": expected_revision,
                "expected_hash": expected_hash,
            },
            **context,
        )

    def _request(
        self,
        path: str,
        *,
        tenant_id: str,
        request_id: str,
        trace_id: str,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-eos",
            )
            response = httpx.get(
                f"{self.base_url.rstrip('/')}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-NeX-Tenant-Id": tenant_id,
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ae-api",
                },
                params=params,
                timeout=self.timeout_seconds,
            )
        except (httpx.HTTPError, AeOutboundServiceTokenError) as exc:
            raise ApprovalFacadeError(
                503,
                "ae.eos_accounting_display_unavailable",
                "EOS accounting display service is unavailable.",
                True,
            ) from exc
        body = _safe_response_json(response)
        if response.status_code >= 400:
            raise ApprovalFacadeError(
                response.status_code,
                "ae.eos_accounting_display_rejected",
                "EOS accounting display request was rejected.",
                response.status_code >= 500,
            )
        if body is None:
            raise ApprovalFacadeError(
                502,
                "ae.eos_accounting_display_invalid",
                "EOS accounting display response is invalid.",
                True,
            )
        _require_safe_accounting_document(body)
        return dict(body)


def build_default_eos_accounting_display_client() -> HttpEosAccountingDisplayClient:
    return HttpEosAccountingDisplayClient(
        base_url=os.getenv(
            "NEX_EOS_BASE_URL",
            DEFAULT_EOS_ACCOUNTING_BASE_URL,
        ),
        service_token=os.getenv("NEX_AE_TO_EOS_SERVICE_TOKEN"),
    )


def register_approval_facade_routes(
    app: FastAPI,
    *,
    wc_client: WcApprovalClient | None = None,
    eos_accounting_client: EosAccountingDisplayClient | None = None,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> None:
    client = wc_client or build_default_wc_approval_client()
    accounting_client = (
        eos_accounting_client or build_default_eos_accounting_display_client()
    )

    @app.get("/api/v1/approval-gates", response_model=None)
    def list_approval_gates(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        authorization: str | None = Header(default=None),
    ):
        auth = _browser_approval_context(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        try:
            return client.list_gates(
                tenant_id=auth.browser_context.tenant_id,
                subject_id=auth.browser_context.user_id,
                limit=limit,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except ApprovalFacadeError as exc:
            return _approval_problem(request, exc)

    @app.get(
        "/api/v1/approval-gates/{approval_work_item_id}",
        response_model=None,
    )
    def get_approval_gate(
        approval_work_item_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = _browser_approval_context(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        try:
            return client.get_gate(
                approval_work_item_id,
                tenant_id=auth.browser_context.tenant_id,
                subject_id=auth.browser_context.user_id,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except ApprovalFacadeError as exc:
            return _approval_problem(request, exc)

    @app.get(
        "/api/v1/approval-gates/{approval_work_item_id}/user-projection",
        response_model=None,
    )
    def get_approval_gate_user_projection(
        approval_work_item_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = _browser_approval_context(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        try:
            detail = client.get_gate(
                approval_work_item_id,
                tenant_id=auth.browser_context.tenant_id,
                subject_id=auth.browser_context.user_id,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
            accounting_ref = _accounting_reference(detail)
            accounting_document = None
            diagnostic_code = None
            if accounting_ref is not None:
                if accounting_ref["kind"] == "INVALID":
                    diagnostic_code = "ae.accounting_reference_invalid"
                else:
                    try:
                        context = {
                            "tenant_id": auth.browser_context.tenant_id,
                            "request_id": request_id_from_headers(request),
                            "trace_id": trace_id_from_headers(request),
                        }
                        if accounting_ref["kind"] == "CASE":
                            accounting_document = accounting_client.get_case_display(
                                accounting_ref["case_id"],
                                **context,
                            )
                        else:
                            accounting_document = accounting_client.get_candidate_display(
                                accounting_ref["candidate_id"],
                                expected_revision=accounting_ref["candidate_revision"],
                                expected_hash=accounting_ref["candidate_hash"],
                                **context,
                            )
                    except ApprovalFacadeError as exc:
                        diagnostic_code = exc.error_code
            return build_user_approval_projection(
                tenant_id=auth.browser_context.tenant_id,
                detail=detail,
                accounting_document=accounting_document,
                accounting_diagnostic_code=diagnostic_code,
            )
        except ApprovalProjectionError as exc:
            return _approval_problem(
                request,
                ApprovalFacadeError(
                    502,
                    "ae.approval_projection_invalid",
                    str(exc),
                    True,
                ),
            )
        except ApprovalFacadeError as exc:
            return _approval_problem(request, exc)

    @app.post(
        "/api/v1/approval-gates/{approval_work_item_id}/decisions",
        response_model=None,
    )
    def decide_approval_gate(
        approval_work_item_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = _browser_approval_context(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        try:
            result, status_code = client.decide_gate(
                approval_work_item_id,
                _decision_request(payload),
                tenant_id=auth.browser_context.tenant_id,
                subject_id=auth.browser_context.user_id,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
            return JSONResponse(dict(result), status_code=status_code)
        except ApprovalFacadeError as exc:
            return _approval_problem(request, exc)


def _browser_approval_context(
    request: Request,
    authorization: str | None,
    *,
    oa_session_client: OaUserSessionClient | None,
    session_mode: str | None,
) -> AeFacadeRouteAuthContext | JSONResponse:
    result = authorize_ae_facade_route_request(
        request,
        authorization,
        required_user_scopes=(DEFAULT_USER_SCOPE,),
        oa_session_client=oa_session_client,
        session_mode=session_mode,
    )
    if isinstance(result, JSONResponse):
        return result
    if result.browser_context is None:
        return problem_response(
            request,
            status_code=403,
            error_code="ae.approval_browser_session_required",
            title="AE approval browser session required",
            detail="Approval interaction requires an authenticated browser user.",
            retryable=False,
        )
    return result


def _decision_request(payload: object) -> dict[str, Any]:
    fields = {
        "schema_version",
        "decision",
        "decision_comment",
        "correlation_id",
        "causation_id",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ApprovalFacadeError(
            422,
            "ae.approval_decision_request_invalid",
            "Approval decision request fields are invalid.",
        )
    if payload.get("schema_version") != "wc_approval_decision_request.v1":
        raise ApprovalFacadeError(
            422,
            "ae.approval_decision_request_invalid",
            "Approval decision request schema_version is invalid.",
        )
    if payload.get("decision") not in {"APPROVE", "REJECT"}:
        raise ApprovalFacadeError(
            422,
            "ae.approval_decision_request_invalid",
            "Approval decision action is invalid.",
        )
    comment = payload.get("decision_comment")
    if comment is not None and (
        not isinstance(comment, str) or not comment or len(comment) > 2000
    ):
        raise ApprovalFacadeError(
            422,
            "ae.approval_decision_request_invalid",
            "Approval decision comment is invalid.",
        )
    for field in ("correlation_id", "causation_id"):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ApprovalFacadeError(
                422,
                "ae.approval_decision_request_invalid",
                f"Approval decision {field} is invalid.",
            )
    return dict(payload)


def _approval_problem(request: Request, exc: ApprovalFacadeError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="AE approval request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/ae-approval-request-failed",
    )


def _safe_response_json(response: httpx.Response) -> Mapping[str, Any] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, Mapping) else None


def _accounting_reference(detail: Mapping[str, Any]) -> dict[str, Any] | None:
    gate = detail.get("gate")
    if not isinstance(gate, Mapping):
        return None
    target = gate.get("approval_target_ref")
    if (
        gate.get("approval_domain") == "BUSINESS_FORMAL"
        and gate.get("approval_provider_type") == "EOS"
        and isinstance(target, str)
        and target.startswith("eos.scoped-approval-case:")
    ):
        case_id = target.removeprefix("eos.scoped-approval-case:")
        try:
            case_id = str(UUID(case_id))
        except ValueError:
            return {"kind": "INVALID"}
        return {
            "kind": "CASE",
            "case_id": case_id,
        }
    if gate.get("approval_domain") != "NSL_WRITE":
        return None
    try:
        summary = json.loads(str(gate.get("summary") or ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(summary, Mapping):
        return None
    reference = summary.get("accounting_document_ref")
    if (
        not isinstance(reference, Mapping)
        or set(reference)
        != {
            "schema_version",
            "candidate_id",
            "candidate_revision",
            "candidate_hash",
        }
        or reference.get("schema_version") != "ae_accounting_candidate_ref.v1"
    ):
        return None
    try:
        candidate_id = str(UUID(str(reference.get("candidate_id"))))
        candidate_hash = validate_hash_ref(reference.get("candidate_hash"))
    except (ValueError, TypeError, AttributeError):
        return {"kind": "INVALID"}
    candidate_revision = reference.get("candidate_revision")
    if (
        isinstance(candidate_revision, bool)
        or not isinstance(candidate_revision, int)
        or candidate_revision < 1
    ):
        return {"kind": "INVALID"}
    return {
        "kind": "CANDIDATE",
        "candidate_id": candidate_id,
        "candidate_revision": candidate_revision,
        "candidate_hash": candidate_hash,
    }


def _require_safe_accounting_document(value: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "tenant_id",
        "candidate_id",
        "candidate_revision",
        "candidate_hash",
        "company_id",
        "project_code",
        "approved_document_ref",
        "recognition_date",
        "currency",
        "requester_subject_id",
        "approval_case_id",
        "approval_state",
        "lines",
        "totals",
    }
    if set(value) != required or value.get("schema_version") != (
        "eos_accounting_document_projection.v1"
    ):
        raise ApprovalFacadeError(
            502,
            "ae.eos_accounting_display_unsafe",
            "EOS accounting display response contains unsupported fields.",
            True,
        )


_HUMAN_GATE_FIELDS = {
    "schema_version",
    "gate_id",
    "approval_domain",
    "state",
    "title",
    "summary",
    "action_ref",
    "approval_provider_type",
    "approval_target_ref",
    "business_operation_id",
    "expires_at",
}
_BUSINESS_FORMAL_FIELDS = {
    "schema_version",
    "current_stage",
    "stage_count",
    "requested_role",
    "eos_target_ref",
    "org_unit_id",
    "project_id",
    "terminal_state",
}


def _require_safe_approval_inbox(body: Mapping[str, Any]) -> None:
    _require_exact_fields(
        body,
        {
            "schema_version",
            "tenant_id",
            "subject_ref",
            "gates",
            "returned_count",
            "limit",
            "scan_truncated",
        },
    )
    subject = body.get("subject_ref")
    gates = body.get("gates")
    if not isinstance(subject, Mapping) or set(subject) != {"type", "id"}:
        _raise_unsafe_wc_response()
    if not isinstance(gates, list):
        _raise_unsafe_wc_response()
    for gate in gates:
        _require_safe_human_gate(gate)


def _require_safe_approval_detail(body: Mapping[str, Any]) -> None:
    _require_exact_fields(
        body,
        {"schema_version", "gate", "created_at", "version", "decision_options"},
    )
    _require_safe_human_gate(body.get("gate"))


def _require_safe_approval_decision(body: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "tenant_id",
        "decision_id",
        "approval_work_item_id",
        "decision",
        "decided_by",
        "decision_version",
        "authorized_by_oa",
        "oa_decision_ref",
        "authorization_revision_hash",
        "authorization_checked_at",
        "decided_at",
    }
    fields = set(body)
    if not required.issubset(fields) or not fields.issubset(
        required | {"decision_comment"}
    ):
        _raise_unsafe_wc_response()


def _require_safe_human_gate(value: object) -> None:
    if not isinstance(value, Mapping):
        _raise_unsafe_wc_response()
    is_business_formal = value.get("approval_domain") == "BUSINESS_FORMAL"
    expected_fields = (
        _HUMAN_GATE_FIELDS | {"formal_approval"}
        if is_business_formal
        else _HUMAN_GATE_FIELDS
    )
    _require_exact_fields(value, expected_fields)
    if not is_business_formal:
        return
    formal = value.get("formal_approval")
    _require_exact_fields(formal, _BUSINESS_FORMAL_FIELDS)
    if (
        value.get("approval_provider_type") != "EOS"
        or not value.get("business_operation_id")
        or formal.get("schema_version") != "business_formal_gate_view.p8.v1"
        or formal.get("eos_target_ref") != value.get("approval_target_ref")
    ):
        _raise_unsafe_wc_response()
    current_stage = formal.get("current_stage")
    stage_count = formal.get("stage_count")
    if current_stage is None or stage_count is None:
        if current_stage is not None or stage_count is not None:
            _raise_unsafe_wc_response()
    elif (
        isinstance(current_stage, bool)
        or isinstance(stage_count, bool)
        or not isinstance(current_stage, int)
        or not isinstance(stage_count, int)
        or not 1 <= current_stage <= stage_count <= 5
    ):
        _raise_unsafe_wc_response()
    expected_terminal = (
        None if value.get("state") == "PENDING" else value.get("state")
    )
    if formal.get("terminal_state") != expected_terminal:
        _raise_unsafe_wc_response()


def _require_exact_fields(value: object, fields: set[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != fields:
        _raise_unsafe_wc_response()


def _raise_unsafe_wc_response() -> None:
    raise ApprovalFacadeError(
        502,
        "ae.wc_approval_response_unsafe",
        "WC approval response contains unsupported fields.",
        True,
    )
