#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "quality",
):
    sys.path.insert(0, str(path))

from check_model_calibration_dataset import (  # noqa: E402
    DEFAULT_V2_PATH,
    admit_calibration_dataset_files,
)
from nex_mo.remote_provider import (  # noqa: E402
    build_remote_reranker_execution_config,
    execute_remote_rerank_request,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "gb2_s20m_reranker_repeatability_live.v1"
SMOKE_ENV = "NEX_GB2_S20M_RERANKER_LIVE"
REPEAT_COUNT = 2
EXPECTED_PAIR_COUNT = 120
MAX_SCORE_DELTA = 0.000001
POLICY_ID = "weighted_rrf_vector_bm25_v1"
SCORE_SEMANTICS = "provider_native_relevance_0_1"
HttpRequester = Callable[..., Any]


def run_gb2_s20m_reranker_repeatability_live(
    environ: Mapping[str, str] | None = None,
    *,
    dataset_path: Path = DEFAULT_V2_PATH,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    effective_env = {**protected_dgx_vllm_profile_defaults(), **env}
    try:
        admitted = admit_calibration_dataset_files(v2_path=dataset_path)
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        config = build_remote_reranker_execution_config(effective_env)
        if not config.configured:
            raise ValueError("Remote reranker provider endpoint is not configured.")
        observations = _collect_repeat_observations(
            dataset,
            environ=effective_env,
            requester=requester,
        )
        analysis = _analyze_repeatability(
            observations,
            expected_pair_ids=set(admitted["v2"]["pair_ids"]),
        )
        observed_models = {item["model_revision"] for item in observations}
        observed_deployments = {item["deployment_id"] for item in observations}
        checks = {
            "dataset_admitted": admitted["v2"]["pair_count"]
            == EXPECTED_PAIR_COUNT,
            "provider_configured": config.configured,
            "request_shape_admitted": config.request_shape == "rerank",
            "model_revision_stable": observed_models == {config.model_revision},
            "deployment_identity_stable": observed_deployments
            == {config.deployment_id},
            "repeat_count_complete": analysis["repeat_count"] == REPEAT_COUNT,
            "pair_coverage_complete": analysis["pair_coverage_complete"],
            "observation_count_complete": len(observations)
            == EXPECTED_PAIR_COUNT * REPEAT_COUNT,
            "scores_finite": analysis["non_finite_score_count"] == 0,
            "scores_bounded": analysis["out_of_bounds_score_count"] == 0,
            "score_repeatability": analysis["max_absolute_score_delta"]
            <= MAX_SCORE_DELTA,
            "rank_repeatability": analysis["rank_inversion_count"] == 0,
        }
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "evidence_generated_at": _utc_now(),
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "provider_binding": {
                "capability": "reranking",
                "model_name": config.model_name,
                "model_revision": config.model_revision,
                "deployment_id": config.deployment_id,
                "request_shape": config.request_shape,
                "score_semantics": SCORE_SEMANTICS,
                "retrieval_policy_id": POLICY_ID,
            },
            "dataset_binding": {
                "dataset_id": admitted["v2"]["dataset_id"],
                "dataset_sha256": admitted["v2"]["dataset_sha256"],
                "pair_count": admitted["v2"]["pair_count"],
            },
            "repeatability": analysis,
            "score_observations": observations,
            "raw_text_persisted": False,
            "provider_endpoint_persisted": False,
            "provider_credential_persisted": False,
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "reranker_repeatability_execution_failed",
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(result, effective_env, dataset_path)
    return result


def _collect_repeat_observations(
    dataset: Mapping[str, Any],
    *,
    environ: Mapping[str, str],
    requester: HttpRequester | None,
) -> list[dict[str, Any]]:
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Calibration dataset cases must be a non-empty list.")
    observations: list[dict[str, Any]] = []
    for repeat_index in range(1, REPEAT_COUNT + 1):
        for case in cases:
            case_id = _required_string(case.get("case_id"), "case_id")
            query = _required_string(case.get("query"), "query")
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
            scored = _scored_results(response, len(documents))
            rank_by_index = {
                original_index: rank
                for rank, (original_index, _score) in enumerate(scored, start=1)
            }
            score_by_index = dict(scored)
            observed_at = _utc_now()
            for document_index, document in enumerate(documents):
                document_id = _required_string(
                    document.get("document_id"), "document_id"
                )
                grade = _required_string(
                    document.get("relevance_grade"), "relevance_grade"
                )
                expected_ready = document.get("expected_ready")
                if type(expected_ready) is not bool:
                    raise ValueError("expected_ready must be boolean.")
                observations.append(
                    {
                        "pair_id": f"{case_id}:{document_id}",
                        "partition": _required_string(
                            case.get("partition"), "partition"
                        ),
                        "relevance_grade": grade,
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


def _scored_results(
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


def _analyze_repeatability(
    observations: list[dict[str, Any]],
    *,
    expected_pair_ids: set[str],
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
    pair_coverage_complete = (
        repeats == list(range(1, REPEAT_COUNT + 1))
        and all(set(items) == expected_pair_ids for items in by_repeat.values())
    )
    deltas: list[float] = []
    rank_inversions: list[str] = []
    if pair_coverage_complete:
        baseline = by_repeat[1]
        repeated = by_repeat[2]
        for pair_id in sorted(expected_pair_ids):
            deltas.append(abs(float(baseline[pair_id]["score"]) - float(repeated[pair_id]["score"])))
            if int(baseline[pair_id]["rank"]) != int(repeated[pair_id]["rank"]):
                rank_inversions.append(pair_id)
    non_finite = sum(
        not math.isfinite(float(item["score"])) for item in observations
    )
    out_of_bounds = sum(
        not 0.0 <= float(item["score"]) <= 1.0 for item in observations
    )
    return {
        "repeat_count": len(repeats),
        "pair_coverage_complete": pair_coverage_complete,
        "observation_count": len(observations),
        "score_delta_tolerance": MAX_SCORE_DELTA,
        "max_absolute_score_delta": max(deltas, default=math.inf),
        "score_drift_pair_count": sum(delta > MAX_SCORE_DELTA for delta in deltas),
        "rank_inversion_count": len(rank_inversions),
        "rank_inversion_pair_ids": rank_inversions,
        "non_finite_score_count": non_finite,
        "out_of_bounds_score_count": out_of_bounds,
    }


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    dataset_path: Path,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected_values = [
        str(environ.get("NEX_MO_REMOTE_RERANKER_URL", "")),
        str(environ.get("NEX_MO_REMOTE_RERANKER_API_KEY", "")),
    ]
    try:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        dataset = None
    if isinstance(dataset, Mapping):
        protected_values.extend(
            str(document["text"])
            for case in dataset.get("cases", [])
            for document in case.get("documents", [])
            if isinstance(document, Mapping) and isinstance(document.get("text"), str)
        )
        protected_values.extend(
            str(case["query"])
            for case in dataset.get("cases", [])
            if isinstance(case, Mapping) and isinstance(case.get("query"), str)
        )
    if any(len(value) >= 4 and value in serialized for value in protected_values):
        raise ValueError("Repeatability evidence contains protected request data.")


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"gb2_s20m_reranker_repeatability_live=skipped reason={SMOKE_ENV}"
    if status == "pass":
        repeatability = result.get("repeatability", {})
        binding = result.get("provider_binding", {})
        return (
            "gb2_s20m_reranker_repeatability_live=pass "
            f"model={binding.get('model_revision')} "
            f"observations={repeatability.get('observation_count')} "
            f"max_delta={repeatability.get('max_absolute_score_delta')} "
            f"rank_inversions={repeatability.get('rank_inversion_count')}"
        )
    return (
        "gb2_s20m_reranker_repeatability_live=fail "
        f"checks={','.join(result.get('failed_checks') or []) or 'execution'}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_V2_PATH)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_gb2_s20m_reranker_repeatability_live(dataset_path=args.dataset)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
