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
from nex_cx.retrieval_candidate_relevance_calibration import (
    calibrate_candidate_relevance_policy,
)
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_candidate_relevance_calibration_samples,
)
from nex_cx.retrieval_pipeline_repeatability import (
    analyze_retrieval_pipeline_repeatability,
)
from nex_runtime.semantic_hashes import sha256_text

SCHEMA_VERSION = "gb2_s20qh_pipeline_repeatability_relevance.v1"
SMOKE_ENV = "NEX_GB2_S20QH_LIVE_SMOKE"
REPEAT_COUNT = 5

Collector = Callable[..., Mapping[str, Any]]
RepeatabilityAnalyzer = Callable[..., dict[str, Any]]
Calibrator = Callable[..., dict[str, Any]]


def run_gb2_s20qh_pipeline_repeatability_relevance(
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
            raise S20QHError(
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
            raise S20QHError("repeat_collection_missing")
        pipeline_repeatability = analyzer(
            runs,
            expected_repeat_count=REPEAT_COUNT,
            reranker_score_tolerance=float(provenance["numeric_tolerance"]),
        )
        baseline_observations = runs[0].get("candidate_observations")
        if not isinstance(baseline_observations, list):
            raise S20QHError("baseline_candidate_observations_missing")
        candidate_samples = build_candidate_relevance_calibration_samples(
            baseline_observations
        )
        calibration = calibrator(
            candidate_samples,
            dataset_id=str(_mapping(source.get("dataset"))["dataset_id"]),
            dataset_sha256=str(_mapping(source.get("dataset"))["dataset_sha256"]),
            expected_binding=_mapping(source.get("binding")),
            pipeline_repeatability=pipeline_repeatability,
            numeric_tolerance=float(provenance["numeric_tolerance"]),
        )
        source_checks = _mapping(source.get("checks"))
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
            "pipeline_repeatability_stable": pipeline_repeatability.get("status")
            == "STABLE",
            "candidate_relevance_policy_frozen": calibration.get("status")
            == "FROZEN",
            "holdout_remained_sealed": (
                calibration.get("holdout_access_permitted") is False
                and _mapping(calibration.get("holdout")).get("status")
                == "SEALED_NOT_OPENED"
                and _mapping(source.get("dataset")).get("holdout_status")
                == "SEALED_NOT_COLLECTED"
            ),
            "runtime_activation_prohibited": (
                calibration.get("runtime_activation_permitted") is False
                and _mapping(calibration.get("frozen_policy")).get(
                    "runtime_activation_permitted"
                )
                is False
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
                None if not failed_checks else "pipeline_relevance_calibration_failed"
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
            "provenance": provenance,
            "pipeline_repeatability": pipeline_repeatability,
            "candidate_relevance_calibration": calibration,
            "persistence": source.get("persistence"),
            "checks": checks,
            "failed_checks": failed_checks,
        }
    except S20QHError as exc:
        result = _failure(exc.failure_code, detail=exc.detail)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = _failure(
            "pipeline_relevance_calibration_execution_failed",
            detail={"exception": exc.__class__.__name__, "message": str(exc)[:160]},
        )
    s20qe._assert_redacted(result, env)
    return result


class S20QHError(ValueError):
    def __init__(self, failure_code: str, detail: object | None = None) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.detail = detail


def _failure(failure_code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": failure_code,
    }
    if detail is not None:
        result["detail"] = detail
    return result


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "PASS":
        pipeline = _mapping(result.get("pipeline_repeatability"))
        calibration = _mapping(result.get("candidate_relevance_calibration"))
        return (
            "gb2_s20qh_pipeline_relevance=pass "
            f"repeatability={pipeline.get('status')} "
            f"calibration={calibration.get('status')} holdout=sealed"
        )
    if result.get("status") == "SKIPPED":
        return f"gb2_s20qh_pipeline_relevance=skipped reason={SMOKE_ENV}"
    return (
        "gb2_s20qh_pipeline_relevance=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qh_pipeline_repeatability_relevance()
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
