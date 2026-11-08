from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

CANDIDATE_OBSERVATION_SCHEMA_VERSION = (
    "cx_retrieval_confidence_candidate_observation.v2"
)
CANDIDATE_DIAGNOSTIC_SCHEMA_VERSION = "cx_retrieval_confidence_candidate_diagnostics.v1"
CANDIDATE_DIAGNOSTIC_POLICY_ID = "cx_candidate_feature_correction_diagnostics_v1"
CANDIDATE_FEATURE_SAMPLE_SCHEMA_VERSION = (
    "cx_retrieval_confidence_candidate_feature_sample.v1"
)
CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION = (
    "cx_retrieval_confidence_candidate_relevance_sample.v1"
)
EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION = (
    "cx_retrieval_confidence_candidate_relevance_sample.v2"
)
PAIR_SEMANTICS = "POSITIVE_PAIR_VS_NEGATIVE_PAIR"
NEAR_CONSTANT_TOLERANCE = 1e-9

CANDIDATE_SIGNAL_FIELDS = (
    "reranker_score",
    "rrf_normalized_score",
    "channel_rank_quality",
)
EXPANDED_CANDIDATE_SIGNAL_FIELDS = (
    *CANDIDATE_SIGNAL_FIELDS,
    "bm25_score_quality",
    "vector_similarity_quality",
)
CURRENT_PACKAGE_FEATURE_FIELDS = (
    "reranker_top_score",
    "reranker_top_margin",
    "rrf_top_score",
    "top_channel_support",
)
CORRECTED_PACKAGE_FEATURE_FIELDS = (
    "reranker_top2_mean",
    "reranker_second_score",
    "reranker_top2_tail_gap",
    "reranker_score_spread",
    "rrf_top2_mean",
    "top2_channel_rank_quality",
    "reranker_rrf_order_agreement",
    "lexical_vector_rank_agreement",
)
PACKAGE_FEATURE_FIELDS = (
    *CURRENT_PACKAGE_FEATURE_FIELDS,
    *CORRECTED_PACKAGE_FEATURE_FIELDS,
)


