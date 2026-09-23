from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re
from typing import Any
from uuid import UUID

from nex_cx.owner_lineage import CxOwnerLineage, attach_owner_lineage


CX_GENERATION_PERSISTENCE_SCHEMA_VERSION = "cx_generation_persistence.v1"
CX_GENERATION_EXECUTION_TABLE = "cx_generation_executions"
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_REQUEST_METADATA_FIELDS = frozenset(
    {
        "provider_prompt_package_hash",
        "generation_request_hash",
        "response_format_type",
        "source_has_messages",
        "source_has_prompt",
        "compatibility_rule_id",
        "grounding_required",
        "retrieval_package_id",
        "retrieval_package_hash",
        "selected_evidence_count",
        "structured_draft_id",
        "draft_validation_status",
        "grounded_response_quality_audit_schema_version",
        "grounded_response_quality_status",
        "grounded_response_quality_issue_count",
    }
)
_RESPONSE_METADATA_FIELDS = frozenset(
    {
        "finish_reason",
        "output_hash",
        "private_output_schema_version",
        "output_storage_backend",
        "output_storage_uri",
        "output_size_bytes",
    }
)
_RUNTIME_METADATA_FIELDS = frozenset(
    {
        "request_id",
        "trace_id",
        "queue_ms",
        "provider_ms",
        "total_ms",
        "route_id",
        "admission_decision",
        "provider_request_id",
    }
)
_USAGE_FIELDS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
    }
)
_FAILURE_FIELDS = frozenset(
    {
        "failure_code",
        "failure_class",
        "owner_service",
        "failed_stage",
        "retryable",
        "recovery_policy_id",
        "recovery_policy_hash",
    }
)
_RECOVERY_FIELDS = frozenset(
    {
        "root_generation_id",
        "parent_generation_id",
        "attempt_no",
        "lineage_type",
        "lineage_reason",
        "default_recovery_action",
        "recovery_policy_id",
        "recovery_policy_hash",
        "retry_after_seconds",
        "max_attempts",
        "reuse_retrieval_package",
        "changed_fields",
    }
)
_PRIVATE_FIELD_NAMES = frozenset(
    {
        "prompt",
        "messages",
        "content",
        "text",
        "chunk_text",
        "summary_text",
        "raw_output",
        "output_preview",
        "embedding",
        "vector",
        "api_key",
        "authorization",
    }
)


