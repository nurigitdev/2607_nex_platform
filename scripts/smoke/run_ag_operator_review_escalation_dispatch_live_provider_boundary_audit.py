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
    "ag_operator_review_escalation_dispatch_live_provider_boundary_audit.v1"
)

SLICE_ID = "0721"
S73_SURFACE = "AG operator review escalation dispatch live-provider readiness"
LIVE_PROVIDER_BOUNDARY = "ag_owned_operator_review_escalation_dispatch_live_provider"
CASE_TABLE = "ag_op_cases"
ESCALATION_TABLE = "ag_op_escalations"
DISPATCH_TABLE = "ag_op_esc_dispatches"
OPERATIONAL_EVENT_TABLE = "service_operational_events"
MAX_TABLE_NAME_LENGTH = 30
NEXT_SLICE = "Slice_0722"

PROTECTED_ENV_KEYS = (
    "NEX_AG_DATABASE_URL",
    "NEX_AG_TEST_DATABASE_URL",
    "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE",
    "NEX_AG_DISPATCH_EXECUTION_PROVIDER_PROFILE",
    "NEX_AG_DISPATCH_LIVE_PROVIDER_MODE",
    "NEX_AG_DISPATCH_LIVE_PROVIDER_PROFILE",
    "NEX_AG_DISPATCH_HTTP_TIMEOUT_SECONDS",
    "NEX_AG_DISPATCH_HTTP_CONNECT_TIMEOUT_SECONDS",
    "NEX_AG_DISPATCH_HTTP_READ_TIMEOUT_SECONDS",
    "NEX_AG_DISPATCH_HTTP_MAX_RETRIES",
    "NEX_AG_DISPATCH_HTTP_BACKOFF_SECONDS",
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
        "s72_closure_script",
        "scripts/smoke/run_s72_operator_review_escalation_dispatch_execution_closure.py",
        "S72 must be closed before live-provider readiness work begins.",
    ),
    RequiredPath(
        "s72_closure_doc",
        "docs/slices/0720_s72_operator_review_escalation_dispatch_execution_closure.md",
        "Closed S72 evidence and deferred-live boundary.",
    ),
    RequiredPath(
        "s72_postgres_smoke",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py",
        "Protected nex_ag_test dispatch execution evidence.",
    ),
    RequiredPath(
        "dispatch_execution_runtime",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "Dispatch execution provider/result/runtime contract.",
    ),
    RequiredPath(
        "operator_review_cases",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "AG-owned dispatch outbox and state machine.",
    ),
    RequiredPath(
        "ag_operations",
        "services/nex-ag/nex_ag/operations.py",
        "AG dashboard and issue-candidate projection surface.",
    ),
    RequiredPath(
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "Operations dashboard contract surface.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath(
        "live_provider_boundary_script",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py",
        "Slice 0721 live-provider boundary audit.",
    ),
    RequiredPath(
        "live_provider_boundary_tests",
        "tests/test_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py",
        "Slice 0721 boundary regression.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath("ag_readme", "services/nex-ag/README.md", "AG implementation notes."),
    RequiredPath(
        "slice_doc",
        "docs/slices/0721_ag_escalation_dispatch_live_provider_boundary_audit.md",
        "Slice 0721 implementation note.",
    ),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "s72_closed_baseline",
        "scripts/smoke/run_s72_operator_review_escalation_dispatch_execution_closure.py",
        "s72_closure_schema",
        "s72_operator_review_escalation_dispatch_execution_closure.v1",
        "Live-provider readiness starts after S72 closure.",
    ),
    TokenRequirement(
        "s72_closed_baseline",
        "scripts/smoke/run_s72_operator_review_escalation_dispatch_execution_closure.py",
        "s72_live_notification_deferred",
        '"live_notification_delivery": "deferred"',
        "S73 must explicitly move live notification delivery out of deferred state.",
    ),
    TokenRequirement(
        "s72_closed_baseline",
        "scripts/smoke/run_s72_operator_review_escalation_dispatch_execution_closure.py",
        "s72_external_incident_deferred",
        '"external_incident_sync": "deferred"',
        "S73 must explicitly move external incident sync out of deferred state.",
    ),
    TokenRequirement(
        "execution_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "provider_catalog_schema",
        "ag_operator_review_escalation_dispatch_execution_provider_catalog.v1",
        "Provider registry must keep a versioned catalog.",
    ),
    TokenRequirement(
        "execution_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "provider_mode_mock_first",
        'DISPATCH_EXECUTION_PROVIDER_MODE = "mock_first_only"',
        "Live-provider work starts from the current mock-first baseline.",
    ),
    TokenRequirement(
        "execution_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "provider_profiles",
        "DISPATCH_EXECUTION_PROVIDER_PROFILES",
        "Live-provider profiles should extend the existing provider registry.",
    ),
    TokenRequirement(
        "execution_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "forbidden_result_keys",
        "FORBIDDEN_DISPATCH_EXECUTION_RESULT_KEYS",
        "Live-provider results must keep raw payloads and secrets forbidden.",
    ),
    TokenRequirement(
        "execution_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "sensitive_value_patterns",
        "SENSITIVE_DISPATCH_EXECUTION_VALUE_PATTERNS",
        "Live-provider evidence must keep sensitive value scanning.",
    ),
    TokenRequirement(
        "execution_runtime_baseline",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "run_once_worker",
        "def run_dispatch_execution_worker_once",
        "Live-provider routing must stay behind the bounded run-once worker first.",
    ),
    TokenRequirement(
        "dispatch_outbox_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "dispatch_table",
        'AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_TABLE = "ag_op_esc_dispatches"',
        "Live-provider execution must keep AG dispatch outbox as source of record.",
    ),
    TokenRequirement(
        "dispatch_outbox_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "allowed_channels",
        "ALLOWED_ESCALATION_DISPATCH_CHANNELS",
        "Live provider routing maps from existing dispatch channel types.",
    ),
    TokenRequirement(
        "dispatch_outbox_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "notification_channel",
        '"NOTIFICATION"',
        "Notification provider routing must use an existing channel type.",
    ),
    TokenRequirement(
        "dispatch_outbox_baseline",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "incident_channel",
        '"INCIDENT"',
        "External incident provider routing must use an existing channel type.",
    ),
    TokenRequirement(
        "operations_visibility_baseline",
        "services/nex-ag/nex_ag/operations.py",
        "dashboard_execution_summary",
        "execution_summary",
        "Live-provider results must remain visible through AG operations.",
    ),
    TokenRequirement(
        "operations_visibility_baseline",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "operations_contract_execution_summary",
        "execution_summary",
        "Operations contract must allow dispatch execution summaries.",
    ),
    TokenRequirement(
        "postgres_smoke_baseline",
        "scripts/smoke/run_ag_operator_review_escalation_dispatch_execution_postgres_smoke.py",
        "protected_smoke_env",
        "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_EXECUTION_POSTGRES_SMOKE",
        "Live-provider work must preserve protected PostgreSQL smoke evidence.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s72_closure_quality_gate",
        "run_s72_operator_review_escalation_dispatch_execution_closure.py",
        "S72 closure remains in the default quality gate.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s73_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py",
        "Slice 0721 audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "s73_docs",
        "docs/README.md",
        "doc_index_0721",
        "0721_ag_escalation_dispatch_live_provider_boundary_audit.md",
        "Slice 0721 must be indexed.",
    ),
    TokenRequirement(
        "s73_docs",
        "services/nex-ag/README.md",
        "ag_s73_readme_note",
        "Slice 0721 starts S73",
        "AG README must record the live-provider boundary.",
    ),
)