def build_candidate_diagnostic_observations(
    case: Mapping[str, Any],
    evidence_items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project text-free calibration truth and numeric retrieval evidence."""
    if not isinstance(case, Mapping):
        raise TypeError("candidate diagnostic case is invalid")
    scenario_id = _required_string(case.get("scenario_id"), "scenario_id")
    expected_ready = case.get("expected_ready")
    candidates = case.get("candidates")
    if type(expected_ready) is not bool or not _sequence(candidates):
        raise TypeError("candidate diagnostic case is invalid")
    if len(candidates) != 4:
        raise ValueError("candidate diagnostic case requires four candidates")

    truth: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise TypeError("candidate diagnostic truth is invalid")
        candidate_id = _required_string(candidate.get("candidate_id"), "candidate_id")
        role = _required_string(candidate.get("evidence_role"), "evidence_role")
        expected_relevant = candidate.get("expected_relevant")
        if type(expected_relevant) is not bool or candidate_id in truth:
            raise ValueError("candidate diagnostic truth is invalid")
        truth[candidate_id] = {
            "evidence_role": role,
            "expected_relevant": expected_relevant,
        }

    if not _sequence(evidence_items) or len(evidence_items) != 4:
        raise ValueError("candidate diagnostic evidence requires four items")
    bm25_scores = [
        _optional_nonnegative_score(
            _mapping(item.get("scores")).get("bm25_score"),
            "bm25_score",
        )
        for item in evidence_items
        if isinstance(item, Mapping)
    ]
    maximum_bm25_score = max(
        (score for score in bm25_scores if score is not None),
        default=0.0,
    )
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    ranks: set[int] = set()
    label = "positive" if expected_ready else "negative"
    sample_id = f"{scenario_id}:{label}"
    for item in evidence_items:
        if not isinstance(item, Mapping):
            raise TypeError("candidate diagnostic evidence item is invalid")
        candidate_id = _required_string(item.get("candidate_id"), "candidate_id")
        rank = _positive_rank(item.get("rank"), "rank")
        scores = item.get("scores")
        if candidate_id not in truth or candidate_id in seen or rank in ranks:
            raise ValueError("candidate diagnostic evidence scope is invalid")
        if not isinstance(scores, Mapping):
            raise TypeError("candidate diagnostic scores are invalid")
        seen.add(candidate_id)
        ranks.add(rank)
        bm25_rank = _optional_rank(scores.get("bm25_rank"), "bm25_rank")
        vector_rank = _optional_rank(scores.get("vector_rank"), "vector_rank")
        bm25_score = _optional_nonnegative_score(
            scores.get("bm25_score"), "bm25_score"
        )
        vector_score = _optional_cosine_score(
            scores.get("vector_score"), "vector_score"
        )
        if bm25_rank is None and vector_rank is None:
            raise ValueError("candidate diagnostic channel ranks are missing")
        if (bm25_rank is None) != (bm25_score is None) or (
            vector_rank is None
        ) != (vector_score is None):
            raise ValueError("candidate diagnostic channel score binding is invalid")
        observation = {
            "observation_schema_version": CANDIDATE_OBSERVATION_SCHEMA_VERSION,
            "sample_id": sample_id,
            "candidate_id": candidate_id,
            "package_expected_ready": expected_ready,
            **truth[candidate_id],
            "rank": rank,
            "signals": {
                "reranker_score": _bounded_score(
                    scores.get("rerank_score"), "rerank_score"
                ),
                "rrf_normalized_score": _bounded_score(
                    scores.get("rrf_normalized_score"), "rrf_normalized_score"
                ),
                "channel_support": _bounded_score(
                    scores.get("channel_support_score"), "channel_support_score"
                ),
                "bm25_score_quality": _normalized_bm25_score(
                    bm25_score,
                    maximum=maximum_bm25_score,
                ),
                "vector_similarity_quality": _vector_similarity_quality(
                    vector_score
                ),
                "bm25_rank": bm25_rank,
                "vector_rank": vector_rank,
            },
        }
        observation["observation_hash"] = semantic_sha256_hash_ref(observation)
        observations.append(observation)
    if seen != set(truth) or ranks != {1, 2, 3, 4}:
        raise ValueError("candidate diagnostic evidence scope is incomplete")
    return sorted(observations, key=lambda row: int(row["rank"]))


def diagnose_candidate_feature_correction(
    observations: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    expected_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit candidate and corrected package signals without selecting a policy."""
    normalized, packages = _normalize_observations(observations)
    candidate_signals = {
        field: _binary_signal_diagnostic(
            [
                (bool(row["expected_relevant"]), float(row["signals"][field]))
                for row in normalized
            ]
        )
        for field in CANDIDATE_SIGNAL_FIELDS
    }

    package_rows = [_package_features(rows) for rows in packages.values()]
    package_features = {
        field: _paired_package_feature_diagnostic(package_rows, field=field)
        for field in PACKAGE_FEATURE_FIELDS
    }
    directional_candidates = sorted(
        field
        for field in CORRECTED_PACKAGE_FEATURE_FIELDS
        if package_features[field]["classification"] == "DIRECTIONAL"
    )
    findings = sorted(
        f"{field.upper()}_{diagnostic['classification']}"
        for field, diagnostic in package_features.items()
        if diagnostic["classification"] != "DIRECTIONAL"
    )
    result = {
        "candidate_diagnostic_schema_version": CANDIDATE_DIAGNOSTIC_SCHEMA_VERSION,
        "policy_id": CANDIDATE_DIAGNOSTIC_POLICY_ID,
        "status": "DIAGNOSED",
        "runtime_activation_permitted": False,
        "feature_selection_permitted": False,
        "weight_selection_permitted": False,
        "threshold_selection_permitted": False,
        "holdout_access_permitted": False,
        "dataset": {
            "dataset_id": _required_string(dataset_id, "dataset_id"),
            "dataset_sha256": _required_string(dataset_sha256, "dataset_sha256"),
            "partition": "CALIBRATION",
            "package_count": len(packages),
            "candidate_observation_count": len(normalized),
            "observation_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["observation_hash"]) for row in normalized)
            ),
        },
        "binding": _binding(expected_binding),
        "package_semantics": {
            "pair_semantics": PAIR_SEMANTICS,
            "single_mixed_candidate_retrieval": True,
            "label_filtered_retrieval": False,
            "candidate_truth_used_for_runtime_feature": False,
            "finding_scope": "diagnostic_only",
        },
        "candidate_ranking": _candidate_ranking_diagnostic(packages),
        "candidate_signals": candidate_signals,
        "package_features": package_features,
        "feature_set_correction": {
            "current_feature_fields": list(CURRENT_PACKAGE_FEATURE_FIELDS),
            "corrected_candidate_fields": list(CORRECTED_PACKAGE_FEATURE_FIELDS),
            "directional_corrected_candidates": directional_candidates,
            "selection_deferred_to": "GB2-CA00-S20Q-G",
        },
        "findings": findings,
    }
    result["diagnostic_hash"] = semantic_sha256_hash_ref(result)
    return result


