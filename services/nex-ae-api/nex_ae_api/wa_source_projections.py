from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    AdmittedServiceClaims,
    admit_service_token_from_request,
    problem_response,
)

from nex_ae_api.agent_results import (
    AgentResultAggregate,
    AgentResultError,
    SqlAlchemyAgentResultRepository,
)

WORK_SOURCE_READ_SCOPE = "work:source:read"
AGENT_RESULT_PROJECTION_SCHEMA_VERSION = "wa_agent_result_source_projection.v1"


@dataclass(frozen=True)
class WaSourceProjectionError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class AgentResultWaProjectionSource(Protocol):
    def get_projection(self, *, tenant_id: str, result_id: str) -> dict[str, Any] | None:
        ...


class SqlAlchemyAgentResultWaProjectionSource:
    def __init__(self, repository: SqlAlchemyAgentResultRepository) -> None:
        self._repository = repository

    def get_projection(self, *, tenant_id: str, result_id: str) -> dict[str, Any] | None:
        try:
            aggregate = self._repository.get(tenant_id, result_id)
        except AgentResultError as exc:
            raise WaSourceProjectionError(
                exc.error_code,
                exc.detail,
                exc.retryable,
            ) from exc
        if aggregate is None:
            return None
        return build_agent_result_wa_projection(aggregate)


def build_agent_result_wa_projection(
    aggregate: AgentResultAggregate,
) -> dict[str, Any]:
    result = aggregate.result
    delivery = aggregate.delivery
    execution = aggregate.execution
    if not delivery.get("required"):
        raise WaSourceProjectionError(
            "ae.wa_source_required_delivery_missing",
            "AgentResult WA projection requires its authoritative delivery.",
        )
    if str(delivery.get("result_id")) != str(result.get("result_id")):
        raise WaSourceProjectionError(
            "ae.wa_source_delivery_lineage_invalid",
            "AgentResult delivery does not match the requested result.",
        )
    if str(execution.get("agent_execution_id")) != str(
        result.get("agent_execution_id")
    ):
        raise WaSourceProjectionError(
            "ae.wa_source_execution_lineage_invalid",
            "AgentResult execution lineage is inconsistent.",
        )
    return {
        "projection_schema_version": AGENT_RESULT_PROJECTION_SCHEMA_VERSION,
        "tenant_id": str(result["tenant_id"]),
        "result_id": str(result["result_id"]),
        "agent_execution_id": str(result["agent_execution_id"]),
        "agent_id": str(result["agent_id"]),
        "agent_type": str(result["agent_type"]),
        "project_id": result.get("project_id"),
        "status": str(result["status"]),
        "result_hash": str(result["result_hash"]),
        "artifact_refs": _bounded_refs(result.get("artifact_refs")),
        "evidence_refs": _bounded_refs(result.get("evidence_refs")),
        "business_refs": _bounded_refs(result.get("business_refs")),
        "source_work_item_ref": result.get("source_work_item_ref"),
        "source_claim_ref": result.get("source_claim_ref"),
        "source_claim_generation": result.get("source_claim_generation"),
        "source_assignment_ref": result.get("source_assignment_ref"),
        "created_at": str(result["created_at"]),
        "agent_execution_state": str(execution["state"]),
        "required_delivery_target_type": str(delivery["target_type"]),
        "required_delivery_state": str(delivery["state"]),
        "required_delivery_ref": str(delivery["delivery_id"]),
        "delivery_acknowledged_at": delivery.get("acknowledged_at"),
    }


def register_wa_agent_result_source_routes(
    app: FastAPI,
    *,
    source: AgentResultWaProjectionSource | None,
) -> None:
    app.state.ae_wa_agent_result_source = source

    @app.get(
        "/internal/v1/wa-sources/agent-results/{result_id}",
        response_model=None,
    )
    def get_wa_agent_result_source(
        result_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Header(default=None, alias="X-NeX-Tenant-Id"),
    ):
        admitted = _admit_wa_source_request(request, authorization)
        if isinstance(admitted, JSONResponse):
            return admitted
        if tenant_id is None or not tenant_id.strip():
            return _problem(
                request,
                400,
                "ae.wa_source_tenant_required",
                "WA source projection requires X-NeX-Tenant-Id.",
            )
        if source is None:
            return _problem(
                request,
                503,
                "ae.wa_source_unavailable",
                "AE WA source projection is unavailable.",
                retryable=True,
            )
        try:
            projection = source.get_projection(
                tenant_id=tenant_id.strip(),
                result_id=result_id,
            )
        except WaSourceProjectionError as exc:
            return _problem(
                request,
                503 if exc.retryable else 409,
                exc.error_code,
                exc.detail,
                retryable=exc.retryable,
            )
        if projection is None:
            return _problem(
                request,
                404,
                "ae.wa_source_agent_result_not_found",
                "AgentResult was not found in this tenant scope.",
            )
        return projection


def _admit_wa_source_request(
    request: Request,
    authorization: str | None,
) -> AdmittedServiceClaims | JSONResponse:
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=(DEFAULT_SERVICE_SCOPE, WORK_SOURCE_READ_SCOPE),
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    if admitted.service_id != "nex-wa":
        return _problem(
            request,
            403,
            "ae.wa_source_caller_forbidden",
            "WA source projections are available only to NeX-WA.",
        )
    return admitted


def _bounded_refs(value: object) -> list[str]:
    if not isinstance(value, list):
        raise WaSourceProjectionError(
            "ae.wa_source_projection_invalid",
            "AgentResult reference fields must be arrays.",
        )
    refs = [str(item) for item in value if isinstance(item, str) and item]
    if len(refs) != len(value) or len(refs) > 100:
        raise WaSourceProjectionError(
            "ae.wa_source_projection_invalid",
            "AgentResult reference fields must contain at most 100 bounded refs.",
        )
    return refs


def _problem(
    request: Request,
    status_code: int,
    error_code: str,
    detail: str,
    *,
    retryable: bool = False,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=status_code,
        error_code=error_code,
        title="AE WA source projection failed",
        detail=detail,
        retryable=retryable,
        type_uri="https://nex-platform.local/problems/ae-wa-source-projection",
    )
