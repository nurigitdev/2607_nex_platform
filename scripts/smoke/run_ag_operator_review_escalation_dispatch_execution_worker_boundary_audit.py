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
    "ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.v1"
)

SLICE_ID = "0712"
S72_SURFACE = "AG operator review escalation dispatch execution worker"
DISPATCH_EXECUTION_WORKER_BOUNDARY = (
    "ag_owned_operator_review_escalation_dispatch_execution_worker"
)
CASE_TABLE = "ag_op_cases"
ESCALATION_TABLE = "ag_op_escalations"
DISPATCH_TABLE = "ag_op_esc_dispatches"
OPERATIONAL_EVENT_TABLE = "service_operational_events"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0713"

PROTECTED_ENV_KEYS = (
    "NEX_AG_DATABASE_URL",
    "NEX_AG_TEST_DATABASE_URL",
    "NEX_AG_DISPATCH_EXECUTION_WORKER_MODE",
    "NEX_AG_DISPATCH_EXECUTION_WORKER_PROFILE",
    "NEX_AG_DISPATCH_EXECUTION_BATCH_LIMIT",
    "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE",
    "NEX_AG_DISPATCH_EXECUTION_PROVIDER_PROFILE",
    "NEX_AG_NOTIFICATION_WEBHOOK_URL",
    "NEX_AG_NOTIFICATION_SERVICE_TOKEN",
    "NEX_AG_EXTERNAL_INCIDENT_BASE_URL",
    "NEX_AG_EXTERNAL_INCIDENT_TOKEN",
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
        "srs_assembly",
        "docs/29_nex_platform_mvp_srs_v0_1_assembly.md",
        "Canonical SRS source for AG governance and operations.",
    ),
    RequiredPath(
        "service_partition",
        "docs/30_service_specific_requirement_partition.md",
        "Service ownership split for AG-owned execution state.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Protected regression and PostgreSQL smoke strategy.",
    ),
    RequiredPath(
        "s71_boundary_doc",
        "docs/slices/0701_ag_operator_review_escalation_outbound_dispatch_boundary_audit.md",
        "S71 outbound dispatch boundary baseline.",
    ),
    RequiredPath(
        "s71_postgres_smoke_doc",
        "docs/slices/0710_ag_operator_review_escalation_dispatch_postgresql_smoke.md",
        "S71 real nex_ag_test PostgreSQL smoke evidence.",
    ),
    RequiredPath(
        "s71_closure_doc",
        "docs/slices/0711_s71_operator_review_escalation_dispatch_closure.md",
        "Closed dispatch outbox foundation before S72 worker execution.",
    ),
    RequiredPath(
        "s71_closure_script",
        "scripts/smoke/run_s71_operator_review_escalation_dispatch_closure.py",
        "Closed S71 evidence checkpoint.",
    ),
    RequiredPath(
        "dispatch_privacy_regression",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_privacy_regression.py",
        "S71 route and evidence redaction baseline.",
    ),
    RequiredPath(
        "dispatch_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_postgres_smoke.py",
        "S71 protected PostgreSQL smoke baseline.",
    ),
    RequiredPath(
        "ag_operator_review_cases",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "AG-owned operator review case, escalation, and dispatch runtime.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG dashboard and issue-candidate projection surface.",
    ),
    RequiredPath(
        "dispatch_migration",
        "database/nex-ag/migrations/0702_ag_operator_review_escalation_dispatch.sql",
        "Existing AG-owned dispatch outbox table baseline.",
    ),
    RequiredPath(
        "event_migration",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "Existing AG-owned operational event table baseline.",
    ),
    RequiredPath(
        "operator_review_case_schema",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "Persisted dispatch plan/list/detail/action contract baseline.",
    ),
    RequiredPath(
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "Operations dashboard contract baseline.",
    ),
    RequiredPath(
        "openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AG OpenAPI contract surface.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s71_closed_baseline",
        "scripts/smoke/run_s71_operator_review_escalation_dispatch_closure.py",
        "s71_closure_schema",
        "s71_operator_review_escalation_dispatch_closure.v1",
        "S72 starts only after S71 dispatch foundation is closed.",
    ),
    TokenRequirement(
        "s71_closed_baseline",
        "docs/slices/0711_s71_operator_review_escalation_dispatch_closure.md",
        "s72_start_note",
        "S72 can now start",
        "S71 closure explicitly hands off to execution-worker work.",
    ),
    TokenRequirement(
        "s71_closed_baseline",
        "scripts/smoke/run_s71_operator_review_escalation_dispatch_closure.py",
        "s71_provider_deferred",
        '"provider_execution": "mock_first_only"',
        "S72 inherits the mock-first outbound provider baseline.",
    ),
    TokenRequirement(
        "dispatch_outbox_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_table_constant",
        'AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_TABLE = "ag_op_esc_dispatches"',
        "Execution worker reads the existing AG-owned dispatch outbox.",
    ),
    TokenRequirement(
        "dispatch_outbox_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_planner",
        "def build_operator_review_escalation_dispatch_plan",
        "Worker execution remains downstream of the dispatch planner.",
    ),
    TokenRequirement(
        "dispatch_outbox_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_state_machine",
        "def apply_operator_review_escalation_dispatch_action",
        "Worker execution must reuse the existing dispatch state machine.",
    ),
    TokenRequirement(
        "dispatch_outbox_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_recorded_event",
        "OPERATOR_REVIEW_ESCALATION_DISPATCH_RECORDED_EVENT_TYPE",
        "Execution evidence should correlate to dispatch creation events.",
    ),
    TokenRequirement(
        "dispatch_outbox_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_action_recorded_event",
        "OPERATOR_REVIEW_ESCALATION_DISPATCH_ACTION_RECORDED_EVENT_TYPE",
        "Execution evidence should correlate to dispatch action events.",
    ),
    TokenRequirement(
        "dispatch_route_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_create_route",
        "/admin/v1/operator-review/escalations/{escalation_id}/dispatches",
        "Worker input is created through the protected dispatch create route.",
    ),
    TokenRequirement(
        "dispatch_route_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_list_route",
        "/admin/v1/operator-review/dispatches",
        "Operators can inspect dispatch rows before worker execution.",
    ),
    TokenRequirement(
        "dispatch_route_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_action_route",
        "/admin/v1/operator-review/dispatches/{dispatch_id}/actions",
        "Worker execution should mutate dispatch state through the same boundary.",
    ),
    TokenRequirement(
        "dispatch_redaction_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "raw_provider_payload_not_stored",
        '"raw_provider_payload_stored": False',
        "Worker results must not persist raw provider payloads.",
    ),
    TokenRequirement(
        "dispatch_redaction_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "raw_notification_payload_not_stored",
        '"raw_notification_payload_stored": False',
        "Worker results must not persist raw notification payloads.",
    ),
    TokenRequirement(
        "dispatch_redaction_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "raw_external_incident_payload_not_stored",
        '"raw_external_incident_payload_stored": False',
        "Worker results must not persist raw external incident payloads.",
    ),
    TokenRequirement(
        "dispatch_redaction_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "live_notification_delivery_false",
        '"live_notification_delivery": False',
        "S72 starts with live notification delivery disabled.",
    ),
    TokenRequirement(
        "dispatch_redaction_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "live_external_incident_sync_false",
        '"live_external_incident_sync": False',
        "S72 starts with live external incident sync disabled.",
    ),
    TokenRequirement(
        "operations_visibility_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_dispatch_section",
        "operator_review_escalation_dispatches",
        "Worker status should be visible through the existing dispatch section first.",
    ),
    TokenRequirement(
        "operations_visibility_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "dispatch_attention_rule",
        "operator_review_escalation_dispatch_attention_required.v1",
        "Worker failures should feed the existing attention signal first.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0702_ag_operator_review_escalation_dispatch.sql",
        "dispatch_table",
        "CREATE TABLE IF NOT EXISTS ag_op_esc_dispatches",
        "Worker execution reads and updates the existing short dispatch table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_table",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
        "Worker attempt history should be observable through operational events.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "dispatch_action_mutation_response",
        "dispatch_action_mutation_response",
        "Worker state changes should preserve the dispatch action mutation shape.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "raw_provider_payload_contract_flag",
        "raw_provider_payload_included",
        "Dispatch contracts expose redaction flags instead of raw provider payloads.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_dispatch_section_contract",
        "ag_operator_review_escalation_dispatch_dashboard_section.v1",
        "Operations projection already exposes safe dispatch status.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "dispatch_action_openapi_route",
        "/admin/v1/operator-review/dispatches/{dispatch_id}/actions:",
        "Worker execution should route state changes through the protected action API.",
    ),
    TokenRequirement(
        "s72_boundary_docs",
        "docs/README.md",
        "doc_index_0712",
        "0712_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.md",
        "Slice 0712 must be indexed.",
    ),
    TokenRequirement(
        "s72_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s72_readme_note",
        "Slice 0712 starts S72",
        "AG README must record the execution-worker boundary.",
    ),
    TokenRequirement(
        "s72_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s72_boundary_quality_gate_hook",
        "run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit.py",
        "Slice 0712 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    (
        "execution_provider_result_contract",
        "Slice_0713",
        "Freeze mock-first provider profiles and safe execution-result shape.",
    ),
    (
        "execution_provider_adapter_foundation",
        "Slice_0714",
        "Add bounded mock provider adapter without live outbound network delivery.",
    ),
    (
        "execution_transition_planner",
        "Slice_0715",
        "Plan dispatch row eligibility and START/SUCCEED/FAIL/RETRY transitions.",
    ),
    (
        "execution_worker_run_once_batch",
        "Slice_0716",
        "Run a bounded batch over eligible dispatch rows using explicit opt-in.",
    ),
    (
        "execution_result_persistence_hardening",
        "Slice_0717",
        "Persist safe result hashes, statuses, counters, and operational events only.",
    ),
    (
        "execution_operations_dashboard_integration",
        "Slice_0718",
        "Expose execution lag/failure counters through existing AG operations surfaces.",
    ),
    (
        "execution_postgres_smoke",
        "Slice_0719",
        "Prove run-once worker behavior against real nex_ag_test PostgreSQL.",
    ),
    (
        "s72_execution_closure",
        "Slice_0720",
        "Close S72 dispatch execution after protected PostgreSQL evidence.",
    ),
)

