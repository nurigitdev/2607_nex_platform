from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
from typing import Any, Mapping


AE_ASYNC_GENERATION_SCHEMA_VERSION = "ae_async_generation.v1"
SYNCHRONOUS = "SYNCHRONOUS"
ASYNCHRONOUS = "ASYNCHRONOUS"
EXECUTION_STRATEGIES = frozenset({SYNCHRONOUS, ASYNCHRONOUS})
CX_JOB_STATUSES = frozenset(
    {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}
)
ADMISSION_STATUSES = frozenset({"ENQUEUED", "JOINED", "REPLAYED"})
HANDOFF_STATUSES = frozenset({"PENDING", "READY", "BLOCKED"})
AE_ASYNC_GENERATION_REFRESH_SCHEMA_VERSION = "ae_async_generation_refresh.v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_PROJECTION_FIELDS = frozenset(
    {
        "async_generation_schema_version",
        "execution_strategy",
        "lifecycle_status",
        "admission_status",
        "job_id",
        "cx_generation_id",
        "cx_job_status",
        "attempt_count",
        "max_attempts",
        "retryable",
        "handoff_status",
        "next_action",
        "error",
        "links",
        "owner_scope_enforced",
        "content_included",
    }
)


@dataclass(frozen=True)
class AeAsyncGenerationError(ValueError):
    error_code: str
    detail: str
    status_code: int = 422
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def resolve_execution_strategy(source_payload: Mapping[str, Any]) -> str:
    if not isinstance(source_payload, Mapping):
        raise _invalid_request("Chat request must be an object.")
    generation = source_payload.get("generation")
    if generation is None:
        return SYNCHRONOUS
    if not isinstance(generation, Mapping):
        raise _invalid_request("generation must be an object when supplied.")
    value = generation.get("execution_strategy", SYNCHRONOUS)
    if not isinstance(value, str) or not value.strip():
        raise _invalid_request(
            "generation.execution_strategy must be a non-empty string."
        )
    strategy = value.strip().upper()
    if strategy not in EXECUTION_STRATEGIES:
        raise _invalid_request(
            f"Unsupported generation.execution_strategy: {value.strip()}"
        )
    return strategy


