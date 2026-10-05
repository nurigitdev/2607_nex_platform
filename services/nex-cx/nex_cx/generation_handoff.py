from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation_contracts import (
    CX_ASYNC_GENERATION_JOB_SCHEMA_VERSION,
    project_async_generation_job,
)
from nex_cx.citation_repair import (
    CitationRepairError,
    validate_citation_repair_projection,
)
from nex_cx.generation_lineage import (
    GroundedGenerationLineageError,
    validate_grounded_generation_lineage,
)
from nex_cx.generation_read_model import GenerationReadModel, GenerationReadModelError


CX_GENERATION_HANDOFF_SCHEMA_VERSION = "cx_generation_handoff.v1"
_HANDOFF_STATUSES = frozenset({"PENDING", "READY", "BLOCKED"})
_NEXT_ACTIONS = {
    "PENDING": "POLL_GENERATION_JOB",
    "READY": "PRESENT_GENERATION_TO_OWNER",
    "BLOCKED": "RETRY_OR_REPAIR_GENERATION",
}
_JOB_PROJECTION_FIELDS = frozenset(
    {
        "async_generation_schema_version",
        "job_id",
        "cx_generation_id",
        "status",
        "attempt_count",
        "max_attempts",
        "retryable",
        "available_at",
        "created_at",
        "updated_at",
        "links",
        "error",
    }
)


