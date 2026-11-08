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
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_canonical_calibration import (
    calibrate_canonical_answer_support_threshold,
)
from nex_cx.retrieval_answer_support_fresh_calibration import (
    build_fresh_calibration_dataset,
)
from nex_cx.retrieval_answer_support_nested_selection import (
    build_answer_support_nested_samples,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

SCHEMA_VERSION = "gb2_s20qpo_canonical_threshold_admission.v1"
SMOKE_ENV = "NEX_GB2_S20QPO_CANONICAL_THRESHOLD_ADMISSION"
PROFILE_ENV = "NEX_GB2_S20QPO_PROFILE"
P_L_SOURCE_ENV = "NEX_GB2_S20QPO_P_L_EVIDENCE"
P_M_SOURCE_ENV = "NEX_GB2_S20QPO_P_M_EVIDENCE"
P_N_SOURCE_ENV = "NEX_GB2_S20QPO_P_N_EVIDENCE"
LIVE = ROOT / "reports" / "live"
P_L_SOURCE_PATH = LIVE / "gb2_ca00_s20qpl_canonical_profile_freeze.json"
P_M_SOURCE_PATH = LIVE / "gb2_ca00_s20qpm_fresh_calibration_admission.json"
P_N_SOURCE_PATH = LIVE / "gb2_ca00_s20qpn_fresh_answer_support_collection.json"
DATA = ROOT / "scripts" / "smoke" / "data"
CANONICAL_DESIGN_PATH = DATA / "s136_answer_support_canonical_profile_v2_design.json"
FRESH_DESIGN_PATH = DATA / "s136_answer_support_fresh_calibration_v1_design.json"
CALIBRATION_DESIGN_PATH = (
    DATA / "s136_answer_support_canonical_calibration_v1_design.json"
)
OUTPUT_PATH = LIVE / "gb2_ca00_s20qpo_canonical_threshold_admission.json"

Builder = Callable[..., dict[str, Any]]
SampleBuilder = Callable[
    [Mapping[str, Any], Sequence[Mapping[str, Any]]], list[dict[str, Any]]
]
Calibrator = Callable[..., dict[str, Any]]


def run_gb2_s20qpo_canonical_threshold_admission(
    environ: Mapping[str, str] | None = None,
    *,
    p_l_source: Mapping[str, Any] | None = None,
    p_m_source: Mapping[str, Any] | None = None,
    p_n_source: Mapping[str, Any] | None = None,
    canonical_design: Mapping[str, Any] | None = None,
    fresh_design: Mapping[str, Any] | None = None,
    calibration_design: Mapping[str, Any] | None = None,
    builder: Builder = build_fresh_calibration_dataset,
    sample_builder: SampleBuilder = build_answer_support_nested_samples,
    calibrator: Calibrator = calibrate_canonical_answer_support_threshold,
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
    try:
        p_l = _source(p_l_source, env.get(P_L_SOURCE_ENV), P_L_SOURCE_PATH)
        p_m = _source(p_m_source, env.get(P_M_SOURCE_ENV), P_M_SOURCE_PATH)
        p_n = _source(p_n_source, env.get(P_N_SOURCE_ENV), P_N_SOURCE_PATH)
        canonical = (
            dict(canonical_design)
            if canonical_design is not None
            else _load(CANONICAL_DESIGN_PATH)
        )
        fresh = (
            dict(fresh_design)
            if fresh_design is not None
            else _load(FRESH_DESIGN_PATH)
        )
        calibration = (
            dict(calibration_design)
            if calibration_design is not None
            else _load(CALIBRATION_DESIGN_PATH)
        )
        freeze = _mapping(p_l.get("freeze"), "P-L freeze")
        dataset = builder(fresh, p_l_freeze=freeze)
        collection = _mapping(p_n.get("collection"), "P-N collection")
        samples = sample_builder(collection, dataset["cases"])
        result = calibrator(
            samples,
            dataset_id=str(dataset["dataset_id"]),
            dataset_sha256=semantic_sha256_hash_ref(dataset),
            collection_hash=str(collection["collection_hash"]),
            provider_binding=_mapping(
                collection.get("provider_binding"), "provider binding"
            ),
            artifact_evidence_hash=str(p_n["artifact_evidence_hash"]),
            canonical_design=canonical,
            canonical_freeze=freeze,
            calibration_design=calibration,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return _failure(
            "canonical_threshold_calibration_failed",
            detail={"exception": exc.__class__.__name__},
        )

    p_n_checks = _mapping(p_n.get("checks"), "P-N checks")
    candidate = result.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else None
    decision_valid = result.get("status") in {
        "CALIBRATION_THRESHOLD_CANDIDATE_ADMITTED",
        "NO_ADMISSIBLE_THRESHOLD",
    }
    checks = {
        "p_l_profile_freeze_passed": p_l.get("status") == "PASS",
        "p_m_dataset_admission_passed": p_m.get("status") == "PASS",
        "p_n_provider_collection_passed": p_n.get("status") == "PASS"
        and bool(p_n_checks)
        and all(value is True for value in p_n_checks.values()),
        "fresh_dataset_binding_preserved": p_m.get("admission", {}).get(
            "dataset_hash"
        )
        == result.get("dataset", {}).get("dataset_sha256"),
        "single_canonical_profile_only": result.get("protocol", {}).get(
            "profile_count"
        )
        == 1
        and result.get("protocol", {}).get("profile_id")
        == "answer-support-contradiction-aware-v2",
        "threshold_decision_is_fail_closed": decision_valid
        and (
            candidate is not None
            if result.get("status") == "CALIBRATION_THRESHOLD_CANDIDATE_ADMITTED"
            else candidate is None
        ),
        "all_outer_folds_accounted": len(result.get("outer_folds", [])) == 5,
        "holdout_remained_sealed": result.get("holdout_access_permitted") is False
        and result.get("holdout", {}).get("status") == "SEALED_NOT_OPENED",
        "runtime_activation_prohibited": result.get(
            "runtime_activation_permitted"
        )
        is False,
    }
    evidence = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-O",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": (
            "CANONICAL_THRESHOLD_CANDIDATE_ADMITTED_HOLDOUT_REQUIRED"
            if candidate is not None
            else "NO_ADMISSIBLE_THRESHOLD_HOLDOUT_REMAINS_SEALED"
        ),
        "new_provider_calls": 0,
        "new_database_calls": 0,
        "calibration": result,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
    try:
        _assert_text_free(evidence, dataset)
    except ValueError:
        return _failure("protected_evidence_contains_source_text")
    return evidence


def _source(
    value: Mapping[str, Any] | None,
    override: str | None,
    default: Path,
) -> dict[str, Any]:
    return dict(value) if value is not None else _load(Path(override or default))


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("evidence must be a JSON object")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _assert_text_free(evidence: object, dataset: Mapping[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise TypeError("fresh calibration cases are invalid")
    protected = [str(case["query"]) for case in cases]
    protected.extend(
        str(candidate["text"])
        for case in cases
        for candidate in case["candidates"]
    )
    if any(value in serialized for value in protected):
        raise ValueError("P-O evidence contains source text")


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
        calibration = result.get("calibration")
        calibration = calibration if isinstance(calibration, Mapping) else {}
        candidate = calibration.get("candidate")
        candidate = candidate if isinstance(candidate, Mapping) else {}
        metrics = calibration.get("oof_evaluation")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        return (
            "gb2_s20qpo_canonical_threshold_admission=pass "
            f"decision={calibration.get('status')} "
            f"threshold={candidate.get('threshold')} "
            f"auc={metrics.get('package_auc')} holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpo_canonical_threshold_admission=skipped"
    return (
        "gb2_s20qpo_canonical_threshold_admission=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpo_canonical_threshold_admission()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
