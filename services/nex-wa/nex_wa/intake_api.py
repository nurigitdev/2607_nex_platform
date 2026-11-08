from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    request_id_from_headers,
    trace_id_from_headers,
)

from .intake import WA_EVIDENCE_INGEST_SCOPE, WaEvidenceIntakeService
from .intake_contracts import (
    WaIntakeContractError,
    build_wa_error_response,
)


def register_evidence_intake_routes(app: FastAPI) -> None:
    @app.post("/internal/v1/evidence-intake", response_model=None)
    def admit_evidence_intake(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-wa",
            required_scopes=(DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_INGEST_SCOPE),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        if admitted.service_id != "nex-ae-api":
            return _error_response(
                WaIntakeContractError(
                    "WA_INTAKE_CALLER_FORBIDDEN",
                    "only nex-ae-api may submit evidence intake notifications",
                    403,
                ),
                request_id=request_id,
                trace_id=trace_id,
            )
        service: WaEvidenceIntakeService | None = getattr(
            request.app.state,
            "wa_evidence_intake_service",
            None,
        )
        if service is None:
            return _error_response(
                WaIntakeContractError(
                    "WA_INTAKE_UNAVAILABLE",
                    "evidence intake dependencies are unavailable",
                    503,
                ),
                request_id=request_id,
                trace_id=trace_id,
            )
        try:
            admission = service.admit(
                payload,
                caller_service_id=admitted.service_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except WaIntakeContractError as exc:
            return _error_response(
                exc,
                request_id=request_id,
                trace_id=trace_id,
            )
        return JSONResponse(admission.to_dict(), status_code=202)


def _error_response(
    error: WaIntakeContractError,
    *,
    request_id: str,
    trace_id: str,
) -> JSONResponse:
    return JSONResponse(
        build_wa_error_response(
            error,
            request_id=request_id,
            trace_id=trace_id,
        ).to_dict(),
        status_code=error.status_code,
    )