@dataclass(frozen=True)
class GenerationHandoffError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def build_generation_handoff(
    job: Mapping[str, Any],
    *,
    read_model: GenerationReadModel | None,
    access_context: CxAccessContext,
) -> dict[str, Any]:
    projected_job = project_async_generation_job(job)
    job_status = projected_job["status"]
    generation = None
    content = None

    if job_status in {"QUEUED", "RUNNING"}:
        handoff_status = "PENDING"
    elif job_status in {"FAILED", "CANCELLED"}:
        handoff_status = "BLOCKED"
    else:
        if read_model is None:
            raise GenerationHandoffError(
                error_code="cx.generation_handoff.read_model_unavailable",
                detail="Durable generation handoff is temporarily unavailable.",
                status_code=503,
                retryable=True,
            )
        generation_id = projected_job["cx_generation_id"]
        try:
            generation = read_model.get_metadata(
                generation_id,
                access_context=access_context,
            )
            if generation is None or generation.get("status") != "COMPLETED":
                raise GenerationHandoffError(
                    error_code="cx.generation_handoff.result_pending",
                    detail="Completed generation metadata is not yet available.",
                    status_code=503,
                    retryable=True,
                )
            content = read_model.get_content(
                generation_id,
                access_context=access_context,
            )
        except GenerationReadModelError as exc:
            raise GenerationHandoffError(
                error_code=exc.error_code,
                detail=exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        if content is None:
            raise GenerationHandoffError(
                error_code="cx.generation_handoff.content_pending",
                detail="Completed generation content is not yet available.",
                status_code=503,
                retryable=True,
            )
        handoff_status = "READY"

    return validate_generation_handoff(
        {
            "handoff_schema_version": CX_GENERATION_HANDOFF_SCHEMA_VERSION,
            "handoff_status": handoff_status,
            "next_action": _NEXT_ACTIONS[handoff_status],
            "job": projected_job,
            "generation": generation,
            "content": content,
            "owner_scope_enforced": True,
        }
    )


def validate_generation_handoff(value: object) -> dict[str, Any]:
    expected_fields = {
        "handoff_schema_version",
        "handoff_status",
        "next_action",
        "job",
        "generation",
        "content",
        "owner_scope_enforced",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise _invalid("Generation handoff has an invalid shape.")
    handoff = dict(value)
    if handoff["handoff_schema_version"] != CX_GENERATION_HANDOFF_SCHEMA_VERSION:
        raise _invalid("Generation handoff schema version is unsupported.")
    status = handoff["handoff_status"]
    if status not in _HANDOFF_STATUSES:
        raise _invalid("Generation handoff status is unsupported.")
    if handoff["next_action"] != _NEXT_ACTIONS[status]:
        raise _invalid("Generation handoff next action is inconsistent.")
    if handoff["owner_scope_enforced"] is not True:
        raise _invalid("Generation handoff owner scope must be enforced.")

    projected_job = _validate_job_projection(handoff["job"])
    expected_status = _handoff_status_for_job(projected_job["status"])
    if status != expected_status:
        raise _invalid("Generation handoff status does not match the job status.")

    generation = handoff["generation"]
    content = handoff["content"]
    if status != "READY":
        if generation is not None or content is not None:
            raise _invalid("Non-ready generation handoff must not expose content.")
        return {**handoff, "job": projected_job}

    generation_id = projected_job["cx_generation_id"]
    if (
        not isinstance(generation, Mapping)
        or generation.get("cx_generation_id") != generation_id
        or generation.get("status") != "COMPLETED"
    ):
        raise _invalid("Ready generation handoff metadata is inconsistent.")
    if (
        not isinstance(content, Mapping)
        or content.get("cx_generation_id") != generation_id
        or content.get("owner_scope_enforced") is not True
        or not isinstance(content.get("content"), str)
    ):
        raise _invalid("Ready generation handoff content is inconsistent.")
    _validate_grounding_lineage_handoff(generation)
    return {**handoff, "job": projected_job}


def _validate_grounding_lineage_handoff(generation: Mapping[str, Any]) -> None:
    metadata = generation.get("request_metadata")
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("grounding_required") is not True
    ):
        return
    try:
        lineage = validate_grounded_generation_lineage(
            metadata.get("grounding_lineage")
        )
    except GroundedGenerationLineageError as exc:
        raise _invalid("Ready grounded generation lineage is invalid.") from exc
    if generation.get("retrieval_package_id") != lineage["retrieval_package_id"]:
        raise _invalid("Ready grounded generation retrieval identity changed.")
    expected_values = {
        "retrieval_package_hash": lineage["retrieval_package_hash"],
        "selected_evidence_count": lineage["selected_evidence_count"],
        "provider_prompt_package_hash": lineage[
            "effective_provider_prompt_package_hash"
        ],
    }
    if any(
        metadata.get(field) != expected for field, expected in expected_values.items()
    ):
        raise _invalid("Ready grounded generation metadata does not match its lineage.")
    repair_value = metadata.get("citation_repair")
    if repair_value is None:
        if lineage["citation_repair_attempted"] is True:
            raise _invalid("Ready grounded generation repair lineage is unavailable.")
        return
    try:
        repair = validate_citation_repair_projection(repair_value)
    except CitationRepairError as exc:
        raise _invalid("Ready grounded generation repair metadata is invalid.") from exc
    if (
        repair["attempted"] != lineage["citation_repair_attempted"]
        or repair["attempt_count"] != lineage["citation_repair_attempt_count"]
        or repair["original_provider_prompt_package_hash"]
        != lineage["original_provider_prompt_package_hash"]
        or repair["effective_provider_prompt_package_hash"]
        != lineage["effective_provider_prompt_package_hash"]
    ):
        raise _invalid("Ready grounded generation repair metadata changed.")


def _validate_job_projection(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _JOB_PROJECTION_FIELDS:
        raise _invalid("Generation handoff job projection has an invalid shape.")
    job = deepcopy(dict(value))
    if job["async_generation_schema_version"] != (
        CX_ASYNC_GENERATION_JOB_SCHEMA_VERSION
    ):
        raise _invalid("Generation handoff job schema version is unsupported.")
    for field in ("job_id", "cx_generation_id", "created_at", "updated_at"):
        if not isinstance(job[field], str) or not job[field].strip():
            raise _invalid(f"Generation handoff job {field} is invalid.")
    if job["status"] not in {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}:
        raise _invalid("Generation handoff job status is unsupported.")
    if (
        isinstance(job["attempt_count"], bool)
        or not isinstance(job["attempt_count"], int)
        or job["attempt_count"] < 0
        or isinstance(job["max_attempts"], bool)
        or not isinstance(job["max_attempts"], int)
        or job["max_attempts"] < 1
        or job["attempt_count"] > job["max_attempts"]
    ):
        raise _invalid("Generation handoff job attempt counts are invalid.")
    if not isinstance(job["retryable"], bool) or not isinstance(job["links"], Mapping):
        raise _invalid("Generation handoff job metadata is invalid.")
    error = job["error"]
    if error is not None and (
        not isinstance(error, Mapping)
        or set(error) != {"error_code", "retryable", "dead_lettered"}
        or not isinstance(error.get("error_code"), str)
        or not isinstance(error.get("retryable"), bool)
        or not isinstance(error.get("dead_lettered"), bool)
    ):
        raise _invalid("Generation handoff job error projection is invalid.")
    return job


def _handoff_status_for_job(job_status: str) -> str:
    return {
        "QUEUED": "PENDING",
        "RUNNING": "PENDING",
        "FAILED": "BLOCKED",
        "CANCELLED": "BLOCKED",
        "SUCCEEDED": "READY",
    }[job_status]


def _invalid(detail: str) -> GenerationHandoffError:
    return GenerationHandoffError(
        error_code="cx.generation_handoff.invalid",
        detail=detail,
        status_code=422,
    )
