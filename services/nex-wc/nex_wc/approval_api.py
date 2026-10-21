from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from nex_runtime import DEFAULT_SERVICE_SCOPE, problem_response
from nex_runtime.auth import validate_authorization_header

from nex_wc.approvals import (
    ApprovalDecisionAuthorizationError,
    ApprovalDecisionError,
    ApprovalDecisionService,
    ApprovalDetailService,
    ApprovalInboxError,
    ApprovalInboxService,
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def register_approval_routes(
    app: FastAPI,
    *,
    inbox_service: ApprovalInboxService,
    detail_service: ApprovalDetailService | None = None,
    decision_service: ApprovalDecisionService | None = None,
) -> None:
    @app.get("/api/v1/approval-gates", response_model=None)
    def list_approval_gates(
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        limit: int = Query(default=50),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        try:
            return inbox_service.list_pending(
                tenant_id=tenant_id,
                subject_id=subject_id,
                limit=limit,
            )
        except ApprovalInboxError as exc:
            return _approval_problem(
                request, exc, title="WC approval inbox request failed"
            )

    @app.get(
        "/api/v1/approval-gates/{approval_work_item_id}",
        response_model=None,
    )
    def get_approval_gate(
        approval_work_item_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        if detail_service is None:
            return _dependency_unavailable(request, "detail")
        try:
            return detail_service.get(
                tenant_id=tenant_id,
                subject_id=subject_id,
                approval_work_item_id=approval_work_item_id,
            )
        except ApprovalInboxError as exc:
            return _approval_problem(
                request, exc, title="WC approval detail request failed"
            )

    @app.post(
        "/api/v1/approval-gates/{approval_work_item_id}/decisions",
        response_model=None,
    )
    def decide_approval_gate(
        approval_work_item_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        if decision_service is None:
            return _dependency_unavailable(request, "decision")
        try:
            request_value = _decision_request(payload)
            result = decision_service.decide(
                tenant_id=tenant_id,
                approval_work_item_id=approval_work_item_id,
                decision=request_value["decision"],
                decided_by=subject_id,
                decision_comment=request_value["decision_comment"],
                correlation_id=request_value["correlation_id"],
                causation_id=request_value["causation_id"],
            )
        except (ApprovalDecisionError, ApprovalDecisionAuthorizationError) as exc:
            return _approval_problem(
                request, exc, title="WC approval decision failed"
            )
        return JSONResponse(
            result["decision"],
            status_code=201 if result["created"] else 200,
        )


def _authorize(request: Request, authorization: str | None) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-wc",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if result.ok:
        return None
    status = 403 if result.error_code == "SERVICE_SCOPE_MISSING" else 401
    return problem_response(
        request,
        status_code=status,
        error_code=result.error_code or "WC_AUTHORIZATION_FAILED",
        title="WC service authorization failed",
        detail=result.detail or "WC service authorization failed.",
        retryable=False,
        type_uri="https://nex-platform.local/problems/wc-service-authorization-failed",
    )


def _decision_request(payload: object) -> dict[str, Any]:
    fields = {
        "schema_version",
        "decision",
        "decision_comment",
        "correlation_id",
        "causation_id",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ApprovalDecisionError(
            "wc.approval_decision_request_invalid",
            "Approval decision request fields are invalid.",
            422,
        )
    if payload["schema_version"] != "wc_approval_decision_request.v1":
        raise ApprovalDecisionError(
            "wc.approval_decision_request_invalid",
            "Approval decision request schema_version is invalid.",
            422,
        )
    if payload["decision"] not in {"APPROVE", "REJECT"}:
        raise ApprovalDecisionError(
            "wc.approval_decision_request_invalid",
            "Approval decision action is invalid.",
            422,
        )
    comment = payload["decision_comment"]
    if comment is not None and (
        not isinstance(comment, str) or not comment or len(comment) > 2000
    ):
        raise ApprovalDecisionError(
            "wc.approval_decision_request_invalid",
            "Approval decision comment is invalid.",
            422,
        )
    for field in ("correlation_id", "causation_id"):
        value = payload[field]
        if value is not None and (
            not isinstance(value, str) or not _SCOPED_ID.fullmatch(value)
        ):
            raise ApprovalDecisionError(
                "wc.approval_decision_request_invalid",
                f"Approval decision {field} is invalid.",
                422,
            )
    return dict(payload)


def _approval_problem(
    request: Request,
    exc: (
        ApprovalInboxError
        | ApprovalDecisionError
        | ApprovalDecisionAuthorizationError
    ),
    *,
    title: str,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title=title,
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/wc-approval-request-failed",
    )


def _dependency_unavailable(request: Request, capability: str) -> JSONResponse:
    return problem_response(
        request,
        status_code=503,
        error_code="wc.approval_api_unavailable",
        title="WC approval API unavailable",
        detail=f"WC approval {capability} dependency is not configured.",
        retryable=True,
        type_uri="https://nex-platform.local/problems/wc-approval-api-unavailable",
    )
