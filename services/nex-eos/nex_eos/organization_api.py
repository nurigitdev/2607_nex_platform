from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .approver_resolution import (
    EosApproverResolutionError,
    EosApproverResolutionService,
)


def register_organization_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v1/organization/approver-resolutions",
        response_model=None,
    )
    def resolve_approver(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service: EosApproverResolutionService | None = getattr(
            request.app.state, "eos_approver_resolution_service", None
        )
        if service is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_APPROVER_RESOLUTION_UNAVAILABLE",
                title="EOS approver resolution unavailable",
                detail="EOS Organization dependencies are not configured.",
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-approver-resolution-unavailable"
                ),
            )
        try:
            return service.resolve(payload, tenant_id=tenant_id)
        except EosApproverResolutionError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS approver resolution failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-approver-resolution-failed"
                ),
            )
