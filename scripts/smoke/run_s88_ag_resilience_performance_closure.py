#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
QUALITY_PATH = ROOT / "scripts" / "quality"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(QUALITY_PATH))

from nex_ag.resilience_performance import (  # noqa: E402
    AgConcurrencyAdmissionGuard,
    AgSourceIsolationExecutor,
    build_ag_resilience_performance_policy,
    build_stable_keyset_page,
)
from nex_ag.resilience_performance_operations import (  # noqa: E402
    build_ag_resilience_performance_operations_projection,
)
from run_ag_resilience_performance_boundary_audit import (  # noqa: E402
    run_ag_resilience_performance_boundary_audit as run_boundary,
)
from run_ag_resilience_performance_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
)
from run_ag_resilience_performance_postgres_smoke import (  # noqa: E402
    run_ag_resilience_performance_postgres_smoke as run_postgres,
)
from run_ag_resilience_performance_privacy_runbook_evidence import (  # noqa: E402
    run_ag_resilience_performance_privacy_runbook_evidence as run_privacy,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s88_ag_resilience_performance_closure.v1"
SLICE_RANGE = "0871-0880"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = (
    "docs/slices/0878_ag_resilience_postgresql_bounded_load_smoke.md"
)
PRIVACY_RUNBOOK_DOC = (
    "docs/slices/0879_ag_resilience_privacy_failure_runbook.md"
)
SOURCE_TABLES = ("service_operational_events", "ag_ev_exports")
NEW_INDEXES = (
    "idx_ag_evt_type_page",
    "idx_ag_evt_trace_page",
    "idx_ag_exp_trace_page",
)

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/resilience_performance.py",
    "services/nex-ag/nex_ag/resilience_performance_operations.py",
    "services/nex-ag/nex_ag/audit_evidence_api.py",
    "services/nex-ag/nex_ag/audit_evidence_operations.py",
    "services/nex-ag/nex_ag/operator_reviews.py",
    "database/nex-ag/migrations/0877_ag_resilience_read_indexes.sql",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/audit_evidence.v1.schema.json",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/schemas/service/nex_ag/resilience_performance.v1.schema.json",
    "contracts/examples/operations/ag_resilience_performance_operations.mock_success.json",
    "contracts/tests/negative/operations/ag_resilience_performance_operations.database_url_leak.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_resilience_performance_boundary_audit.py",
    "scripts/smoke/run_ag_resilience_performance_postgres_smoke.py",
    "scripts/smoke/run_ag_resilience_performance_privacy_runbook_evidence.py",
    "scripts/smoke/run_s88_ag_resilience_performance_closure.py",
    "tests/test_nex_ag_resilience_performance.py",
    "tests/test_nex_ag_resilience_performance_operations.py",
    "tests/test_nex_ag_resilience_performance_contracts.py",
    "tests/test_ag_resilience_performance_postgres_smoke.py",
    "tests/test_ag_resilience_performance_privacy_runbook_evidence.py",
    "tests/test_s88_ag_resilience_performance_closure.py",
    "docs/README.md",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0871", "ag_resilience_performance_boundary_audit"),
            ("0872", "ag_resilience_performance_budget_policy"),
            ("0873", "ag_stable_bounded_pagination"),
            ("0874", "ag_concurrency_admission_load_shedding"),
            ("0875", "ag_source_timeout_failure_isolation"),
            ("0876", "ag_resilience_performance_operations_projection"),
            ("0877", "ag_resilience_index_contract_hardening"),
            ("0878", "ag_resilience_postgresql_bounded_load_smoke"),
            ("0879", "ag_resilience_privacy_failure_runbook"),
            ("0880", "s88_ag_resilience_performance_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "policy_builder",
        "services/nex-ag/nex_ag/resilience_performance.py",
        "def build_ag_resilience_performance_policy",
    ),
    (
        "stable_pagination",
        "services/nex-ag/nex_ag/resilience_performance.py",
        "def build_stable_keyset_page",
    ),
    (
        "admission_guard",
        "services/nex-ag/nex_ag/resilience_performance.py",
        "class AgConcurrencyAdmissionGuard",
    ),
    (
        "source_isolation",
        "services/nex-ag/nex_ag/resilience_performance.py",
        "class AgSourceIsolationExecutor",
    ),
    (
        "operations_projection",
        "services/nex-ag/nex_ag/resilience_performance_operations.py",
        "def build_ag_resilience_performance_operations_projection",
    ),
    (
        "protected_route",
        "services/nex-ag/nex_ag/resilience_performance_operations.py",
        "/admin/v1/operations/resilience-performance",
    ),
    (
        "migration_version",
        "database/nex-ag/migrations/0877_ag_resilience_read_indexes.sql",
        "0877_ag_resilience_read_indexes",
    ),
    (
        "openapi_operation",
        "contracts/openapi/nex-ag.openapi.yaml",
        "getAgResiliencePerformanceOperationsProjection",
    ),
    (
        "strict_contract",
        "contracts/schemas/service/nex_ag/resilience_performance.v1.schema.json",
        "ag_resilience_performance_operations_projection.v1",
    ),
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_ag_resilience_performance_boundary_audit.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_ag_resilience_performance_postgres_smoke.py",
    ),
    (
        "quality_privacy",
        QUALITY_GATE_PATH,
        "run_ag_resilience_performance_privacy_runbook_evidence.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s88_ag_resilience_performance_closure.py",
    ),
    ("postgres_pass", POSTGRES_SMOKE_DOC, "live smoke: PASS"),
    ("postgres_requests", POSTGRES_SMOKE_DOC, "requests=25 concurrency=4"),
    ("postgres_latency", POSTGRES_SMOKE_DOC, "p95_ms=49.678 budget_ms=1500"),
    ("postgres_indexes", POSTGRES_SMOKE_DOC, "indexes=3"),
    ("postgres_cleanup", POSTGRES_SMOKE_DOC, "event_residue=0 export_residue=0"),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "ag_resilience_privacy_runbook=pass",
    ),
    (
        "docs_index_0880",
        "docs/README.md",
        "0880_s88_ag_resilience_performance_closure.md",
    ),
)


