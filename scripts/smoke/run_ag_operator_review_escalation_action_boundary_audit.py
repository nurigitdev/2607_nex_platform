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
SCHEMA_VERSION = "ag_operator_review_escalation_action_boundary_audit.v1"

SLICE_ID = "0691"
S70_SURFACE = "AG operator review escalation action loop"
ESCALATION_ACTION_BOUNDARY = "ag_owned_operator_review_escalation_action_loop"
CASE_TABLE = "ag_op_cases"
OPERATIONAL_EVENT_TABLE = "service_operational_events"
ESCALATION_TABLE = "ag_op_escalations"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0692"

PROTECTED_ENV_KEYS = (
    "NEX_AG_DATABASE_URL",
    "NEX_AG_TEST_DATABASE_URL",
    "NEX_AG_OPERATIONS_SOURCE_MODE",
    "NEX_AG_OPERATIONS_SOURCE_PROFILE",
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
        "Canonical SRS source for AG governance and operator review.",
    ),
    RequiredPath(
        "service_partition",
        "docs/30_service_specific_requirement_partition.md",
        "Service ownership split for AG-owned operator state.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Testing baseline for protected regression and PostgreSQL smoke evidence.",
    ),
    RequiredPath(
        "s69_boundary_doc",
        "docs/slices/0681_ag_operator_review_case_sla_escalation_boundary_audit.md",
        "SLA/escalation read-model boundary baseline.",
    ),
    RequiredPath(
        "s69_closure_doc",
        "docs/slices/0690_s69_operator_review_case_sla_escalation_closure.md",
        "Closed S69 readiness checkpoint.",
    ),
    RequiredPath(
        "s69_closure_script",
        "scripts/smoke/run_s69_operator_review_case_sla_escalation_closure.py",
        "Closed S69 evidence checkpoint.",
    ),
    RequiredPath(
        "s70_boundary_doc",
        "docs/slices/0691_ag_operator_review_escalation_action_boundary_audit.md",
        "This S70 boundary decision record.",
    ),
    RequiredPath(
        "ag_operator_review_cases",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "AG-owned operator review case, action, and escalation projection runtime.",
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
        "case_schema",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "Case mutation/action contract baseline.",
    ),
    RequiredPath(
        "case_workbench_schema",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "Case workbench, SLA, escalation, and lifecycle contract baseline.",
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
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh", "Default regression gate."),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s69_closed_baseline",
        "scripts/smoke/run_s69_operator_review_case_sla_escalation_closure.py",
        "s69_closure_schema",
        "s69_operator_review_case_sla_escalation_closure.v1",
        "S70 starts after S69 SLA/escalation readiness is closed.",
    ),
    TokenRequirement(
        "s69_closed_baseline",
        "docs/slices/0690_s69_operator_review_case_sla_escalation_closure.md",
        "s69_deferred_execution",
        "external incident sync remain deferred",
        "S70 inherits the deferred external execution decision.",
    ),
    TokenRequirement(
        "s69_escalation_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "escalation_schema_version",
        "OPERATOR_REVIEW_CASE_ESCALATION_SCHEMA_VERSION",
        "S70 actions must be anchored to S69 escalation candidates.",
    ),
    TokenRequirement(
        "s69_escalation_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "escalation_projection",
        "def build_operator_review_case_escalation_projection",
        "S70 overlays action state on the existing escalation projection.",
    ),
    TokenRequirement(
        "s69_escalation_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "notification_payload_redacted",
        '"notification_payload_included": False',
        "Escalation actions must not expose notification payloads.",
    ),
    TokenRequirement(
        "s69_escalation_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "external_incident_payload_redacted",
        '"external_incident_payload_included": False',
        "Escalation actions must not expose external incident payloads.",
    ),
    TokenRequirement(
        "case_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "allowed_case_actions",
        "ALLOWED_CASE_ACTIONS = (",
        "Escalation action loop should reuse bounded operator actions.",
    ),
    TokenRequirement(
        "case_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_action_state_machine",
        "CASE_ACTION_ALLOWED_FROM",
        "Escalation action loop must stay state-machine driven.",
    ),
    TokenRequirement(
        "case_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_action_apply",
        "def apply_operator_review_case_action",
        "Escalation actions should call the existing case action function.",
    ),
    TokenRequirement(
        "case_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "case_action_event",
        "OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE",
        "Escalation action history should remain visible through safe events.",
    ),
    TokenRequirement(
        "case_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "idempotency_required",
        "Idempotency-Key is required for operator review case actions.",
        "Operator escalation actions must be idempotent.",
    ),
    TokenRequirement(
        "operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_escalation_block",
        '"escalations": {',
        "S70 dashboard updates should extend the existing escalation block.",
    ),
    TokenRequirement(
        "operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "issue_candidate_rule",
        "operator_review_case_attention_required.v1",
        "Escalation actions should align with existing attention issue signals.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0642_ag_operator_review_case_persistence.sql",
        "case_table",
        "CREATE TABLE IF NOT EXISTS ag_op_cases",
        "S70 must keep the case table as the case state source of record.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_table",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
        "S70 action history should be observable through operational events.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "case_action_mutation_contract",
        "ag_operator_review_case_action_mutation.v1",
        "S70 should reuse the existing case action mutation contract where possible.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case_workbench.v1.schema.json",
        "case_escalations_contract",
        "ag_operator_review_case_escalations.v1",
        "S70 action overlays start from the frozen S69 escalation contract.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "case_action_route",
        "/admin/v1/operator-review/cases/{case_id}/actions",
        "S70 action routes should stay close to the existing case action API.",
    ),
    TokenRequirement(
        "s70_boundary_docs",
        "docs/README.md",
        "doc_index_0691",
        "0691_ag_operator_review_escalation_action_boundary_audit.md",
        "Slice 0691 must be indexed.",
    ),
    TokenRequirement(
        "s70_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s70_readme_note",
        "Slice 0691 starts S70",
        "AG README must record the escalation action boundary.",
    ),
    TokenRequirement(
        "s70_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s70_boundary_quality_gate_hook",
        "run_ag_operator_review_escalation_action_boundary_audit.py",
        "Slice 0691 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    ("escalation_persistence_foundation", "Slice_0692", "Add AG-owned escalation acknowledgement/action persistence."),
    ("escalation_action_state_machine", "Slice_0693", "Define ACK/SNOOZE/DISMISS/REOPEN action transitions."),
    ("escalation_action_routes", "Slice_0694", "Expose protected escalation action routes."),
    ("escalation_read_model_overlay", "Slice_0695", "Overlay persisted escalation action state on S69 projections."),
    ("escalation_dashboard_integration", "Slice_0696", "Show active/acknowledged/snoozed escalation status in operations."),
    ("escalation_contract_openapi", "Slice_0697", "Freeze escalation action schemas, examples, and OpenAPI."),
    ("escalation_privacy_idempotency_regression", "Slice_0698", "Prove redaction and idempotency boundaries."),
    ("escalation_postgres_smoke", "Slice_0699", "Prove action loop against nex_ag_test."),
    ("s70_closure", "Slice_0700", "Close the escalation action loop."),
)

