#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ae_operator_control_execution_worker_result_persistence_boundary_audit.v1"
)

S62_SURFACE = "S62 AE operator-control execution worker result persistence"
RESULT_PERSISTENCE_BOUNDARY = "ae_owned_safe_summary_worker_result_persistence"
RESULT_TABLE = "ae_op_exec_worker_results"
EVENT_TABLE = "ae_op_exec_worker_events"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0612"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE",
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE",
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE",
    "NEX_AG_AE_ARTIFACT_BASE_URL",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)


@dataclass(frozen=True)
class RequiredPath:
    name: str
    relative_path: str
    purpose: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    relative_path: str
    token_id: str
    token: str
    purpose: str


REQUIRED_PATHS = (
    RequiredPath(
        "ae_daemon_runtime",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE daemon worker contracts and worker result builders.",
    ),
    RequiredPath(
        "ae_artifacts_routes",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE artifact retention route surface.",
    ),
    RequiredPath(
        "ag_artifact_operations",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG read-only worker projection surface.",
    ),
    RequiredPath(
        "ae_execution_migration",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "Existing AE execution state/transition persistence baseline.",
    ),
    RequiredPath(
        "s61_closure",
        "scripts/smoke/run_s61_ae_operator_control_execution_worker_closure.py",
        "S61 worker execution closure checkpoint.",
    ),
    RequiredPath(
        "s61_closure_doc",
        "docs/slices/0610_s61_ae_operator_control_execution_worker_closure.md",
        "S61 closure implementation note.",
    ),
    RequiredPath(
        "s62_boundary_audit",
        "scripts/smoke/run_ae_operator_control_execution_worker_result_persistence_boundary_audit.py",
        "S62 worker result persistence boundary audit.",
    ),
    RequiredPath(
        "s62_boundary_test",
        "tests/test_ae_operator_control_execution_worker_result_persistence_boundary_audit.py",
        "S62 boundary regression tests.",
    ),
    RequiredPath(
        "s62_boundary_doc",
        "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
        "Slice 0611 implementation note.",
    ),
    RequiredPath(
        "ae_worker_postgres_smoke",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "AE worker route PostgreSQL smoke evidence baseline.",
    ),
    RequiredPath(
        "ag_worker_postgres_smoke",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "AG-to-AE worker PostgreSQL smoke evidence baseline.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath(
        "ae_readme",
        "services/nex-ae-api/README.md",
        "AE service implementation notes.",
    ),
    RequiredPath(
        "ag_readme",
        "services/nex-ag/README.md",
        "AG service implementation notes.",
    ),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s61_closed_baseline",
        "scripts/smoke/run_s61_ae_operator_control_execution_worker_closure.py",
        "s61_closure_schema",
        "s61_ae_operator_control_execution_worker_closure.v1",
        "S62 must start after the full S61 worker execution closure.",
    ),
    TokenRequirement(
        "s61_closed_baseline",
        "docs/slices/0610_s61_ae_operator_control_execution_worker_closure.md",
        "worker_result_persistence_deferred",
        "persistence stays deferred",
        "S61 explicitly leaves worker-result persistence for S62.",
    ),
    TokenRequirement(
        "ae_worker_result_contract",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "worker_result_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION",
        "Worker result persistence must source from the validated AE result contract.",
    ),
    TokenRequirement(
        "ae_worker_result_contract",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "worker_result_builder",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_worker_result",
        "Worker result builders remain AE-owned.",
    ),
    TokenRequirement(
        "ae_worker_result_contract",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "worker_result_validator",
        "validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_result",
        "Worker result writes must validate the source contract before projection.",
    ),
    TokenRequirement(
        "ae_worker_result_contract",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "worker_result_summary",
        "summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_result",
        "Persistence must prefer the safe summary shape over the full payload.",
    ),
    TokenRequirement(
        "ae_worker_result_contract",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "worker_runner",
        "run_artifact_retention_scheduler_daemon_operator_control_execution_worker",
        "Worker result persistence must stay behind the AE worker runner/route boundary.",
    ),
    TokenRequirement(
        "ae_worker_full_payload_boundary",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "nested_worker_command_payload",
        '"operator_control_execution_worker_command": deepcopy(command),',
        "The full result contract embeds command payload and needs a persistence projection.",
    ),
    TokenRequirement(
        "ae_worker_full_payload_boundary",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "nested_transition_plan_payload",
        '"operator_control_execution_worker_transition_plan": deepcopy',
        "The full transition-plan payload must not be stored as a raw DB blob.",
    ),
    TokenRequirement(
        "ae_worker_full_payload_boundary",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "nested_supervisor_results_payload",
        '"supervisor_results": [deepcopy(item) for item in results],',
        "Supervisor result payloads must be summarized before persistence.",
    ),
    TokenRequirement(
        "ae_worker_safe_summary_source",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "safe_for_ag_projection",
        '"safe_for_ag_projection": True',
        "The persisted read model must remain safe for AG projection.",
    ),
    TokenRequirement(
        "ae_worker_safe_summary_source",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "worker_command_hash",
        '"operator_control_execution_worker_command_hash"',
        "Persist hashes for raw command correlation instead of raw command payloads.",
    ),
    TokenRequirement(
        "ae_worker_safe_summary_source",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "transition_plan_hash",
        '"operator_control_execution_worker_transition_plan_hash"',
        "Persist hashes for transition-plan correlation instead of raw plan payloads.",
    ),
    TokenRequirement(
        "ae_worker_safe_summary_source",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_result_statuses",
        '"supervisor_result_statuses"',
        "Persist bounded supervisor status summaries.",
    ),
    TokenRequirement(
        "ae_worker_safe_summary_source",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_result_ids",
        '"supervisor_result_ids"',
        "Persist supervisor result IDs for correlation, not full supervisor payloads.",
    ),
    TokenRequirement(
        "ae_worker_safe_summary_source",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "database_write_currently_false",
        '"database_write_performed": False',
        "S61 worker results currently do not write their own result rows.",
    ),
    TokenRequirement(
        "ae_worker_safe_summary_source",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "transition_persistence_currently_false",
        '"transition_persistence_performed": False',
        "S61 worker results do not persist transition rows from the worker call.",
    ),
    TokenRequirement(
        "ae_worker_route_boundary",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "worker_route",
        '"scheduler-daemon-operator-control-execution-workers"',
        "Worker result persistence must hang off the protected AE worker route.",
    ),
    TokenRequirement(
        "ae_worker_route_boundary",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "worker_route_callable",
        "run_artifact_retention_scheduler_daemon_operator_control_execution_worker_route",
        "Route wiring should remain explicit and testable.",
    ),
    TokenRequirement(
        "ae_worker_route_boundary",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "execution_state_lookup",
        "artifact_retention_daemon_operator_control_execution_store.get_execution_state",
        "Persisted worker results must stay scoped to a known execution state.",
    ),
    TokenRequirement(
        "ae_existing_execution_persistence",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "execution_states_table",
        "ae_daemon_operator_control_execution_states",
        "Worker result rows should reference the existing execution state boundary.",
    ),
    TokenRequirement(
        "ae_existing_execution_persistence",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "execution_transitions_table",
        "ae_daemon_operator_control_execution_transitions",
        "Worker result persistence must not replace state transition evidence.",
    ),
    TokenRequirement(
        "ag_worker_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_worker_projection_builder",
        "build_artifact_operation_retention_daemon_operator_control_execution_worker_projection",
        "AG may project persisted worker result read models but not own them.",
    ),
    TokenRequirement(
        "ag_worker_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_worker_projector",
        "_project_retention_scheduler_daemon_operator_control_execution_worker_result",
        "AG already has a safe projection shape for worker result payloads.",
    ),
    TokenRequirement(
        "ag_worker_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_worker_source_schema",
        '"source_operator_control_execution_worker_result_schema_version"',
        "AG projection records the AE source result schema without exposing raw payloads.",
    ),
    TokenRequirement(
        "ag_worker_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_worker_read_model",
        '"read_model": "ae_operator_control_execution_worker_result"',
        "AG treats worker result as an AE read model.",
    ),
    TokenRequirement(
        "ag_worker_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE worker result persistence.",
    ),
    TokenRequirement(
        "ag_worker_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_direct_job_enqueue_disallowed",
        '"ag_direct_job_enqueue_allowed": False',
        "AG must not enqueue AE worker result jobs directly.",
    ),
    TokenRequirement(
        "ag_worker_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "physical_delete_disabled",
        '"physical_delete_automation_enabled": False',
        "Worker result persistence must not enable physical deletion.",
    ),
    TokenRequirement(
        "postgres_smoke_baseline",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "ae_worker_smoke_opt_in",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE",
        "AE worker route test DB smoke remains the baseline before result persistence.",
    ),
    TokenRequirement(
        "postgres_smoke_baseline",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "ae_worker_smoke_live_db",
        '"live_db": True',
        "Result persistence smoke must also prove a live test DB path.",
    ),
    TokenRequirement(
        "postgres_smoke_baseline",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "ag_worker_smoke_opt_in",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE",
        "AG-to-AE worker route smoke remains the read-only projection baseline.",
    ),
    TokenRequirement(
        "s62_boundary_decision",
        "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
        "candidate_result_table",
        RESULT_TABLE,
        "Slice 0611 must document the short result table candidate.",
    ),
    TokenRequirement(
        "s62_boundary_decision",
        "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
        "persist_flag",
        "persist_worker_result=true",
        "Worker result writes must be explicit.",
    ),
    TokenRequirement(
        "s62_boundary_decision",
        "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
        "safe_summary_shape",
        "safe summary + hashes",
        "Persistence should store summaries and hashes, not raw nested payloads.",
    ),
    TokenRequirement(
        "s62_boundary_decision",
        "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
        "full_worker_command_forbidden",
        "full worker command payload",
        "The full worker command must be excluded from persistence.",
    ),
    TokenRequirement(
        "s62_boundary_decision",
        "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
        "full_transition_plan_forbidden",
        "transition-plan payload",
        "The full transition plan must be excluded from persistence.",
    ),
    TokenRequirement(
        "s62_boundary_decision",
        "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
        "full_supervisor_result_forbidden",
        "full supervisor result payload",
        "The full supervisor result must be excluded from persistence.",
    ),
    TokenRequirement(
        "quality_docs",
        "scripts/quality/run_quality_gate.sh",
        "s62_boundary_quality_gate_hook",
        "run_ae_operator_control_execution_worker_result_persistence_boundary_audit.py",
        "Slice 0611 audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_docs",
        "docs/README.md",
        "s62_doc_indexed",
        "0611_ae_worker_result_persistence_boundary_audit.md",
        "Slice 0611 must be indexed.",
    ),
    TokenRequirement(
        "quality_docs",
        "services/nex-ae-api/README.md",
        "ae_s62_readme_note",
        "Slice 0611 starts S62",
        "AE notes must record the worker result persistence boundary.",
    ),
    TokenRequirement(
        "quality_docs",
        "services/nex-ag/README.md",
        "ag_s62_readme_note",
        "Slice 0611 starts S62",
        "AG notes must record its read-only result projection boundary.",
    ),
)

