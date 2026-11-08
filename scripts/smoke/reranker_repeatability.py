from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from itertools import combinations
import math
from typing import Any

from nex_mo.remote_provider import execute_remote_rerank_request


HttpRequester = Callable[..., Any]
DEFAULT_TOLERANCE_QUANTUM = 0.0005
DEFAULT_TOLERANCE_GUARD_FACTOR = 1.25
DEFAULT_TOLERANCE_HARD_CAP = 0.005


def collect_reranker_repeat_observations(
    dataset: Mapping[str, Any],
    *,
    repeat_count: int,
    environ: Mapping[str, str],
    requester: HttpRequester | None,
) -> list[dict[str, Any]]:
    if repeat_count < 2:
        raise ValueError("repeat_count must be at least two")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Calibration dataset cases must be a non-empty list.")
    observations: list[dict[str, Any]] = []
    for repeat_index in range(1, repeat_count + 1):
        for case in cases:
            case_id = _required_string(case.get("case_id"), "case_id")
            query = _required_string(case.get("query"), "query")
            partition = _required_string(case.get("partition"), "partition")
            documents = case.get("documents")
            if not isinstance(documents, list) or not documents:
                raise ValueError("documents must be a non-empty list.")
            response = execute_remote_rerank_request(
                {
                    "alias": "reranker-default",
                    "query": query,
                    "documents": [
                        _required_string(document.get("text"), "text")
                        for document in documents
                    ],
                    "top_n": len(documents),
                },
                environ=dict(environ),
                requester=requester,
            )
            model_revision = _required_string(
                response.get("model_revision"), "model_revision"
            )
            deployment_id = _required_string(
                response.get("deployment_id"), "deployment_id"
            )
            scored = scored_reranker_results(response, len(documents))
            score_by_index = dict(scored)
            rank_by_index = {
                original_index: rank
                for rank, (original_index, _score) in enumerate(scored, start=1)
            }
            observed_at = _utc_now()
            for document_index, document in enumerate(documents):
                expected_ready = document.get("expected_ready")
                if type(expected_ready) is not bool:
                    raise ValueError("expected_ready must be boolean.")
                document_id = _required_string(
                    document.get("document_id"), "document_id"
                )
                observations.append(
                    {
                        "case_id": case_id,
                        "pair_id": f"{case_id}:{document_id}",
                        "partition": partition,
                        "relevance_grade": _required_string(
                            document.get("relevance_grade"), "relevance_grade"
                        ),
                        "expected_ready": expected_ready,
                        "repeat_index": repeat_index,
                        "score": score_by_index[document_index],
                        "rank": rank_by_index[document_index],
                        "model_revision": model_revision,
                        "deployment_id": deployment_id,
                        "observed_at": observed_at,
                    }
                )
    return observations


def scored_reranker_results(
    response: Mapping[str, Any],
    document_count: int,
) -> list[tuple[int, float]]:
    results = response.get("results")
    if not isinstance(results, list):
        raise ValueError("Reranker response results must be a list.")
    by_index: dict[int, float] = {}
    for item in results:
        if not isinstance(item, Mapping):
            raise ValueError("Reranker result must be an object.")
        index = item.get("index")
        score = item.get("score")
        if type(index) is not int or isinstance(score, bool) or not isinstance(
            score, int | float
        ):
            raise ValueError("Reranker result index and score are invalid.")
        if index in by_index:
            raise ValueError("Reranker response contains a duplicate index.")
        by_index[index] = float(score)
    if set(by_index) != set(range(document_count)):
        raise ValueError("Reranker response did not score every document.")
    return sorted(by_index.items(), key=lambda item: (-item[1], item[0]))


