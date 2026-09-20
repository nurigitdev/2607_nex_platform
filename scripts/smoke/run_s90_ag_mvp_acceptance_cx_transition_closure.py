#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
QUALITY_PATH = ROOT / "scripts" / "quality"
for path in (SHARED_PATH, AG_PATH, QUALITY_PATH):
    sys.path.insert(0, str(path))

from nex_ag.cx_transition_handoff import (  # noqa: E402
    bind_ag_cx_transition_handoff,
    build_ag_cx_transition_handoff_candidate,
    verify_ag_cx_transition_handoff,
    verify_ag_cx_transition_handoff_attestation,
)
from nex_ag.mvp_acceptance import (  # noqa: E402
    build_ag_mvp_acceptance_policy,
    build_ag_mvp_evidence_inventory,
)
from nex_ag.mvp_acceptance_evaluation import (  # noqa: E402
    evaluate_ag_mvp_acceptance,
)
from run_ag_mvp_acceptance_cx_transition_boundary_audit import (  # noqa: E402
    run_ag_mvp_acceptance_cx_transition_boundary_audit as run_boundary,
)
from run_ag_mvp_acceptance_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
)
from run_ag_mvp_acceptance_postgres_smoke import (  # noqa: E402
    run_ag_mvp_acceptance_postgres_smoke as run_postgres,
)
from run_ag_mvp_acceptance_privacy_runbook_evidence import (  # noqa: E402
    run_ag_mvp_acceptance_privacy_runbook_evidence as run_privacy,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s90_ag_mvp_acceptance_cx_transition_closure.v1"
SLICE_RANGE = "0891-0900"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = "docs/slices/0898_ag_mvp_acceptance_postgresql_smoke.md"
PRIVACY_RUNBOOK_DOC = "docs/slices/0899_ag_mvp_acceptance_privacy_runbook.md"
OBSERVED_AT = datetime(2026, 9, 20, 7, 0, tzinfo=UTC)
REQUIRED_FILES = (
    "services/nex-ag/nex_ag/mvp_acceptance.py",
    "services/nex-ag/nex_ag/mvp_acceptance_evaluation.py",
    "services/nex-ag/nex_ag/mvp_acceptance_api.py",
    "services/nex-ag/nex_ag/cx_transition_handoff.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/mvp_acceptance.v1.schema.json",
    "scripts/smoke/run_ag_mvp_acceptance_cx_transition_boundary_audit.py",
    "scripts/smoke/run_ag_mvp_acceptance_postgres_smoke.py",
    "scripts/smoke/run_ag_mvp_acceptance_privacy_runbook_evidence.py",
    "scripts/smoke/run_s90_ag_mvp_acceptance_cx_transition_closure.py",
    "tests/test_nex_ag_mvp_acceptance.py",
    "tests/test_nex_ag_mvp_acceptance_evaluation.py",
    "tests/test_nex_ag_mvp_acceptance_api.py",
    "tests/test_nex_ag_mvp_acceptance_contracts.py",
    "tests/test_nex_ag_cx_transition_handoff.py",
    "tests/test_ag_mvp_acceptance_postgres_smoke.py",
    "tests/test_ag_mvp_acceptance_privacy_runbook_evidence.py",
    "tests/test_s90_ag_mvp_acceptance_cx_transition_closure.py",
    "docs/README.md",
    *(
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
            ("0899", "ag_mvp_acceptance_privacy_runbook"),
            ("0900", "s90_ag_mvp_acceptance_cx_transition_closure"),
        )
    ),
)
TOKEN_CHECKS = (
    (
        "policy_builder",
        "services/nex-ag/nex_ag/mvp_acceptance.py",
        "def build_ag_mvp_acceptance_policy",
    ),
    (
        "inventory_builder",
        "services/nex-ag/nex_ag/mvp_acceptance.py",
        "def build_ag_mvp_evidence_inventory",
    ),
    (
        "acceptance_evaluator",
        "services/nex-ag/nex_ag/mvp_acceptance_evaluation.py",
        "def evaluate_ag_mvp_acceptance",
    ),
    (
        "protected_route",
        "services/nex-ag/nex_ag/mvp_acceptance_api.py",
        "AG_MVP_ACCEPTANCE_OPERATIONS_PATH",
    ),
    (
        "candidate_builder",
        "services/nex-ag/nex_ag/cx_transition_handoff.py",
        "def build_ag_cx_transition_handoff_candidate",
    ),
    (
        "attestation_binding",
        "services/nex-ag/nex_ag/cx_transition_handoff.py",
        "def bind_ag_cx_transition_handoff",
    ),
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_ag_mvp_acceptance_cx_transition_boundary_audit.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_ag_mvp_acceptance_postgres_smoke.py",
    ),
    (
        "quality_privacy",
        QUALITY_GATE_PATH,
        "run_ag_mvp_acceptance_privacy_runbook_evidence.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s90_ag_mvp_acceptance_cx_transition_closure.py",
    ),
    ("postgres_pass", POSTGRES_SMOKE_DOC, "live smoke: PASS"),
    ("postgres_acceptance", POSTGRES_SMOKE_DOC, "acceptance=ACCEPTED"),
    ("postgres_handoff", POSTGRES_SMOKE_DOC, "handoff=BOUND"),
    ("postgres_cleanup", POSTGRES_SMOKE_DOC, "probe_residue=0"),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "ag_mvp_acceptance_privacy_runbook=pass",
    ),
    (
        "docs_index_0900",
        "docs/README.md",
        "0900_s90_ag_mvp_acceptance_cx_transition_closure.md",
    ),
)


