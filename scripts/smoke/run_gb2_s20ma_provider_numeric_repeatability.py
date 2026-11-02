#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime
import json
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
from nex_mo.remote_provider import build_remote_reranker_execution_config  # noqa: E402
from reranker_repeatability import (  # noqa: E402
    DEFAULT_TOLERANCE_GUARD_FACTOR,
    DEFAULT_TOLERANCE_HARD_CAP,
    DEFAULT_TOLERANCE_QUANTUM,
    analyze_reranker_repeatability,
    candidate_score_tolerance,
    collect_reranker_repeat_observations,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "gb2_s20ma_provider_numeric_repeatability.v1"
PROFILE_SCHEMA_VERSION = "provider_numeric_repeatability_profile.v1"
SMOKE_ENV = "NEX_GB2_S20MA_RERANKER_LIVE"
REPEAT_COUNT = 5
POLICY_ID = "weighted_rrf_vector_bm25_v1"
SCORE_SEMANTICS = "provider_native_relevance_0_1"


def run_gb2_s20ma_provider_numeric_repeatability(
    environ: Mapping[str, str] | None = None,
    *,
    dataset_path: Path = DEFAULT_V2_PATH,
    requester=None,
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
        observations = collect_reranker_repeat_observations(
            dataset,
            repeat_count=REPEAT_COUNT,
            environ=effective_env,
            requester=requester,
        )
        provisional = analyze_reranker_repeatability(
            observations,
            expected_pair_ids=set(admitted["v2"]["pair_ids"]),
            repeat_count=REPEAT_COUNT,
            score_tolerance=DEFAULT_TOLERANCE_HARD_CAP,
        )
        tolerance = candidate_score_tolerance(
            provisional["max_pair_score_range"]
        )
        analysis = analyze_reranker_repeatability(
            observations,
            expected_pair_ids=set(admitted["v2"]["pair_ids"]),
            repeat_count=REPEAT_COUNT,
            score_tolerance=tolerance,
        )
        observed_models = {item["model_revision"] for item in observations}
        observed_deployments = {item["deployment_id"] for item in observations}
        checks = {
            "provider_configured": config.configured,
            "request_shape_admitted": config.request_shape == "rerank",
            "model_revision_stable": observed_models == {config.model_revision},
            "deployment_identity_stable": observed_deployments
            == {config.deployment_id},
            "repeat_count_complete": analysis["repeat_count"] == REPEAT_COUNT,
            "pair_coverage_complete": analysis["pair_coverage_complete"],
            "observation_count_complete": len(observations) == 120 * REPEAT_COUNT,
            "scores_finite": analysis["non_finite_score_count"] == 0,
            "scores_bounded": analysis["out_of_bounds_score_count"] == 0,
            "tolerance_within_hard_cap": tolerance
            <= DEFAULT_TOLERANCE_HARD_CAP,
            "cross_label_rank_stable": analysis[
                "cross_label_rank_exchange_count"
            ]
            == 0,
            "same_label_non_near_rank_stable": analysis[
                "same_label_non_near_exchange_count"
            ]
            == 0,
        }
        profile = None
        if all(checks.values()):
            profile = {
                "profile_schema_version": PROFILE_SCHEMA_VERSION,
                "profile_id": "reranking-qwen3-4b-numeric-repeatability-v1",
                "status": "CANDIDATE",
                "binding": {
                    "capability": "reranking",
                    "model_name": config.model_name,
                    "model_revision": config.model_revision,
                    "deployment_id": config.deployment_id,
                    "request_shape": config.request_shape,
                    "score_semantics": SCORE_SEMANTICS,
                    "retrieval_policy_id": POLICY_ID,
                    "dataset_id": admitted["v2"]["dataset_id"],
                    "dataset_sha256": admitted["v2"]["dataset_sha256"],
                },
                "measurement": {
                    "repeat_count": REPEAT_COUNT,
                    "observation_count": len(observations),
                    "max_pair_score_range": analysis["max_pair_score_range"],
                    "mean_pair_score_range": analysis["mean_pair_score_range"],
                    "p95_pair_score_range": analysis["p95_pair_score_range"],
                    "p99_pair_score_range": analysis["p99_pair_score_range"],
                    "same_label_near_tie_exchange_count": analysis[
                        "same_label_near_tie_exchange_count"
                    ],
                },
                "policy": {
                    "score_delta_tolerance": tolerance,
                    "tolerance_quantum": DEFAULT_TOLERANCE_QUANTUM,
                    "tolerance_guard_factor": DEFAULT_TOLERANCE_GUARD_FACTOR,
                    "tolerance_hard_cap": DEFAULT_TOLERANCE_HARD_CAP,
                    "cross_label_rank_exchange": "FAIL_CLOSED",
                    "same_label_near_tie_exchange": "OBSERVE",
                    "same_label_non_near_exchange": "FAIL_CLOSED",
                },
            }
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "evidence_generated_at": _utc_now(),
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "candidate_profile": profile,
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
            "failure_code": "numeric_repeatability_calibration_failed",
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(result, effective_env, dataset_path)
    return result


def _assert_redacted(
    evidence: object,
    environ: Mapping[str, str],
    dataset_path: Path,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    protected = [
        str(environ.get("NEX_MO_REMOTE_RERANKER_URL", "")),
        str(environ.get("NEX_MO_REMOTE_RERANKER_API_KEY", "")),
    ]
    try:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        dataset = None
    if isinstance(dataset, Mapping):
        protected.extend(
            str(value)
            for case in dataset.get("cases", [])
            for value in (
                case.get("query"),
                *(document.get("text") for document in case.get("documents", [])),
            )
            if isinstance(value, str)
        )
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("Numeric repeatability evidence contains protected data.")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"gb2_s20ma_numeric_repeatability=skipped reason={SMOKE_ENV}"
    if status == "pass":
        profile = result.get("candidate_profile") or {}
        policy = profile.get("policy", {})
        analysis = result.get("repeatability", {})
        return (
            "gb2_s20ma_numeric_repeatability=pass "
            f"tolerance={policy.get('score_delta_tolerance')} "
            f"max_range={analysis.get('max_pair_score_range')} "
            f"cross_label={analysis.get('cross_label_rank_exchange_count')} "
            f"same_label_near={analysis.get('same_label_near_tie_exchange_count')}"
        )
    return (
        "gb2_s20ma_numeric_repeatability=fail "
        f"checks={','.join(result.get('failed_checks') or []) or 'execution'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_V2_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_gb2_s20ma_provider_numeric_repeatability(dataset_path=args.dataset)
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
