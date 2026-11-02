from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_confidence_calibration import RetrievalConfidenceWeights
from nex_cx.retrieval_confidence_multisignal import (
    WEIGHTED_FEATURE_FIELDS,
    reweight_multisignal_feature_package,
)

FEATURE_AUDIT_SCHEMA_VERSION = "cx_retrieval_confidence_feature_audit.v1"
FEATURE_AUDIT_POLICY_ID = "cx_multisignal_feature_discriminativeness_v1"
PAIR_SEMANTICS = "POSITIVE_PAIR_VS_NEGATIVE_PAIR"
NEAR_CONSTANT_TOLERANCE = 1e-9
NEAR_PERFECT_CORRELATION = 0.95
DEFAULT_FEATURE_AUDIT_CONSTRAINTS = BinaryCalibrationConstraints()


def audit_multisignal_feature_discriminativeness(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    expected_binding: Mapping[str, Any],
    constraints: BinaryCalibrationConstraints = DEFAULT_FEATURE_AUDIT_CONSTRAINTS,
) -> dict[str, Any]:
    normalized, groups = _normalize_samples(samples, expected_binding=expected_binding)
    features: dict[str, dict[str, Any]] = {}
    findings: list[str] = []
    for field in WEIGHTED_FEATURE_FIELDS:
        field_audit = _audit_feature(
            normalized,
            groups=groups,
            field=field,
            dataset_id=dataset_id,
            constraints=constraints,
        )
        features[field] = field_audit
        if field_audit["classification"] != "DIRECTIONAL":
            findings.append(f"{field.upper()}_{field_audit['classification']}")

    correlations = _correlation_matrix(normalized)
    for left_index, left in enumerate(WEIGHTED_FEATURE_FIELDS):
        for right in WEIGHTED_FEATURE_FIELDS[left_index + 1 :]:
            value = correlations[left][right]
            if value is not None and abs(value) >= NEAR_PERFECT_CORRELATION:
                findings.append(f"{left.upper()}_{right.upper()}_CORRELATED")

    result = {
        "feature_audit_schema_version": FEATURE_AUDIT_SCHEMA_VERSION,
        "policy_id": FEATURE_AUDIT_POLICY_ID,
        "status": "AUDITED",
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {
            "dataset_id": _required_string(dataset_id, "dataset_id"),
            "dataset_sha256": _required_string(dataset_sha256, "dataset_sha256"),
            "partition": "CALIBRATION",
            "sample_count": len(normalized),
            "group_count": len(groups),
        },
        "package_semantics": {
            "pair_semantics": PAIR_SEMANTICS,
            "positive_package": "two expected-ready documents in one scoped retrieval",
            "negative_package": "two expected-low-confidence documents in one scoped retrieval",
            "finding_scope": "diagnostic_only",
        },
        "features": features,
        "correlations": correlations,
        "findings": sorted(set(findings)),
    }
    result["audit_hash"] = semantic_sha256_hash_ref(result)
    return result


def _normalize_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    expected_binding: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[bool, dict[str, Any]]]]:
    if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
        raise TypeError("multi-signal feature audit samples are invalid")
    expected = dict(expected_binding)
    normalized: list[dict[str, Any]] = []
    groups: dict[str, dict[bool, dict[str, Any]]] = {}
    seen: set[str] = set()
    expected_weights: dict[str, float] | None = None
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise TypeError("multi-signal feature audit sample is invalid")
        sample_id = _required_string(sample.get("sample_id"), "sample_id")
        if sample_id in seen:
            raise ValueError("multi-signal feature audit sample IDs must be unique")
        seen.add(sample_id)
        expected_ready = sample.get("expected_ready")
        package = sample.get("feature_package")
        if not isinstance(expected_ready, bool) or not isinstance(package, Mapping):
            raise TypeError("multi-signal feature audit sample is invalid")
        raw_weights = package.get("weights")
        if not isinstance(raw_weights, Mapping) or set(raw_weights) != set(
            WEIGHTED_FEATURE_FIELDS
        ):
            raise ValueError("multi-signal feature audit weights are invalid")
        weights = RetrievalConfidenceWeights(**dict(raw_weights))
        validated = reweight_multisignal_feature_package(package, weights=weights)
        if validated.get("binding") != expected:
            raise ValueError("multi-signal feature audit binding does not match")
        features = validated.get("features")
        if not isinstance(features, Mapping) or features.get("status") != "COMPLETE":
            raise ValueError("multi-signal feature audit requires complete packages")
        wire_weights = weights.to_wire()
        if expected_weights is None:
            expected_weights = wire_weights
        elif wire_weights != expected_weights:
            raise ValueError("multi-signal feature audit weights do not match")
        group_id, label = _sample_identity(sample_id)
        if label != expected_ready or expected_ready in groups.setdefault(group_id, {}):
            raise ValueError("multi-signal feature audit pair semantics are invalid")
        row = {
            "sample_id": sample_id,
            "group_id": group_id,
            "expected_ready": expected_ready,
            "features": {
                field: float(features[field]) for field in WEIGHTED_FEATURE_FIELDS
            },
        }
        groups[group_id][expected_ready] = row
        normalized.append(row)
    if not normalized or any(set(pair) != {False, True} for pair in groups.values()):
        raise ValueError(
            "each feature audit group requires positive and negative labels"
        )
    return sorted(normalized, key=lambda row: row["sample_id"]), groups


