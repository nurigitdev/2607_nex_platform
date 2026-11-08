from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_cx.retrieval_confidence_candidate_diagnostics import (
    CANDIDATE_OBSERVATION_SCHEMA_VERSION,
)
from nex_cx.vector_score_policy import (
    VECTOR_SIMILARITY_NUMERIC_EQUIVALENCE_DELTA,
)

PIPELINE_REPEATABILITY_SCHEMA_VERSION = "cx_retrieval_pipeline_repeatability.v2"
PIPELINE_REPEATABILITY_POLICY_ID = (
    "cx_uncertainty_aware_full_retrieval_pipeline_repeatability_v2"
)


def analyze_retrieval_pipeline_repeatability(
    runs: Sequence[Mapping[str, Any]],
    *,
    expected_repeat_count: int = 5,
    expected_package_count: int = 40,
    expected_candidates_per_package: int = 4,
    reranker_score_tolerance: float = 0.0005,
    rrf_score_tolerance: float = 1e-8,
    bm25_score_tolerance: float = 1e-8,
    vector_similarity_tolerance: float = (
        VECTOR_SIMILARITY_NUMERIC_EQUIVALENCE_DELTA
    ),
) -> dict[str, Any]:
    """Compare repeated full-pipeline observations from one immutable corpus."""
    _validate_tolerances(
        reranker_score_tolerance,
        rrf_score_tolerance,
        bm25_score_tolerance,
        vector_similarity_tolerance,
    )
    normalized = _normalize_runs(
        runs,
        expected_repeat_count=expected_repeat_count,
        expected_package_count=expected_package_count,
        expected_candidates_per_package=expected_candidates_per_package,
    )
    baseline = normalized[0]
    stage_counts = {
        "candidate_membership_change_count": 0,
        "bm25_rank_change_count": 0,
        "vector_rank_change_count": 0,
        "rrf_score_drift_count": 0,
        "bm25_score_quality_drift_count": 0,
        "vector_similarity_quality_drift_count": 0,
        "reranker_score_drift_count": 0,
        "final_rank_change_count": 0,
    }
    uncertainty_counts = {
        "bounded_vector_rank_exchange_count": 0,
        "unbounded_vector_rank_change_count": 0,
        "bounded_rrf_score_drift_count": 0,
        "unbounded_rrf_score_drift_count": 0,
    }
    max_rrf_delta = 0.0
    max_bm25_score_quality_delta = 0.0
    max_vector_similarity_quality_delta = 0.0
    max_reranker_delta = 0.0
    for current in normalized[1:]:
        baseline_packages = _package_membership(baseline)
        current_packages = _package_membership(current)
        membership_stable = baseline_packages == current_packages
        for sample_id in sorted(set(baseline_packages) | set(current_packages)):
            if baseline_packages.get(sample_id) != current_packages.get(sample_id):
                stage_counts["candidate_membership_change_count"] += 1
        for identity in sorted(set(baseline) & set(current)):
            before = baseline[identity]
            after = current[identity]
            before_signals = _mapping(before["signals"])
            after_signals = _mapping(after["signals"])
            if before_signals.get("bm25_rank") != after_signals.get("bm25_rank"):
                stage_counts["bm25_rank_change_count"] += 1
            vector_rank_changed = (
                before_signals.get("vector_rank")
                != after_signals.get("vector_rank")
            )
            bm25_rank_changed = (
                before_signals.get("bm25_rank") != after_signals.get("bm25_rank")
            )
            final_rank_changed = before["rank"] != after["rank"]
            if vector_rank_changed:
                stage_counts["vector_rank_change_count"] += 1
            rrf_delta = abs(
                float(before_signals["rrf_normalized_score"])
                - float(after_signals["rrf_normalized_score"])
            )
            reranker_delta = abs(
                float(before_signals["reranker_score"])
                - float(after_signals["reranker_score"])
            )
            bm25_score_quality_delta = abs(
                float(before_signals["bm25_score_quality"])
                - float(after_signals["bm25_score_quality"])
            )
            vector_similarity_quality_delta = abs(
                float(before_signals["vector_similarity_quality"])
                - float(after_signals["vector_similarity_quality"])
            )
            max_rrf_delta = max(max_rrf_delta, rrf_delta)
            max_bm25_score_quality_delta = max(
                max_bm25_score_quality_delta,
                bm25_score_quality_delta,
            )
            max_vector_similarity_quality_delta = max(
                max_vector_similarity_quality_delta,
                vector_similarity_quality_delta,
            )
            max_reranker_delta = max(max_reranker_delta, reranker_delta)
            bounded_numeric_exchange = (
                membership_stable
                and vector_rank_changed
                and not bm25_rank_changed
                and not final_rank_changed
                and bm25_score_quality_delta <= bm25_score_tolerance
                and vector_similarity_quality_delta
                <= vector_similarity_tolerance
                and reranker_delta <= reranker_score_tolerance
            )
            if vector_rank_changed:
                field = (
                    "bounded_vector_rank_exchange_count"
                    if bounded_numeric_exchange
                    else "unbounded_vector_rank_change_count"
                )
                uncertainty_counts[field] += 1
            if rrf_delta > rrf_score_tolerance:
                stage_counts["rrf_score_drift_count"] += 1
                field = (
                    "bounded_rrf_score_drift_count"
                    if bounded_numeric_exchange
                    else "unbounded_rrf_score_drift_count"
                )
                uncertainty_counts[field] += 1
            if bm25_score_quality_delta > bm25_score_tolerance:
                stage_counts["bm25_score_quality_drift_count"] += 1
            if vector_similarity_quality_delta > vector_similarity_tolerance:
                stage_counts["vector_similarity_quality_drift_count"] += 1
            if reranker_delta > reranker_score_tolerance:
                stage_counts["reranker_score_drift_count"] += 1
            if final_rank_changed:
                stage_counts["final_rank_change_count"] += 1

    effective_counts = {
        **stage_counts,
        "vector_rank_change_count": uncertainty_counts[
            "unbounded_vector_rank_change_count"
        ],
        "rrf_score_drift_count": uncertainty_counts[
            "unbounded_rrf_score_drift_count"
        ],
    }
    stable = all(count == 0 for count in effective_counts.values())
    result = {
        "repeatability_schema_version": PIPELINE_REPEATABILITY_SCHEMA_VERSION,
        "policy_id": PIPELINE_REPEATABILITY_POLICY_ID,
        "status": "STABLE" if stable else "UNSTABLE",
        "runtime_activation_permitted": False,
        "holdout_access_permitted": False,
        "measurement": {
            "repeat_count": len(normalized),
            "package_count_per_repeat": expected_package_count,
            "candidate_count_per_repeat": len(baseline),
            "comparison_count": len(baseline) * (len(normalized) - 1),
            "same_seeded_corpus_required": True,
        },
        "tolerances": {
            "reranker_score": reranker_score_tolerance,
            "rrf_normalized_score": rrf_score_tolerance,
            "bm25_score_quality": bm25_score_tolerance,
            "vector_similarity_quality": vector_similarity_tolerance,
            "rank": 0,
        },
        "uncertainty_contract": {
            "policy_id": "cx_bounded_vector_numeric_equivalence_v1",
            "classification": (
                "BOUNDED_NUMERIC_EQUIVALENT_EXCHANGE_OBSERVED"
                if uncertainty_counts["bounded_vector_rank_exchange_count"]
                else "NO_BOUNDED_EXCHANGE_OBSERVED"
            ),
            "raw_changes_preserved": True,
            "candidate_membership_must_match": True,
            "bm25_rank_must_match": True,
            "final_reranker_rank_must_match": True,
        },
        "stages": {
            **stage_counts,
            **uncertainty_counts,
            "max_rrf_score_delta": round(max_rrf_delta, 12),
            "max_bm25_score_quality_delta": round(
                max_bm25_score_quality_delta, 12
            ),
            "max_vector_similarity_quality_delta": round(
                max_vector_similarity_quality_delta, 12
            ),
            "max_reranker_score_delta": round(max_reranker_delta, 12),
            "first_observed_change_stage": _first_unstable_stage(stage_counts),
            "first_unstable_stage": _first_unstable_stage(effective_counts),
        },
        "run_set_hash": semantic_sha256_hash_ref(
            [run["run_hash"] for run in runs]
        ),
    }
    result["repeatability_hash"] = semantic_sha256_hash_ref(result)
    return result


