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
SCHEMA_VERSION = "ag_operator_review_escalation_outbound_dispatch_boundary_audit.v1"

SLICE_ID = "0701"
S71_SURFACE = "AG operator review escalation outbound dispatch"
ESCALATION_OUTBOUND_DISPATCH_BOUNDARY = (
    "ag_owned_operator_review_escalation_outbound_dispatch"
)
CASE_TABLE = "ag_op_cases"
ESCALATION_TABLE = "ag_op_escalations"
OPERATIONAL_EVENT_TABLE = "service_operational_events"
PLANNED_DISPATCH_TABLE = "ag_op_esc_dispatches"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0702"

PROTECTED_ENV_KEYS = (
    "NEX_AG_DATABASE_URL",
    "NEX_AG_TEST_DATABASE_URL",
    "NEX_AG_ESCALATION_DISPATCH_PROVIDER_MODE",
    "NEX_AG_ESCALATION_DISPATCH_PROVIDER_PROFILE",
    "NEX_AG_NOTIFICATION_WEBHOOK_URL",
    "NEX_AG_NOTIFICATION_SERVICE_TOKEN",
    "NEX_AG_EXTERNAL_INCIDENT_BASE_URL",
    "NEX_AG_EXTERNAL_INCIDENT_TOKEN",
    "NEX_AG_DISPATCH_OUTBOX_DATABASE_URL",
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
        "Service ownership split for AG-owned operator state.",
    ),
    RequiredPath(
        "testing_strategy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Testing baseline for protected regression and PostgreSQL smoke evidence.",
    ),
    RequiredPath(
        "s70_boundary_doc",
        "docs/slices/0691_ag_operator_review_escalation_action_boundary_audit.md",
        "S70 action boundary and external delivery deferral baseline.",
    ),
    RequiredPath(
        "s70_postgres_smoke_doc",
        "docs/slices/0699_ag_operator_review_escalation_postgresql_smoke.md",
        "S70 real nex_ag_test PostgreSQL smoke evidence.",
    ),
    RequiredPath(
        "s70_closure_doc",
        "docs/slices/0700_s70_operator_review_escalation_action_closure.md",
        "Closed S70 escalation action loop baseline.",
    ),
    RequiredPath(
        "s70_closure_script",
        "scripts/smoke/run_s70_operator_review_escalation_action_closure.py",
        "Closed S70 evidence checkpoint.",
    ),
    RequiredPath(
        "s71_boundary_doc",
        "docs/slices/0701_ag_operator_review_escalation_outbound_dispatch_boundary_audit.md",
        "This S71 boundary decision record.",
    ),
    RequiredPath(
        "ag_operator_review_cases",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "AG-owned operator review case and persisted escalation runtime.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG dashboard and issue-candidate projection surface.",
    ),
    RequiredPath(
        "escalation_migration",
        "database/nex-ag/migrations/0692_ag_operator_review_escalation_persistence.sql",
        "Existing AG-owned escalation action-state table baseline.",
    ),
    RequiredPath(
        "event_migration",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "Existing AG-owned operational event table baseline.",
    ),
    RequiredPath(
        "operator_review_case_schema",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "Persisted escalation list/detail/action contract baseline.",
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
        "s70_closed_baseline",
        "scripts/smoke/run_s70_operator_review_escalation_action_closure.py",
        "s70_closure_schema",
        "s70_operator_review_escalation_action_closure.v1",
        "S71 starts after S70 escalation action readiness is closed.",
    ),
    TokenRequirement(
        "s70_closed_baseline",
        "docs/slices/0700_s70_operator_review_escalation_action_closure.md",
        "s70_dispatch_deferred",
        "notification delivery and external incident-system sync remain",
        "S71 inherits the explicit external delivery deferral from S70.",
    ),
    TokenRequirement(
        "s70_dispatch_deferred_baseline",
        "docs/slices/0691_ag_operator_review_escalation_action_boundary_audit.md",
        "not_outbound_integration",
        "not an outbound integration slice",
        "S71 must intentionally reopen the previously deferred outbound boundary.",
    ),
    TokenRequirement(
        "s70_dispatch_deferred_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "notification_delivery_deferred",
        '"notification_delivery_deferred": True',
        "Existing escalation metadata marks notification delivery deferred.",
    ),
    TokenRequirement(
        "s70_dispatch_deferred_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "external_incident_sync_deferred",
        '"external_incident_sync_deferred": True',
        "Existing escalation metadata marks external incident sync deferred.",
    ),
    TokenRequirement(
        "escalation_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "escalation_table_constant",
        'AG_OPERATOR_REVIEW_ESCALATION_TABLE = "ag_op_escalations"',
        "Outbound dispatch must reference persisted S70 escalation state.",
    ),
    TokenRequirement(
        "escalation_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "escalation_action_event",
        "OPERATOR_REVIEW_ESCALATION_ACTION_RECORDED_EVENT_TYPE",
        "Outbound dispatch should correlate to safe escalation action history.",
    ),
    TokenRequirement(
        "escalation_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "apply_escalation_action",
        "def apply_operator_review_escalation_action",
        "Dispatch planning starts after the persisted action state machine.",
    ),
    TokenRequirement(
        "escalation_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "raw_notification_payload_not_stored",
        '"raw_notification_payload_stored": False',
        "S71 outbox must not persist raw notification payloads.",
    ),
    TokenRequirement(
        "escalation_action_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "raw_external_incident_payload_not_stored",
        '"raw_external_incident_payload_stored": False',
        "S71 outbox must not persist raw external incident payloads.",
    ),
    TokenRequirement(
        "operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "operator_review_escalation_dashboard_section",
        "operator_review_escalations",
        "Dispatch status should extend the persisted escalation operations section.",
    ),
    TokenRequirement(
        "operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "escalation_issue_candidate_rule",
        "operator_review_escalation_action_required.v1",
        "Dispatch planning must align with the existing escalation issue signal.",
    ),
    TokenRequirement(
        "operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "raw_notification_payload_redacted",
        '"raw_notification_payload_included": False',
        "Operations projections must not expose raw outbound notification payloads.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0692_ag_operator_review_escalation_persistence.sql",
        "escalation_table",
        "CREATE TABLE IF NOT EXISTS ag_op_escalations",
        "S71 dispatch records should reference the existing short escalation table.",
    ),
    TokenRequirement(
        "persistence_baseline",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "event_table",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
        "Dispatch attempts should remain observable through safe operational events.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "escalation_action_mutation_contract",
        "ag_operator_review_escalation_action_mutation.v1",
        "Dispatch is downstream of the frozen escalation action mutation contract.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operator_review_case.v1.schema.json",
        "raw_notification_payload_contract_flag",
        "raw_notification_payload_included",
        "Dispatch contracts must preserve explicit redaction flags.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_escalation_section_contract",
        "ag_operator_review_escalation_dashboard_section.v1",
        "S71 dashboard additions should extend the frozen escalation section.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "escalation_action_route",
        "/admin/v1/operator-review/escalations/{escalation_id}/actions",
        "Dispatch remains downstream of the protected escalation action route.",
    ),
    TokenRequirement(
        "s71_boundary_docs",
        "docs/README.md",
        "doc_index_0701",
        "0701_ag_operator_review_escalation_outbound_dispatch_boundary_audit.md",
        "Slice 0701 must be indexed.",
    ),
    TokenRequirement(
        "s71_boundary_docs",
        "services/nex-ag/README.md",
        "ag_s71_readme_note",
        "Slice 0701 starts S71",
        "AG README must record the outbound dispatch boundary.",
    ),
    TokenRequirement(
        "s71_boundary_docs",
        "scripts/quality/run_quality_gate.sh",
        "s71_boundary_quality_gate_hook",
        "run_ag_operator_review_escalation_outbound_dispatch_boundary_audit.py",
        "Slice 0701 audit must run in the default quality gate.",
    ),
)

