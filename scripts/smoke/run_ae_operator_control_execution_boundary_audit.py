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
SCHEMA_VERSION = "ae_operator_control_execution_boundary_audit.v1"

S60_SURFACE = "S60 AE supervised scheduler daemon operator-control execution"
EXECUTION_BOUNDARY = "ae_owned_supervisor_execution_test_profile_only"
DEFAULT_EXECUTION_MODE = "blocked_until_execution_contract"
FIRST_EXECUTION_MODE = "fake_dry_run_supervisor_persistent_dispatch"
NEXT_SLICE = "Slice_0592"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_OPERATOR_CONTROL_EXECUTION_SMOKE",
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_SMOKE",
    "NEX_AE_SCHEDULER_DAEMON_ENABLE_SUPERVISED_PROCESS",
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
        "AE daemon supervisor, supervised-process, and operator-control module.",
    ),
    RequiredPath(
        "ae_artifacts_routes",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE artifact retention control API routes.",
    ),
    RequiredPath(
        "ag_artifact_operations",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG read-only operator-facing projection and dispatcher surface.",
    ),
    RequiredPath(
        "s59_closure",
        "scripts/smoke/run_s59_ae_supervised_process_operator_control_closure.py",
        "Closed S59 preview-only operator-control baseline.",
    ),
    RequiredPath(
        "s59_closure_doc",
        "docs/slices/0590_s59_ae_supervised_process_operator_control_closure.md",
        "S59 closure note and next-slice guidance.",
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
    RequiredPath(
        "s60_boundary_audit",
        "scripts/smoke/run_ae_operator_control_execution_boundary_audit.py",
        "S60 operator-control execution boundary audit.",
    ),
    RequiredPath(
        "s60_boundary_test",
        "tests/test_ae_operator_control_execution_boundary_audit.py",
        "S60 boundary regression tests.",
    ),
    RequiredPath(
        "s60_boundary_doc",
        "docs/slices/0591_ae_operator_control_execution_boundary_audit.md",
        "Slice 0591 implementation note.",
    ),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s59_closed_baseline",
        "scripts/smoke/run_s59_ae_supervised_process_operator_control_closure.py",
        "s59_closure_schema",
        "s59_ae_supervised_process_operator_control_closure.v1",
        "S60 must start after the full S59 operator-control closure.",
    ),
    TokenRequirement(
        "s59_closed_baseline",
        "docs/slices/0590_s59_ae_supervised_process_operator_control_closure.md",
        "s59_next_execution_track",
        "operator execution track",
        "S59 explicitly points to protected operator execution work.",
    ),
    TokenRequirement(
        "ae_preview_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "operator_control_facade_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION",
        "Execution must consume the validated AE operator-control facade.",
    ),
    TokenRequirement(
        "ae_preview_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "operator_control_command_preview_builder",
        "build_artifact_retention_scheduler_daemon_operator_control_command_preview",
        "Execution must reuse AE-generated supervisor command previews.",
    ),
    TokenRequirement(
        "ae_preview_surface",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "operator_control_preview_route",
        '"/api/v1/artifact-retention/scheduler-daemon-operator-control-preview"',
        "The existing preview route remains the admission/preview primitive.",
    ),
    TokenRequirement(
        "ae_supervisor_execution_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_command_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_COMMAND_SCHEMA_VERSION",
        "Execution must dispatch AE supervisor command contracts.",
    ),
    TokenRequirement(
        "ae_supervisor_execution_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_result_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_RESULT_SCHEMA_VERSION",
        "Execution must capture sanitized AE supervisor results.",
    ),
    TokenRequirement(
        "ae_supervisor_execution_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_dispatch_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISOR_DISPATCH_SCHEMA_VERSION",
        "Execution persistence must stay aligned with supervisor dispatch evidence.",
    ),
    TokenRequirement(
        "ae_supervisor_execution_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_runner",
        "run_artifact_retention_scheduler_daemon_supervisor_command",
        "Execution must call the existing supervisor runner instead of duplicating it.",
    ),
    TokenRequirement(
        "ae_supervisor_execution_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "fake_supervisor_adapter",
        "FakeArtifactRetentionSchedulerDaemonSupervisorAdapter",
        "The first execution mode remains fake dry-run and bounded.",
    ),
    TokenRequirement(
        "ae_supervisor_persistence_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervisor_store",
        "SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore",
        "Execution results must be persisted through the AE-owned supervisor store.",
    ),
    TokenRequirement(
        "ae_supervisor_persistence_surface",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "supervisor_control_route",
        '"/api/v1/artifact-retention/scheduler-daemon-supervisor-controls"',
        "The current internal control route is the execution primitive.",
    ),
    TokenRequirement(
        "ae_supervised_process_surface",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "supervised_process_schema",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_SCHEMA_VERSION",
        "Execution must remain compatible with supervised-process evidence.",
    ),
    TokenRequirement(
        "ae_execution_guardrails",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "test_profile_required",
        "profile must be test.",
        "The first execution mode is test-profile-only.",
    ),
    TokenRequirement(
        "ae_execution_guardrails",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "explicit_opt_in_required",
        '"execution_requires_explicit_opt_in": True',
        "Start execution requires explicit opt-in.",
    ),
    TokenRequirement(
        "ae_execution_guardrails",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "process_side_effect_guard",
        "side effect is invalid",
        "Supervisor result validation blocks unexpected process side effects.",
    ),
    TokenRequirement(
        "ae_execution_guardrails",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "physical_delete_disabled",
        '"physical_delete_automation_enabled": False',
        "Operator-control execution cannot enable physical artifact deletion.",
    ),
    TokenRequirement(
        "ag_execution_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_direct_process_control_disallowed",
        '"ag_direct_daemon_process_control_allowed": False',
        "AG must not directly control AE daemon processes.",
    ),
    TokenRequirement(
        "ag_execution_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_direct_database_write_disallowed",
        '"ag_direct_database_write_allowed": False',
        "AG must not write AE persistence.",
    ),
    TokenRequirement(
        "ag_execution_boundary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "ag_operator_control_projection",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION",
        "AG must keep operator-control evidence projected and read-only.",
    ),
    TokenRequirement(
        "quality_docs",
        "scripts/quality/run_quality_gate.sh",
        "s59_closure_quality_gate_hook",
        "run_s59_ae_supervised_process_operator_control_closure.py",
        "S59 closure must remain in the default quality gate.",
    ),
    TokenRequirement(
        "quality_docs",
        "scripts/quality/run_quality_gate.sh",
        "s60_audit_quality_gate_hook",
        "run_ae_operator_control_execution_boundary_audit.py",
        "Slice 0591 audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "quality_docs",
        "docs/README.md",
        "s60_doc_indexed",
        "0591_ae_operator_control_execution_boundary_audit.md",
        "Slice 0591 must be indexed.",
    ),
    TokenRequirement(
        "quality_docs",
        "services/nex-ae-api/README.md",
        "ae_s60_readme_note",
        "Slice 0591 starts S60",
        "AE notes must record the execution boundary.",
    ),
    TokenRequirement(
        "quality_docs",
        "services/nex-ag/README.md",
        "ag_s60_readme_note",
        "Slice 0591 starts S60",
        "AG notes must record its dispatcher-only boundary.",
    ),
)

