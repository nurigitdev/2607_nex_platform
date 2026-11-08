from __future__ import annotations

from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response

from nex_ae_api.route_auth import authorize_ae_internal_service_request
from nex_ae_api.work_result_events import WorkResultEventError


class WorkResultEventAdmission(Protocol):
    def ingest(self, event: object) -> dict[str, Any]: ...


def register_work_result_event_routes(
    app: FastAPI, *, admission: WorkResultEventAdmission | None
) -> None:
    @app.post("/internal/v1/work-result-events", response_model=None)
    def ingest_work_result_event(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = authorize_ae_internal_service_request(
            request,
            authorization,
            allowed_service_ids=("nex-wc",),
            error_code="AE_WORK_RESULT_EVENT_CALLER_DENIED",
            title="AE WorkResult event caller denied",
            detail="Only nex-wc may deliver a WorkResult event.",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        if admission is None:
            return problem_response(
                request,
                status_code=503,
                error_code="AE_WORK_RESULT_EVENT_UNAVAILABLE",
                title="AE WorkResult event admission unavailable",
                detail="AE WorkResult event persistence is not configured.",
                retryable=True,
            )
        try:
            result = admission.ingest(payload)
        except WorkResultEventError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="AE WorkResult event admission failed",
                detail=exc.detail,
                retryable=exc.retryable,
            )
        return JSONResponse(result, status_code=201 if result["created"] else 200)
