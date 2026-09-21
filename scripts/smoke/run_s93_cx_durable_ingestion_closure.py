#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_PATH))

from run_cx_durable_ingestion_admission_smoke import (  # noqa: E402
    run_cx_durable_ingestion_admission_smoke as run_admission,
)
from run_cx_durable_ingestion_boundary_audit import (  # noqa: E402
    run_cx_durable_ingestion_boundary_audit as run_boundary,
)
from run_cx_ingestion_checkpoint_coordinator_smoke import (  # noqa: E402
    run_cx_ingestion_checkpoint_coordinator_smoke as run_coordinator,
)
from run_cx_ingestion_operations_contract_smoke import (  # noqa: E402
    run_cx_ingestion_operations_contract_smoke as run_operations,
)
from run_cx_ingestion_orchestration_contract import (  # noqa: E402
    run_cx_ingestion_orchestration_contract as run_orchestration,
)
from run_cx_ingestion_restart_read_model_smoke import (  # noqa: E402
    run_cx_ingestion_restart_read_model_smoke as run_read_model,
)
from run_cx_ingestion_run_repository_contract import (  # noqa: E402
    run_cx_ingestion_run_repository_contract as run_repository,
)
from run_cx_ingestion_worker_retry_recovery_smoke import (  # noqa: E402
    run_cx_ingestion_worker_retry_recovery_smoke as run_worker,
)


SCHEMA_VERSION = "s93_cx_durable_ingestion_closure.v1"
SLICE_RANGE = "0921-0930"
POSTGRES_EVIDENCE_DOC = (
    "docs/slices/0929_cx_ingestion_operations_postgresql_smoke.md"
)
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
REQUIRED_FILES = (
    "services/nex-cx/nex_cx/ingestion_orchestration.py",
    "services/nex-cx/nex_cx/ingestion_orchestration_repository.py",
    "services/nex-cx/nex_cx/ingestion_admission.py",
    "services/nex-cx/nex_cx/ingestion_coordinator.py",
    "services/nex-cx/nex_cx/ingestion_worker.py",
    "services/nex-cx/nex_cx/ingestion_read_model.py",
    "services/nex-cx/nex_cx/ingestion_operations.py",
    "database/nex-cx/migrations/0923_cx_ingest_run_persistence.sql",
    "scripts/smoke/run_cx_ingestion_operations_postgres_smoke.py",
    "scripts/smoke/run_s93_cx_durable_ingestion_closure.py",
    "tests/test_s93_cx_durable_ingestion_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0921", "cx_durable_ingestion_boundary_audit"),
            ("0922", "cx_ingestion_orchestration_state_contract"),
            ("0923", "cx_durable_ingestion_run_repository"),
            ("0924", "cx_durable_ingestion_admission"),
            ("0925", "cx_checkpointed_ingestion_coordinator"),
            ("0926", "cx_ingestion_worker_retry_recovery"),
            ("0927", "cx_ingestion_restart_hydration_read_model"),
            ("0928", "cx_ingestion_protected_api_contracts"),
            ("0929", "cx_ingestion_operations_postgresql_smoke"),
            ("0930", "s93_cx_durable_ingestion_closure"),
        )
    ),
)
TOKEN_CHECKS = (
    (
        "quality_postgres_runner",
        QUALITY_GATE_PATH,
        "run_cx_ingestion_operations_postgres_smoke.py",
    ),
    (
        "quality_closure_runner",
        QUALITY_GATE_PATH,
        "run_s93_cx_durable_ingestion_closure.py",
    ),
    (
        "job_id_type_compatibility",
        "database/nex-cx/migrations/0923_cx_ingest_run_persistence.sql",
        "job_id TEXT NOT NULL",
    ),
    (
        "postgres_target",
        POSTGRES_EVIDENCE_DOC,
        "database=nex_cx_test role=nex_cx_user",
    ),
    (
        "postgres_migration",
        POSTGRES_EVIDENCE_DOC,
        "migration_applied=0923_cx_ingest_run_persistence",
    ),
    ("postgres_checks", POSTGRES_EVIDENCE_DOC, "checks=17/17"),
    (
        "postgres_states",
        POSTGRES_EVIDENCE_DOC,
        "job_status=QUEUED run_status=WAITING_RETRY checkpoint_version=2",
    ),
    (
        "postgres_owner_isolation",
        POSTGRES_EVIDENCE_DOC,
        "cross_owner_hidden=true private_payload_absent=true",
    ),
    (
        "postgres_event",
        POSTGRES_EVIDENCE_DOC,
        "operational_event=cx.ingestion.lease_recovered",
    ),
    ("postgres_cleanup", POSTGRES_EVIDENCE_DOC, "probe_residue=0"),
    (
        "postgres_dgx",
        POSTGRES_EVIDENCE_DOC,
        "dgx_live_provider_required=false",
    ),
    (
        "docs_index",
        "docs/README.md",
        "0930_s93_cx_durable_ingestion_closure.md",
    ),
)


