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
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.retrieval_answer_support_canonical_profile import (
    freeze_canonical_answer_support_profile,
)

SCHEMA_VERSION = "gb2_s20qpl_canonical_profile_freeze.v1"
SMOKE_ENV = "NEX_GB2_S20QPL_CANONICAL_PROFILE_FREEZE"
PROFILE_ENV = "NEX_GB2_S20QPL_PROFILE"
SOURCE_ENV = "NEX_GB2_S20QPL_P_K_EVIDENCE"
SOURCE_PATH = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpk_profile_stability_equivalence_audit.json"
)
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_answer_support_canonical_profile_v2_design.json"
)
OUTPUT_PATH = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpl_canonical_profile_freeze.json"
)

Freezer = Callable[..., dict[str, Any]]


def run_gb2_s20qpl_canonical_profile_freeze(
    environ: Mapping[str, str] | None = None,
    *,
    source: Mapping[str, Any] | None = None,
    design: Mapping[str, Any] | None = None,
    freezer: Freezer = freeze_canonical_answer_support_profile,
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
        source_value = (
            dict(source)
            if source is not None
            else _load(Path(env.get(SOURCE_ENV, str(SOURCE_PATH))))
        )
        design_value = dict(design) if design is not None else _load(DESIGN_PATH)
        audit = _mapping(source_value.get("audit"), "P-K audit")
        freeze = freezer(design_value, p_k_audit=audit)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            "canonical_profile_freeze_failed",
            detail={"exception": exc.__class__.__name__},
        )

    checks = {
        "p_k_evidence_passed": source_value.get("status") == "PASS",
        "canonical_profile_frozen": freeze.get("status")
        == "CANONICAL_PROFILE_FROZEN_FRESH_CALIBRATION_REQUIRED",
        "threshold_remains_unset": freeze.get("canonical_profile", {}).get(
            "threshold"
        )
        is None,
        "fresh_calibration_required": freeze.get("evidence_plan", {}).get(
            "existing_evidence_role"
        )
        == "DIAGNOSTIC_ONLY_NOT_THRESHOLD_ADMISSIBLE",
        "holdout_remains_sealed": freeze.get("holdout_access_permitted") is False,
        "runtime_activation_prohibited": freeze.get(
            "runtime_activation_permitted"
        )
        is False,
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-L",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": "CANONICAL_CONTRADICTION_AWARE_V2_FROZEN",
        "new_provider_calls": 0,
        "new_database_calls": 0,
        "freeze": freeze,
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
        freeze = result.get("freeze")
        freeze = freeze if isinstance(freeze, Mapping) else {}
        profile = freeze.get("canonical_profile")
        profile = profile if isinstance(profile, Mapping) else {}
        return (
            "gb2_s20qpl_canonical_profile_freeze=pass "
            f"profile={profile.get('profile_id')} "
            "threshold=unset holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpl_canonical_profile_freeze=skipped"
    return (
        "gb2_s20qpl_canonical_profile_freeze=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpl_canonical_profile_freeze()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
