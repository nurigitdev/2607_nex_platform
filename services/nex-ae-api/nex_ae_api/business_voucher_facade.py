from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

import httpx
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)

from nex_ae_api.oa_session_client import OaUserSessionClient
from nex_ae_api.product_planning_runtime import ProductPlanningRuntimeError
from nex_ae_api.product_preparation_persistence import (
    ProductPreparationPersistenceError,
)
from nex_ae_api.route_auth import authorize_ae_facade_route_request
from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

DEFAULT_EOS_BUSINESS_VOUCHER_BASE_URL = (
    f"http://127.0.0.1:{SERVICE_SPECS['nex-eos'].default_port}"
)


class EosBusinessVoucherClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
        params: list[tuple[str, str]] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[Mapping[str, Any], int]: ...


@dataclass(frozen=True)
class BusinessVoucherFacadeError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpEosBusinessVoucherClient:
    base_url: str = DEFAULT_EOS_BUSINESS_VOUCHER_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 30.0

    def request(
        self,
        method: str,
        path: str,
        *,
        tenant_id: str,
        subject_id: str,
        request_id: str,
        trace_id: str,
        params: list[tuple[str, str]] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[Mapping[str, Any], int]:
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-eos",
            )
            response = httpx.request(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-NeX-Tenant-Id": tenant_id,
                    "X-NeX-Subject-Id": subject_id,
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ae-api",
                },
                params=params,
                json=dict(payload) if payload is not None else None,
                timeout=self.timeout_seconds,
            )
        except (httpx.HTTPError, AeOutboundServiceTokenError) as exc:
            raise BusinessVoucherFacadeError(
                503,
                "ae.business_voucher_unavailable",
                "Business voucher service is unavailable.",
                True,
            ) from exc
        body = _response_body(response)
        if response.status_code >= 400:
            raise BusinessVoucherFacadeError(
                response.status_code,
                str(body.get("error_code") or "ae.business_voucher_request_failed"),
                str(body.get("detail") or "Business voucher request failed."),
                bool(body.get("retryable", response.status_code >= 500)),
            )
        return body, response.status_code


def register_business_voucher_facade_routes(
    app: FastAPI,
    *,
    eos_client: EosBusinessVoucherClient | None = None,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> None:
    client = eos_client or HttpEosBusinessVoucherClient(
        base_url=os.getenv("NEX_EOS_BASE_URL", DEFAULT_EOS_BUSINESS_VOUCHER_BASE_URL),
        service_token=os.getenv("NEX_AE_TO_EOS_SERVICE_TOKEN"),
    )

    @app.get("/api/v1/business-voucher-drafts", response_model=None)
    def list_drafts(
        request: Request,
        state: Annotated[list[str] | None, Query()] = None,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "GET",
            "/internal/v2/business-voucher-drafts",
            params=[("states", item) for item in (state or ())],
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    @app.post("/api/v1/business-voucher-drafts", response_model=None)
    def create_draft(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "POST",
            "/internal/v2/business-voucher-drafts",
            payload=payload,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    @app.get("/api/v1/business-voucher-drafts/{candidate_id}", response_model=None)
    def get_draft(
        candidate_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "GET",
            f"/internal/v2/business-voucher-drafts/{candidate_id}",
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    @app.patch("/api/v1/business-voucher-drafts/{candidate_id}", response_model=None)
    def revise_draft(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "PATCH",
            f"/internal/v2/business-voucher-drafts/{candidate_id}",
            payload=payload,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    for suffix in ("validate", "submit-for-accounting"):
        _register_command(
            app,
            suffix=suffix,
            client=client,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )


def _register_command(
    app: FastAPI,
    *,
    suffix: str,
    client: EosBusinessVoucherClient,
    oa_session_client: OaUserSessionClient | None,
    session_mode: str | None,
) -> None:
    path = f"/api/v1/business-voucher-drafts/{{candidate_id}}:{suffix}"

    def command(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "POST",
            f"/internal/v2/business-voucher-drafts/{candidate_id}:{suffix}",
            payload=payload,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
            review_authority_kind=(
                "REQUESTER_VOUCHER_REVIEW"
                if suffix == "submit-for-accounting"
                else None
            ),
            review_authority_ref=(
                f"eos.voucher-candidate:{candidate_id}"
                if suffix == "submit-for-accounting"
                else None
            ),
        )

    command.__name__ = f"business_voucher_{suffix.replace('-', '_')}"
    app.post(path, response_model=None)(command)


def _forward(
    request: Request,
    authorization: str | None,
    client: EosBusinessVoucherClient,
    method: str,
    path: str,
    *,
    params: list[tuple[str, str]] | None = None,
    payload: Mapping[str, Any] | None = None,
    oa_session_client: OaUserSessionClient | None,
    session_mode: str | None,
    review_authority_kind: str | None = None,
    review_authority_ref: str | None = None,
):
    auth = authorize_ae_facade_route_request(
        request,
        authorization,
        required_user_scopes=(DEFAULT_USER_SCOPE,),
        oa_session_client=oa_session_client,
        session_mode=session_mode,
    )
    if isinstance(auth, JSONResponse):
        return auth
    if auth.browser_context is None:
        return problem_response(
            request,
            status_code=403,
            error_code="ae.business_voucher_browser_session_required",
            title="AE business voucher browser session required",
            detail="Voucher draft interaction requires an authenticated user.",
            retryable=False,
        )
    try:
        body, status_code = client.request(
            method,
            path,
            tenant_id=auth.browser_context.tenant_id,
            subject_id=auth.browser_context.user_id,
            request_id=request_id_from_headers(request),
            trace_id=trace_id_from_headers(request),
            params=params,
            payload=payload,
        )
    except BusinessVoucherFacadeError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="AE business voucher request failed",
            detail=exc.detail,
            retryable=exc.retryable,
        )
    if review_authority_kind is not None and review_authority_ref is not None:
        admission = getattr(request.app.state, "ae_product_review_events", None)
        if admission is not None:
            try:
                admission.ingest(
                    tenant_id=auth.browser_context.tenant_id,
                    requester_ref=auth.browser_context.user_id,
                    authority_kind=review_authority_kind,
                    authority_ref=review_authority_ref,
                    receipt=body,
                )
            except (
                ProductPlanningRuntimeError,
                ProductPreparationPersistenceError,
            ) as exc:
                error_code = str(
                    getattr(exc, "error_code", "ae.product_review_resume_failed")
                )
                return problem_response(
                    request,
                    status_code=503 if bool(getattr(exc, "retryable", False)) else 409,
                    error_code=error_code,
                    title="AE Product review resume failed",
                    detail=str(getattr(exc, "detail", "Product review resume failed.")),
                    retryable=bool(getattr(exc, "retryable", False)),
                )
    return JSONResponse(dict(body), status_code=status_code)


def _response_body(response: httpx.Response) -> Mapping[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise BusinessVoucherFacadeError(
            502,
            "ae.business_voucher_response_invalid",
            "Business voucher response is invalid.",
            True,
        ) from exc
    if not isinstance(body, Mapping):
        raise BusinessVoucherFacadeError(
            502,
            "ae.business_voucher_response_invalid",
            "Business voucher response is invalid.",
            True,
        )
    return body


__all__ = [
    "BusinessVoucherFacadeError",
    "HttpEosBusinessVoucherClient",
    "register_business_voucher_facade_routes",
]
