from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from nex_runtime.canonical_generation_binding import CANONICAL_GENERATION_BINDING
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref


RELOCATION_SCHEMA_VERSION = "cx_answer_support_provider_relocation.v1"
RELOCATION_PATH_ENV = "NEX_CX_ANSWER_SUPPORT_PROVIDER_RELOCATION_PATH"
_BINDING_FIELDS = {
    "deployment_id",
    "model_revision",
    "provider_alias",
    "provider_type",
    "request_profile_id",
    "score_semantics_id",
}
_RELOCATION_FIELDS = {
    "amendment_hash",
    "calibration_reuse_authorized",
    "decided_at",
    "model_artifact_changed",
    "operator_decision",
    "request_profile_changed",
    "relocation_schema_version",
    "scope",
    "source_activation_bundle_hash",
    "source_provider_binding",
    "status",
    "target_provider_binding",
}


class AnswerSupportProviderRelocationError(ValueError):
    pass


def resolve_runtime_provider_binding(
    environ: Mapping[str, str],
    *,
    activation_bundle: Mapping[str, Any],
) -> dict[str, str] | None:
    path = str(environ.get(RELOCATION_PATH_ENV, "")).strip()
    if not path:
        return None
    return load_provider_relocation(
        Path(path), activation_bundle=activation_bundle
    )["target_provider_binding"]


def load_provider_relocation(
    path: Path,
    *,
    activation_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnswerSupportProviderRelocationError(
            "The answer-support provider relocation amendment is unavailable."
        ) from exc
    return validate_provider_relocation(value, activation_bundle=activation_bundle)


def validate_provider_relocation(
    value: object,
    *,
    activation_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    amendment = _exact_mapping(value, _RELOCATION_FIELDS, "relocation amendment")
    supplied_hash = _hash_ref(amendment.pop("amendment_hash"), "amendment_hash")
    if semantic_sha256_hash_ref(amendment) != supplied_hash:
        raise AnswerSupportProviderRelocationError(
            "The answer-support provider relocation amendment hash is invalid."
        )
    if (
        amendment.get("relocation_schema_version") != RELOCATION_SCHEMA_VERSION
        or amendment.get("status") != "APPROVED"
        or amendment.get("scope") != "ENDPOINT_RELOCATION_ONLY"
        or amendment.get("operator_decision")
        != "CANONICAL_GENERATION_BINDING_PROMOTION_APPROVED"
        or amendment.get("model_artifact_changed") is not False
        or amendment.get("request_profile_changed") is not False
        or amendment.get("calibration_reuse_authorized") is not True
    ):
        raise AnswerSupportProviderRelocationError(
            "The answer-support provider relocation amendment is not approved."
        )
    source_bundle_hash = _hash_ref(
        amendment.get("source_activation_bundle_hash"),
        "source_activation_bundle_hash",
    )
    if source_bundle_hash != activation_bundle.get("bundle_hash"):
        raise AnswerSupportProviderRelocationError(
            "The relocation amendment does not bind the active calibration bundle."
        )
    source = _binding(amendment.get("source_provider_binding"), "source binding")
    target = _binding(amendment.get("target_provider_binding"), "target binding")
    calibrated = _binding(
        _mapping(activation_bundle.get("readiness_manifest"), "readiness manifest")
        .get("candidate_profile", {})
        .get("provider_binding"),
        "calibrated binding",
    )
    if source != calibrated:
        raise AnswerSupportProviderRelocationError(
            "The relocation source does not match the calibrated provider binding."
        )
    stable_fields = _BINDING_FIELDS - {"deployment_id"}
    if any(source[field] != target[field] for field in stable_fields):
        raise AnswerSupportProviderRelocationError(
            "Provider relocation changed calibrated model or request semantics."
        )
    if source["deployment_id"] == target["deployment_id"]:
        raise AnswerSupportProviderRelocationError(
            "Provider relocation must change the deployment identity."
        )
    if (
        target["model_revision"] != CANONICAL_GENERATION_BINDING.model_revision
        or target["deployment_id"] != CANONICAL_GENERATION_BINDING.deployment_id
        or target["provider_alias"] != CANONICAL_GENERATION_BINDING.alias
    ):
        raise AnswerSupportProviderRelocationError(
            "The relocation target is not the canonical generation binding."
        )
    amendment.update(
        {
            "amendment_hash": supplied_hash,
            "source_activation_bundle_hash": source_bundle_hash,
            "source_provider_binding": source,
            "target_provider_binding": target,
        }
    )
    return amendment


def _binding(value: object, label: str) -> dict[str, str]:
    binding = _exact_mapping(value, _BINDING_FIELDS, label)
    normalized: dict[str, str] = {}
    for field in sorted(_BINDING_FIELDS):
        text = str(binding.get(field, "")).strip()
        if not text:
            raise AnswerSupportProviderRelocationError(f"{label} {field} is required.")
        normalized[field] = text
    return normalized


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AnswerSupportProviderRelocationError(f"{label} must be an object.")
    return value


def _exact_mapping(value: object, fields: set[str], label: str) -> dict[str, Any]:
    normalized = dict(_mapping(value, label))
    if set(normalized) != fields:
        raise AnswerSupportProviderRelocationError(f"{label} fields are invalid.")
    return normalized


def _hash_ref(value: object, label: str) -> str:
    try:
        return validate_hash_ref(str(value))
    except (TypeError, ValueError) as exc:
        raise AnswerSupportProviderRelocationError(f"{label} is invalid.") from exc
