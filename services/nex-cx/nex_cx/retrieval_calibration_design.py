from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

RETRIEVAL_CALIBRATION_DESIGN_SCHEMA_VERSION = (
    "cx_retrieval_calibration_design.v1"
)
RETRIEVAL_CALIBRATION_DESIGN_ID = (
    "s136-retrieval-package-confidence-v4-design"
)
TARGET_DATASET_SCHEMA_VERSION = "model_calibration_dataset.v4"
TARGET_DATASET_ID = "s136-retrieval-package-confidence-public-v4"

PARTITION_SCENARIO_COUNTS = {"CALIBRATION": 80, "HOLDOUT": 20}
PARTITION_LANGUAGE_SCENARIO_COUNTS = {
    "CALIBRATION": {
        "KOREAN": 48,
        "KOREAN_ENGLISH_MIXED": 16,
        "ENGLISH": 16,
    },
    "HOLDOUT": {
        "KOREAN": 12,
        "KOREAN_ENGLISH_MIXED": 4,
        "ENGLISH": 4,
    },
}
PARTITION_DOMAIN_SCENARIO_COUNTS = {
    "CALIBRATION": {
        "PROJECT": 16,
        "FINANCE": 20,
        "IDENTITY_AUTHORIZATION": 12,
        "GOVERNANCE_OPERATIONS": 12,
        "AI_RUNTIME": 20,
    },
    "HOLDOUT": {
        "PROJECT": 4,
        "FINANCE": 5,
        "IDENTITY_AUTHORIZATION": 3,
        "GOVERNANCE_OPERATIONS": 3,
        "AI_RUNTIME": 5,
    },
}

ALLOWED_SIGNAL_FIELDS = frozenset(
    {
        "reranker_score",
        "rrf_normalized_score",
        "channel_rank_quality",
        "bm25_score_quality",
        "vector_similarity_quality",
    }
)
EXPECTED_PROFILE_SHORTLIST = (
    {
        "profile_id": "reranker-only-v1",
        "evidence_source": "S20Q-I_SINGLE_SIGNAL_DIAGNOSTIC",
        "feature_fields": ["reranker_score"],
        "weights": {"reranker_score": 1.0},
    },
    {
        "profile_id": "s20qh-three-signal-balanced-v1",
        "evidence_source": "S20Q-H_LIVE_BEST_EFFORT",
        "feature_fields": [
            "reranker_score",
            "rrf_normalized_score",
            "channel_rank_quality",
        ],
        "weights": {
            "reranker_score": 0.3,
            "rrf_normalized_score": 0.4,
            "channel_rank_quality": 0.3,
        },
    },
    {
        "profile_id": "s20qk-three-signal-channel-v1",
        "evidence_source": "S20Q-K_4B_BASELINE_BEST_EFFORT",
        "feature_fields": [
            "reranker_score",
            "rrf_normalized_score",
            "channel_rank_quality",
        ],
        "weights": {
            "reranker_score": 0.3,
            "rrf_normalized_score": 0.3,
            "channel_rank_quality": 0.4,
        },
    },
    {
        "profile_id": "s20qi-expanded-channel-v1",
        "evidence_source": "S20Q-I_LIVE_BEST_EFFORT",
        "feature_fields": [
            "reranker_score",
            "channel_rank_quality",
            "bm25_score_quality",
        ],
        "weights": {
            "reranker_score": 0.6,
            "channel_rank_quality": 0.3,
            "bm25_score_quality": 0.1,
        },
    },
)