TABLE_NAMES_UNDER_REVIEW = (
    CASE_TABLE,
    OPERATIONAL_EVENT_TABLE,
    ESCALATION_TABLE,
)


def run_ag_operator_review_escalation_action_boundary_audit(
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
        "s69_closed_baseline_present": token_groups.get("s69_closed_baseline", False),
        "s69_escalation_runtime_present": token_groups.get("s69_escalation_runtime", False),
        "case_action_runtime_present": token_groups.get("case_action_runtime", False),
        "operations_runtime_present": token_groups.get("operations_runtime", False),
        "persistence_baseline_present": token_groups.get("persistence_baseline", False),
        "contracts_baseline_present": token_groups.get("contracts_baseline", False),
        "s70_boundary_docs_present": token_groups.get("s70_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S70_SURFACE,
        "escalation_action_boundary": _escalation_action_boundary(),
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
        evidence["failure_code"] = "ag_operator_review_escalation_action_boundary_failed"
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _escalation_action_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "execution_owner": "nex-ag",
        "boundary": ESCALATION_ACTION_BOUNDARY,
        "create_table_in_slice_0691": False,
        "first_persistence_slice": NEXT_SLICE,
        "case_source_table": CASE_TABLE,
        "event_source_table": OPERATIONAL_EVENT_TABLE,
        "planned_escalation_table": ESCALATION_TABLE,
        "source_tables": [
            {"table_name": CASE_TABLE, "role": "case_state_source_of_record"},
            {
                "table_name": OPERATIONAL_EVENT_TABLE,
                "role": "safe_action_history_and_timeline_source",
            },
        ],
        "planned_owned_tables": [
            {
                "table_name": ESCALATION_TABLE,
                "role": "operator_acknowledgement_snooze_and_resolution_state",
                "first_slice": NEXT_SLICE,
            }
        ],
        "existing_reference_surfaces": [
            "/admin/v1/operator-review/cases/escalations",
            "/admin/v1/operator-review/cases/aging",
            "/admin/v1/operator-review/cases/queue",
            "/admin/v1/operator-review/cases/{case_id}/actions",
            "/admin/v1/operator-review/cases/{case_id}/timeline",
            "/admin/v1/operator-review/cases/{case_id}/closure-packet",
        ],
        "planned_action_surfaces": [
            "/admin/v1/operator-review/escalations",
            "/admin/v1/operator-review/escalations/{escalation_id}/actions",
        ],
        "allowed_action_intents": [
            "ACKNOWLEDGE",
            "SNOOZE",
            "ASSIGN_OWNER",
            "LINK_CASE_ACTION",
            "DISMISS_ESCALATION",
            "REOPEN_ESCALATION",
        ],
        "allowed_payload_shape": [
            "escalation_id",
            "case_id",
            "target_reference",
            "operator_ref",
            "action_type",
            "reason_codes",
            "snooze_until",
            "safe_comment_hash",
            "safe_comment_preview",
            "idempotency_key_hash",
            "created_at",
            "updated_at",
            "redaction_flags",
        ],
        "forbidden_payloads": [
            "raw_case_comment",
            "raw_action_comment",
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
            "raw_notification_payload",
            "raw_external_incident_payload",
            "notification_secret",
            "external_incident_token",
        ],
        "notification_delivery": "still_deferred",
        "external_incident_sync": "still_deferred",
        "escalation_persistence": "planned_ag_owned_ack_state",
        "action_history": "service_operational_events_and_safe_escalation_state",
        "postgres_smoke_required_before_s70_closure": True,
        "ag_may_write_own_escalation_records_after_slice_0692": True,
        "ag_may_reuse_case_action_state_machine": True,
        "ag_may_send_outbound_notifications_in_s70": False,
        "ag_may_sync_external_incident_systems_in_s70": False,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "reuse_s69_escalation_projection_as_candidate_input": True,
        "reuse_existing_case_action_state_machine_for_case_status_changes": True,
        "persist_only_operator_acknowledgement_snooze_and_resolution_state": True,
        "keep_raw_comments_as_hash_and_short_preview_only": True,
        "hash_idempotency_keys_before_storage_or_projection": True,
        "keep_notification_delivery_deferred_in_s70": True,
        "keep_external_incident_sync_deferred_in_s70": True,
        "record_safe_action_history_in_operational_events": True,
        "require_real_nex_ag_test_db_smoke_before_s70_closure": True,
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
            "ag_operator_review_escalation_action_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("escalation_action_boundary")
    table_results = evidence.get("table_name_results")
    grouped = _grouped_token_status(evidence.get("source_tokens"))
    return (
        "ag_operator_review_escalation_action_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in grouped.values() if value)}/{len(grouped)} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else ESCALATION_ACTION_BOUNDARY} "
        "persistence=planned_ag_owned_ack_state "
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
            "Run the Slice 0691 AG operator review escalation action boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_escalation_action_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
