from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from nex_ae_api.async_generation import ASYNCHRONOUS, AeAsyncGenerationError
from nex_ae_api.generation_progress import build_generation_recovery_plan


AE_GENERATION_RETRY_ORCHESTRATION_SCHEMA_VERSION = (
    "ae_generation_retry_orchestration.v1"
)


@dataclass(frozen=True)
class AeGenerationRecoveryError(ValueError):
    error_code: str
    detail: str
    status_code: int
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def prepare_generation_retry(
    parent: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    submitted_input_hash: str,
) -> dict[str, Any]:
    if not isinstance(parent, Mapping) or not isinstance(payload, Mapping):
        raise _invalid("Parent interaction and retry payload must be objects.")
    parent_interaction_id = _required_text(
        parent.get("interaction_id"), "parent.interaction_id"
    )
    generation = parent.get("generation")
    projection = (
        generation.get("async_generation")
        if isinstance(generation, Mapping)
        else None
    )
    try:
        recovery = build_generation_recovery_plan(projection)
    except (AeAsyncGenerationError, TypeError, ValueError) as exc:
        raise _invalid("Parent interaction has invalid generation metadata.") from exc
    if recovery["eligible"] is not True:
        raise AeGenerationRecoveryError(
            error_code="ae.async_generation.not_retryable",
            detail="Asynchronous generation is not retryable.",
            status_code=409,
        )
    retry_interaction_id = _required_text(
        payload.get("interaction_id"), "interaction_id"
    )
    if retry_interaction_id == parent_interaction_id:
        raise AeGenerationRecoveryError(
            error_code="ae.async_generation.retry_interaction_id_invalid",
            detail="Retry requires a new interaction_id.",
            status_code=400,
        )
    expected_hash = _required_text(parent.get("user_message_hash"), "user_message_hash")
    if _required_text(submitted_input_hash, "submitted_input_hash") != expected_hash:
        raise AeGenerationRecoveryError(
            error_code="ae.async_generation.retry_input_mismatch",
            detail="Retry input does not match the original interaction.",
            status_code=409,
        )
    requested_generation = payload.get("generation", {})
    if not isinstance(requested_generation, Mapping):
        raise AeGenerationRecoveryError(
            error_code="ae.async_generation.retry_request_invalid",
            detail="generation must be an object when supplied.",
            status_code=400,
        )
    retry_payload = deepcopy(dict(payload))
    retry_payload["generation"] = {
        **deepcopy(dict(requested_generation)),
        "execution_strategy": ASYNCHRONOUS,
    }
    lineage = {
        "retry_lineage_schema_version": "ae_async_generation_retry_lineage.v1",
        "parent_interaction_id": parent_interaction_id,
        "parent_job_id": projection["job_id"],
        "parent_cx_generation_id": projection["cx_generation_id"],
        "raw_input_included": False,
    }
    return {
        "retry_orchestration_schema_version": (
            AE_GENERATION_RETRY_ORCHESTRATION_SCHEMA_VERSION
        ),
        "retry_payload": retry_payload,
        "lineage": lineage,
        "recovery": recovery,
        "owner_scope_enforced": True,
        "raw_input_included": False,
    }


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _invalid(detail: str) -> AeGenerationRecoveryError:
    return AeGenerationRecoveryError(
        error_code="ae.async_generation.retry_request_invalid",
        detail=detail,
        status_code=400,
    )
