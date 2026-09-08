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
SCHEMA_VERSION = "ae_operator_control_execution_worker_boundary_audit.v1"

S61_SURFACE = "S61 AE operator-control execution worker"
WORKER_BOUNDARY = "ae_owned_bounded_fake_dry_run_worker_test_profile_only"
DEFAULT_WORKER_MODE = "blocked_until_worker_contract"
FIRST_WORKER_MODE = "fake_dry_run_supervisor_persistent_dispatch_worker"
NEXT_SLICE = "Slice_0602"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_OPERATOR_CONTROL_EXECUTION_WORKER_SMOKE",
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_SMOKE",
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE",
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
        "AE daemon, supervisor, and operator-control execution module.",
    ),
    RequiredPath(
        "ae_artifacts_routes",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE artifact retention service route surface.",
    ),
    RequiredPath(
        "ag_artifact_operations",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG read-only operations projection surface.",
    ),
    RequiredPath(
        "ae_operator_control_execution_migration",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "AE operator-control execution state/transition persistence schema.",
    ),
    RequiredPath(
        "s60_boundary_audit",
        "scripts/smoke/run_ae_operator_control_execution_boundary_audit.py",
        "S60 execution boundary audit baseline.",
    ),
    RequiredPath(
        "s60_closure",
        "scripts/smoke/run_s60_ae_operator_control_execution_closure.py",
        "S60 execution track closure checkpoint.",
    ),
    RequiredPath(
        "s60_closure_doc",
        "docs/slices/0600_s60_ae_operator_control_execution_closure.md",
        "S60 closure implementation note.",
    ),
    RequiredPath(
        "s61_boundary_audit",
        "scripts/smoke/run_ae_operator_control_execution_worker_boundary_audit.py",
        "S61 worker boundary audit.",
    ),
    RequiredPath(
        "s61_boundary_test",
        "tests/test_ae_operator_control_execution_worker_boundary_audit.py",
        "S61 worker boundary regression tests.",
    ),
    RequiredPath(
        "s61_boundary_doc",
        "docs/slices/0601_ae_operator_control_execution_worker_boundary_audit.md",
        "Slice 0601 implementation note.",
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
        "s60_closed_baseline",
        "scripts/smoke/run_s60_ae_operator_control_execution_closure.py",
        "s60_closure_schema",
        "s60_ae_operator_control_execution_closure.v1",
        "S61 must start after the full S60 operator-control execution closure.",
    ),
    TokenRequirement(
        "s60_closed_baseline",
        "docs/slices/0600_s60_ae_operator_control_execution_closure.md",
        "s60_next_worker_track",
        "a more complete AE execution worker",
        "S60 explicitly points to an AE execution worker decision.",
    ),
    TokenRequirement(
        "ae_execution_contract_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "execution_request_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_REQUEST_SCHEMA_VERSION",
        "Worker input must consume the S60 execution request contract.",
    ),
    TokenRequirement(
        "ae_execution_contract_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "execution_state_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION",
        "Worker state must update the AE-owned execution state contract.",
    ),
    TokenRequirement(
        "ae_execution_contract_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "execution_transition_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION",
        "Worker progress must be represented as AE-owned transitions.",
    ),
    TokenRequirement(
        "ae_execution_state_machine",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "allowed_next_statuses",
        "_operator_control_execution_allowed_next_statuses",
        "Worker status changes must reuse the S60 state machine.",
    ),
    TokenRequirement(
        "ae_execution_state_machine",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "admitted_to_executing_or_blocked",
        '"ADMITTED": ["EXECUTING", "BLOCKED"]',
        "An admitted state may only move to executing or blocked.",
    ),
    TokenRequirement(
        "ae_execution_state_machine",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "executing_to_terminal",
        '"EXECUTING": ["SUCCEEDED", "FAILED"]',
        "An executing state may only move to succeeded or failed.",
    ),
    TokenRequirement(
        "ae_supervisor_worker_primitives",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_runner",
        "run_artifact_retention_scheduler_daemon_supervisor_command",
        "The first worker must call the existing supervisor runner.",
    ),
    TokenRequirement(
        "ae_supervisor_worker_primitives",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "fake_supervisor_adapter",
        "FakeArtifactRetentionSchedulerDaemonSupervisorAdapter",
        "The first worker mode remains fake dry-run and bounded.",
    ),
    TokenRequirement(
        "ae_supervisor_worker_primitives",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_dispatch_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_DISPATCH_SCHEMA_VERSION",
        "Worker evidence must align with supervisor dispatch evidence.",
    ),
    TokenRequirement(
        "ae_supervisor_worker_primitives",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_result_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION",
        "Worker evidence must capture sanitized supervisor results.",
    ),
    TokenRequirement(
        "ae_execution_persistence_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "execution_store",
        "SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore",
        "Worker state must persist through the AE-owned execution store.",
    ),
    TokenRequirement(
        "ae_execution_persistence_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "record_execution_state",
        "record_execution_state",
        "Worker state writes must use the existing execution state adapter.",
    ),
    TokenRequirement(
        "ae_execution_persistence_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "record_execution_state_transition",
        "record_execution_state_transition",
        "Worker progress writes must use the existing transition adapter.",
    ),
    TokenRequirement(
        "ae_execution_persistence_surface",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "execution_states_table",
        "ae_daemon_operator_control_execution_states",
        "Worker state evidence must be backed by the S60 state table.",
    ),
    TokenRequirement(
        "ae_execution_persistence_surface",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "execution_transitions_table",
        "ae_daemon_operator_control_execution_transitions",
        "Worker transition evidence must be backed by the S60 transition table.",
    ),
    TokenRequirement(
        "ae_route_boundary",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "execution_post_route",
        '"/api/v1/artifact-retention/scheduler-daemon-operator-control-executions"',
        "Worker admission starts from the protected AE execution route.",
    ),
    TokenRequirement(
        "ae_route_boundary",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "transition_post_route",
        '"scheduler-daemon-operator-control-execution-transitions"',
        "Worker progress must use the protected AE transition route.",
    ),
    TokenRequirement(
        "ae_route_boundary",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "persist_execution_state_flag",
        '"persist_execution_state"',
        "Persisted worker state remains explicitly opted in.",
    ),
    TokenRequirement(
        "ae_route_boundary",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "persist_transition_flag",
        '"persist_transition"',
        "Persisted worker transitions remain explicitly opted in.",
    ),
    TokenRequirement(
        "worker_side_effect_guardrails",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "existing_worker_guard",
        '"worker_execution_performed": False',
        "S60 still proves no worker side effect before S61 wiring.",
    ),
    TokenRequirement(
        "worker_side_effect_guardrails",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "fake_dispatch_mode_reserved",
        "fake_dry_run_supervisor_persistent_dispatch",
        "The first worker mode must stay fake dry-run supervisor dispatch.",
    ),
    TokenRequirement(
        "worker_side_effect_guardrails",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "test_profile_guard",
        "profile must be test.",
        "The first worker path remains test-profile-only.",
    ),
    TokenRequirement(
        "worker_side_effect_guardrails",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "physical_delete_disabled",
        '"physical_delete_automation_enabled": False',
        "Operator-control worker must not enable physical deletion.",
    ),
    TokenRequirement(
        "ag_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_execution_collection_projection",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION",
        "AG may project execution worker state, but only through AE read APIs.",
    ),
    TokenRequirement(
        "ag_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_direct_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE execution worker persistence.",
    ),
    TokenRequirement(
        "ag_projection_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_direct_process_control_disallowed",
        '"ag_direct_daemon_process_control_allowed": False',
        "AG must not control AE daemon processes directly.",
    ),
    TokenRequirement(
        "quality_docs",
        "scripts/quality/run_quality_gate.sh",
        "s60_closure_quality_gate_hook",
        "run_s60_ae_operator_control_execution_closure.py",
        "S60 closure must remain in the default quality gate.",
    ),
    TokenRequirement(
        "quality_docs",
        "scripts/quality/run_quality_gate.sh",
        "s61_audit_quality_gate_hook",
        "run_ae_operator_control_execution_worker_boundary_audit.py",
        "Slice 0601 audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_docs",
        "docs/README.md",
        "s61_doc_indexed",
        "0601_ae_operator_control_execution_worker_boundary_audit.md",
        "Slice 0601 must be indexed.",
    ),
    TokenRequirement(
        "quality_docs",
        "services/nex-ae-api/README.md",
        "ae_s61_readme_note",
        "Slice 0601 starts S61",
        "AE notes must record the worker boundary.",
    ),
    TokenRequirement(
        "quality_docs",
        "services/nex-ag/README.md",
        "ag_s61_readme_note",
        "Slice 0601 starts S61",
        "AG notes must record its read-only worker projection boundary.",
    ),
)