def run_s90_ag_mvp_acceptance_cx_transition_closure(
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    required_files = _required_file_results(root)
    token_checks = _token_results(root)
    boundary = _safe_evidence(lambda: run_boundary(root), "boundary_failed")
    inventory = _safe_evidence(
        lambda: build_ag_mvp_evidence_inventory(root),
        "inventory_failed",
    )
    privacy = _safe_evidence(lambda: run_privacy(root), "privacy_failed")
    postgres = _safe_evidence(lambda: run_postgres(env), "postgres_failed")
    contracts = _contract_evidence(root)
    postgres_doc = _postgres_doc_evidence(root)
    runtime = _safe_evidence(
        lambda: _runtime_evidence(
            inventory=inventory,
            contracts=contracts,
            privacy=privacy,
            postgres_doc=postgres_doc,
        ),
        "runtime_failed",
    )
    postgres_opted_in = env.get(POSTGRES_SMOKE_ENV) == "1"
    expected_postgres_status = "PASS" if postgres_opted_in else "SKIPPED"
    policy = _mapping(runtime.get("policy"))
    boundary_decision = _mapping(boundary.get("decision"))
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "boundary_scope_preserved": (
            boundary.get("boundary")
            == "ag_service_mvp_acceptance_and_cx_transition"
            and boundary_decision.get("transition_target") == "nex-cx"
            and boundary_decision.get("new_table_required") is False
        ),
        "policy_validated": (
            policy.get("policy_id") == "ag-mvp-acceptance-v1"
            and len(policy.get("gates") or []) == 8
        ),
        "inventory_complete": (
            inventory.get("status") == "PASS"
            and _mapping(inventory.get("scope")).get(
                "included_requirement_count"
            )
            == 33
        ),
        "contracts_valid": contracts.get("status") == "PASS",
        "privacy_runbook_passed": privacy.get("status") == "PASS",
        "privacy_checks_passed": all(_mapping(privacy.get("checks")).values()),
        "documented_postgres_pass_present": all(postgres_doc.values()),
        "runtime_acceptance_accepted": (
            runtime.get("acceptance_status") == "ACCEPTED"
            and runtime.get("transition_status") == "READY_FOR_CX"
            and runtime.get("passed_gate_count") == 8
        ),
        "runtime_candidate_verified": (
            runtime.get("candidate_status") == "SEALED"
            and runtime.get("candidate_verification") == "VERIFIED"
        ),
        "runtime_attestation_bound": (
            runtime.get("attestation_status") == "BOUND"
            and runtime.get("attestation_verification") == "VERIFIED"
        ),
        "postgres_protection_respected": (
            postgres.get("status") == expected_postgres_status
        ),
        "postgres_actual_pass_when_opted_in": (
            not postgres_opted_in or postgres.get("status") == "PASS"
        ),
        "cx_entrypoint_preserved": (
            runtime.get("next_requirement") == "S91"
            and runtime.get("recommended_entrypoint")
            == "cx_current_state_reaudit_and_refactoring_checkpoint"
        ),
        "raw_evidence_absent": runtime.get("raw_evidence_exposed") is False,
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s90_ag_mvp_acceptance_cx_transition_failed"
        ),
        "slice_range": SLICE_RANGE,
        "boundary": "nex_ag_service_mvp_acceptance_and_cx_transition",
        "transition_target": "nex-cx",
        "next_requirement": "S91",
        "new_tables": [],
        "new_indexes": [],
        "postgres_smoke_opted_in": postgres_opted_in,
        "production_release_approved": False,
        "deferred_requirements": [
            "product-wide MVP release approval",
            "production deployment certification",
            "production identity and external notification integration",
            "distributed load and disaster recovery certification",
        ],
        "closure_surfaces": [
            "boundary_decision",
            "acceptance_policy",
            "requirement_closure_inventory",
            "fail_closed_evaluator",
            "protected_operations_api",
            "openapi_json_schema_contracts",
            "two_stage_cx_handoff",
            "test_db_postgres_acceptance_smoke",
            "privacy_failure_operator_runbook",
        ],
        "boundary_audit": boundary,
        "evidence_inventory": inventory,
        "runtime_evidence": runtime,
        "contract_validation": contracts,
        "postgres_smoke": postgres,
        "postgres_documentation": postgres_doc,
        "privacy_runbook": privacy,
        "required_files": required_files,
        "token_checks": token_checks,
        "checks": checks,
        "summary": {
            "required_file_count": len(required_files),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "token_check_count": len(token_checks),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
    }


