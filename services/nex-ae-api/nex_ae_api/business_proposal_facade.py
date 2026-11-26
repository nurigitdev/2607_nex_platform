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
from nex_ae_api.route_auth import authorize_ae_facade_route_request
from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)

DEFAULT_EOS_BUSINESS_PROPOSAL_BASE_URL = (
    f"http://127.0.0.1:{SERVICE_SPECS['nex-eos'].default_port}"
)


class EosBusinessProposalClient(Protocol):
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
class BusinessProposalFacadeError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpEosBusinessProposalClient:
    base_url: str = DEFAULT_EOS_BUSINESS_PROPOSAL_BASE_URL
    service_token: str | None = None
    timeout_seconds: float = 20.0

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
            raise BusinessProposalFacadeError(
                503,
                "ae.business_proposal_unavailable",
                "Business proposal service is unavailable.",
                True,
            ) from exc
        body = _response_body(response)
        if response.status_code >= 400:
            raise BusinessProposalFacadeError(
                response.status_code,
                str(body.get("error_code") or "ae.business_proposal_request_failed"),
                str(body.get("detail") or "Business proposal request failed."),
                bool(body.get("retryable", response.status_code >= 500)),
            )
        return body, response.status_code


def build_default_eos_business_proposal_client() -> HttpEosBusinessProposalClient:
    return HttpEosBusinessProposalClient(
        base_url=os.getenv(
            "NEX_EOS_BASE_URL",
            DEFAULT_EOS_BUSINESS_PROPOSAL_BASE_URL,
        ),
        service_token=os.getenv("NEX_AE_TO_EOS_SERVICE_TOKEN"),
    )


def register_business_proposal_facade_routes(
    app: FastAPI,
    *,
    eos_client: EosBusinessProposalClient | None = None,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> None:
    client = eos_client or build_default_eos_business_proposal_client()

    @app.get("/api/v1/business-proposals", response_model=None)
    def list_business_proposals(
        request: Request,
        state: Annotated[list[str] | None, Query()] = None,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "GET",
            "/internal/v2/business-proposals",
            params=[("states", item) for item in (state or [])],
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    @app.post("/api/v1/business-proposals", response_model=None)
    def create_business_proposal(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "POST",
            "/internal/v2/business-proposals",
            payload=payload,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    @app.get("/api/v1/business-proposals/{proposal_id}", response_model=None)
    def get_business_proposal(
        proposal_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "GET",
            f"/internal/v2/business-proposals/{proposal_id}",
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    @app.patch("/api/v1/business-proposals/{proposal_id}", response_model=None)
    def revise_business_proposal(
        proposal_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "PATCH",
            f"/internal/v2/business-proposals/{proposal_id}",
            payload=payload,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    for suffix in ("preview-approval", "select-approval-line", "submit"):
        _register_proposal_command(
            app,
            suffix=suffix,
            client=client,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )


def _register_proposal_command(
    app: FastAPI,
    *,
    suffix: str,
    client: EosBusinessProposalClient,
    oa_session_client: OaUserSessionClient | None,
    session_mode: str | None,
) -> None:
    path = f"/api/v1/business-proposals/{{proposal_id}}:{suffix}"

    def command(
        proposal_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _forward(
            request,
            authorization,
            client,
            "POST",
            f"/internal/v2/business-proposals/{proposal_id}:{suffix}",
            payload=payload,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )

    command.__name__ = f"business_proposal_{suffix.replace('-', '_')}"
    app.post(path, response_model=None)(command)


def _forward(
    request: Request,
    authorization: str | None,
    client: EosBusinessProposalClient,
    method: str,
    path: str,
    *,
    params: list[tuple[str, str]] | None = None,
    payload: Mapping[str, Any] | None = None,
    oa_session_client: OaUserSessionClient | None,
    session_mode: str | None,
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
            error_code="ae.business_proposal_browser_session_required",
            title="AE business proposal browser session required",
            detail="Business proposal interaction requires an authenticated user.",
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
    except BusinessProposalFacadeError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="AE business proposal request failed",
            detail=exc.detail,
            retryable=exc.retryable,
        )
    return JSONResponse(dict(body), status_code=status_code)


def _response_body(response: httpx.Response) -> Mapping[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise BusinessProposalFacadeError(
            502,
            "ae.business_proposal_response_invalid",
            "Business proposal response is invalid.",
            True,
        ) from exc
    if not isinstance(body, Mapping):
        raise BusinessProposalFacadeError(
            502,
            "ae.business_proposal_response_invalid",
            "Business proposal response is invalid.",
            True,
        )
    return body
