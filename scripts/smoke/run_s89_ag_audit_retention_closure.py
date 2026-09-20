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

from nex_ag.audit_retention import (  # noqa: E402
    InMemoryAgRetentionCandidateStore,
    build_ag_audit_retention_policy,
)
from nex_ag.audit_retention_archive import (  # noqa: E402
    InMemoryAgArchiveReceiptStore,
    build_ag_archive_receipt,
)
from nex_ag.audit_retention_operations import (  # noqa: E402
    build_ag_audit_retention_operations_projection,
)
from nex_ag.audit_retention_purge import (  # noqa: E402
    InMemoryAgRetentionPurgeStore,
    execute_ag_retention_purge,
)
from run_ag_audit_retention_archive_purge_boundary_audit import (  # noqa: E402
    run_ag_audit_retention_archive_purge_boundary_audit as run_boundary,
)
from run_ag_audit_retention_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
)
from run_ag_audit_retention_postgres_smoke import (  # noqa: E402
    run_ag_audit_retention_postgres_smoke as run_postgres,
)
from run_ag_audit_retention_privacy_runbook_evidence import (  # noqa: E402
    run_ag_audit_retention_privacy_runbook_evidence as run_privacy,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s89_ag_audit_retention_closure.v1"
SLICE_RANGE = "0881-0890"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = "docs/slices/0888_ag_audit_retention_postgresql_smoke.md"
PRIVACY_RUNBOOK_DOC = "docs/slices/0889_ag_audit_retention_privacy_runbook.md"
SOURCE_TABLES = ("service_operational_events", "ag_ev_exports")
NEW_TABLES = ("ag_ret_archives",)
NEW_INDEXES = (
    "idx_ag_ret_arc_status_due",
    "idx_ag_evt_retention_time",
    "idx_ag_exp_retention_time",
)

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/audit_retention.py",
    "services/nex-ag/nex_ag/audit_retention_archive.py",
    "services/nex-ag/nex_ag/audit_retention_purge.py",
    "services/nex-ag/nex_ag/audit_retention_operations.py",
    "database/nex-ag/migrations/0884_ag_retention_archive_receipts.sql",
    "database/nex-ag/migrations/0887_ag_retention_candidate_indexes.sql",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/audit_retention.v1.schema.json",
    "contracts/examples/operations/ag_audit_retention_operations.mock_success.json",
    "contracts/examples/operations/ag_audit_retention_purge.mock_success.json",
    "contracts/tests/negative/operations/ag_audit_retention_operations.object_ref_leak.json",
    "contracts/tests/negative/operations/ag_audit_retention_purge.confirmation_leak.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_audit_retention_archive_purge_boundary_audit.py",
    "scripts/smoke/run_ag_audit_retention_postgres_smoke.py",
    "scripts/smoke/run_ag_audit_retention_privacy_runbook_evidence.py",
    "scripts/smoke/run_s89_ag_audit_retention_closure.py",
    "tests/test_nex_ag_audit_retention.py",
    "tests/test_nex_ag_audit_retention_archive.py",
    "tests/test_nex_ag_audit_retention_purge.py",
    "tests/test_nex_ag_audit_retention_operations.py",
    "tests/test_nex_ag_audit_retention_contracts.py",
    "tests/test_ag_audit_retention_postgres_smoke.py",
    "tests/test_ag_audit_retention_privacy_runbook_evidence.py",
    "tests/test_s89_ag_audit_retention_closure.py",
    "docs/README.md",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0881", "ag_audit_retention_archive_purge_boundary_audit"),
            ("0882", "ag_audit_retention_archive_policy"),
            ("0883", "ag_audit_retention_candidate_read_model"),
            ("0884", "ag_archive_receipt_persistence_sealing"),
            ("0885", "ag_guarded_physical_purge_execution"),
            ("0886", "ag_audit_retention_operations_projection"),
            ("0887", "ag_audit_retention_contract_index_hardening"),
            ("0888", "ag_audit_retention_postgresql_smoke"),
            ("0889", "ag_audit_retention_privacy_runbook"),
            ("0890", "s89_ag_audit_retention_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "policy_builder",
        "services/nex-ag/nex_ag/audit_retention.py",
        "def build_ag_audit_retention_policy",
    ),
    (
        "candidate_store",
        "services/nex-ag/nex_ag/audit_retention.py",
        "class SqlAlchemyAgRetentionCandidateStore",
    ),
    (
        "archive_receipt_builder",
        "services/nex-ag/nex_ag/audit_retention_archive.py",
        "def build_ag_archive_receipt",
    ),
    (
        "purge_execution",
        "services/nex-ag/nex_ag/audit_retention_purge.py",
        "def execute_ag_retention_purge",
    ),
    (
        "operations_projection",
        "services/nex-ag/nex_ag/audit_retention_operations.py",
        "def build_ag_audit_retention_operations_projection",
    ),
    (
        "receipt_migration",
        "database/nex-ag/migrations/0884_ag_retention_archive_receipts.sql",
        "CREATE TABLE IF NOT EXISTS ag_ret_archives",
    ),
    (
        "index_migration",
        "database/nex-ag/migrations/0887_ag_retention_candidate_indexes.sql",
        "0887_ag_retention_candidate_indexes",
    ),
    (
        "openapi_projection",
        "contracts/openapi/nex-ag.openapi.yaml",
        "getAgAuditRetentionOperationsProjection",
    ),
    (
        "openapi_purge",
        "contracts/openapi/nex-ag.openapi.yaml",
        "executeAgAuditRetentionPurge",
    ),
    (
        "strict_contract",
        "contracts/schemas/service/nex_ag/audit_retention.v1.schema.json",
        "ag_audit_retention_operations_projection.v1",
    ),
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_ag_audit_retention_archive_purge_boundary_audit.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_ag_audit_retention_postgres_smoke.py",
    ),
    (
        "quality_privacy",
        QUALITY_GATE_PATH,
        "run_ag_audit_retention_privacy_runbook_evidence.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s89_ag_audit_retention_closure.py",
    ),
    ("postgres_pass", POSTGRES_SMOKE_DOC, "live smoke: PASS"),
    ("postgres_lifecycle", POSTGRES_SMOKE_DOC, "candidates=2 purged=2"),
    ("postgres_indexes", POSTGRES_SMOKE_DOC, "indexes=2"),
    (
        "postgres_cleanup",
        POSTGRES_SMOKE_DOC,
        "event_residue=0 export_residue=0 receipt_residue=0",
    ),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "ag_audit_retention_privacy_runbook=pass",
    ),
    (
        "docs_index_0890",
        "docs/README.md",
        "0890_s89_ag_audit_retention_closure.md",
    ),
)