_PREDECESSOR = {
    "dataset_schema_version": "model_calibration_dataset.v3",
    "dataset_id": "s136-retrieval-package-confidence-public-v3",
    "file_sha256": (
        "5f79912782bb4f7c672894d1b5be445b958f93a5fb044730dc72b643a8bcb8c4"
    ),
    "dataset_sha256": (
        "edde3040ef27adf2ae450cc3c2193a0900620e2e514dc372a31ebe57085b34fb"
    ),
    "policy_audit_hash": (
        "sha256:9690c64496e4d2755649a7fe27e363b972d24f7f6df2204477c2f3d8373ca4f6"
    ),
}
_PACKAGE_SEMANTICS = {
    "ready_meaning": "AT_LEAST_TWO_RELEVANT_CANDIDATES",
    "package_score": "SECOND_HIGHEST_CANDIDATE_SCORE",
    "candidate_truth_used_at_runtime": False,
    "positive_roles": [
        "PRIMARY_ANSWER",
        "SUPPORTING_ANSWER",
        "HARD_NON_ANSWER",
        "EASY_NON_ANSWER",
    ],
    "negative_roles": [
        "HARD_NON_ANSWER",
        "RELATED_NON_ANSWER",
        "CONTRADICTORY_NON_ANSWER",
        "EASY_NON_ANSWER",
    ],
}
_AUTHORING = {
    "review_mode": "AUTHOR_PLUS_INDEPENDENT_REVIEWER",
    "minimum_distinct_reviewers": 2,
    "model_score_guided_authoring_permitted": False,
    "mechanical_paraphrase_permitted": False,
    "normalized_text_uniqueness_required": True,
    "semantic_near_duplicate_review_required": True,
    "holdout_labels_visible_to_calibration_executor": False,
}
_ADMISSION = {
    "pipeline_repeat_count": 5,
    "maximum_false_ready_rate": 0.1,
    "minimum_ready_recall": 0.8,
    "minimum_candidate_auc": 0.7,
    "minimum_outer_fold_balanced_accuracy": 0.5,
    "maximum_outer_threshold_spread": 0.2,
    "minimum_profile_selection_fold_count": 4,
    "confidence_interval_method": "WILSON_95_TWO_SIDED_REPORT_ONLY",
    "point_constraints_remain_authoritative": True,
    "calibration_oof_pass_required": True,
    "holdout_single_execution_required": True,
    "holdout_pass_required": True,
    "runtime_activation_requires_separate_approval": True,
}
_BOUNDARIES = {
    "dataset_v3_mutation_permitted": False,
    "dataset_v4_authoring_in_this_slice": False,
    "provider_execution_in_this_slice": False,
    "holdout_access_in_this_slice": False,
    "runtime_activation_in_this_slice": False,
    "model_revision_selection_in_this_slice": False,
    "threshold_relaxation_permitted": False,
    "incumbent_disposition": "KEEP_4B_4B_AS_NON_ADMITTED_BASELINE",
}


@dataclass
class RetrievalCalibrationDesignError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AdmittedRetrievalCalibrationDesign:
    design: dict[str, Any]
    manifest: dict[str, Any]