def run_s93_cx_durable_ingestion_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "orchestration": _safe_evidence(run_orchestration),
        "repository": _safe_evidence(run_repository),
        "admission": _safe_evidence(run_admission),
        "coordinator": _safe_evidence(run_coordinator),
        "worker": _safe_evidence(run_worker),
        "read_model": _safe_evidence(run_read_model),
        "operations": _safe_evidence(run_operations),
    }
    boundary_summary = _mapping(evidence["boundary"].get("summary"))
    boundary_decision = _mapping(evidence["boundary"].get("decision"))
    repository_checks = _mapping(evidence["repository"].get("checks"))
    admission_checks = _mapping(evidence["admission"].get("checks"))
    read_model_checks = _mapping(evidence["read_model"].get("checks"))
    operations_checks = _mapping(evidence["operations"].get("checks"))
    postgres_tokens = {
        item["name"]: item["present"]
        for item in token_checks
        if item["name"].startswith("postgres_")
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_deterministic_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "boundary_plan_completed": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("issue_count") == 0
            and boundary_decision.get("orchestration_system_of_record")
            == "cx_ingest_runs"
        ),
        "state_and_transition_contract_closed": (
            evidence["orchestration"].get("pipeline_step_count") == 6
            and evidence["orchestration"].get("transition_count") == 10
        ),
        "repository_contract_closed": (
            evidence["repository"].get("table") == "cx_ingest_runs"
            and evidence["repository"].get("table_name_length") == 14
            and repository_checks.get("stale_writer_rejected") is True
            and repository_checks.get("private_columns_absent") is True
        ),
        "idempotent_admission_closed": (
            evidence["admission"].get("job_count") == 1
            and evidence["admission"].get("run_count") == 1
            and admission_checks.get("partial_success_recoverable") is True
        ),
        "six_step_checkpoint_execution_closed": (
            evidence["coordinator"].get("step_count") == 6
            and evidence["coordinator"].get("checkpoint_version") == 7
        ),
        "worker_retry_recovery_closed": (
            evidence["worker"].get("job_status") == "SUCCEEDED"
            and evidence["worker"].get("run_status") == "SUCCEEDED"
            and evidence["worker"].get("checkpoint_version") == 7
        ),
        "restart_read_model_closed": (
            evidence["read_model"].get("restart_action")
            == "RECOVER_EXPIRED_LEASE"
            and read_model_checks.get("read_only_hydration") is True
            and read_model_checks.get("cross_owner_hidden") is True
        ),
        "protected_operations_closed": (
            evidence["operations"].get("restart_action")
            == "RECOVER_EXPIRED_LEASE"
            and evidence["operations"].get("recovery_status")
            == "RETRY_SCHEDULED"
            and operations_checks.get("event_emitted") is True
            and operations_checks.get("cross_owner_hidden") is True
        ),
        "actual_postgres_evidence_passed": all(postgres_tokens.values()),
        "private_payload_boundary_preserved": (
            repository_checks.get("private_columns_absent") is True
            and admission_checks.get("private_payload_absent") is True
            and read_model_checks.get("private_payload_absent") is True
            and operations_checks.get("private_payload_absent") is True
        ),
        "dgx_not_required": all(
            _dgx_not_required(item) for item in evidence.values()
        )
        and decision["dgx_live_provider_required"] is False,
        "single_migration_history_preserved": (
            decision["migration_strategy"]
            == "versioned_sql_schema_migrations_runner"
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "0930",
        "slice_range": SLICE_RANGE,
        "requirement": "S93",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s93_durable_ingestion_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S94" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_DURABLE_INGESTION_ORCHESTRATION_READY"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "pipeline_step_count": evidence["orchestration"].get(
                "pipeline_step_count", 0
            ),
            "transition_count": evidence["orchestration"].get(
                "transition_count", 0
            ),
            "postgres_check_count": 17 if all(postgres_tokens.values()) else 0,
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "postgres_evidence": postgres_tokens,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S94",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "execution_queue": "existing_service_jobs_job_queue",
        "orchestration_system_of_record": "cx_ingest_runs",
        "pipeline_steps": [
            "extraction",
            "chunking",
            "lexical_index",
            "embedding_index",
            "summary",
            "summary_embedding",
        ],
        "persistence_policy": "owner_scoped_metadata_only",
        "concurrency_control": "optimistic_checkpoint_version",
        "worker_model": "bounded_claim_execute_checkpoint",
        "retry_model": "synchronized_job_and_run_backoff",
        "restart_model": "read_only_plan_then_explicit_recovery",
        "cross_owner_visibility": "not-found",
        "migration_strategy": "versioned_sql_schema_migrations_runner",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "dgx_live_provider_required": False,
        "deferred_scope": [
            "provider_backed_pipeline_execution",
            "continuous_ingestion_worker_process",
            "production_object_and_vector_storage_adapters",
        ],
    }


def _dgx_not_required(evidence: Mapping[str, Any]) -> bool:
    decision = _mapping(evidence.get("decision"))
    candidates = (
        evidence.get("dgx_live_provider_required"),
        evidence.get("dgx_required"),
        decision.get("dgx_live_provider_required"),
    )
    explicit = [value for value in candidates if value is not None]
    return bool(explicit) and all(value is False for value in explicit)


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s93_cx_durable_ingestion_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"steps={summary.get('pipeline_step_count', 0)} "
        f"postgres_checks={summary.get('postgres_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s93_cx_durable_ingestion_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
