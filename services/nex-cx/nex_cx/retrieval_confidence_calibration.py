from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from typing import Any


RETRIEVAL_CONFIDENCE_FEATURE_SCHEMA_VERSION = (
    "cx_retrieval_confidence_features.v1"
)
RETRIEVAL_CONFIDENCE_PROFILE_SCHEMA_VERSION = (
    "cx_retrieval_confidence_calibration_profile.v1"
)
RETRIEVAL_CONFIDENCE_POLICY_ID = "cx_retrieval_confidence_multisignal_v1"
SUPPORTED_PROFILE_STATUSES = frozenset({"CANDIDATE", "ACTIVE", "RETIRED"})


class RetrievalConfidenceCalibrationError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class RetrievalConfidenceWeights:
    reranker_score: float = 0.20
    reranker_margin: float = 0.10
    rrf_normalized_score: float = 0.40
    channel_support: float = 0.30

    def __post_init__(self) -> None:
        values = (
            self.reranker_score,
            self.reranker_margin,
            self.rrf_normalized_score,
            self.channel_support,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 1.0
            for value in values
        ) or not math.isclose(sum(values), 1.0, abs_tol=1e-9):
            raise RetrievalConfidenceCalibrationError(
                "cx.retrieval_confidence.weights_invalid",
                "Retrieval confidence weights are invalid.",
            )

    def to_wire(self) -> dict[str, float]:
        return {
            "reranker_score": float(self.reranker_score),
            "reranker_margin": float(self.reranker_margin),
            "rrf_normalized_score": float(self.rrf_normalized_score),
            "channel_support": float(self.channel_support),
        }


DEFAULT_RETRIEVAL_CONFIDENCE_WEIGHTS = RetrievalConfidenceWeights()


def project_retrieval_confidence_features(
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    weights: RetrievalConfidenceWeights = DEFAULT_RETRIEVAL_CONFIDENCE_WEIGHTS,
) -> dict[str, Any]:
    if isinstance(evidence_items, (str, bytes)) or not isinstance(
        evidence_items, Sequence
    ):
        raise _invalid("evidence_items")
    if not evidence_items:
        return {
            "feature_schema_version": RETRIEVAL_CONFIDENCE_FEATURE_SCHEMA_VERSION,
            "candidate_count": 0,
            "reranker_score": 0.0,
            "reranker_margin": 0.0,
            "rrf_normalized_score": 0.0,
            "channel_support": 0.0,
            "composite_score": 0.0,
        }

    normalized: list[dict[str, float | int]] = []
    seen_ranks: set[int] = set()
    for item in evidence_items:
        if not isinstance(item, Mapping):
            raise _invalid("evidence_item")
        rank = item.get("rank")
        scores = item.get("scores")
        if (
            isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank < 1
            or rank in seen_ranks
            or not isinstance(scores, Mapping)
        ):
            raise _invalid("evidence_item")
        seen_ranks.add(rank)
        reranker_score = _optional_bounded_score(scores.get("rerank_score"))
        normalized.append(
            {
                "rank": rank,
                "reranker_score": reranker_score or 0.0,
                "rrf_normalized_score": _bounded_score(
                    scores.get("rrf_normalized_score"),
                    "rrf_normalized_score",
                ),
                "channel_support": _bounded_score(
                    scores.get("channel_support_score"),
                    "channel_support_score",
                ),
            }
        )
    normalized.sort(key=lambda item: int(item["rank"]))
    top = normalized[0]
    reranker_scores = sorted(
        (float(item["reranker_score"]) for item in normalized),
        reverse=True,
    )
    margin = (
        max(0.0, reranker_scores[0] - reranker_scores[1])
        if len(reranker_scores) > 1
        else 0.0
    )
    values = {
        "reranker_score": float(top["reranker_score"]),
        "reranker_margin": round(margin, 8),
        "rrf_normalized_score": float(top["rrf_normalized_score"]),
        "channel_support": float(top["channel_support"]),
    }
    composite = sum(
        values[name] * weight
        for name, weight in weights.to_wire().items()
    )
    return {
        "feature_schema_version": RETRIEVAL_CONFIDENCE_FEATURE_SCHEMA_VERSION,
        "candidate_count": len(normalized),
        **values,
        "composite_score": round(composite, 8),
    }


