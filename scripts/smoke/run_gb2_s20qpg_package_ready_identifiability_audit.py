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

from nex_cx.retrieval_package_identifiability_audit import (
    audit_package_ready_identifiability,
)

SCHEMA_VERSION = "gb2_s20qpg_package_ready_identifiability_audit.v1"
SMOKE_ENV = "NEX_GB2_S20QPG_PACKAGE_READY_IDENTIFIABILITY_AUDIT"
PROFILE_ENV = "NEX_GB2_S20QPG_PROFILE"
SOURCE_ENV = "NEX_GB2_S20QPG_SOURCE_EVIDENCE"
SELECTION_ENV = "NEX_GB2_S20QPG_SELECTION_EVIDENCE"
DEFAULT_SOURCE = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpca_vector_near_tie_boundary.json"
)
DEFAULT_SELECTION = (
    ROOT
    / "reports"
    / "live"
    / "gb2_ca00_s20qpf_nested_package_ordinal_calibration.json"
)
DATASET_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_retrieval_package_calibration_v4.json"
)
RETRIEVAL_DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4_design.json"
)
ORDINAL_DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_package_ordinal_calibrator_v1_design.json"
)


def run_gb2_s20qpg_package_ready_identifiability_audit(
    environ: Mapping[str, str] | None = None,
    *,
    source: Mapping[str, Any] | None = None,
    selection_source: Mapping[str, Any] | None = None,
    dataset: Mapping[str, Any] | None = None,
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
    source = source or _load_json(Path(env.get(SOURCE_ENV, str(DEFAULT_SOURCE))))
    if source is None:
        return _failure("source_evidence_missing")
    selection_source = selection_source or _load_json(
        Path(env.get(SELECTION_ENV, str(DEFAULT_SELECTION)))
    )
    if selection_source is None:
        return _failure("selection_evidence_missing")
    dataset = dataset or _load_json(DATASET_PATH)
    if dataset is None:
        return _failure("dataset_missing")

    runs = _mapping(source.get("repeat_collection")).get("runs")
    first_run = runs[0] if isinstance(runs, list) and runs else None
    observations = _mapping(first_run).get("candidate_observations")
    if not isinstance(observations, list):
        return _failure("candidate_observations_missing")
    try:
        metadata = _calibration_package_metadata(dataset)
        retrieval_design = json.loads(RETRIEVAL_DESIGN_PATH.read_text(encoding="utf-8"))
        ordinal_design = json.loads(ORDINAL_DESIGN_PATH.read_text(encoding="utf-8"))
        audit = audit_package_ready_identifiability(
            observations,
            candidate_profiles=retrieval_design["selection_protocol"][
                "profile_shortlist"
            ],
            ordinal_design=ordinal_design,
            expected_binding=_mapping(source.get("binding")),
            package_metadata=metadata,
            maximum_false_ready_rate=float(
                retrieval_design["admission"]["maximum_false_ready_rate"]
            ),
            minimum_ready_recall=float(
                retrieval_design["admission"]["minimum_ready_recall"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _failure("audit_input_invalid", detail=str(exc))

    source_nested = _mapping(source.get("nested_selection"))
    selection = _mapping(selection_source.get("selection"))
    allowed_decisions = {
        "EXISTING_SIGNAL_RECALIBRATION_JUSTIFIED",
        "ANSWERABILITY_SIGNAL_REQUIRED",
        "SIGNAL_AND_DATASET_REVIEW_REQUIRED",
    }
    checks = {
        "source_execution_passed": source.get("status") == "PASS",
        "source_holdout_remained_sealed": (
            source_nested.get("holdout_access_permitted") is False
            and _mapping(source_nested.get("holdout")).get("status")
            == "SEALED_NOT_OPENED"
        ),
        "p_f_nested_admission_failed_closed": (
            selection_source.get("status") == "PASS"
            and selection.get("status") == "NO_ADMISSIBLE_PROFILE"
            and _mapping(selection.get("holdout")).get("status")
            == "SEALED_NOT_OPENED"
        ),
        "audit_completed": audit.get("status") == "DIAGNOSED",
        "decision_is_bounded": audit.get("decision") in allowed_decisions,
        "holdout_remained_sealed": audit["next_contract"][
            "holdout_access_permitted"
        ]
        is False,
        "runtime_activation_prohibited": audit["next_contract"][
            "runtime_activation_permitted"
        ]
        is False,
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-G",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": audit.get("decision"),
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_opened": False,
        "source_provider_request_counts": source.get("provider_request_counts"),
        "audit": audit,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _calibration_package_metadata(
    dataset: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise TypeError("dataset cases are invalid")
    metadata: dict[str, dict[str, str]] = {}
    for value in cases:
        if not isinstance(value, Mapping) or value.get("partition") != "CALIBRATION":
            continue
        scenario_id = _required_string(value.get("scenario_id"), "scenario_id")
        expected_ready = value.get("expected_ready")
        if type(expected_ready) is not bool:
            raise TypeError("expected_ready is invalid")
        sample_id = f"{scenario_id}:{'positive' if expected_ready else 'negative'}"
        if sample_id in metadata:
            raise ValueError("dataset calibration package is duplicated")
        metadata[sample_id] = {
            "domain": _required_string(value.get("domain"), "domain"),
            "language_profile": _required_string(
                value.get("language_profile"), "language_profile"
            ),
        }
    if not metadata:
        raise ValueError("dataset calibration packages are missing")
    return metadata


def _load_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, Mapping) else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _failure(code: str, *, detail: str | None = None) -> dict[str, Any]:
    result = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
    }
    if detail:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        audit = _mapping(result.get("audit"))
        selected = _mapping(
            _mapping(audit.get("identifiability")).get(
                "selected_diagnostic_combination"
            )
        )
        safety = _mapping(selected.get("best_safety_point"))
        return (
            "gb2_s20qpg_package_ready_identifiability_audit=pass "
            f"decision={result.get('decision')} "
            f"safe_recall={safety.get('ready_recall')} "
            f"false_ready={safety.get('false_ready_rate')} "
            "holdout=sealed runtime=disabled"
        )
    if status == "skipped":
        return "gb2_s20qpg_package_ready_identifiability_audit=skipped"
    return (
        "gb2_s20qpg_package_ready_identifiability_audit=fail "
        f"checks={','.join(result.get('failed_checks', [])) or result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpg_package_ready_identifiability_audit()
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