def _audit_feature(
    samples: Sequence[Mapping[str, Any]],
    *,
    groups: Mapping[str, Mapping[bool, Mapping[str, Any]]],
    field: str,
    dataset_id: str,
    constraints: BinaryCalibrationConstraints,
) -> dict[str, Any]:
    positives = [
        float(sample["features"][field])
        for sample in samples
        if sample["expected_ready"]
    ]
    negatives = [
        float(sample["features"][field])
        for sample in samples
        if not sample["expected_ready"]
    ]
    auc = _auc(positives, negatives)
    all_values = positives + negatives
    near_constant = max(all_values) - min(all_values) <= NEAR_CONSTANT_TOLERANCE
    if near_constant:
        classification = "CONSTANT"
    elif auc < 0.45:
        classification = "INVERTED"
    elif auc <= 0.55:
        classification = "NON_DISCRIMINATIVE"
    else:
        classification = "DIRECTIONAL"
    deltas = [
        float(pair[True]["features"][field]) - float(pair[False]["features"][field])
        for pair in groups.values()
    ]
    evaluation = evaluate_binary_score_calibration(
        [
            {
                "sample_id": str(sample["sample_id"]),
                "expected_ready": bool(sample["expected_ready"]),
                "score": float(sample["features"][field]),
            }
            for sample in samples
        ],
        dataset_id=f"{dataset_id}:feature-audit:{field}",
        constraints=constraints,
    )
    return {
        "classification": classification,
        "higher_is_ready_auc": auc,
        "near_constant": near_constant,
        "positive_distribution": _distribution(positives),
        "negative_distribution": _distribution(negatives),
        "overlap_span": round(
            max(
                0.0,
                min(max(positives), max(negatives))
                - max(min(positives), min(negatives)),
            ),
            8,
        ),
        "paired_delta": {
            **_distribution(deltas),
            "positive_higher_count": sum(delta > 0.0 for delta in deltas),
            "tied_count": sum(
                math.isclose(delta, 0.0, abs_tol=1e-12) for delta in deltas
            ),
            "negative_higher_count": sum(delta < 0.0 for delta in deltas),
        },
        "univariate_threshold": {
            "status": evaluation["status"],
            "selected_threshold": evaluation["selected_threshold"],
            "selected_metrics": evaluation["selected_metrics"],
            "best_effort_metrics": evaluation["best_effort_metrics"],
        },
    }


def _auc(positives: Sequence[float], negatives: Sequence[float]) -> float:
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return round(wins / (len(positives) * len(negatives)), 8)


def _distribution(values: Sequence[float]) -> dict[str, float]:
    return {
        "minimum": round(min(values), 8),
        "maximum": round(max(values), 8),
        "mean": round(statistics.fmean(values), 8),
        "median": round(statistics.median(values), 8),
    }


def _correlation_matrix(
    samples: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float | None]]:
    values = {
        field: [float(sample["features"][field]) for sample in samples]
        for field in WEIGHTED_FEATURE_FIELDS
    }
    return {
        left: {right: _pearson(values[left], values[right]) for right in values}
        for left in values
    }


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_delta)
        * sum(value * value for value in right_delta)
    )
    if denominator <= NEAR_CONSTANT_TOLERANCE:
        return None
    return round(
        sum(a * b for a, b in zip(left_delta, right_delta, strict=True)) / denominator,
        8,
    )


def _sample_identity(sample_id: str) -> tuple[str, bool]:
    group_id, separator, label = sample_id.rpartition(":")
    if not separator or not group_id or label not in {"positive", "negative"}:
        raise ValueError("sample_id must use '<group>:positive|negative'")
    return group_id, label == "positive"


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()