PLANNED_SLICES = (
    (
        "provider_profile_config_registry_hardening",
        "Slice_0722",
        "Normalize live-provider mode/profile/env/secret timeout settings.",
    ),
    (
        "notification_provider_contract_and_mock_http_adapter",
        "Slice_0723",
        "Define notification provider request/result shape with mock HTTP transport.",
    ),
    (
        "external_incident_provider_contract_and_mock_http_adapter",
        "Slice_0724",
        "Define external incident provider request/result shape with mock HTTP transport.",
    ),
    (
        "dispatch_provider_http_client_foundation",
        "Slice_0725",
        "Add redaction-aware HTTP client timeout/retry/idempotency behavior.",
    ),
    (
        "execution_worker_provider_routing_integration",
        "Slice_0726",
        "Route worker execution through mock, notification, and incident adapters.",
    ),
    (
        "provider_result_diagnostics_dashboard",
        "Slice_0727",
        "Surface provider timeout/failure/retry summaries in AG operations.",
    ),
    (
        "live_provider_privacy_regression_pack",
        "Slice_0728",
        "Prove tokens, webhook URLs, raw payloads, and idempotency keys stay redacted.",
    ),
    (
        "dispatch_provider_postgresql_smoke",
        "Slice_0729",
        "Prove provider routing and safe result persistence against nex_ag_test.",
    ),
    (
        "s73_dispatch_provider_readiness_closure",
        "Slice_0730",
        "Close provider readiness before any real outbound network activation.",
    ),
)