def run_s89_ag_audit_retention_closure(
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
    decision = _mapping(boundary.get("decision"))
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "boundary_decision_preserved": (
            decision.get("archive_payload_authority")
            == "external_injected_adapter"
            and decision.get("metadata_only_manifest_allows_purge") is False
            and decision.get("physical_purge_requires_sealed_archive_receipt")
            is True
        ),
        "runtime_policy_validated": runtime.get("policy_status") == "VALIDATED",
        "runtime_candidate_selected": runtime.get("candidate_status") == "SELECTED",
        "runtime_receipt_sealed": runtime.get("receipt_status") == "SEALED",
        "runtime_dry_run_eligible": runtime.get("dry_run_status") == "ELIGIBLE",
        "runtime_purge_completed": runtime.get("execute_status") == "PURGED",
        "runtime_retry_idempotent": runtime.get("retry_status") == "NOOP",
        "runtime_redacted": runtime.get("raw_values_exposed") is False,
        "contracts_valid": contracts.get("status") == "PASS",
        "privacy_runbook_passed": privacy.get("status") == "PASS",
        "privacy_checks_passed": all(_mapping(privacy.get("checks")).values()),
        "postgres_protection_respected": postgres.get("status")
        == expected_postgres_status,
        "postgres_actual_pass_when_opted_in": (
            not postgres_opted_in or postgres.get("status") == "PASS"
        ),
        "postgres_documented_pass_present": all(postgres_doc.values()),
        "short_identifiers_only": all(
            len(name) <= 30 for name in (*NEW_TABLES, *NEW_INDEXES)
        ),
        "s90_scope_preserved": "ag_mvp_acceptance_and_cx_transition_s90"
        in boundary.get("deferred_scope", []),
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s89_ag_audit_retention_closure_failed",
        "slice_range": SLICE_RANGE,
        "boundary": "ag_audit_evidence_retention_archive_and_guarded_purge",
        "source_tables": list(SOURCE_TABLES),
        "new_tables": list(NEW_TABLES),
        "new_indexes": list(NEW_INDEXES),
        "archive_payload_authority": "external_injected_adapter",
        "production_object_storage_implemented": False,
        "postgres_smoke_opted_in": postgres_opted_in,
        "deferred_requirements": [
            "production object storage provider selection",
            "cross-service retention orchestration",
            "legal hold case management",
            "S90 AG MVP acceptance and CX transition",
        ],
        "closure_surfaces": [
            "boundary_decision",
            "validated_retention_policy",
            "bounded_candidate_read_model",
            "recoverable_archive_receipt_sealing",
            "guarded_transactional_purge",
            "protected_operations_api",
            "openapi_json_schema_contracts",
            "test_db_postgres_lifecycle_smoke",
            "privacy_failure_operator_runbook",
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
    raw_message = "private-s89-closure-message-0890"
    raw_detail = "private-s89-closure-detail-0890"
    raw_object_ref = "archive://private-s89-closure-object-0890"
    source = {
        "event_id": "event-0890",
        "service_id": "nex-ag",
        "event_type": "ag.audit_retention.closure_source",
        "severity": "INFO",
        "trace_id": "d" * 32,
        "request_id": "request-0890",
        "subject_type": "s89_closure",
        "subject_id": "source-0890",
        "message": raw_message,
        "details": {"raw_payload": raw_detail},
        "created_at": "2024-01-01T00:00:00Z",
    }
    policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_ARCHIVE_PROVIDER_MODE": "external",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": "true",
            "NEX_AG_ARCHIVE_GRACE_DAYS": "1",
        }
    )
    candidate_store = InMemoryAgRetentionCandidateStore(event_records=[source])
    candidate_page = candidate_store.list_candidates(
        policy=policy,
        as_of="2026-09-20T12:00:00Z",
    )
    candidate = candidate_page["items"][0]
    receipt = build_ag_archive_receipt(
        candidate=candidate,
        provider_result={
            "provider_mode": "external",
            "content_sha256": candidate["content_sha256"],
            "object_ref": raw_object_ref,
            "receipt_sha256": "e" * 64,
            "recoverable": True,
        },
        archived_at="2026-08-01T00:00:00Z",
        grace_days=1,
    )
    receipt_store = InMemoryAgArchiveReceiptStore()
    receipt_store.save(receipt)
    purge_store = InMemoryAgRetentionPurgeStore(
        receipt_store=receipt_store,
        source_records={("operational_event", "event-0890"): source},
    )
    operations = build_ag_audit_retention_operations_projection(
        policy=policy,
        candidate_store=candidate_store,
        receipt_store=receipt_store,
        as_of="2026-09-20T12:00:00Z",
    )
    execution_args = {
        "store": purge_store,
        "policy": policy,
        "source_kind": "operational_event",
        "source_id": "event-0890",
        "as_of": "2026-09-20T12:00:00Z",
    }
    dry_run = execute_ag_retention_purge(**execution_args)
    executed = execute_ag_retention_purge(
        **execution_args,
        mode="EXECUTE",
        confirmation="PURGE",
    )
    retried = execute_ag_retention_purge(
        **execution_args,
        mode="EXECUTE",
        confirmation="PURGE",
    )
    serialized = json.dumps(
        {
            "policy": policy,
            "candidate_page": candidate_page,
            "receipt": receipt,
            "operations": operations,
            "dry_run": dry_run,
            "executed": executed,
            "retried": retried,
        },
        sort_keys=True,
    )
    return {
        "status": "PASS",
        "policy_status": "VALIDATED"
        if policy["archive"]["provider_mode"] == "external"
        and policy["purge"]["execute_enabled"] is True
        else "INVALID",
        "candidate_status": "SELECTED"
        if candidate_page["candidate_count"] == 1
        else "MISSING",
        "receipt_status": receipt["archive_status"],
        "dry_run_status": dry_run["status"],
        "execute_status": executed["status"],
        "retry_status": retried["status"],
        "source_deleted": not purge_store.source_records,
        "raw_values_exposed": any(
            value in serialized for value in (raw_message, raw_detail, raw_object_ref)
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
        "summary_pass": "live smoke: PASS" in content,
        "two_candidates_purged": "candidates=2 purged=2" in content,
        "indexes": "indexes=2" in content,
        "migration": "migration_present=true" in content,
        "cleanup": (
            "cleaned=True" in content
            and "event_residue=0 export_residue=0 receipt_residue=0" in content
        ),
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
            "s89_ag_audit_retention_closure=fail "
            f"missing_files={summary.get('missing_file_count')} "
            f"missing_tokens={summary.get('missing_token_count')}"
        )
    postgres = _mapping(evidence.get("postgres_smoke"))
    privacy = _mapping(evidence.get("privacy_runbook"))
    contracts = _mapping(evidence.get("contract_validation"))
    return (
        "s89_ag_audit_retention_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"contracts={contracts.get('status')} "
        f"postgres={postgres.get('status')} "
        f"privacy={privacy.get('status')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s89_ag_audit_retention_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
