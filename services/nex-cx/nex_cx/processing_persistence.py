from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_cx.retrieval_persistence import sha256_json, sha256_text


CX_PROCESSING_RUN_PERSISTENCE_DECISION_SCHEMA_VERSION = (
    "cx_processing_run_persistence_decision.v1"
)
CX_PROCESSING_RUN_PERSISTENCE_PREVIEW_SCHEMA_VERSION = (
    "cx_processing_run_persistence_preview.v1"
)
CX_DOCUMENT_PROCESSING_RUN_TABLE = "cx_document_processing_runs"
CX_DOCUMENT_PROCESSING_STEP_TABLE = "cx_document_processing_steps"
CX_PROCESSING_RUNTIME_RECORD_SCHEMA = "cx_document_processing_pipeline.v1"

CX_PROCESSING_PRIVATE_PAYLOAD_KEY_HINTS = (
    "chunk_text",
    "content_bytes",
    "detail",
    "embedding",
    "embeddings",
    "markdown",
    "markdown_text",
    "prompt",
    "prompt_text",
    "query_embedding",
    "query_text",
    "raw_output",
    "raw_prompt",
    "raw_text",
    "source_bytes",
    "source_text",
    "summary_text",
    "text",
    "vector",
    "vectors",
)


def build_processing_run_persistence_decision() -> dict[str, Any]:
    return {
        "decision_schema_version": CX_PROCESSING_RUN_PERSISTENCE_DECISION_SCHEMA_VERSION,
        "decision_slice": "0181",
        "surface_id": "processing_runs",
        "decision_status": "write_through_ready_postgres_smoke_pending",
        "runtime_record_schema": CX_PROCESSING_RUNTIME_RECORD_SCHEMA,
        "persistence_owner": "nex-cx",
        "repository_boundary": "CxProcessingRunRepository",
        "write_path": (
            "ContentIngestionStore.save_document_processing_run write-through after "
            "queue, worker, or pipeline state changes"
        ),
        "migration_version": "0182_cx_processing_run_step_persistence",
        "adapter_slice": "0183",
        "write_through_slice": "0184",
        "postgres_smoke_slice": "0185",
        "target_tables": [
            CX_DOCUMENT_PROCESSING_RUN_TABLE,
            CX_DOCUMENT_PROCESSING_STEP_TABLE,
        ],
        "unique_keys": {
            CX_DOCUMENT_PROCESSING_RUN_TABLE: [
                ["pipeline_run_id"],
                ["document_id", "updated_at", "pipeline_run_id"],
            ],
            CX_DOCUMENT_PROCESSING_STEP_TABLE: [
                ["pipeline_run_id", "step_order"],
                ["pipeline_run_id", "step_id"],
            ],
        },
        "run_metadata_fields": [
            "pipeline_run_id",
            "pipeline_schema_version",
            "document_id",
            "status",
            "trace_id",
            "request_id",
            "job_id",
            "job_type",
            "job_status",
            "job_attempt_count",
            "job_max_attempts",
            "job_retryable",
            "job_subject_ref",
            "job_links",
            "step_total",
            "step_succeeded",
            "step_skipped",
            "step_failed",
            "queued_at",
            "started_at",
            "completed_at",
            "updated_at",
        ],
        "step_metadata_fields": [
            "pipeline_run_id",
            "step_order",
            "step_id",
            "status",
            "output_ref_type",
            "output_ref_id",
            "output_ref_document_id",
            "output_ref_hash",
            "error_code",
            "error_detail_sha256",
            "error_retryable",
        ],
        "private_payload_exclusions": [
            "source_bytes",
            "source_text",
            "markdown_text",
            "chunk_text",
            "summary_text",
            "embedding_raw_vector",
            "summary_embedding_raw_vector",
            "generation_prompt_text",
            "steps[].output",
            "steps[].output_ref.private_payload",
            "steps[].error.detail",
        ],
        "private_payload_policy": (
            "run_header_step_status_output_ref_hash_and_error_hash_only"
        ),
        "migration_policy": "postgres_schema_then_repository_write_through",
        "next_slice": "0185_cx_processing_postgresql_smoke_evidence",
    }


