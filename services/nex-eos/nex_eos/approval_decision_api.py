from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .approval_transitions import (
    EosApprovalTransitionError,
    EosBusinessApprovalTransitionService,
)


def register_approval_decision_routes(app: FastAPI) -> None:
    @app.post("/internal/v1/approval-decision-events", response_model=None)
    def ingest_approval_decision_event(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        if admitted.service_id != "nex-ae-api":
            return problem_response(
                request,
                status_code=403,
                error_code="EOS_APPROVAL_DECISION_CALLER_DENIED",
                title="EOS approval decision caller denied",
                detail="Only nex-ae-api may deliver a business approval decision.",
                retryable=False,
            )
        service: EosBusinessApprovalTransitionService | None = getattr(
            request.app.state, "eos_approval_transition_service", None
        )
        if service is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_APPROVAL_TRANSITION_UNAVAILABLE",
                title="EOS approval transition unavailable",
                detail="EOS approval transition dependencies are not configured.",
                retryable=True,
            )
        try:
            outbox_id, work_item, decision, event = _delivery(payload)
            approval_instance_id = _approval_instance_id(work_item)
            result = service.advance_from_wc_decision(
                tenant_id=event["tenant_id"],
                approval_instance_id=approval_instance_id,
                work_item=work_item,
                decision=decision,
                event=event,
            )
        except ApprovalDecisionApiError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS approval decision admission failed",
                detail=exc.detail,
                retryable=False,
            )
        except EosApprovalTransitionError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS approval decision transition failed",
                detail=exc.detail,
                retryable=exc.retryable,
            )
        return {
            "schema_version": "eos_approval_decision_receipt.v1",
            "outbox_id": outbox_id,
            "event_id": event["event_id"],
            "approval_domain": "BUSINESS_FORMAL",
            "approval_instance_id": approval_instance_id,
            "transition_state": result["instance"]["state"],
        }


class ApprovalDecisionApiError(ValueError):
    def __init__(self, error_code: str, detail: str, status_code: int = 400) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _delivery(
    value: Mapping[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    if value.get("schema_version") != "wc_approval_delivery.v1":
        raise _invalid("WC approval delivery schema is invalid.")
    outbox_id = _required(value.get("outbox_id"), "outbox_id")
    work_item = _mapping(value.get("work_item"), "work_item")
    decision = _mapping(value.get("decision"), "decision")
    event = _mapping(value.get("event"), "event")
    if work_item.get("approval_domain") != "BUSINESS_FORMAL":
        raise _invalid("EOS accepts only BUSINESS_FORMAL approval decisions.")
    expected = {
        "tenant_id": event.get("tenant_id"),
        "approval_work_item_id": event.get("approval_work_item_id"),
    }
    if any(work_item.get(name) != item for name, item in expected.items()):
        raise _invalid("WC approval work-item lineage differs.")
    if any(decision.get(name) != item for name, item in expected.items()):
        raise _invalid("WC approval decision lineage differs.")
    if decision.get("decision_id") != event.get("decision_id"):
        raise _invalid("WC approval decision event identity differs.")
    return outbox_id, work_item, decision, event


def _approval_instance_id(work_item: Mapping[str, Any]) -> str:
    value = _required(work_item.get("resume_target_ref"), "resume_target_ref")
    prefix = "eos.approval-instance:"
    if not value.startswith(prefix) or ":stage:" not in value:
        raise _invalid("EOS approval resume target is invalid.")
    candidate = value.removeprefix(prefix).partition(":stage:")[0]
    try:
        return str(UUID(candidate))
    except ValueError as exc:
        raise _invalid("EOS approval instance identity is invalid.") from exc


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"Approval delivery {field} must be an object.")
    return dict(value)


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"Approval delivery {field} is invalid.")
    return value.strip()


def _invalid(detail: str) -> ApprovalDecisionApiError:
    return ApprovalDecisionApiError("eos.approval_decision_invalid", detail)