class CxGenerationPersistenceError(ValueError):
    def __init__(self, *, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def build_generation_persistence_record(
    execution_record: Mapping[str, Any],
    *,
    owner_lineage: CxOwnerLineage,
) -> dict[str, Any]:
    status = _required_choice(
        execution_record.get("status"),
        field_name="status",
        choices={"COMPLETED", "FAILED"},
    )
    request_metadata = _safe_mapping(
        execution_record.get("request_metadata"),
        allowed_fields=_REQUEST_METADATA_FIELDS,
    )
    retrieval_package_id = _optional_uuid(
        request_metadata.pop("retrieval_package_id", None),
        field_name="retrieval_package_id",
    )
    failure = _optional_safe_mapping(
        execution_record.get("failure"),
        allowed_fields=_FAILURE_FIELDS,
    )
    if (status == "COMPLETED" and failure is not None) or (
        status == "FAILED" and failure is None
    ):
        raise CxGenerationPersistenceError(
            error_code="CX_GENERATION_PERSISTENCE_STATUS_INVALID",
            detail="Generation status and failure metadata are inconsistent.",
        )

    trace_id = _required_text(execution_record.get("trace_id"), field_name="trace_id")
    if not _TRACE_ID_PATTERN.fullmatch(trace_id):
        raise _invalid("trace_id must contain 32 lowercase hexadecimal characters.")

    record = {
        "cx_generation_id": _required_text(
            execution_record.get("cx_generation_id"),
            field_name="cx_generation_id",
        ),
        "record_schema_version": _required_choice(
            execution_record.get("record_schema_version"),
            field_name="record_schema_version",
            choices={"cx_generation_execution_record.v1"},
        ),
        "status": status,
        "retrieval_package_id": retrieval_package_id,
        "trace_id": trace_id,
        "request_id": _required_text(
            execution_record.get("request_id"),
            field_name="request_id",
        ),
        "alias": _required_text(execution_record.get("alias"), field_name="alias"),
        "provider_capability": _required_text(
            execution_record.get("provider_capability"),
            field_name="provider_capability",
        ),
        "mo_generation_id": _optional_text(execution_record.get("mo_generation_id")),
        "request_metadata": request_metadata,
        "response_metadata": _safe_mapping(
            execution_record.get("response_metadata"),
            allowed_fields=_RESPONSE_METADATA_FIELDS,
        ),
        "mo_runtime_metadata": _safe_mapping(
            execution_record.get("mo_runtime_metadata"),
            allowed_fields=_RUNTIME_METADATA_FIELDS,
        ),
        "usage": _numeric_mapping(
            execution_record.get("usage"),
            allowed_fields=_USAGE_FIELDS,
        ),
        "failure": failure,
        "recovery_lineage": _optional_safe_mapping(
            execution_record.get("recovery_lineage"),
            allowed_fields=_RECOVERY_FIELDS,
        ),
        "created_at": _required_datetime(
            execution_record.get("created_at"),
            field_name="created_at",
        ),
        "updated_at": _required_datetime(
            execution_record.get("updated_at"),
            field_name="updated_at",
        ),
    }
    record = attach_owner_lineage(record, owner_lineage)
    if generation_persistence_has_private_payload(record):
        raise CxGenerationPersistenceError(
            error_code="CX_GENERATION_PERSISTENCE_PRIVATE_PAYLOAD",
            detail="Generation persistence records cannot contain private payload fields.",
        )
    return record


def generation_persistence_has_private_payload(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in _PRIVATE_FIELD_NAMES
            or generation_persistence_has_private_payload(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(generation_persistence_has_private_payload(item) for item in value)
    return False


def _safe_mapping(value: object, *, allowed_fields: frozenset[str]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _invalid("Generation metadata must be an object.")
    return {
        key: item
        for key, item in value.items()
        if key in allowed_fields and _is_safe_scalar_or_list(item)
    }


def _optional_safe_mapping(
    value: object,
    *,
    allowed_fields: frozenset[str],
) -> dict[str, Any] | None:
    if value is None:
        return None
    return _safe_mapping(value, allowed_fields=allowed_fields)


def _numeric_mapping(value: object, *, allowed_fields: frozenset[str]) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _invalid("Generation usage must be an object.")
    result: dict[str, int] = {}
    for key, item in value.items():
        if key in allowed_fields and isinstance(item, int) and not isinstance(item, bool):
            if item < 0:
                raise _invalid("Generation usage values must be non-negative integers.")
            result[key] = item
    return result


def _is_safe_scalar_or_list(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(item is None or isinstance(item, (str, int, float, bool)) for item in value)
    return False


def _required_text(value: object, *, field_name: str) -> str:
    normalized = _optional_text(value)
    if normalized is None or len(normalized) > 256:
        raise _invalid(f"{field_name} must be a non-empty string of at most 256 characters.")
    return normalized


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _invalid("Optional text values must be non-empty strings when present.")
    return value.strip()


def _required_choice(
    value: object,
    *,
    field_name: str,
    choices: set[str],
) -> str:
    normalized = _required_text(value, field_name=field_name)
    if normalized not in choices:
        raise _invalid(f"{field_name} is not supported.")
    return normalized


def _optional_uuid(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = _required_text(value, field_name=field_name)
    try:
        return str(UUID(normalized))
    except ValueError as exc:
        raise _invalid(f"{field_name} must be a UUID when present.") from exc


def _required_datetime(value: object, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    raise _invalid(f"{field_name} must be a datetime value.")


def _invalid(detail: str) -> CxGenerationPersistenceError:
    return CxGenerationPersistenceError(
        error_code="CX_GENERATION_PERSISTENCE_INVALID",
        detail=detail,
    )
