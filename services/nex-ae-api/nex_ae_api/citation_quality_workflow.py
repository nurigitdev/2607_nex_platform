from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Mapping


AE_CHAT_GROUNDED_RESPONSE_QUALITY_CONTRACT_VERSION = (
    "ae_chat_grounded_response_quality.v1"
)
AE_CITATION_QUALITY_WORKFLOW_SCHEMA_VERSION = "ae_citation_quality_workflow.v1"
_CX_CITATION_REPAIR_SCHEMA_VERSION = "cx_citation_repair.v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_BOUNDARY_STATUSES = frozenset({"PASS", "WARN", "FAIL", "NOT_REQUIRED", "UNKNOWN"})
_CITATION_STATUSES = frozenset({"VALIDATED", "INVALID", "NOT_REQUIRED", "UNKNOWN"})
_REPAIRABLE_ERROR_CODES = frozenset(
    {"cx.citation_required_missing", "cx.citation_validation_failed"}
)
_WORKFLOW_ACTIONS = {
    "NOT_REQUIRED": "PRESENT_RESPONSE",
    "VALIDATED": "PRESENT_RESPONSE",
    "REPAIRED": "PRESENT_REPAIRED_RESPONSE",
    "ATTENTION_REQUIRED": "RETRY_OR_REVIEW_GENERATION",
}
_WORKFLOW_FIELDS = frozenset(
    {
        "workflow_schema_version",
        "interaction_id",
        "cx_generation_id",
        "workflow_status",
        "next_action",
        "quality",
        "repair",
        "operator_remediation",
        "owner_scope_enforced",
        "content_included",
    }
)
_QUALITY_FIELDS = frozenset(
    {
        "contract_schema_version",
        "source_audit_schema_version",
        "boundary_status",
        "citation_status",
        "issue_count",
        "recommended_action",
        "grounding_required",
        "retrieval_package_id",
        "retrieval_package_hash",
        "structured_draft_id",
        "raw_output_included",
        "evidence_text_included",
        "prompt_text_included",
        "provider_detail_included",
    }
)
_REPAIR_FIELDS = frozenset(
    {
        "source_projection_present",
        "repair_schema_version",
        "mode",
        "status",
        "attempted",
        "attempt_count",
        "max_attempts",
        "trigger_error_code",
        "same_retrieval_package",
        "original_provider_prompt_package_hash",
        "effective_provider_prompt_package_hash",
        "invalid_output_included",
    }
)
_OPERATOR_REMEDIATION_FIELDS = frozenset(
    {"mode", "required", "handoff_included"}
)


