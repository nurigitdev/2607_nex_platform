from __future__ import annotations

import hmac
import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

from nex_runtime.model_artifact_revision import (
    ModelArtifactRevisionError,
    normalize_immutable_model_revision,
)
from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_calibration,
)
from nex_runtime.semantic_hashes import (
    semantic_sha256_hash_ref,
    validate_sha256_digest,
)

from nex_cx.retrieval_confidence_calibration import (
    DEFAULT_RETRIEVAL_CONFIDENCE_WEIGHTS,
    RetrievalConfidenceWeights,
)

MULTISIGNAL_FEATURE_SCHEMA_VERSION = "cx_retrieval_confidence_features.v2"
MULTISIGNAL_FEATURE_PACKAGE_SCHEMA_VERSION = (
    "cx_retrieval_confidence_feature_package.v2"
)
MULTISIGNAL_EVALUATION_SCHEMA_VERSION = (
    "cx_retrieval_confidence_multisignal_evaluation.v1"
)
MULTISIGNAL_DECISION_SCHEMA_VERSION = "cx_retrieval_confidence_multisignal_decision.v1"
MULTISIGNAL_POLICY_ID = "cx_retrieval_confidence_multisignal_v2"
DEFAULT_MULTISIGNAL_CALIBRATION_CONSTRAINTS = BinaryCalibrationConstraints()

REQUIRED_BINDING_FIELDS = (
    "embedding_model_revision",
    "reranker_model_revision",
    "ranking_policy_id",
    "tokenizer_policy_id",
    "chunk_policy_id",
)
WEIGHTED_FEATURE_FIELDS = (
    "reranker_score",
    "reranker_margin",
    "rrf_normalized_score",
    "channel_support",
)
ALLOWED_SCORE_FIELDS = frozenset(
    {
        "bm25_score",
        "vector_score",
        "bm25_rank",
        "vector_rank",
        "rrf_score",
        "rrf_normalized_score",
        "channel_support_score",
        "rerank_score",
        "final_score",
    }
)
FORBIDDEN_RELEVANCE_KEY_PARTS = frozenset(
    {
        "tenant",
        "owner",
        "permission",
        "authorization",
        "subject",
        "actor",
        "principal",
        "acl",
        "role",
    }
)
FEATURE_FIELDS = frozenset(
    {
        "feature_schema_version",
        "status",
        "reason_codes",
        "candidate_count",
        *WEIGHTED_FEATURE_FIELDS,
        "composite_score",
        "diagnostics",
        "weighted_feature_fields",
    }
)


class MultiSignalCalibrationError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def build_multisignal_feature_package(
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    binding: Mapping[str, Any],
    weights: RetrievalConfidenceWeights = DEFAULT_RETRIEVAL_CONFIDENCE_WEIGHTS,
) -> dict[str, Any]:
    normalized_binding = _binding(binding)
    features = _project_features(evidence_items, weights=weights)
    package = {
        "feature_package_schema_version": (MULTISIGNAL_FEATURE_PACKAGE_SCHEMA_VERSION),
        "policy_id": MULTISIGNAL_POLICY_ID,
        "binding": normalized_binding,
        "weights": weights.to_wire(),
        "features": features,
        "permission_signals_used": False,
        "ownership_signals_used": False,
    }
    package["feature_package_hash"] = semantic_sha256_hash_ref(package)
    return package


def decide_multisignal_confidence(
    feature_package: Mapping[str, Any],
    *,
    expected_binding: Mapping[str, Any],
    threshold: object,
) -> dict[str, Any]:
    expected = _binding(expected_binding)
    numeric_threshold = _bounded_score(threshold, "threshold")
    package = _validated_package(feature_package)
    features = package["features"]
    if package["binding"] != expected:
        return _decision(
            status="LOW_CONFIDENCE",
            reason_code="MODEL_OR_POLICY_BINDING_MISMATCH",
            features=features,
            threshold=numeric_threshold,
            package=package,
        )
    if features["status"] != "COMPLETE":
        status = (
            "NO_ANSWER"
            if "NO_ADMITTED_CANDIDATES" in features["reason_codes"]
            else "LOW_CONFIDENCE"
        )
        return _decision(
            status=status,
            reason_code=features["reason_codes"][0],
            features=features,
            threshold=numeric_threshold,
            package=package,
        )
    ready = float(features["composite_score"]) >= numeric_threshold
    return _decision(
        status="READY" if ready else "LOW_CONFIDENCE",
        reason_code=(
            "COMPOSITE_SCORE_AT_OR_ABOVE_THRESHOLD"
            if ready
            else "COMPOSITE_SCORE_BELOW_THRESHOLD"
        ),
        features=features,
        threshold=numeric_threshold,
        package=package,
    )


