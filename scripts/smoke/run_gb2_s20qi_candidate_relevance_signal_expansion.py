#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_gb2_s20qe_v3_calibration_collection as s20qe
import run_gb2_s20qg_candidate_policy_freeze as s20qg
import run_gb2_s20qh_pipeline_repeatability_relevance as s20qh
from nex_cx.retrieval_candidate_relevance_calibration import (
    EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID,
    calibrate_candidate_relevance_policy,
)
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    EXPANDED_CANDIDATE_SIGNAL_FIELDS,
    build_expanded_candidate_relevance_calibration_samples,
)
from nex_cx.retrieval_pipeline_repeatability import (
    analyze_retrieval_pipeline_repeatability,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, sha256_text

SCHEMA_VERSION = "gb2_s20qi_candidate_relevance_signal_expansion.v1"
SMOKE_ENV = "NEX_GB2_S20QI_LIVE_SMOKE"
REPEAT_COUNT = 5
VECTOR_SIMILARITY_TOLERANCE = 0.005

Collector = Callable[..., Mapping[str, Any]]
RepeatabilityAnalyzer = Callable[..., dict[str, Any]]
Calibrator = Callable[..., dict[str, Any]]


def run_gb2_s20qi_candidate_relevance_signal_expansion(
    environ: Mapping[str, str] | None = None,
    *,
    requester: s20qe.HttpRequester | None = None,
    collector: Collector = s20qe.run_gb2_s20qe_v3_calibration_collection,
    analyzer: RepeatabilityAnalyzer = analyze_retrieval_pipeline_repeatability,
    calibrator: Calibrator = calibrate_candidate_relevance_policy,
    repeatability_path: Path = s20qg.DEFAULT_REPEATABILITY_PATH,
    revision_path: Path = s20qg.DEFAULT_REVISION_PATH,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    try:
        repeatability_text, numeric_repeatability = s20qg._read_json(
            repeatability_path
        )
        revision_text, revision = s20qg._read_json(revision_path)
        source = collector(
            {
                **env,
                s20qe.SMOKE_ENV: "1",
                s20qe.REPEAT_COUNT_ENV: str(REPEAT_COUNT),
            },
            requester=requester,
        )
        if source.get("status") != "PASS":
            raise s20qh.S20QHError(
                "source_collection_failed",
                {
                    "status": source.get("status"),
                    "failure_code": source.get("failure_code"),
                },
            )
        provenance = s20qg._admit_provenance(
            source,
            repeatability=numeric_repeatability,
            revision=revision,
            repeatability_sha256=f"sha256:{sha256_text(repeatability_text)}",
            revision_sha256=f"sha256:{sha256_text(revision_text)}",
        )
        repeat_collection = _mapping(source.get("repeat_collection"))
        runs = repeat_collection.get("runs")
        if not isinstance(runs, list):
            raise s20qh.S20QHError("repeat_collection_missing")
        pipeline_repeatability = analyzer(
            runs,
            expected_repeat_count=REPEAT_COUNT,
            reranker_score_tolerance=float(provenance["numeric_tolerance"]),
            vector_similarity_tolerance=VECTOR_SIMILARITY_TOLERANCE,
        )
        baseline_observations = _mapping(runs[0]).get("candidate_observations")
        if not isinstance(baseline_observations, list):
            raise s20qh.S20QHError("baseline_candidate_observations_missing")
        candidate_samples = build_expanded_candidate_relevance_calibration_samples(
            baseline_observations
        )
        calibration = calibrator(
            candidate_samples,
            dataset_id=str(_mapping(source.get("dataset"))["dataset_id"]),
            dataset_sha256=str(_mapping(source.get("dataset"))["dataset_sha256"]),
            expected_binding=_mapping(source.get("binding")),
            pipeline_repeatability=pipeline_repeatability,
            numeric_tolerance=float(provenance["numeric_tolerance"]),
            signal_fields=EXPANDED_CANDIDATE_SIGNAL_FIELDS,
            policy_id=EXPANDED_CANDIDATE_RELEVANCE_POLICY_ID,
            signal_tolerances={
                "reranker_score": float(provenance["numeric_tolerance"]),
                "vector_similarity_quality": VECTOR_SIMILARITY_TOLERANCE,
            },
        )
        signal_contract = _signal_contract()
        source_checks = _mapping(source.get("checks"))
        calibration_status = calibration.get("status")
        decision_complete = calibration_status in {
            "FROZEN",
            "NO_ACCEPTABLE_POLICY",
        }
        frozen_policy = _mapping(calibration.get("frozen_policy"))
        checks = {
            "source_live_collection_passed": source.get("status") == "PASS",
            "actual_test_database_verified": source_checks.get(
                "test_database_identity"
            )
            is True,
            "same_corpus_repeat_collection_complete": (
                repeat_collection.get("repeat_count") == REPEAT_COUNT
                and repeat_collection.get("retrieval_request_count") == 200
                and repeat_collection.get("candidate_observation_count") == 800
                and source_checks.get("repeat_collection_complete") is True
            ),
            "provider_collection_complete": source_checks.get(
                "provider_calls_complete"
            )
            is True,
            "pipeline_and_expanded_signals_repeatable": (
                pipeline_repeatability.get("status") == "STABLE"
            ),
            "expanded_signal_contract_exact": (
                _mapping(calibration.get("search")).get("signal_fields")
                == list(EXPANDED_CANDIDATE_SIGNAL_FIELDS)
                and signal_contract["truth_or_permission_signal_included"] is False
            ),
            "candidate_relevance_decision_complete": decision_complete,
            "holdout_remained_sealed": (
                calibration.get("holdout_access_permitted") is False
                and _mapping(calibration.get("holdout")).get("status")
                == "SEALED_NOT_OPENED"
                and _mapping(source.get("dataset")).get("holdout_status")
                == "SEALED_NOT_COLLECTED"
            ),
            "runtime_activation_prohibited": (
                calibration.get("runtime_activation_permitted") is False
                and (
                    not frozen_policy
                    or frozen_policy.get("runtime_activation_permitted") is False
                )
            ),
            "restart_readback_exact": source_checks.get("restart_readback_exact")
            is True,
            "cleanup_complete": source_checks.get("cleanup_complete") is True,
        }
        failed_checks = [name for name, passed in checks.items() if not passed]
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "PASS" if not failed_checks else "FAIL",
            "failure_code": (
                None
                if not failed_checks
                else "candidate_relevance_signal_expansion_failed"
            ),
            "service_id": source.get("service_id"),
            "profile": source.get("profile"),
            "redacted_database_url": source.get("redacted_database_url"),
            "migration": source.get("migration"),
            "dataset": source.get("dataset"),
            "binding": source.get("binding"),
            "provider_observation": source.get("provider_observation"),
            "provider_request_counts": source.get("provider_request_counts"),
            "source_collection": {
                "repeat_count": repeat_collection.get("repeat_count"),
                "retrieval_request_count": repeat_collection.get(
                    "retrieval_request_count"
                ),
                "candidate_observation_count": repeat_collection.get(
                    "candidate_observation_count"
                ),
                "baseline_candidate_sample_count": len(candidate_samples),
            },
            "signal_contract": signal_contract,
            "provenance": provenance,
            "pipeline_repeatability": pipeline_repeatability,
            "candidate_relevance_calibration": calibration,
            "decision": {
                "status": calibration_status,
                "next_action": (
                    "ORIGINAL_S20Q_HOLDOUT_ACCEPTANCE"
                    if calibration_status == "FROZEN"
                    else "CONTROLLED_RERANKER_REVISION_AB"
                ),
            },
            "persistence": source.get("persistence"),
            "checks": checks,
            "failed_checks": failed_checks,
        }
    except s20qh.S20QHError as exc:
        result = s20qh._failure(exc.failure_code, detail=exc.detail)
        result["evidence_schema_version"] = SCHEMA_VERSION
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = s20qh._failure(
            "candidate_relevance_signal_expansion_execution_failed",
            detail={"exception": exc.__class__.__name__, "message": str(exc)[:160]},
        )
        result["evidence_schema_version"] = SCHEMA_VERSION
    s20qe._assert_redacted(result, env)
    return result


def _signal_contract() -> dict[str, Any]:
    contract = {
        "historical_signals": [
            "reranker_score",
            "rrf_normalized_score",
            "channel_rank_quality",
        ],
        "added_signals": [
            "bm25_score_quality",
            "vector_similarity_quality",
        ],
        "bm25_score_quality": "PACKAGE_LOCAL_SCORE_DIVIDED_BY_PACKAGE_MAXIMUM",
        "vector_similarity_quality": "CLAMP_COSINE_SIMILARITY_TO_ZERO_ONE",
        "vector_similarity_tolerance": VECTOR_SIMILARITY_TOLERANCE,
        "missing_channel_quality": 0.0,
        "maximum_selected_signal_count": 3,
        "truth_or_permission_signal_included": False,
    }
    return {**contract, "contract_hash": semantic_sha256_hash_ref(contract)}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "PASS":
        decision = _mapping(result.get("decision"))
        return (
            "gb2_s20qi_signal_expansion=pass "
            f"decision={decision.get('status')} holdout=sealed"
        )
    if result.get("status") == "SKIPPED":
        return f"gb2_s20qi_signal_expansion=skipped reason={SMOKE_ENV}"
    return (
        "gb2_s20qi_signal_expansion=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qi_candidate_relevance_signal_expansion()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
