from __future__ import annotations

from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response

from nex_ae_api.agent_execution import AgentExecutionError, AgentRuntimeAdmission
from nex_ae_api.route_auth import authorize_ae_internal_service_request


class ClaimedWorkAdmission(Protocol):
    def admit_claimed_work(
        self,
        *,
        event_id: str,
        requester_ref: str,
        handoff: dict[str, Any],
        planning_source: dict[str, Any],
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
                planning_source=payload.get("planning_source"),
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
    result = authorize_ae_internal_service_request(
        request,
        authorization,
        allowed_service_ids=("nex-wc",),
        error_code="AE_CLAIM_HANDOFF_CALLER_DENIED",
        title="AE claim handoff caller denied",
        detail="Only nex-wc may deliver a ClaimExecutionHandoff.",
    )
    return result if isinstance(result, JSONResponse) else None
