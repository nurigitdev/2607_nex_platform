from __future__ import annotations

from datetime import date

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .reporting_maps import EosReportingMapError, EosReportingMapService


def register_reporting_map_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/finance/reporting-map",
        response_model=None,
        operation_id="FINANCE.COA.REPORTING_MAP_GET",
    )
    def get_reporting_map(
        request: Request,
        mapping_release_id: str,
        entry_id: str,
        effective_on: date,
        regulated_export: bool = False,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
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
        service: EosReportingMapService | None = getattr(
            request.app.state, "eos_reporting_map_service", None
        )
        if service is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_COA_REPORTING_SERVICE_UNAVAILABLE",
                title="EOS reporting map service unavailable",
                detail="Reporting map persistence or OA authorization is not configured.",
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-coa-reporting-service-unavailable"
                ),
            )
        try:
            return service.get_mapping(
                tenant_id=tenant_id,
                requester_subject_id=requester_subject_id,
                mapping_release_id=mapping_release_id,
                entry_id=entry_id,
                effective_on=effective_on,
                regulated_export=regulated_export,
            )
        except EosReportingMapError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS reporting map query failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-coa-reporting-map-query-failed"
                ),
            )
