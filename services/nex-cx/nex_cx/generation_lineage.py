from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from nex_cx.citation_repair import (
    CitationRepairError,
    validate_citation_repair_projection,
)
from nex_cx.grounded_prompt import (
    GroundedPromptPackageError,
    build_grounded_evidence_binding,
)

CX_GROUNDED_GENERATION_LINEAGE_SCHEMA_VERSION = "cx_grounded_generation_lineage.v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_LINEAGE_FIELDS = {
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


@dataclass(frozen=True)
class GroundedGenerationLineageError(RuntimeError):
    error_code: str
    detail: str
    status_code: int = 422
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def build_grounded_generation_lineage(
    *,
    mo_payload: Mapping[str, Any],
    retrieval_package: Mapping[str, Any],
    selected_evidence_ids: Sequence[str] | None,
    structured_draft: Mapping[str, Any],
    citation_repair: Mapping[str, Any] | None,
) -> dict[str, Any]:
    try:
        binding = build_grounded_evidence_binding(
            retrieval_package=retrieval_package,
            selected_evidence_ids=selected_evidence_ids,
        )
    except GroundedPromptPackageError as exc:
        raise _invalid("Grounded generation evidence binding is invalid.") from exc

    metadata = mo_payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise _invalid("Grounded generation provider metadata is unavailable.")
    if metadata.get("retrieval_package_id") != binding["retrieval_package_id"] or (
        metadata.get("retrieval_package_hash") != binding["retrieval_package_hash"]
    ):
        raise _invalid("Grounded generation retrieval package identity changed.")
    if metadata.get("evidence_binding_hash") != binding["evidence_binding_hash"]:
        raise _invalid("Grounded generation evidence binding changed.")
    if metadata.get("selected_evidence_count") != len(binding["selected_evidence_ids"]):
        raise _invalid("Grounded generation selected evidence count changed.")

    validation = structured_draft.get("validation")
    if (
        not isinstance(validation, Mapping)
        or validation.get("citation_status") != "VALIDATED"
    ):
        raise _invalid("Grounded generation citation validation did not pass.")

    effective_hash = _sha256(
        mo_payload.get("provider_prompt_package_hash"),
        "effective_provider_prompt_package_hash",
    )
    if citation_repair is None:
        repair_attempted = False
        repair_attempt_count = 0
        original_hash = effective_hash
    else:
        try:
            repair = validate_citation_repair_projection(citation_repair)
        except CitationRepairError as exc:
            raise _invalid(
                "Grounded generation citation repair lineage is invalid."
            ) from exc
        if repair["effective_provider_prompt_package_hash"] != effective_hash:
            raise _invalid("Grounded generation effective prompt hash changed.")
        repair_attempted = repair["attempted"]
        repair_attempt_count = repair["attempt_count"]
        original_hash = repair["original_provider_prompt_package_hash"]

    return validate_grounded_generation_lineage(
        {
            "lineage_schema_version": CX_GROUNDED_GENERATION_LINEAGE_SCHEMA_VERSION,
            "retrieval_package_id": binding["retrieval_package_id"],
            "retrieval_package_hash": binding["retrieval_package_hash"],
            "evidence_binding_hash": binding["evidence_binding_hash"],
            "selected_evidence_count": len(binding["selected_evidence_ids"]),
            "citation_validation_status": "VALIDATED",
            "citation_repair_attempted": repair_attempted,
            "citation_repair_attempt_count": repair_attempt_count,
            "original_provider_prompt_package_hash": original_hash,
            "effective_provider_prompt_package_hash": effective_hash,
            "same_retrieval_package": True,
            "private_evidence_included": False,
        }
    )


def validate_grounded_generation_lineage(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _LINEAGE_FIELDS:
        raise _invalid("Grounded generation lineage has an invalid shape.")
    lineage = deepcopy(dict(value))
    if lineage["lineage_schema_version"] != (
        CX_GROUNDED_GENERATION_LINEAGE_SCHEMA_VERSION
    ):
        raise _invalid("Grounded generation lineage schema version is invalid.")
    lineage["retrieval_package_id"] = _required_text(
        lineage["retrieval_package_id"], "retrieval_package_id"
    )
    for field in (
        "retrieval_package_hash",
        "evidence_binding_hash",
        "original_provider_prompt_package_hash",
        "effective_provider_prompt_package_hash",
    ):
        lineage[field] = _sha256(lineage[field], field)
    selected_count = lineage["selected_evidence_count"]
    if (
        isinstance(selected_count, bool)
        or not isinstance(selected_count, int)
        or selected_count < 1
    ):
        raise _invalid("Grounded generation selected evidence count is invalid.")
    if lineage["citation_validation_status"] != "VALIDATED":
        raise _invalid("Grounded generation citation validation status is invalid.")
    attempted = lineage["citation_repair_attempted"]
    attempt_count = lineage["citation_repair_attempt_count"]
    if not isinstance(attempted, bool) or (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count != (1 if attempted else 0)
    ):
        raise _invalid("Grounded generation citation repair metadata is inconsistent.")
    if not attempted and lineage["original_provider_prompt_package_hash"] != (
        lineage["effective_provider_prompt_package_hash"]
    ):
        raise _invalid("Unrepaired grounded generation changed its prompt hash.")
    if lineage["same_retrieval_package"] is not True:
        raise _invalid("Grounded generation must reuse the retrieval package.")
    if lineage["private_evidence_included"] is not False:
        raise _invalid("Grounded generation lineage cannot include private evidence.")
    return lineage


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
        raise _invalid(f"Grounded generation {field} is invalid.")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    normalized = _required_text(value, field).lower()
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        raise _invalid(f"Grounded generation {field} must be a SHA-256 value.")
    return normalized


def _invalid(detail: str) -> GroundedGenerationLineageError:
    return GroundedGenerationLineageError(
        error_code="cx.grounded_generation_lineage.invalid",
        detail=detail,
    )
