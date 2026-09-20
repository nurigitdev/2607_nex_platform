#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.cx_transition_handoff import (  # noqa: E402
    bind_ag_cx_transition_handoff,
    build_ag_cx_transition_handoff_candidate,
    verify_ag_cx_transition_handoff,
    verify_ag_cx_transition_handoff_attestation,
)
from nex_ag.mvp_acceptance import build_ag_mvp_acceptance_policy  # noqa: E402
from nex_ag.mvp_acceptance_evaluation import (  # noqa: E402
    evaluate_ag_mvp_acceptance,
)


SCHEMA_VERSION = "ag_mvp_acceptance_privacy_runbook.v1"
SLICE_ID = "0899"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ag_mvp_acceptance_privacy_runbook_evidence.py"
POSTGRES_EVIDENCE_PATH = (
    "docs/slices/0898_ag_mvp_acceptance_postgresql_smoke.md"
)
OBSERVED_AT = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
FORBIDDEN_VALUES = {
    "database_url": "postgresql+psycopg://private-s90-runbook",
    "credential": "private-s90-credential",
    "raw_document": "private-s90-document-content",
    "raw_prompt": "private-s90-prompt",
    "raw_generation": "private-s90-generation",
    "raw_event": "private-s90-event-detail",
}
FORBIDDEN_KEYS = {
    "authorization",
    "credential",
    "database_url",
    "details",
    "message",
    "password",
    "raw_document",
    "raw_generation",
    "raw_payload",
    "raw_prompt",
    "secret",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0891", "ag_mvp_acceptance_cx_transition_boundary_audit"),
        ("0892", "ag_mvp_acceptance_policy"),
        ("0893", "ag_mvp_evidence_inventory"),
        ("0894", "ag_mvp_acceptance_evaluator"),
        ("0895", "ag_mvp_acceptance_protected_api"),
        ("0896", "ag_mvp_acceptance_contract_operations_hardening"),
        ("0897", "ag_cx_transition_handoff_package"),
        ("0898", "ag_mvp_acceptance_postgresql_smoke"),
    )
)


def run_ag_mvp_acceptance_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    policy = build_ag_mvp_acceptance_policy({})
    baseline = _acceptance_evidence()
    accepted_report = evaluate_ag_mvp_acceptance(
        baseline,
        policy=policy,
        now=OBSERVED_AT,
    )
    candidate = build_ag_cx_transition_handoff_candidate(
        generated_at=OBSERVED_AT,
        root=ROOT,
    )
    candidate_verification = verify_ag_cx_transition_handoff(candidate)
    attestation = bind_ag_cx_transition_handoff(
        candidate,
        accepted_report,
        bound_at=OBSERVED_AT,
    )
    attestation_verification = verify_ag_cx_transition_handoff_attestation(
        attestation,
        candidate=candidate,
        acceptance_report=accepted_report,
    )
    tampered_candidate = deepcopy(candidate)
    tampered_candidate["target_service"] = "nex-ae-api"
    tampered_attestation = deepcopy(attestation)
    tampered_attestation["acceptance_id"] = "b" * 64
    failures = _failure_matrix(baseline, policy=policy)
    postgres_evidence = _postgres_evidence(
        _read_text(root / POSTGRES_EVIDENCE_PATH)
    )
    runbook = _runbook_actions()
    surfaces = {
        "accepted_report": _report_projection(accepted_report),
        "candidate_verification": candidate_verification,
        "attestation_verification": attestation_verification,
        "tampered_candidate": verify_ag_cx_transition_handoff(
            tampered_candidate
        ),
        "tampered_attestation": verify_ag_cx_transition_handoff_attestation(
            tampered_attestation,
            candidate=candidate,
            acceptance_report=accepted_report,
        ),
        "failure_matrix": failures,
        "postgres_evidence": postgres_evidence,
        "runbook": runbook,
    }
    serialized = json.dumps(surfaces, ensure_ascii=False, sort_keys=True)
    forbidden_value_labels = _forbidden_value_labels(serialized)
    forbidden_key_paths = _forbidden_key_paths(surfaces)
    required_docs = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in _read_text(
        root / QUALITY_GATE_PATH
    )
    expected_failures = {
        "evidence_missing",
        "evidence_skipped",
        "evidence_stale",
        "evidence_from_future",
        "regression_failure",
        "statement_coverage_low",
        "branch_coverage_low",
        "wrong_database",
        "cleanup_unproven",
        "runbook_incomplete",
        "handoff_invalid",
    }
    checks = {
        "baseline_acceptance_passed": (
            accepted_report["status"] == "ACCEPTED"
            and accepted_report["transition_status"] == "READY_FOR_CX"
            and accepted_report["summary"]["passed_gate_count"] == 8
        ),
        "two_stage_handoff_verified": (
            candidate_verification["status"] == "VERIFIED"
            and attestation_verification["status"] == "VERIFIED"
            and attestation["attestation_status"] == "BOUND"
        ),
        "tamper_detection_passed": (
            surfaces["tampered_candidate"]["status"] == "INVALID"
            and surfaces["tampered_attestation"]["status"] == "INVALID"
        ),
        "failure_matrix_complete": (
            set(failures) == expected_failures
            and all(item["status"] == "BLOCKED" for item in failures.values())
        ),
        "postgres_evidence_complete": all(postgres_evidence.values()),
        "runbook_complete": set(runbook) == {
            "evidence_missing_or_skipped",
            "evidence_stale_or_future",
            "regression_or_coverage_failure",
            "contract_or_inventory_failure",
            "postgres_connectivity_or_migration",
            "wrong_test_database",
            "smoke_cleanup_failure",
            "runbook_inventory_incomplete",
            "handoff_candidate_invalid",
            "handoff_attestation_invalid",
        },
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    passed = all(checks.values())
    result = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "ag_mvp_acceptance_privacy_runbook_failed"
        ),
        "slice": SLICE_ID,
        "surface_count": len(surfaces),
        "surfaces": surfaces,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(result, ensure_ascii=False))
    return result


