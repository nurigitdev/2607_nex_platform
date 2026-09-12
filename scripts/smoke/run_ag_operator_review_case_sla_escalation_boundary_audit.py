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
SCHEMA_VERSION = "ag_operator_review_case_sla_escalation_boundary_audit.v1"

SLICE_ID = "0681"
S69_SURFACE = "AG operator review case SLA/escalation"
CASE_SLA_ESCALATION_BOUNDARY = "ag_owned_operator_review_case_sla_escalation"
CASE_TABLE = "ag_op_cases"
OPERATIONAL_EVENT_TABLE = "service_operational_events"
DEFERRED_ESCALATION_TABLE = "ag_op_escalations"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0682"

PROTECTED_ENV_KEYS = (
    "NEX_AG_DATABASE_URL",
    "NEX_AG_TEST_DATABASE_URL",
    "NEX_AG_OPERATIONS_SOURCE_MODE",
    "NEX_AG_OPERATIONS_SOURCE_PROFILE",
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
        "Canonical SRS source for AG governance and operator evidence.",
    ),
    RequiredPath(
        "service_partition",
        "docs/30_service_specific_requirement_partition.md",
        "Service ownership split for AG-owned operator review state.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Testing baseline for protected regression and PostgreSQL smoke evidence.",
    ),
    RequiredPath(
        "issue_candidate_foundation",
        "docs/slices/0109_ag_operations_issue_candidate_projection.md",
        "Existing AG issue-candidate foundation for future escalation signals.",
    ),
    RequiredPath(
        "s65_boundary_doc",
        "docs/slices/0641_ag_operator_review_case_action_boundary_audit.md",
        "Original case/action boundary and notification deferral decision.",
    ),
    RequiredPath(
        "s68_workload_doc",
        "docs/slices/0674_ag_operator_review_case_assignment_workload_projection.md",
        "Existing assignment workload projection baseline.",
    ),
    RequiredPath(
        "s68_dashboard_doc",
        "docs/slices/0677_ag_operator_review_case_lifecycle_dashboard_integration.md",
        "Existing dashboard lifecycle integration baseline.",
    ),
    RequiredPath(
        "s68_closure_doc",
        "docs/slices/0680_s68_operator_review_case_decision_lifecycle_closure.md",
        "Closed decision lifecycle baseline.",
    ),
    RequiredPath(
        "s69_boundary_doc",
        "docs/slices/0681_ag_operator_review_case_sla_escalation_boundary_audit.md",
        "This S69 boundary decision record.",
    ),
    RequiredPath(
        "s68_closure_script",
        "scripts/smoke/run_s68_operator_review_case_decision_lifecycle_closure.py",
        "Closed S68 evidence checkpoint.",
    ),
    RequiredPath(
        "s69_boundary_script",
        "scripts/smoke/run_ag_operator_review_case_sla_escalation_boundary_audit.py",
        "This S69 boundary audit runner.",
    ),
    RequiredPath(
        "ag_operator_review_cases",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "AG-owned operator review case/action runtime surface.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG dashboard and issue-candidate projection surface.",
    ),
    RequiredPath(
        "case_migration",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "Existing AG-owned case table baseline.",
    ),
    RequiredPath(
        "event_migration",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "Existing AG-owned operational event table baseline.",
    ),
    RequiredPath(
        "case_workbench_schema",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "Case queue, lifecycle, assignment workload, and closure contract baseline.",
    ),
    RequiredPath(
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "Operations dashboard and issue-candidate contract baseline.",
    ),
    RequiredPath(
        "case_queue_example",
        "contracts/examples/operations/ag_operator_review_case_queue.mock_success.json",
        "Existing case attention/recommended-action example.",
    ),
    RequiredPath(
        "openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AG OpenAPI contract surface.",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh", "Default regression gate."),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s68_closed_baseline",
        "scripts/smoke/run_s68_operator_review_case_decision_lifecycle_closure.py",
        "s68_closure_schema",
        "s68_operator_review_case_decision_lifecycle_closure.v1",
        "S69 starts after S68 decision lifecycle closure.",
    ),
    TokenRequirement(
        "s68_closed_baseline",
        "docs/slices/0680_s68_operator_review_case_decision_lifecycle_closure.md",
        "s68_read_model_only",
        "closure_packet_storage=read_model_only_not_persisted",
        "SLA/escalation builds on the closed read-model-only lifecycle.",
    ),
    TokenRequirement(
        "deferred_delivery_baseline",
        "docs/slices/0641_ag_operator_review_case_action_boundary_audit.md",
        "notification_deferred",
        "Notification delivery and external incident-system sync remain deferred.",
        "S69 must not send outbound notifications or sync incident systems yet.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "attention_status_choices",
        "ALLOWED_CASE_QUEUE_ATTENTION_STATUSES",
        "SLA/escalation should reuse existing case attention statuses.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "open_case_unassigned_reason",
        "open_case_unassigned",
        "Unassigned open cases are an escalation input.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "urgent_not_closed_reason",
        "urgent_case_not_closed",
        "Urgent open cases are an escalation input.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "assigned_in_progress_reason",
        "assigned_case_in_progress",
        "Assigned cases in progress are aging/SLA inputs.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "reopened_review_reason",
        "reopened_case_requires_review",
        "Reopened cases are escalation inputs.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "assignment_workload_projection",
        "build_operator_review_case_assignment_workload_projection",
        "SLA/escalation should reuse the workload projection foundation.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "recommended_actions",
        "recommended_actions",
        "Escalation signals should remain operator-action hints, not mutations.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "idempotency_keys_redacted",
        '"idempotency_keys_included": False',
        "SLA/escalation surfaces must not expose raw idempotency keys.",
    ),
    TokenRequirement(
        "case_attention_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "raw_comments_redacted",
        '"raw_action_comment_included": False',
        "SLA/escalation surfaces must not expose raw operator comments.",
    ),
    TokenRequirement(
        "operations_issue_candidate_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "case_attention_issue_rule",
        "operator_review_case_attention_required.v1",
        "SLA/escalation should extend the existing case attention issue signal.",
    ),
    TokenRequirement(
        "operations_issue_candidate_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "assign_owner_runbook",
        "ag.operator_review_case.assign_owner.v1",
        "Unassigned case escalation should point to an owner-assignment runbook.",
    ),
    TokenRequirement(
        "operations_issue_candidate_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "urgent_triage_runbook",
        "ag.operator_review_case.urgent_triage.v1",
        "Urgent overdue escalation should point to urgent triage.",
    ),
    TokenRequirement(
        "operations_issue_candidate_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "case_queue_path",
        'case_queue_path": "/admin/v1/operator-review/cases/queue"',
        "Escalation candidates should link back to the case queue.",
    ),
    TokenRequirement(
        "operations_issue_candidate_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "workbench_detail_template",
        "case_workbench_detail_path_template",
        "Escalation candidates should link to case detail.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_table",
        "CREATE TABLE IF NOT EXISTS ag_op_cases",
        "S69 should reuse the existing case table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_status_index",
        "idx_ag_op_cases_status_time",
        "SLA reads need status/time indexed case access.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_assignee_index",
        "idx_ag_op_cases_assignee_time",
        "Assignment and stale-owner projections need assignee/time indexed reads.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_table",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
        "Escalation evidence should correlate with existing operational events.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "case_queue_schema",
        "ag_operator_review_case_queue.v1",
        "SLA/escalation starts from the existing case queue contract.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "attention_status_contract",
        "attention_status",
        "SLA/escalation must keep attention status contract alignment.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "recommended_actions_contract",
        "recommended_actions",
        "SLA/escalation should expose bounded operator action hints.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_case_section",
        "dashboard_operator_review_cases",
        "Operations dashboard can carry future escalation summary fields.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "case_queue_route",
        "/admin/v1/operator-review/cases/queue",
        "SLA/escalation links must resolve to existing case queue route.",
    ),
    TokenRequirement(
        "s69_boundary_docs",
        "docs/README.md",
        "doc_index_0681",
        "0681_ag_operator_review_case_sla_escalation_boundary_audit.md",
        "Slice 0681 must be indexed.",
    ),
    TokenRequirement(
        "s69_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s69_readme_note",
        "Slice 0681 starts S69",
        "AG README must record the SLA/escalation boundary.",
    ),
    TokenRequirement(
        "s69_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s69_boundary_quality_gate_hook",
        "run_ag_operator_review_case_sla_escalation_boundary_audit.py",
        "Slice 0681 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    ("sla_policy_read_model", "Slice_0682", "Define case SLA policy and read-model shape."),
    ("case_aging_stale_assignment", "Slice_0683", "Project case age and stale assignment signals."),
    ("escalation_candidate_projection", "Slice_0684", "Build escalation candidate projection."),
    ("escalation_route_wiring", "Slice_0685", "Expose protected escalation route."),
    ("escalation_dashboard_integration", "Slice_0686", "Fold escalation signals into AG operations."),
    ("escalation_contract_openapi", "Slice_0687", "Freeze escalation contracts and OpenAPI."),
    ("escalation_privacy_regression", "Slice_0688", "Prove redaction/privacy boundaries."),
    ("escalation_postgres_smoke", "Slice_0689", "Prove escalation read models against nex_ag_test."),
    ("s69_closure", "Slice_0690", "Close the SLA/escalation readiness loop."),
)