TABLE_NAMES_UNDER_REVIEW = (
    CASE_TABLE,
    ESCALATION_TABLE,
    DISPATCH_TABLE,
    OPERATIONAL_EVENT_TABLE,
)


def run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit(
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
        "table_name_lengths_safe": all(item["within_limit"] for item in table_names),
        "s71_closed_baseline_present": token_groups.get("s71_closed_baseline", False),
        "dispatch_outbox_runtime_present": token_groups.get(
            "dispatch_outbox_runtime", False
        ),
        "dispatch_route_runtime_present": token_groups.get(
            "dispatch_route_runtime", False
        ),
        "dispatch_redaction_baseline_present": token_groups.get(
            "dispatch_redaction_baseline", False
        ),
        "operations_visibility_baseline_present": token_groups.get(
            "operations_visibility_baseline", False
        ),
        "persistence_baseline_present": token_groups.get("persistence_baseline", False),
        "contracts_baseline_present": token_groups.get("contracts_baseline", False),
        "s72_boundary_docs_present": token_groups.get("s72_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S72_SURFACE,
        "execution_worker_boundary": _execution_worker_boundary(),
        "refactoring_checkpoint": _refactoring_checkpoint(),
        "table_name_results": table_names,
        "next_slices": [planned_slice for _, planned_slice, _ in PLANNED_SLICES],
        "planned_sequence": [
            {"name": name, "planned_slice": planned_slice, "purpose": purpose}
            for name, planned_slice, purpose in PLANNED_SLICES
        ],
        "protected_env": {key: bool(environment.get(key)) for key in PROTECTED_ENV_KEYS},
        "checks": checks,
        "paths": paths,
        "source_tokens": tokens,
    }
    if evidence["status"] != "PASS":
        evidence["failure_code"] = (
            "ag_operator_review_escalation_dispatch_execution_worker_boundary_failed"
        )
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _execution_worker_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "worker_owner": "nex-ag",
        "boundary": DISPATCH_EXECUTION_WORKER_BOUNDARY,
        "create_table_in_slice_0712": False,
        "first_worker_implementation_slice": NEXT_SLICE,
        "source_dispatch_table": DISPATCH_TABLE,
        "event_source_table": OPERATIONAL_EVENT_TABLE,
        "source_tables": [
            {"table_name": CASE_TABLE, "role": "case_state_reference"},
            {"table_name": ESCALATION_TABLE, "role": "escalation_state_reference"},
            {"table_name": DISPATCH_TABLE, "role": "dispatch_outbox_source_of_record"},
            {
                "table_name": OPERATIONAL_EVENT_TABLE,
                "role": "safe_execution_history_source",
            },
        ],
        "planned_owned_tables": [],
        "result_storage": "safe_result_hashes_statuses_attempt_counts_only",
        "execution_history": "service_operational_events_first",
        "worker_mode_in_s72": "bounded_mock_first_only",
        "continuous_daemon_in_0712": False,
        "run_once_batch_required_before_daemon": True,
        "explicit_operator_or_smoke_opt_in_required": True,
        "batch_limit_required": True,
        "provider_execution": "mock_first_only",
        "dispatch_provider_adapter": "mock_profile_only_until_explicit_live_slice",
        "live_provider_execution_in_s72": False,
        "outbound_network_delivery_in_s72": False,
        "ag_may_send_live_notifications_in_s72": False,
        "ag_may_sync_live_external_incidents_in_s72": False,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
        "eligible_source_statuses": ["PENDING", "RETRY_WAIT", "FAILED"],
        "allowed_worker_actions": ["START", "SUCCEED", "FAIL", "RETRY", "CANCEL"],
        "expected_worker_result_shape": [
            "dispatch_id",
            "execution_status",
            "attempt_count",
            "provider_profile",
            "provider_result_ref",
            "provider_result_hash",
            "safe_result_preview",
            "next_attempt_at",
            "redaction_flags",
            "operational_event_id",
        ],
        "forbidden_worker_result_payloads": [
            "raw_case_comment",
            "raw_action_comment",
            "raw_operator_note_text",
            "raw_evidence_body",
            "raw_prompt_text",
            "raw_generation_output_text",
            "raw_source_document_text",
            "raw_provider_payload",
            "raw_notification_payload",
            "raw_external_incident_payload",
            "provider_api_key",
            "notification_secret",
            "external_incident_token",
            "database_url",
            "service_token",
            "local_storage_path",
            "artifact_binary_payload",
            "raw_idempotency_key",
        ],
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "reuse_s71_dispatch_outbox_as_worker_input": True,
        "separate_worker_planning_from_live_provider_delivery": True,
        "start_with_bounded_run_once_batches_before_daemon_loop": True,
        "require_explicit_opt_in_for_execution_smoke": True,
        "reuse_dispatch_state_machine_for_worker_transitions": True,
        "persist_only_safe_result_hashes_statuses_and_counters": True,
        "keep_live_notification_delivery_out_of_s72_start": True,
        "keep_live_external_incident_sync_out_of_s72_start": True,
        "keep_raw_provider_payloads_out_of_db_and_evidence": True,
        "record_safe_worker_history_in_operational_events": True,
        "avoid_new_tables_until_result_persistence_slice": True,
        "keep_table_names_short": True,
    }