PLANNED_SLICES = (
    ("dispatch_schema_store_foundation", "Slice_0702", "Add AG-owned dispatch/outbox persistence foundation."),
    ("dispatch_policy_planner", "Slice_0703", "Plan safe notification and incident dispatch intents."),
    ("dispatch_state_machine", "Slice_0704", "Define PENDING/DISPATCHING/SUCCEEDED/FAILED/RETRY_WAIT/CANCELLED transitions."),
    ("dispatch_service_api_routes", "Slice_0705", "Expose protected dispatch create/detail/action controls."),
    ("dispatch_read_model_routes", "Slice_0706", "Expose protected dispatch list/read-model filters."),
    ("dispatch_operations_dashboard", "Slice_0707", "Surface delayed/failed dispatches in operations and issue candidates."),
    ("dispatch_contract_openapi", "Slice_0708", "Freeze schemas, examples, negative leak fixtures, and OpenAPI."),
    ("dispatch_privacy_regression", "Slice_0709", "Prove route, dashboard, and evidence redaction."),
    ("dispatch_postgres_smoke", "Slice_0710", "Prove nex_ag_test persistence behavior."),
    ("s71_closure", "Slice_0711", "Close the outbound dispatch foundation."),
)

TABLE_NAMES_UNDER_REVIEW = (
    CASE_TABLE,
    ESCALATION_TABLE,
    OPERATIONAL_EVENT_TABLE,
    PLANNED_DISPATCH_TABLE,
)


