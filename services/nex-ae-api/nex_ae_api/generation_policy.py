from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from nex_ae_api.cx_owner_context import cx_owner_scope_from_payload
from nex_ae_api.runtime_policy import (
    FORBIDDEN_PROVIDER_FIELDS,
    RUNTIME_POLICY_SCHEMA_VERSION,
)


GENERATION_POLICY_PACKAGE_SCHEMA_VERSION = "ae_generation_policy_package.v1"
ALLOWED_RETRIEVAL_STATUSES = frozenset({"READY", "LOW_CONFIDENCE", "PARTIAL"})


@dataclass(frozen=True)
class GenerationPolicyPackageError(Exception):
    status_code: int
    error_code: str
    detail: str


def build_generation_policy_package(
    source_payload: Mapping[str, Any],
    *,
    runtime_policy: Mapping[str, Any],
    prompt_binding: Mapping[str, Any],
    retrieval_package: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    user_message = _required_text(source_payload.get("user_message"), "user_message")
    _reject_provider_runtime(source_payload.get("generation"))
    _validate_runtime_policy(runtime_policy)
    prompt_ref = _validate_prompt_binding(runtime_policy, prompt_binding)
    retrieval_ref, selected_ids = _retrieval_policy(
        source_payload,
        runtime_policy=runtime_policy,
        retrieval_package=retrieval_package,
    )
    tenant_id, subject_id = cx_owner_scope_from_payload(source_payload)
    intent = _mapping(runtime_policy.get("intent_decision"), "intent_decision")

    package = {
        "generation_policy_package_schema_version": (
            GENERATION_POLICY_PACKAGE_SCHEMA_VERSION
        ),
        "execution_mode": intent["execution_mode"],
        "intent_decision_ref": {
            "decision_hash": intent["decision_hash"],
            "intent_label": intent["intent_label"],
            "task_category": intent["task_category"],
            "decision_source": intent["decision_source"],
        },
        "ownership_ref": {
            "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
            "owner_subject_ref": {"type": "oa.user", "id": subject_id},
        },
        "template_ref": dict(runtime_policy["template_ref"]),
        "prompt_contract_ref": prompt_ref,
        "output_contract": dict(runtime_policy["output_contract"]),
        "generation_profile": runtime_policy["generation_profile"],
        "provider_capability": runtime_policy["provider_capability"],
        "generation_parameters": dict(runtime_policy["generation_parameters"]),
        "quality_policy": dict(runtime_policy["quality_policy"]),
        "retrieval_package_ref": retrieval_ref,
        "selected_evidence_ids": selected_ids,
        "user_message_hash": _sha256_text(user_message),
        "policy_snapshot_hash": runtime_policy["policy_snapshot_hash"],
        "privacy": {
            "raw_user_prompt_included": False,
            "raw_evidence_included": False,
            "provider_runtime_included": False,
            "raw_token_included": False,
        },
    }
    package["client_package_hash"] = _stable_hash(package)
    return package


def _validate_runtime_policy(runtime_policy: Mapping[str, Any]) -> None:
    if runtime_policy.get("runtime_policy_schema_version") != RUNTIME_POLICY_SCHEMA_VERSION:
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_runtime_invalid",
            "A canonical resolved AE runtime policy is required.",
        )
    if runtime_policy.get("raw_prompt_included") is not False:
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_raw_prompt_forbidden",
            "Runtime policy must exclude raw prompt content.",
        )
    if runtime_policy.get("provider_runtime_included") is not False:
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_provider_runtime_forbidden",
            "Runtime policy must exclude provider runtime configuration.",
        )
    for field in (
        "template_ref",
        "prompt_contract_ref",
        "output_contract",
        "generation_parameters",
        "quality_policy",
    ):
        _mapping(runtime_policy.get(field), field)
    for field in (
        "generation_profile",
        "provider_capability",
        "policy_snapshot_hash",
    ):
        _required_text(runtime_policy.get(field), field)