def _acceptance_evidence() -> dict[str, dict[str, Any]]:
    observed_at = _timestamp(OBSERVED_AT)
    return {
        "ag_requirement_closures": {
            "status": "PASS",
            "observed_at": observed_at,
            "requirement_count": 33,
            "issue_count": 0,
        },
        "contract_validation": {
            "status": "PASS",
            "observed_at": observed_at,
            "schema_count": 82,
            "openapi_count": 7,
            "negative_fixture_count": 97,
        },
        "unit_regression": {
            "status": "PASS",
            "observed_at": observed_at,
            "passed_tests": 6256,
            "failed_tests": 0,
        },
        "statement_coverage": {
            "status": "PASS",
            "observed_at": observed_at,
            "percent": 98.84,
        },
        "branch_coverage": {
            "status": "PASS",
            "observed_at": observed_at,
            "percent": 96.44,
        },
        "postgres_smoke": {
            "status": "PASS",
            "observed_at": observed_at,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "zero_residue": True,
        },
        "privacy_failure_runbooks": {
            "status": "PASS",
            "observed_at": observed_at,
            "runbook_count": 27,
        },
        "cx_transition_handoff": {
            "status": "PASS",
            "observed_at": observed_at,
            "target_service": "nex-cx",
            "manifest_status": "SEALED",
        },
    }


