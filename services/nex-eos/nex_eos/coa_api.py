from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .coa_operations import EosCoaOperationError, EosCoaOperationsService


def register_coa_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/coa/releases/{definition_release_id}/publish",
        response_model=None,
        operation_id="FINANCE.COA.PUBLISH_APPROVED",
    )
    def publish_approved_coa(
        definition_release_id: str,
        payload: dict[str, Any],
        request: Request,
        actor_tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        command = {**payload, "definition_release_id": definition_release_id}
        result = _invoke(
            request,
            authorization,
            lambda service: service.publish_approved(
                actor_tenant_id=actor_tenant_id,
                requester_subject_id=requester_subject_id,
                payload=command,
            ),
        )
        if isinstance(result, JSONResponse):
            return result
        return JSONResponse(result, 201 if result.get("created") else 200)

    @app.post(
        "/internal/v2/finance/coa/adoptions",
        response_model=None,
        operation_id="FINANCE.COA.ADOPT_APPROVED",
    )
    def adopt_approved_coa(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        result = _invoke(
            request,
            authorization,
            lambda service: service.adopt_approved(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                payload=payload,
            ),
        )
        if isinstance(result, JSONResponse):
            return result
        return JSONResponse(result, 201 if result.get("created") else 200)


def _invoke(request: Request, authorization: str | None, operation):
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-eos",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
        route_class="WRITE",
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    service: EosCoaOperationsService | None = getattr(
        request.app.state, "eos_coa_operations_service", None
    )
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_COA_SERVICE_UNAVAILABLE",
            title="EOS COA service unavailable",
            detail=(
                "COA persistence, OA authorization, or publication admission "
                "is not configured."
            ),
            retryable=True,
            type_uri="https://nex-platform.local/problems/eos-coa-service-unavailable",
        )
    try:
        return operation(service)
    except EosCoaOperationError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS COA operation failed",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri="https://nex-platform.local/problems/eos-coa-operation-failed",
        )