def admit_retrieval_calibration_v4_design(
    payload: Mapping[str, Any],
) -> AdmittedRetrievalCalibrationDesign:
    source = _mapping(payload, "design")
    if set(source) != {
        "design_schema_version",
        "design_id",
        "status",
        "predecessor",
        "dataset",
        "selection_protocol",
        "admission",
        "boundaries",
    }:
        raise _invalid("design fields")
    if source.get("design_schema_version") != (
        RETRIEVAL_CALIBRATION_DESIGN_SCHEMA_VERSION
    ):
        raise _invalid("design_schema_version")
    if source.get("design_id") != RETRIEVAL_CALIBRATION_DESIGN_ID:
        raise _invalid("design_id")
    if source.get("status") != "FROZEN_NOT_AUTHORED":
        raise _invalid("status")

    predecessor = _exact_mapping(source.get("predecessor"), _PREDECESSOR, "predecessor")
    dataset = _normalize_dataset(source.get("dataset"))
    selection = _normalize_selection(source.get("selection_protocol"), dataset)
    admission = _exact_mapping(source.get("admission"), _ADMISSION, "admission")
    boundaries = _exact_mapping(source.get("boundaries"), _BOUNDARIES, "boundaries")
    normalized = {
        "design_schema_version": RETRIEVAL_CALIBRATION_DESIGN_SCHEMA_VERSION,
        "design_id": RETRIEVAL_CALIBRATION_DESIGN_ID,
        "status": "FROZEN_NOT_AUTHORED",
        "predecessor": predecessor,
        "dataset": dataset,
        "selection_protocol": selection,
        "admission": admission,
        "boundaries": boundaries,
    }
    design_hash = semantic_sha256_hash_ref(normalized)
    manifest = {
        "design_schema_version": RETRIEVAL_CALIBRATION_DESIGN_SCHEMA_VERSION,
        "design_id": RETRIEVAL_CALIBRATION_DESIGN_ID,
        "design_hash": design_hash,
        "status": "FROZEN_NOT_AUTHORED",
        "target_dataset_schema_version": TARGET_DATASET_SCHEMA_VERSION,
        "target_dataset_id": TARGET_DATASET_ID,
        "scenario_count": dataset["scenario_count"],
        "calibration_scenario_count": PARTITION_SCENARIO_COUNTS["CALIBRATION"],
        "holdout_scenario_count": PARTITION_SCENARIO_COUNTS["HOLDOUT"],
        "outer_fold_count": selection["outer_fold_count"],
        "inner_fold_count": selection["inner_fold_count"],
        "profile_ids": [
            item["profile_id"] for item in selection["profile_shortlist"]
        ],
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    return AdmittedRetrievalCalibrationDesign(
        design=json.loads(json.dumps(normalized, sort_keys=True)),
        manifest=manifest,
    )


def _normalize_dataset(value: object) -> dict[str, Any]:
    dataset = _mapping(value, "dataset")
    if set(dataset) != {
        "target_schema_version",
        "target_dataset_id",
        "independent_unit",
        "scenario_count",
        "partition_scenario_counts",
        "packages_per_scenario",
        "candidates_per_package",
        "package_count",
        "candidate_count",
        "partition_language_scenario_counts",
        "partition_domain_scenario_counts",
        "package_semantics",
        "authoring",
    }:
        raise _invalid("dataset fields")
    if (
        dataset.get("target_schema_version") != TARGET_DATASET_SCHEMA_VERSION
        or dataset.get("target_dataset_id") != TARGET_DATASET_ID
        or dataset.get("independent_unit") != "SCENARIO_PAIR"
    ):
        raise _invalid("dataset identity")
    counts = _exact_mapping(
        dataset.get("partition_scenario_counts"),
        PARTITION_SCENARIO_COUNTS,
        "partition_scenario_counts",
    )
    scenario_count = _integer(dataset.get("scenario_count"), "scenario_count")
    packages_per_scenario = _integer(
        dataset.get("packages_per_scenario"), "packages_per_scenario"
    )
    candidates_per_package = _integer(
        dataset.get("candidates_per_package"), "candidates_per_package"
    )
    package_count = _integer(dataset.get("package_count"), "package_count")
    candidate_count = _integer(dataset.get("candidate_count"), "candidate_count")
    if (
        scenario_count != sum(counts.values())
        or scenario_count != 100
        or packages_per_scenario != 2
        or candidates_per_package != 4
        or package_count != scenario_count * packages_per_scenario
        or candidate_count != package_count * candidates_per_package
    ):
        raise _invalid("dataset counts")
    language_counts = _partition_quotas(
        dataset.get("partition_language_scenario_counts"),
        PARTITION_LANGUAGE_SCENARIO_COUNTS,
        "partition language quotas",
    )
    domain_counts = _partition_quotas(
        dataset.get("partition_domain_scenario_counts"),
        PARTITION_DOMAIN_SCENARIO_COUNTS,
        "partition domain quotas",
    )
    semantics = _exact_mapping(
        dataset.get("package_semantics"), _PACKAGE_SEMANTICS, "package_semantics"
    )
    authoring = _exact_mapping(dataset.get("authoring"), _AUTHORING, "authoring")
    return {
        "target_schema_version": TARGET_DATASET_SCHEMA_VERSION,
        "target_dataset_id": TARGET_DATASET_ID,
        "independent_unit": "SCENARIO_PAIR",
        "scenario_count": scenario_count,
        "partition_scenario_counts": counts,
        "packages_per_scenario": packages_per_scenario,
        "candidates_per_package": candidates_per_package,
        "package_count": package_count,
        "candidate_count": candidate_count,
        "partition_language_scenario_counts": language_counts,
        "partition_domain_scenario_counts": domain_counts,
        "package_semantics": semantics,
        "authoring": authoring,
    }


def _normalize_selection(value: object, dataset: Mapping[str, Any]) -> dict[str, Any]:
    selection = _mapping(value, "selection_protocol")
    required = {
        "mode",
        "group_key",
        "stratification_fields",
        "assignment_algorithm",
        "assignment_seed",
        "outer_fold_count",
        "inner_fold_count",
        "outer_validation_scenarios_per_fold",
        "inner_validation_scenarios_per_fold",
        "maximum_profile_count",
        "profile_shortlist",
        "selection_objective",
        "selection_tie_break",
        "inner_loop_selects",
        "outer_loop_evaluates_only",
        "outer_validation_reselection_permitted",
        "final_threshold_fit_partition",
        "holdout_threshold_reselection_permitted",
    }
    if set(selection) != required:
        raise _invalid("selection_protocol fields")
    fixed = {
        "mode": "NESTED_STRATIFIED_GROUP_CV_WITH_PREFROZEN_SHORTLIST",
        "group_key": "scenario_id",
        "stratification_fields": ["domain", "language_profile"],
        "assignment_algorithm": "SHA256_STRATIFIED_ROUND_ROBIN_V1",
        "assignment_seed": "s136-v4-nested-cv-v1",
        "selection_objective": "CONSTRAINT_FIRST_BALANCED_ACCURACY",
        "selection_tie_break": [
            "HIGHER_BALANCED_ACCURACY",
            "HIGHER_READY_RECALL",
            "LOWER_FALSE_READY_RATE",
            "HIGHER_CANDIDATE_AUC",
            "PROFILE_SHORTLIST_ORDER",
        ],
        "inner_loop_selects": ["PROFILE_ID", "THRESHOLD"],
        "outer_loop_evaluates_only": True,
        "outer_validation_reselection_permitted": False,
        "final_threshold_fit_partition": "CALIBRATION_ONLY",
        "holdout_threshold_reselection_permitted": False,
    }
    for field, expected in fixed.items():
        if selection.get(field) != expected:
            raise _invalid(field)
    outer_count = _integer(selection.get("outer_fold_count"), "outer_fold_count")
    inner_count = _integer(selection.get("inner_fold_count"), "inner_fold_count")
    outer_size = _integer(
        selection.get("outer_validation_scenarios_per_fold"),
        "outer_validation_scenarios_per_fold",
    )
    inner_size = _integer(
        selection.get("inner_validation_scenarios_per_fold"),
        "inner_validation_scenarios_per_fold",
    )
    calibration_count = int(dataset["partition_scenario_counts"]["CALIBRATION"])
    if (
        outer_count != 5
        or inner_count != 4
        or calibration_count % outer_count
        or outer_size != calibration_count // outer_count
        or (calibration_count - outer_size) % inner_count
        or inner_size != (calibration_count - outer_size) // inner_count
    ):
        raise _invalid("nested fold geometry")
    maximum_profiles = _integer(
        selection.get("maximum_profile_count"), "maximum_profile_count"
    )
    profiles = _normalize_profiles(selection.get("profile_shortlist"))
    if maximum_profiles != 5 or len(profiles) > maximum_profiles:
        raise _invalid("profile shortlist size")
    return {
        **fixed,
        "outer_fold_count": outer_count,
        "inner_fold_count": inner_count,
        "outer_validation_scenarios_per_fold": outer_size,
        "inner_validation_scenarios_per_fold": inner_size,
        "maximum_profile_count": maximum_profiles,
        "profile_shortlist": profiles,
    }


def _normalize_profiles(value: object) -> list[dict[str, Any]]:
    values = _sequence(value, "profile_shortlist")
    normalized: list[dict[str, Any]] = []
    profile_ids: set[str] = set()
    for item in values:
        profile = _mapping(item, "profile")
        if set(profile) != {
            "profile_id",
            "evidence_source",
            "feature_fields",
            "weights",
        }:
            raise _invalid("profile fields")
        profile_id = _string(profile.get("profile_id"), "profile_id")
        if profile_id in profile_ids:
            raise _invalid("duplicate profile_id")
        profile_ids.add(profile_id)
        evidence_source = _string(profile.get("evidence_source"), "evidence_source")
        fields = [_string(field, "feature_field") for field in _sequence(profile.get("feature_fields"), "feature_fields")]
        if not fields or len(fields) > 3 or len(fields) != len(set(fields)):
            raise _invalid("feature_fields")
        if any(field not in ALLOWED_SIGNAL_FIELDS for field in fields):
            raise _invalid("feature field")
        raw_weights = _mapping(profile.get("weights"), "weights")
        if set(raw_weights) != set(fields):
            raise _invalid("weight fields")
        weights = {field: _weight(raw_weights[field], field) for field in fields}
        if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
            raise _invalid("weight sum")
        normalized.append(
            {
                "profile_id": profile_id,
                "evidence_source": evidence_source,
                "feature_fields": fields,
                "weights": weights,
            }
        )
    if normalized != list(EXPECTED_PROFILE_SHORTLIST):
        raise _invalid("profile shortlist drift")
    return normalized


def _partition_quotas(
    value: object,
    expected: Mapping[str, Mapping[str, int]],
    field: str,
) -> dict[str, dict[str, int]]:
    source = _mapping(value, field)
    if set(source) != set(PARTITION_SCENARIO_COUNTS):
        raise _invalid(field)
    result: dict[str, dict[str, int]] = {}
    for partition, expected_quota in expected.items():
        quota = _exact_mapping(source.get(partition), expected_quota, field)
        result[partition] = quota
    return result


def _exact_mapping(
    value: object, expected: Mapping[str, Any], field: str
) -> dict[str, Any]:
    source = _mapping(value, field)
    if dict(source) != dict(expected):
        raise _invalid(field)
    return json.loads(json.dumps(dict(expected)))


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _invalid(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string")
    return value.strip()


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _invalid(f"{field} must be a positive integer")
    return value


def _weight(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise _invalid(f"{field} weight")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 < normalized <= 1.0:
        raise _invalid(f"{field} weight")
    return normalized


def _invalid(field: str) -> RetrievalCalibrationDesignError:
    return RetrievalCalibrationDesignError(
        "retrieval_calibration_design.invalid",
        f"Invalid retrieval calibration design: {field}.",
    )
