from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response

from nex_wc.route_auth import authorize_wc_service_request
from nex_wc.work_results import WorkResultError, WorkResultService


def register_work_result_routes(app: FastAPI, *, service: WorkResultService) -> None:
    @app.post("/api/v1/work-items/{work_item_id}/results", response_model=None)
    def submit_work_result(
        work_item_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = authorize_wc_service_request(
            request,
            authorization,
            allowed_service_ids=("nex-ae-api",),
            error_code="WC_WORK_RESULT_CALLER_DENIED",
            detail="Only nex-ae-api may submit an Agent WorkResult.",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        try:
            result = service.submit(
                tenant_id=tenant_id,
                work_item_id=work_item_id,
                expected_version=payload.get("expected_version"),
                work_result=payload.get("work_result"),
            )
        except WorkResultError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="WC WorkResult submission failed",
                detail=exc.detail,
                retryable=exc.retryable,
            )
        return JSONResponse(dict(result), status_code=201 if result["created"] else 200)