PLANNED_SLICES = (
    ("worker_plan_command_contract", "Slice_0602", "AE execution worker plan/command contract."),
    ("worker_state_transition_hardening", "Slice_0603", "Worker state transition hardening."),
    ("fake_dry_run_worker_adapter", "Slice_0604", "AE fake dry-run execution worker adapter."),
    ("worker_service_api_wiring", "Slice_0605", "Protected AE worker service/API wiring."),
    ("worker_postgres_smoke", "Slice_0606", "AE execution worker PostgreSQL smoke evidence."),
    ("ag_worker_projection", "Slice_0607", "AG worker execution projection foundation."),
    ("ag_worker_route_dashboard", "Slice_0608", "AG worker route/dashboard wiring."),
    ("ag_worker_postgres_smoke", "Slice_0609", "AG-to-AE worker PostgreSQL smoke evidence."),
    ("s61_closure", "Slice_0610", "S61 execution worker closure checkpoint."),
)


def run_ae_operator_control_execution_worker_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    environment = dict(os.environ if env is None else env)
    paths = _path_results(root_dir)
    tokens = _token_results(root_dir)
    grouped = _grouped_token_status(tokens)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "s60_closed_baseline_present": grouped.get("s60_closed_baseline", False),
        "ae_execution_contract_surface_present": grouped.get(
            "ae_execution_contract_surface",
            False,
        ),
        "ae_execution_state_machine_present": grouped.get(
            "ae_execution_state_machine",
            False,
        ),
        "ae_supervisor_worker_primitives_present": grouped.get(
            "ae_supervisor_worker_primitives",
            False,
        ),
        "ae_execution_persistence_surface_present": grouped.get(
            "ae_execution_persistence_surface",
            False,
        ),
        "ae_route_boundary_present": grouped.get("ae_route_boundary", False),
        "worker_side_effect_guardrails_present": grouped.get(
            "worker_side_effect_guardrails",
            False,
        ),
        "ag_projection_boundary_present": grouped.get(
            "ag_projection_boundary",
            False,
        ),
        "quality_docs_present": grouped.get("quality_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": "0601",
        "surface": S61_SURFACE,
        "worker_boundary": _worker_boundary(),
        "refactoring_checkpoint": _refactoring_checkpoint(),
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
        evidence["failure_code"] = "ae_operator_control_execution_worker_boundary_failed"
        evidence["issues"] = _issues(paths, tokens)
    _assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _worker_boundary() -> dict[str, Any]:
    return {
        "artifact_system_of_record": "nex-ae-api",
        "operator_control_execution_owner": "nex-ae-api",
        "worker_execution_owner": "nex-ae-api",
        "worker_state_persistence_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "operator_dispatch_owner": "nex-ag",
        "worker_boundary": WORKER_BOUNDARY,
        "default_worker_mode": DEFAULT_WORKER_MODE,
        "first_worker_mode": FIRST_WORKER_MODE,
        "source_execution_state_required": True,
        "source_execution_state_status_required": "ADMITTED",
        "uses_s60_execution_request_contract": True,
        "uses_s60_execution_state_machine": True,
        "uses_existing_supervisor_runner": True,
        "uses_fake_supervisor_adapter_first": True,
        "persists_execution_state": True,
        "persists_execution_transition": True,
        "persists_supervisor_result_metadata": True,
        "restart_semantics": "stop_then_start_with_distinct_persisted_results",
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "operator_approval_required_for_start_restart": True,
        "test_profile_required": True,
        "explicit_opt_in_required_for_start_restart": True,
        "bounded_max_cycles_required": True,
        "admitted_to_executing_transition_required": True,
        "executing_to_terminal_transition_required": True,
        "postgres_smoke_required_before_ag_enablement": True,
        "real_subprocess_start_stop_enabled": False,
        "production_continuous_start_enabled": False,
        "job_queue_enqueue_allowed_for_operator_control": False,
        "ag_direct_worker_execution_allowed": False,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "separate_worker_contract_from_route_handler": True,
        "keep_worker_contracts_in_daemon_module": True,
        "keep_route_validation_in_artifacts_module": True,
        "reuse_s60_execution_request_state_transition_contracts": True,
        "reuse_supervisor_command_result_contract": True,
        "reuse_fake_supervisor_adapter_for_first_worker": True,
        "reuse_operator_control_execution_store": True,
        "do_not_reuse_scheduled_purge_worker_for_process_control": True,
        "avoid_new_long_running_jobqueue_worker": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "keep_ag_as_read_only_worker_projection": True,
        "metadata_only_safe_projection": True,
    }


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
        r"raw_(?:artifact|execution|daemon|supervised_process)_payload",
    )
    for pattern in sensitive_patterns:
        if re.search(pattern, serialized):
            raise ValueError("Sensitive value leaked in audit evidence")


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "PASS":
        paths = _present_count(evidence.get("paths"))  # type: ignore[arg-type]
        tokens = _present_count(evidence.get("source_tokens"))  # type: ignore[arg-type]
        token_groups = sum(evidence.get("checks", {}).values()) - 1
        total_token_groups = len(evidence.get("checks", {})) - 1
        return (
            "ae_operator_control_execution_worker_boundary_audit=pass "
            f"paths={paths}/{len(REQUIRED_PATHS)} "
            f"tokens={tokens}/{len(REQUIRED_SOURCE_TOKENS)} "
            f"token_groups={token_groups}/{total_token_groups} "
            f"boundary={WORKER_BOUNDARY} "
            f"mode={DEFAULT_WORKER_MODE} "
            f"first_mode={FIRST_WORKER_MODE} "
            f"next={NEXT_SLICE}"
        )
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), Mapping) else {}
    failing = ",".join(key for key, value in checks.items() if value is not True)
    return (
        "ae_operator_control_execution_worker_boundary_audit=fail "
        f"reason={evidence.get('failure_code')} "
        f"failing_checks={failing}"
    )


def write_audit_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the S61 AE operator-control execution worker boundary."
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
    evidence = run_ae_operator_control_execution_worker_boundary_audit()
    if args.output is not None:
        write_audit_evidence(args.output, evidence)
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
