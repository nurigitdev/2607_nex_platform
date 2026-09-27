from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_cx.access_context import CxAccessContext


CX_MVP_INTEGRATION_SCHEMA_VERSION = "cx_mvp_integration.v1"

INGESTION_STATUSES = frozenset(
    {"QUEUED", "RUNNING", "WAITING_RETRY", "SUCCEEDED", "FAILED", "CANCELLED"}
)
VECTOR_STATUSES = frozenset(
    {"BUILDING", "READY", "STALE", "REBUILD_REQUIRED", "FAILED"}
)
RETRIEVAL_STATUSES = frozenset(
    {"READY", "NO_ANSWER", "LOW_CONFIDENCE", "PARTIAL", "FAILED"}
)
GENERATION_JOB_STATUSES = frozenset(
    {"QUEUED", "RUNNING", "RETRY_SCHEDULED", "SUCCEEDED", "FAILED", "CANCELLED"}
)
GENERATION_STATUSES = frozenset(
    {"ACCEPTED", "RUNNING", "SUCCEEDED", "REJECTED", "FAILED", "CANCELLED"}
)

_STATE_FIELDS = frozenset(
    {
        "integration_schema_version",
        "integration_id",
        "tenant_ref",
        "owner_subject_ref",
        "document_id",
        "stage",
        "status",
        "next_action",
        "ingestion",
        "vector_index",
        "retrieval",
        "generation_job",
        "generation",
        "updated_at",
    }
)
_REF_FIELDS = frozenset({"id", "status"})
_HASH_REF_FIELDS = frozenset({"id", "status", "sha256"})