def build_retrieval_confidence_profile(
    *,
    profile_id: str,
    version: str,
    status: str,
    embedding_model_revision: str,
    reranker_model_revision: str,
    ranking_policy_id: str,
    weights: RetrievalConfidenceWeights,
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_status = _required_string(status, "status").upper()
    if normalized_status not in SUPPORTED_PROFILE_STATUSES:
        raise _invalid("status")
    if (
        evaluation.get("evaluation_schema_version")
        != "model_calibration_evaluation.v1"
        or evaluation.get("status") != "PASSED"
    ):
        raise RetrievalConfidenceCalibrationError(
            "cx.retrieval_confidence.evaluation_not_passed",
            "A retrieval confidence profile requires a passed evaluation.",
        )
    threshold = _bounded_score(
        evaluation.get("selected_threshold"),
        "selected_threshold",
    )
    profile = {
        "profile_schema_version": RETRIEVAL_CONFIDENCE_PROFILE_SCHEMA_VERSION,
        "profile_id": _required_string(profile_id, "profile_id"),
        "version": _required_string(version, "version"),
        "status": normalized_status,
        "policy_id": RETRIEVAL_CONFIDENCE_POLICY_ID,
        "binding": {
            "embedding_model_revision": _required_string(
                embedding_model_revision,
                "embedding_model_revision",
            ),
            "reranker_model_revision": _required_string(
                reranker_model_revision,
                "reranker_model_revision",
            ),
            "ranking_policy_id": _required_string(
                ranking_policy_id,
                "ranking_policy_id",
            ),
            "feature_schema_version": RETRIEVAL_CONFIDENCE_FEATURE_SCHEMA_VERSION,
        },
        "weights": weights.to_wire(),
        "threshold": threshold,
        "evaluation": json.loads(json.dumps(evaluation, sort_keys=True)),
    }
    profile["profile_hash"] = _sha256_json(profile)
    return profile


def select_retrieval_confidence_profile(
    profiles: Sequence[Mapping[str, Any]],
    *,
    embedding_model_revision: object,
    reranker_model_revision: object,
    ranking_policy_id: object,
) -> dict[str, Any] | None:
    if not all(
        isinstance(value, str) and bool(value.strip())
        for value in (
            embedding_model_revision,
            reranker_model_revision,
            ranking_policy_id,
        )
    ):
        return None
    expected = {
        "embedding_model_revision": str(embedding_model_revision).strip(),
        "reranker_model_revision": str(reranker_model_revision).strip(),
        "ranking_policy_id": str(ranking_policy_id).strip(),
        "feature_schema_version": RETRIEVAL_CONFIDENCE_FEATURE_SCHEMA_VERSION,
    }
    matches = [
        profile
        for profile in profiles
        if profile.get("profile_schema_version")
        == RETRIEVAL_CONFIDENCE_PROFILE_SCHEMA_VERSION
        and profile.get("status") == "ACTIVE"
        and profile.get("policy_id") == RETRIEVAL_CONFIDENCE_POLICY_ID
        and dict(_mapping(profile.get("binding"))) == expected
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise RetrievalConfidenceCalibrationError(
            "cx.retrieval_confidence.active_profile_ambiguous",
            "Exactly one active retrieval confidence profile may match.",
        )
    _validate_profile_integrity(matches[0])
    return json.loads(json.dumps(matches[0], sort_keys=True))


def decide_retrieval_confidence(
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    profiles: Sequence[Mapping[str, Any]],
    embedding_model_revision: object,
    reranker_model_revision: object,
    ranking_policy_id: object,
) -> dict[str, Any]:
    if not evidence_items:
        return _decision(
            status="NO_ANSWER",
            reason="no_permission_admitted_candidates",
            features=project_retrieval_confidence_features([]),
            profile=None,
        )
    profile = select_retrieval_confidence_profile(
        profiles,
        embedding_model_revision=embedding_model_revision,
        reranker_model_revision=reranker_model_revision,
        ranking_policy_id=ranking_policy_id,
    )
    if profile is None:
        return _decision(
            status="LOW_CONFIDENCE",
            reason="active_calibration_profile_missing",
            features=None,
            profile=None,
            evidence_count=len(evidence_items),
        )
    weights = _weights_from_profile(profile)
    features = project_retrieval_confidence_features(
        evidence_items,
        weights=weights,
    )
    threshold = float(profile["threshold"])
    ready = float(features["composite_score"]) >= threshold
    return _decision(
        status="READY" if ready else "LOW_CONFIDENCE",
        reason=None if ready else "composite_score_below_calibrated_threshold",
        features=features,
        profile=profile,
    )


def _decision(
    *,
    status: str,
    reason: str | None,
    features: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    evidence_count: int | None = None,
) -> dict[str, Any]:
    return {
        "policy_id": RETRIEVAL_CONFIDENCE_POLICY_ID,
        "status": status,
        "reason": reason,
        "best_score": (
            float(features["composite_score"])
            if features is not None
            else 0.0
        ),
        "low_confidence_threshold": (
            float(profile["threshold"]) if profile is not None else None
        ),
        "threshold_inclusive": True,
        "evidence_count": (
            int(features["candidate_count"])
            if features is not None
            else int(evidence_count or 0)
        ),
        "feature_schema_version": RETRIEVAL_CONFIDENCE_FEATURE_SCHEMA_VERSION,
        "features": dict(features) if features is not None else None,
        "calibration_profile_id": (
            profile.get("profile_id") if profile is not None else None
        ),
        "calibration_profile_hash": (
            profile.get("profile_hash") if profile is not None else None
        ),
    }


def _weights_from_profile(
    profile: Mapping[str, Any],
) -> RetrievalConfidenceWeights:
    values = _mapping(profile.get("weights"))
    return RetrievalConfidenceWeights(
        reranker_score=values.get("reranker_score"),  # type: ignore[arg-type]
        reranker_margin=values.get("reranker_margin"),  # type: ignore[arg-type]
        rrf_normalized_score=values.get(  # type: ignore[arg-type]
            "rrf_normalized_score"
        ),
        channel_support=values.get("channel_support"),  # type: ignore[arg-type]
    )


def _validate_profile_integrity(profile: Mapping[str, Any]) -> None:
    threshold = _bounded_score(profile.get("threshold"), "threshold")
    evaluation = _mapping(profile.get("evaluation"))
    selected = _bounded_score(
        evaluation.get("selected_threshold"),
        "evaluation.selected_threshold",
    )
    if evaluation.get("status") != "PASSED" or threshold != selected:
        raise RetrievalConfidenceCalibrationError(
            "cx.retrieval_confidence.threshold_mismatch",
            "Profile threshold does not match a passed evaluation.",
        )
    _weights_from_profile(profile)
    profile_hash = _required_string(profile.get("profile_hash"), "profile_hash")
    unsigned = dict(profile)
    unsigned.pop("profile_hash", None)
    if not hmac.compare_digest(profile_hash, _sha256_json(unsigned)):
        raise RetrievalConfidenceCalibrationError(
            "cx.retrieval_confidence.profile_integrity_invalid",
            "Retrieval confidence profile integrity validation failed.",
        )


def _optional_bounded_score(value: object) -> float | None:
    if value is None:
        return None
    return _bounded_score(value, "reranker_score")


def _bounded_score(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(field_name)
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise _invalid(field_name)
    return numeric


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field_name)
    return value.strip()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _invalid(field_name: str) -> RetrievalConfidenceCalibrationError:
    return RetrievalConfidenceCalibrationError(
        "cx.retrieval_confidence.field_invalid",
        f"{field_name} is invalid.",
    )