def _normalize_runs(
    runs: Sequence[Mapping[str, Any]],
    *,
    expected_repeat_count: int,
    expected_package_count: int,
    expected_candidates_per_package: int,
) -> list[dict[tuple[str, str], dict[str, Any]]]:
    if (
        isinstance(runs, (str, bytes))
        or not isinstance(runs, Sequence)
        or len(runs) != expected_repeat_count
    ):
        raise ValueError("pipeline repeat runs are incomplete")
    normalized: list[dict[tuple[str, str], dict[str, Any]]] = []
    expected_indexes = list(range(expected_repeat_count))
    if [run.get("repeat_index") for run in runs] != expected_indexes:
        raise ValueError("pipeline repeat indexes are invalid")
    for run in runs:
        unsigned = dict(run)
        run_hash = _hash_ref(unsigned.pop("run_hash", None), "run_hash")
        if run_hash != semantic_sha256_hash_ref(unsigned):
            raise ValueError("pipeline repeat run integrity is invalid")
        observations = run.get("candidate_observations")
        if isinstance(observations, (str, bytes)) or not isinstance(
            observations, Sequence
        ):
            raise TypeError("pipeline repeat observations are invalid")
        expected_count = expected_package_count * expected_candidates_per_package
        if (
            len(observations) != expected_count
            or run.get("sample_count") != expected_package_count
            or run.get("candidate_observation_count") != expected_count
        ):
            raise ValueError("pipeline repeat observation coverage is incomplete")
        by_identity: dict[tuple[str, str], dict[str, Any]] = {}
        packages: set[str] = set()
        for value in observations:
            row = _normalize_observation(value)
            identity = (row["sample_id"], row["candidate_id"])
            if identity in by_identity:
                raise ValueError("pipeline repeat candidate identity is duplicated")
            by_identity[identity] = row
            packages.add(row["sample_id"])
        if len(packages) != expected_package_count:
            raise ValueError("pipeline repeat package coverage is incomplete")
        normalized.append(by_identity)
    return normalized