@dataclass(frozen=True)
class CxMvpIntegrationError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_cx_mvp_integration_state(
    *,
    access_context: CxAccessContext,
    document_id: str,
    updated_at: str,
    ingestion: Mapping[str, Any] | None = None,
    vector_index: Mapping[str, Any] | None = None,
    retrieval: Mapping[str, Any] | None = None,
    generation_job: Mapping[str, Any] | None = None,
    generation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_document_id = _identifier(document_id, "document_id")
    components = {
        "ingestion": _component(ingestion, INGESTION_STATUSES, "ingestion"),
        "vector_index": _component(
            vector_index, VECTOR_STATUSES, "vector_index"
        ),
        "retrieval": _component(
            retrieval, RETRIEVAL_STATUSES, "retrieval", hash_required=True
        ),
        "generation_job": _component(
            generation_job, GENERATION_JOB_STATUSES, "generation_job"
        ),
        "generation": _component(
            generation, GENERATION_STATUSES, "generation", hash_required=True
        ),
    }
    stage, status, next_action = _lifecycle(components)
    state = {
        "integration_schema_version": CX_MVP_INTEGRATION_SCHEMA_VERSION,
        "integration_id": str(
            uuid5(
                NAMESPACE_URL,
                (
                    "cx-mvp-integration:"
                    f"{access_context.tenant_id}:{access_context.subject_id}:"
                    f"{resolved_document_id}"
                ),
            )
        ),
        "tenant_ref": {"type": "oa.tenant", "id": access_context.tenant_id},
        "owner_subject_ref": {
            "type": "oa.user",
            "id": access_context.subject_id,
        },
        "document_id": resolved_document_id,
        "stage": stage,
        "status": status,
        "next_action": next_action,
        **components,
        "updated_at": _identifier(updated_at, "updated_at"),
    }
    return validate_cx_mvp_integration_state(state)


def validate_cx_mvp_integration_state(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _STATE_FIELDS:
        raise _invalid("CX MVP integration state has an invalid shape.")
    state = dict(value)
    if state["integration_schema_version"] != CX_MVP_INTEGRATION_SCHEMA_VERSION:
        raise _invalid("CX MVP integration schema version is unsupported.")
    for field in ("integration_id", "document_id", "stage", "status", "next_action", "updated_at"):
        _identifier(state[field], field)
    _typed_ref(state["tenant_ref"], "tenant_ref", "oa.tenant")
    _typed_ref(state["owner_subject_ref"], "owner_subject_ref", "oa.user")
    components = {
        "ingestion": _component(state["ingestion"], INGESTION_STATUSES, "ingestion"),
        "vector_index": _component(
            state["vector_index"], VECTOR_STATUSES, "vector_index"
        ),
        "retrieval": _component(
            state["retrieval"], RETRIEVAL_STATUSES, "retrieval", hash_required=True
        ),
        "generation_job": _component(
            state["generation_job"], GENERATION_JOB_STATUSES, "generation_job"
        ),
        "generation": _component(
            state["generation"], GENERATION_STATUSES, "generation", hash_required=True
        ),
    }
    expected = _lifecycle(components)
    if (state["stage"], state["status"], state["next_action"]) != expected:
        raise _invalid("CX MVP integration lifecycle projection is inconsistent.")
    return state


def _lifecycle(
    components: Mapping[str, Mapping[str, Any] | None],
) -> tuple[str, str, str]:
    ingestion = _status(components["ingestion"])
    vector = _status(components["vector_index"])
    retrieval = _status(components["retrieval"])
    job = _status(components["generation_job"])
    generation = _status(components["generation"])

    if ingestion in {"FAILED", "CANCELLED"}:
        return "INGESTION", "BLOCKED", "RETRY_INGESTION"
    if ingestion != "SUCCEEDED":
        return "INGESTION", "IN_PROGRESS", "POLL_INGESTION"
    if vector in {"FAILED", "STALE", "REBUILD_REQUIRED"}:
        return "INDEXING", "BLOCKED", "REBUILD_INDEX"
    if vector != "READY":
        return "INDEXING", "IN_PROGRESS", "POLL_INDEX"
    if retrieval in {"NO_ANSWER", "LOW_CONFIDENCE", "FAILED"}:
        return "RETRIEVAL", "BLOCKED", "REVISE_RETRIEVAL"
    if retrieval not in {"READY", "PARTIAL"}:
        return "RETRIEVAL", "READY", "CREATE_RETRIEVAL_PACKAGE"
    if job in {"FAILED", "CANCELLED"} or generation in {
        "REJECTED",
        "FAILED",
        "CANCELLED",
    }:
        return "GENERATION", "BLOCKED", "RETRY_OR_REPAIR_GENERATION"
    if generation == "SUCCEEDED":
        return "HANDOFF", "READY", "READ_GENERATION_HANDOFF"
    if job == "SUCCEEDED":
        return "GENERATION", "IN_PROGRESS", "POLL_GENERATION_RESULT"
    if job in {"QUEUED", "RUNNING", "RETRY_SCHEDULED"} or generation in {
        "ACCEPTED",
        "RUNNING",
    }:
        return "GENERATION", "IN_PROGRESS", "POLL_GENERATION_JOB"
    return "GENERATION", "READY", "CREATE_GENERATION_JOB"


def _component(
    value: object,
    allowed_statuses: frozenset[str],
    field: str,
    *,
    hash_required: bool = False,
) -> dict[str, Any] | None:
    if value is None:
        return None
    expected_fields = _HASH_REF_FIELDS if hash_required else _REF_FIELDS
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise _invalid(f"{field} reference has an invalid shape.")
    component_id = _identifier(value.get("id"), f"{field}.id")
    status = value.get("status")
    if status not in allowed_statuses:
        raise _invalid(f"{field} status is unsupported.")
    result = {"id": component_id, "status": status}
    if hash_required:
        result["sha256"] = _sha256(value.get("sha256"), f"{field}.sha256")
    return result


def _typed_ref(value: object, field: str, expected_type: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "id"}
        or value.get("type") != expected_type
    ):
        raise _invalid(f"{field} must be a {expected_type} reference.")
    return {"type": expected_type, "id": _identifier(value.get("id"), f"{field}.id")}


def _status(value: Mapping[str, Any] | None) -> str | None:
    return None if value is None else str(value["status"])


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    normalized = _identifier(value, field)
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise _invalid(f"{field} must be a lowercase SHA-256 value.")
    return normalized


def _invalid(detail: str) -> CxMvpIntegrationError:
    return CxMvpIntegrationError(
        error_code="cx.mvp_integration.invalid",
        detail=detail,
    )
