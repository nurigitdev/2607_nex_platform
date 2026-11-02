from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.model_calibration_package_dataset import (
    CANDIDATE_ROLE_EXPECTED_RELEVANT,
    LOW_CONFIDENCE_CANDIDATE_ROLES,
    READY_CANDIDATE_ROLES,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_confidence_calibration import (
    DEFAULT_RETRIEVAL_CONFIDENCE_WEIGHTS,
    RetrievalConfidenceWeights,
)
from nex_cx.retrieval_confidence_multisignal import (
    build_multisignal_feature_package,
)

MIXED_CANDIDATE_SAMPLE_SCHEMA_VERSION = (
    "cx_retrieval_confidence_mixed_candidate_sample.v1"
)
MIXED_CANDIDATE_SEMANTICS_ID = "cx_mixed_candidate_package_confidence_v1"


def build_mixed_candidate_calibration_sample(
    case: Mapping[str, Any],
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    binding: Mapping[str, Any],
    weights: RetrievalConfidenceWeights = DEFAULT_RETRIEVAL_CONFIDENCE_WEIGHTS,
) -> dict[str, Any]:
    normalized_case = _case(case)
    numeric_evidence = _evidence(
        evidence_items,
        expected_candidate_ids={
            candidate["candidate_id"] for candidate in normalized_case["candidates"]
        },
    )
    expected_ready = bool(normalized_case["expected_ready"])
    label = "positive" if expected_ready else "negative"
    candidate_ids = sorted(
        candidate["candidate_id"] for candidate in normalized_case["candidates"]
    )
    sample = {
        "sample_schema_version": MIXED_CANDIDATE_SAMPLE_SCHEMA_VERSION,
        "package_semantics_id": MIXED_CANDIDATE_SEMANTICS_ID,
        "sample_id": f"{normalized_case['scenario_id']}:{label}",
        "case_id": normalized_case["case_id"],
        "expected_ready": expected_ready,
        "retrieval_scope": {
            "candidate_count": len(candidate_ids),
            "candidate_set_hash": semantic_sha256_hash_ref(candidate_ids),
            "single_mixed_candidate_retrieval": True,
            "label_filtered_retrieval": False,
        },
        "feature_package": build_multisignal_feature_package(
            numeric_evidence,
            binding=binding,
            weights=weights,
        ),
    }
    sample["sample_hash"] = semantic_sha256_hash_ref(sample)
    return sample


def _case(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("mixed-candidate calibration case is invalid")
    scenario_id = _required_string(value.get("scenario_id"), "scenario_id")
    case_id = _required_string(value.get("case_id"), "case_id")
    expected_ready = value.get("expected_ready")
    candidates = value.get("candidates")
    if type(expected_ready) is not bool or not _is_sequence(candidates):
        raise TypeError("mixed-candidate calibration case is invalid")
    if len(candidates) != 4:
        raise ValueError("mixed-candidate calibration case requires four candidates")
    normalized_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TypeError("mixed-candidate calibration candidate is invalid")
        candidate_id = _required_string(candidate.get("candidate_id"), "candidate_id")
        role = _required_string(candidate.get("evidence_role"), "evidence_role").upper()
        expected_relevant = candidate.get("expected_relevant")
        if (
            role not in CANDIDATE_ROLE_EXPECTED_RELEVANT
            or type(expected_relevant) is not bool
            or expected_relevant is not CANDIDATE_ROLE_EXPECTED_RELEVANT[role]
        ):
            raise ValueError("mixed-candidate calibration relevance role is invalid")
        normalized_candidates.append(
            {
                "candidate_id": candidate_id,
                "evidence_role": role,
                "expected_relevant": expected_relevant,
            }
        )
    candidate_ids = [candidate["candidate_id"] for candidate in normalized_candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("mixed-candidate calibration candidate IDs must be unique")
    roles = {candidate["evidence_role"] for candidate in normalized_candidates}
    expected_roles = (
        READY_CANDIDATE_ROLES if expected_ready else LOW_CONFIDENCE_CANDIDATE_ROLES
    )
    if roles != expected_roles:
        raise ValueError("mixed-candidate calibration roles do not match package label")
    expected_case_id = (
        f"{scenario_id}-ready" if expected_ready else f"{scenario_id}-low-confidence"
    )
    if case_id != expected_case_id:
        raise ValueError("mixed-candidate calibration case identity is invalid")
    return {
        "scenario_id": scenario_id,
        "case_id": case_id,
        "expected_ready": expected_ready,
        "candidates": normalized_candidates,
    }


def _evidence(
    value: Sequence[Mapping[str, Any]],
    *,
    expected_candidate_ids: set[str],
) -> list[dict[str, Any]]:
    if not _is_sequence(value) or len(value) != 4:
        raise ValueError("mixed-candidate calibration evidence requires four items")
    normalized: list[dict[str, Any]] = []
    candidate_ids: list[str] = []
    ranks: list[int] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("mixed-candidate calibration evidence item is invalid")
        candidate_id = _required_string(item.get("candidate_id"), "candidate_id")
        rank = item.get("rank")
        scores = item.get("scores")
        if (
            isinstance(rank, bool)
            or not isinstance(rank, int)
            or not isinstance(scores, Mapping)
        ):
            raise TypeError("mixed-candidate calibration evidence item is invalid")
        candidate_ids.append(candidate_id)
        ranks.append(rank)
        normalized.append({"rank": rank, "scores": dict(scores)})
    if set(candidate_ids) != expected_candidate_ids or len(candidate_ids) != len(
        set(candidate_ids)
    ):
        raise ValueError("mixed-candidate calibration evidence scope is incomplete")
    if sorted(ranks) != [1, 2, 3, 4]:
        raise ValueError("mixed-candidate calibration evidence ranks are invalid")
    return normalized


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()
