from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .approved_documents import EosApprovedDocumentError, EosApprovedDocumentService


def register_approved_document_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/finance/approved-documents/{envelope_id}",
        response_model=None,
        operation_id="BUSINESS.DOCUMENT_APPROVED.GET",
    )
    def get_approved_document(
        envelope_id: str,
        request: Request,
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
        service: EosApprovedDocumentService | None = getattr(
            request.app.state, "eos_approved_document_service", None
        )
        if service is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_APPROVED_DOCUMENT_SERVICE_UNAVAILABLE",
                title="EOS approved document service unavailable",
                detail=(
                    "Approved document persistence or OA authorization is not "
                    "configured."
                ),
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-approved-document-service-unavailable"
                ),
            )
        try:
            return service.get_approved_document(
                tenant_id=tenant_id,
                envelope_id=envelope_id,
                requester_subject_id=requester_subject_id,
            )
        except EosApprovedDocumentError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS approved document operation failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-approved-document-operation-failed"
                ),
            )
