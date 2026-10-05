from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from nex_ae_api.citation_quality_workflow import (
    AeCitationQualityWorkflowError,
    validate_citation_quality_workflow,
)
from nex_ae_api.generated_response_storage import (
    GeneratedResponseStorageError,
    build_generated_response_payload,
    build_generated_response_storage_ref,
)


AE_GENERATED_RESPONSE_LINEAGE_SCHEMA_VERSION = "ae_generated_response_lineage.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LINEAGE_TYPES = frozenset({"ORIGINAL", "RETRY_CHILD"})
_WORKFLOW_STATUSES = frozenset(
    {"NOT_REQUIRED", "VALIDATED", "REPAIRED", "ATTENTION_REQUIRED"}
)
_BASE_LINEAGE_FIELDS = frozenset(
    {
        "lineage_schema_version",
        "response_id",
        "lineage_type",
        "interaction_id",
        "chat_document_id",
        "cx_generation_id",
        "cx_job_id",
        "content_type",
        "content_sha256",
        "size_bytes",
        "content_available",
        "retrieval_package_id",
        "retrieval_package_hash",
        "structured_draft_id",
        "citation_workflow_status",
        "bounded_repair_applied",
        "parent_interaction_id",
        "parent_response_id",
        "owner_scope_enforced",
        "raw_content_included",
        "storage_ref_included",
    }
)
_LINEAGE_FIELDS = _BASE_LINEAGE_FIELDS | {"cx_grounding_lineage"}
_CX_GROUNDING_LINEAGE_FIELDS = frozenset(
    {
        "lineage_schema_version",
        "retrieval_package_id",
        "retrieval_package_hash",
        "evidence_binding_hash",
        "selected_evidence_count",
        "citation_validation_status",
        "citation_repair_attempted",
        "citation_repair_attempt_count",
        "original_provider_prompt_package_hash",
        "effective_provider_prompt_package_hash",
        "same_retrieval_package",
        "private_evidence_included",
    }
)


