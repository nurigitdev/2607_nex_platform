#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
QUALITY_PATH = ROOT / "scripts" / "quality"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(QUALITY_PATH))

from nex_ag.audit_correlation import (  # noqa: E402
    build_audit_correlation_continuity_report,
)
from nex_ag.audit_evidence_package import (  # noqa: E402
    build_audit_evidence_package,
    verify_audit_evidence_package,
)
from nex_ag.audit_integrity import (  # noqa: E402
    build_audit_event_integrity_report,
)
from nex_runtime import build_operational_event  # noqa: E402
from run_ag_audit_evidence_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
)
from run_ag_audit_evidence_postgres_smoke import (  # noqa: E402
    run_ag_audit_evidence_postgres_smoke as run_postgres,
)
from run_ag_audit_evidence_privacy_runbook_evidence import (  # noqa: E402
    run_ag_audit_evidence_privacy_runbook_evidence as run_privacy,
)
from run_ag_audit_integrity_evidence_boundary_audit import (  # noqa: E402
    run_ag_audit_integrity_evidence_boundary_audit as run_boundary,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s87_ag_audit_integrity_evidence_closure.v1"
SLICE_RANGE = "0861-0870"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = (
    "docs/slices/0868_ag_audit_evidence_postgresql_smoke.md"
)
PRIVACY_RUNBOOK_DOC = (
    "docs/slices/0869_ag_audit_evidence_privacy_runbook.md"
)
SOURCE_TABLES = ("service_operational_events", "ag_ev_exports")
CHECKED_AT = "2026-09-20T11:00:00Z"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/audit_integrity.py",
    "services/nex-ag/nex_ag/audit_correlation.py",
    "services/nex-ag/nex_ag/audit_evidence_package.py",
    "services/nex-ag/nex_ag/audit_evidence_api.py",
    "services/nex-ag/nex_ag/audit_evidence_operations.py",
    "services/nex-ag/nex_ag/operations.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/audit_evidence.v1.schema.json",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_audit_evidence_package_response.mock_success.json",
    "contracts/examples/operations/ag_audit_evidence_verify_response.mock_success.json",
    "contracts/examples/operations/ag_audit_evidence_operations_projection.mock_success.json",
    "contracts/tests/negative/operations/ag_audit_evidence_verify_response.raw_payload_leak.json",
    "contracts/tests/negative/operations/ag_audit_evidence_verify_response.untrusted_package_id.json",
    "contracts/tests/negative/operations/ag_audit_evidence_operations_projection.manifest_leak.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_audit_integrity_evidence_boundary_audit.py",
    "scripts/smoke/run_ag_audit_evidence_postgres_smoke.py",
    "scripts/smoke/run_ag_audit_evidence_privacy_runbook_evidence.py",
    "scripts/smoke/run_s87_ag_audit_integrity_evidence_closure.py",
    "tests/test_ag_audit_integrity_evidence_boundary_audit.py",
    "tests/test_nex_ag_audit_integrity.py",
    "tests/test_nex_ag_audit_correlation.py",
    "tests/test_nex_ag_audit_evidence_package.py",
    "tests/test_nex_ag_audit_evidence_api.py",
    "tests/test_nex_ag_audit_evidence_operations.py",
    "tests/test_nex_ag_audit_evidence_contracts.py",
    "tests/test_ag_audit_evidence_postgres_smoke.py",
    "tests/test_ag_audit_evidence_privacy_runbook_evidence.py",
    "tests/test_s87_ag_audit_integrity_evidence_closure.py",
    "docs/README.md",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0861", "ag_audit_integrity_evidence_boundary_audit"),
            ("0862", "ag_audit_event_integrity_contract"),
            ("0863", "ag_audit_trace_correlation_continuity"),
            ("0864", "ag_audit_evidence_package_builder"),
            ("0865", "ag_audit_evidence_protected_api"),
            ("0866", "ag_audit_integrity_operations_projection"),
            ("0867", "ag_audit_evidence_contract_hardening"),
            ("0868", "ag_audit_evidence_postgresql_smoke"),
            ("0869", "ag_audit_evidence_privacy_runbook"),
            ("0870", "s87_ag_audit_integrity_evidence_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "boundary_mode",
        "docs/slices/0861_ag_audit_integrity_evidence_boundary_audit.md",
        "read-only and deterministic",
    ),
    (
        "integrity_builder",
        "services/nex-ag/nex_ag/audit_integrity.py",
        "def build_audit_event_integrity_report",
    ),
    (
        "correlation_builder",
        "services/nex-ag/nex_ag/audit_correlation.py",
        "def build_audit_correlation_continuity_report",
    ),
    (
        "package_builder",
        "services/nex-ag/nex_ag/audit_evidence_package.py",
        "def build_audit_evidence_package",
    ),
    (
        "package_verifier",
        "services/nex-ag/nex_ag/audit_evidence_package.py",
        "def verify_audit_evidence_package",
    ),
    (
        "protected_create_route",
        "services/nex-ag/nex_ag/audit_evidence_api.py",
        '"/admin/v1/audit-integrity/evidence-packages"',
    ),
    (
        "operations_projection",
        "services/nex-ag/nex_ag/audit_evidence_operations.py",
        "def build_audit_evidence_operations_projection",
    ),
    (
        "dashboard_section",
        "services/nex-ag/nex_ag/operations.py",
        '"audit_integrity"',
    ),
    (
        "contract_schema",
        "contracts/schemas/service/nex_ag/audit_evidence.v1.schema.json",
        "ag_audit_evidence_package_response.v1",
    ),
    (
        "openapi_create",
        "contracts/openapi/nex-ag.openapi.yaml",
        "createAgAuditEvidencePackage",
    ),
    (
        "openapi_verify",
        "contracts/openapi/nex-ag.openapi.yaml",
        "verifyAgAuditEvidencePackage",
    ),
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_ag_audit_integrity_evidence_boundary_audit.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_ag_audit_evidence_postgres_smoke.py",
    ),
    (
        "quality_privacy",
        QUALITY_GATE_PATH,
        "run_ag_audit_evidence_privacy_runbook_evidence.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s87_ag_audit_integrity_evidence_closure.py",
    ),
    (
        "postgres_pass",
        POSTGRES_SMOKE_DOC,
        "ag_audit_evidence_postgres_smoke=pass",
    ),
    ("postgres_cleanup", POSTGRES_SMOKE_DOC, "cleaned=True"),
    ("postgres_direct_zero", POSTGRES_SMOKE_DOC, "|0|0"),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "ag_audit_evidence_privacy_runbook=pass",
    ),
    (
        "docs_index_0870",
        "docs/README.md",
        "0870_s87_ag_audit_integrity_evidence_closure.md",
    ),
)