def build_candidate_feature_calibration_samples(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build integrity-protected numeric rows for calibration-only selection."""
    _, packages = _normalize_observations(observations)
    projected: list[dict[str, Any]] = []
    for rows in packages.values():
        package = _package_features(rows)
        sample = {
            "sample_schema_version": CANDIDATE_FEATURE_SAMPLE_SCHEMA_VERSION,
            "sample_id": package["sample_id"],
            "expected_ready": package["expected_ready"],
            "features": package["features"],
        }
        sample["sample_hash"] = semantic_sha256_hash_ref(sample)
        projected.append(sample)
    return sorted(projected, key=lambda row: str(row["sample_id"]))


def build_candidate_relevance_calibration_samples(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project candidate labels and runtime signals for calibration-only use."""
    normalized, _ = _normalize_observations(observations)
    projected: list[dict[str, Any]] = []
    for row in normalized:
        sample = {
            "sample_schema_version": CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION,
            "sample_id": row["sample_id"],
            "candidate_id": row["candidate_id"],
            "expected_ready": row["package_expected_ready"],
            "expected_relevant": row["expected_relevant"],
            "signals": {
                field: row["signals"][field] for field in CANDIDATE_SIGNAL_FIELDS
            },
        }
        sample["sample_hash"] = semantic_sha256_hash_ref(sample)
        projected.append(sample)
    return sorted(
        projected,
        key=lambda row: (str(row["sample_id"]), str(row["candidate_id"])),
    )


def build_expanded_candidate_relevance_calibration_samples(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project historical and bounded raw-channel relevance signals."""
    normalized, _ = _normalize_observations(observations)
    projected: list[dict[str, Any]] = []
    for row in normalized:
        sample = {
            "sample_schema_version": (
                EXPANDED_CANDIDATE_RELEVANCE_SAMPLE_SCHEMA_VERSION
            ),
            "sample_id": row["sample_id"],
            "candidate_id": row["candidate_id"],
            "expected_ready": row["package_expected_ready"],
            "expected_relevant": row["expected_relevant"],
            "signals": {
                field: row["signals"][field]
                for field in EXPANDED_CANDIDATE_SIGNAL_FIELDS
            },
        }
        sample["sample_hash"] = semantic_sha256_hash_ref(sample)
        projected.append(sample)
    return sorted(
        projected,
        key=lambda row: (str(row["sample_id"]), str(row["candidate_id"])),
    )


def _normalize_observations(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if not _sequence(observations):
        raise TypeError("candidate diagnostic observations are invalid")
    normalized: list[dict[str, Any]] = []
    packages: dict[str, list[dict[str, Any]]] = {}
    seen_hashes: set[str] = set()
    for value in observations:
        if not isinstance(value, Mapping):
            raise TypeError("candidate diagnostic observation is invalid")
        row = dict(value)
        observation_hash = _required_string(
            row.pop("observation_hash", None), "observation_hash"
        )
        if (
            observation_hash in seen_hashes
            or observation_hash != semantic_sha256_hash_ref(row)
        ):
            raise ValueError("candidate diagnostic observation integrity is invalid")
        seen_hashes.add(observation_hash)
        if (
            row.get("observation_schema_version")
            != CANDIDATE_OBSERVATION_SCHEMA_VERSION
        ):
            raise ValueError("candidate diagnostic observation schema is invalid")
        sample_id = _required_string(row.get("sample_id"), "sample_id")
        expected_ready = row.get("package_expected_ready")
        expected_relevant = row.get("expected_relevant")
        signals = row.get("signals")
        if (
            type(expected_ready) is not bool
            or type(expected_relevant) is not bool
            or not isinstance(signals, Mapping)
        ):
            raise TypeError("candidate diagnostic observation values are invalid")
        normalized_signals = {
            "reranker_score": _bounded_score(
                signals.get("reranker_score"), "reranker_score"
            ),
            "rrf_normalized_score": _bounded_score(
                signals.get("rrf_normalized_score"), "rrf_normalized_score"
            ),
            "channel_support": _bounded_score(
                signals.get("channel_support"), "channel_support"
            ),
            "bm25_score_quality": _bounded_score(
                signals.get("bm25_score_quality"), "bm25_score_quality"
            ),
            "vector_similarity_quality": _bounded_score(
                signals.get("vector_similarity_quality"),
                "vector_similarity_quality",
            ),
            "bm25_rank": _optional_rank(signals.get("bm25_rank"), "bm25_rank"),
            "vector_rank": _optional_rank(signals.get("vector_rank"), "vector_rank"),
        }
        normalized_signals["channel_rank_quality"] = _channel_rank_quality(
            normalized_signals["bm25_rank"], normalized_signals["vector_rank"]
        )
        normalized_row = {
            **row,
            "observation_hash": observation_hash,
            "sample_id": sample_id,
            "rank": _positive_rank(row.get("rank"), "rank"),
            "signals": normalized_signals,
        }
        packages.setdefault(sample_id, []).append(normalized_row)
        normalized.append(normalized_row)

    for sample_id, rows in packages.items():
        rows.sort(key=lambda row: int(row["rank"]))
        expected_ready = sample_id.endswith(":positive")
        if (
            len(rows) != 4
            or [row["rank"] for row in rows] != [1, 2, 3, 4]
            or len({row["candidate_id"] for row in rows}) != 4
            or any(row["package_expected_ready"] is not expected_ready for row in rows)
            or sum(bool(row["expected_relevant"]) for row in rows)
            != (2 if expected_ready else 0)
        ):
            raise ValueError("candidate diagnostic package semantics are invalid")
    scenario_labels: dict[str, set[str]] = {}
    for sample_id in packages:
        scenario, separator, label = sample_id.rpartition(":")
        if not separator or label not in {"positive", "negative"}:
            raise ValueError("candidate diagnostic sample identity is invalid")
        scenario_labels.setdefault(scenario, set()).add(label)
    if not packages or any(
        labels != {"positive", "negative"} for labels in scenario_labels.values()
    ):
        raise ValueError("candidate diagnostic scenario pairs are incomplete")
    return sorted(normalized, key=lambda row: (row["sample_id"], row["rank"])), packages


def _package_features(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reranker = [float(row["signals"]["reranker_score"]) for row in rows]
    rrf = [float(row["signals"]["rrf_normalized_score"]) for row in rows]
    rank_quality = [float(row["signals"]["channel_rank_quality"]) for row in rows]
    rrf_order = sorted(range(4), key=lambda index: (-rrf[index], index))
    rrf_positions = {index: position for position, index in enumerate(rrf_order)}
    concordant = sum(
        rrf_positions[left] < rrf_positions[right]
        for left in range(4)
        for right in range(left + 1, 4)
    )
    bm25 = [row["signals"]["bm25_rank"] for row in rows]
    vector = [row["signals"]["vector_rank"] for row in rows]
    comparable = [index for index in range(4) if bm25[index] and vector[index]]
    pair_count = len(comparable) * (len(comparable) - 1) // 2
    channel_concordant = sum(
        (int(bm25[left]) - int(bm25[right])) * (int(vector[left]) - int(vector[right]))
        > 0
        for position, left in enumerate(comparable)
        for right in comparable[position + 1 :]
    )
    return {
        "sample_id": rows[0]["sample_id"],
        "expected_ready": rows[0]["package_expected_ready"],
        "features": {
            "reranker_top_score": reranker[0],
            "reranker_top_margin": round(max(0.0, reranker[0] - reranker[1]), 8),
            "rrf_top_score": rrf[0],
            "top_channel_support": float(rows[0]["signals"]["channel_support"]),
            "reranker_top2_mean": round(statistics.fmean(reranker[:2]), 8),
            "reranker_second_score": reranker[1],
            "reranker_top2_tail_gap": round(
                max(
                    0.0, statistics.fmean(reranker[:2]) - statistics.fmean(reranker[2:])
                ),
                8,
            ),
            "reranker_score_spread": round(max(0.0, reranker[0] - reranker[-1]), 8),
            "rrf_top2_mean": round(statistics.fmean(rrf[:2]), 8),
            "top2_channel_rank_quality": round(statistics.fmean(rank_quality[:2]), 8),
            "reranker_rrf_order_agreement": round(concordant / 6, 8),
            "lexical_vector_rank_agreement": (
                round(channel_concordant / pair_count, 8) if pair_count else 0.0
            ),
        },
    }


def _candidate_ranking_diagnostic(
    packages: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    ready = [rows for rows in packages.values() if rows[0]["package_expected_ready"]]
    top1 = sum(bool(rows[0]["expected_relevant"]) for rows in ready)
    top2_relevant = sum(
        sum(bool(row["expected_relevant"]) for row in rows[:2]) for rows in ready
    )
    reciprocal_ranks = [
        1.0 / min(int(row["rank"]) for row in rows if row["expected_relevant"])
        for rows in ready
    ]
    return {
        "ready_package_count": len(ready),
        "low_confidence_package_count": len(packages) - len(ready),
        "ready_top1_relevant_rate": round(top1 / len(ready), 8),
        "ready_top2_relevant_recall": round(top2_relevant / (len(ready) * 2), 8),
        "ready_mean_reciprocal_relevant_rank": round(
            statistics.fmean(reciprocal_ranks), 8
        ),
    }


def _binary_signal_diagnostic(
    labelled_values: Sequence[tuple[bool, float]],
) -> dict[str, Any]:
    positives = [value for label, value in labelled_values if label]
    negatives = [value for label, value in labelled_values if not label]
    return _diagnostic(positives, negatives)


def _paired_package_feature_diagnostic(
    package_rows: Sequence[Mapping[str, Any]],
    *,
    field: str,
) -> dict[str, Any]:
    positives = [
        float(row["features"][field]) for row in package_rows if row["expected_ready"]
    ]
    negatives = [
        float(row["features"][field])
        for row in package_rows
        if not row["expected_ready"]
    ]
    positive_by_scenario = {
        str(row["sample_id"]).rpartition(":")[0]: float(row["features"][field])
        for row in package_rows
        if row["expected_ready"]
    }
    negative_by_scenario = {
        str(row["sample_id"]).rpartition(":")[0]: float(row["features"][field])
        for row in package_rows
        if not row["expected_ready"]
    }
    deltas = [
        positive_by_scenario[scenario] - negative_by_scenario[scenario]
        for scenario in sorted(positive_by_scenario)
    ]
    return {
        **_diagnostic(positives, negatives),
        "paired_delta": {
            **_distribution(deltas),
            "positive_higher_count": sum(delta > 0 for delta in deltas),
            "tied_count": sum(
                math.isclose(delta, 0.0, abs_tol=1e-12) for delta in deltas
            ),
            "negative_higher_count": sum(delta < 0 for delta in deltas),
        },
    }


def _diagnostic(
    positives: Sequence[float], negatives: Sequence[float]
) -> dict[str, Any]:
    all_values = [*positives, *negatives]
    auc = _auc(positives, negatives)
    near_constant = max(all_values) - min(all_values) <= NEAR_CONSTANT_TOLERANCE
    return {
        "classification": _classification(auc, near_constant=near_constant),
        "higher_is_positive_auc": auc,
        "near_constant": near_constant,
        "unique_value_count": len(set(all_values)),
        "positive_distribution": _distribution(positives),
        "negative_distribution": _distribution(negatives),
    }


def _auc(positives: Sequence[float], negatives: Sequence[float]) -> float:
    if not positives or not negatives:
        raise ValueError("candidate diagnostic labels are incomplete")
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return round(wins / (len(positives) * len(negatives)), 8)


def _classification(auc: float, *, near_constant: bool) -> str:
    if near_constant:
        return "CONSTANT"
    if auc < 0.45:
        return "INVERTED"
    if auc <= 0.55:
        return "NON_DISCRIMINATIVE"
    return "DIRECTIONAL"


def _distribution(values: Sequence[float]) -> dict[str, float]:
    return {
        "minimum": round(min(values), 8),
        "maximum": round(max(values), 8),
        "mean": round(statistics.fmean(values), 8),
        "median": round(statistics.median(values), 8),
    }


def _channel_rank_quality(bm25_rank: int | None, vector_rank: int | None) -> float:
    scores = [1.0 / rank for rank in (bm25_rank, vector_rank) if rank is not None]
    return round(statistics.fmean(scores), 8) if scores else 0.0


def _binding(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise TypeError("candidate diagnostic binding is invalid")
    return {str(key): _required_string(item, str(key)) for key, item in value.items()}


def _bounded_score(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} is invalid")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{field} is invalid")
    return numeric


def _optional_nonnegative_score(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} is invalid")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        raise ValueError(f"{field} is invalid")
    return numeric


def _optional_cosine_score(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} is invalid")
    numeric = float(value)
    if not math.isfinite(numeric) or not -1.0 <= numeric <= 1.0:
        raise ValueError(f"{field} is invalid")
    return numeric


def _normalized_bm25_score(value: float | None, *, maximum: float) -> float:
    if value is None or maximum <= 0.0:
        return 0.0
    return round(min(1.0, value / maximum), 8)


def _vector_similarity_quality(value: float | None) -> float:
    if value is None:
        return 0.0
    return round(min(1.0, max(0.0, value)), 8)


def _positive_rank(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TypeError(f"{field} is invalid")
    return value


def _optional_rank(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_rank(value, field)


def _sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()
