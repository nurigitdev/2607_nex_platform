from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5


CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def build_structured_draft(
    *,
    cx_generation_id: str,
    trace_id: str,
    request_id: str,
    output_text: str,
    compatibility_rule: dict[str, Any] | None,
    retrieval_package: dict[str, Any] | None,
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
            "warnings": build_validation_warnings(
                compatibility_rule=compatibility_rule,
                retrieval_package=retrieval_package,
            ),
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
    citation_policy = compatibility_rule.get("citation_policy", {}) if compatibility_rule else {}
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
    if compatibility_rule and compatibility_rule["grounding_required"] and retrieval_package is None:
        return ["grounding_required_without_retrieval_package"]
    return []


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