def evaluate_multisignal_calibration(
    samples: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    expected_binding: Mapping[str, Any],
    constraints: BinaryCalibrationConstraints = (
        DEFAULT_MULTISIGNAL_CALIBRATION_CONSTRAINTS
    ),
) -> dict[str, Any]:
    if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
        raise _invalid("samples")
    binding = _binding(expected_binding)
    normalized: list[dict[str, Any]] = []
    seen_sample_ids: set[str] = set()
    package_hashes: list[str] = []
    expected_weights: dict[str, float] | None = None
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise _invalid("sample")
        sample_id = _required_string(sample.get("sample_id"), "sample_id")
        if sample_id in seen_sample_ids:
            raise MultiSignalCalibrationError(
                "cx.retrieval_confidence.sample_replay",
                "Calibration sample IDs must not be replayed.",
            )
        seen_sample_ids.add(sample_id)
        expected_ready = sample.get("expected_ready")
        if not isinstance(expected_ready, bool):
            raise _invalid("expected_ready")
        package = _validated_package(_mapping(sample.get("feature_package")))
        if package["binding"] != binding:
            raise MultiSignalCalibrationError(
                "cx.retrieval_confidence.binding_mismatch",
                "Calibration sample model or policy binding does not match.",
            )
        features = package["features"]
        if features["status"] != "COMPLETE":
            raise MultiSignalCalibrationError(
                "cx.retrieval_confidence.required_signal_missing",
                "Calibration samples require a complete multi-signal package.",
            )
        weights = package["weights"]
        if expected_weights is None:
            expected_weights = weights
        elif weights != expected_weights:
            raise MultiSignalCalibrationError(
                "cx.retrieval_confidence.weights_mismatch",
                "All calibration samples must use the same feature weights.",
            )
        package_hashes.append(package["feature_package_hash"])
        normalized.append(
            {
                "sample_id": sample_id,
                "expected_ready": expected_ready,
                "score": features["composite_score"],
            }
        )

    dataset_digest = _dataset_digest(dataset_sha256)
    evaluation = evaluate_binary_score_calibration(
        normalized,
        dataset_id=_required_string(dataset_id, "dataset_id"),
        constraints=constraints,
    )
    reason_code = {
        "PASSED": "CALIBRATED_THRESHOLD_SELECTED",
        "NO_ACCEPTABLE_THRESHOLD": "NO_ACCEPTABLE_THRESHOLD",
        "INSUFFICIENT_SAMPLES": "INSUFFICIENT_CALIBRATION_SAMPLES",
    }.get(str(evaluation.get("status")), "CALIBRATION_EVALUATION_INVALID")
    result = {
        "multisignal_evaluation_schema_version": (
            MULTISIGNAL_EVALUATION_SCHEMA_VERSION
        ),
        "policy_id": MULTISIGNAL_POLICY_ID,
        "status": evaluation["status"],
        "reason_code": reason_code,
        "runtime_activation_permitted": False,
        "binding": binding,
        "weights": expected_weights,
        "feature_schema_version": MULTISIGNAL_FEATURE_SCHEMA_VERSION,
        "dataset": {
            "dataset_id": _required_string(dataset_id, "dataset_id"),
            "dataset_sha256": dataset_digest,
            "partition": "CALIBRATION",
        },
        "feature_package_count": len(package_hashes),
        "feature_package_set_hash": semantic_sha256_hash_ref(sorted(package_hashes)),
        "evaluation": evaluation,
    }
    result["evaluation_hash"] = semantic_sha256_hash_ref(result)
    return result