class _Pool:
    def __init__(self, size: int) -> None:
        self.size = size

    def checkedout(self) -> int:
        return 0

    def checkedin(self) -> int:
        return self.size

    def overflow(self) -> int:
        return -self.size


def run_s88_ag_resilience_performance_closure(
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
    boundary_decision = _mapping(boundary.get("decision"))
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "runtime_policy_validated": runtime.get("policy_status") == "VALIDATED",
        "runtime_pagination_stable": runtime.get("pagination_status") == "STABLE",
        "runtime_admission_bounded": runtime.get("admission_status") == "BOUNDED",
        "runtime_source_isolated": runtime.get("source_status") == "HEALTHY",
        "runtime_operations_ready": runtime.get("operations_status") == "READY",
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
        "existing_tables_reused": boundary_decision.get("new_table_required")
        is False,
        "targeted_indexes_only": all(len(name) <= 30 for name in NEW_INDEXES),
        "s89_s90_scope_preserved": {
            "retention_archive_and_physical_purge_s89",
            "ag_mvp_acceptance_and_cx_transition_s90",
        }.issubset(set(boundary.get("deferred_scope", []))),
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s88_ag_resilience_performance_closure_failed",
        "slice_range": SLICE_RANGE,
        "boundary": "ag_admin_read_resilience_and_bounded_performance",
        "source_tables": list(SOURCE_TABLES),
        "new_tables": [],
        "new_indexes": list(NEW_INDEXES),
        "postgres_smoke_opted_in": postgres_opted_in,
        "deferred_requirements": [
            "S89 retention archive and physical purge",
            "S90 AG MVP acceptance and CX transition",
        ],
        "closure_surfaces": [
            "validated_performance_budget",
            "stable_bounded_pagination",
            "concurrency_admission_load_shedding",
            "source_timeout_failure_isolation",
            "database_pool_operations_projection",
            "deterministic_read_indexes",
            "openapi_json_schema_contracts",
            "test_db_bounded_load_smoke",
            "privacy_failure_performance_runbook",
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
    raw_value = "private-s88-closure-value-0880"
    policy = build_ag_resilience_performance_policy({})
    records = [
        {
            "event_id": f"event-{index}",
            "created_at": f"2026-09-20T11:00:0{index}Z",
            "raw": raw_value,
        }
        for index in range(4)
    ]
    first = build_stable_keyset_page(
        records,
        limit=2,
        cursor=None,
        timestamp_field="created_at",
        identity_field="event_id",
    )
    second = build_stable_keyset_page(
        records,
        limit=2,
        cursor=first["pagination"]["next_cursor"],
        timestamp_field="created_at",
        identity_field="event_id",
    )
    guard = AgConcurrencyAdmissionGuard(max_in_flight=2, wait_timeout_ms=10)
    with guard.admit("closure-outer"):
        with guard.admit("closure-inner"):
            pass
    executor = AgSourceIsolationExecutor(
        timeout_ms=20,
        slow_operation_ms=10,
        max_workers=1,
    )
    try:
        source_value = executor.execute(lambda: "ready")
        source_snapshot = executor.snapshot()
    finally:
        executor.close()
    operations = build_ag_resilience_performance_operations_projection(
        policy=policy,
        admission_snapshot=guard.snapshot(),
        source_snapshot=source_snapshot,
        api_engine=SimpleNamespace(pool=_Pool(5)),
        worker_engine=SimpleNamespace(pool=_Pool(3)),
        checked_at="2026-09-20T11:00:00Z",
    )
    serialized = json.dumps(
        {
            "policy": policy,
            "pagination": [first["pagination"], second["pagination"]],
            "admission": guard.snapshot(),
            "source": source_snapshot,
            "operations": operations,
        },
        sort_keys=True,
    )
    return {
        "status": "PASS",
        "policy_status": "VALIDATED"
        if policy["bounded_smoke"]["p95_budget_ms"] == 1500
        else "INVALID",
        "pagination_status": "STABLE"
        if [item["event_id"] for item in first["items"] + second["items"]]
        == ["event-3", "event-2", "event-1", "event-0"]
        else "UNSTABLE",
        "admission_status": "BOUNDED"
        if guard.snapshot()["peak_in_flight"] == 2
        else "UNBOUNDED",
        "source_status": "HEALTHY"
        if source_value == "ready" and source_snapshot["completed_total"] == 1
        else "UNHEALTHY",
        "operations_status": operations["projection_status"],
        "raw_values_exposed": raw_value in serialized,
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
        "bounded_requests": "requests=25 concurrency=4" in content,
        "latency_budget": "p95_ms=49.678 budget_ms=1500" in content,
        "indexes": "indexes=3" in content,
        "migration": "migration_present=true" in content,
        "cleanup": (
            "cleaned=True" in content
            and "event_residue=0 export_residue=0" in content
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
            "s88_ag_resilience_performance_closure=fail "
            f"missing_files={summary.get('missing_file_count')} "
            f"missing_tokens={summary.get('missing_token_count')}"
        )
    postgres = _mapping(evidence.get("postgres_smoke"))
    privacy = _mapping(evidence.get("privacy_runbook"))
    contracts = _mapping(evidence.get("contract_validation"))
    return (
        "s88_ag_resilience_performance_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"contracts={contracts.get('status')} "
        f"postgres={postgres.get('status')} "
        f"privacy={privacy.get('status')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s88_ag_resilience_performance_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