def analyze_reranker_repeatability(
    observations: list[dict[str, Any]],
    *,
    expected_pair_ids: set[str],
    repeat_count: int,
    score_tolerance: float,
) -> dict[str, Any]:
    repeats = sorted({int(item["repeat_index"]) for item in observations})
    by_repeat = {
        repeat: {
            str(item["pair_id"]): item
            for item in observations
            if item["repeat_index"] == repeat
        }
        for repeat in repeats
    }
    coverage_complete = (
        repeats == list(range(1, repeat_count + 1))
        and all(set(items) == expected_pair_ids for items in by_repeat.values())
    )
    score_ranges: dict[str, float] = {}
    if coverage_complete:
        for pair_id in sorted(expected_pair_ids):
            scores = [float(by_repeat[repeat][pair_id]["score"]) for repeat in repeats]
            score_ranges[pair_id] = max(scores) - min(scores)
    rank_policy = _rank_exchange_analysis(
        by_repeat,
        repeats=repeats,
        expected_pair_ids=expected_pair_ids,
        score_tolerance=score_tolerance,
        coverage_complete=coverage_complete,
    )
    ranges = sorted(score_ranges.values())
    return {
        "repeat_count": len(repeats),
        "pair_coverage_complete": coverage_complete,
        "observation_count": len(observations),
        "score_delta_tolerance": score_tolerance,
        "max_pair_score_range": max(ranges, default=math.inf),
        "mean_pair_score_range": (
            sum(ranges) / len(ranges) if ranges else math.inf
        ),
        "p95_pair_score_range": _percentile(ranges, 0.95),
        "p99_pair_score_range": _percentile(ranges, 0.99),
        "score_drift_pair_count": sum(
            value > score_tolerance for value in ranges
        ),
        "non_finite_score_count": sum(
            not math.isfinite(float(item["score"])) for item in observations
        ),
        "out_of_bounds_score_count": sum(
            not 0.0 <= float(item["score"]) <= 1.0 for item in observations
        ),
        **rank_policy,
    }


def candidate_score_tolerance(
    max_pair_score_range: float,
    *,
    quantum: float = DEFAULT_TOLERANCE_QUANTUM,
    guard_factor: float = DEFAULT_TOLERANCE_GUARD_FACTOR,
    hard_cap: float = DEFAULT_TOLERANCE_HARD_CAP,
) -> float:
    if (
        not math.isfinite(max_pair_score_range)
        or max_pair_score_range < 0.0
        or quantum <= 0.0
        or guard_factor < 1.0
        or hard_cap <= 0.0
    ):
        raise ValueError("numeric repeatability tolerance inputs are invalid")
    guarded = max_pair_score_range * guard_factor
    candidate = math.ceil((guarded - 1e-15) / quantum) * quantum
    return round(max(quantum, candidate), 10)


def _rank_exchange_analysis(
    by_repeat: Mapping[int, Mapping[str, Mapping[str, Any]]],
    *,
    repeats: list[int],
    expected_pair_ids: set[str],
    score_tolerance: float,
    coverage_complete: bool,
) -> dict[str, Any]:
    cross_label: list[str] = []
    same_label_near: list[str] = []
    same_label_non_near: list[str] = []
    if coverage_complete:
        case_pairs: dict[str, list[str]] = {}
        for pair_id in expected_pair_ids:
            case_pairs.setdefault(pair_id.split(":", 1)[0], []).append(pair_id)
        for pair_ids in case_pairs.values():
            for left, right in combinations(sorted(pair_ids), 2):
                order = {
                    int(by_repeat[repeat][left]["rank"])
                    < int(by_repeat[repeat][right]["rank"])
                    for repeat in repeats
                }
                if len(order) == 1:
                    continue
                exchange_id = f"{left}|{right}"
                left_ready = bool(by_repeat[repeats[0]][left]["expected_ready"])
                right_ready = bool(by_repeat[repeats[0]][right]["expected_ready"])
                if left_ready != right_ready:
                    cross_label.append(exchange_id)
                    continue
                gaps = [
                    abs(
                        float(by_repeat[repeat][left]["score"])
                        - float(by_repeat[repeat][right]["score"])
                    )
                    for repeat in repeats
                ]
                target = (
                    same_label_near
                    if max(gaps) <= score_tolerance
                    else same_label_non_near
                )
                target.append(exchange_id)
    return {
        "cross_label_rank_exchange_count": len(cross_label),
        "cross_label_rank_exchange_ids": sorted(cross_label),
        "same_label_near_tie_exchange_count": len(same_label_near),
        "same_label_near_tie_exchange_ids": sorted(same_label_near),
        "same_label_non_near_exchange_count": len(same_label_non_near),
        "same_label_non_near_exchange_ids": sorted(same_label_non_near),
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return math.inf
    index = max(0, math.ceil(len(values) * percentile) - 1)
    return values[index]


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