def _project_features(
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    weights: RetrievalConfidenceWeights,
) -> dict[str, Any]:
    if isinstance(evidence_items, (str, bytes)) or not isinstance(
        evidence_items, Sequence
    ):
        raise _invalid("evidence_items")
    if not evidence_items:
        return _incomplete_features(
            candidate_count=0,
            reason_codes=("NO_ADMITTED_CANDIDATES",),
        )

    candidates: list[dict[str, Any]] = []
    seen_ranks: set[int] = set()
    missing: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, Mapping):
            raise _invalid("evidence_item")
        _reject_forbidden_relevance_keys(item)
        if set(item) != {"rank", "scores"}:
            raise _invalid("evidence_item.fields")
        rank = _positive_rank(item.get("rank"), "rank")
        if rank in seen_ranks:
            raise _invalid("rank")
        seen_ranks.add(rank)
        raw_scores = item.get("scores")
        if not isinstance(raw_scores, Mapping):
            raise _invalid("scores")
        if not set(raw_scores).issubset(ALLOWED_SCORE_FIELDS):
            raise _invalid("scores.fields")
        scores = _scores(raw_scores, missing=missing)
        if scores["bm25_rank"] is None and scores["vector_rank"] is None:
            missing.add("RETRIEVAL_CHANNEL_RANK_MISSING")
        candidates.append({"rank": rank, **scores})

    candidates.sort(key=lambda candidate: candidate["rank"])
    if [candidate["rank"] for candidate in candidates] != list(
        range(1, len(candidates) + 1)
    ):
        raise MultiSignalCalibrationError(
            "cx.retrieval_confidence.rank_sequence_invalid",
            "Candidate ranks must form a contiguous sequence.",
        )
    if len(candidates) < 2:
        missing.add("RERANKER_MARGIN_UNAVAILABLE")
    reranker_scores = [candidate["reranker_score"] for candidate in candidates]
    if all(score is not None for score in reranker_scores) and any(
        float(left) < float(right) for left, right in pairwise(reranker_scores)
    ):
        raise MultiSignalCalibrationError(
            "cx.retrieval_confidence.reranker_order_invalid",
            "Candidate order does not match descending reranker scores.",
        )
    if missing:
        return _incomplete_features(
            candidate_count=len(candidates),
            reason_codes=tuple(sorted(missing)),
        )

    top = candidates[0]
    margin = float(top["reranker_score"]) - float(candidates[1]["reranker_score"])
    weighted_values = {
        "reranker_score": float(top["reranker_score"]),
        "reranker_margin": round(max(0.0, margin), 8),
        "rrf_normalized_score": float(top["rrf_normalized_score"]),
        "channel_support": float(top["channel_support"]),
    }
    composite = sum(
        weighted_values[field] * weights.to_wire()[field]
        for field in WEIGHTED_FEATURE_FIELDS
    )
    return {
        "feature_schema_version": MULTISIGNAL_FEATURE_SCHEMA_VERSION,
        "status": "COMPLETE",
        "reason_codes": [],
        "candidate_count": len(candidates),
        **weighted_values,
        "composite_score": round(composite, 8),
        "diagnostics": _diagnostics(candidates),
        "weighted_feature_fields": list(WEIGHTED_FEATURE_FIELDS),
    }


def _scores(
    values: Mapping[str, Any],
    *,
    missing: set[str],
) -> dict[str, Any]:
    required = {
        "reranker_score": ("rerank_score", "RERANKER_SCORE_MISSING"),
        "rrf_normalized_score": (
            "rrf_normalized_score",
            "RRF_NORMALIZED_SCORE_MISSING",
        ),
        "channel_support": (
            "channel_support_score",
            "CHANNEL_SUPPORT_SCORE_MISSING",
        ),
    }
    normalized: dict[str, Any] = {}
    for target, (source, reason) in required.items():
        value = values.get(source)
        if value is None:
            missing.add(reason)
            normalized[target] = None
        else:
            normalized[target] = _bounded_score(value, source)
    normalized["bm25_rank"] = _optional_rank(values.get("bm25_rank"), "bm25_rank")
    normalized["vector_rank"] = _optional_rank(values.get("vector_rank"), "vector_rank")
    for field in ("bm25_score", "vector_score", "rrf_score", "final_score"):
        _optional_finite_number(values.get(field), field)
    return normalized


