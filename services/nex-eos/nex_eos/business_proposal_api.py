from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .business_proposal_approval import (
    ApprovalLineSelectionInput,
    EosBusinessProposalApprovalError,
)
from .business_proposals import (
    BusinessProposalRevisionInput,
    BusinessProposalSubmissionInput,
    EosBusinessProposalError,
)


def register_business_proposal_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/business-proposals",
        response_model=None,
        operation_id="BUSINESS.PROPOSAL.CREATE",
    )
    def create_proposal(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _repository_call(
            request,
            authorization,
            lambda repository: repository.create_draft(
                _revision_input(tenant_id, requester_subject_id, payload)
            ),
            status_code=201,
        )

    @app.patch(
        "/internal/v2/business-proposals/{proposal_id}",
        response_model=None,
        operation_id="BUSINESS.PROPOSAL.REVISE",
    )
    def revise_proposal(
        proposal_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _repository_call(
            request,
            authorization,
            lambda repository: repository.revise_draft(
                _revision_input(
                    tenant_id,
                    requester_subject_id,
                    {**payload, "proposal_id": proposal_id},
                ),
                expected_version=_positive_int(
                    "expected_version", payload.get("expected_version")
                ),
                expected_revision=_positive_int(
                    "expected_revision", payload.get("expected_revision")
                ),
                actor_subject_id=requester_subject_id,
            ),
        )

    @app.get(
        "/internal/v2/business-proposals/{proposal_id}",
        response_model=None,
        operation_id="BUSINESS.PROPOSAL.GET",
    )
    def get_proposal(
        proposal_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        def operation(repository):
            found = repository.get(
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                requester_subject_id=requester_subject_id,
            )
            if found is None:
                raise EosBusinessProposalError(
                    "BUSINESS_PROPOSAL_NOT_FOUND",
                    "Business proposal was not found",
                    status_code=404,
                )
            return found

        return _repository_call(request, authorization, operation)

    @app.get(
        "/internal/v2/business-proposals",
        response_model=None,
        operation_id="BUSINESS.PROPOSAL.LIST",
    )
    def list_proposals(
        request: Request,
        states: Annotated[list[str] | None, Query()] = None,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _repository_call(
            request,
            authorization,
            lambda repository: {
                "schema_version": "eos_business_proposal_list.v1",
                "items": repository.list_owner(
                    tenant_id=tenant_id,
                    requester_subject_id=requester_subject_id,
                    states=states or [],
                ),
            },
        )

    @app.post(
        "/internal/v2/business-proposals/{proposal_id}:preview-approval",
        response_model=None,
        operation_id="BUSINESS.PROPOSAL.PREVIEW_APPROVAL",
    )
    def preview_approval(
        proposal_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _approval_call(
            request,
            authorization,
            lambda service: service.preview(
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                requester_subject_id=requester_subject_id,
                effective_at=_instant(payload.get("effective_at")),
                risk_level=_optional_text(payload.get("risk_level")),
            ),
        )

    @app.post(
        "/internal/v2/business-proposals/{proposal_id}:select-approval-line",
        response_model=None,
        operation_id="BUSINESS.PROPOSAL.SELECT_APPROVAL_LINE",
    )
    def select_approval_line(
        proposal_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        def operation(service):
            preview = service.preview(
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                requester_subject_id=requester_subject_id,
                effective_at=_instant(payload.get("effective_at")),
                risk_level=_optional_text(payload.get("risk_level")),
            )
            return service.select_line(
                preview=preview,
                selection=ApprovalLineSelectionInput(
                    preview_hash=str(payload.get("preview_hash", "")),
                    proposal_id=proposal_id,
                    revision_no=_positive_int(
                        "revision_no", payload.get("revision_no")
                    ),
                    selected_approvers=_object_list(
                        "selected_approvers", payload.get("selected_approvers")
                    ),
                ),
            )

        return _approval_call(request, authorization, operation)

    @app.post(
        "/internal/v2/business-proposals/{proposal_id}:submit",
        response_model=None,
        operation_id="BUSINESS.PROPOSAL.SUBMIT",
    )
    def submit_proposal(
        proposal_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = _admit(request, authorization)
        if isinstance(admitted, JSONResponse):
            return admitted
        repository = getattr(request.app.state, "eos_business_proposals", None)
        service = getattr(request.app.state, "eos_business_proposal_approval", None)
        if repository is None or service is None:
            return _unavailable(request)
        try:
            at = _instant(payload.get("effective_at"))
            preview = service.preview(
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                requester_subject_id=requester_subject_id,
                effective_at=at,
                risk_level=_optional_text(payload.get("risk_level")),
            )
            line = service.select_line(
                preview=preview,
                selection=ApprovalLineSelectionInput(
                    preview_hash=str(payload.get("preview_hash", "")),
                    proposal_id=proposal_id,
                    revision_no=_positive_int(
                        "expected_revision", payload.get("expected_revision")
                    ),
                    selected_approvers=_object_list(
                        "selected_approvers", payload.get("selected_approvers")
                    ),
                ),
            )
            normalization = preview["normalized_amount_evidence"]
            result = repository.submit(
                BusinessProposalSubmissionInput(
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    requester_subject_id=requester_subject_id,
                    expected_version=_positive_int(
                        "expected_version", payload.get("expected_version")
                    ),
                    expected_revision=_positive_int(
                        "expected_revision", payload.get("expected_revision")
                    ),
                    content_hash=str(preview["content_hash"]),
                    approval_policy_id=str(preview["approval_policy_id"]),
                    approval_policy_hash=str(preview["approval_policy_hash"]),
                    approval_preview_hash=str(preview["preview_hash"]),
                    candidate_evidence_hash=str(
                        preview["candidate_evidence_hash"]
                    ),
                    approval_line_hash=str(line["approval_line_hash"]),
                    normalized_amount=Decimal(
                        str(normalization["normalized_amount"])
                    ),
                    functional_currency=str(normalization["functional_currency"]),
                    normalization_hash=str(normalization["calculation_hash"]),
                ),
                submitted_at=at,
            )
        except (EosBusinessProposalError, EosBusinessProposalApprovalError) as exc:
            return _problem(request, exc)
        return JSONResponse(
            {**result, "approval_line": line, "approval_preview": preview},
            status_code=200,
        )


def _revision_input(
    tenant_id: str, requester_subject_id: str, payload: Mapping[str, Any]
) -> BusinessProposalRevisionInput:
    return BusinessProposalRevisionInput(
        tenant_id=tenant_id,
        proposal_id=str(payload.get("proposal_id", "")),
        revision_id=str(payload.get("revision_id", "")),
        company_id=str(payload.get("company_id", "")),
        requester_subject_id=requester_subject_id,
        document_type=str(payload.get("document_type", "")),
        work_code=str(payload.get("work_code", "")),
        title=str(payload.get("title", "")),
        purpose=str(payload.get("purpose", "")),
        business_justification=str(payload.get("business_justification", "")),
        transaction_type=str(payload.get("transaction_type", "")),
        requested_amount=Decimal(str(payload.get("requested_amount", ""))),
        original_currency=str(payload.get("original_currency", "")),
        valid_from=_instant(payload.get("valid_from")),
        valid_until=_optional_instant(payload.get("valid_until")),
        scope_type=str(payload.get("scope_type", "")),
        project_ids=_string_list("project_ids", payload.get("project_ids")),
        project_codes=_string_list("project_codes", payload.get("project_codes")),
        attachment_manifest=_object_list(
            "attachment_manifest", payload.get("attachment_manifest", [])
        ),
    )


def _repository_call(
    request: Request,
    authorization: str | None,
    operation: Callable[[Any], Any],
    *,
    status_code: int = 200,
):
    admitted = _admit(request, authorization)
    if isinstance(admitted, JSONResponse):
        return admitted
    repository = getattr(request.app.state, "eos_business_proposals", None)
    if repository is None:
        return _unavailable(request)
    try:
        result = operation(repository)
    except (EosBusinessProposalError, InvalidOperation, ValueError) as exc:
        if isinstance(exc, EosBusinessProposalError):
            return _problem(request, exc)
        return _problem(
            request,
            EosBusinessProposalError(
                "BUSINESS_PROPOSAL_INVALID", "Request payload is invalid", status_code=422
            ),
        )
    return JSONResponse(result, status_code=status_code)


def _approval_call(
    request: Request,
    authorization: str | None,
    operation: Callable[[Any], Any],
):
    admitted = _admit(request, authorization)
    if isinstance(admitted, JSONResponse):
        return admitted
    service = getattr(request.app.state, "eos_business_proposal_approval", None)
    if service is None:
        return _unavailable(request)
    try:
        return JSONResponse(operation(service), status_code=200)
    except (EosBusinessProposalApprovalError, EosBusinessProposalError) as exc:
        return _problem(request, exc)


def _admit(request: Request, authorization: str | None):
    return admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-eos",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )


def _problem(request: Request, exc: Any) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS business proposal request failed",
        detail=exc.detail,
        retryable=getattr(exc, "retryable", False),
    )


def _unavailable(request: Request) -> JSONResponse:
    return problem_response(
        request,
        status_code=503,
        error_code="BUSINESS_PROPOSAL_UNAVAILABLE",
        title="EOS business proposal unavailable",
        detail="Business proposal dependencies are not configured",
        retryable=True,
    )


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise EosBusinessProposalError(
            "BUSINESS_PROPOSAL_INVALID", "datetime value is required", status_code=422
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EosBusinessProposalError(
            "BUSINESS_PROPOSAL_INVALID", "datetime value is invalid", status_code=422
        ) from exc
    if parsed.tzinfo is None:
        raise EosBusinessProposalError(
            "BUSINESS_PROPOSAL_INVALID", "datetime value must be timezone-aware", status_code=422
        )
    return parsed.astimezone(UTC)


def _optional_instant(value: object) -> datetime | None:
    return None if value is None else _instant(value)


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EosBusinessProposalError(
            "BUSINESS_PROPOSAL_INVALID", f"{field} must be positive", status_code=422
        )
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _string_list(field: str, value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EosBusinessProposalError(
            "BUSINESS_PROPOSAL_INVALID", f"{field} must be a string list", status_code=422
        )
    return value


def _object_list(field: str, value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise EosBusinessProposalError(
            "BUSINESS_PROPOSAL_INVALID", f"{field} must be an object list", status_code=422
        )
    return value
