from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
    evaluate_binary_score_threshold,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

import nex_cx.retrieval_answer_support_nested_selection as answer_support
import nex_cx.retrieval_calibration_nested_selection as nested_support
from nex_cx.retrieval_answer_support_canonical_profile import (
    CANONICAL_PROFILE_ID,
    validate_canonical_answer_support_profile_design,
)

CANONICAL_CALIBRATION_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_canonical_calibration_design.v1"
)
CANONICAL_CALIBRATION_RESULT_SCHEMA_VERSION = (
    "cx_answer_support_canonical_threshold_calibration.v1"
)

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "protocol",
    "admission",
    "safety",
}
_SOURCE_FIELDS = {
    "artifact_evidence_hash",
    "artifact_revision",
    "canonical_profile_hash",
    "p_l_design_hash",
    "p_l_freeze_hash",
    "p_m_dataset_hash",
    "p_n_collection_hash",
}
_EXPECTED_PROTOCOL = {
    "final_refit_scope": "ALL_FRESH_CALIBRATION_PACKAGES",
    "fold_assignment": "DOMAIN_LANGUAGE_STRATIFIED_ROUND_ROBIN_V1",
    "group_key": "scenario_id",
    "mode": "SINGLE_CANONICAL_PROFILE_THRESHOLD_ONLY",
    "outer_fold_count": 5,
    "outer_training_scope": "FRESH_CALIBRATION_OUTER_TRAINING_ONLY",
    "outer_validation_reselection_permitted": False,
    "profile_search_permitted": False,
}
_EXPECTED_ADMISSION = {
    "maximum_false_ready_rate": 0.1,
    "maximum_outer_threshold_spread": 0.2,
    "minimum_outer_fold_balanced_accuracy": 0.5,
    "minimum_package_auc": 0.8,
    "minimum_ready_recall": 0.8,
    "outer_fold_count": 5,
    "point_constraints_remain_authoritative": True,
}
_EXPECTED_SAFETY = {
    "candidate_truth_runtime_input_permitted": False,
    "holdout_access_permitted": False,
    "profile_search_permitted": False,
    "runtime_activation_permitted": False,
    "threshold_relaxation_permitted": False,
}
_LANGUAGE_QUOTAS = {
    "ENGLISH": 4,
    "KOREAN": 12,
    "KOREAN_ENGLISH_MIXED": 4,
}


