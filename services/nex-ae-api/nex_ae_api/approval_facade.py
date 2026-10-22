from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

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


def register_approval_facade_routes(
    app: FastAPI,
    *,
    wc_client: WcApprovalClient | None = None,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> None:
    client = wc_client or build_default_wc_approval_client()

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
        _require_exact_fields(gate, _HUMAN_GATE_FIELDS)


def _require_safe_approval_detail(body: Mapping[str, Any]) -> None:
    _require_exact_fields(
        body,
        {"schema_version", "gate", "created_at", "version", "decision_options"},
    )
    _require_exact_fields(body.get("gate"), _HUMAN_GATE_FIELDS)


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
