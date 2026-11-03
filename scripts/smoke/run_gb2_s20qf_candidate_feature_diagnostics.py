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

SCHEMA_VERSION = "gb2_s20qf_candidate_feature_diagnostics.v1"
SMOKE_ENV = "NEX_GB2_S20QF_LIVE_SMOKE"
Collector = Callable[..., Mapping[str, Any]]


def run_gb2_s20qf_candidate_feature_diagnostics(
    environ: Mapping[str, str] | None = None,
    *,
    requester: s20qe.HttpRequester | None = None,
    collector: Collector = s20qe.run_gb2_s20qe_v3_calibration_collection,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    source = collector(
        {**env, s20qe.SMOKE_ENV: "1"},
        requester=requester,
    )
    if source.get("status") != "PASS":
        return _failure(
            "source_collection_failed",
            detail={
                "status": source.get("status"),
                "failure_code": source.get("failure_code"),
            },
        )

    diagnostics = _mapping(source.get("candidate_feature_diagnostics"))
    source_checks = _mapping(source.get("checks"))
    dataset = _mapping(source.get("dataset"))
    collection = _mapping(source.get("collection"))
    feature_set = _mapping(diagnostics.get("feature_set_correction"))
    checks = {
        "source_live_collection_passed": source.get("status") == "PASS",
        "actual_test_database_verified": source_checks.get("test_database_identity")
        is True,
        "provider_collection_complete": source_checks.get("provider_calls_complete")
        is True,
        "restart_readback_exact": source_checks.get("restart_readback_exact") is True,
        "cleanup_complete": source_checks.get("cleanup_complete") is True,
        "candidate_diagnostics_complete": source_checks.get(
            "candidate_diagnostics_complete"
        )
        is True,
        "calibration_partition_only": (
            diagnostics.get("dataset", {}).get("partition") == "CALIBRATION"
        ),
        "holdout_remained_sealed": (
            diagnostics.get("holdout_access_permitted") is False
            and dataset.get("holdout_status") == "SEALED_NOT_COLLECTED"
        ),
        "no_policy_selection_or_activation": (
            diagnostics.get("runtime_activation_permitted") is False
            and diagnostics.get("feature_selection_permitted") is False
            and diagnostics.get("weight_selection_permitted") is False
            and diagnostics.get("threshold_selection_permitted") is False
        ),
        "corrected_candidates_declared": (
            isinstance(feature_set.get("corrected_candidate_fields"), list)
            and bool(feature_set.get("corrected_candidate_fields"))
            and feature_set.get("selection_deferred_to") == "GB2-CA00-S20Q-G"
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        return _failure("candidate_diagnostic_checks_failed", detail=failed_checks)

    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": source.get("service_id"),
        "profile": source.get("profile"),
        "redacted_database_url": source.get("redacted_database_url"),
        "migration": source.get("migration"),
        "dataset": dataset,
        "binding": source.get("binding"),
        "provider_observation": source.get("provider_observation"),
        "provider_request_counts": source.get("provider_request_counts"),
        "source_collection": {
            "sample_count": collection.get("sample_count"),
            "ready_count": collection.get("ready_count"),
            "low_confidence_count": collection.get("low_confidence_count"),
            "sample_set_hash": collection.get("sample_set_hash"),
        },
        "candidate_feature_diagnostics": diagnostics,
        "persistence": source.get("persistence"),
        "checks": checks,
        "failed_checks": failed_checks,
    }


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
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        diagnostics = _mapping(result.get("candidate_feature_diagnostics"))
        feature_set = _mapping(diagnostics.get("feature_set_correction"))
        return (
            "gb2_s20qf_candidate_feature_diagnostics=pass "
            f"directional={len(feature_set.get('directional_corrected_candidates', []))} "
            "holdout=sealed"
        )
    if status == "skipped":
        return "gb2_s20qf_candidate_feature_diagnostics=skipped"
    return (
        "gb2_s20qf_candidate_feature_diagnostics=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qf_candidate_feature_diagnostics()
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