def _table_name_results() -> list[dict[str, Any]]:
    return [
        {
            "table_name": table_name,
            "length": len(table_name),
            "max_length": MAX_TABLE_NAME_LENGTH,
            "within_limit": len(table_name) <= MAX_TABLE_NAME_LENGTH,
        }
        for table_name in TABLE_NAMES_UNDER_REVIEW
    ]


def _path_results(root_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": required.name,
            "path": required.relative_path,
            "purpose": required.purpose,
            "present": (root_dir / required.relative_path).is_file(),
        }
        for required in REQUIRED_PATHS
    ]


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
                    "id": str(path_result["name"]),
                    "path": str(path_result["path"]),
                    "purpose": str(path_result["purpose"]),
                }
            )
    for token_result in tokens:
        if not token_result["present"]:
            issues.append(
                {
                    "category": "source_token_missing",
                    "id": str(token_result["token_id"]),
                    "path": str(token_result["path"]),
                    "purpose": str(token_result["purpose"]),
                }
            )
    for table_result in table_names:
        if not table_result["within_limit"]:
            issues.append(
                {
                    "category": "table_name_too_long",
                    "id": str(table_result["table_name"]),
                    "path": "database/nex-ag/migrations",
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


def assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
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
        r"raw_case_comment\s*[:=]\s*['\"]",
        r"raw_action_comment\s*[:=]\s*['\"]",
        r"raw_operator_note_text\s*[:=]\s*['\"]",
        r"raw_evidence_body\s*[:=]\s*['\"]",
        r"raw_prompt_text\s*[:=]\s*['\"]",
        r"raw_generation_output_text\s*[:=]\s*['\"]",
        r"raw_source_document_text\s*[:=]\s*['\"]",
        r"raw_provider_payload\s*[:=]\s*\{",
        r"raw_notification_payload\s*[:=]\s*\{",
        r"raw_external_incident_payload\s*[:=]\s*\{",
        r"provider_api_key\s*[:=]\s*['\"]",
        r"notification_secret\s*[:=]\s*['\"]",
        r"external_incident_token\s*[:=]\s*['\"]",
        r"artifact_binary_payload\s*[:=]\s*[A-Za-z0-9+/=]{16,}",
    )
    for pattern in sensitive_patterns:
        if re.search(pattern, serialized):
            raise ValueError(f"Sensitive value leaked in evidence: {pattern}")


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks")
    if evidence.get("status") != "PASS":
        failed = [
            key
            for key, value in (checks.items() if isinstance(checks, Mapping) else [])
            if not value
        ]
        return (
            "ag_operator_review_escalation_dispatch_execution_worker_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("execution_worker_boundary")
    table_results = evidence.get("table_name_results")
    grouped = _grouped_token_status(evidence.get("source_tokens"))
    return (
        "ag_operator_review_escalation_dispatch_execution_worker_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in grouped.values() if value)}/{len(grouped)} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else DISPATCH_EXECUTION_WORKER_BOUNDARY} "
        f"dispatch_table={DISPATCH_TABLE} "
        "worker=bounded_mock_first_only "
        "provider=mock_first_only "
        "live_delivery=deferred "
        f"next={NEXT_SLICE}"
    )


def write_audit_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Slice 0712 AG operator review escalation dispatch execution "
            "worker boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = (
        run_ag_operator_review_escalation_dispatch_execution_worker_boundary_audit()
    )
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