def run_s87_ag_audit_integrity_evidence_closure(
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    required_files = _required_file_results(root)
    token_checks = _token_results(root)
    boundary = _safe_evidence(lambda: run_boundary(root), "boundary_failed")
    privacy = _safe_evidence(lambda: run_privacy(root), "privacy_failed")
    postgres = _safe_evidence(lambda: run_postgres(env), "postgres_failed")
    runtime = _safe_evidence(_runtime_evidence, "runtime_failed")
    contracts = _contract_evidence(root)
    postgres_opted_in = env.get(POSTGRES_SMOKE_ENV) == "1"
    expected_postgres_status = "PASS" if postgres_opted_in else "SKIPPED"
    postgres_doc = _postgres_doc_evidence(root)
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "runtime_integrity_verified": (
            runtime.get("integrity_status") == "VERIFIED"
            and runtime.get("continuity_status") == "CONTIGUOUS"
        ),
        "runtime_package_verified": (
            runtime.get("package_status") == "VERIFIED"
            and runtime.get("verification_status") == "VERIFIED"
            and runtime.get("issue_count") == 0
        ),
        "runtime_redacted": runtime.get("raw_values_exposed") is False,
        "contracts_valid": contracts.get("status") == "PASS",
        "privacy_runbook_passed": privacy.get("status") == "PASS",
        "privacy_checks_passed": all(_mapping(privacy.get("checks")).values()),
        "postgres_protection_respected": (
            postgres.get("status") == expected_postgres_status
        ),
        "postgres_actual_pass_when_opted_in": (
            not postgres_opted_in or postgres.get("status") == "PASS"
        ),
        "postgres_documented_pass_present": all(postgres_doc.values()),
        "existing_tables_reused": boundary.get("decision", {}).get(
            "event_source_table"
        )
        == SOURCE_TABLES[0]
        and boundary.get("decision", {}).get("evidence_source_table")
        == SOURCE_TABLES[1],
        "no_new_table_required": boundary.get("decision", {}).get(
            "new_table_required"
        )
        is False,
        "external_notary_deferred": (
            "external_notary_or_signature_service"
            in boundary.get("deferred_scope", [])
        ),
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s87_ag_audit_integrity_evidence_closure_failed",
        "slice_range": SLICE_RANGE,
        "boundary": "read_only_deterministic_audit_integrity_evidence",
        "source_tables": list(SOURCE_TABLES),
        "new_tables": [],
        "new_indexes": [],
        "external_notary_implemented": False,
        "postgres_smoke_opted_in": postgres_opted_in,
        "closure_surfaces": [
            "boundary_decision",
            "event_integrity",
            "trace_correlation_continuity",
            "deterministic_redacted_package",
            "protected_package_and_verify_api",
            "operations_dashboard",
            "openapi_json_schema_contracts",
            "test_db_postgres_smoke",
            "privacy_tamper_runbook",
        ],
        "boundary_audit": boundary,
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


def _runtime_evidence() -> dict[str, Any]:
    trace_id = "d" * 32
    raw_message = "private-closure-message-0870"
    raw_detail = "private-closure-detail-0870"
    event = build_operational_event(
        service_id="nex-ag",
        event_type="ag.audit_evidence.closure_source",
        severity="INFO",
        message=raw_message,
        trace_id=trace_id,
        request_id="request-0870",
        subject_ref={"type": "s87_closure", "id": "source-0870"},
        details={"raw_payload": raw_detail},
        created_at=CHECKED_AT,
        event_id="event-0870",
    )
    export = {
        "export_id": "export-0870",
        "trace_id": trace_id,
        "evidence_hash": "e" * 64,
        "evidence_item_count": 1,
        "export_status": "READY",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_manifest": {"raw_payload": raw_detail},
    }
    integrity = build_audit_event_integrity_report(
        [event],
        expected_event_ids=[event["event_id"]],
        checked_at=CHECKED_AT,
    )
    correlation = build_audit_correlation_continuity_report(
        [event],
        evidence_exports=[export],
        expected_event_ids=[event["event_id"]],
        expected_trace_ids=[trace_id],
        required_event_types=[event["event_type"]],
        checked_at=CHECKED_AT,
    )
    package = build_audit_evidence_package(
        integrity_report=integrity,
        correlation_report=correlation,
        evidence_exports=[export],
        generated_at=CHECKED_AT,
    )
    verification = verify_audit_evidence_package(package)
    serialized = json.dumps(
        [integrity, correlation, package, verification],
        sort_keys=True,
    )
    return {
        "status": "PASS",
        "integrity_status": integrity["integrity_status"],
        "continuity_status": correlation["continuity_status"],
        "package_status": package["verification_status"],
        "verification_status": verification["verification_status"],
        "issue_count": verification["issue_count"],
        "package_id": package["package_id"],
        "manifest_hash": package["manifest_hash"],
        "package_hash": package["package_hash"],
        "raw_values_exposed": (
            raw_message in serialized or raw_detail in serialized
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
        "negative_example_count": result.negative_example_count,
        "openapi_count": result.openapi_count,
        "failure_count": len(result.failures),
    }


def _safe_evidence(
    call: Callable[[], Mapping[str, Any]],
    failure_code: str,
) -> dict[str, Any]:
    try:
        return dict(call())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": failure_code,
            "error_type": type(exc).__name__,
        }


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "check_id": check_id,
            "path": relative_path,
            "present": token in _read_text(root / relative_path),
        }
        for check_id, relative_path, token in TOKEN_CHECKS
    ]


def _postgres_doc_evidence(root: Path) -> dict[str, bool]:
    content = _read_text(root / POSTGRES_SMOKE_DOC)
    return {
        "test_database": "database=nex_ag_test" in content,
        "summary_pass": "ag_audit_evidence_postgres_smoke=pass" in content,
        "event_insert_select": "events=3" in content,
        "export_insert_select": "exports=1" in content,
        "package_verified": "package_status=VERIFIED" in content,
        "cleanup": "cleaned=True" in content,
        "direct_zero_rows": "|0|0" in content,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        summary = _mapping(evidence.get("summary"))
        return (
            "s87_ag_audit_integrity_evidence_closure=fail "
            f"missing_files={summary.get('missing_file_count')} "
            f"missing_tokens={summary.get('missing_token_count')}"
        )
    postgres = _mapping(evidence.get("postgres_smoke"))
    privacy = _mapping(evidence.get("privacy_runbook"))
    contracts = _mapping(evidence.get("contract_validation"))
    return (
        "s87_ag_audit_integrity_evidence_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"contracts={contracts.get('status')} "
        f"postgres={postgres.get('status')} "
        f"privacy={privacy.get('status')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s87_ag_audit_integrity_evidence_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