PLANNED_SLICES = (
    ("worker_result_schema_migration", "Slice_0612", "AE worker result schema/migration foundation."),
    ("worker_result_repository_read_model", "Slice_0613", "AE worker result repository/read-model foundation."),
    ("worker_route_persisted_result_wiring", "Slice_0614", "AE worker route persisted-result wiring."),
    ("worker_result_postgres_smoke", "Slice_0615", "AE worker result PostgreSQL smoke evidence."),
    ("ag_worker_result_projection", "Slice_0616", "AG worker result read-model projection foundation."),
    ("ag_worker_result_route_dashboard", "Slice_0617", "AG worker result route/dashboard wiring."),
    ("ag_to_ae_worker_result_postgres_smoke", "Slice_0618", "AG-to-AE worker result PostgreSQL smoke evidence."),
    ("ag_worker_execution_diagnostics_rollup", "Slice_0619", "AG worker execution diagnostics rollup."),
    ("s62_closure", "Slice_0620", "S62 worker result persistence closure checkpoint."),
)


def run_ae_operator_control_execution_worker_result_persistence_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    environment = dict(os.environ if env is None else env)
    paths = _path_results(root_dir)
    tokens = _token_results(root_dir)
    token_groups = _grouped_token_status(tokens)
    table_names = _table_name_results()
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "table_name_lengths_safe": all(
            item["within_limit"] for item in table_names
        ),
        "s61_closed_baseline_present": token_groups.get(
            "s61_closed_baseline", False
        ),
        "ae_worker_result_contract_present": token_groups.get(
            "ae_worker_result_contract", False
        ),
        "ae_worker_full_payload_boundary_present": token_groups.get(
            "ae_worker_full_payload_boundary", False
        ),
        "ae_worker_safe_summary_source_present": token_groups.get(
            "ae_worker_safe_summary_source", False
        ),
        "ae_worker_route_boundary_present": token_groups.get(
            "ae_worker_route_boundary", False
        ),
        "ae_existing_execution_persistence_present": token_groups.get(
            "ae_existing_execution_persistence", False
        ),
        "ag_worker_projection_boundary_present": token_groups.get(
            "ag_worker_projection_boundary", False
        ),
        "postgres_smoke_baseline_present": token_groups.get(
            "postgres_smoke_baseline", False
        ),
        "s62_boundary_decision_present": token_groups.get(
            "s62_boundary_decision", False
        ),
        "quality_docs_present": token_groups.get("quality_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": "0611",
        "surface": S62_SURFACE,
        "result_persistence_boundary": _result_persistence_boundary(),
        "refactoring_checkpoint": _refactoring_checkpoint(),
        "table_name_results": table_names,
        "next_slices": [planned_slice for _, planned_slice, _ in PLANNED_SLICES],
        "planned_sequence": [
            {"name": name, "planned_slice": planned_slice, "purpose": purpose}
            for name, planned_slice, purpose in PLANNED_SLICES
        ],
        "protected_env": {
            key: bool(environment.get(key)) for key in PROTECTED_ENV_KEYS
        },
        "checks": checks,
        "paths": paths,
        "source_tokens": tokens,
    }
    if evidence["status"] != "PASS":
        evidence["failure_code"] = (
            "ae_operator_control_execution_worker_result_persistence_boundary_failed"
        )
        evidence["issues"] = _issues(paths, tokens, table_names)
    _assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _result_persistence_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ae-api",
        "persistence_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "boundary": RESULT_PERSISTENCE_BOUNDARY,
        "create_table_in_slice_0611": False,
        "first_schema_slice": NEXT_SLICE,
        "candidate_result_table": RESULT_TABLE,
        "candidate_result_table_length": len(RESULT_TABLE),
        "candidate_event_table": EVENT_TABLE,
        "candidate_event_table_length": len(EVENT_TABLE),
        "event_table_deferred": True,
        "max_table_name_length": MAX_TABLE_NAME_LENGTH,
        "storage_shape": "safe_summary_plus_hashes",
        "persist_flag": "persist_worker_result",
        "default_persist_worker_result": False,
        "explicit_opt_in_required": True,
        "test_profile_smoke_required": True,
        "postgres_smoke_required_before_ag_enablement": True,
        "store_columns": [
            "operator_control_execution_worker_result_id",
            "operator_control_execution_state_id",
            "operator_control_execution_request_id",
            "operator_control_execution_worker_command_id",
            "operator_control_execution_worker_plan_id",
            "operator_control_execution_worker_transition_plan_id",
            "scheduler_id",
            "action",
            "execution_mode",
            "worker_mode",
            "worker_status",
            "decision_reason",
            "observed_at",
            "supervisor_result_count",
            "created_at",
            "updated_at",
        ],
        "store_jsonb_columns": [
            "status_path",
            "supervisor_result_statuses",
            "supervisor_actions",
            "supervisor_result_ids",
            "guardrails",
            "metadata",
        ],
        "store_hash_columns": [
            "operator_control_execution_worker_command_hash",
            "operator_control_execution_worker_transition_plan_hash",
        ],
        "forbidden_persistence_payloads": [
            "full_worker_command_payload",
            "full_transition_plan_payload",
            "full_supervisor_result_payload",
            "database_url",
            "service_token",
            "provider_api_key",
            "local_storage_path",
            "artifact_payload",
            "execution_payload",
            "daemon_runtime_payload",
            "supervised_process_snapshot",
        ],
        "recommended_indexes": [
            "worker_result_id_unique",
            "execution_state_id",
            "worker_status_observed_at",
            "scheduler_action_observed_at",
        ],
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "worker_result_blob_storage_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "separate_persistence_projection_from_full_worker_result_contract": True,
        "keep_worker_result_builder_validation_in_daemon_module": True,
        "keep_route_validation_in_artifacts_module": True,
        "add_repository_before_route_write_toggle": True,
        "make_persist_worker_result_explicit": True,
        "default_route_remains_non_persistent": True,
        "reuse_existing_execution_state_identity": True,
        "reuse_existing_transition_evidence_without_replacing_it": True,
        "store_safe_summary_and_hashes_only": True,
        "do_not_store_full_worker_command_payload": True,
        "do_not_store_full_transition_plan_payload": True,
        "do_not_store_full_supervisor_result_payload": True,
        "keep_ag_read_only": True,
        "require_real_test_db_smoke_before_ag_result_routes": True,
    }


