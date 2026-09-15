#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_"
    "ack_suppression_state_boundary_audit.v1"
)

SLICE_ID = "0801"
S81_SURFACE = (
    "AG operator review escalation dispatch daemon liveness "
    "acknowledgement/suppression state"
)
BOUNDARY = (
    "ag_owned_operator_review_dispatch_daemon_liveness_ack_suppression_state"
)
ACK_STATE_TABLE = "ag_op_review_ack_state"
SOURCE_EVENT_TABLE = "service_operational_events"
SOURCE_HEARTBEAT_TABLE = "service_worker_heartbeats"
MAX_TABLE_NAME_LENGTH = 30
DEFAULT_SUPPRESSION_TTL_SECONDS = 1800
MAX_SUPPRESSION_TTL_SECONDS = 86400


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
        "s80_closure_script",
        "scripts/smoke/run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py",
        "S80 recovery foundation must be closed before persisted ack state.",
    ),
    RequiredPath(
        "s80_closure_doc",
        "docs/slices/0800_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.md",
        "S80 closure decision record.",
    ),
    RequiredPath(
        "s80_ack_policy_doc",
        "docs/slices/0796_ag_escalation_dispatch_daemon_liveness_ack_suppression_policy.md",
        "Read-only acknowledgement/suppression policy baseline.",
    ),
    RequiredPath(
        "s80_ack_state_decision_doc",
        "docs/slices/0798_ag_escalation_dispatch_daemon_liveness_recovery_privacy_runbook.md",
        "Future acknowledgement/suppression state table decision.",
    ),
    RequiredPath(
        "s70_persistence_doc",
        "docs/slices/0692_ag_operator_review_escalation_persistence.md",
        "Existing AG-owned safe operator action-state persistence pattern.",
    ),
    RequiredPath(
        "s70_closure_doc",
        "docs/slices/0700_s70_operator_review_escalation_action_closure.md",
        "Closed escalation action-loop persistence baseline.",
    ),
    RequiredPath(
        "ag_operations_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "AG operations recovery, dashboard, issue-candidate, and policy runtime.",
    ),
    RequiredPath(
        "ag_operator_review_cases_runtime",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "Existing safe operator action-state hashing/idempotency pattern.",
    ),
    RequiredPath(
        "operational_event_runtime",
        "services/_shared/nex_runtime/operational_events.py",
        "Shared safe operational event source for action history.",
    ),
    RequiredPath(
        "worker_heartbeat_runtime",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "Shared heartbeat source that remains the liveness source of truth.",
    ),
    RequiredPath(
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "Operations projection contract that exposes ack policy state.",
    ),
    RequiredPath(
        "openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "AG protected API contract surface.",
    ),
    RequiredPath(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "Default regression gate.",
    ),
    RequiredPath("docs_index", "docs/README.md", "Slice documentation index."),
    RequiredPath(
        "slice_doc",
        "docs/slices/0801_ag_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.md",
        "Slice 0801 implementation note.",
    ),
)


TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s80_closed_baseline",
        "scripts/smoke/run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py",
        "s80_closure_schema",
        "s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.v1",
        "S81 starts only after S80 recovery foundation is closed.",
    ),
    TokenRequirement(
        "s80_closed_baseline",
        "scripts/smoke/run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py",
        "s80_future_ack_state_table",
        '"future_table_candidate": "ag_op_review_ack_state"',
        "S80 already reserved the short ack-state table candidate.",
    ),
    TokenRequirement(
        "s80_closed_baseline",
        "scripts/smoke/run_s80_operator_review_escalation_dispatch_daemon_liveness_recovery_closure.py",
        "s80_no_ack_state_table",
        '"new_tables_in_s80": []',
        "S81 picks up the deferred persistence work.",
    ),
    TokenRequirement(
        "s80_decision_docs",
        "docs/slices/0798_ag_escalation_dispatch_daemon_liveness_recovery_privacy_runbook.md",
        "future_table_doc",
        "future candidate table name: `ag_op_review_ack_state`",
        "The future state table name is documented before persistence work.",
    ),
    TokenRequirement(
        "s80_decision_docs",
        "docs/slices/0798_ag_escalation_dispatch_daemon_liveness_recovery_privacy_runbook.md",
        "non_persistent_doc",
        "current state remains non-persistent",
        "S80 intentionally did not persist ack/suppression state.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "ack_policy_builder",
        "def build_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_policy",
        "S81 must extend the existing policy shape, not invent a parallel one.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "ack_and_suppress_actions",
        '"acknowledge_once", "suppress_for_ttl"',
        "Actionable missing/stale liveness states support ack and TTL suppression.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "source_attention_actions",
        '"acknowledge_source_attention",',
        "Source-attention states use dedicated acknowledgement actions.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "default_ttl",
        '"default_suppression_ttl_seconds": 1800',
        "S81 must carry forward the default suppression TTL.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "max_ttl",
        '"max_suppression_ttl_seconds": 86400',
        "S81 must carry forward the maximum suppression TTL.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "no_projection_suppression",
        '"does_not_suppress_current_projection": True',
        "Persisted state must not hide the source liveness projection.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "operator_identity_required",
        '"operator_identity_required": True',
        "Mutating ack/suppression actions require an operator identity.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "reason_required",
        '"reason_required": True',
        "Mutating ack/suppression actions require bounded reason codes.",
    ),
    TokenRequirement(
        "ack_policy_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "raw_comment_forbidden",
        '"raw_comment_included": False',
        "Raw operator comments must never be stored or exposed.",
    ),
    TokenRequirement(
        "issue_candidate_overlay",
        "services/nex-ag/nex_ag/operations.py",
        "issue_candidate_policy_helper",
        "def _operator_review_dispatch_daemon_liveness_ack_suppression_policy_for_signal",
        "Issue-candidate signals already carry ack/suppression policy context.",
    ),
    TokenRequirement(
        "issue_candidate_overlay",
        "services/nex-ag/nex_ag/operations.py",
        "issue_candidate_signal_policy",
        '"acknowledgement_suppression_policy": ack_suppression_policy',
        "S81 state overlays should flow through the existing signal policy field.",
    ),
    TokenRequirement(
        "s70_safe_state_pattern",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "comment_hash",
        '"comment_hash"',
        "S81 should store hashes/previews instead of raw comments.",
    ),
    TokenRequirement(
        "s70_safe_state_pattern",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "comment_preview",
        '"comment_preview"',
        "S81 can store bounded previews for operator usability.",
    ),
    TokenRequirement(
        "s70_safe_state_pattern",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "idempotency_hash",
        '"idempotency_key_hash"',
        "S81 idempotency should store only hashes.",
    ),
    TokenRequirement(
        "s70_safe_state_pattern",
        "services/nex-ag/nex_ag/operator_review_cases.py",
        "action_state_storage",
        '"action_state_storage": "ag_owned_escalation_state_only"',
        "S81 follows the existing AG-owned action-state-only storage pattern.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "operations_ack_policy_schema",
        '"acknowledgement_suppression_policy"',
        "Operations projection already includes the ack/suppression policy envelope.",
    ),
    TokenRequirement(
        "contracts_baseline",
        "contracts/openapi/nex-ag.openapi.yaml",
        "openapi_ack_policy_schema",
        "acknowledgement_suppression_policy",
        "OpenAPI already exposes the recovery-plan ack policy envelope.",
    ),
    TokenRequirement(
        "quality_gate",
        "scripts/quality/run_quality_gate.sh",
        "s81_boundary_quality_gate",
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.py",
        "Slice 0801 boundary audit must run in the default quality gate.",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "slice_0801_indexed",
        "0801_ag_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.md",
        "Slice 0801 documentation must be indexed.",
    ),
)


TABLE_NAMES_UNDER_REVIEW = (
    ACK_STATE_TABLE,
    SOURCE_EVENT_TABLE,
    SOURCE_HEARTBEAT_TABLE,
)

FORBIDDEN_STORAGE_FIELDS = (
    "raw_comment",
    "raw_operator_comment",
    "raw_provider_payload",
    "raw_provider_error",
    "raw_notification_payload",
    "raw_external_incident_payload",
    "raw_heartbeat_payload",
    "database_url",
    "service_token",
    "provider_token",
    "storage_path",
    "raw_idempotency_key",
)

NEXT_SLICES = (
    "Slice_0802",
    "Slice_0803",
    "Slice_0804",
    "Slice_0805",
    "Slice_0806",
    "Slice_0807",
    "Slice_0808",
    "Slice_0809",
    "Slice_0810",
)


