from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Protocol

from nex_cx.grounded_output_validation import (
    GroundedOutputValidationError,
    normalize_generation_provider_response,
)
from nex_cx.grounded_prompt import (
    GroundedPromptPackageError,
    build_grounded_evidence_binding,
)


CX_CITATION_REPAIR_SCHEMA_VERSION = "cx_citation_repair.v1"
MAX_CITATION_REPAIR_ATTEMPTS = 1
_REPAIRABLE_ERROR_CODES = frozenset(
    {"cx.citation_required_missing", "cx.citation_validation_failed"}
)


class CitationRepairGenerationClient(Protocol):
    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CitationRepairResult:
    mo_response: dict[str, Any]
    effective_mo_payload: dict[str, Any]
    repair: dict[str, Any]


@dataclass(frozen=True)
class CitationRepairError(RuntimeError):
    error_code: str
    detail: str
    status_code: int = 422
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def generate_with_bounded_citation_repair(
    *,
    generation_client: CitationRepairGenerationClient,
    mo_payload: Mapping[str, Any],
    request_id: str,
    trace_id: str,
    grounding_required: bool,
    retrieval_package: Mapping[str, Any] | None,
    selected_evidence_ids: Sequence[str] | None,
    cancellation_checkpoint: Callable[[], None],
) -> CitationRepairResult:
    original_payload = deepcopy(dict(mo_payload))
    raw_response = generation_client.create_generation(
        original_payload,
        request_id=request_id,
        trace_id=trace_id,
    )
    cancellation_checkpoint()
    try:
        normalized = _normalize(
            raw_response,
            grounding_required=grounding_required,
            retrieval_package=retrieval_package,
            selected_evidence_ids=selected_evidence_ids,
        )
    except GroundedOutputValidationError as exc:
        if exc.error_code not in _REPAIRABLE_ERROR_CODES:
            raise
        repair_payload = build_citation_repair_payload(
            original_payload,
            retrieval_package=retrieval_package,
            selected_evidence_ids=selected_evidence_ids,
            trigger_error_code=exc.error_code,
        )
        repaired_raw_response = generation_client.create_generation(
            repair_payload,
            request_id=request_id,
            trace_id=trace_id,
        )
        cancellation_checkpoint()
        repaired = _normalize(
            repaired_raw_response,
            grounding_required=True,
            retrieval_package=retrieval_package,
            selected_evidence_ids=selected_evidence_ids,
        )
        return CitationRepairResult(
            mo_response=repaired,
            effective_mo_payload=repair_payload,
            repair=_repair_projection(
                attempted=True,
                trigger_error_code=exc.error_code,
                original_hash=str(original_payload["provider_prompt_package_hash"]),
                effective_hash=str(repair_payload["provider_prompt_package_hash"]),
            ),
        )
    prompt_hash = _sha256(original_payload.get("provider_prompt_package_hash"))
    return CitationRepairResult(
        mo_response=normalized,
        effective_mo_payload=original_payload,
        repair=_repair_projection(
            attempted=False,
            trigger_error_code=None,
            original_hash=prompt_hash,
            effective_hash=prompt_hash,
        ),
    )


def build_citation_repair_payload(
    mo_payload: Mapping[str, Any],
    *,
    retrieval_package: Mapping[str, Any] | None,
    selected_evidence_ids: Sequence[str] | None,
    trigger_error_code: str,
) -> dict[str, Any]:
    if trigger_error_code not in _REPAIRABLE_ERROR_CODES:
        raise _invalid("Citation repair trigger is not repairable.")
    if not isinstance(retrieval_package, Mapping):
        raise _invalid("Citation repair requires the admitted retrieval package.")
    payload = deepcopy(dict(mo_payload))
    metadata = payload.get("metadata")
    messages = payload.get("messages")
    if not isinstance(metadata, Mapping) or not isinstance(messages, list) or not messages:
        raise _invalid("Citation repair requires the original grounded prompt package.")
    try:
        evidence_binding = build_grounded_evidence_binding(
            retrieval_package=retrieval_package,
            selected_evidence_ids=selected_evidence_ids,
        )
    except GroundedPromptPackageError as exc:
        raise _invalid("Citation repair evidence binding is invalid.") from exc
    package_id = evidence_binding["retrieval_package_id"]
    package_hash = evidence_binding["retrieval_package_hash"]
    evidence_binding_hash = evidence_binding["evidence_binding_hash"]
    if metadata.get("retrieval_package_id") != package_id or (
        metadata.get("retrieval_package_hash") != package_hash
    ):
        raise _invalid("Citation repair retrieval package identity changed.")
    if _sha256(metadata.get("evidence_binding_hash")) != evidence_binding_hash:
        raise _invalid("Citation repair evidence binding changed.")
    if metadata.get("selected_evidence_count") != len(
        evidence_binding["selected_evidence_ids"]
    ):
        raise _invalid("Citation repair selected evidence count changed.")
    original_hash = _sha256(payload.get("provider_prompt_package_hash"))
    labels = [item["citation_label"] for item in evidence_binding["evidence_binding"]]
    repair_instruction = (
        "Regenerate the answer using the same supplied evidence. The previous "
        "attempt failed citation validation. Cite factual claims using only "
        f"these admitted labels: {', '.join(labels)}. Do not mention this repair."
    )
    repaired_messages = [*deepcopy(messages), {"role": "user", "content": repair_instruction}]
    repair_hash = _sha256_json(
        {
            "schema_version": CX_CITATION_REPAIR_SCHEMA_VERSION,
            "attempt": MAX_CITATION_REPAIR_ATTEMPTS,
            "trigger_error_code": trigger_error_code,
            "original_provider_prompt_package_hash": original_hash,
            "retrieval_package_id": package_id,
            "retrieval_package_hash": package_hash,
            "evidence_binding_hash": evidence_binding_hash,
            "messages": repaired_messages,
        }
    )
    repaired_metadata = {
        **deepcopy(dict(metadata)),
        "generation_request_hash": repair_hash,
        "citation_repair_attempt_count": MAX_CITATION_REPAIR_ATTEMPTS,
        "citation_repair_trigger_error_code": trigger_error_code,
        "citation_repair_original_prompt_package_hash": original_hash,
    }
    return {
        **payload,
        "client_request_id": (
            f"{_required_text(payload.get('client_request_id'), 'client_request_id')}"
            ":citation-repair-1"
        ),
        "provider_prompt_package_hash": repair_hash,
        "messages": repaired_messages,
        "prompt": None,
        "temperature": 0.0,
        "metadata": repaired_metadata,
    }