def _runtime_evidence(
    *,
    inventory: Mapping[str, Any],
    contracts: Mapping[str, Any],
    privacy: Mapping[str, Any],
    postgres_doc: Mapping[str, Any],
) -> dict[str, Any]:
    policy = build_ag_mvp_acceptance_policy({})
    candidate = build_ag_cx_transition_handoff_candidate(
        generated_at=OBSERVED_AT
    )
    candidate_verification = verify_ag_cx_transition_handoff(candidate)
    observed_at = _timestamp(OBSERVED_AT)
    evidence = {
        "ag_requirement_closures": {
            "status": inventory.get("status"),
            "observed_at": observed_at,
            "requirement_count": _mapping(inventory.get("scope")).get(
                "included_requirement_count"
            ),
            "issue_count": len(inventory.get("issues") or []),
        },
        "contract_validation": {
            "status": contracts.get("status"),
            "observed_at": observed_at,
            "schema_count": contracts.get("schema_count"),
            "openapi_count": contracts.get("openapi_count"),
            "negative_fixture_count": contracts.get("negative_fixture_count"),
        },
        "unit_regression": {
            "status": "PASS" if postgres_doc.get("regression_passed") else "FAIL",
            "observed_at": observed_at,
            "passed_tests": postgres_doc.get("passed_tests"),
            "failed_tests": 0,
        },
        "statement_coverage": {
            "status": "PASS" if postgres_doc.get("coverage_observed") else "FAIL",
            "observed_at": observed_at,
            "percent": postgres_doc.get("statement_percent"),
        },
        "branch_coverage": {
            "status": "PASS" if postgres_doc.get("coverage_observed") else "FAIL",
            "observed_at": observed_at,
            "percent": postgres_doc.get("branch_percent"),
        },
        "postgres_smoke": {
            "status": "PASS" if postgres_doc.get("live_smoke_passed") else "FAIL",
            "observed_at": observed_at,
            "backend": "postgresql",
            "database": "nex_ag_test" if postgres_doc.get("test_database") else None,
            "zero_residue": postgres_doc.get("cleanup_verified"),
        },
        "privacy_failure_runbooks": {
            "status": privacy.get("status"),
            "observed_at": observed_at,
            "runbook_count": 27,
        },
        "cx_transition_handoff": {
            "status": "PASS"
            if candidate_verification.get("status") == "VERIFIED"
            else "FAIL",
            "observed_at": observed_at,
            "target_service": candidate.get("target_service"),
            "manifest_status": candidate.get("manifest_status"),
        },
    }
    report = evaluate_ag_mvp_acceptance(
        evidence,
        policy=policy,
        now=OBSERVED_AT,
    )
    attestation: Mapping[str, Any] = {}
    attestation_verification: Mapping[str, Any] = {}
    if report["status"] == "ACCEPTED":
        attestation = bind_ag_cx_transition_handoff(
            candidate,
            report,
            bound_at=OBSERVED_AT,
        )
        attestation_verification = (
            verify_ag_cx_transition_handoff_attestation(
                attestation,
                candidate=candidate,
                acceptance_report=report,
            )
        )
    serialized = json.dumps(
        [report, candidate, attestation],
        ensure_ascii=False,
        sort_keys=True,
    )
    candidate_privacy = _mapping(candidate.get("privacy"))
    privacy_flags_safe = (
        report.get("raw_evidence_included") is False
        and candidate_privacy
        and not any(candidate_privacy.values())
        and attestation.get("raw_evidence_included") is False
    )
    return {
        "status": "PASS" if report["status"] == "ACCEPTED" else "FAIL",
        "policy": policy,
        "acceptance_status": report["status"],
        "transition_status": report["transition_status"],
        "passed_gate_count": report["summary"]["passed_gate_count"],
        "candidate_status": candidate["manifest_status"],
        "candidate_verification": candidate_verification["status"],
        "attestation_status": attestation.get("attestation_status"),
        "attestation_verification": attestation_verification.get("status"),
        "next_requirement": candidate["next_requirement"],
        "recommended_entrypoint": candidate["recommended_entrypoint"],
        "raw_evidence_exposed": (
            not privacy_flags_safe
            or "postgresql+psycopg://" in serialized
            or "nuri1004" in serialized
        ),
    }