def run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = _required_path_results(root)
    tokens = _token_results(root)
    table_names = _table_name_results()
    storage_fields = _storage_field_results()
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "table_names_within_limit": all(item["within_limit"] for item in table_names),
        "storage_fields_redacted": all(
            item["boundary_safe"] for item in storage_fields
        ),
        "s80_closed_baseline_present": _group_present(tokens, "s80_closed_baseline"),
        "s80_decision_docs_present": _group_present(tokens, "s80_decision_docs"),
        "ack_policy_runtime_present": _group_present(tokens, "ack_policy_runtime"),
        "issue_candidate_overlay_present": _group_present(
            tokens,
            "issue_candidate_overlay",
        ),
        "s70_safe_state_pattern_present": _group_present(
            tokens,
            "s70_safe_state_pattern",
        ),
        "contracts_baseline_present": _group_present(tokens, "contracts_baseline"),
        "quality_gate_present": _group_present(tokens, "quality_gate"),
        "docs_index_present": _group_present(tokens, "docs_index"),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else (
            "ag_operator_review_escalation_dispatch_daemon_liveness_"
            "ack_suppression_state_boundary_failed"
        ),
        "slice": SLICE_ID,
        "surface": S81_SURFACE,
        "boundary": {
            "boundary": BOUNDARY,
            "owner_service": "nex-ag",
            "state_table_candidate": ACK_STATE_TABLE,
            "source_event_table": SOURCE_EVENT_TABLE,
            "source_heartbeat_table": SOURCE_HEARTBEAT_TABLE,
            "new_table_in_slice_0801": False,
            "state_mutation_route_in_slice_0801": False,
            "current_liveness_projection_suppressed": False,
            "first_persistence_slice": "Slice_0802",
            "first_state_machine_slice": "Slice_0803",
            "first_protected_action_api_slice": "Slice_0804",
            "first_persisted_read_model_slice": "Slice_0805",
            "first_dashboard_issue_overlay_slice": "Slice_0806",
            "contract_openapi_slice": "Slice_0807",
            "postgres_smoke_slice": "Slice_0808",
            "privacy_runbook_slice": "Slice_0809",
            "closure_slice": "Slice_0810",
        },
        "state_contract": {
            "state_key": "acknowledgement_key",
            "supported_actions": [
                "acknowledge_once",
                "suppress_for_ttl",
                "acknowledge_source_attention",
                "suppress_source_attention_for_ttl",
            ],
            "state_statuses": [
                "ACKNOWLEDGED",
                "SUPPRESSED",
                "EXPIRED",
                "CLEARED",
            ],
            "default_suppression_ttl_seconds": DEFAULT_SUPPRESSION_TTL_SECONDS,
            "max_suppression_ttl_seconds": MAX_SUPPRESSION_TTL_SECONDS,
            "idempotency_storage": "sha256_hash_only",
            "operator_comment_storage": "sha256_hash_and_bounded_preview_only",
            "operator_identity_required": True,
            "reason_codes_required": True,
            "expires_at_required_for_ttl_suppression": True,
            "state_overlay_target": "dashboard_issue_candidate_recovery_plan_only",
        },
        "storage_decision": {
            "allowed_fields": [
                "ack_state_id",
                "acknowledgement_key",
                "service_id",
                "worker_id",
                "worker_type",
                "liveness_status",
                "action",
                "state_status",
                "operator_ref",
                "reason_codes",
                "comment_hash",
                "comment_preview",
                "idempotency_key_hash",
                "requested_ttl_seconds",
                "suppressed_until",
                "created_at",
                "updated_at",
                "cleared_at",
                "metadata",
            ],
            "forbidden_fields": list(FORBIDDEN_STORAGE_FIELDS),
            "source_of_truth_not_modified": [
                SOURCE_HEARTBEAT_TABLE,
                SOURCE_EVENT_TABLE,
            ],
            "history_source": SOURCE_EVENT_TABLE,
        },
        "separation_of_concerns": {
            "liveness_status": "continues_to_be_derived_from_service_worker_heartbeats",
            "ack_suppression_state": "operator_overlay_state_owned_by_nex_ag",
            "issue_candidate": "may_be_marked_acknowledged_or_suppressed_without_hiding_liveness",
            "recovery_plan": "may_include_operator_state_overlay_but_remains_read_only",
            "process_control": "not_invoked_by_ack_or_suppression_actions",
            "audit_events": "safe_summary_only_for_action_history",
        },
        "refactoring_checkpoint": {
            "reuse_s80_ack_policy_shape": True,
            "reuse_s70_safe_comment_hash_preview_pattern": True,
            "reuse_s70_idempotency_hash_pattern": True,
            "keep_route_handlers_thin": True,
            "keep_state_store_behind_interface": True,
            "keep_postgres_smoke_real_test_db": True,
            "keep_sensitive_values_redacted": True,
            "defer_retention_cleanup_to_s89": True,
        },
        "checks": checks,
        "paths": paths,
        "source_tokens": tokens,
        "table_names": table_names,
        "storage_fields": storage_fields,
        "issues": _issues(paths, tokens, table_names, storage_fields),
        "next_slices": list(NEXT_SLICES),
    }


