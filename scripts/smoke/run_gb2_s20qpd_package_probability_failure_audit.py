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

from nex_cx.retrieval_package_probability_audit import (
    audit_candidate_probability_failure,
)
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_expanded_candidate_relevance_calibration_samples,
)

SCHEMA_VERSION = "gb2_s20qpd_package_probability_failure_audit.v1"
SMOKE_ENV = "NEX_GB2_S20QPD_PACKAGE_PROBABILITY_FAILURE_AUDIT"
PROFILE_ENV = "NEX_GB2_S20QPD_PROFILE"
SOURCE_ENV = "NEX_GB2_S20QPD_SOURCE_EVIDENCE"
DEFAULT_SOURCE = (
    ROOT / "reports" / "live" / "gb2_ca00_s20qpc_probability_nested_calibration.json"
)
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4_design.json"
)


def run_gb2_s20qpd_package_probability_failure_audit(
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
        source_path = Path(env.get(SOURCE_ENV, str(DEFAULT_SOURCE)))
        if not source_path.is_file():
            return _failure("source_evidence_missing")
        source = json.loads(source_path.read_text(encoding="utf-8"))
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    nested = _mapping(source.get("nested_selection"))
    collection = _mapping(source.get("collection"))
    samples = collection.get("candidate_relevance_samples")
    if not isinstance(samples, list):
        runs = _mapping(source.get("repeat_collection")).get("runs")
        first_run = runs[0] if isinstance(runs, list) and runs else None
        observations = _mapping(first_run).get("candidate_observations")
        if isinstance(observations, list):
            samples = build_expanded_candidate_relevance_calibration_samples(
                observations
            )
    if not isinstance(samples, list):
        return _failure("candidate_samples_missing")

    audit = audit_candidate_probability_failure(
        samples,
        profiles=design["selection_protocol"]["profile_shortlist"],
        expected_binding=_mapping(source.get("binding")),
        maximum_false_ready_rate=float(
            design["admission"]["maximum_false_ready_rate"]
        ),
        minimum_ready_recall=float(design["admission"]["minimum_ready_recall"]),
    )
    checks = {
        "source_is_fail_closed": nested.get("status") == "NO_ADMISSIBLE_PROFILE",
        "holdout_remained_sealed": (
            nested.get("holdout_access_permitted") is False
            and _mapping(nested.get("holdout")).get("status")
            == "SEALED_NOT_OPENED"
        ),
        "audit_completed": audit.get("status") == "DIAGNOSED",
        "failure_attributed_to_package_boundary": audit.get("decision")
        == "DEPENDENCE_ROBUST_PACKAGE_SCORE_REQUIRED",
        "model_revision_unchanged": audit["failure_attribution"][
            "model_revision_change_authorized"
        ]
        is False,
        "runtime_activation_prohibited": audit["next_contract"][
            "runtime_activation_permitted"
        ]
        is False,
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-D",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "source_selection_hash": nested.get("selection_hash"),
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_opened": False,
        "audit": audit,
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
        audit = _mapping(result.get("audit"))
        return (
            "gb2_s20qpd_package_probability_failure_audit=pass "
            f"decision={audit.get('decision')} holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpd_package_probability_failure_audit=skipped"
    return (
        "gb2_s20qpd_package_probability_failure_audit=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpd_package_probability_failure_audit()
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
