#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_expanded_candidate_relevance_calibration_samples,
)
from nex_cx.retrieval_package_ordinal_nested_selection import (
    select_nested_package_ordinal_profile,
)

SCHEMA_VERSION = "gb2_s20qpf_nested_package_ordinal_calibration.v1"
SMOKE_ENV = "NEX_GB2_S20QPF_NESTED_PACKAGE_ORDINAL_CALIBRATION"
PROFILE_ENV = "NEX_GB2_S20QPF_PROFILE"
SOURCE_ENV = "NEX_GB2_S20QPF_SOURCE_EVIDENCE"
DEFAULT_SOURCE = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpca_vector_near_tie_boundary.json"
)
DATA = ROOT / "scripts" / "smoke" / "data"
RETRIEVAL_DESIGN_PATH = DATA / "s136_retrieval_package_calibration_v4_design.json"
FOLD_PATH = DATA / "s136_retrieval_package_calibration_v4_folds.json"
ORDINAL_DESIGN_PATH = DATA / "s136_package_ordinal_calibrator_v1_design.json"


def run_gb2_s20qpf_nested_package_ordinal_calibration(
    environ: Mapping[str, str] | None = None,
    *,
    source: Mapping[str, Any] | None = None,
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
    if source is None:
        path = Path(env.get(SOURCE_ENV, str(DEFAULT_SOURCE)))
        if not path.is_file():
            return _failure("source_evidence_missing")
        source = json.loads(path.read_text(encoding="utf-8"))
    runs = _mapping(source.get("repeat_collection")).get("runs")
    first_run = runs[0] if isinstance(runs, list) and runs else None
    observations = _mapping(first_run).get("candidate_observations")
    if not isinstance(observations, list):
        return _failure("candidate_observations_missing")
    samples = build_expanded_candidate_relevance_calibration_samples(observations)
    dataset = _mapping(source.get("dataset"))
    selection = select_nested_package_ordinal_profile(
        samples,
        dataset_id=str(dataset.get("dataset_id")),
        dataset_sha256=str(dataset.get("dataset_sha256")),
        retrieval_design=_load(RETRIEVAL_DESIGN_PATH),
        fold_plan=_load(FOLD_PATH),
        ordinal_design=_load(ORDINAL_DESIGN_PATH),
        expected_binding=_mapping(source.get("binding")),
    )
    repeatability = _mapping(source.get("pipeline_repeatability"))
    checks = {
        "source_execution_passed": source.get("status") == "PASS",
        "actual_test_database_identity": source.get("database_identity")
        == {"database": "nex_cx_test", "role": "nex_cx_user"},
        "uncertainty_aware_repeatability_stable": repeatability.get("status")
        == "STABLE",
        "nested_selection_completed_fail_closed": selection.get("status")
        in {"CALIBRATION_OOF_ADMITTED", "NO_ADMISSIBLE_PROFILE"},
        "candidate_probability_fit_is_inner_fold_local": _inner_counts(selection)
        == {384},
        "holdout_remained_sealed": (
            selection.get("holdout_access_permitted") is False
            and _mapping(selection.get("holdout")).get("status")
            == "SEALED_NOT_OPENED"
            and dataset.get("holdout_status") == "SEALED_NOT_COLLECTED"
        ),
        "runtime_activation_prohibited": selection.get(
            "runtime_activation_permitted"
        )
        is False,
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-F",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": (
            "CALIBRATION_OOF_PROFILE_AVAILABLE_P_G_REQUIRED"
            if selection.get("status") == "CALIBRATION_OOF_ADMITTED"
            else "NO_ADMISSIBLE_PROFILE_STOP_BEFORE_P_G"
        ),
        "provider_calls": 0,
        "database_calls": 0,
        "source_provider_request_counts": source.get("provider_request_counts"),
        "holdout_opened": False,
        "selection": selection,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _inner_counts(selection: Mapping[str, Any]) -> set[int]:
    return {
        int(fold["candidate_probability_training_candidate_count"])
        for outer in selection.get("outer_folds", [])
        if isinstance(outer, Mapping)
        for combination in outer.get("inner_selection", [])
        if isinstance(combination, Mapping)
        for fold in combination.get("inner_folds", [])
        if isinstance(fold, Mapping)
        and "candidate_probability_training_candidate_count" in fold
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _failure(code: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        selection = _mapping(result.get("selection"))
        metrics = _mapping(_mapping(selection.get("oof_evaluation")).get("metrics"))
        return (
            "gb2_s20qpf_nested_package_ordinal_calibration=pass "
            f"selection={selection.get('status')} "
            f"ready_recall={metrics.get('ready_recall')} "
            f"false_ready={metrics.get('false_ready_rate')} "
            "holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpf_nested_package_ordinal_calibration=skipped"
    return (
        "gb2_s20qpf_nested_package_ordinal_calibration=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpf_nested_package_ordinal_calibration()
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
