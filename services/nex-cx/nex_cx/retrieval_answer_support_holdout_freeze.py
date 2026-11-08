from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.retrieval_answer_support_canonical_profile import CANONICAL_PROFILE_ID

HOLDOUT_EXECUTION_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_holdout_execution_design.v1"
)
HOLDOUT_EXECUTION_FREEZE_SCHEMA_VERSION = (
    "cx_answer_support_holdout_execution_freeze.v1"
)
HOLDOUT_RECEIPT_PATH = (
    "reports/live/gb2_ca00_s20qpq_holdout_one_shot_receipt.json"
)

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "holdout_manifest",
    "protocol",
    "admission",
    "safety",
}
_SOURCE_FIELDS = {
    "artifact_evidence_hash",
    "artifact_revision",
    "canonical_profile_hash",
    "dataset_file_sha256",
    "dataset_semantic_sha256",
    "p_n_collection_hash",
    "p_o_calibration_design_hash",
    "p_o_calibration_hash",
    "p_o_threshold",
}
_EXPECTED_HOLDOUT_MANIFEST = {
    "candidate_count": 160,
    "dataset_id": "s136-retrieval-package-confidence-public-v4",
    "domain_scenario_counts": {
        "AI_RUNTIME": 5,
        "FINANCE": 5,
        "GOVERNANCE_OPERATIONS": 3,
        "IDENTITY_AUTHORIZATION": 3,
        "PROJECT": 4,
    },
    "language_scenario_counts": {
        "ENGLISH": 4,
        "KOREAN": 12,
        "KOREAN_ENGLISH_MIXED": 4,
    },
    "package_count": 40,
    "partition": "HOLDOUT",
    "scenario_count": 20,
}
_EXPECTED_PROTOCOL = {
    "execution_mode": "ONE_SHOT_BLIND_HOLDOUT",
    "expected_provider_evaluations": 40,
    "maximum_concurrency": 4,
    "maximum_execution_attempts": 1,
    "maximum_provider_http_requests": 40,
    "partial_failure_disposition": "TERMINAL_INCONCLUSIVE_CONSUMED",
    "profile_change_permitted": False,
    "provider_request_retry_permitted": False,
    "receipt_creation_mode": "ATOMIC_CREATE_EXCLUSIVE",
    "receipt_path": HOLDOUT_RECEIPT_PATH,
    "receipt_reservation_required_before_provider_call": True,
    "threshold_reselection_permitted": False,
}
_EXPECTED_ADMISSION = {
    "calibration_candidate_required": True,
    "holdout_pass_required_for_activation": True,
    "maximum_false_ready_rate": 0.1,
    "minimum_package_auc": 0.8,
    "minimum_ready_recall": 0.8,
    "point_constraints_remain_authoritative": True,
    "runtime_activation_requires_separate_approval": True,
}
_EXPECTED_SAFETY = {
    "calibration_reentry_permitted": False,
    "candidate_truth_provider_input_permitted": False,
    "holdout_access_in_this_slice_permitted": False,
    "holdout_source_text_in_freeze_permitted": False,
    "runtime_activation_permitted": False,
    "second_execution_permitted": False,
}


def validate_holdout_execution_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the immutable pre-HOLDOUT authorization contract."""
    _exact_mapping(design, _DESIGN_FIELDS, "holdout execution design")
    if (
        design.get("design_schema_version")
        != HOLDOUT_EXECUTION_DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_PRE_HOLDOUT_ONLY"
    ):
        raise ValueError("holdout execution design identity is invalid")
    _required_text(design.get("design_id"), "design_id")
    source = _exact_mapping(
        design.get("source_binding"), _SOURCE_FIELDS, "holdout source binding"
    )
    normalized_source = {
        field: (
            _required_text(source.get(field), field)
            if field == "artifact_revision"
            else _bounded(source.get(field), field)
            if field == "p_o_threshold"
            else validate_hash_ref(source.get(field))
        )
        for field in sorted(_SOURCE_FIELDS)
    }
    if dict(_mapping(design.get("holdout_manifest"), "holdout manifest")) != (
        _EXPECTED_HOLDOUT_MANIFEST
    ):
        raise ValueError("holdout manifest is invalid")
    if dict(_mapping(design.get("protocol"), "holdout protocol")) != (
        _EXPECTED_PROTOCOL
    ):
        raise ValueError("holdout execution protocol is invalid")
    if dict(_mapping(design.get("admission"), "holdout admission")) != (
        _EXPECTED_ADMISSION
    ):
        raise ValueError("holdout admission is invalid")
    if dict(_mapping(design.get("safety"), "holdout safety")) != _EXPECTED_SAFETY:
        raise ValueError("holdout safety is invalid")
    normalized = dict(design)
    normalized["source_binding"] = normalized_source
    normalized["design_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def freeze_holdout_one_shot_execution(
    *,
    p_o_calibration: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    design: Mapping[str, Any],
    existing_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Arm exactly one future blind HOLDOUT execution without consuming it."""
    normalized_design = validate_holdout_execution_design(design)
    source = normalized_design["source_binding"]
    calibration = _validated_calibration(p_o_calibration, source=source)
    dataset = _validated_dataset_manifest(dataset_manifest, source=source)
    if existing_receipt is not None:
        _mapping(existing_receipt, "existing holdout receipt")
        raise ValueError("holdout one-shot execution is already consumed")

    candidate = _mapping(calibration.get("candidate"), "P-O candidate")
    binding = _mapping(calibration.get("binding"), "P-O binding")
    provider = _mapping(binding.get("provider_binding"), "P-O provider binding")
    authorization = {
        "design_hash": normalized_design["design_hash"],
        "source_calibration_hash": source["p_o_calibration_hash"],
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "dataset_file_sha256": source["dataset_file_sha256"],
            "dataset_semantic_sha256": source["dataset_semantic_sha256"],
            **normalized_design["holdout_manifest"],
        },
        "candidate": {
            "profile_id": candidate["profile_id"],
            "profile_hash": candidate["profile_hash"],
            "threshold": candidate["threshold"],
            "score_semantics": "WEIGHTED_BOUNDED_ORDINAL_NOT_PROBABILITY",
        },
        "provider_binding": dict(provider),
        "protocol": dict(normalized_design["protocol"]),
    }
    authorization_hash = semantic_sha256_hash_ref(authorization)
    execution_id = f"s20qpq-{authorization_hash.removeprefix('sha256:')[:24]}"
    result: dict[str, Any] = {
        "freeze_schema_version": HOLDOUT_EXECUTION_FREEZE_SCHEMA_VERSION,
        "status": "HOLDOUT_ONE_SHOT_EXECUTION_ARMED",
        "execution_id": execution_id,
        "authorization_hash": authorization_hash,
        "authorization": authorization,
        "admission": dict(normalized_design["admission"]),
        "receipt_contract": {
            "receipt_path": normalized_design["protocol"]["receipt_path"],
            "required_execution_id": execution_id,
            "reservation_status": "STARTED",
            "reservation_write_mode": "ATOMIC_CREATE_EXCLUSIVE",
            "reservation_required_before_provider_call": True,
            "terminal_statuses": ["PASS", "FAIL", "INCONCLUSIVE"],
            "terminal_receipt_consumes_authorization": True,
            "reexecution_permitted": False,
        },
        "safety": {
            **normalized_design["safety"],
            "holdout_execution_authorized_for_next_slice": True,
            "holdout_executed_in_this_slice": False,
        },
        "new_provider_calls": 0,
        "new_database_calls": 0,
        "runtime_activation_permitted": False,
    }
    result["freeze_hash"] = semantic_sha256_hash_ref(result)
    return result