@dataclass(frozen=True)
class AeGeneratedResponseLineageError(ValueError):
    error_code: str
    detail: str
    status_code: int = 422
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def prepare_generated_response(
    record: Mapping[str, Any],
    refresh_result: Mapping[str, Any],
    citation_workflow: Mapping[str, Any],
    *,
    cx_generation: Mapping[str, Any] | None = None,
    parent_response_id: str | None = None,
) -> dict[str, Any]:
    interaction_id = _required_text(record.get("interaction_id"), "interaction_id")
    chat_document_id = _required_text(
        record.get("chat_document_id"), "chat_document_id"
    )
    generation = record.get("generation")
    if not isinstance(generation, Mapping):
        raise _invalid("Chat interaction generation metadata is missing.")
    projection = generation.get("async_generation")
    if not isinstance(projection, Mapping):
        raise _invalid("Chat interaction async generation metadata is missing.")
    cx_generation_id = _required_text(
        projection.get("cx_generation_id"), "cx_generation_id"
    )
    cx_job_id = _required_text(projection.get("job_id"), "cx_job_id")
    if record.get("cx_generation_id") != cx_generation_id:
        raise _invalid("Chat interaction generation lineage is inconsistent.")

    result = _validate_ready_refresh_result(refresh_result, cx_generation_id)
    workflow = _validated_workflow(
        citation_workflow,
        interaction_id=interaction_id,
        cx_generation_id=cx_generation_id,
    )
    cx_grounding_lineage = _grounding_lineage_from_cx_generation(
        cx_generation,
        workflow=workflow,
        cx_generation_id=cx_generation_id,
    )
    response_id = str(
        uuid5(
            NAMESPACE_URL,
            "ae-generated-response:"
            f"{interaction_id}:{cx_generation_id}:{result['content_sha256']}",
        )
    )
    try:
        payload = build_generated_response_payload(
            response_id=response_id,
            content=result["content"],
            content_type=result["content_type"],
        )
    except GeneratedResponseStorageError as exc:
        raise _invalid(exc.detail) from exc
    if (
        payload["content_sha256"] != result["content_sha256"]
        or payload["size_bytes"] != result["size_bytes"]
    ):
        raise _invalid("Generated response content integrity is inconsistent.")

    quality = workflow["quality"]
    retry_lineage = generation.get("retry_lineage")
    lineage_type = "RETRY_CHILD" if retry_lineage is not None else "ORIGINAL"
    parent_interaction_id: str | None = None
    normalized_parent_response_id: str | None = None
    if lineage_type == "RETRY_CHILD":
        if not isinstance(retry_lineage, Mapping):
            raise _invalid("Generated response retry lineage is invalid.")
        parent_interaction_id = _required_text(
            retry_lineage.get("parent_interaction_id"),
            "parent_interaction_id",
        )
        normalized_parent_response_id = _nullable_text(
            parent_response_id or retry_lineage.get("parent_response_id"),
            "parent_response_id",
        )
    elif parent_response_id is not None:
        raise _invalid("Original generated response cannot have a parent response.")

    lineage = validate_generated_response_lineage(
        {
            "lineage_schema_version": AE_GENERATED_RESPONSE_LINEAGE_SCHEMA_VERSION,
            "response_id": response_id,
            "lineage_type": lineage_type,
            "interaction_id": interaction_id,
            "chat_document_id": chat_document_id,
            "cx_generation_id": cx_generation_id,
            "cx_job_id": cx_job_id,
            "content_type": result["content_type"],
            "content_sha256": result["content_sha256"],
            "size_bytes": result["size_bytes"],
            "content_available": True,
            "retrieval_package_id": quality["retrieval_package_id"],
            "retrieval_package_hash": quality["retrieval_package_hash"],
            "structured_draft_id": quality["structured_draft_id"],
            "citation_workflow_status": workflow["workflow_status"],
            "bounded_repair_applied": (
                workflow["workflow_status"] == "REPAIRED"
                and workflow["repair"]["attempted"] is True
            ),
            "cx_grounding_lineage": cx_grounding_lineage,
            "parent_interaction_id": parent_interaction_id,
            "parent_response_id": normalized_parent_response_id,
            "owner_scope_enforced": True,
            "raw_content_included": False,
            "storage_ref_included": False,
        }
    )
    _validate_retrieval_lineage(record, lineage)
    return {"lineage": lineage, "storage_payload": payload}


def validate_generated_response_lineage(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) not in {
        _BASE_LINEAGE_FIELDS,
        _LINEAGE_FIELDS,
    }:
        raise _invalid("Generated response lineage has an invalid shape.")
    lineage = deepcopy(dict(value))
    lineage.setdefault("cx_grounding_lineage", None)
    if lineage["lineage_schema_version"] != (
        AE_GENERATED_RESPONSE_LINEAGE_SCHEMA_VERSION
    ):
        raise _invalid("Generated response lineage schema version is invalid.")
    for field in (
        "response_id",
        "interaction_id",
        "chat_document_id",
        "cx_generation_id",
        "cx_job_id",
    ):
        lineage[field] = _required_text(lineage[field], field)
    if lineage["lineage_type"] not in _LINEAGE_TYPES:
        raise _invalid("Generated response lineage type is invalid.")
    content_type = lineage["content_type"]
    if (
        not isinstance(content_type, str)
        or not content_type.strip().startswith("text/")
        or len(content_type.strip()) > 120
    ):
        raise _invalid("Generated response content type is invalid.")
    lineage["content_type"] = content_type.strip()
    lineage["content_sha256"] = _required_sha256(
        lineage["content_sha256"], "content_sha256"
    )
    size_bytes = lineage["size_bytes"]
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise _invalid("Generated response content size is invalid.")
    if lineage["content_available"] is not True:
        raise _invalid("Generated response content availability is invalid.")
    lineage["retrieval_package_id"] = _nullable_text(
        lineage["retrieval_package_id"], "retrieval_package_id"
    )
    lineage["retrieval_package_hash"] = _nullable_sha256(
        lineage["retrieval_package_hash"], "retrieval_package_hash"
    )
    lineage["structured_draft_id"] = _nullable_text(
        lineage["structured_draft_id"], "structured_draft_id"
    )
    if lineage["citation_workflow_status"] not in _WORKFLOW_STATUSES:
        raise _invalid("Generated response citation workflow status is invalid.")
    if not isinstance(lineage["bounded_repair_applied"], bool):
        raise _invalid("Generated response repair flag is invalid.")
    if lineage["bounded_repair_applied"] is not (
        lineage["citation_workflow_status"] == "REPAIRED"
    ):
        raise _invalid("Generated response repair lineage is inconsistent.")
    lineage["cx_grounding_lineage"] = _validate_cx_grounding_lineage(
        lineage["cx_grounding_lineage"]
    )
    _validate_persisted_grounding_lineage(lineage)
    parent_interaction_id = _nullable_text(
        lineage["parent_interaction_id"], "parent_interaction_id"
    )
    parent_response_id = _nullable_text(
        lineage["parent_response_id"], "parent_response_id"
    )
    if lineage["lineage_type"] == "ORIGINAL":
        if parent_interaction_id is not None or parent_response_id is not None:
            raise _invalid("Original generated response has parent lineage.")
    elif parent_interaction_id is None:
        raise _invalid("Retry generated response parent interaction is missing.")
    lineage["parent_interaction_id"] = parent_interaction_id
    lineage["parent_response_id"] = parent_response_id
    if lineage["owner_scope_enforced"] is not True:
        raise _invalid("Generated response lineage must enforce owner scope.")
    if lineage["raw_content_included"] is not False:
        raise _invalid("Generated response lineage must not include raw content.")
    if lineage["storage_ref_included"] is not False:
        raise _invalid("Generated response lineage must not expose storage references.")
    return lineage