def validate_canonical_calibration_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the post-collection, fixed-profile threshold-fit contract."""
    _exact_mapping(design, _DESIGN_FIELDS, "canonical calibration design")
    if (
        design.get("design_schema_version")
        != CANONICAL_CALIBRATION_DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_SINGLE_PROFILE_CALIBRATION_ONLY"
    ):
        raise ValueError("canonical calibration design identity is invalid")
    _required_text(design.get("design_id"), "design_id")
    source = _exact_mapping(
        design.get("source_binding"), _SOURCE_FIELDS, "calibration source binding"
    )
    normalized_source = {
        field: (
            _required_text(source.get(field), field)
            if field == "artifact_revision"
            else validate_hash_ref(source.get(field))
        )
        for field in sorted(_SOURCE_FIELDS)
    }
    if dict(_mapping(design.get("protocol"), "calibration protocol")) != _EXPECTED_PROTOCOL:
        raise ValueError("canonical calibration protocol is invalid")
    if dict(_mapping(design.get("admission"), "calibration admission")) != _EXPECTED_ADMISSION:
        raise ValueError("canonical calibration admission is invalid")
    if dict(_mapping(design.get("safety"), "calibration safety")) != _EXPECTED_SAFETY:
        raise ValueError("canonical calibration safety is invalid")
    normalized = dict(design)
    normalized["source_binding"] = normalized_source
    normalized["design_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def calibrate_canonical_answer_support_threshold(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    collection_hash: str,
    provider_binding: Mapping[str, Any],
    artifact_evidence_hash: str,
    canonical_design: Mapping[str, Any],
    canonical_freeze: Mapping[str, Any],
    calibration_design: Mapping[str, Any],
) -> dict[str, Any]:
    """Fit one frozen profile by grouped OOF CALIBRATION, never by HOLDOUT."""
    normalized = answer_support._normalize_samples(samples)
    fixed_design = validate_canonical_calibration_design(calibration_design)
    profile_design = validate_canonical_answer_support_profile_design(
        canonical_design
    )
    source = fixed_design["source_binding"]
    profile = _validated_canonical_freeze(
        canonical_freeze,
        canonical_design=profile_design,
        source=source,
    )
    dataset_hash = validate_hash_ref(dataset_sha256)
    source_collection_hash = validate_hash_ref(collection_hash)
    artifact_hash = validate_hash_ref(artifact_evidence_hash)
    binding = answer_support._provider_binding(provider_binding)
    if (
        dataset_hash != source["p_m_dataset_hash"]
        or source_collection_hash != source["p_n_collection_hash"]
        or artifact_hash != source["artifact_evidence_hash"]
        or binding["model_revision"] != source["artifact_revision"]
    ):
        raise ValueError("canonical calibration source binding is invalid")

    fold_plan = _stratified_outer_folds(normalized)
    constraints = BinaryCalibrationConstraints(
        maximum_false_ready_rate=_EXPECTED_ADMISSION["maximum_false_ready_rate"],
        minimum_ready_recall=_EXPECTED_ADMISSION["minimum_ready_recall"],
    )
    scenario_ids = {str(row["scenario_id"]) for row in normalized}
    outer_results = []
    oof_scores: list[dict[str, Any]] = []
    for fold in fold_plan:
        validation_ids = set(fold["validation_scenario_ids"])
        training_ids = scenario_ids - validation_ids
        training_scores = answer_support._profile_scores(
            normalized, profile=profile, scenario_ids=training_ids
        )
        fit = evaluate_binary_score_calibration(
            training_scores,
            dataset_id=(
                f"{dataset_id}:canonical-threshold:outer-{fold['fold_index']}:train"
            ),
            constraints=constraints,
        )
        threshold = fit.get("selected_threshold")
        if threshold is None:
            outer_results.append(
                {
                    "fold_index": fold["fold_index"],
                    "status": "NO_ACCEPTABLE_TRAINING_THRESHOLD",
                    "training_package_count": len(training_scores),
                    "validation_package_count": 0,
                    "threshold": None,
                    "metrics": None,
                }
            )
            continue
        validation_scores = answer_support._profile_scores(
            normalized, profile=profile, scenario_ids=validation_ids
        )
        evaluation = evaluate_binary_score_threshold(
            validation_scores,
            dataset_id=(
                f"{dataset_id}:canonical-threshold:outer-{fold['fold_index']}:validation"
            ),
            threshold=float(threshold),
            constraints=nested_support._partition_constraints(
                len(validation_scores), constraints=constraints
            ),
        )
        oof_scores.extend(validation_scores)
        outer_results.append(
            {
                "fold_index": fold["fold_index"],
                "status": "EVALUATED",
                "training_package_count": len(training_scores),
                "validation_package_count": len(validation_scores),
                "threshold": float(threshold),
                "metrics": evaluation["metrics"],
                "confidence_intervals": evaluation["confidence_intervals"],
            }
        )

    completed = [row for row in outer_results if row["status"] == "EVALUATED"]
    aggregate = nested_support._aggregate_metrics(
        [answer_support._mapping(row["metrics"], "outer metrics") for row in completed]
    )
    thresholds = [float(row["threshold"]) for row in completed]
    threshold_spread = (
        round(max(thresholds) - min(thresholds), 8) if thresholds else None
    )
    minimum_accuracy = (
        min(float(row["metrics"]["balanced_accuracy"]) for row in completed)
        if completed
        else None
    )
    package_auc = answer_support._auc(oof_scores) if oof_scores else None
    checks = {
        "all_outer_folds_evaluated": len(completed) == 5,
        "oof_package_coverage_complete": len(oof_scores) == len(normalized),
        "false_ready_rate_within_limit": aggregate is not None
        and aggregate["false_ready_rate"] <= 0.1,
        "ready_recall_within_limit": aggregate is not None
        and aggregate["ready_recall"] >= 0.8,
        "package_auc_within_limit": package_auc is not None and package_auc >= 0.8,
        "minimum_outer_accuracy_within_limit": minimum_accuracy is not None
        and minimum_accuracy >= 0.5,
        "outer_threshold_spread_within_limit": threshold_spread is not None
        and threshold_spread <= 0.2,
    }
    admitted = all(checks.values())
    final_fit = None
    if admitted:
        final_fit = evaluate_binary_score_calibration(
            answer_support._profile_scores(normalized, profile=profile),
            dataset_id=f"{dataset_id}:canonical-threshold:full-calibration",
            constraints=constraints,
        )
        checks["full_calibration_threshold_fitted"] = final_fit["status"] == "PASSED"
        admitted = checks["full_calibration_threshold_fitted"]
        if not admitted:
            final_fit = None

    result: dict[str, Any] = {
        "calibration_schema_version": CANONICAL_CALIBRATION_RESULT_SCHEMA_VERSION,
        "status": (
            "CALIBRATION_THRESHOLD_CANDIDATE_ADMITTED"
            if admitted
            else "NO_ADMISSIBLE_THRESHOLD"
        ),
        "reason_code": (
            "FIXED_PROFILE_OOF_CONSTRAINTS_SATISFIED"
            if admitted
            else "FIXED_PROFILE_OOF_CONSTRAINTS_NOT_SATISFIED"
        ),
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {
            "dataset_id": _required_text(dataset_id, "dataset_id"),
            "dataset_sha256": dataset_hash,
            "partition": "CALIBRATION",
            "scenario_count": len(scenario_ids),
            "package_count": len(normalized),
            "sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["sample_hash"]) for row in normalized)
            ),
        },
        "binding": {
            "calibration_design_hash": fixed_design["design_hash"],
            "canonical_design_hash": profile_design["design_hash"],
            "canonical_profile_hash": profile["profile_hash"],
            "source_collection_hash": source_collection_hash,
            "artifact_evidence_hash": artifact_hash,
            "provider_binding": binding,
        },
        "protocol": {
            **fixed_design["protocol"],
            "profile_id": profile["profile_id"],
            "profile_count": 1,
            "fold_assignment_hash": semantic_sha256_hash_ref(fold_plan),
        },
        "fold_plan": fold_plan,
        "outer_folds": outer_results,
        "oof_evaluation": {
            "metrics": aggregate,
            "confidence_intervals": nested_support._confidence_intervals(aggregate),
            "package_auc": package_auc,
            "minimum_outer_fold_balanced_accuracy": minimum_accuracy,
            "threshold_spread": threshold_spread,
        },
        "checks": checks,
        "candidate": (
            {
                "status": "CANDIDATE_NOT_ACTIVE",
                "profile_id": profile["profile_id"],
                "profile_hash": profile["profile_hash"],
                "threshold": final_fit["selected_threshold"],
                "fit": final_fit,
            }
            if admitted and final_fit is not None
            else None
        ),
        "holdout": {
            "status": "SEALED_NOT_OPENED",
            "threshold_reselected": False,
        },
    }
    result["calibration_hash"] = semantic_sha256_hash_ref(result)
    return result


def _validated_canonical_freeze(
    freeze: Mapping[str, Any],
    *,
    canonical_design: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    value = dict(_mapping(freeze, "canonical profile freeze"))
    freeze_hash = validate_hash_ref(value.pop("freeze_hash", None))
    profile = dict(_mapping(value.get("canonical_profile"), "canonical profile"))
    if (
        semantic_sha256_hash_ref(value) != freeze_hash
        or freeze_hash != source["p_l_freeze_hash"]
        or value.get("design_hash") != source["p_l_design_hash"]
        or canonical_design["design_hash"] != source["p_l_design_hash"]
        or profile.get("profile_id") != CANONICAL_PROFILE_ID
        or profile.get("profile_hash") != source["canonical_profile_hash"]
        or profile.get("threshold") is not None
        or value.get("admission") != _EXPECTED_ADMISSION
        or value.get("holdout_access_permitted") is not False
        or value.get("runtime_activation_permitted") is not False
    ):
        raise ValueError("canonical profile freeze binding is invalid")
    return profile


def _stratified_outer_folds(
    samples: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    scenarios: dict[str, tuple[str, str]] = {}
    for row in samples:
        scenario_id = str(row["scenario_id"])
        stratum = (str(row["domain"]), str(row["language_profile"]))
        previous = scenarios.setdefault(scenario_id, stratum)
        if previous != stratum:
            raise ValueError("canonical calibration scenario stratum is inconsistent")
    domains = sorted({value[0] for value in scenarios.values()})
    languages = sorted({value[1] for value in scenarios.values()})
    if len(scenarios) != 100 or len(domains) != 5 or set(languages) != set(_LANGUAGE_QUOTAS):
        raise ValueError("canonical calibration scenario coverage is invalid")

    assignments: dict[int, list[str]] = defaultdict(list)
    language_offsets = {
        "KOREAN": 0,
        "KOREAN_ENGLISH_MIXED": 2,
        "ENGLISH": 1,
    }
    for domain_index, domain in enumerate(domains):
        for language in languages:
            values = sorted(
                scenario_id
                for scenario_id, stratum in scenarios.items()
                if stratum == (domain, language)
            )
            expected = 12 if language == "KOREAN" else 4
            if len(values) != expected:
                raise ValueError("canonical calibration stratum coverage is invalid")
            offset = domain_index + language_offsets[language]
            for index, scenario_id in enumerate(values):
                assignments[(index + offset) % 5].append(scenario_id)

    folds = []
    for fold_index in range(5):
        validation_ids = sorted(assignments[fold_index])
        domain_counts = Counter(scenarios[value][0] for value in validation_ids)
        language_counts = Counter(scenarios[value][1] for value in validation_ids)
        if (
            len(validation_ids) != 20
            or set(domain_counts.values()) != {4}
            or dict(language_counts) != _LANGUAGE_QUOTAS
        ):
            raise ValueError("canonical calibration fold balance is invalid")
        folds.append(
            {
                "fold_index": fold_index,
                "validation_scenario_ids": validation_ids,
                "domain_counts": dict(sorted(domain_counts.items())),
                "language_counts": dict(sorted(language_counts.items())),
            }
        )
    return folds


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