def run_ag_operator_review_escalation_outbound_dispatch_boundary_audit(
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
        "s70_closed_baseline_present": token_groups.get("s70_closed_baseline", False),
        "s70_dispatch_deferred_baseline_present": token_groups.get(
            "s70_dispatch_deferred_baseline", False
        ),
        "escalation_action_runtime_present": token_groups.get(
            "escalation_action_runtime", False
        ),
        "operations_runtime_present": token_groups.get("operations_runtime", False),
        "persistence_baseline_present": token_groups.get("persistence_baseline", False),
        "contracts_baseline_present": token_groups.get("contracts_baseline", False),
        "s71_boundary_docs_present": token_groups.get("s71_boundary_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S71_SURFACE,
        "outbound_dispatch_boundary": _outbound_dispatch_boundary(),
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
            "ag_operator_review_escalation_outbound_dispatch_boundary_failed"
        )
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _outbound_dispatch_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "dispatch_owner": "nex-ag",
        "boundary": ESCALATION_OUTBOUND_DISPATCH_BOUNDARY,
        "create_table_in_slice_0701": False,
        "first_persistence_slice": NEXT_SLICE,
        "case_source_table": CASE_TABLE,
        "escalation_source_table": ESCALATION_TABLE,
        "event_source_table": OPERATIONAL_EVENT_TABLE,
        "planned_dispatch_table": PLANNED_DISPATCH_TABLE,
        "source_tables": [
            {"table_name": CASE_TABLE, "role": "case_state_source_of_record"},
            {
                "table_name": ESCALATION_TABLE,
                "role": "persisted_escalation_action_state_source",
            },
            {
                "table_name": OPERATIONAL_EVENT_TABLE,
                "role": "safe_action_and_dispatch_history_source",
            },
        ],
        "planned_owned_tables": [
            {
                "table_name": PLANNED_DISPATCH_TABLE,
                "role": "safe_outbound_dispatch_outbox_and_attempt_state",
                "first_slice": NEXT_SLICE,
            }
        ],
        "existing_reference_surfaces": [
            "/admin/v1/operator-review/escalations",
            "/admin/v1/operator-review/escalations/{escalation_id}",
            "/admin/v1/operator-review/escalations/{escalation_id}/actions",
            "/admin/v1/operations/dashboard",
            "/admin/v1/operations/issue-candidates",
        ],
        "planned_dispatch_surfaces": [
            "/admin/v1/operator-review/escalation-dispatches",
            "/admin/v1/operator-review/escalation-dispatches/{dispatch_id}",
            "/admin/v1/operator-review/escalation-dispatches/{dispatch_id}/actions",
        ],
        "allowed_dispatch_intents": [
            "NOTIFY_OPERATOR",
            "NOTIFY_OWNER",
            "OPEN_INCIDENT",
            "UPDATE_INCIDENT",
            "CANCEL_PENDING_DISPATCH",
            "RETRY_FAILED_DISPATCH",
        ],
        "allowed_payload_shape": [
            "dispatch_id",
            "escalation_id",
            "case_id",
            "target_reference",
            "channel_type",
            "provider_ref",
            "provider_profile",
            "dispatch_status",
            "dispatch_intent",
            "reason_codes",
            "safe_subject",
            "safe_body_hash",
            "safe_body_preview",
            "provider_payload_hash",
            "idempotency_key_hash",
            "attempt_count",
            "next_attempt_at",
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
        "provider_execution_in_s71": "mock_first_only",
        "live_provider_execution_in_s71": False,
        "outbound_network_delivery_in_s71": False,
        "postgres_smoke_required_before_s71_closure": True,
        "notification_delivery": "planned_as_outbox_not_live_delivery",
        "external_incident_sync": "planned_as_outbox_not_live_sync",
        "dispatch_persistence": "planned_ag_owned_outbox_state",
        "dispatch_history": "service_operational_events_and_safe_dispatch_state",
        "ag_may_create_dispatch_outbox_records_after_slice_0702": True,
        "ag_may_send_live_notifications_in_s71": False,
        "ag_may_sync_live_external_incidents_in_s71": False,
        "ag_may_mutate_source_service_records": False,
        "ag_may_copy_raw_source_payloads": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "reuse_s70_persisted_escalation_state_as_dispatch_input": True,
        "separate_dispatch_planning_from_provider_execution": True,
        "persist_only_safe_outbox_state_hashes_and_previews": True,
        "keep_live_provider_execution_out_of_s71": True,
        "use_mock_provider_for_s71_regression": True,
        "hash_idempotency_keys_before_storage_or_projection": True,
        "keep_raw_notification_payloads_out_of_db_and_evidence": True,
        "keep_raw_external_incident_payloads_out_of_db_and_evidence": True,
        "record_safe_dispatch_history_in_operational_events": True,
        "require_real_nex_ag_test_db_smoke_before_s71_closure": True,
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
            "ag_operator_review_escalation_outbound_dispatch_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("outbound_dispatch_boundary")
    table_results = evidence.get("table_name_results")
    grouped = _grouped_token_status(evidence.get("source_tokens"))
    return (
        "ag_operator_review_escalation_outbound_dispatch_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in grouped.values() if value)}/{len(grouped)} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else ESCALATION_OUTBOUND_DISPATCH_BOUNDARY} "
        f"dispatch_table={PLANNED_DISPATCH_TABLE} "
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
            "Run the Slice 0701 AG operator review escalation outbound dispatch "
            "boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_escalation_outbound_dispatch_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
