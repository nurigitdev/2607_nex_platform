from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


CX_PROCESSING_RUN_READ_MODEL_SCHEMA_VERSION = "cx_processing_run_read_model.v1"
CX_PROCESSING_RUN_QUERY_FILTER_SCHEMA_VERSION = "cx_processing_run_query_filters.v1"
DEFAULT_PROCESSING_RUN_QUERY_LIMIT = 50
MAX_PROCESSING_RUN_QUERY_LIMIT = 500
PROCESSING_RUN_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")


def build_processing_run_query_filters(
    *,
    document_id: str | None = None,
    status: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    job_id: str | None = None,
    limit: int | str | None = None,
    include_steps: bool = True,
) -> dict[str, Any]:
    return {
        "filter_schema_version": CX_PROCESSING_RUN_QUERY_FILTER_SCHEMA_VERSION,
        "document_id": _optional_non_empty_string(document_id),
        "status": normalize_processing_run_status(status),
        "trace_id": _optional_non_empty_string(trace_id),
        "request_id": _optional_non_empty_string(request_id),
        "job_id": _optional_non_empty_string(job_id),
        "limit": bounded_processing_run_query_limit(limit),
        "include_steps": bool(include_steps),
    }


def build_processing_run_read_model(
    records: list[dict[str, Any]],
    *,
    filters: Mapping[str, Any],
    source_kind: str,
    database_env: str | None = None,
    redacted_database_url: str | None = None,
) -> dict[str, Any]:
    include_steps = bool(filters.get("include_steps", True))
    runs = [
        project_processing_run_record(record, include_steps=include_steps)
        for record in records
    ]
    return {
        "read_model_schema_version": CX_PROCESSING_RUN_READ_MODEL_SCHEMA_VERSION,
        "source": {
            "service_id": "nex-cx",
            "source_kind": source_kind,
            "database_env": database_env,
            "redacted_database_url": redacted_database_url,
        },
        "filters": _public_filters(filters),
        "pagination": {
            "limit": bounded_processing_run_query_limit(filters.get("limit")),
            "returned": len(runs),
        },
        "summary": {
            "run_count": len(runs),
            "status_counts": _status_counts(runs),
            "failed_count": sum(1 for run in runs if run["status"] == "FAILED"),
        },
        "runs": runs,
    }


def project_processing_run_record(
    record: Mapping[str, Any],
    *,
    include_steps: bool = True,
) -> dict[str, Any]:
    steps = [
        _project_processing_step(step)
        for step in _list_value(record.get("steps"))
        if isinstance(step, Mapping)
    ]
    return {
        "processing_run_schema_version": "cx_document_processing_run.persistence.v1",
        "pipeline_run_id": record.get("pipeline_run_id"),
        "pipeline_schema_version": record.get("pipeline_schema_version"),
        "document_id": record.get("document_id"),
        "status": record.get("status"),
        "trace_id": record.get("trace_id"),
        "request_id": record.get("request_id"),
        "job_id": record.get("job_id"),
        "job_type": record.get("job_type"),
        "job_status": record.get("job_status"),
        "job_attempt_count": _int_value(record.get("job_attempt_count")),
        "job_max_attempts": _int_value(record.get("job_max_attempts")),
        "job_retryable": record.get("job_retryable"),
        "job_subject_ref": _mapping_copy(record.get("job_subject_ref")),
        "job_links": _mapping_copy(record.get("job_links")),
        "step_total": _int_value(record.get("step_total")),
        "step_succeeded": _int_value(record.get("step_succeeded")),
        "step_skipped": _int_value(record.get("step_skipped")),
        "step_failed": _int_value(record.get("step_failed")),
        "queued_at": record.get("queued_at"),
        "started_at": record.get("started_at"),
        "completed_at": record.get("completed_at"),
        "updated_at": record.get("updated_at"),
        "steps_included": include_steps,
        "steps": steps if include_steps else [],
    }


def normalize_processing_run_status(status: str | None) -> str | None:
    normalized = _optional_non_empty_string(status)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if normalized not in PROCESSING_RUN_STATUSES:
        raise ValueError(
            "CX processing run status must be one of: "
            f"{', '.join(PROCESSING_RUN_STATUSES)}"
        )
    return normalized


def bounded_processing_run_query_limit(limit: int | str | None) -> int:
    if limit is None:
        return DEFAULT_PROCESSING_RUN_QUERY_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("CX processing run query limit must be an integer.") from exc
    if value < 1:
        return 1
    return min(value, MAX_PROCESSING_RUN_QUERY_LIMIT)


def _project_processing_step(step: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "processing_step_schema_version": "cx_document_processing_step.persistence.v1",
        "pipeline_run_id": step.get("pipeline_run_id"),
        "step_order": _int_value(step.get("step_order")),
        "step_id": step.get("step_id"),
        "status": step.get("status"),
        "output_ref_type": step.get("output_ref_type"),
        "output_ref_id": step.get("output_ref_id"),
        "output_ref_document_id": step.get("output_ref_document_id"),
        "output_ref_hash": step.get("output_ref_hash"),
        "error_code": step.get("error_code"),
        "error_detail_sha256": step.get("error_detail_sha256"),
        "error_retryable": step.get("error_retryable"),
        "created_at": step.get("created_at"),
    }


def _public_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "filter_schema_version": filters.get(
            "filter_schema_version",
            CX_PROCESSING_RUN_QUERY_FILTER_SCHEMA_VERSION,
        ),
        "document_id": filters.get("document_id"),
        "status": filters.get("status"),
        "trace_id": filters.get("trace_id"),
        "request_id": filters.get("request_id"),
        "job_id": filters.get("job_id"),
        "include_steps": bool(filters.get("include_steps", True)),
    }


def _status_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in PROCESSING_RUN_STATUSES}
    for run in runs:
        status = run.get("status")
        if status in counts:
            counts[str(status)] += 1
    return {status: count for status, count in counts.items() if count}


def _optional_non_empty_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping_copy(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return deepcopy(dict(value))


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
