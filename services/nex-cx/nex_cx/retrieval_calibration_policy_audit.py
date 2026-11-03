from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_candidate_relevance_calibration import (
    EXPANDED_CANDIDATE_SIGNAL_FIELDS,
    diagnose_candidate_relevance_profile_outcomes,
)

CALIBRATION_POLICY_AUDIT_SCHEMA_VERSION = "cx_calibration_policy_audit.v1"
INCUMBENT_EMBEDDING_REVISION = "hf:5cf2132abc99cad020ac570b19d031efec650f2b"
INCUMBENT_RERANKER_REVISION = "hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5"


class CalibrationPolicyAuditError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def audit_calibration_dataset_and_package_policy(
    calibration_cases: Sequence[Mapping[str, Any]],
    candidate_samples: Sequence[Mapping[str, Any]],
    current_evidence: Mapping[str, Any],
    *,
    historical_evidence: Mapping[str, Any],
    numeric_tolerance: float,
    signal_tolerances: Mapping[str, float],
) -> dict[str, Any]:
    cases, case_by_sample, scenario_metadata = _admit_cases(calibration_cases)
    current = _admit_evidence(current_evidence)
    historical = _admit_evidence(historical_evidence)
    if current["dataset"] != historical["dataset"]:
        raise CalibrationPolicyAuditError("S20QL_DATASET_BINDING_DRIFT")
    if current["binding"] != historical["binding"]:
        raise CalibrationPolicyAuditError("S20QL_MODEL_OR_POLICY_BINDING_DRIFT")
    binding = current["binding"]
    if (
        binding.get("embedding_model_revision") != INCUMBENT_EMBEDDING_REVISION
        or binding.get("reranker_model_revision") != INCUMBENT_RERANKER_REVISION
    ):
        raise CalibrationPolicyAuditError("S20QL_INCUMBENT_BINDING_INVALID")

    calibration = _mapping(current.get("candidate_relevance_calibration"))
    best_effort = _mapping(calibration.get("best_effort"))
    diagnostic = diagnose_candidate_relevance_profile_outcomes(
        candidate_samples,
        dataset_id=str(current["dataset"]["dataset_id"]),
        profile=best_effort,
        numeric_tolerance=numeric_tolerance,
        signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
        signal_tolerances=signal_tolerances,
    )
    outcomes = list(diagnostic["outcomes"])
    failures = _failure_projection(outcomes, case_by_sample, scenario_metadata)
    pair_separation = _pair_separation(outcomes)
    metrics = _mapping(best_effort.get("oof_metrics"))
    constraints = _mapping(_mapping(calibration.get("cross_validation")).get("constraints"))
    positive_count = 20
    negative_count = 20
    maximum_false_ready = math.floor(
        float(constraints.get("maximum_false_ready_rate")) * negative_count
    )
    minimum_true_ready = math.ceil(
        float(constraints.get("minimum_ready_recall")) * positive_count
    )
    profile_count = _positive_int(
        _mapping(calibration.get("search")).get("profile_count"),
        "profile_count",
    )
    fold_count = _positive_int(
        _mapping(calibration.get("cross_validation")).get("fold_count"),
        "fold_count",
    )
    scenario_count = len(scenario_metadata)
    package_count = len(cases)
    current_metrics = _metric_projection(best_effort)
    historical_best = _mapping(
        _mapping(historical.get("candidate_relevance_calibration")).get("best_effort")
    )
    historical_metrics = _metric_projection(historical_best)
    result = {
        "audit_schema_version": CALIBRATION_POLICY_AUDIT_SCHEMA_VERSION,
        "status": "AUDITED",
        "incumbent": {
            "embedding_model_revision": INCUMBENT_EMBEDDING_REVISION,
            "reranker_model_revision": INCUMBENT_RERANKER_REVISION,
            "disposition": "KEEP_AS_BASELINE_NOT_ADMITTED",
        },
        "dataset": {
            **dict(current["dataset"]),
            "effective_independent_unit": "SCENARIO_PAIR",
            "effective_independent_count": scenario_count,
            "package_count": package_count,
            "candidate_count": len(candidate_samples),
            "candidate_label_counts": {
                "relevant": sum(bool(row.get("expected_relevant")) for row in candidate_samples),
                "non_relevant": sum(not bool(row.get("expected_relevant")) for row in candidate_samples),
            },
            "domain_scenario_counts": dict(
                sorted(Counter(row["domain"] for row in scenario_metadata.values()).items())
            ),
            "language_scenario_counts": dict(
                sorted(Counter(row["language_profile"] for row in scenario_metadata.values()).items())
            ),
        },
        "package_policy": {
            "ready_meaning": "AT_LEAST_TWO_RELEVANT_CANDIDATES",
            "package_score": "SECOND_HIGHEST_CANDIDATE_SCORE",
            "semantic_alignment": "EXACT",
            "candidate_truth_used_at_runtime": False,
            "profile_outcome_diagnostic_hash": diagnostic["diagnostic_hash"],
        },
        "statistical_resolution": {
            "profile_count": profile_count,
            "profiles_per_scenario": round(profile_count / scenario_count, 8),
            "profiles_per_package": round(profile_count / package_count, 8),
            "fold_count": fold_count,
            "validation_scenarios_per_fold": scenario_count // fold_count,
            "validation_packages_per_fold": package_count // fold_count,
            "validation_labels_per_class": positive_count // fold_count,
            "fold_rate_increment": round(1.0 / (positive_count // fold_count), 8),
            "overall_rate_increment": round(1.0 / positive_count, 8),
            "selection_mode": "SINGLE_LEVEL_GROUP_CV_PROFILE_SEARCH",
            "selection_bias_risk": "HIGH",
        },
        "constraint_gap": {
            "maximum_false_ready": maximum_false_ready,
            "observed_false_ready": int(metrics.get("false_ready")),
            "false_ready_excess": max(
                0, int(metrics.get("false_ready")) - maximum_false_ready
            ),
            "minimum_true_ready": minimum_true_ready,
            "observed_true_ready": int(metrics.get("true_ready")),
            "true_ready_deficit": max(
                0, minimum_true_ready - int(metrics.get("true_ready"))
            ),
        },
        "current_outcomes": {
            "metrics": current_metrics,
            "pair_separation": pair_separation,
            "failures": failures,
        },
        "cross_execution": {
            "exact_binding": True,
            "historical_metrics": historical_metrics,
            "current_metrics": current_metrics,
            "metric_delta": {
                key: round(current_metrics[key] - historical_metrics[key], 8)
                for key in current_metrics
            },
            "profile_changed": (
                best_effort.get("feature_fields") != historical_best.get("feature_fields")
                or best_effort.get("weights") != historical_best.get("weights")
            ),
            "decision_stable": (
                calibration.get("status")
                == _mapping(historical.get("candidate_relevance_calibration")).get("status")
                == "NO_ACCEPTABLE_POLICY"
            ),
        },
        "findings": [
            "DATASET_STRUCTURE_VALID_BUT_EFFECTIVE_N_IS_20_SCENARIO_PAIRS",
            "SECOND_HIGHEST_PACKAGE_RULE_MATCHES_TWO_EVIDENCE_SEMANTICS",
            "PROFILE_SEARCH_SPACE_EXCEEDS_INDEPENDENT_SAMPLE_CAPACITY",
            "FOLD_ERROR_RATES_MOVE_IN_0_25_STEPS",
            "INCUMBENT_DECISION_IS_STABLE_BUT_METRICS_ARE_EXECUTION_SENSITIVE",
            "THRESHOLD_RELAXATION_IS_NOT_AUTHORIZED",
        ],
        "decision": {
            "status": "CORRECTIVE_DATASET_AND_POLICY_DESIGN_REQUIRED",
            "incumbent_action": "KEEP_4B_4B_AS_NON_ADMITTED_BASELINE",
            "next_action": "DATASET_V4_EXPANSION_AND_NESTED_SELECTION_DESIGN",
            "holdout_access_permitted": False,
            "runtime_activation_permitted": False,
            "threshold_relaxation_permitted": False,
        },
    }
    result["audit_hash"] = semantic_sha256_hash_ref(result)
    return result


def _admit_cases(
    values: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("S20Q-L calibration cases are invalid")
    cases: list[dict[str, Any]] = []
    case_by_sample: dict[str, dict[str, Any]] = {}
    scenario_metadata: dict[str, dict[str, str]] = {}
    for value in values:
        if not isinstance(value, Mapping) or value.get("partition") != "CALIBRATION":
            raise CalibrationPolicyAuditError("S20QL_CALIBRATION_CASE_INVALID")
        case = dict(value)
        scenario_id = _required_string(case.get("scenario_id"), "scenario_id")
        expected_ready = case.get("expected_ready")
        candidates = case.get("candidates")
        if type(expected_ready) is not bool or not isinstance(candidates, list) or len(candidates) != 4:
            raise CalibrationPolicyAuditError("S20QL_CALIBRATION_CASE_INVALID")
        label = "positive" if expected_ready else "negative"
        sample_id = f"{scenario_id}:{label}"
        if sample_id in case_by_sample:
            raise CalibrationPolicyAuditError("S20QL_CALIBRATION_CASE_DUPLICATE")
        metadata = {
            "domain": _required_string(case.get("domain"), "domain"),
            "language_profile": _required_string(
                case.get("language_profile"), "language_profile"
            ),
        }
        previous = scenario_metadata.setdefault(scenario_id, metadata)
        if previous != metadata:
            raise CalibrationPolicyAuditError("S20QL_SCENARIO_METADATA_DRIFT")
        role_by_candidate = {
            _required_string(item.get("candidate_id"), "candidate_id"): _required_string(
                item.get("evidence_role"), "evidence_role"
            )
            for item in candidates
            if isinstance(item, Mapping)
        }
        if len(role_by_candidate) != 4:
            raise CalibrationPolicyAuditError("S20QL_CANDIDATE_ROLE_INVALID")
        case_by_sample[sample_id] = {**metadata, "roles": role_by_candidate}
        cases.append(case)
    if len(cases) != 40 or len(scenario_metadata) != 20:
        raise CalibrationPolicyAuditError("S20QL_EFFECTIVE_SAMPLE_BOUNDARY_INVALID")
    if any(
        {f"{scenario}:positive", f"{scenario}:negative"} - set(case_by_sample)
        for scenario in scenario_metadata
    ):
        raise CalibrationPolicyAuditError("S20QL_SCENARIO_PAIR_INCOMPLETE")
    return cases, case_by_sample, scenario_metadata


def _admit_evidence(value: Mapping[str, Any]) -> Mapping[str, Any]:
    calibration = _mapping(value.get("candidate_relevance_calibration"))
    if (
        value.get("status") != "PASS"
        or not _all_true(value.get("checks"))
        or calibration.get("status") != "NO_ACCEPTABLE_POLICY"
        or calibration.get("holdout_access_permitted") is not False
        or calibration.get("runtime_activation_permitted") is not False
        or _mapping(calibration.get("holdout")).get("status") != "SEALED_NOT_OPENED"
    ):
        raise CalibrationPolicyAuditError("S20QL_EVIDENCE_NOT_ADMITTED")
    dataset = _mapping(value.get("dataset"))
    binding = _mapping(value.get("binding"))
    if dataset.get("partition") != "CALIBRATION" or dataset.get("holdout_status") != "SEALED_NOT_COLLECTED":
        raise CalibrationPolicyAuditError("S20QL_HOLDOUT_BOUNDARY_INVALID")
    return {**dict(value), "dataset": dict(dataset), "binding": dict(binding)}


def _failure_projection(
    outcomes: Sequence[Mapping[str, Any]],
    case_by_sample: Mapping[str, Mapping[str, Any]],
    scenario_metadata: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for row in outcomes:
        if row["outcome"] not in {"FALSE_READY", "FALSE_LOW_CONFIDENCE"}:
            continue
        sample_id = str(row["sample_id"])
        case = case_by_sample[sample_id]
        top2 = list(row["ranked_candidates"])[:2]
        failures.append(
            {
                "scenario_id": row["scenario_id"],
                "sample_id": sample_id,
                "outcome": row["outcome"],
                "domain": case["domain"],
                "language_profile": case["language_profile"],
                "package_score": row["package_score"],
                "threshold": row["threshold"],
                "top2_roles": [case["roles"][item["candidate_id"]] for item in top2],
                "top2_relevant_count": sum(bool(item["expected_relevant"]) for item in top2),
            }
        )
    return {
        "count": len(failures),
        "items": sorted(failures, key=lambda row: (row["outcome"], row["sample_id"])),
        "domain_counts": dict(sorted(Counter(row["domain"] for row in failures).items())),
        "language_counts": dict(
            sorted(Counter(row["language_profile"] for row in failures).items())
        ),
        "scenario_metadata_count": len(scenario_metadata),
    }


def _pair_separation(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pairs: dict[str, dict[bool, float]] = {}
    for row in outcomes:
        pairs.setdefault(str(row["scenario_id"]), {})[bool(row["expected_ready"])] = float(row["package_score"])
    deltas = [labels[True] - labels[False] for labels in pairs.values()]
    return {
        "positive_higher": sum(delta > 0 for delta in deltas),
        "tied": sum(math.isclose(delta, 0.0, abs_tol=1e-12) for delta in deltas),
        "negative_higher": sum(delta < 0 for delta in deltas),
        "minimum_delta": round(min(deltas), 8),
        "maximum_delta": round(max(deltas), 8),
    }


def _metric_projection(value: Mapping[str, Any]) -> dict[str, float]:
    metrics = _mapping(value.get("oof_metrics"))
    return {
        "false_ready_rate": float(metrics.get("false_ready_rate")),
        "ready_recall": float(metrics.get("ready_recall")),
        "balanced_accuracy": float(metrics.get("balanced_accuracy")),
        "candidate_auc": float(value.get("candidate_auc")),
        "minimum_fold_balanced_accuracy": float(
            value.get("minimum_fold_balanced_accuracy")
        ),
        "threshold_spread": float(value.get("threshold_spread")),
    }


def _all_true(value: object) -> bool:
    return isinstance(value, Mapping) and bool(value) and all(item is True for item in value.values())


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CalibrationPolicyAuditError(f"S20QL_{field.upper()}_INVALID")
    return value


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CalibrationPolicyAuditError(f"S20QL_{field.upper()}_INVALID")
    return value.strip()