def attach_generated_response_lineage(
    record: Mapping[str, Any],
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_generated_response_lineage(lineage)
    generation = record.get("generation")
    if not isinstance(generation, Mapping):
        raise _invalid("Chat interaction generation metadata is missing.")
    if (
        normalized["interaction_id"] != record.get("interaction_id")
        or normalized["chat_document_id"] != record.get("chat_document_id")
        or normalized["cx_generation_id"] != record.get("cx_generation_id")
    ):
        raise _invalid("Generated response chat lineage is inconsistent.")
    existing = generation.get("generated_response")
    if existing is not None:
        validated_existing = validate_generated_response_lineage(existing)
        if validated_existing != normalized:
            raise AeGeneratedResponseLineageError(
                error_code="ae.generated_response_lineage_conflict",
                detail="Chat interaction already has different generated response lineage.",
                status_code=409,
            )
    return {
        **deepcopy(dict(record)),
        "generation": {
            **deepcopy(dict(generation)),
            "generated_response": normalized,
        },
    }


def generated_response_lineage_from_record(
    record: Mapping[str, Any],
) -> dict[str, Any] | None:
    generation = record.get("generation")
    if not isinstance(generation, Mapping):
        return None
    value = generation.get("generated_response")
    if value is None:
        return None
    lineage = validate_generated_response_lineage(value)
    if (
        lineage["interaction_id"] != record.get("interaction_id")
        or lineage["chat_document_id"] != record.get("chat_document_id")
        or lineage["cx_generation_id"] != record.get("cx_generation_id")
    ):
        raise _invalid("Persisted generated response lineage is inconsistent.")
    return lineage


def generated_response_storage_metadata_from_lineage(
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_generated_response_lineage(lineage)
    storage_ref = build_generated_response_storage_ref(
        normalized["response_id"], normalized["content_sha256"]
    )
    return {
        "response_id": normalized["response_id"],
        "content_type": normalized["content_type"],
        "content_sha256": normalized["content_sha256"],
        "size_bytes": normalized["size_bytes"],
        "storage_ref": storage_ref,
    }


def _validate_ready_refresh_result(
    value: Mapping[str, Any], expected_generation_id: str
) -> dict[str, Any]:
    expected_fields = {
        "refresh_schema_version",
        "handoff_status",
        "cx_generation_id",
        "content",
        "content_type",
        "content_sha256",
        "size_bytes",
        "owner_scope_enforced",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise _invalid("Generated response refresh result has an invalid shape.")
    if (
        value["refresh_schema_version"] != "ae_async_generation_refresh.v1"
        or value["handoff_status"] != "READY"
        or value["cx_generation_id"] != expected_generation_id
        or value["owner_scope_enforced"] is not True
    ):
        raise _invalid("Generated response refresh lineage is inconsistent.")
    content = value["content"]
    content_type = value["content_type"]
    digest = value["content_sha256"]
    size_bytes = value["size_bytes"]
    if not isinstance(content, str):
        raise _invalid("Generated response content is missing.")
    if not isinstance(content_type, str) or not content_type.strip():
        raise _invalid("Generated response content type is invalid.")
    digest = _required_sha256(digest, "content_sha256")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise _invalid("Generated response content size is invalid.")
    return {
        "content": content,
        "content_type": content_type.strip(),
        "content_sha256": digest,
        "size_bytes": size_bytes,
    }


def _validated_workflow(
    value: Mapping[str, Any], *, interaction_id: str, cx_generation_id: str
) -> dict[str, Any]:
    try:
        workflow = validate_citation_quality_workflow(value)
    except AeCitationQualityWorkflowError as exc:
        raise _invalid(exc.detail) from exc
    if (
        workflow["interaction_id"] != interaction_id
        or workflow["cx_generation_id"] != cx_generation_id
    ):
        raise _invalid("Generated response citation lineage is inconsistent.")
    return workflow


def _validate_retrieval_lineage(
    record: Mapping[str, Any], lineage: Mapping[str, Any]
) -> None:
    retrieval = record.get("retrieval")
    if not isinstance(retrieval, Mapping):
        return
    expected_id = retrieval.get("cx_retrieval_package_id")
    expected_hash = retrieval.get("cx_package_hash")
    if expected_id is not None and expected_id != lineage["retrieval_package_id"]:
        raise _invalid("Generated response retrieval package ID is inconsistent.")
    if expected_hash is not None and expected_hash != lineage["retrieval_package_hash"]:
        raise _invalid("Generated response retrieval package hash is inconsistent.")


def _grounding_lineage_from_cx_generation(
    cx_generation: Mapping[str, Any] | None,
    *,
    workflow: Mapping[str, Any],
    cx_generation_id: str,
) -> dict[str, Any] | None:
    quality = workflow["quality"]
    if quality["grounding_required"] is False:
        return None
    if (
        workflow["workflow_status"] not in {"VALIDATED", "REPAIRED"}
        or quality["boundary_status"] != "PASS"
        or quality["citation_status"] != "VALIDATED"
        or quality["issue_count"] != 0
    ):
        raise _invalid("Grounded response citation workflow is incomplete.")
    if not isinstance(cx_generation, Mapping):
        raise _invalid("CX grounded generation metadata is missing.")
    if cx_generation.get("cx_generation_id") != cx_generation_id:
        raise _invalid("CX grounded generation identity is inconsistent.")
    request_metadata = cx_generation.get("request_metadata")
    if not isinstance(request_metadata, Mapping):
        raise _invalid("CX grounded generation request metadata is missing.")
    lineage = _validate_cx_grounding_lineage(
        request_metadata.get("grounding_lineage")
    )
    if lineage is None:
        raise _invalid("CX grounded generation lineage is missing.")
    if (
        lineage["retrieval_package_id"] != quality["retrieval_package_id"]
        or lineage["retrieval_package_hash"] != quality["retrieval_package_hash"]
        or request_metadata.get("retrieval_package_id")
        != lineage["retrieval_package_id"]
        or request_metadata.get("retrieval_package_hash")
        != lineage["retrieval_package_hash"]
        or request_metadata.get("selected_evidence_count")
        != lineage["selected_evidence_count"]
    ):
        raise _invalid("CX grounded generation retrieval lineage is inconsistent.")
    top_level_retrieval_id = cx_generation.get("retrieval_package_id")
    if (
        top_level_retrieval_id is not None
        and top_level_retrieval_id != lineage["retrieval_package_id"]
    ):
        raise _invalid("CX grounded generation retrieval identity is inconsistent.")
    provider_prompt_hash = request_metadata.get("provider_prompt_package_hash")
    if provider_prompt_hash is not None and provider_prompt_hash != lineage[
        "effective_provider_prompt_package_hash"
    ]:
        raise _invalid("CX grounded generation prompt lineage is inconsistent.")
    repair = workflow["repair"]
    if (
        lineage["citation_repair_attempted"] is not repair["attempted"]
        or lineage["citation_repair_attempt_count"] != repair["attempt_count"]
    ):
        raise _invalid("CX grounded generation repair lineage is inconsistent.")
    if repair["source_projection_present"] and (
        lineage["original_provider_prompt_package_hash"]
        != repair["original_provider_prompt_package_hash"]
        or lineage["effective_provider_prompt_package_hash"]
        != repair["effective_provider_prompt_package_hash"]
    ):
        raise _invalid("CX grounded generation repair prompt lineage is inconsistent.")
    return lineage


def _validate_cx_grounding_lineage(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != _CX_GROUNDING_LINEAGE_FIELDS:
        raise _invalid("CX grounded generation lineage has an invalid shape.")
    lineage = deepcopy(dict(value))
    if lineage["lineage_schema_version"] != "cx_grounded_generation_lineage.v1":
        raise _invalid("CX grounded generation lineage version is invalid.")
    lineage["retrieval_package_id"] = _required_text(
        lineage["retrieval_package_id"], "grounding_retrieval_package_id"
    )
    if len(lineage["retrieval_package_id"]) > 256:
        raise _invalid("CX grounded generation retrieval package ID is invalid.")
    for field in (
        "retrieval_package_hash",
        "evidence_binding_hash",
        "original_provider_prompt_package_hash",
        "effective_provider_prompt_package_hash",
    ):
        lineage[field] = _required_sha256(lineage[field], field)
    evidence_count = lineage["selected_evidence_count"]
    if (
        isinstance(evidence_count, bool)
        or not isinstance(evidence_count, int)
        or evidence_count < 1
    ):
        raise _invalid("CX grounded generation evidence count is invalid.")
    if lineage["citation_validation_status"] != "VALIDATED":
        raise _invalid("CX grounded generation citation status is invalid.")
    attempted = lineage["citation_repair_attempted"]
    attempt_count = lineage["citation_repair_attempt_count"]
    if not isinstance(attempted, bool) or (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count != (1 if attempted else 0)
    ):
        raise _invalid("CX grounded generation repair attempt is inconsistent.")
    if not attempted and lineage["original_provider_prompt_package_hash"] != (
        lineage["effective_provider_prompt_package_hash"]
    ):
        raise _invalid("Unrepaired CX grounded generation changed its prompt hash.")
    if lineage["same_retrieval_package"] is not True:
        raise _invalid("CX grounded generation changed its retrieval package.")
    if lineage["private_evidence_included"] is not False:
        raise _invalid("CX grounded generation lineage contains private evidence.")
    return lineage


def _validate_persisted_grounding_lineage(lineage: Mapping[str, Any]) -> None:
    grounding = lineage["cx_grounding_lineage"]
    if grounding is None:
        return
    if (
        grounding["retrieval_package_id"] != lineage["retrieval_package_id"]
        or grounding["retrieval_package_hash"] != lineage["retrieval_package_hash"]
        or grounding["citation_repair_attempted"]
        is not lineage["bounded_repair_applied"]
        or lineage["citation_workflow_status"] not in {"VALIDATED", "REPAIRED"}
    ):
        raise _invalid("Persisted CX grounding lineage is inconsistent.")


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"Generated response {field} is invalid.")
    return value.strip()


def _nullable_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _required_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise _invalid(f"Generated response {field} is invalid.")
    return value


def _nullable_sha256(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_sha256(value, field)


def _invalid(detail: str) -> AeGeneratedResponseLineageError:
    return AeGeneratedResponseLineageError(
        error_code="ae.generated_response_lineage_invalid",
        detail=detail,
    )