def build_async_generation_projection(
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(admission, Mapping):
        raise _invalid_contract("CX async admission must be an object.")
    admission_status = admission.get("admission_status")
    if admission_status not in ADMISSION_STATUSES:
        raise _invalid_contract("CX async admission status is invalid.")
    job = admission.get("job")
    if not isinstance(job, Mapping):
        raise AeAsyncGenerationError(
            error_code="ae.async_generation.durable_job_missing",
            detail="CX async admission did not return a durable job projection.",
            status_code=503,
            retryable=True,
        )
    normalized_job = _validate_cx_job_projection(job)
    lifecycle_status, next_action = _ae_state_for_job(normalized_job["status"])
    return validate_async_generation_projection(
        {
            "async_generation_schema_version": AE_ASYNC_GENERATION_SCHEMA_VERSION,
            "execution_strategy": ASYNCHRONOUS,
            "lifecycle_status": lifecycle_status,
            "admission_status": admission_status,
            "job_id": normalized_job["job_id"],
            "cx_generation_id": normalized_job["cx_generation_id"],
            "cx_job_status": normalized_job["status"],
            "attempt_count": normalized_job["attempt_count"],
            "max_attempts": normalized_job["max_attempts"],
            "retryable": normalized_job["retryable"],
            "handoff_status": None,
            "next_action": next_action,
            "error": normalized_job["error"],
            "links": normalized_job["links"],
            "owner_scope_enforced": True,
            "content_included": False,
        }
    )


def validate_async_generation_projection(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROJECTION_FIELDS:
        raise _invalid_contract("AE async generation projection has an invalid shape.")
    projection = deepcopy(dict(value))
    if projection["async_generation_schema_version"] != (
        AE_ASYNC_GENERATION_SCHEMA_VERSION
    ):
        raise _invalid_contract("AE async generation schema version is invalid.")
    if projection["execution_strategy"] != ASYNCHRONOUS:
        raise _invalid_contract("AE async generation execution strategy is invalid.")
    if projection["admission_status"] not in ADMISSION_STATUSES:
        raise _invalid_contract("AE async generation admission status is invalid.")
    for field in ("job_id", "cx_generation_id"):
        if not isinstance(projection[field], str) or not projection[field].strip():
            raise _invalid_contract(f"AE async generation {field} is invalid.")
    if projection["cx_job_status"] not in CX_JOB_STATUSES:
        raise _invalid_contract("AE async generation CX job status is invalid.")
    _validate_attempts(projection)
    if not isinstance(projection["retryable"], bool):
        raise _invalid_contract("AE async generation retryable flag is invalid.")
    handoff_status = projection["handoff_status"]
    if handoff_status is not None and handoff_status not in HANDOFF_STATUSES:
        raise _invalid_contract("AE async generation handoff status is invalid.")
    expected_status, expected_action = _ae_state(
        projection["cx_job_status"], handoff_status
    )
    if projection["lifecycle_status"] != expected_status:
        raise _invalid_contract("AE async generation lifecycle status is inconsistent.")
    if projection["next_action"] != expected_action:
        raise _invalid_contract("AE async generation next action is inconsistent.")
    if projection["owner_scope_enforced"] is not True:
        raise _invalid_contract("AE async generation owner scope must be enforced.")
    if projection["content_included"] is not False:
        raise _invalid_contract("AE async generation projection must not include content.")
    projection["error"] = _safe_error(projection["error"])
    projection["links"] = _safe_links(projection["links"])
    return projection


def refresh_async_generation_projection(
    current: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    projection = validate_async_generation_projection(current)
    normalized = _validate_cx_handoff(handoff)
    job = normalized["job"]
    if (
        job["job_id"] != projection["job_id"]
        or job["cx_generation_id"] != projection["cx_generation_id"]
    ):
        raise _invalid_contract("CX generation handoff lineage is inconsistent.")
    handoff_status = normalized["handoff_status"]
    lifecycle_status, next_action = _ae_state(job["status"], handoff_status)
    refreshed = validate_async_generation_projection(
        {
            **projection,
            "lifecycle_status": lifecycle_status,
            "cx_job_status": job["status"],
            "attempt_count": job["attempt_count"],
            "max_attempts": job["max_attempts"],
            "retryable": job["retryable"],
            "handoff_status": handoff_status,
            "next_action": next_action,
            "error": job["error"],
            "links": job["links"],
        }
    )
    return refreshed, _build_refresh_result(normalized)


def refresh_async_generation_job_projection(
    current: Mapping[str, Any],
    job: Mapping[str, Any],
) -> dict[str, Any]:
    projection = validate_async_generation_projection(current)
    normalized_job = _validate_cx_job_projection(job)
    if (
        normalized_job["job_id"] != projection["job_id"]
        or normalized_job["cx_generation_id"] != projection["cx_generation_id"]
    ):
        raise _invalid_contract("CX async job lineage is inconsistent.")
    lifecycle_status, next_action = _ae_state(normalized_job["status"], None)
    return validate_async_generation_projection(
        {
            **projection,
            "lifecycle_status": lifecycle_status,
            "cx_job_status": normalized_job["status"],
            "attempt_count": normalized_job["attempt_count"],
            "max_attempts": normalized_job["max_attempts"],
            "retryable": normalized_job["retryable"],
            "handoff_status": None,
            "next_action": next_action,
            "error": normalized_job["error"],
            "links": normalized_job["links"],
        }
    )


def _validate_cx_job_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "job_id",
        "cx_generation_id",
        "status",
        "attempt_count",
        "max_attempts",
        "retryable",
        "links",
        "error",
    }
    if not required.issubset(value):
        raise _invalid_contract("CX async job projection is incomplete.")
    job = {field: deepcopy(value[field]) for field in required}
    for field in ("job_id", "cx_generation_id"):
        if not isinstance(job[field], str) or not job[field].strip():
            raise _invalid_contract(f"CX async job {field} is invalid.")
    if job["status"] not in CX_JOB_STATUSES:
        raise _invalid_contract("CX async job status is invalid.")
    _validate_attempts(job)
    if not isinstance(job["retryable"], bool):
        raise _invalid_contract("CX async job retryable flag is invalid.")
    job["error"] = _safe_error(job["error"])
    job["links"] = _safe_links(job["links"])
    return job


def _validate_cx_handoff(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid_contract("CX generation handoff must be an object.")
    required = {
        "handoff_schema_version",
        "handoff_status",
        "next_action",
        "job",
        "generation",
        "content",
        "owner_scope_enforced",
    }
    if set(value) != required:
        raise _invalid_contract("CX generation handoff has an invalid shape.")
    if value["handoff_schema_version"] != "cx_generation_handoff.v1":
        raise _invalid_contract("CX generation handoff schema version is invalid.")
    status = value["handoff_status"]
    if status not in HANDOFF_STATUSES:
        raise _invalid_contract("CX generation handoff status is invalid.")
    expected_action = {
        "PENDING": "POLL_GENERATION_JOB",
        "READY": "PRESENT_GENERATION_TO_OWNER",
        "BLOCKED": "RETRY_OR_REPAIR_GENERATION",
    }[status]
    if value["next_action"] != expected_action:
        raise _invalid_contract("CX generation handoff next action is inconsistent.")
    if value["owner_scope_enforced"] is not True:
        raise _invalid_contract("CX generation handoff owner scope is not enforced.")
    if not isinstance(value["job"], Mapping):
        raise _invalid_contract("CX generation handoff job is invalid.")
    job = _validate_cx_job_projection(value["job"])
    expected_lifecycle, _ = _ae_state(job["status"], status)
    if status != "READY":
        if value["generation"] is not None or value["content"] is not None:
            raise _invalid_contract("Non-ready CX handoff must not expose content.")
        return {**dict(value), "job": job, "lifecycle_status": expected_lifecycle}

    generation = value["generation"]
    content = value["content"]
    if (
        not isinstance(generation, Mapping)
        or generation.get("cx_generation_id") != job["cx_generation_id"]
        or generation.get("status") != "COMPLETED"
    ):
        raise _invalid_contract("Ready CX generation metadata is inconsistent.")
    normalized_content = _validate_handoff_content(content, job["cx_generation_id"])
    return {
        **dict(value),
        "job": job,
        "generation": deepcopy(dict(generation)),
        "content": normalized_content,
        "lifecycle_status": expected_lifecycle,
    }


def _validate_handoff_content(value: object, generation_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid_contract("Ready CX handoff content is invalid.")
    content = value.get("content")
    digest = value.get("content_sha256")
    size_bytes = value.get("size_bytes")
    if (
        value.get("cx_generation_id") != generation_id
        or value.get("owner_scope_enforced") is not True
        or not isinstance(content, str)
        or not isinstance(value.get("content_type"), str)
        or not value["content_type"].strip()
        or not isinstance(digest, str)
        or _SHA256_PATTERN.fullmatch(digest) is None
        or isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
    ):
        raise _invalid_contract("Ready CX handoff content metadata is invalid.")
    encoded = content.encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != digest or len(encoded) != size_bytes:
        raise _invalid_contract("Ready CX handoff content integrity check failed.")
    return {
        "cx_generation_id": generation_id,
        "content_type": value["content_type"].strip(),
        "content": content,
        "content_sha256": digest,
        "size_bytes": size_bytes,
        "owner_scope_enforced": True,
    }


def _build_refresh_result(handoff: Mapping[str, Any]) -> dict[str, Any]:
    content = handoff["content"]
    return {
        "refresh_schema_version": AE_ASYNC_GENERATION_REFRESH_SCHEMA_VERSION,
        "handoff_status": handoff["handoff_status"],
        "cx_generation_id": handoff["job"]["cx_generation_id"],
        "content": content["content"] if content is not None else None,
        "content_type": content["content_type"] if content is not None else None,
        "content_sha256": (
            content["content_sha256"] if content is not None else None
        ),
        "size_bytes": content["size_bytes"] if content is not None else None,
        "owner_scope_enforced": True,
    }


def _validate_attempts(value: Mapping[str, Any]) -> None:
    attempt_count = value.get("attempt_count")
    max_attempts = value.get("max_attempts")
    if (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count < 0
        or isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts < 1
        or attempt_count > max_attempts
    ):
        raise _invalid_contract("Async generation attempt counts are invalid.")


def _safe_error(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "error_code",
        "retryable",
        "dead_lettered",
    }:
        raise _invalid_contract("Async generation error projection is invalid.")
    error_code = value.get("error_code")
    if not isinstance(error_code, str) or not error_code.strip():
        raise _invalid_contract("Async generation error code is invalid.")
    if not isinstance(value.get("retryable"), bool) or not isinstance(
        value.get("dead_lettered"), bool
    ):
        raise _invalid_contract("Async generation error flags are invalid.")
    return {
        "error_code": error_code.strip(),
        "retryable": value["retryable"],
        "dead_lettered": value["dead_lettered"],
    }


def _safe_links(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise _invalid_contract("Async generation links are invalid.")
    allowed = {"generation", "async_job"}
    if not set(value).issubset(allowed):
        raise _invalid_contract("Async generation links contain an unsafe key.")
    links: dict[str, str] = {}
    for key, link in value.items():
        if not isinstance(link, str) or not link.startswith("/api/v1/"):
            raise _invalid_contract("Async generation link is invalid.")
        links[str(key)] = link
    return links


def _ae_state_for_job(status: str) -> tuple[str, str]:
    return _ae_state(status, None)


def _ae_state(status: str, handoff_status: str | None) -> tuple[str, str]:
    if handoff_status == "READY" and status == "SUCCEEDED":
        return "COMPLETED", "PRESENT_GENERATION_TO_OWNER"
    if handoff_status == "BLOCKED" and status in {"FAILED", "CANCELLED"}:
        return "BLOCKED", "RETRY_OR_REVIEW_GENERATION"
    if handoff_status in {None, "PENDING"} and status in {
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
    }:
        return "PENDING", "POLL_GENERATION_HANDOFF"
    if handoff_status is None and status in {"FAILED", "CANCELLED"}:
        return "BLOCKED", "RETRY_OR_REVIEW_GENERATION"
    raise _invalid_contract("Async generation job and handoff status are inconsistent.")


def _invalid_request(detail: str) -> AeAsyncGenerationError:
    return AeAsyncGenerationError(
        error_code="ae.async_generation.execution_strategy_invalid",
        detail=detail,
        status_code=400,
    )


def _invalid_contract(detail: str) -> AeAsyncGenerationError:
    return AeAsyncGenerationError(
        error_code="ae.async_generation.contract_invalid",
        detail=detail,
    )
