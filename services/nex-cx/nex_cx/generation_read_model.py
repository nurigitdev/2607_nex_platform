from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.generation_private_output import load_generation_output
from nex_cx.generation_repository import (
    GenerationRuntimeRepository,
    GenerationRuntimeRepositoryError,
)
from nex_cx.private_content import CxPrivateContentError, CxPrivateTextStore


CX_GENERATION_READ_MODEL_SCHEMA_VERSION = "cx_generation_read_model.v1"
CX_GENERATION_CONTENT_SCHEMA_VERSION = "cx_generation_content.v1"
_READ_MODEL_FIELDS = frozenset(
    {
        "record_schema_version",
        "cx_generation_id",
        "tenant_ref_type",
        "tenant_ref_id",
        "owner_subject_ref_type",
        "owner_subject_ref_id",
        "status",
        "retrieval_package_id",
        "trace_id",
        "request_id",
        "alias",
        "provider_capability",
        "mo_generation_id",
        "request_metadata",
        "response_metadata",
        "mo_runtime_metadata",
        "usage",
        "failure",
        "recovery_lineage",
        "created_at",
        "updated_at",
    }
)
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
_RESPONSE_METADATA_FIELDS = frozenset({"finish_reason", "output_hash"})
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
        "input_tokens",
        "output_tokens",
        "total_tokens",
    }
)


@dataclass(frozen=True)
class GenerationReadModelError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class GenerationReadModel:
    repository: GenerationRuntimeRepository
    private_output_store: CxPrivateTextStore

    def get_metadata(
        self,
        cx_generation_id: str,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any] | None:
        record = self._get_record(
            cx_generation_id,
            access_context=access_context,
        )
        if record is None:
            return None
        return project_generation_read_model(record)

    def get_content(
        self,
        cx_generation_id: str,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any] | None:
        record = self._get_record(
            cx_generation_id,
            access_context=access_context,
        )
        if record is None:
            return None
        if record.get("status") != "COMPLETED":
            raise GenerationReadModelError(
                error_code="cx.generation_content_unavailable",
                detail="Generated content is unavailable for this execution status.",
            )

        metadata = record.get("private_output_metadata")
        if not isinstance(metadata, Mapping):
            raise GenerationReadModelError(
                error_code="cx.generation_content_reference_missing",
                detail="Completed generation content metadata is unavailable.",
            )
        try:
            content = load_generation_output(
                private_text_store=self.private_output_store,
                access_context=access_context,
                cx_generation_id=cx_generation_id,
                metadata=metadata,
            )
        except CxPrivateContentError as exc:
            raise GenerationReadModelError(
                error_code="cx.generation_content_integrity_failed",
                detail="Generated content failed its owner-private integrity check.",
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        if content is None:
            raise GenerationReadModelError(
                error_code="cx.generation_content_payload_unavailable",
                detail="Generated content is temporarily unavailable.",
                status_code=503,
                retryable=True,
            )
        return {
            "content_schema_version": CX_GENERATION_CONTENT_SCHEMA_VERSION,
            "cx_generation_id": cx_generation_id,
            "content_type": "text/plain; charset=utf-8",
            "content": content,
            "content_sha256": metadata["output_sha256"],
            "size_bytes": metadata["output_size_bytes"],
            "owner_scope_enforced": True,
        }

    def _get_record(
        self,
        cx_generation_id: str,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any] | None:
        try:
            return self.repository.get(
                cx_generation_id,
                access_context=access_context,
            )
        except GenerationRuntimeRepositoryError as exc:
            raise GenerationReadModelError(
                error_code=exc.error_code,
                detail=exc.detail,
                status_code=exc.status_code,
            ) from exc


def project_generation_read_model(record: Mapping[str, Any]) -> dict[str, Any]:
    private_output = record.get("private_output_metadata")
    content_ref = _safe_content_ref(private_output)
    projection = {
        key: deepcopy(record[key])
        for key in _READ_MODEL_FIELDS
        if key in record
    }
    projection["request_metadata"] = _safe_metadata(
        record.get("request_metadata"),
        allowed_fields=_REQUEST_METADATA_FIELDS,
    )
    projection["response_metadata"] = _safe_metadata(
        record.get("response_metadata"),
        allowed_fields=_RESPONSE_METADATA_FIELDS,
    )
    projection["mo_runtime_metadata"] = _safe_metadata(
        record.get("mo_runtime_metadata"),
        allowed_fields=_RUNTIME_METADATA_FIELDS,
    )
    projection["usage"] = _safe_metadata(
        record.get("usage"),
        allowed_fields=_USAGE_FIELDS,
    )
    projection.setdefault(
        "retrieval_package_id",
        projection["request_metadata"].get("retrieval_package_id"),
    )
    projection.setdefault("failure", None)
    projection.setdefault("recovery_lineage", None)
    return {
        "read_model_schema_version": CX_GENERATION_READ_MODEL_SCHEMA_VERSION,
        **projection,
        "content_ref": content_ref,
    }


def _safe_content_ref(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "available": False,
            "content_sha256": None,
            "size_bytes": None,
        }
    return {
        "available": True,
        "content_sha256": value.get("output_sha256"),
        "size_bytes": value.get("output_size_bytes"),
    }


def _safe_metadata(
    value: object,
    *,
    allowed_fields: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: deepcopy(item)
        for key, item in value.items()
        if key in allowed_fields
    }
