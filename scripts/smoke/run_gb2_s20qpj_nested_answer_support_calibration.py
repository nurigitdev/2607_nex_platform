#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "quality",
):
    sys.path.insert(0, str(path))

from check_retrieval_calibration_v4_dataset import (
    DEFAULT_DATASET_PATH,
    check_retrieval_calibration_v4_dataset,
)
from nex_cx.retrieval_answer_support_nested_selection import (
    build_answer_support_nested_samples,
    select_nested_answer_support_profile,
)

SCHEMA_VERSION = "gb2_s20qpj_nested_answer_support_calibration.v1"
SMOKE_ENV = "NEX_GB2_S20QPJ_NESTED_ANSWER_SUPPORT_CALIBRATION"
PROFILE_ENV = "NEX_GB2_S20QPJ_PROFILE"
SOURCE_ENV = "NEX_GB2_S20QPJ_SOURCE_EVIDENCE"
DEFAULT_SOURCE = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpi_answer_support_calibration_collection.json"
)
DATA = ROOT / "scripts" / "smoke" / "data"
DESIGN_PATH = DATA / "s136_answer_support_nested_calibration_v1_design.json"
FOLD_PATH = DATA / "s136_retrieval_package_calibration_v4_folds.json"
OUTPUT_PATH = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpj_nested_answer_support_calibration.json"
)
EXPECTED_PACKAGES = 160
EXPECTED_SCENARIOS = 80
EXPECTED_INNER_TRAINING_PACKAGES = 96

SampleBuilder = Callable[
    [Mapping[str, Any], Sequence[Mapping[str, Any]]], list[dict[str, Any]]
]
Selector = Callable[..., dict[str, Any]]


def run_gb2_s20qpj_nested_answer_support_calibration(
    environ: Mapping[str, str] | None = None,
    *,
    source: Mapping[str, Any] | None = None,
    sample_builder: SampleBuilder = build_answer_support_nested_samples,
    selector: Selector = select_nested_answer_support_profile,
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
        try:
            source = _load(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return _failure(
                "source_evidence_invalid",
                detail={"exception": exc.__class__.__name__},
            )
    try:
        admission = check_retrieval_calibration_v4_dataset()
        dataset = _load(DEFAULT_DATASET_PATH)
        design = _load(DESIGN_PATH)
        fold_plan = _load(FOLD_PATH)
        collection = _mapping(source.get("collection"), "P-I collection")
        collection_dataset = _mapping(collection.get("dataset"), "collection dataset")
        samples = sample_builder(collection, dataset["cases"])
        selection = selector(
            samples,
            dataset_id=str(admission["dataset_id"]),
            dataset_sha256=str(admission["dataset_sha256"]),
            collection_hash=str(collection["collection_hash"]),
            provider_binding=_mapping(
                collection.get("provider_binding"), "provider binding"
            ),
            design=design,
            fold_plan=fold_plan,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return _failure(
            "nested_calibration_failed",
            detail={"exception": exc.__class__.__name__},
        )

    selection_dataset = _mapping(selection.get("dataset"), "selection dataset")
    holdout = _mapping(selection.get("holdout"), "selection holdout")
    source_checks = _mapping(source.get("checks"), "P-I checks")
    checks = {
        "p_i_collection_passed": source.get("status") == "PASS"
        and source.get("decision") == "CALIBRATION_EVIDENCE_COLLECTED_P_J_REQUIRED",
        "p_i_checks_all_passed": bool(source_checks)
        and all(value is True for value in source_checks.values()),
        "v4_dataset_immutable_admission_passed": admission.get("status") == "PASS",
        "dataset_binding_matches_p_i": (
            collection_dataset.get("dataset_id") == admission.get("dataset_id")
            and collection_dataset.get("dataset_sha256")
            == admission.get("dataset_sha256")
        ),
        "calibration_scope_complete": (
            selection_dataset.get("scenario_count") == EXPECTED_SCENARIOS
            and selection_dataset.get("package_count") == EXPECTED_PACKAGES
        ),
        "nested_selection_completed_fail_closed": selection.get("status")
        in {"CALIBRATION_OOF_ADMITTED", "NO_ADMISSIBLE_PROFILE"},
        "inner_threshold_fit_is_fold_local": _inner_training_counts(selection)
        == {EXPECTED_INNER_TRAINING_PACKAGES},
        "source_actual_test_database_identity": source.get(
            "source_database_identity"
        )
        == {"database": "nex_cx_test", "role": "nex_cx_user"},
        "immutable_generation_revision_preserved": (
            _mapping(
                collection.get("provider_binding"), "provider binding"
            ).get("model_revision")
            == source.get("artifact_revision")
        ),
        "holdout_remained_sealed": (
            selection.get("holdout_access_permitted") is False
            and holdout.get("status") == "SEALED_NOT_OPENED"
            and collection_dataset.get("holdout_status") == "SEALED_NOT_ACCESSED"
        ),
        "runtime_activation_prohibited": selection.get(
            "runtime_activation_permitted"
        )
        is False,
    }
    admitted = selection.get("status") == "CALIBRATION_OOF_ADMITTED"
    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-J",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": (
            "CALIBRATION_OOF_ADMITTED_KEEP_HOLDOUT_SEALED"
            if admitted
            else "NO_ADMISSIBLE_PROFILE_KEEP_HOLDOUT_SEALED"
        ),
        "new_provider_calls": 0,
        "new_database_calls": 0,
        "source_provider_evaluation_count": source.get(
            "provider_evaluation_count"
        ),
        "source_collection_hash": collection.get("collection_hash"),
        "selection": selection,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
    try:
        _assert_text_free(result, dataset)
    except ValueError:
        return _failure("protected_evidence_contains_source_text")
    return result


def _inner_training_counts(selection: Mapping[str, Any]) -> set[int]:
    return {
        int(fold["training_package_count"])
        for outer in selection.get("outer_folds", [])
        if isinstance(outer, Mapping)
        for profile in outer.get("inner_selection", [])
        if isinstance(profile, Mapping)
        for fold in profile.get("inner_folds", [])
        if isinstance(fold, Mapping) and "training_package_count" in fold
    }


def _assert_text_free(evidence: object, dataset: Mapping[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise TypeError("Dataset v4 cases are invalid")
    protected = [str(case["query"]) for case in cases]
    protected.extend(
        str(candidate["text"])
        for case in cases
        for candidate in case["candidates"]
    )
    if any(value in serialized for value in protected):
        raise ValueError("P-J evidence contains source text")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("evidence must be a JSON object")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        selection = result.get("selection")
        selection = selection if isinstance(selection, Mapping) else {}
        evaluation = selection.get("oof_evaluation")
        evaluation = evaluation if isinstance(evaluation, Mapping) else {}
        metrics = evaluation.get("metrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        return (
            "gb2_s20qpj_nested_answer_support_calibration=pass "
            f"selection={selection.get('status')} "
            f"ready_recall={metrics.get('ready_recall')} "
            f"false_ready={metrics.get('false_ready_rate')} "
            f"stable_folds={evaluation.get('stable_profile_fold_count')} "
            "holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpj_nested_answer_support_calibration=skipped"
    return (
        "gb2_s20qpj_nested_answer_support_calibration=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpj_nested_answer_support_calibration()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        f"{json.dumps(result, indent=2, sort_keys=True)}\n", encoding="utf-8"
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