TABLE_NAMES_UNDER_REVIEW = (
    CASE_TABLE,
    ESCALATION_TABLE,
    DISPATCH_TABLE,
    OPERATIONAL_EVENT_TABLE,
)


def run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit(
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
        "s72_closed_baseline_present": token_groups.get("s72_closed_baseline", False),
        "execution_runtime_baseline_present": token_groups.get(
            "execution_runtime_baseline", False
        ),
        "dispatch_outbox_baseline_present": token_groups.get(
            "dispatch_outbox_baseline", False
        ),
        "operations_visibility_baseline_present": token_groups.get(
            "operations_visibility_baseline", False
        ),
        "postgres_smoke_baseline_present": token_groups.get(
            "postgres_smoke_baseline", False
        ),
        "quality_gate_present": token_groups.get("quality_gate", False),
        "s73_docs_present": token_groups.get("s73_docs", False),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "slice": SLICE_ID,
        "surface": S73_SURFACE,
        "live_provider_boundary": _live_provider_boundary(),
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
            "ag_operator_review_escalation_dispatch_live_provider_boundary_failed"
        )
        evidence["issues"] = _issues(paths, tokens, table_names)
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), environment)
    return evidence


def _live_provider_boundary() -> dict[str, Any]:
    return {
        "system_of_record": "nex-ag",
        "provider_owner": "nex-ag",
        "boundary": LIVE_PROVIDER_BOUNDARY,
        "create_table_in_slice_0721": False,
        "first_provider_config_slice": NEXT_SLICE,
        "source_dispatch_table": DISPATCH_TABLE,
        "event_source_table": OPERATIONAL_EVENT_TABLE,
        "source_tables": [
            {"table_name": CASE_TABLE, "role": "case_state_reference"},
            {"table_name": ESCALATION_TABLE, "role": "escalation_state_reference"},
            {"table_name": DISPATCH_TABLE, "role": "dispatch_outbox_source_of_record"},
            {
                "table_name": OPERATIONAL_EVENT_TABLE,
                "role": "safe_provider_attempt_history",
            },
        ],
        "planned_owned_tables": [],
        "live_network_calls_in_slice_0721": False,
        "live_network_calls_before_protected_smoke": False,
        "provider_execution_mode_in_0721": "mock_first_boundary_only",
        "external_network_delivery_in_0721": False,
        "notification_delivery_activation": "deferred_until_explicit_live_slice",
        "external_incident_sync_activation": "deferred_until_explicit_live_slice",
        "prepared_channel_types": ["NOTIFICATION", "EMAIL", "WEBHOOK", "INCIDENT"],
        "existing_mock_channel_type": "MOCK",
        "provider_categories": [
            "notification_webhook",
            "email_notification",
            "external_incident",
        ],
        "required_provider_controls": [
            "explicit_provider_mode",
            "profile_allowlist",
            "timeout_seconds",
            "retry_budget",
            "idempotency_key_hashing",
            "secret_redaction",
            "safe_result_hash",
            "safe_result_preview",
            "protected_postgresql_smoke",
        ],
        "allowed_worker_actions": ["START", "SUCCEED", "FAIL", "RETRY", "CANCEL"],
        "result_storage": "safe_hashes_statuses_counters_only",
        "raw_provider_payload_storage_allowed": False,
        "raw_provider_error_storage_allowed": False,
        "webhook_url_in_evidence_allowed": False,
        "provider_token_in_evidence_allowed": False,
        "ag_may_mutate_source_service_records": False,
        "cross_service_database_write_allowed": False,
    }


