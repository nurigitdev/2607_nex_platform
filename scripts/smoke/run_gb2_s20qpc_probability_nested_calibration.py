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

import run_gb2_s20qp_v4_nested_calibration as s20qp
from nex_cx.retrieval_calibration_nested_selection import (
    evaluate_candidate_probability_package_repeatability,
    select_nested_candidate_probability_profile,
    select_nested_retrieval_profile,
)
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_expanded_candidate_relevance_calibration_samples,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = "gb2_s20qpc_probability_nested_calibration.v1"
SMOKE_ENV = "NEX_GB2_S20QPC_PROBABILITY_NESTED_CALIBRATION"
PROFILE_ENV = "NEX_GB2_S20QPC_PROFILE"

ParentRunner = Callable[..., dict[str, Any]]


def run_gb2_s20qpc_probability_nested_calibration(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    parent_runner: ParentRunner = s20qp.run_gb2_s20qp_v4_nested_calibration,
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

    source = parent_runner(
        {
            **env,
            s20qp.SMOKE_ENV: "1",
            s20qp.PROFILE_ENV: "test",
        },
        requester=requester,
        selector=_comparison_selector,
    )
    nested = _mapping(source.get("nested_selection"))
    comparison = _mapping(nested.get("baseline_comparison"))
    source_checks = _mapping(source.get("checks"))
    repeatability = _mapping(source.get("pipeline_repeatability"))
    package_ready_repeatability = _package_ready_repeatability(
        source,
        nested=nested,
        repeatability=repeatability,
    )
    inner_counts = [
        int(fold["candidate_probability_training_candidate_count"])
        for outer in nested.get("outer_folds", [])
        if isinstance(outer, Mapping)
        for profile in outer.get("inner_selection", [])
        if isinstance(profile, Mapping)
        for fold in profile.get("inner_folds", [])
        if isinstance(fold, Mapping)
        and "candidate_probability_training_candidate_count" in fold
    ]
    checks = {
        "parent_execution_passed": source.get("status") == "PASS",
        "actual_test_database_identity": source.get("database_identity")
        == {"database": "nex_cx_test", "role": "nex_cx_user"},
        "provider_calls_complete": source_checks.get("provider_calls_complete")
        is True,
        "cleanup_complete": source_checks.get("cleanup_complete") is True,
        "five_run_pipeline_repeatability_stable": (
            repeatability.get("status") == "STABLE"
            and _mapping(repeatability.get("measurement")).get("repeat_count")
            == s20qp.REPEAT_COUNT
        ),
        "probability_nested_selection_completed_fail_closed": nested.get("status")
        in {"CALIBRATION_OOF_ADMITTED", "NO_ADMISSIBLE_PROFILE"},
        "legacy_baseline_compared_same_collection": (
            comparison.get("comparison_scope")
            == "SAME_CALIBRATION_COLLECTION_INNER_DIAGNOSTIC_ONLY"
            and _mapping(comparison.get("legacy_second_highest")).get("status")
            in {"CALIBRATION_OOF_ADMITTED", "NO_ADMISSIBLE_PROFILE"}
        ),
        "candidate_probability_fit_is_inner_fold_local": (
            len(inner_counts) == 5 * 4 * 4 and set(inner_counts) == {384}
        ),
        "package_ready_repeatability_contract_satisfied": (
            package_ready_repeatability.get("status")
            in {"STABLE", "NOT_APPLICABLE_PROFILE_NOT_ADMITTED"}
            and (
                nested.get("status") != "CALIBRATION_OOF_ADMITTED"
                or package_ready_repeatability.get("status") == "STABLE"
            )
        ),
        "holdout_remained_sealed": (
            nested.get("holdout_access_permitted") is False
            and _mapping(nested.get("holdout")).get("status")
            == "SEALED_NOT_OPENED"
            and _mapping(source.get("dataset")).get("holdout_status")
            == "SEALED_NOT_COLLECTED"
        ),
        "runtime_activation_prohibited": (
            nested.get("runtime_activation_permitted") is False
        ),
    }
    result = {
        **source,
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-C",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": (
            "CALIBRATION_OOF_CANDIDATE_AVAILABLE_HOLDOUT_STILL_SEALED"
            if nested.get("status") == "CALIBRATION_OOF_ADMITTED"
            else "NO_ADMISSIBLE_PROFILE_KEEP_HOLDOUT_SEALED"
        ),
        "package_ready_repeatability": package_ready_repeatability,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
    return result


def _package_ready_repeatability(
    source: Mapping[str, Any],
    *,
    nested: Mapping[str, Any],
    repeatability: Mapping[str, Any],
) -> dict[str, Any]:
    repeated_samples: list[list[dict[str, Any]]] = []
    if nested.get("status") == "CALIBRATION_OOF_ADMITTED":
        repeat_collection = _mapping(source.get("repeat_collection"))
        runs = repeat_collection.get("runs")
        if not isinstance(runs, list):
            raise ValueError("candidate probability repeat collection is unavailable")
        for run in runs:
            observations = _mapping(run).get("candidate_observations")
            if not isinstance(observations, list):
                raise TypeError("candidate probability repeat observations are invalid")
            repeated_samples.append(
                build_expanded_candidate_relevance_calibration_samples(
                    observations
                )
            )
    design = json.loads(s20qp.DEFAULT_DESIGN_PATH.read_text(encoding="utf-8"))
    return evaluate_candidate_probability_package_repeatability(
        repeated_samples,
        selection_result=nested,
        design=design,
        expected_binding=_mapping(source.get("binding")),
        expected_repeat_count=int(
            _mapping(repeatability.get("measurement")).get("repeat_count", 5)
        ),
    )


def _comparison_selector(
    samples: list[Mapping[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    legacy = select_nested_retrieval_profile(samples, **kwargs)
    probability = select_nested_candidate_probability_profile(samples, **kwargs)
    result = dict(probability)
    result.pop("selection_hash", None)
    result["baseline_comparison"] = {
        "comparison_scope": "SAME_CALIBRATION_COLLECTION_INNER_DIAGNOSTIC_ONLY",
        "legacy_second_highest": _selection_diagnostic(legacy),
        "candidate_probability_at_least_two": _selection_diagnostic(probability),
        "selection_or_threshold_change_permitted": False,
        "holdout_access_permitted": False,
    }
    result["selection_hash"] = semantic_sha256_hash_ref(result)
    return result


def _selection_diagnostic(selection: Mapping[str, Any]) -> dict[str, Any]:
    rows = [
        profile
        for outer in selection.get("outer_folds", [])
        if isinstance(outer, Mapping)
        for profile in outer.get("inner_selection", [])
        if isinstance(profile, Mapping) and isinstance(profile.get("metrics"), Mapping)
    ]
    return {
        "status": selection.get("status"),
        "selection_hash": selection.get("selection_hash"),
        "profile_fold_diagnostic_count": len(rows),
        "ready_recall_range": _range(rows, "ready_recall"),
        "false_ready_rate_range": _range(rows, "false_ready_rate"),
        "balanced_accuracy_range": _range(rows, "balanced_accuracy"),
        "candidate_auc_range": _range(rows, "candidate_auc", nested=False),
        "oof_evaluation": selection.get("oof_evaluation"),
    }


def _range(
    rows: list[Mapping[str, Any]], field: str, *, nested: bool = True
) -> dict[str, float] | None:
    values = [
        float(_mapping(row.get("metrics")).get(field))
        if nested
        else float(row.get(field))
        for row in rows
    ]
    return (
        {"minimum": round(min(values), 8), "maximum": round(max(values), 8)}
        if values
        else None
    )


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
        comparison = _mapping(nested.get("baseline_comparison"))
        probability = _mapping(comparison.get("candidate_probability_at_least_two"))
        recall = _mapping(probability.get("ready_recall_range"))
        return (
            "gb2_s20qpc_probability_nested_calibration=pass "
            f"selection={nested.get('status')} "
            f"ready_recall_max={recall.get('maximum')} "
            "holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpc_probability_nested_calibration=skipped"
    return (
        "gb2_s20qpc_probability_nested_calibration=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpc_probability_nested_calibration()
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