def _validated_calibration(
    value: Mapping[str, Any], *, source: Mapping[str, Any]
) -> dict[str, Any]:
    calibration = dict(_mapping(value, "P-O calibration"))
    calibration_hash = validate_hash_ref(calibration.pop("calibration_hash", None))
    candidate = _mapping(calibration.get("candidate"), "P-O candidate")
    binding = _mapping(calibration.get("binding"), "P-O binding")
    provider = _mapping(binding.get("provider_binding"), "P-O provider binding")
    oof = _mapping(calibration.get("oof_evaluation"), "P-O OOF evaluation")
    metrics = _mapping(oof.get("metrics"), "P-O OOF metrics")
    checks = _mapping(calibration.get("checks"), "P-O checks")
    if (
        semantic_sha256_hash_ref(calibration) != calibration_hash
        or calibration_hash != source["p_o_calibration_hash"]
        or calibration.get("status")
        != "CALIBRATION_THRESHOLD_CANDIDATE_ADMITTED"
        or candidate.get("status") != "CANDIDATE_NOT_ACTIVE"
        or candidate.get("profile_id") != CANONICAL_PROFILE_ID
        or candidate.get("profile_hash") != source["canonical_profile_hash"]
        or not math.isclose(
            _bounded(candidate.get("threshold"), "candidate threshold"),
            source["p_o_threshold"],
            abs_tol=1e-12,
        )
        or binding.get("calibration_design_hash")
        != source["p_o_calibration_design_hash"]
        or binding.get("source_collection_hash") != source["p_n_collection_hash"]
        or binding.get("artifact_evidence_hash") != source["artifact_evidence_hash"]
        or provider.get("model_revision") != source["artifact_revision"]
        or metrics.get("false_ready_rate", 1.0) > 0.1
        or metrics.get("ready_recall", 0.0) < 0.8
        or oof.get("package_auc", 0.0) < 0.8
        or not checks
        or not all(item is True for item in checks.values())
        or calibration.get("holdout_access_permitted") is not False
        or calibration.get("runtime_activation_permitted") is not False
    ):
        raise ValueError("P-O calibration admission is invalid")
    calibration["calibration_hash"] = calibration_hash
    return calibration


def _validated_dataset_manifest(
    value: Mapping[str, Any], *, source: Mapping[str, Any]
) -> dict[str, Any]:
    manifest = dict(_mapping(value, "Dataset v4 manifest"))
    if (
        manifest.get("status") != "PASS"
        or manifest.get("dataset_id")
        != _EXPECTED_HOLDOUT_MANIFEST["dataset_id"]
        or _hash_ref(manifest.get("dataset_file_sha256"), "dataset file hash")
        != source["dataset_file_sha256"]
        or _hash_ref(manifest.get("dataset_sha256"), "dataset semantic hash")
        != source["dataset_semantic_sha256"]
        or manifest.get("scenario_count") != 100
        or manifest.get("package_count") != 200
        or manifest.get("candidate_count") != 800
        or manifest.get("holdout_scenario_count") != 20
        or manifest.get("independent_review_passed") is not True
        or manifest.get("immutable") is not True
        or manifest.get("holdout_excluded_from_folds") is not True
        or manifest.get("runtime_activation_permitted") is not False
    ):
        raise ValueError("Dataset v4 holdout admission is invalid")
    return manifest


def _hash_ref(value: object, name: str) -> str:
    text = _required_text(value, name)
    return validate_hash_ref(text if text.startswith("sha256:") else f"sha256:{text}")


def _exact_mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    item = _mapping(value, name)
    if set(item) != fields:
        raise ValueError(f"{name} fields are invalid")
    return item


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _bounded(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{name} is invalid")
    return float(value)
