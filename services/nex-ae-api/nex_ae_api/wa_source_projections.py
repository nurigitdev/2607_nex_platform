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
from nex_ae_api.artifacts import ArtifactHandoffError, SqlAlchemyArtifactRecordStore

WORK_SOURCE_READ_SCOPE = "work:source:read"
AGENT_RESULT_PROJECTION_SCHEMA_VERSION = "wa_agent_result_source_projection.v1"
ARTIFACT_PROJECTION_SCHEMA_VERSION = "wa_artifact_source_projection.v1"
DEFAULT_ARTIFACT_CLASSIFICATION = "CONFIDENTIAL"


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


class ArtifactWaProjectionSource(Protocol):
    def get_projection(
        self,
        *,
        tenant_id: str,
        artifact_id: str,
        artifact_version_id: str,
    ) -> dict[str, Any] | None: ...


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


class SqlAlchemyArtifactWaProjectionSource:
    def __init__(self, repository: SqlAlchemyArtifactRecordStore) -> None:
        self._repository = repository

    def get_projection(
        self,
        *,
        tenant_id: str,
        artifact_id: str,
        artifact_version_id: str,
    ) -> dict[str, Any] | None:
        try:
            record = self._repository.get(artifact_id)
        except ArtifactHandoffError as exc:
            raise WaSourceProjectionError(
                exc.error_code,
                exc.detail,
                exc.retryable,
            ) from exc
        if record is None or not _artifact_belongs_to_tenant(record, tenant_id):
            return None
        return build_artifact_wa_projection(
            record,
            artifact_version_id=artifact_version_id,
        )


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


def build_artifact_wa_projection(
    record: dict[str, Any],
    *,
    artifact_version_id: str,
) -> dict[str, Any] | None:
    if record.get("artifact_status") != "READY":
        raise WaSourceProjectionError(
            "ae.wa_source_artifact_not_ready",
            "Only READY Artifact versions are admissible WA sources.",
        )
    versions = record.get("versions")
    if not isinstance(versions, list):
        raise _invalid_artifact_projection("Artifact versions must be an array.")
    version = next(
        (
            item
            for item in versions
            if isinstance(item, dict)
            and item.get("artifact_version_id") == artifact_version_id
        ),
        None,
    )
    if version is None:
        return None
    artifact_id = str(record.get("artifact_id") or "")
    if version.get("artifact_id") != artifact_id:
        raise _invalid_artifact_projection(
            "Artifact version identity does not match its Artifact."
        )
    source_hash = _sha256_digest(version.get("source_content_hash"), "source")
    artifact_hash = _sha256_digest(
        version.get("artifact_content_hash"),
        "artifact",
    )
    source_refs = record.get("source_refs")
    if not isinstance(source_refs, list) or not any(
        isinstance(source_ref, dict)
        and source_ref.get("structured_draft_content_hash") == source_hash
        for source_ref in source_refs
    ):
        raise WaSourceProjectionError(
            "ae.wa_source_artifact_content_hash_mismatch",
            "Artifact version source hash does not match authoritative source lineage.",
        )
    owner_actor_ref = _tenant_exact_ref(
        record.get("owner_actor_ref"),
        "owner",
        ("actor_type", "actor_id", "tenant_id"),
    )
    workspace_ref = _tenant_exact_ref(
        record.get("workspace_ref"),
        "workspace",
        ("workspace_id", "tenant_id"),
    )
    if owner_actor_ref["tenant_id"] != workspace_ref["tenant_id"]:
        raise _invalid_artifact_projection(
            "Artifact owner and workspace tenant lineage is inconsistent."
        )
    producer_execution_ref = record.get("producer_execution_ref")
    if not isinstance(producer_execution_ref, str) or not producer_execution_ref:
        producer_execution_ref = None
    return {
        "projection_schema_version": ARTIFACT_PROJECTION_SCHEMA_VERSION,
        "tenant_id": owner_actor_ref["tenant_id"],
        "artifact_id": artifact_id,
        "artifact_version_id": artifact_version_id,
        "artifact_status": "READY",
        "owner_actor_ref": owner_actor_ref,
        "workspace_ref": workspace_ref,
        "source_content_hash": source_hash,
        "artifact_content_hash": artifact_hash,
        "created_at": str(version.get("created_at") or ""),
        "classification": DEFAULT_ARTIFACT_CLASSIFICATION,
        "producer_execution_ref": producer_execution_ref,
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


def register_wa_artifact_source_routes(
    app: FastAPI,
    *,
    source: ArtifactWaProjectionSource | None,
) -> None:
    app.state.ae_wa_artifact_source = source

    @app.get(
        "/internal/v1/wa-sources/artifacts/{artifact_id}/versions/{artifact_version_id}",
        response_model=None,
    )
    def get_wa_artifact_source(
        artifact_id: str,
        artifact_version_id: str,
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
                "AE WA Artifact source projection is unavailable.",
                retryable=True,
            )
        try:
            projection = source.get_projection(
                tenant_id=tenant_id.strip(),
                artifact_id=artifact_id,
                artifact_version_id=artifact_version_id,
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
                "ae.wa_source_artifact_version_not_found",
                "Artifact version was not found in this tenant scope.",
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


def _artifact_belongs_to_tenant(record: dict[str, Any], tenant_id: str) -> bool:
    owner = record.get("owner_actor_ref")
    workspace = record.get("workspace_ref")
    return (
        isinstance(owner, dict)
        and isinstance(workspace, dict)
        and owner.get("tenant_id") == tenant_id
        and workspace.get("tenant_id") == tenant_id
    )


def _tenant_exact_ref(
    value: object,
    label: str,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(value, dict) or any(
        not isinstance(value.get(field), str) or not value[field]
        for field in fields
    ):
        raise _invalid_artifact_projection(
            f"Artifact {label} reference must contain exact bounded lineage."
        )
    return {field: value[field] for field in fields}


def _sha256_digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _invalid_artifact_projection(
            f"Artifact {label} content hash must be a SHA-256 digest."
        )
    return value


def _invalid_artifact_projection(detail: str) -> WaSourceProjectionError:
    return WaSourceProjectionError("ae.wa_source_artifact_invalid", detail)


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
