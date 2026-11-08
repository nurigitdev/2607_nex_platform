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
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_gb2_s20qe_v3_calibration_collection as s20qe
from check_retrieval_calibration_v4_dataset import (
    DEFAULT_DATASET_PATH,
    DEFAULT_DESIGN_PATH,
    DEFAULT_FOLD_PLAN_PATH,
    check_retrieval_calibration_v4_dataset,
)
from nex_cx.retrieval_calibration_nested_selection import (
    select_nested_retrieval_profile,
)
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_expanded_candidate_relevance_calibration_samples,
)
from nex_cx.retrieval_pipeline_repeatability import (
    analyze_retrieval_pipeline_repeatability,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = "gb2_s20qp_v4_nested_calibration.v1"
SMOKE_ENV = "NEX_GB2_S20QP_V4_NESTED_CALIBRATION"
PROFILE_ENV = "NEX_GB2_S20QP_PROFILE"
REPEAT_COUNT = 5
EXPECTED_SCENARIOS = 80
EXPECTED_PACKAGES = 160
EXPECTED_CANDIDATES = 640
INCUMBENT_EMBEDDING_REVISION = "hf:5cf2132abc99cad020ac570b19d031efec650f2b"
INCUMBENT_RERANKER_REVISION = "hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5"
V4_DATASET_SPEC = s20qe.LiveCalibrationDatasetSpec(
    dataset_path=DEFAULT_DATASET_PATH,
    schema_version="model_calibration_dataset.v4",
    case_count=200,
    calibration_scenario_count=EXPECTED_SCENARIOS,
    holdout_scenario_count=20,
    request_prefix="s20qp",
)

Collector = Callable[..., dict[str, Any]]
Selector = Callable[..., dict[str, Any]]


def run_gb2_s20qp_v4_nested_calibration(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    collector: Collector | None = None,
    selector: Selector = select_nested_retrieval_profile,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(PROFILE_ENV, "test") != "test":
        return _failure("profile_not_allowed")

    def execute(**kwargs: Any) -> dict[str, Any]:
        collect = collector or _execute_v4_collection
        return collect(**kwargs, selector=selector)

    source = s20qe.run_gb2_s20qe_v3_calibration_collection(
        {
            **env,
            "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": env.get(
                "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION",
                INCUMBENT_EMBEDDING_REVISION,
            ),
            "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": env.get(
                "NEX_MO_REMOTE_RERANKER_MODEL_REVISION",
                INCUMBENT_RERANKER_REVISION,
            ),
            s20qe.SMOKE_ENV: "1",
            s20qe.PROFILE_ENV: "test",
            s20qe.REPEAT_COUNT_ENV: str(REPEAT_COUNT),
        },
        requester=requester,
        executor=execute,
    )
    result = {
        **source,
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P",
    }
    _assert_redacted(result, env)
    return result


def _execute_v4_collection(
    *,
    database_url: str,
    database_env: str,
    runtime_environ: dict[str, str],
    requester: Callable[..., Any] | None,
    repeat_count: int,
    selector: Selector,
) -> dict[str, Any]:  # pragma: no cover - PostgreSQL/DGX protected
    if repeat_count != REPEAT_COUNT:
        raise ValueError("v4 nested calibration repeat count drifted")
    admission = check_retrieval_calibration_v4_dataset()
    collection = s20qe._execute_live_collection(
        database_url=database_url,
        database_env=database_env,
        runtime_environ=runtime_environ,
        requester=requester,
        repeat_count=repeat_count,
        dataset_spec=V4_DATASET_SPEC,
        dataset_manifest={
            "dataset_id": admission["dataset_id"],
            "dataset_sha256": admission["dataset_sha256"],
        },
    )
    if collection.get("failed_checks"):
        return collection
    repeat_collection = _mapping(collection.get("repeat_collection"))
    runs = repeat_collection.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("v4 repeated collection is unavailable")
    repeatability = analyze_retrieval_pipeline_repeatability(
        runs,
        expected_repeat_count=REPEAT_COUNT,
        expected_package_count=EXPECTED_PACKAGES,
    )
    baseline_observations = _mapping(runs[0]).get("candidate_observations")
    if not isinstance(baseline_observations, list):
        raise TypeError("v4 baseline candidate observations are unavailable")
    candidate_samples = build_expanded_candidate_relevance_calibration_samples(
        baseline_observations
    )
    design = _read_object(DEFAULT_DESIGN_PATH)
    fold_plan = _read_object(DEFAULT_FOLD_PLAN_PATH)
    nested = selector(
        candidate_samples,
        dataset_id=str(admission["dataset_id"]),
        dataset_sha256=str(admission["dataset_sha256"]),
        design=design,
        fold_plan=fold_plan,
        expected_binding=_mapping(collection.get("binding")),
    )
    admission_checks = {
        "pipeline_repeatability_stable": repeatability.get("status") == "STABLE",
        "nested_calibration_oof_admitted": (
            nested.get("status") == "CALIBRATION_OOF_ADMITTED"
        ),
    }
    calibration_admitted = all(admission_checks.values())
    calibration_admission = {
        "status": "ADMITTED" if calibration_admitted else "REJECTED",
        "checks": admission_checks,
        "holdout_eligible_for_separate_execution": calibration_admitted,
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    checks = dict(_mapping(collection.get("checks")))
    checks.update(
        {
            "v4_immutable_admission_verified": admission["status"] == "PASS",
            "five_run_pipeline_repeatability_measured": (
                repeatability.get("status") in {"STABLE", "UNSTABLE"}
                and _mapping(repeatability.get("measurement")).get("repeat_count")
                == REPEAT_COUNT
            ),
            "calibration_candidate_projection_complete": (
                len(candidate_samples) == EXPECTED_CANDIDATES
                and len({row["sample_id"] for row in candidate_samples})
                == EXPECTED_PACKAGES
            ),
            "nested_selection_completed_fail_closed": nested.get("status")
            in {"CALIBRATION_OOF_ADMITTED", "NO_ADMISSIBLE_PROFILE"},
            "holdout_remained_sealed": (
                nested.get("holdout_access_permitted") is False
                and _mapping(nested.get("holdout")).get("status")
                == "SEALED_NOT_OPENED"
                and _mapping(collection.get("dataset")).get("holdout_status")
                == "SEALED_NOT_COLLECTED"
            ),
            "runtime_activation_prohibited": (
                nested.get("runtime_activation_permitted") is False
            ),
        }
    )
    return {
        **collection,
        "v4_admission": admission,
        "pipeline_repeatability": repeatability,
        "nested_selection": nested,
        "calibration_admission": calibration_admission,
        "provenance": {
            "design_hash": _mapping(fold_plan.get("design")).get("design_hash"),
            "fold_plan_hash": fold_plan.get("fold_plan_hash"),
            "candidate_sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["sample_hash"]) for row in candidate_samples)
            ),
            "provider_scores_used_for_authoring": False,
            "holdout_scores_collected": False,
        },
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _assert_redacted(evidence: object, environ: Mapping[str, str]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    dataset = _read_object(DEFAULT_DATASET_PATH)
    protected = [
        *(str(case["query"]) for case in dataset["cases"]),
        *(
            str(candidate["text"])
            for case in dataset["cases"]
            for candidate in case["candidates"]
        ),
        *(
            str(environ.get(key, ""))
            for key in s20qe.PROTECTED_ENV_KEYS
            if environ.get(key)
        ),
    ]
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("S20Q-P evidence contains protected data")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("calibration artifact must be an object")
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _failure(code: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        nested = _mapping(result.get("nested_selection"))
        oof = _mapping(nested.get("oof_evaluation"))
        admission = _mapping(result.get("calibration_admission"))
        return (
            "gb2_s20qp_v4_nested_calibration=pass "
            f"admission={admission.get('status')} "
            f"selection={nested.get('status')} "
            f"profile={oof.get('stable_profile_id')} holdout=sealed"
        )
    if status == "skipped":
        return "gb2_s20qp_v4_nested_calibration=skipped"
    return (
        "gb2_s20qp_v4_nested_calibration=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qp_v4_nested_calibration()
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
