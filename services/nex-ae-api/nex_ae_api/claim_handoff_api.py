from __future__ import annotations

from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_ae_api.agent_execution import AgentExecutionError, AgentRuntimeAdmission
from nex_runtime import DEFAULT_SERVICE_SCOPE, problem_response
from nex_runtime.auth import validate_authorization_header


class ClaimedWorkAdmission(Protocol):
    def admit_claimed_work(
        self,
        *,
        event_id: str,
        requester_ref: str,
        handoff: dict[str, Any],
    ) -> AgentRuntimeAdmission: ...


def register_claim_handoff_routes(
    app: FastAPI, *, admission: ClaimedWorkAdmission | None
) -> None:
    @app.post("/internal/v1/work-handoffs", response_model=None)
    def admit_claim_handoff(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = _authorize(request, authorization)
        if denied is not None:
            return denied
        if admission is None:
            return problem_response(
                request,
                status_code=503,
                error_code="AE_CLAIM_HANDOFF_UNAVAILABLE",
                title="AE claim handoff unavailable",
                detail="AE claimed-work admission is not configured.",
                retryable=True,
            )
        try:
            if payload.get("event_type") != "CLAIM_EXECUTION_HANDOFF":
                raise AgentExecutionError(
                    "ae.claim_handoff_event_type_invalid",
                    "Claim handoff event_type is invalid.",
                )
            result = admission.admit_claimed_work(
                event_id=payload.get("event_id"),
                requester_ref=payload.get("requester_ref"),
                handoff=payload.get("handoff"),
            )
            return {
                "schema_version": "ae_claim_handoff_admission.v1",
                "mode": result.mode,
                "execution": result.execution,
            }
        except AgentExecutionError as exc:
            return problem_response(
                request,
                status_code=503 if exc.retryable else 409,
                error_code=exc.error_code,
                title="AE claim handoff admission failed",
                detail=exc.detail,
                retryable=exc.retryable,
            )


def _authorize(request: Request, authorization: str | None) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    if not result.ok or result.claims is None:
        return problem_response(
            request,
            status_code=401,
            error_code=result.error_code or "AE_CLAIM_HANDOFF_AUTH_FAILED",
            title="AE claim handoff authorization failed",
            detail=result.detail or "AE claim handoff authorization failed.",
            retryable=False,
        )
    if result.claims.service_id != "nex-wc":
        return problem_response(
            request,
            status_code=403,
            error_code="AE_CLAIM_HANDOFF_CALLER_DENIED",
            title="AE claim handoff caller denied",
            detail="Only nex-wc may deliver a ClaimExecutionHandoff.",
            retryable=False,
        )
    return None