def _table_name_results() -> list[dict[str, Any]]:
    return [
        {
            "table_name": table_name,
            "length": len(table_name),
            "max_length": MAX_TABLE_NAME_LENGTH,
            "within_limit": len(table_name) <= MAX_TABLE_NAME_LENGTH,
        }
        for table_name in (RESULT_TABLE, EVENT_TABLE)
    ]


def _path_results(root_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for required in REQUIRED_PATHS:
        path = root_dir / required.relative_path
        results.append(
            {
                "name": required.name,
                "path": required.relative_path,
                "purpose": required.purpose,
                "present": path.is_file(),
            }
        )
    return results


def _token_results(root_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for requirement in REQUIRED_SOURCE_TOKENS:
        text = _read_text(root_dir / requirement.relative_path)
        results.append(
            {
                "group": requirement.group,
                "token_id": requirement.token_id,
                "path": requirement.relative_path,
                "purpose": requirement.purpose,
                "present": requirement.token in text,
            }
        )
    return results


def _issues(
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
    table_names: list[dict[str, Any]],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for path_result in paths:
        if not path_result["present"]:
            issues.append(
                {
                    "category": "path_missing",
                    "id": path_result["name"],
                    "path": path_result["path"],
                    "purpose": path_result["purpose"],
                }
            )
    for token_result in tokens:
        if not token_result["present"]:
            issues.append(
                {
                    "category": "source_token_missing",
                    "id": token_result["token_id"],
                    "path": token_result["path"],
                    "purpose": token_result["purpose"],
                }
            )
    for table_result in table_names:
        if not table_result["within_limit"]:
            issues.append(
                {
                    "category": "table_name_too_long",
                    "id": table_result["table_name"],
                    "path": "database/nex-ae-api/migrations",
                    "purpose": "Keep PostgreSQL relation names concise for operations.",
                }
            )
    return issues


def _grouped_token_status(tokens: list[dict[str, Any]] | None) -> dict[str, bool]:
    grouped: dict[str, list[bool]] = {}
    for token in tokens or []:
        grouped.setdefault(str(token.get("group")), []).append(
            token.get("present") is True
        )
    return {group: all(values) for group, values in grouped.items()}


def _present_count(items: list[dict[str, Any]] | None) -> int:
    return sum(1 for item in items or [] if item.get("present") is True)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and len(value) > 8 and value in serialized:
            raise ValueError(f"Sensitive value leaked in evidence: {key}")
    sensitive_patterns = (
        r"postgresql(?:\+psycopg)?://[^*\s]+:[^*\s]+@",
        r"Bearer\s+[A-Za-z0-9._~+/=@-]+",
        r"ed6@c496em",
        r"nuri1004",
        r"/data/nex-platform",
        r"idempotency[_-]?key\s*[:=]\s*[A-Za-z0-9._~+/=@-]+",
        r"full_worker_command_payload\s*[:=]\s*\{",
        r"full_transition_plan_payload\s*[:=]\s*\{",
        r"full_supervisor_result_payload\s*[:=]\s*\{",
        r"raw_(?:artifact|execution|daemon|supervised_process)_payload",
    )
    for pattern in sensitive_patterns:
        if re.search(pattern, serialized):
            raise ValueError("Sensitive value leaked in audit evidence")


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "PASS":
        paths = _present_count(evidence.get("paths"))  # type: ignore[arg-type]
        tokens = _present_count(evidence.get("source_tokens"))  # type: ignore[arg-type]
        table_names = evidence.get("table_name_results")
        table_count = _present_count(
            [
                {"present": item.get("within_limit") is True}
                for item in table_names
            ]
            if isinstance(table_names, list)
            else None
        )
        checks = evidence.get("checks", {})
        token_groups = sum(
            1
            for key, value in checks.items()
            if key.endswith("_present") and value is True
        )
        total_token_groups = sum(1 for key in checks if key.endswith("_present"))
        return (
            "ae_operator_control_execution_worker_result_persistence_boundary_audit=pass "
            f"paths={paths}/{len(REQUIRED_PATHS)} "
            f"tokens={tokens}/{len(REQUIRED_SOURCE_TOKENS)} "
            f"token_groups={token_groups}/{total_token_groups} "
            f"tables={table_count}/{len(CANDIDATE_TABLE_NAMES)} "
            f"boundary={RESULT_PERSISTENCE_BOUNDARY} "
            f"result_table={RESULT_TABLE} "
            f"next={NEXT_SLICE}"
        )
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), Mapping) else {}
    failing = ",".join(key for key, value in checks.items() if value is not True)
    return (
        "ae_operator_control_execution_worker_result_persistence_boundary_audit=fail "
        f"reason={evidence.get('failure_code')} "
        f"failing_checks={failing}"
    )


CANDIDATE_TABLE_NAMES = (RESULT_TABLE, EVENT_TABLE)


def write_audit_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the S62 AE operator-control execution worker result "
            "persistence boundary."
        )
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a concise summary line instead of JSON evidence.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path where JSON evidence should be written.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = (
        run_ae_operator_control_execution_worker_result_persistence_boundary_audit()
    )
    if args.output is not None:
        write_audit_evidence(args.output, evidence)
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
