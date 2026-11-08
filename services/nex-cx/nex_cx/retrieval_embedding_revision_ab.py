from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.model_artifact_revision import (
    admit_model_artifact_revision_evidence,
    model_artifact_revision_evidence_digest,
    normalize_immutable_model_revision,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

EMBEDDING_REVISION_PROFILE_SCHEMA_VERSION = "cx_embedding_revision_profile.v1"
EMBEDDING_REVISION_AB_SCHEMA_VERSION = "cx_embedding_revision_ab.v1"
PROFILE_SLOTS = frozenset({"A", "B"})
COMPLETE_CALIBRATION_STATUSES = frozenset({"FROZEN", "NO_ACCEPTABLE_POLICY"})


class EmbeddingRevisionABError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def build_embedding_revision_profile(
    source: Mapping[str, Any],
    *,
    artifact_evidence: Mapping[str, Any],
    provider_binding: Mapping[str, Any],
    slot: str,
    source_evidence_sha256: str,
    artifact_evidence_sha256: str,
) -> dict[str, Any]:
    admitted_slot = _slot(slot)
    if source.get("status") != "PASS" or not _all_true(source.get("checks")):
        raise EmbeddingRevisionABError("S20QK_SOURCE_EVIDENCE_NOT_ADMITTED")

    calibration = _mapping(source.get("candidate_relevance_calibration"))
    calibration_status = calibration.get("status")
    if calibration_status not in COMPLETE_CALIBRATION_STATUSES:
        raise EmbeddingRevisionABError("S20QK_CALIBRATION_INCOMPLETE")
    if (
        calibration.get("runtime_activation_permitted") is not False
        or calibration.get("holdout_access_permitted") is not False
        or _mapping(calibration.get("holdout")).get("status")
        != "SEALED_NOT_OPENED"
    ):
        raise EmbeddingRevisionABError("S20QK_CALIBRATION_BOUNDARY_INVALID")

    try:
        artifact_revision = admit_model_artifact_revision_evidence(artifact_evidence)
        artifact_digest = model_artifact_revision_evidence_digest(artifact_evidence)
    except ValueError as exc:
        raise EmbeddingRevisionABError("S20QK_ARTIFACT_EVIDENCE_INVALID") from exc
    source_binding = _mapping(source.get("binding"))
    if (
        source_binding.get("embedding_model_revision") != artifact_revision
        or provider_binding.get("model_revision") != artifact_revision
        or provider_binding.get("response_model_revision") != artifact_revision
        or provider_binding.get("deployment_id")
        != provider_binding.get("response_deployment_id")
        or provider_binding.get("request_shape") != "openai_embeddings"
        or provider_binding.get("item_count") != 2
        or provider_binding.get("indices") != [0, 1]
        or provider_binding.get("finite_vectors") is not True
        or provider_binding.get("consistent_dimension") is not True
    ):
        raise EmbeddingRevisionABError("S20QK_EMBEDDING_PROVENANCE_MISMATCH")

    dataset = _mapping(source.get("dataset"))
    signal_contract = _mapping(source.get("signal_contract"))
    repeatability = _mapping(source.get("pipeline_repeatability"))
    stages = _mapping(repeatability.get("stages"))
    if (
        dataset.get("partition") != "CALIBRATION"
        or dataset.get("holdout_status") != "SEALED_NOT_COLLECTED"
        or repeatability.get("status") != "STABLE"
        or signal_contract.get("truth_or_permission_signal_included") is not False
    ):
        raise EmbeddingRevisionABError("S20QK_EXPERIMENT_BOUNDARY_INVALID")

    selected = _mapping(calibration.get("selected"))
    best_effort = _mapping(calibration.get("best_effort"))
    metrics_source = selected if calibration_status == "FROZEN" else best_effort
    metrics = _decision_metrics(metrics_source)
    invariant_binding = {
        key: _required_string(source_binding.get(key), key)
        for key in (
            "reranker_model_revision",
            "ranking_policy_id",
            "tokenizer_policy_id",
            "chunk_policy_id",
        )
    }
    calibration_contract = {
        "policy_id": _required_string(calibration.get("policy_id"), "policy_id"),
        "signal_fields": list(
            _mapping(calibration.get("search")).get("signal_fields") or []
        ),
        "cross_validation": _mapping(calibration.get("cross_validation")),
        "signal_contract_hash": _required_hash(
            signal_contract.get("contract_hash"), "signal_contract_hash"
        ),
        "pipeline_repeatability_policy_id": _required_string(
            repeatability.get("policy_id"),
            "pipeline_repeatability_policy_id",
        ),
        "repeat_count": _positive_int(
            _mapping(repeatability.get("measurement")).get("repeat_count"),
            "repeat_count",
        ),
    }
    experiment_binding = {
        "dataset_id": _required_string(dataset.get("dataset_id"), "dataset_id"),
        "dataset_sha256": _required_string(
            dataset.get("dataset_sha256"), "dataset_sha256"
        ),
        "scenario_count": dataset.get("scenario_count"),
        "package_count": dataset.get("package_count"),
        "candidate_count": dataset.get("candidate_count"),
        "invariant_binding": invariant_binding,
        "calibration_contract_hash": semantic_sha256_hash_ref(calibration_contract),
    }
    profile = {
        "profile_schema_version": EMBEDDING_REVISION_PROFILE_SCHEMA_VERSION,
        "slot": admitted_slot,
        "status": "ADMITTED",
        "experiment_binding": experiment_binding,
        "experiment_binding_hash": semantic_sha256_hash_ref(experiment_binding),
        "embedding_binding": {
            "served_model_name": _required_string(
                provider_binding.get("served_model_name"), "served_model_name"
            ),
            "artifact_revision": artifact_revision,
            "deployment_id": _required_string(
                provider_binding.get("deployment_id"), "deployment_id"
            ),
            "request_shape": "openai_embeddings",
            "vector_dimension": _positive_int(
                provider_binding.get("vector_dimension"), "vector_dimension"
            ),
            "artifact_evidence_digest": artifact_digest,
        },
        "calibration": {
            "status": calibration_status,
            "admissible_profile_count": _nonnegative_int(
                _mapping(calibration.get("search")).get("admissible_profile_count"),
                "admissible_profile_count",
            ),
            "metrics": metrics,
            "signal_diagnostics": _mapping(
                _mapping(calibration.get("search")).get("signal_diagnostics")
            ),
        },
        "repeatability": {
            "status": "STABLE",
            "pipeline_repeatability_hash": _required_hash(
                repeatability.get("repeatability_hash"),
                "pipeline_repeatability_hash",
            ),
            "repeat_count": calibration_contract["repeat_count"],
            "max_vector_similarity_quality_delta": _bounded_float(
                stages.get("max_vector_similarity_quality_delta"),
                "max_vector_similarity_quality_delta",
                maximum=0.005,
            ),
            "vector_rank_change_count": _nonnegative_int(
                stages.get("vector_rank_change_count"),
                "vector_rank_change_count",
            ),
        },
        "evidence": {
            "source_evidence_sha256": _required_hash(
                source_evidence_sha256, "source_evidence_sha256"
            ),
            "artifact_evidence_sha256": _required_hash(
                artifact_evidence_sha256, "artifact_evidence_sha256"
            ),
            "raw_text_persisted": False,
            "embedding_vector_persisted": False,
            "provider_endpoint_persisted": False,
            "provider_credential_persisted": False,
        },
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    profile["profile_hash"] = semantic_sha256_hash_ref(profile)
    return profile


def compare_embedding_revision_profiles(
    profile_a: Mapping[str, Any],
    profile_b: Mapping[str, Any],
) -> dict[str, Any]:
    admitted_a = _admit_profile(profile_a, expected_slot="A")
    admitted_b = _admit_profile(profile_b, expected_slot="B")
    if admitted_a["experiment_binding_hash"] != admitted_b["experiment_binding_hash"]:
        raise EmbeddingRevisionABError("S20QK_EXPERIMENT_BINDING_DRIFT")

    embedding_a = _mapping(admitted_a.get("embedding_binding"))
    embedding_b = _mapping(admitted_b.get("embedding_binding"))
    if embedding_a.get("artifact_revision") == embedding_b.get("artifact_revision"):
        raise EmbeddingRevisionABError("S20QK_REVISIONS_MUST_DIFFER")
    if embedding_a.get("request_shape") != embedding_b.get("request_shape"):
        raise EmbeddingRevisionABError("S20QK_EMBEDDING_SEMANTICS_DRIFT")

    calibration_a = _mapping(admitted_a.get("calibration"))
    calibration_b = _mapping(admitted_b.get("calibration"))
    admissible_slots = [
        slot
        for slot, status in (
            ("A", calibration_a.get("status")),
            ("B", calibration_b.get("status")),
        )
        if status == "FROZEN"
    ]
    if not admissible_slots:
        decision_status = "NO_ADMISSIBLE_REVISION"
        selected_slot = None
        reason_code = "CALIBRATION_CONSTRAINTS_NOT_SATISFIED"
        next_action = "CALIBRATION_DATASET_AND_RELEVANCE_POLICY_REVIEW"
    elif len(admissible_slots) == 1:
        selected_slot = admissible_slots[0]
        decision_status = f"REVISION_{selected_slot}_SELECTED"
        reason_code = "ONLY_ADMISSIBLE_REVISION_SELECTED"
        next_action = "ORIGINAL_S20Q_HOLDOUT_ACCEPTANCE"
    else:
        key_a = _selection_key(_mapping(calibration_a.get("metrics")))
        key_b = _selection_key(_mapping(calibration_b.get("metrics")))
        selected_slot = "B" if key_b > key_a else "A"
        decision_status = f"REVISION_{selected_slot}_SELECTED"
        reason_code = (
            "ADMISSIBLE_REVISION_QUALITY_SELECTED"
            if key_a != key_b
            else "EQUIVALENT_REVISIONS_KEEP_INCUMBENT"
        )
        next_action = "ORIGINAL_S20Q_HOLDOUT_ACCEPTANCE"

    comparison = {
        "comparison_schema_version": EMBEDDING_REVISION_AB_SCHEMA_VERSION,
        "status": "DECIDED",
        "experiment_binding": admitted_a["experiment_binding"],
        "experiment_binding_hash": admitted_a["experiment_binding_hash"],
        "profiles": {
            "A": _comparison_projection(admitted_a),
            "B": _comparison_projection(admitted_b),
        },
        "decision": {
            "status": decision_status,
            "selected_slot": selected_slot,
            "reason_code": reason_code,
            "next_action": next_action,
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
        },
    }
    comparison["comparison_hash"] = semantic_sha256_hash_ref(comparison)
    return comparison


def _admit_profile(
    profile: Mapping[str, Any], *, expected_slot: str
) -> Mapping[str, Any]:
    if (
        profile.get("profile_schema_version")
        != EMBEDDING_REVISION_PROFILE_SCHEMA_VERSION
        or profile.get("slot") != expected_slot
        or profile.get("status") != "ADMITTED"
        or profile.get("holdout_access_permitted") is not False
        or profile.get("runtime_activation_permitted") is not False
    ):
        raise EmbeddingRevisionABError("S20QK_PROFILE_NOT_ADMITTED")
    unsigned = dict(profile)
    profile_hash = unsigned.pop("profile_hash", None)
    if profile_hash != semantic_sha256_hash_ref(unsigned):
        raise EmbeddingRevisionABError("S20QK_PROFILE_INTEGRITY_INVALID")
    experiment_binding = _mapping(profile.get("experiment_binding"))
    if profile.get("experiment_binding_hash") != semantic_sha256_hash_ref(
        experiment_binding
    ):
        raise EmbeddingRevisionABError("S20QK_EXPERIMENT_BINDING_INTEGRITY_INVALID")
    normalize_immutable_model_revision(
        _mapping(profile.get("embedding_binding")).get("artifact_revision")
    )
    calibration_status = _mapping(profile.get("calibration")).get("status")
    if calibration_status not in COMPLETE_CALIBRATION_STATUSES:
        raise EmbeddingRevisionABError("S20QK_CALIBRATION_INCOMPLETE")
    return profile


def _decision_metrics(source: Mapping[str, Any]) -> dict[str, Any]:
    oof = _mapping(source.get("oof_metrics"))
    return {
        "feature_fields": list(source.get("feature_fields") or []),
        "weights": dict(_mapping(source.get("weights"))),
        "candidate_auc": _unit_float(source.get("candidate_auc"), "candidate_auc"),
        "false_ready_rate": _unit_float(
            oof.get("false_ready_rate"), "false_ready_rate"
        ),
        "ready_recall": _unit_float(oof.get("ready_recall"), "ready_recall"),
        "balanced_accuracy": _unit_float(
            oof.get("balanced_accuracy"), "balanced_accuracy"
        ),
        "minimum_fold_balanced_accuracy": _unit_float(
            source.get("minimum_fold_balanced_accuracy"),
            "minimum_fold_balanced_accuracy",
        ),
        "threshold_spread": _unit_float(
            source.get("threshold_spread"), "threshold_spread"
        ),
    }


def _selection_key(metrics: Mapping[str, Any]) -> tuple[float, ...]:
    return (
        -float(metrics["false_ready_rate"]),
        float(metrics["ready_recall"]),
        float(metrics["minimum_fold_balanced_accuracy"]),
        float(metrics["balanced_accuracy"]),
        float(metrics["candidate_auc"]),
        -float(metrics["threshold_spread"]),
    )


def _comparison_projection(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "profile_hash": profile["profile_hash"],
        "embedding_binding": profile["embedding_binding"],
        "calibration": profile["calibration"],
        "repeatability": profile["repeatability"],
    }


def _slot(value: object) -> str:
    if value not in PROFILE_SLOTS:
        raise EmbeddingRevisionABError("S20QK_PROFILE_SLOT_INVALID")
    return str(value)


def _all_true(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and bool(value)
        and all(item is True for item in value.values())
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingRevisionABError(f"S20QK_{field_name.upper()}_INVALID")
    return value.strip()


def _required_hash(value: object, field_name: str) -> str:
    normalized = _required_string(value, field_name)
    try:
        return normalize_immutable_model_revision(normalized)
    except ValueError as exc:
        raise EmbeddingRevisionABError(f"S20QK_{field_name.upper()}_INVALID") from exc


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EmbeddingRevisionABError(f"S20QK_{field_name.upper()}_INVALID")
    return value


def _nonnegative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EmbeddingRevisionABError(f"S20QK_{field_name.upper()}_INVALID")
    return value


def _unit_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EmbeddingRevisionABError(f"S20QK_{field_name.upper()}_INVALID")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise EmbeddingRevisionABError(f"S20QK_{field_name.upper()}_INVALID")
    return normalized


def _bounded_float(value: object, field_name: str, *, maximum: float) -> float:
    normalized = _unit_float(value, field_name)
    if normalized > maximum:
        raise EmbeddingRevisionABError(f"S20QK_{field_name.upper()}_INVALID")
    return normalized