@dataclass
class AeCitationQualityWorkflowError(ValueError):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_grounded_response_quality_contract(
    cx_record: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(cx_record, Mapping):
        raise _invalid("CX generation metadata must be an object.")
    request_metadata = _mapping(cx_record.get("request_metadata"))
    grounding_required = bool(request_metadata.get("grounding_required"))
    boundary_status = _boundary_status(
        request_metadata.get("grounded_response_quality_status"),
        grounding_required=grounding_required,
    )
    issue_count = _non_negative_int(
        request_metadata.get("grounded_response_quality_issue_count")
    )
    return {
        "contract_schema_version": (
            AE_CHAT_GROUNDED_RESPONSE_QUALITY_CONTRACT_VERSION
        ),
        "source_audit_schema_version": _optional_text(
            request_metadata.get("grounded_response_quality_audit_schema_version")
        ),
        "boundary_status": boundary_status,
        "citation_status": _citation_status(
            request_metadata.get("draft_validation_status"),
            boundary_status=boundary_status,
        ),
        "issue_count": issue_count,
        "recommended_action": _quality_action(boundary_status, issue_count),
        "grounding_required": grounding_required,
        "retrieval_package_id": _optional_text(
            request_metadata.get("retrieval_package_id")
        ),
        "retrieval_package_hash": _optional_sha256(
            request_metadata.get("retrieval_package_hash")
        ),
        "structured_draft_id": _optional_text(
            request_metadata.get("structured_draft_id")
        ),
        "raw_output_included": False,
        "evidence_text_included": False,
        "prompt_text_included": False,
        "provider_detail_included": False,
    }


def build_citation_quality_workflow(
    cx_record: Mapping[str, Any],
    *,
    interaction_id: str,
    cx_generation_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(cx_record, Mapping):
        raise _invalid("CX generation metadata must be an object.")
    interaction = _required_text(interaction_id, "interaction_id")
    generation_id = _required_text(
        cx_generation_id or cx_record.get("cx_generation_id"),
        "cx_generation_id",
    )
    quality = build_grounded_response_quality_contract(cx_record)
    request_metadata = _mapping(cx_record.get("request_metadata"))
    repair = _repair_projection(request_metadata.get("citation_repair"))
    workflow_status = _workflow_status(quality, repair)
    repair["status"] = _repair_status(workflow_status, repair["attempted"])
    operator_required = workflow_status == "ATTENTION_REQUIRED"
    return validate_citation_quality_workflow(
        {
            "workflow_schema_version": AE_CITATION_QUALITY_WORKFLOW_SCHEMA_VERSION,
            "interaction_id": interaction,
            "cx_generation_id": generation_id,
            "workflow_status": workflow_status,
            "next_action": _WORKFLOW_ACTIONS[workflow_status],
            "quality": quality,
            "repair": repair,
            "operator_remediation": {
                "mode": "SEPARATE_HANDOFF",
                "required": operator_required,
                "handoff_included": False,
            },
            "owner_scope_enforced": True,
            "content_included": False,
        }
    )


def validate_citation_quality_workflow(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _WORKFLOW_FIELDS:
        raise _invalid("Citation quality workflow has an invalid shape.")
    workflow = deepcopy(dict(value))
    if workflow["workflow_schema_version"] != (
        AE_CITATION_QUALITY_WORKFLOW_SCHEMA_VERSION
    ):
        raise _invalid("Citation quality workflow schema version is invalid.")
    for field in ("interaction_id", "cx_generation_id"):
        workflow[field] = _required_text(workflow[field], field)
    workflow["quality"] = _validate_quality(workflow["quality"])
    workflow["repair"] = _validate_repair(workflow["repair"])
    workflow["operator_remediation"] = _validate_operator_remediation(
        workflow["operator_remediation"]
    )
    expected_status = _workflow_status(workflow["quality"], workflow["repair"])
    if workflow["workflow_status"] != expected_status:
        raise _invalid("Citation quality workflow status is inconsistent.")
    if workflow["next_action"] != _WORKFLOW_ACTIONS[expected_status]:
        raise _invalid("Citation quality workflow next action is inconsistent.")
    expected_repair_status = _repair_status(
        expected_status, workflow["repair"]["attempted"]
    )
    if workflow["repair"]["status"] != expected_repair_status:
        raise _invalid("Citation quality repair status is inconsistent.")
    expected_operator_required = expected_status == "ATTENTION_REQUIRED"
    if workflow["operator_remediation"]["required"] is not (
        expected_operator_required
    ):
        raise _invalid("Operator remediation requirement is inconsistent.")
    if workflow["owner_scope_enforced"] is not True:
        raise _invalid("Citation quality workflow must enforce owner scope.")
    if workflow["content_included"] is not False:
        raise _invalid("Citation quality workflow must not include content.")
    return workflow


def _validate_quality(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _QUALITY_FIELDS:
        raise _invalid("Citation quality metadata has an invalid shape.")
    quality = deepcopy(dict(value))
    if quality["contract_schema_version"] != (
        AE_CHAT_GROUNDED_RESPONSE_QUALITY_CONTRACT_VERSION
    ):
        raise _invalid("Citation quality contract version is invalid.")
    if quality["boundary_status"] not in _BOUNDARY_STATUSES:
        raise _invalid("Citation quality boundary status is invalid.")
    if quality["citation_status"] not in _CITATION_STATUSES:
        raise _invalid("Citation validation status is invalid.")
    issue_count = quality["issue_count"]
    if (
        isinstance(issue_count, bool)
        or not isinstance(issue_count, int)
        or issue_count < 0
    ):
        raise _invalid("Citation quality issue count is invalid.")
    if not isinstance(quality["grounding_required"], bool):
        raise _invalid("Citation grounding requirement is invalid.")
    expected_action = _quality_action(quality["boundary_status"], issue_count)
    if quality["recommended_action"] != expected_action:
        raise _invalid("Citation quality recommended action is inconsistent.")
    for field in (
        "raw_output_included",
        "evidence_text_included",
        "prompt_text_included",
        "provider_detail_included",
    ):
        if quality[field] is not False:
            raise _invalid("Citation quality projection contains private content.")
    quality["source_audit_schema_version"] = _nullable_text(
        quality["source_audit_schema_version"], "source_audit_schema_version"
    )
    quality["retrieval_package_id"] = _nullable_text(
        quality["retrieval_package_id"], "retrieval_package_id"
    )
    quality["retrieval_package_hash"] = _nullable_sha256(
        quality["retrieval_package_hash"], "retrieval_package_hash"
    )
    quality["structured_draft_id"] = _nullable_text(
        quality["structured_draft_id"], "structured_draft_id"
    )
    return quality


def _repair_projection(value: object) -> dict[str, Any]:
    if value is None:
        return {
            "source_projection_present": False,
            "repair_schema_version": None,
            "mode": "NONE",
            "status": "NOT_ATTEMPTED",
            "attempted": False,
            "attempt_count": 0,
            "max_attempts": 1,
            "trigger_error_code": None,
            "same_retrieval_package": None,
            "original_provider_prompt_package_hash": None,
            "effective_provider_prompt_package_hash": None,
            "invalid_output_included": False,
        }
    if not isinstance(value, Mapping):
        raise _invalid("CX citation repair metadata must be an object.")
    return {
        "source_projection_present": True,
        "repair_schema_version": value.get("repair_schema_version"),
        "mode": "BOUNDED_INLINE",
        "status": "NOT_ATTEMPTED",
        "attempted": value.get("attempted"),
        "attempt_count": value.get("attempt_count"),
        "max_attempts": value.get("max_attempts"),
        "trigger_error_code": value.get("trigger_error_code"),
        "same_retrieval_package": value.get("same_retrieval_package"),
        "original_provider_prompt_package_hash": value.get(
            "original_provider_prompt_package_hash"
        ),
        "effective_provider_prompt_package_hash": value.get(
            "effective_provider_prompt_package_hash"
        ),
        "invalid_output_included": value.get("invalid_output_included"),
    }


def _validate_repair(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REPAIR_FIELDS:
        raise _invalid("Citation repair workflow metadata has an invalid shape.")
    repair = deepcopy(dict(value))
    if not isinstance(repair["source_projection_present"], bool):
        raise _invalid("Citation repair source projection flag is invalid.")
    if repair["source_projection_present"] is False:
        expected = _repair_projection(None)
        if repair != expected:
            raise _invalid("Absent citation repair projection is inconsistent.")
        return repair
    if (
        repair["repair_schema_version"] != _CX_CITATION_REPAIR_SCHEMA_VERSION
        or repair["mode"] != "BOUNDED_INLINE"
    ):
        raise _invalid("Citation repair source contract is invalid.")
    attempted = repair["attempted"]
    count = repair["attempt_count"]
    if not isinstance(attempted, bool) or (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count != (1 if attempted else 0)
    ):
        raise _invalid("Citation repair attempt metadata is inconsistent.")
    if repair["max_attempts"] != 1:
        raise _invalid("Citation repair maximum attempts is invalid.")
    trigger = repair["trigger_error_code"]
    if (attempted and trigger not in _REPAIRABLE_ERROR_CODES) or (
        not attempted and trigger is not None
    ):
        raise _invalid("Citation repair trigger is inconsistent.")
    if repair["same_retrieval_package"] is not True:
        raise _invalid("Citation repair must reuse the retrieval package.")
    original_hash = _required_sha256(
        repair["original_provider_prompt_package_hash"],
        "original_provider_prompt_package_hash",
    )
    effective_hash = _required_sha256(
        repair["effective_provider_prompt_package_hash"],
        "effective_provider_prompt_package_hash",
    )
    if not attempted and original_hash != effective_hash:
        raise _invalid("Unattempted citation repair changed the prompt hash.")
    if repair["invalid_output_included"] is not False:
        raise _invalid("Citation repair workflow contains invalid output.")
    repair["original_provider_prompt_package_hash"] = original_hash
    repair["effective_provider_prompt_package_hash"] = effective_hash
    return repair


def _validate_operator_remediation(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _OPERATOR_REMEDIATION_FIELDS:
        raise _invalid("Operator remediation metadata has an invalid shape.")
    projection = deepcopy(dict(value))
    if projection["mode"] != "SEPARATE_HANDOFF":
        raise _invalid("Operator remediation mode is invalid.")
    if not isinstance(projection["required"], bool):
        raise _invalid("Operator remediation requirement is invalid.")
    if projection["handoff_included"] is not False:
        raise _invalid("Citation workflow must not embed remediation handoffs.")
    return projection


def _workflow_status(quality: Mapping[str, Any], repair: Mapping[str, Any]) -> str:
    if quality["grounding_required"] is False:
        return "NOT_REQUIRED"
    if quality["boundary_status"] == "PASS":
        return "REPAIRED" if repair["attempted"] else "VALIDATED"
    return "ATTENTION_REQUIRED"


def _repair_status(workflow_status: str, attempted: bool) -> str:
    if not attempted:
        return "NOT_ATTEMPTED"
    if workflow_status == "REPAIRED":
        return "SUCCEEDED"
    return "ATTENTION_REQUIRED"


def _boundary_status(value: object, *, grounding_required: bool) -> str:
    status = _optional_text(value)
    if status in {"PASS", "WARN", "FAIL", "NOT_REQUIRED"}:
        return status
    return "NOT_REQUIRED" if not grounding_required else "UNKNOWN"


def _citation_status(value: object, *, boundary_status: str) -> str:
    status = _optional_text(value)
    if status in _CITATION_STATUSES:
        return status
    return "NOT_REQUIRED" if boundary_status == "NOT_REQUIRED" else "UNKNOWN"


def _quality_action(boundary_status: str, issue_count: int) -> str:
    if boundary_status == "FAIL":
        return "show_error"
    if boundary_status in {"WARN", "UNKNOWN"} or issue_count > 0:
        return "proceed_with_caveat"
    return "proceed"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _required_text(value: object, field: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise _invalid(f"Citation quality workflow {field} is invalid.")
    return normalized


def _nullable_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    normalized = _optional_text(value)
    if normalized is None:
        raise _invalid(f"Citation quality workflow {field} is invalid.")
    return normalized


def _optional_sha256(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _SHA256_PATTERN.fullmatch(value.strip()):
        return value.strip()
    return None


def _nullable_sha256(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_sha256(value, field)


def _required_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value.strip()) is None:
        raise _invalid(f"Citation quality workflow {field} is invalid.")
    return value.strip()


def _invalid(detail: str) -> AeCitationQualityWorkflowError:
    return AeCitationQualityWorkflowError(
        error_code="ae.citation_quality_workflow.invalid",
        detail=detail,
    )