def build_processing_run_persistence_preview(run: Mapping[str, Any]) -> dict[str, Any]:
    job = _mapping_value(run.get("job"))
    step_summary = _mapping_value(run.get("step_summary"))
    steps = [
        _build_processing_step_preview(
            step,
            pipeline_run_id=run.get("pipeline_run_id"),
            step_order=index,
        )
        for index, step in enumerate(_list_value(run.get("steps")), start=1)
        if isinstance(step, Mapping)
    ]
    header = {
        "preview_schema_version": CX_PROCESSING_RUN_PERSISTENCE_PREVIEW_SCHEMA_VERSION,
        "target_table": CX_DOCUMENT_PROCESSING_RUN_TABLE,
        "pipeline_run_id": run.get("pipeline_run_id"),
        "pipeline_schema_version": run.get("pipeline_schema_version"),
        "document_id": run.get("document_id"),
        "status": run.get("status"),
        "trace_id": run.get("trace_id"),
        "request_id": run.get("request_id"),
        "job_id": job.get("job_id"),
        "job_type": job.get("job_type"),
        "job_status": job.get("status"),
        "job_attempt_count": job.get("attempt_count"),
        "job_max_attempts": job.get("max_attempts"),
        "job_retryable": job.get("retryable"),
        "job_subject_ref": job.get("subject_ref"),
        "job_links": job.get("links"),
        "step_total": _summary_count(step_summary, "total", fallback=len(steps)),
        "step_succeeded": _summary_count(step_summary, "succeeded"),
        "step_skipped": _summary_count(step_summary, "skipped"),
        "step_failed": _summary_count(step_summary, "failed"),
        "queued_at": run.get("queued_at"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "updated_at": run.get("updated_at"),
    }
    return {
        "preview_schema_version": CX_PROCESSING_RUN_PERSISTENCE_PREVIEW_SCHEMA_VERSION,
        "decision": build_processing_run_persistence_decision(),
        "header": header,
        "steps": steps,
        "private_payload_key_paths": find_processing_private_payload_key_paths(run),
    }


def find_processing_private_payload_key_paths(
    value: object,
    *,
    prefix: str = "",
) -> list[str]:
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in CX_PROCESSING_PRIVATE_PAYLOAD_KEY_HINTS:
                paths.append(child_path)
            paths.extend(
                find_processing_private_payload_key_paths(item, prefix=child_path)
            )
        return paths
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            child_path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(
                find_processing_private_payload_key_paths(item, prefix=child_path)
            )
        return paths
    return []


def _build_processing_step_preview(
    step: Mapping[str, Any],
    *,
    pipeline_run_id: object,
    step_order: int,
) -> dict[str, Any]:
    output_ref = _mapping_value(step.get("output_ref"))
    error = _mapping_value(step.get("error"))
    error_detail = _string_value(error.get("detail"))
    return {
        "target_table": CX_DOCUMENT_PROCESSING_STEP_TABLE,
        "pipeline_run_id": pipeline_run_id,
        "step_order": step_order,
        "step_id": step.get("step_id"),
        "status": step.get("status"),
        "output_ref_type": output_ref.get("type"),
        "output_ref_id": output_ref.get("id"),
        "output_ref_document_id": output_ref.get("document_id"),
        "output_ref_hash": sha256_json(output_ref) if output_ref else None,
        "error_code": error.get("error_code"),
        "error_detail_sha256": sha256_text(error_detail) if error_detail else None,
        "error_retryable": (
            error.get("retryable") if isinstance(error.get("retryable"), bool) else None
        ),
    }


def _summary_count(
    step_summary: Mapping[str, Any],
    key: str,
    *,
    fallback: int = 0,
) -> int:
    value = step_summary.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _mapping_value(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