def _normalize_observation(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("pipeline repeat observation is invalid")
    row = dict(value)
    observation_hash = _hash_ref(
        row.pop("observation_hash", None), "observation_hash"
    )
    if observation_hash != semantic_sha256_hash_ref(row):
        raise ValueError("pipeline repeat observation integrity is invalid")
    if row.get("observation_schema_version") != CANDIDATE_OBSERVATION_SCHEMA_VERSION:
        raise ValueError("pipeline repeat observation schema is invalid")
    sample_id = _required_string(row.get("sample_id"), "sample_id")
    candidate_id = _required_string(row.get("candidate_id"), "candidate_id")
    rank = _rank(row.get("rank"), "rank")
    signals = _mapping(row.get("signals"))
    normalized_signals = {
        "reranker_score": _score(signals.get("reranker_score"), "reranker_score"),
        "rrf_normalized_score": _score(
            signals.get("rrf_normalized_score"), "rrf_normalized_score"
        ),
        "bm25_score_quality": _score(
            signals.get("bm25_score_quality"), "bm25_score_quality"
        ),
        "vector_similarity_quality": _score(
            signals.get("vector_similarity_quality"),
            "vector_similarity_quality",
        ),
        "bm25_rank": _optional_rank(signals.get("bm25_rank"), "bm25_rank"),
        "vector_rank": _optional_rank(signals.get("vector_rank"), "vector_rank"),
    }
    return {
        **row,
        "observation_hash": observation_hash,
        "sample_id": sample_id,
        "candidate_id": candidate_id,
        "rank": rank,
        "signals": normalized_signals,
    }


def _package_membership(
    observations: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, tuple[str, ...]]:
    packages: dict[str, list[str]] = {}
    for sample_id, candidate_id in observations:
        packages.setdefault(sample_id, []).append(candidate_id)
    return {
        sample_id: tuple(sorted(candidates))
        for sample_id, candidates in packages.items()
    }


def _first_unstable_stage(counts: Mapping[str, int]) -> str | None:
    stages = (
        ("CANDIDATE_MEMBERSHIP", "candidate_membership_change_count"),
        ("BM25_RANK", "bm25_rank_change_count"),
        ("VECTOR_RANK", "vector_rank_change_count"),
        ("BM25_SCORE_QUALITY", "bm25_score_quality_drift_count"),
        (
            "VECTOR_SIMILARITY_QUALITY",
            "vector_similarity_quality_drift_count",
        ),
        ("RRF_SCORE", "rrf_score_drift_count"),
        ("RERANKER_SCORE", "reranker_score_drift_count"),
        ("FINAL_RANK", "final_rank_change_count"),
    )
    return next((stage for stage, field in stages if counts[field]), None)


def _validate_tolerances(
    reranker: float,
    rrf: float,
    bm25: float,
    vector: float,
) -> None:
    if any(
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 0.01
        for value in (reranker, rrf, bm25, vector)
    ):
        raise ValueError("pipeline repeatability tolerances are invalid")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _hash_ref(value: object, field: str) -> str:
    text = _required_string(value, field)
    if not text.startswith("sha256:") or len(text) != 71:
        raise ValueError(f"{field} is invalid")
    return text


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _rank(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} is invalid")
    return value


def _optional_rank(value: object, field: str) -> int | None:
    return None if value is None else _rank(value, field)


def _score(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{field} is invalid")
    return float(value)
