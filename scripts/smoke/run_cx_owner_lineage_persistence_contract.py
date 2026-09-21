#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping

from nex_cx.access_context import CxAccessContext
from nex_cx.generation_persistence import build_generation_persistence_record
from nex_cx.owner_lineage import OWNER_LINEAGE_COLUMN_NAMES, build_owner_lineage


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_owner_lineage_persistence_contract.v1"
MIGRATION = Path("database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql")
REQUIRED_PATHS = (
    MIGRATION,
    Path("services/nex-cx/nex_cx/owner_lineage.py"),
    Path("services/nex-cx/nex_cx/generation_persistence.py"),
    Path("docs/slices/0917_cx_owner_lineage_persistence.md"),
    Path("scripts/quality/run_quality_gate.sh"),
)
LINEAGE_TABLES = (
    "service_jobs",
    "cx_document_processing_runs",
    "cx_retrieval_packages",
    "cx_remediation_execution_attempts",
)
FORBIDDEN_GENERATION_COLUMNS = (
    "prompt",
    "messages",
    "raw_output",
    "output_preview",
    "chunk_text",
    "summary_text",
    "embedding",
    "vector",
    "bytea",
)
_NAMED_SQL_OBJECT = re.compile(
    r"(?:CONSTRAINT|INDEX IF NOT EXISTS|FUNCTION|TRIGGER|TABLE IF NOT EXISTS)"
    r"\s+([a-z][a-z0-9_]*)",
    re.IGNORECASE,
)


def run_cx_owner_lineage_persistence_contract(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_paths = [
        {"path": str(path), "present": (root / path).is_file()}
        for path in REQUIRED_PATHS
    ]
    migration = _read_text(root / MIGRATION)
    generation_ddl = _table_ddl(migration, "cx_generation_executions")
    sql_names = sorted(set(_NAMED_SQL_OBJECT.findall(migration)))
    lineage = build_owner_lineage(
        CxAccessContext(
            caller_service_id="nex-cx",
            tenant_id="tenant-s92",
            subject_id="employee-0917",
            request_id="request-0917",
            trace_id="91700000000000000000000000000001",
            scopes=("service:call",),
        )
    )
    persisted = build_generation_persistence_record(
        {
            "record_schema_version": "cx_generation_execution_record.v1",
            "cx_generation_id": "cx-gen-0917",
            "status": "COMPLETED",
            "trace_id": "91700000000000000000000000000001",
            "request_id": "request-0917",
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "mo_generation_id": "mo-gen-0917",
            "request_metadata": {
                "generation_request_hash": "a" * 64,
                "retrieval_package_id": "91700000-0000-0000-0000-000000000001",
                "prompt": "must-not-persist",
            },
            "response_metadata": {
                "finish_reason": "stop",
                "output_hash": "b" * 64,
                "output_preview": "must-not-persist",
            },
            "mo_runtime_metadata": {"total_ms": 10},
            "usage": {"input_tokens": 2, "output_tokens": 3},
            "created_at": datetime(2026, 9, 21, tzinfo=UTC),
            "updated_at": datetime(2026, 9, 21, tzinfo=UTC),
        },
        owner_lineage=lineage,
    )
    serialized_record = repr(persisted).lower()
    checks = {
        "required_paths_present": all(item["present"] for item in required_paths),
        "migration_transactional": migration.startswith("BEGIN;")
        and migration.rstrip().endswith("COMMIT;"),
        "lineage_targets_present": all(
            f"ALTER TABLE {table}" in migration for table in LINEAGE_TABLES
        ),
        "lineage_columns_present": all(
            migration.count(f"ADD COLUMN IF NOT EXISTS {column}")
            == len(LINEAGE_TABLES)
            for column in OWNER_LINEAGE_COLUMN_NAMES
        ),
        "lineage_backfill_present": all(
            token in migration
            for token in (
                "UPDATE cx_document_processing_runs AS run",
                "UPDATE service_jobs AS job",
                "UPDATE cx_retrieval_packages AS package",
            )
        ),
        "lineage_triggers_present": all(
            token in migration
            for token in (
                "tr_cx_proc_runs_apply_owner",
                "tr_cx_jobs_apply_owner",
                "tr_cx_ret_evidence_apply_owner",
            )
        ),
        "mixed_owner_history_rejected": (
            "Existing CX retrieval package mixes owner scopes" in migration
        ),
        "generation_table_metadata_only": bool(generation_ddl)
        and not any(
            re.search(rf"^\s*{term}\s+", generation_ddl, re.IGNORECASE | re.MULTILINE)
            for term in FORBIDDEN_GENERATION_COLUMNS
        )
        and "ck_cx_gen_exec_private_keys" in generation_ddl,
        "owner_indexes_present": all(
            token in migration
            for token in (
                "idx_svc_jobs_owner_created",
                "idx_cx_proc_owner_updated",
                "idx_cx_ret_owner_created",
                "idx_cx_rem_owner_updated",
                "idx_cx_gen_owner_created",
            )
        ),
        "sql_identifiers_bounded": bool(sql_names)
        and all(len(name) <= 63 for name in sql_names),
        "persistence_record_owner_scoped": all(
            persisted.get(key) == value
            for key, value in lineage.to_columns().items()
        ),
        "persistence_record_private_payload_free": not any(
            term in serialized_record
            for term in ("must-not-persist", "output_preview", "prompt")
        ),
        "quality_gate_hook_present": (
            "run_cx_owner_lineage_persistence_contract.py"
            in _read_text(root / "scripts/quality/run_quality_gate.sh")
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    return {
        "contract_schema_version": SCHEMA_VERSION,
        "slice": "0917",
        "requirement": "S92",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "cx_owner_lineage_persistence_failed",
        "decision": {
            "owner_source": "authenticated_cx_access_context",
            "public_database_policy": "metadata_and_owner_lineage_only",
            "generation_payload_policy": "allowlisted_metadata_without_preview",
            "legacy_row_policy": "nullable_then_backfill",
            "mixed_owner_retrieval_policy": "reject",
            "postgres_smoke_slice": "0919",
            "dgx_live_provider_required": False,
        },
        "summary": {
            "lineage_table_count": len(LINEAGE_TABLES),
            "generation_table_count": 1,
            "sql_identifier_count": len(sql_names),
            "check_count": len(checks),
            "issue_count": len(issues),
        },
        "checks": checks,
        "required_paths": required_paths,
        "issues": issues,
        "next_slice": "0918",
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _table_ddl(sql: str, table_name: str) -> str:
    marker = f"CREATE TABLE IF NOT EXISTS {table_name}"
    start = sql.find(marker)
    if start < 0:
        return ""
    end = sql.find(";", start)
    return sql[start:] if end < 0 else sql[start : end + 1]


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    decision = evidence.get("decision") or {}
    return (
        "cx_owner_lineage_persistence="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"tables={summary.get('lineage_table_count', 0)} "
        f"checks={summary.get('check_count', 0)} "
        f"dgx_required={decision.get('dgx_live_provider_required', False)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_owner_lineage_persistence_contract()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
