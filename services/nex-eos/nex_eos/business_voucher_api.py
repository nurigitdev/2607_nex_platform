from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .business_voucher_drafts import (
    EosBusinessVoucherDraftError,
    EosBusinessVoucherDraftService,
)
from .voucher_commands import EosServiceCaller


def register_business_voucher_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v2/business-voucher-drafts",
        response_model=None,
        operation_id="FINANCE.VOUCHER_PRE_SUBMISSION.LIST",
    )
    def list_drafts(
        request: Request,
        states: Annotated[list[str] | None, Query()] = None,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service, _caller: service.list_owner(
                tenant_id=tenant_id,
                subject_id=subject_id,
                states=states or (),
            ),
        )

    @app.post(
        "/internal/v2/business-voucher-drafts",
        response_model=None,
        operation_id="FINANCE.VOUCHER_PRE_SUBMISSION.CREATE",
    )
    def create_draft(
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service, caller: service.create(
                tenant_id=tenant_id,
                subject_id=subject_id,
                payload=payload,
                caller=caller,
            ),
            status_code=201,
            write=True,
        )

    @app.get(
        "/internal/v2/business-voucher-drafts/{candidate_id}",
        response_model=None,
        operation_id="FINANCE.VOUCHER_PRE_SUBMISSION.GET",
    )
    def get_draft(
        candidate_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service, _caller: service.get_owner(
                tenant_id=tenant_id,
                subject_id=subject_id,
                candidate_id=candidate_id,
            ),
        )

    @app.patch(
        "/internal/v2/business-voucher-drafts/{candidate_id}",
        response_model=None,
        operation_id="FINANCE.VOUCHER_PRE_SUBMISSION.REVISE",
    )
    def revise_draft(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service, _caller: service.revise(
                tenant_id=tenant_id,
                subject_id=subject_id,
                candidate_id=candidate_id,
                payload=payload,
            ),
            write=True,
        )

    @app.post(
        "/internal/v2/business-voucher-drafts/{candidate_id}:validate",
        response_model=None,
        operation_id="FINANCE.VOUCHER_PRE_SUBMISSION.VALIDATE",
    )
    def validate_draft(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service, _caller: service.validate(
                tenant_id=tenant_id,
                subject_id=subject_id,
                candidate_id=candidate_id,
                as_of=_optional_instant(payload.get("as_of")),
            ),
        )

    @app.post(
        "/internal/v2/business-voucher-drafts/{candidate_id}:submit-for-accounting",
        response_model=None,
        operation_id="FINANCE.VOUCHER_PRE_SUBMISSION.SUBMIT_FOR_ACCOUNTING",
    )
    def submit_draft(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        subject_id: str = Header(alias="X-NeX-Subject-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _call(
            request,
            authorization,
            lambda service, caller: service.submit(
                tenant_id=tenant_id,
                subject_id=subject_id,
                candidate_id=candidate_id,
                payload=payload,
                caller=caller,
            ),
            write=True,
        )


def _call(
    request: Request,
    authorization: str | None,
    operation: Callable[
        [EosBusinessVoucherDraftService, EosServiceCaller], Any
    ],
    *,
    status_code: int = 200,
    write: bool = False,
):
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-eos",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
        route_class="WRITE" if write else "READ",
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    service = getattr(request.app.state, "eos_business_voucher_drafts", None)
    if service is None:
        return problem_response(
            request,
            status_code=503,
            error_code="EOS_BUSINESS_VOUCHER_DRAFT_UNAVAILABLE",
            title="EOS business voucher draft unavailable",
            detail="Business voucher draft dependencies are not configured.",
            retryable=True,
        )
    try:
        result = operation(
            service,
            EosServiceCaller(admitted.subject, admitted.audience, admitted.scopes),
        )
    except EosBusinessVoucherDraftError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="EOS business voucher draft request failed",
            detail=exc.detail,
            retryable=exc.retryable,
        )
    return JSONResponse(result, status_code=status_code)


def _optional_instant(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EosBusinessVoucherDraftError(
            "EOS_BUSINESS_VOUCHER_DRAFT_INVALID",
            "as_of must be an ISO timestamp.",
            status_code=422,
        ) from exc
    if parsed.tzinfo is None:
        raise EosBusinessVoucherDraftError(
            "EOS_BUSINESS_VOUCHER_DRAFT_INVALID",
            "as_of must include a timezone.",
            status_code=422,
        )
    return parsed.astimezone(UTC)


__all__ = ["register_business_voucher_routes"]