def _required_path_results(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "path": item.relative_path,
            "purpose": item.purpose,
            "present": (root / item.relative_path).is_file(),
        }
        for item in REQUIRED_PATHS
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in TOKEN_REQUIREMENTS:
        path = root / item.relative_path
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        results.append(
            {
                "group": item.group,
                "token_id": item.token_id,
                "path": item.relative_path,
                "purpose": item.purpose,
                "present": item.token in text,
            }
        )
    return results


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


def _storage_field_results() -> list[dict[str, Any]]:
    allowed_fields = {
        "ack_state_id",
        "acknowledgement_key",
        "service_id",
        "worker_id",
        "worker_type",
        "liveness_status",
        "action",
        "state_status",
        "operator_ref",
        "reason_codes",
        "comment_hash",
        "comment_preview",
        "idempotency_key_hash",
        "requested_ttl_seconds",
        "suppressed_until",
        "created_at",
        "updated_at",
        "cleared_at",
        "metadata",
    }
    results = [
        {"field": field, "classification": "allowed", "allowed": True}
        for field in sorted(allowed_fields)
    ]
    results.extend(
        {"field": field, "classification": "forbidden", "allowed": False}
        for field in FORBIDDEN_STORAGE_FIELDS
    )
    return [
        {
            **item,
            "boundary_safe": item["allowed"] or item["classification"] == "forbidden",
        }
        for item in results
    ]


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    grouped = [item for item in tokens if item["group"] == group]
    return bool(grouped) and all(item["present"] for item in grouped)


def _issues(
    paths: list[dict[str, Any]],
    tokens: list[dict[str, Any]],
    table_names: list[dict[str, Any]],
    storage_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(
        {
            "category": "path_missing",
            "name": item["name"],
            "path": item["path"],
        }
        for item in paths
        if not item["present"]
    )
    issues.extend(
        {
            "category": "source_token_missing",
            "group": item["group"],
            "token_id": item["token_id"],
            "path": item["path"],
        }
        for item in tokens
        if not item["present"]
    )
    issues.extend(
        {
            "category": "table_name_too_long",
            "table_name": item["table_name"],
            "length": item["length"],
            "max_length": item["max_length"],
        }
        for item in table_names
        if not item["within_limit"]
    )
    issues.extend(
        {
            "category": "forbidden_storage_field_marked_allowed",
            "field": item["field"],
        }
        for item in storage_fields
        if item["classification"] == "forbidden" and item["allowed"]
    )
    return issues


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        boundary = evidence["boundary"]
        contract = evidence["state_contract"]
        return (
            "ag_operator_review_escalation_dispatch_daemon_"
            "liveness_ack_suppression_state_boundary=pass "
            f"boundary={boundary['boundary']} "
            f"table={boundary['state_table_candidate']} "
            f"new_table={boundary['new_table_in_slice_0801']} "
            f"projection_suppressed={boundary['current_liveness_projection_suppressed']} "
            f"default_ttl={contract['default_suppression_ttl_seconds']} "
            f"next={boundary['first_persistence_slice']}"
        )
    return (
        "ag_operator_review_escalation_dispatch_daemon_"
        "liveness_ack_suppression_state_boundary=fail "
        f"reason={evidence.get('failure_code')} "
        f"issues={len(evidence.get('issues', []))}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the S81 AG operator review escalation dispatch daemon liveness "
            "acknowledgement/suppression state boundary audit."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit()
    )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, default=str)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