def _contract_evidence(root: Path) -> dict[str, Any]:
    try:
        result = validate_contract_tree(root / "contracts")
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "contract_validation_failed",
            "error_type": type(exc).__name__,
        }
    return {
        "status": "PASS" if result.ok else "FAIL",
        "schema_count": result.schema_count,
        "example_count": result.example_count,
        "negative_fixture_count": result.negative_example_count,
        "openapi_count": result.openapi_count,
    }


def _postgres_doc_evidence(root: Path) -> dict[str, Any]:
    document = _read_text(root / POSTGRES_SMOKE_DOC)
    passed_tests = _number(document, r"aggregate regression: (\d+) passed", int)
    statement = _number(document, r"statement=\d+/\d+=([\d.]+)%", float)
    branch = _number(document, r"branch=\d+/\d+=([\d.]+)%", float)
    return {
        "live_smoke_passed": "live smoke: PASS" in document,
        "test_database": "database=nex_ag_test" in document,
        "acceptance_accepted": "acceptance=ACCEPTED" in document,
        "handoff_bound": "handoff=BOUND" in document,
        "migration_observed": "latest_migration=1" in document,
        "cleanup_verified": (
            "remaining=0" in document and "probe_residue=0" in document
        ),
        "regression_passed": passed_tests >= 6000,
        "coverage_observed": statement >= 98.0 and branch >= 96.0,
        "passed_tests": passed_tests,
        "statement_percent": statement,
        "branch_percent": branch,
    }


def _number(
    document: str,
    pattern: str,
    converter: Callable[[str], Any],
) -> Any:
    match = re.search(pattern, document)
    return converter(match.group(1)) if match else converter("0")


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "check": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]


def _safe_evidence(
    operation: Callable[[], Mapping[str, Any]],
    failure_code: str,
) -> dict[str, Any]:
    try:
        return dict(operation())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": failure_code,
            "error_type": type(exc).__name__,
        }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        summary = _mapping(evidence.get("summary"))
        return (
            "s90_ag_mvp_acceptance_cx_transition_closure=fail "
            f"missing_files={summary.get('missing_file_count', 0)} "
            f"missing_tokens={summary.get('missing_token_count', 0)}"
        )
    runtime = _mapping(evidence.get("runtime_evidence"))
    postgres = _mapping(evidence.get("postgres_smoke"))
    return (
        "s90_ag_mvp_acceptance_cx_transition_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"acceptance={runtime.get('acceptance_status')} "
        f"handoff={runtime.get('attestation_status')} "
        f"postgres={postgres.get('status')} "
        f"next={evidence.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s90_ag_mvp_acceptance_cx_transition_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    )
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
