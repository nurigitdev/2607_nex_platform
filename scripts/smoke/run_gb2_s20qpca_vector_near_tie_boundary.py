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

import run_gb2_s20qpc_probability_nested_calibration as s20qpc
from nex_cx.vector_ordering import (
    VECTOR_NEAR_TIE_MAX_SCORE_DELTA,
    VECTOR_NEAR_TIE_ORDERING_POLICY_ID,
)
from nex_cx.vector_score_policy import (
    VECTOR_SIMILARITY_NUMERIC_EQUIVALENCE_DELTA,
    VECTOR_SIMILARITY_NUMERIC_EQUIVALENCE_POLICY_ID,
)

SCHEMA_VERSION = "gb2_s20qpca_vector_near_tie_boundary.v1"
SMOKE_ENV = "NEX_GB2_S20QPCA_VECTOR_NEAR_TIE_BOUNDARY"
PROFILE_ENV = "NEX_GB2_S20QPCA_PROFILE"

ParentRunner = Callable[..., dict[str, Any]]


def run_gb2_s20qpca_vector_near_tie_boundary(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    parent_runner: ParentRunner = (
        s20qpc.run_gb2_s20qpc_probability_nested_calibration
    ),
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
            s20qpc.SMOKE_ENV: "1",
            s20qpc.PROFILE_ENV: "test",
        },
        requester=requester,
    )
    repeatability = _mapping(source.get("pipeline_repeatability"))
    stages = _mapping(repeatability.get("stages"))
    tolerances = _mapping(repeatability.get("tolerances"))
    nested = _mapping(source.get("nested_selection"))
    package_ready = _mapping(source.get("package_ready_repeatability"))
    raw_vector_changes = int(stages.get("vector_rank_change_count", -1))
    bounded_vector_changes = int(
        stages.get("bounded_vector_rank_exchange_count", -1)
    )
    unbounded_vector_changes = int(
        stages.get("unbounded_vector_rank_change_count", -1)
    )
    raw_rrf_drifts = int(stages.get("rrf_score_drift_count", -1))
    bounded_rrf_drifts = int(stages.get("bounded_rrf_score_drift_count", -1))
    unbounded_rrf_drifts = int(stages.get("unbounded_rrf_score_drift_count", -1))
    checks = {
        "parent_probability_calibration_passed": source.get("status") == "PASS",
        "actual_test_database_identity": source.get("database_identity")
        == {"database": "nex_cx_test", "role": "nex_cx_user"},
        "ordering_boundary_not_expanded": (
            VECTOR_NEAR_TIE_MAX_SCORE_DELTA == 0.001
            and VECTOR_NEAR_TIE_ORDERING_POLICY_ID.endswith("_v1")
        ),
        "numeric_equivalence_tolerance_bound": (
            VECTOR_SIMILARITY_NUMERIC_EQUIVALENCE_DELTA
            == tolerances.get("vector_similarity_quality")
            == 0.005
        ),
        "five_run_pipeline_repeatability_stable": (
            repeatability.get("status") == "STABLE"
            and _mapping(repeatability.get("measurement")).get("repeat_count")
            == 5
        ),
        "raw_vector_changes_preserved": (
            raw_vector_changes
            == bounded_vector_changes + unbounded_vector_changes
            and raw_vector_changes >= 0
        ),
        "raw_rrf_drifts_preserved": (
            raw_rrf_drifts == bounded_rrf_drifts + unbounded_rrf_drifts
            and raw_rrf_drifts >= 0
        ),
        "unbounded_vector_changes_absent": unbounded_vector_changes == 0,
        "unbounded_rrf_drifts_absent": unbounded_rrf_drifts == 0,
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
        "package_ready_repeatability_fail_closed": (
            package_ready.get("status")
            in {"STABLE", "NOT_APPLICABLE_PROFILE_NOT_ADMITTED"}
            and package_ready.get("runtime_activation_permitted") is False
            and package_ready.get("holdout_access_permitted") is False
        ),
    }
    return {
        **source,
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-C-A",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "ordering_policy": {
            "policy_id": VECTOR_NEAR_TIE_ORDERING_POLICY_ID,
            "numeric_equivalence_policy_id": (
                VECTOR_SIMILARITY_NUMERIC_EQUIVALENCE_POLICY_ID
            ),
            "maximum_score_delta": VECTOR_NEAR_TIE_MAX_SCORE_DELTA,
            "raw_score_preserved": True,
            "stable_identity_fields": [
                "content_object_id",
                "chunk_id",
                "vector_index_id",
            ],
        },
        "uncertainty_aware_classification": {
            "raw_vector_rank_change_count": raw_vector_changes,
            "bounded_vector_rank_exchange_count": bounded_vector_changes,
            "unbounded_vector_rank_change_count": unbounded_vector_changes,
            "raw_rrf_score_drift_count": raw_rrf_drifts,
            "bounded_rrf_score_drift_count": bounded_rrf_drifts,
            "unbounded_rrf_score_drift_count": unbounded_rrf_drifts,
            "raw_changes_preserved": True,
        },
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
        stages = _mapping(
            _mapping(result.get("pipeline_repeatability")).get("stages")
        )
        return (
            "gb2_s20qpca_vector_near_tie_boundary=pass "
            f"vector_raw={stages.get('vector_rank_change_count')} "
            f"vector_bounded={stages.get('bounded_vector_rank_exchange_count')} "
            f"rrf_raw={stages.get('rrf_score_drift_count')} "
            f"rrf_bounded={stages.get('bounded_rrf_score_drift_count')} "
            "unbounded=0 holdout=sealed"
        )
    if status == "skipped":
        return "gb2_s20qpca_vector_near_tie_boundary=skipped"
    return (
        "gb2_s20qpca_vector_near_tie_boundary=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpca_vector_near_tie_boundary()
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