def _diagnostics(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(candidates)
    lexical_count = sum(candidate["bm25_rank"] is not None for candidate in candidates)
    vector_count = sum(candidate["vector_rank"] is not None for candidate in candidates)
    rrf_order = sorted(
        candidates,
        key=lambda candidate: (
            -float(candidate["rrf_normalized_score"]),
            int(candidate["rank"]),
        ),
    )
    rrf_positions = {
        int(candidate["rank"]): index
        for index, candidate in enumerate(rrf_order, start=1)
    }
    pair_count = count * (count - 1) // 2
    concordant = sum(
        rrf_positions[left] < rrf_positions[right]
        for left in range(1, count + 1)
        for right in range(left + 1, count + 1)
    )
    return {
        "reranker_rrf_order_agreement": round(concordant / pair_count, 8),
        "lexical_channel_candidate_ratio": round(lexical_count / count, 8),
        "vector_channel_candidate_ratio": round(vector_count / count, 8),
        "admitted_candidate_count": count,
        "diagnostics_used_in_composite": False,
    }


def _incomplete_features(
    *,
    candidate_count: int,
    reason_codes: Sequence[str],
) -> dict[str, Any]:
    return {
        "feature_schema_version": MULTISIGNAL_FEATURE_SCHEMA_VERSION,
        "status": "INCOMPLETE",
        "reason_codes": list(reason_codes),
        "candidate_count": candidate_count,
        "reranker_score": None,
        "reranker_margin": None,
        "rrf_normalized_score": None,
        "channel_support": None,
        "composite_score": None,
        "diagnostics": None,
        "weighted_feature_fields": list(WEIGHTED_FEATURE_FIELDS),
    }


def _validated_package(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("feature_package")
    package = dict(value)
    package_hash = _required_string(
        package.get("feature_package_hash"), "feature_package_hash"
    )
    unsigned = dict(package)
    unsigned.pop("feature_package_hash", None)
    if not hmac.compare_digest(package_hash, semantic_sha256_hash_ref(unsigned)):
        raise MultiSignalCalibrationError(
            "cx.retrieval_confidence.feature_package_integrity_invalid",
            "Multi-signal feature package integrity validation failed.",
        )
    if (
        package.get("feature_package_schema_version")
        != MULTISIGNAL_FEATURE_PACKAGE_SCHEMA_VERSION
        or package.get("policy_id") != MULTISIGNAL_POLICY_ID
        or package.get("permission_signals_used") is not False
        or package.get("ownership_signals_used") is not False
    ):
        raise _invalid("feature_package.contract")
    binding = _binding(_mapping(package.get("binding")))
    weights = _weights(_mapping(package.get("weights")))
    features = _mapping(package.get("features"))
    _reject_forbidden_relevance_keys(features)
    if set(features) != FEATURE_FIELDS:
        raise _invalid("features.fields")
    if features.get("feature_schema_version") != MULTISIGNAL_FEATURE_SCHEMA_VERSION:
        raise _invalid("features.feature_schema_version")
    if features.get("status") not in {"COMPLETE", "INCOMPLETE"}:
        raise _invalid("features.status")
    candidate_count = features.get("candidate_count")
    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count < 0
    ):
        raise _invalid("features.candidate_count")
    if features["status"] == "COMPLETE":
        if candidate_count < 2 or features.get("reason_codes") != []:
            raise _invalid("features.complete")
        for field in (*WEIGHTED_FEATURE_FIELDS, "composite_score"):
            _bounded_score(features.get(field), f"features.{field}")
        if features.get("weighted_feature_fields") != list(WEIGHTED_FEATURE_FIELDS):
            raise _invalid("features.weighted_feature_fields")
        expected_composite = round(
            sum(
                float(features[field]) * weights.to_wire()[field]
                for field in WEIGHTED_FEATURE_FIELDS
            ),
            8,
        )
        if not math.isclose(
            float(features["composite_score"]),
            expected_composite,
            abs_tol=1e-9,
        ):
            raise MultiSignalCalibrationError(
                "cx.retrieval_confidence.composite_score_invalid",
                "Composite score does not match the bound feature weights.",
            )
    else:
        reasons = features.get("reason_codes")
        if (
            not isinstance(reasons, list)
            or not reasons
            or any(not isinstance(reason, str) or not reason for reason in reasons)
        ):
            raise _invalid("features.reason_codes")
        if features.get("composite_score") is not None:
            raise _invalid("features.composite_score")
    return {
        **package,
        "binding": binding,
        "weights": weights.to_wire(),
        "features": dict(features),
    }


def _decision(
    *,
    status: str,
    reason_code: str,
    features: Mapping[str, Any],
    threshold: float,
    package: Mapping[str, Any],
) -> dict[str, Any]:
    decision = {
        "decision_schema_version": MULTISIGNAL_DECISION_SCHEMA_VERSION,
        "policy_id": MULTISIGNAL_POLICY_ID,
        "status": status,
        "reason_code": reason_code,
        "score": features.get("composite_score"),
        "threshold": threshold,
        "threshold_inclusive": True,
        "feature_package_hash": package["feature_package_hash"],
        "binding": package["binding"],
        "feature_status": features["status"],
        "missing_signal_reasons": list(features["reason_codes"]),
    }
    decision["decision_hash"] = semantic_sha256_hash_ref(decision)
    return decision


def _binding(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(REQUIRED_BINDING_FIELDS):
        raise _invalid("binding")
    normalized = {
        field: _required_string(value.get(field), f"binding.{field}")
        for field in REQUIRED_BINDING_FIELDS
    }
    try:
        normalized["reranker_model_revision"] = normalize_immutable_model_revision(
            normalized["reranker_model_revision"]
        )
    except ModelArtifactRevisionError as exc:
        raise MultiSignalCalibrationError(
            "cx.retrieval_confidence.reranker_revision_mutable",
            "Reranker revision binding must be immutable.",
        ) from exc
    return normalized


def _weights(value: Mapping[str, Any]) -> RetrievalConfidenceWeights:
    if set(value) != set(WEIGHTED_FEATURE_FIELDS):
        raise _invalid("weights")
    return RetrievalConfidenceWeights(
        reranker_score=value.get("reranker_score"),  # type: ignore[arg-type]
        reranker_margin=value.get("reranker_margin"),  # type: ignore[arg-type]
        rrf_normalized_score=value.get(  # type: ignore[arg-type]
            "rrf_normalized_score"
        ),
        channel_support=value.get("channel_support"),  # type: ignore[arg-type]
    )


def _reject_forbidden_relevance_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid("feature_key")
            normalized = key.lower().replace("-", "_")
            if any(part in normalized for part in FORBIDDEN_RELEVANCE_KEY_PARTS):
                raise MultiSignalCalibrationError(
                    "cx.retrieval_confidence.forbidden_relevance_signal",
                    "Permission and ownership data cannot become relevance features.",
                )
            _reject_forbidden_relevance_keys(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _reject_forbidden_relevance_keys(item)


def _positive_rank(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field)
    return value


def _optional_rank(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_rank(value, field)


def _optional_finite_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(field)
    numeric = float(value)
    if not math.isfinite(numeric):
        raise _invalid(field)
    return numeric


def _bounded_score(value: object, field: str) -> float:
    numeric = _optional_finite_number(value, field)
    if numeric is None or not 0.0 <= numeric <= 1.0:
        raise _invalid(field)
    return numeric


def _dataset_digest(value: object) -> str:
    try:
        return validate_sha256_digest(value)
    except ValueError as exc:
        raise _invalid("dataset_sha256") from exc


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field)
    return value.strip()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _invalid(field: str) -> MultiSignalCalibrationError:
    return MultiSignalCalibrationError(
        "cx.retrieval_confidence.field_invalid",
        f"{field} is invalid.",
    )