def _normalize(
    response: object,
    *,
    grounding_required: bool,
    retrieval_package: Mapping[str, Any] | None,
    selected_evidence_ids: Sequence[str] | None,
) -> dict[str, Any]:
    return normalize_generation_provider_response(
        response,
        grounding_required=grounding_required,
        retrieval_package=retrieval_package,
        selected_evidence_ids=selected_evidence_ids,
    )


def _repair_projection(
    *,
    attempted: bool,
    trigger_error_code: str | None,
    original_hash: str,
    effective_hash: str,
) -> dict[str, Any]:
    return validate_citation_repair_projection({
        "repair_schema_version": CX_CITATION_REPAIR_SCHEMA_VERSION,
        "attempted": attempted,
        "attempt_count": 1 if attempted else 0,
        "max_attempts": MAX_CITATION_REPAIR_ATTEMPTS,
        "trigger_error_code": trigger_error_code,
        "same_retrieval_package": True,
        "original_provider_prompt_package_hash": original_hash,
        "effective_provider_prompt_package_hash": effective_hash,
        "invalid_output_included": False,
    })


def validate_citation_repair_projection(value: object) -> dict[str, Any]:
    fields = {
        "repair_schema_version",
        "attempted",
        "attempt_count",
        "max_attempts",
        "trigger_error_code",
        "same_retrieval_package",
        "original_provider_prompt_package_hash",
        "effective_provider_prompt_package_hash",
        "invalid_output_included",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Citation repair projection has an invalid shape.")
    projection = deepcopy(dict(value))
    if projection["repair_schema_version"] != CX_CITATION_REPAIR_SCHEMA_VERSION:
        raise _invalid("Citation repair projection schema version is invalid.")
    attempted = projection["attempted"]
    attempt_count = projection["attempt_count"]
    if not isinstance(attempted, bool) or (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count != (1 if attempted else 0)
    ):
        raise _invalid("Citation repair attempt metadata is inconsistent.")
    if projection["max_attempts"] != MAX_CITATION_REPAIR_ATTEMPTS:
        raise _invalid("Citation repair maximum attempts is invalid.")
    trigger = projection["trigger_error_code"]
    if (attempted and trigger not in _REPAIRABLE_ERROR_CODES) or (
        not attempted and trigger is not None
    ):
        raise _invalid("Citation repair trigger metadata is inconsistent.")
    original_hash = _sha256(projection["original_provider_prompt_package_hash"])
    effective_hash = _sha256(projection["effective_provider_prompt_package_hash"])
    if not attempted and original_hash != effective_hash:
        raise _invalid("Unattempted citation repair changed the prompt hash.")
    if projection["same_retrieval_package"] is not True:
        raise _invalid("Citation repair must reuse the retrieval package.")
    if projection["invalid_output_included"] is not False:
        raise _invalid("Citation repair metadata must exclude invalid output.")
    projection["original_provider_prompt_package_hash"] = original_hash
    projection["effective_provider_prompt_package_hash"] = effective_hash
    return projection


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"Citation repair {field} is invalid.")
    return value.strip()


def _sha256(value: object) -> str:
    normalized = _required_text(value, "SHA-256").lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise _invalid("Citation repair SHA-256 is invalid.")
    return normalized


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _invalid(detail: str) -> CitationRepairError:
    return CitationRepairError(
        error_code="cx.citation_repair.invalid",
        detail=detail,
    )
