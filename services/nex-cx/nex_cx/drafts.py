from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5


CITATION_PATTERN = re.compile(r"\[(\d+)\]")
CX_GROUNDED_RESPONSE_CITATION_QUALITY_AUDIT_SCHEMA_VERSION = (
    "cx_grounded_response_citation_quality_audit.v1"
)
CITATION_QUALITY_STAGES = (
    "grounding_requirement",
    "citation_presence",
    "citation_evidence_membership",
    "selected_evidence_coverage",
    "raw_output_redaction",
)
FORBIDDEN_RESPONSE_AUDIT_RAW_KEYS = {
    "prompt",
    "messages",
    "content",
    "output_text",
    "raw_output",
    "text",
    "chunk_text",
    "source_text",
    "query_text",
    "provider_url",
    "provider_endpoint",
    "model_path",
    "api_key",
}


def build_structured_draft(
    *,
    cx_generation_id: str,
    trace_id: str,
    request_id: str,
    output_text: str,
    compatibility_rule: dict[str, Any] | None,
    retrieval_package: dict[str, Any] | None,
    selected_evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    text = output_text.strip()
    text_hash = sha256_text(text)
    draft_id = str(uuid5(NAMESPACE_URL, f"cx-structured-draft:{cx_generation_id}:{text_hash}"))
    citations = build_citation_claims(
        output_text=text,
        retrieval_package=retrieval_package,
    )
    validation_errors = validate_citation_claims(
        citations=citations,
        compatibility_rule=compatibility_rule,
        retrieval_package=retrieval_package,
    )
    validation_warnings = build_validation_warnings(
        compatibility_rule=compatibility_rule,
        retrieval_package=retrieval_package,
    )
    quality_audit = build_grounded_response_citation_quality_audit(
        output_text=text,
        citations=citations,
        validation_errors=validation_errors,
        validation_warnings=validation_warnings,
        compatibility_rule=compatibility_rule,
        retrieval_package=retrieval_package,
        selected_evidence_ids=selected_evidence_ids,
    )
    now = _utc_now()
    return {
        "structured_draft_schema_version": "cx_structured_draft.v1",
        "structured_draft_id": draft_id,
        "cx_generation_id": cx_generation_id,
        "status": "VALIDATED" if not validation_errors else "VALIDATION_FAILED",
        "trace_id": trace_id,
        "request_id": request_id,
        "title": build_title(text),
        "summary": build_summary(text),
        "content_hash": text_hash,
        "sections": [
            {
                "section_id": str(uuid5(NAMESPACE_URL, f"{draft_id}:section:1")),
                "ordinal": 1,
                "heading": "Generated response",
                "blocks": [
                    {
                        "block_id": str(uuid5(NAMESPACE_URL, f"{draft_id}:block:1")),
                        "block_type": "paragraph",
                        "text_hash": text_hash,
                        "text_preview": text[:240],
                    }
                ],
            }
        ],
        "citations": citations,
        "validation": {
            "validator_profile_id": "mock-structured-draft-validator-v1",
            "citation_status": "VALIDATED" if not validation_errors else "FAILED",
            "errors": validation_errors,
            "warnings": validation_warnings,
            "quality_audit": quality_audit,
        },
        "metadata": {
            "raw_output_stored_in_public_record": False,
            "retrieval_package_id": retrieval_package["retrieval_package_id"]
            if retrieval_package
            else None,
            "compatibility_rule_id": compatibility_rule["compatibility_rule_id"]
            if compatibility_rule
            else None,
        },
        "created_at": now,
        "updated_at": now,
    }


def build_grounded_response_citation_quality_audit(
    *,
    output_text: str,
    citations: list[dict[str, Any]],
    validation_errors: list[dict[str, Any]],
    validation_warnings: list[str],
    compatibility_rule: dict[str, Any] | None,
    retrieval_package: dict[str, Any] | None,
    selected_evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    citation_policy = _mapping_value(
        compatibility_rule.get("citation_policy") if compatibility_rule else None
    )
    grounding_required = bool(
        compatibility_rule and compatibility_rule.get("grounding_required")
    )
    citations_required = bool(citation_policy.get("citations_required"))
    source_trace_required = bool(citation_policy.get("source_trace_required"))
    selected_ids = _selected_evidence_ids(selected_evidence_ids)
    cited_evidence_ids = {
        citation["evidence_id"]
        for citation in citations
        if isinstance(citation.get("evidence_id"), str)
    }
    stage_status = {
        "grounding_requirement": "PASS" if grounding_required else "NOT_REQUIRED",
        "citation_presence": _citation_presence_status(
            citations=citations,
            citations_required=citations_required,
        ),
        "citation_evidence_membership": _citation_membership_status(citations),
        "selected_evidence_coverage": _selected_evidence_coverage_status(
            selected_ids=selected_ids,
            cited_evidence_ids=cited_evidence_ids,
        ),
        "raw_output_redaction": "PASS",
    }
    boundary_status = _citation_quality_boundary_status(
        stage_status=stage_status,
        validation_errors=validation_errors,
        grounding_required=grounding_required,
        citations_required=citations_required,
        citations=citations,
    )
    audit = {
        "audit_schema_version": CX_GROUNDED_RESPONSE_CITATION_QUALITY_AUDIT_SCHEMA_VERSION,
        "boundary_id": "cx.grounded_response.citation_quality",
        "service_id": "nex-cx",
        "boundary_status": boundary_status,
        "grounding_required": grounding_required,
        "citations_required": citations_required,
        "source_trace_required": source_trace_required,
        "output_summary": {
            "output_hash": sha256_text(output_text),
            "output_char_count": len(output_text),
            "raw_output_included": False,
        },
        "citation_summary": {
            "citation_count": len(citations),
            "valid_citation_count": len(
                [citation for citation in citations if citation.get("valid") is True]
            ),
            "invalid_citation_count": len(
                [citation for citation in citations if citation.get("valid") is False]
            ),
            "missing_required_citation": citations_required and not citations,
            "citation_labels": [
                citation["citation_label"]
                for citation in citations
                if isinstance(citation.get("citation_label"), str)
            ],
            "validation_error_codes": sorted(
                {
                    error["code"]
                    for error in validation_errors
                    if isinstance(error.get("code"), str)
                }
            ),
        },
        "retrieval_summary": {
            "retrieval_package_id": retrieval_package.get("retrieval_package_id")
            if retrieval_package
            else None,
            "package_hash": retrieval_package.get("package_hash")
            if retrieval_package
            else None,
            "evidence_item_count": len(
                _list_value(retrieval_package.get("evidence_items"))
                if retrieval_package
                else []
            ),
            "selected_evidence_count": len(selected_ids),
            "selected_evidence_cited_count": len(selected_ids & cited_evidence_ids),
            "source_trace_required": source_trace_required,
        },
        "stage_status": stage_status,
        "issues": _citation_quality_issues(validation_errors),
        "warnings": _warning_kinds(validation_warnings),
        "recommended_action": _citation_quality_recommended_action(
            boundary_status=boundary_status,
            stage_status=stage_status,
        ),
        "refactoring_checkpoint": {
            "validation_entrypoint": (
                "build_grounded_response_citation_quality_audit"
            ),
            "legacy_entrypoint": "validate_citation_claims",
            "previous_guard_slot": "retrieval_package_quality",
            "active_guard_slot": "grounded_response_citation_validation",
            "next_guard_slot": "ae_chat_grounded_response_quality_surface",
            "external_api_changed": True,
            "database_schema_changed": False,
        },
        "redaction": {
            "status": "PASS",
            "raw_output_included": False,
            "evidence_text_included": False,
            "prompt_text_included": False,
            "provider_detail_included": False,
        },
    }
    assert_grounded_response_citation_quality_audit_redacted(
        audit,
        output_text=output_text,
        retrieval_package=retrieval_package,
    )
    return audit


def build_citation_claims(
    *,
    output_text: str,
    retrieval_package: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    evidence_by_label = evidence_index_by_label(retrieval_package)
    citations: list[dict[str, Any]] = []
    for label in citation_labels(output_text):
        evidence = evidence_by_label.get(label)
        citations.append(
            {
                "citation_label": label,
                "evidence_id": evidence["evidence_id"] if evidence else None,
                "retrieval_package_id": retrieval_package["retrieval_package_id"]
                if retrieval_package
                else None,
                "valid": evidence is not None,
                "validation_error": None if evidence else "citation_evidence_not_found",
            }
        )
    return citations


def validate_citation_claims(
    *,
    citations: list[dict[str, Any]],
    compatibility_rule: dict[str, Any] | None,
    retrieval_package: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    citation_policy = (
        compatibility_rule.get("citation_policy", {}) if compatibility_rule else {}
    )
    citations_required = bool(citation_policy.get("citations_required"))
    if citations_required and not citations:
        errors.append(
            {
                "code": "cx.citation_required_missing",
                "detail": "The compatibility rule requires citations.",
            }
        )
    if citations and retrieval_package is None:
        errors.append(
            {
                "code": "cx.citation_retrieval_package_missing",
                "detail": "Citation claims require a retrieval package.",
            }
        )
    for citation in citations:
        if not citation["valid"]:
            errors.append(
                {
                    "code": "cx.citation_evidence_mismatch",
                    "detail": f"Citation is not in retrieval package: {citation['citation_label']}",
                }
            )
    return errors


def build_validation_warnings(
    *,
    compatibility_rule: dict[str, Any] | None,
    retrieval_package: dict[str, Any] | None,
) -> list[str]:
    if (
        compatibility_rule
        and compatibility_rule["grounding_required"]
        and retrieval_package is None
    ):
        return ["grounding_required_without_retrieval_package"]
    return []


def assert_grounded_response_citation_quality_audit_redacted(
    audit: dict[str, Any],
    *,
    output_text: str,
    retrieval_package: dict[str, Any] | None,
) -> None:
    serialized = json.dumps(audit, ensure_ascii=False, sort_keys=True)
    if _protected_value_leaked(serialized, output_text):
        raise ValueError("grounded response citation quality audit leaked raw output")
    if retrieval_package is not None:
        for value in _forbidden_audit_values(retrieval_package):
            if _protected_value_leaked(serialized, value):
                raise ValueError(
                    "grounded response citation quality audit leaked retrieval payload"
                )


def citation_labels(output_text: str) -> list[str]:
    seen: set[str] = set()
    labels: list[str] = []
    for match in CITATION_PATTERN.finditer(output_text):
        label = f"[{match.group(1)}]"
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def evidence_index_by_label(
    retrieval_package: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if retrieval_package is None:
        return {}
    return {
        item["citation_label"]: item
        for item in retrieval_package.get("evidence_items", [])
        if isinstance(item.get("citation_label"), str)
        and isinstance(item.get("evidence_id"), str)
    }


def _citation_presence_status(
    *,
    citations: list[dict[str, Any]],
    citations_required: bool,
) -> str:
    if citations:
        return "PASS"
    return "FAIL" if citations_required else "NOT_REQUIRED"


def _citation_membership_status(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "NOT_REQUIRED"
    return (
        "PASS"
        if all(citation.get("valid") is True for citation in citations)
        else "FAIL"
    )


def _selected_evidence_coverage_status(
    *,
    selected_ids: set[str],
    cited_evidence_ids: set[str],
) -> str:
    if not selected_ids:
        return "NOT_REQUIRED"
    cited_selected_ids = selected_ids & cited_evidence_ids
    if not cited_selected_ids:
        return "PARTIAL"
    if cited_selected_ids == selected_ids:
        return "PASS"
    return "PARTIAL"


def _citation_quality_boundary_status(
    *,
    stage_status: dict[str, str],
    validation_errors: list[dict[str, Any]],
    grounding_required: bool,
    citations_required: bool,
    citations: list[dict[str, Any]],
) -> str:
    if validation_errors:
        return "FAIL"
    if not grounding_required and not citations_required and not citations:
        return "NOT_REQUIRED"
    if "FAIL" in stage_status.values():
        return "FAIL"
    return "PASS"


def _citation_quality_issues(
    validation_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "stage": _stage_for_validation_error_code(error.get("code")),
            "error_code": error.get("code", "cx.citation_quality_unknown"),
            "retryable": False,
        }
        for error in validation_errors
    ]


def _stage_for_validation_error_code(value: Any) -> str:
    if value == "cx.citation_required_missing":
        return "citation_presence"
    if value in {
        "cx.citation_retrieval_package_missing",
        "cx.citation_evidence_mismatch",
    }:
        return "citation_evidence_membership"
    return "grounded_response_citation_validation"


def _citation_quality_recommended_action(
    *,
    boundary_status: str,
    stage_status: dict[str, str],
) -> str:
    if boundary_status == "FAIL":
        return "repair_or_retry"
    if "PARTIAL" in stage_status.values():
        return "proceed_with_caveat"
    return "proceed"


def _selected_evidence_ids(value: list[str] | None) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item.strip() for item in value if isinstance(item, str) and item.strip()}


def _warning_kinds(value: list[str]) -> list[str]:
    return sorted({item.split(":", 1)[0].strip() for item in value if item.strip()})


def _forbidden_audit_values(value: Any, *, parent_key: str | None = None) -> list[str]:
    if isinstance(value, dict):
        collected: list[str] = []
        for key, item in value.items():
            key_string = str(key)
            if key_string in FORBIDDEN_RESPONSE_AUDIT_RAW_KEYS or _secretish_key(
                key_string
            ):
                collected.extend(_string_values(item))
                continue
            collected.extend(_forbidden_audit_values(item, parent_key=key_string))
        return collected
    if isinstance(value, list):
        collected = []
        for item in value:
            collected.extend(_forbidden_audit_values(item, parent_key=parent_key))
        return collected
    return []


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        collected: list[str] = []
        for item in value.values():
            collected.extend(_string_values(item))
        return collected
    if isinstance(value, list):
        collected = []
        for item in value:
            collected.extend(_string_values(item))
        return collected
    return []


def _protected_value_leaked(serialized: str, value: str) -> bool:
    return len(value) >= 8 and value in serialized


def _secretish_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in ("secret", "password", "token"))


def _mapping_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def build_title(output_text: str) -> str:
    first_line = output_text.strip().splitlines()[0] if output_text.strip() else "Untitled"
    return first_line[:80]


def build_summary(output_text: str) -> str:
    text = " ".join(output_text.strip().split())
    return text[:160]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