PLANNED_SLICES = (
    ("execution_contract_schema", "Slice_0592", "AE execution request/result contract."),
    ("execution_state_machine", "Slice_0593", "Execution status and idempotency state machine."),
    ("supervisor_adapter_wiring", "Slice_0594", "Protected supervisor adapter dispatch wiring."),
    ("execution_persistence_api", "Slice_0595", "AE execution persistence and read-model API."),
    ("ae_postgres_smoke", "Slice_0596", "AE execution PostgreSQL smoke evidence."),
    ("ag_dispatcher_projection", "Slice_0597", "AG dispatcher projection over AE execution."),
    ("ag_dashboard_execution_history", "Slice_0598", "AG dashboard execution progress/history."),
    ("ag_to_ae_postgres_smoke", "Slice_0599", "AG-to-AE execution PostgreSQL smoke evidence."),
    ("s60_closure", "Slice_0600", "S60 operator-control execution closure."),
)


def run_ae_operator_control_execution_boundary_audit(
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
        "s59_closed_baseline_present": grouped.get("s59_closed_baseline", False),
        "ae_preview_surface_present": grouped.get("ae_preview_surface", False),
        "ae_supervisor_execution_surface_present": grouped.get(
            "ae_supervisor_execution_surface",
            False,
        ),
        "ae_supervisor_persistence_surface_present": grouped.get(
            "ae_supervisor_persistence_surface",
            False,
        ),
        "ae_supervised_process_surface_present": grouped.get(
            "ae_supervised_process_surface",
            False,
        ),
        "ae_execution_guardrails_present": grouped.get("ae_execution_guardrails", False),
        "ag_execution_boundary_present": grouped.get("ag_execution_boundary", False),
        "quality_docs_present": grouped.get("quality_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": "0591",
        "surface": S60_SURFACE,
        "execution_boundary": _execution_boundary(),
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
        evidence["failure_code"] = "ae_operator_control_execution_boundary_failed"
        evidence["issues"] = _issues(paths, tokens)
    _assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _execution_boundary() -> dict[str, Any]:
    return {
        "artifact_system_of_record": "nex-ae-api",
        "daemon_process_owner": "nex-ae-api",
        "supervisor_execution_owner": "nex-ae-api",
        "operator_projection_owner": "nex-ag",
        "operator_dispatch_owner": "nex-ag",
        "execution_boundary": EXECUTION_BOUNDARY,
        "default_execution_mode": DEFAULT_EXECUTION_MODE,
        "first_execution_mode": FIRST_EXECUTION_MODE,
        "source_preview_required": True,
        "supported_operator_actions": [
            "status_probe",
            "start_daemon",
            "stop_daemon",
            "restart_daemon",
        ],
        "restart_semantics": "stop_then_start_with_distinct_persisted_results",
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "operator_approval_required_for_start_restart": True,
        "test_profile_required": True,
        "explicit_opt_in_required_for_start_restart": True,
        "bounded_max_cycles_required": True,
        "supervisor_adapter_required_for_mutation": True,
        "supervisor_result_persistence_required": True,
        "supervised_process_snapshot_compatible": True,
        "postgres_smoke_required_before_ag_enablement": True,
        "production_continuous_start_enabled": False,
        "ag_direct_process_control_allowed": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "reuse_s59_policy_request_admission_preview": True,
        "keep_execution_contracts_in_daemon_module": True,
        "keep_route_validation_in_artifacts_module": True,
        "reuse_supervisor_command_result_contract": True,
        "reuse_supervisor_store_for_execution_evidence": True,
        "reuse_supervised_process_read_model_for_status": True,
        "avoid_new_long_running_jobqueue_worker": True,
        "keep_jobqueue_for_finite_retention_work": True,
        "keep_ag_as_dispatcher_projection_only": True,
        "metadata_only_operator_execution_evidence": True,
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
    )
    for pattern in sensitive_patterns:
        if re.search(pattern, serialized):
            raise ValueError("Sensitive value leaked in audit evidence")


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "PASS":
        paths = _present_count(evidence.get("paths"))  # type: ignore[arg-type]
        tokens = _present_count(evidence.get("source_tokens"))  # type: ignore[arg-type]
        return (
            "ae_operator_control_execution_boundary_audit=pass "
            f"paths={paths}/{len(REQUIRED_PATHS)} "
            f"token_groups={sum(evidence.get('checks', {}).values()) - 1}/"
            f"{len(evidence.get('checks', {})) - 1} "
            f"boundary={EXECUTION_BOUNDARY} "
            f"mode={DEFAULT_EXECUTION_MODE} "
            f"first_mode={FIRST_EXECUTION_MODE} "
            f"next={NEXT_SLICE}"
        )
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), Mapping) else {}
    failing = ",".join(key for key, value in checks.items() if value is not True)
    return (
        "ae_operator_control_execution_boundary_audit=fail "
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
        description="Audit the S60 AE operator-control execution boundary."
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
    evidence = run_ae_operator_control_execution_boundary_audit()
    if args.output is not None:
        write_audit_evidence(args.output, evidence)
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