def _validate_prompt_binding(
    runtime_policy: Mapping[str, Any],
    prompt_binding: Mapping[str, Any],
) -> dict[str, Any]:
    if prompt_binding.get("content_included") is not False or "content" in prompt_binding:
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_prompt_content_forbidden",
            "Prompt binding projection must exclude prompt content.",
        )
    policy_ref = _mapping(runtime_policy.get("prompt_contract_ref"), "prompt_contract_ref")
    if (
        prompt_binding.get("binding_key") != policy_ref.get("prompt_binding_key")
        or prompt_binding.get("prompt_version") != policy_ref.get("prompt_version")
    ):
        raise GenerationPolicyPackageError(
            409,
            "ae.generation_policy_prompt_mismatch",
            "Prompt binding does not match the resolved runtime policy.",
        )
    return {
        "prompt_binding_key": _required_text(
            prompt_binding.get("binding_key"), "binding_key"
        ),
        "prompt_binding_id": _required_text(
            prompt_binding.get("prompt_binding_id"), "prompt_binding_id"
        ),
        "prompt_template_version_id": _required_text(
            prompt_binding.get("prompt_template_version_id"),
            "prompt_template_version_id",
        ),
        "prompt_version": _required_text(
            prompt_binding.get("prompt_version"), "prompt_version"
        ),
        "content_sha256": _sha256_value(
            prompt_binding.get("content_sha256"), "content_sha256"
        ),
    }


def _retrieval_policy(
    source_payload: Mapping[str, Any],
    *,
    runtime_policy: Mapping[str, Any],
    retrieval_package: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    quality = _mapping(runtime_policy.get("quality_policy"), "quality_policy")
    grounding_required = quality.get("grounding_required") is True
    if retrieval_package is None:
        if grounding_required:
            raise GenerationPolicyPackageError(
                409,
                "ae.generation_policy_retrieval_required",
                "Grounded generation requires an admitted retrieval package.",
            )
        return None, []
    if not isinstance(retrieval_package, Mapping):
        raise GenerationPolicyPackageError(
            400,
            "ae.generation_policy_retrieval_invalid",
            "retrieval_package must be an object.",
        )
    if not grounding_required:
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_retrieval_not_allowed",
            "General answer policy must not carry a retrieval package.",
        )

    status = _required_text(retrieval_package.get("status"), "retrieval status")
    if status not in ALLOWED_RETRIEVAL_STATUSES:
        raise GenerationPolicyPackageError(
            409,
            "ae.generation_policy_retrieval_not_admitted",
            f"Retrieval package is not admitted for generation: {status}",
        )
    evidence_ids = _evidence_ids(retrieval_package.get("evidence_items"))
    selected_ids = _selected_evidence_ids(source_payload, evidence_ids)
    return (
        {
            "retrieval_package_id": _required_text(
                retrieval_package.get("retrieval_package_id"),
                "retrieval_package_id",
            ),
            "package_hash": _sha256_value(
                retrieval_package.get("package_hash"), "package_hash"
            ),
            "status": status,
        },
        selected_ids,
    )


def _evidence_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise GenerationPolicyPackageError(
            400,
            "ae.generation_policy_evidence_invalid",
            "retrieval evidence_items must be a list.",
        )
    ids = [
        _required_text(item.get("evidence_id"), "evidence_id")
        for item in value
        if isinstance(item, Mapping)
    ]
    if len(ids) != len(value) or len(set(ids)) != len(ids):
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_evidence_invalid",
            "Retrieval evidence IDs must be unique non-empty strings.",
        )
    return ids


def _selected_evidence_ids(
    source_payload: Mapping[str, Any],
    evidence_ids: list[str],
) -> list[str]:
    selected = source_payload.get("selected_evidence_ids")
    if selected is None:
        return evidence_ids
    if not isinstance(selected, list):
        raise GenerationPolicyPackageError(
            400,
            "ae.generation_policy_evidence_selection_invalid",
            "selected_evidence_ids must be a list.",
        )
    normalized = [_required_text(item, "selected_evidence_id") for item in selected]
    if len(set(normalized)) != len(normalized) or not set(normalized).issubset(
        evidence_ids
    ):
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_evidence_selection_invalid",
            "Selected evidence IDs must be unique members of the retrieval package.",
        )
    return normalized


def _reject_provider_runtime(generation: Any) -> None:
    if generation is None:
        return
    if not isinstance(generation, Mapping):
        raise GenerationPolicyPackageError(
            400,
            "ae.generation_policy_generation_invalid",
            "generation must be an object when supplied.",
        )
    forbidden = sorted(FORBIDDEN_PROVIDER_FIELDS.intersection(generation))
    if forbidden:
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_provider_runtime_forbidden",
            f"Provider runtime field is forbidden: {forbidden[0]}",
        )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_runtime_invalid",
            f"Resolved runtime policy field must be an object: {field_name}",
        )
    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_value_invalid",
            f"Generation policy field must be a non-empty string: {field_name}",
        )
    return value.strip()


def _sha256_value(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise GenerationPolicyPackageError(
            422,
            "ae.generation_policy_hash_invalid",
            f"Generation policy field must be a lowercase SHA-256 value: {field_name}",
        )
    return normalized


def _stable_hash(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(canonical)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