TABLE_NAMES_UNDER_REVIEW = (
    CASE_TABLE,
    OPERATIONAL_EVENT_TABLE,
    DEFERRED_ESCALATION_TABLE,
)


def run_ag_operator_review_case_sla_escalation_boundary_audit(
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
        "s68_closed_baseline_present": token_groups.get("s68_closed_baseline", False),
        "deferred_delivery_baseline_present": token_groups.get(
            "deferred_delivery_baseline", False
        ),
        "case_attention_runtime_present": token_groups.get(
            "case_attention_runtime", False
        ),
        "operations_issue_candidate_runtime_present": token_groups.get(
            "operations_issue_candidate_runtime", False
        ),
        "persistence_baseline_present": token_groups.get("persistence_baseline", False),
        "contracts_baseline_present": token_groups.get("contracts_baseline", False),
        "s69_boundary_docs_present": token_groups.get("s69_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S69_SURFACE,
        "case_sla_escalation_boundary": _case_sla_escalation_boundary(),
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
        evidence["failure_code"] = "ag_operator_review_case_sla_escalation_boundary_failed"
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _case_sla_escalation_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "projection_owner": "nex-ag",
        "boundary": CASE_SLA_ESCALATION_BOUNDARY,
        "create_table_in_slice_0681": False,
        "first_read_model_slice": NEXT_SLICE,
        "case_source_table": CASE_TABLE,
        "event_source_table": OPERATIONAL_EVENT_TABLE,
        "deferred_escalation_table_candidate": DEFERRED_ESCALATION_TABLE,
        "source_tables": [
            {"table_name": CASE_TABLE, "role": "case_status_priority_assignment_source"},
            {
                "table_name": OPERATIONAL_EVENT_TABLE,
                "role": "case_action_history_and_evidence_correlation_source",
            },
        ],
        "planned_read_model_surfaces": [
            "/admin/v1/operator-review/cases/sla-policy",
            "/admin/v1/operator-review/cases/aging",
            "/admin/v1/operator-review/cases/escalations",
        ],
        "existing_reference_surfaces": [
            "/admin/v1/operator-review/cases/queue",
            "/admin/v1/operator-review/cases/{case_id}/workbench-detail",
            "/admin/v1/operator-review/cases/{case_id}/timeline",
            "/admin/v1/operator-review/cases/{case_id}/closure-packet",
            "/admin/v1/operations/issue-candidates",
        ],
        "sla_inputs": [
            "case_status",
            "case_priority",
            "assignment_ref",
            "created_at",
            "updated_at",
            "closed_at",
            "latest_action_at",
            "attention_status",
            "attention_reason_codes",
        ],
        "sla_outputs": [
            "sla_policy_id",
            "case_age_seconds",
            "stale_assignment",
            "overdue_state",
            "escalation_level",
            "recommended_operator_actions",
            "runbook_ids",
            "safe_case_links",
        ],
        "initial_policy_defaults": {
            "LOW": "observe_only",
            "MEDIUM": "triage_within_business_day",
            "HIGH": "same_day_follow_up",
            "URGENT": "immediate_operator_attention",
        },
        "allowed_payload_shape": [
            "case_id",
            "target_reference",
            "case_status",
            "case_priority",
            "assignment_ref",
            "age_summary",
            "sla_state",
            "escalation_candidate_summary",
            "safe_runbook_ids",
            "safe_route_links",
            "redaction_flags",
        ],
        "forbidden_payloads": [
            "raw_case_comment",
            "raw_action_comment",
            "raw_resolution_comment",
            "raw_operator_note_text",
            "raw_evidence_body",
            "raw_prompt_text",
            "raw_generation_output_text",
            "raw_source_document_text",
            "raw_provider_payload",
            "database_url",
            "service_token",
            "provider_api_key",
            "local_storage_path",
            "artifact_binary_payload",
            "raw_idempotency_key",
            "raw_metadata_payload",
            "notification_secret",
            "external_incident_token",
        ],
        "notification_delivery": "deferred",
        "external_incident_sync": "deferred",
        "escalation_persistence": "read_model_first",
        "operator_acknowledgement_persistence": "deferred_until_required",
        "postgres_smoke_required_before_s69_closure": True,
        "ag_may_write_own_case_records": True,
        "ag_may_send_outbound_notifications_in_s69": False,
        "ag_may_sync_external_incident_systems_in_s69": False,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "reuse_ag_op_cases_for_sla_state_inputs": True,
        "reuse_service_operational_events_for_action_age_context": True,
        "derive_escalation_candidates_from_existing_attention_reasons": True,
        "avoid_new_escalation_table_until_ack_history_or_retention_need_is_proven": True,
        "keep_sla_policy_as_read_model_configuration_first": True,
        "do_not_send_notifications_or_sync_external_incidents_in_s69": True,
        "keep_escalation_surfaces_metadata_only": True,
        "link_to_case_queue_detail_timeline_and_closure_packet": True,
        "require_real_nex_ag_test_db_smoke_before_s69_closure": True,
        "do_not_copy_raw_prompts_source_docs_provider_payloads_or_storage_paths": True,
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
        r"raw_resolution_comment\s*[:=]\s*['\"]",
        r"raw_operator_note_text\s*[:=]\s*['\"]",
        r"raw_evidence_body\s*[:=]\s*['\"]",
        r"raw_prompt_text\s*[:=]\s*['\"]",
        r"raw_generation_output_text\s*[:=]\s*['\"]",
        r"raw_source_document_text\s*[:=]\s*['\"]",
        r"raw_provider_payload\s*[:=]\s*\{",
        r"raw_metadata_payload\s*[:=]\s*\{",
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
            "ag_operator_review_case_sla_escalation_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("case_sla_escalation_boundary")
    table_results = evidence.get("table_name_results")
    grouped = _grouped_token_status(evidence.get("source_tokens"))
    return (
        "ag_operator_review_case_sla_escalation_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in grouped.values() if value)}/{len(grouped)} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else CASE_SLA_ESCALATION_BOUNDARY} "
        "escalation=read_model_first "
        "notification=deferred "
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
            "Run the Slice 0681 AG operator review case SLA/escalation "
            "boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_case_sla_escalation_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
