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
from nex_cx.vector_ordering import (
    VECTOR_NEAR_TIE_MAX_SCORE_DELTA,
    VECTOR_NEAR_TIE_ORDERING_POLICY_ID,
)

SCHEMA_VERSION = "gb2_s20qpa_vector_near_tie_ordering.v1"
SMOKE_ENV = "NEX_GB2_S20QPA_VECTOR_NEAR_TIE_ORDERING"
PROFILE_ENV = "NEX_GB2_S20QPA_PROFILE"

ParentRunner = Callable[..., dict[str, Any]]


def run_gb2_s20qpa_vector_near_tie_ordering(
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
    )
    repeatability = _mapping(source.get("pipeline_repeatability"))
    stages = _mapping(repeatability.get("stages"))
    nested = _mapping(source.get("nested_selection"))
    source_checks = _mapping(source.get("checks"))
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
        "vector_rank_repeatable": stages.get("vector_rank_change_count") == 0,
        "rrf_score_repeatable": stages.get("rrf_score_drift_count") == 0,
        "candidate_membership_repeatable": (
            stages.get("candidate_membership_change_count") == 0
        ),
        "final_rank_repeatable": stages.get("final_rank_change_count") == 0,
        "holdout_remained_sealed": (
            nested.get("holdout_access_permitted") is False
            and _mapping(nested.get("holdout")).get("status")
            == "SEALED_NOT_OPENED"
        ),
        "runtime_activation_prohibited": (
            nested.get("runtime_activation_permitted") is False
        ),
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-A",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "ordering_policy": {
            "policy_id": VECTOR_NEAR_TIE_ORDERING_POLICY_ID,
            "maximum_score_delta": VECTOR_NEAR_TIE_MAX_SCORE_DELTA,
            "raw_score_preserved": True,
            "stable_identity_fields": [
                "content_object_id",
                "chunk_id",
                "vector_index_id",
            ],
        },
        "database_identity": source.get("database_identity"),
        "migration": source.get("migration"),
        "dataset": source.get("dataset"),
        "provider_binding": source.get("binding"),
        "provider_observation": source.get("provider_observation"),
        "provider_request_counts": source.get("provider_request_counts"),
        "pipeline_repeatability": repeatability,
        "calibration_admission": source.get("calibration_admission"),
        "nested_selection_status": nested.get("status"),
        "holdout_status": _mapping(nested.get("holdout")).get("status"),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


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
        repeatability = _mapping(result.get("pipeline_repeatability"))
        stages = _mapping(repeatability.get("stages"))
        return (
            "gb2_s20qpa_vector_near_tie_ordering=pass "
            f"repeatability={repeatability.get('status')} "
            f"vector_rank_changes={stages.get('vector_rank_change_count')} "
            f"rrf_drifts={stages.get('rrf_score_drift_count')} holdout=sealed"
        )
    if status == "skipped":
        return "gb2_s20qpa_vector_near_tie_ordering=skipped"
    return (
        "gb2_s20qpa_vector_near_tie_ordering=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpa_vector_near_tie_ordering()
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
