from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import re
from typing import Any


GROUNDED_OUTPUT_VALIDATION_SCHEMA_VERSION = "cx_grounded_output_validation.v1"
_CITATION_PATTERN = re.compile(r"\[[1-9][0-9]*\]")


@dataclass(frozen=True)
class GroundedOutputValidationError(RuntimeError):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def normalize_generation_provider_response(
    response: object,
    *,
    grounding_required: bool,
    retrieval_package: Mapping[str, Any] | None,
    selected_evidence_ids: Sequence[str] | None,
) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        raise _invalid("MO generation response must be an object.")
    output = response.get("output")
    if not isinstance(output, Mapping) or output.get("type") != "text":
        raise _invalid("MO generation output must use the text type.")
    output_text = output.get("text")
    if not isinstance(output_text, str) or not output_text.strip():
        raise _invalid("MO generation output text must not be empty.")
    normalized_text = output_text.strip()
    finish_reason = _required_text(response.get("finish_reason"), "finish_reason").upper()
    if finish_reason != "STOP":
        raise GroundedOutputValidationError(
            status_code=502,
            error_code="cx.provider_output_incomplete",
            detail=f"MO generation stopped with finish reason {finish_reason}.",
            retryable=True,
        )
    citations = _validate_grounded_citations(
        normalized_text,
        grounding_required=grounding_required,
        retrieval_package=retrieval_package,
        selected_evidence_ids=selected_evidence_ids,
    )
    return {
        "mo_generation_id": _required_text(
            response.get("mo_generation_id"),
            "mo_generation_id",
        ),
        "alias": _required_text(response.get("alias"), "alias"),
        "model_revision": _required_text(
            response.get("model_revision"),
            "model_revision",
        ),
        "deployment_id": _required_text(
            response.get("deployment_id"),
            "deployment_id",
        ),
        "provider_type": _required_text(
            response.get("provider_type"),
            "provider_type",
        ),
        "output": {"type": "text", "text": normalized_text},
        "finish_reason": finish_reason,
        "usage": _safe_usage(response.get("usage")),
        "runtime_metadata": _safe_mapping(response.get("runtime_metadata")),
        "grounded_output_validation": {
            "validation_schema_version": GROUNDED_OUTPUT_VALIDATION_SCHEMA_VERSION,
            "status": "PASS",
            "grounding_required": grounding_required,
            "output_sha256": hashlib.sha256(
                normalized_text.encode("utf-8")
            ).hexdigest(),
            "output_char_count": len(normalized_text),
            "citation_labels": citations,
            "citation_count": len(citations),
            "raw_output_included": False,
        },
    }


def _validate_grounded_citations(
    output_text: str,
    *,
    grounding_required: bool,
    retrieval_package: Mapping[str, Any] | None,
    selected_evidence_ids: Sequence[str] | None,
) -> list[str]:
    labels = _citation_labels(output_text)
    if not grounding_required:
        return labels
    evidence_by_label = _evidence_by_label(retrieval_package)
    if not labels:
        raise GroundedOutputValidationError(
            status_code=502,
            error_code="cx.citation_required_missing",
            detail="Grounded generation output must include an evidence citation.",
            retryable=True,
        )
    selected_ids = _selected_ids(
        selected_evidence_ids,
        available_ids={item["evidence_id"] for item in evidence_by_label.values()},
    )
    for label in labels:
        evidence = evidence_by_label.get(label)
        if evidence is None or evidence["evidence_id"] not in selected_ids:
            raise GroundedOutputValidationError(
                status_code=502,
                error_code="cx.citation_validation_failed",
                detail="Grounded generation cited evidence outside the admitted set.",
                retryable=True,
            )
    return labels


def _evidence_by_label(
    retrieval_package: Mapping[str, Any] | None,
) -> dict[str, dict[str, str]]:
    if not isinstance(retrieval_package, Mapping):
        raise _invalid("Grounded generation requires a retrieval package.")
    raw_items = retrieval_package.get("evidence_items")
    if isinstance(raw_items, (str, bytes)) or not isinstance(raw_items, Sequence):
        raise _invalid("Grounded retrieval evidence must be a list.")
    evidence: dict[str, dict[str, str]] = {}
    evidence_ids: set[str] = set()
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise _invalid("Grounded retrieval evidence item must be an object.")
        label = _required_text(item.get("citation_label"), "citation_label")
        evidence_id = _required_text(item.get("evidence_id"), "evidence_id")
        if label in evidence or evidence_id in evidence_ids:
            raise _invalid("Grounded retrieval citation bindings must be unique.")
        evidence[label] = {
            "citation_label": label,
            "evidence_id": evidence_id,
        }
        evidence_ids.add(evidence_id)
    if not evidence:
        raise _invalid("Grounded retrieval evidence must not be empty.")
    return evidence


def _selected_ids(
    value: Sequence[str] | None,
    *,
    available_ids: set[str],
) -> set[str]:
    if value is None or len(value) == 0:
        return available_ids
    if isinstance(value, (str, bytes)):
        raise _invalid("selected_evidence_ids must be a list.")
    selected = {
        _required_text(item, "selected_evidence_id")
        for item in value
    }
    if len(selected) != len(value) or not selected.issubset(available_ids):
        raise _invalid("selected_evidence_ids do not match admitted evidence.")
    return selected


def _citation_labels(output_text: str) -> list[str]:
    return list(dict.fromkeys(_CITATION_PATTERN.findall(output_text)))


def _safe_usage(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: item
        for key in ("input_tokens", "output_tokens", "total_tokens")
        if isinstance((item := value.get(key)), int)
        and not isinstance(item, bool)
        and item >= 0
    }


def _safe_mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"MO generation field {field} is invalid.")
    return value.strip()


def _invalid(detail: str) -> GroundedOutputValidationError:
    return GroundedOutputValidationError(
        status_code=502,
        error_code="cx.provider_output_invalid",
        detail=detail,
        retryable=True,
    )
