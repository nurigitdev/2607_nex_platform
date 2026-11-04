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

from nex_cx.retrieval_answer_support_fresh_calibration import (
    admit_fresh_calibration_dataset,
    build_fresh_calibration_dataset,
)

SCHEMA_VERSION = "gb2_s20qpm_fresh_calibration_admission.v1"
SMOKE_ENV = "NEX_GB2_S20QPM_FRESH_CALIBRATION_ADMISSION"
PROFILE_ENV = "NEX_GB2_S20QPM_PROFILE"
P_L_SOURCE_ENV = "NEX_GB2_S20QPM_P_L_EVIDENCE"
P_L_SOURCE_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpl_canonical_profile_freeze.json"
)
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_answer_support_fresh_calibration_v1_design.json"
)
PREDECESSOR_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4.json"
)
OUTPUT_PATH = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpm_fresh_calibration_admission.json"
)

Builder = Callable[..., dict[str, Any]]
Admitter = Callable[..., dict[str, Any]]


def run_gb2_s20qpm_fresh_calibration_admission(
    environ: Mapping[str, str] | None = None,
    *,
    p_l_source: Mapping[str, Any] | None = None,
    design: Mapping[str, Any] | None = None,
    predecessor_cases: Sequence[Mapping[str, Any]] | None = None,
    builder: Builder = build_fresh_calibration_dataset,
    admitter: Admitter = admit_fresh_calibration_dataset,
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
        source = (
            dict(p_l_source)
            if p_l_source is not None
            else _load(Path(env.get(P_L_SOURCE_ENV, str(P_L_SOURCE_PATH))))
        )
        design_value = dict(design) if design is not None else _load(DESIGN_PATH)
        predecessor = (
            list(predecessor_cases)
            if predecessor_cases is not None
            else list(_load(PREDECESSOR_PATH)["cases"])
        )
        freeze = _mapping(source.get("freeze"), "P-L freeze")
        dataset = builder(design_value, p_l_freeze=freeze)
        admission = admitter(
            dataset,
            design=design_value,
            p_l_freeze=freeze,
            predecessor_cases=predecessor,
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            "fresh_calibration_admission_failed",
            detail={"exception": exc.__class__.__name__},
        )

    checks = {
        "p_l_evidence_passed": source.get("status") == "PASS",
        "fresh_dataset_admitted": admission.get("status")
        == "ADMITTED_FRESH_CALIBRATION_ONLY",
        "scenario_count_complete": admission.get("scenario_count") == 100,
        "package_count_complete": admission.get("package_count") == 200,
        "candidate_count_complete": admission.get("candidate_count") == 800,
        "holdout_absent": admission.get("holdout_case_count") == 0,
        "provider_not_called": admission.get("provider_calls") == 0,
        "runtime_activation_prohibited": admission.get(
            "runtime_activation_permitted"
        )
        is False,
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-M",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": "FRESH_CALIBRATION_EXTENSION_ADMITTED_P_N_REQUIRED",
        "new_provider_calls": 0,
        "new_database_calls": 0,
        "admission": admission,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON source must be an object")
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
        admission = result.get("admission")
        admission = admission if isinstance(admission, Mapping) else {}
        return (
            "gb2_s20qpm_fresh_calibration_admission=pass "
            f"scenarios={admission.get('scenario_count')} "
            f"packages={admission.get('package_count')} "
            f"dataset_hash={admission.get('dataset_hash')} holdout=absent"
        )
    if status == "skipped":
        return "gb2_s20qpm_fresh_calibration_admission=skipped"
    return (
        "gb2_s20qpm_fresh_calibration_admission=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpm_fresh_calibration_admission()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