def _refactoring_checkpoint() -> dict[str, bool]:
    return {
        "reuse_s72_worker_and_result_contracts": True,
        "keep_provider_config_separate_from_worker_state_machine": True,
        "start_with_mock_http_transports_before_live_network": True,
        "require_explicit_opt_in_for_live_provider_smoke": True,
        "route_all_state_changes_through_dispatch_action_state_machine": True,
        "persist_only_safe_provider_hashes_statuses_and_previews": True,
        "keep_raw_provider_payloads_out_of_db_logs_and_evidence": True,
        "require_timeout_retry_and_idempotency_controls": True,
        "keep_live_notification_delivery_deferred_in_0721": True,
        "keep_live_external_incident_sync_deferred_in_0721": True,
        "avoid_new_tables_until_provider_result_needs_are_proven": True,
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
        r"https?://[^*\s]+/(?:hook|api)/[^*\s]+",
        r"Bearer\s+[A-Za-z0-9._~+/=@-]+",
        r"ed6@c496em",
        r"nuri1004",
        r"/data/nex-platform",
        r"idempotency[_-]?key\s*[:=]\s*[A-Za-z0-9._~+/=@-]+",
        r"raw_provider_payload\s*[:=]\s*\{",
        r"raw_provider_error\s*[:=]\s*['\"]",
        r"raw_notification_payload\s*[:=]\s*\{",
        r"raw_external_incident_payload\s*[:=]\s*\{",
        r"provider_api_key\s*[:=]\s*['\"]",
        r"notification_secret\s*[:=]\s*['\"]",
        r"external_incident_token\s*[:=]\s*['\"]",
        r"service_token\s*[:=]\s*['\"]",
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
            "ag_operator_review_escalation_dispatch_live_provider_boundary_audit=fail "
            f"failed_checks={','.join(failed) or 'unknown'}"
        )
    boundary = evidence.get("live_provider_boundary")
    table_results = evidence.get("table_name_results")
    grouped = _grouped_token_status(evidence.get("source_tokens"))
    return (
        "ag_operator_review_escalation_dispatch_live_provider_boundary_audit=pass "
        f"paths={_present_count(evidence.get('paths'))}/{len(REQUIRED_PATHS)} "
        f"tokens={_present_count(evidence.get('source_tokens'))}/{len(REQUIRED_SOURCE_TOKENS)} "
        f"token_groups={sum(1 for value in grouped.values() if value)}/{len(grouped)} "
        f"tables={sum(1 for item in table_results or [] if item.get('within_limit'))}/{len(table_results or [])} "
        f"boundary={boundary.get('boundary') if isinstance(boundary, Mapping) else LIVE_PROVIDER_BOUNDARY} "
        f"dispatch_table={DISPATCH_TABLE} "
        "provider=live_readiness_only "
        "network=deferred "
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
            "Run the Slice 0721 AG operator review escalation dispatch "
            "live-provider boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print one-line summary.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    args = parser.parse_args(argv)

    evidence = run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit()
    if args.output:
        write_audit_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