def _failure_matrix(
    baseline: Mapping[str, Mapping[str, Any]],
    *,
    policy: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, dict[str, Any]]] = {}
    missing = deepcopy(baseline)
    missing.pop("contract_validation")
    scenarios["evidence_missing"] = missing
    scenarios["evidence_skipped"] = _changed(
        baseline, "postgres_smoke", status="SKIPPED"
    )
    scenarios["evidence_stale"] = _changed(
        baseline,
        "unit_regression",
        observed_at=_timestamp(OBSERVED_AT - timedelta(hours=25)),
    )
    scenarios["evidence_from_future"] = _changed(
        baseline,
        "branch_coverage",
        observed_at=_timestamp(OBSERVED_AT + timedelta(minutes=6)),
    )
    scenarios["regression_failure"] = _changed(
        baseline, "unit_regression", failed_tests=1
    )
    scenarios["statement_coverage_low"] = _changed(
        baseline, "statement_coverage", percent=97.99
    )
    scenarios["branch_coverage_low"] = _changed(
        baseline, "branch_coverage", percent=95.99
    )
    scenarios["wrong_database"] = _changed(
        baseline, "postgres_smoke", database="nex_ag_dev"
    )
    scenarios["cleanup_unproven"] = _changed(
        baseline, "postgres_smoke", zero_residue=False
    )
    scenarios["runbook_incomplete"] = _changed(
        baseline, "privacy_failure_runbooks", runbook_count=26
    )
    scenarios["handoff_invalid"] = _changed(
        baseline, "cx_transition_handoff", manifest_status="DRAFT"
    )
    return {
        name: _report_projection(
            evaluate_ag_mvp_acceptance(
                evidence,
                policy=policy,
                now=OBSERVED_AT,
            )
        )
        for name, evidence in scenarios.items()
    }


def _changed(
    baseline: Mapping[str, Mapping[str, Any]],
    gate_id: str,
    **updates: Any,
) -> dict[str, dict[str, Any]]:
    changed = deepcopy(baseline)
    changed[gate_id].update(updates)
    return changed


def _report_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": report.get("status"),
        "transition_status": report.get("transition_status"),
        "acceptance_id": report.get("acceptance_id"),
        "blockers": list(report.get("blockers") or []),
        "raw_evidence_included": report.get("raw_evidence_included"),
    }


def _postgres_evidence(document: str) -> dict[str, bool]:
    return {
        "live_smoke_passed": "live smoke: PASS" in document,
        "test_database_selected": "database=nex_ag_test" in document,
        "acceptance_accepted": "acceptance=ACCEPTED" in document,
        "handoff_bound": "handoff=BOUND" in document,
        "cleanup_verified": (
            "remaining=0" in document and "probe_residue=0" in document
        ),
        "migration_observed": "latest_migration=1" in document,
        "regression_observed": "aggregate regression: 6256 passed" in document,
        "coverage_observed": (
            "statement=75383/76264" in document
            and "branch=17634/18284" in document
        ),
    }


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "evidence_missing_or_skipped": {
            "retryable": True,
            "action": "run the named blocking gate and attach server-derived evidence",
        },
        "evidence_stale_or_future": {
            "retryable": True,
            "action": "synchronize clocks and regenerate evidence within the policy window",
        },
        "regression_or_coverage_failure": {
            "retryable": False,
            "action": "fix regressions or add tests before rerunning acceptance",
        },
        "contract_or_inventory_failure": {
            "retryable": False,
            "action": "repair contracts or requirement closure inventory first",
        },
        "postgres_connectivity_or_migration": {
            "retryable": True,
            "action": "verify the test profile and apply current AG migrations",
        },
        "wrong_test_database": {
            "retryable": False,
            "action": "stop and select nex_ag_test before creating any probe",
        },
        "smoke_cleanup_failure": {
            "retryable": False,
            "action": "delete only the owned probe and prove zero residue",
        },
        "runbook_inventory_incomplete": {
            "retryable": False,
            "action": "restore all required privacy and failure-mode runbooks",
        },
        "handoff_candidate_invalid": {
            "retryable": False,
            "action": "rebuild and verify the sealed candidate from repository assets",
        },
        "handoff_attestation_invalid": {
            "retryable": False,
            "action": "reject binding and attest the accepted report to the exact candidate hash",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _forbidden_value_labels(serialized: str) -> list[str]:
    return sorted(
        label for label, value in FORBIDDEN_VALUES.items() if value in serialized
    )


def _forbidden_key_paths(value: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_KEYS:
                paths.append(path)
            paths.extend(_forbidden_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
    return paths


def _assert_no_forbidden_values(serialized: str) -> None:
    labels = _forbidden_value_labels(serialized)
    if labels:
        raise ValueError(f"privacy evidence contains forbidden values: {labels}")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_mvp_acceptance_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = _mapping(evidence.get("checks"))
    return (
        "ag_mvp_acceptance_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"postgres={checks.get('postgres_evidence_complete')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_mvp_acceptance_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    )
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
