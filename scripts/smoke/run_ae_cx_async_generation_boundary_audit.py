#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_cx_async_generation_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0991_s99_cx_async_generation_recovery_closure.md",
    "docs/slices/1001_s100_cx_mvp_integration_ae_handoff_closure.md",
    "docs/slices/1031_s103_ae_runtime_policy_orchestration_closure.md",
    "services/nex-cx/nex_cx/async_generation_operations.py",
    "services/nex-cx/nex_cx/generation_handoff.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
    "docs/development_process.md",
    "docs/slices/1032_ae_cx_async_generation_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s99_async_foundation",
        "docs/slices/0991_s99_cx_async_generation_recovery_closure.md",
        "existing `service_jobs` queue",
    ),
    EvidenceToken(
        "s100_handoff",
        "docs/slices/1001_s100_cx_mvp_integration_ae_handoff_closure.md",
        "`PENDING`, `BLOCKED`, and `READY`",
    ),
    EvidenceToken(
        "s103_policy_handoff",
        "docs/slices/1031_s103_ae_runtime_policy_orchestration_closure.md",
        "S104",
    ),
    EvidenceToken(
        "cx_admission_api",
        "services/nex-cx/nex_cx/async_generation_operations.py",
        "@app.post(\"/api/v1/generation-jobs\"",
    ),
    EvidenceToken(
        "cx_poll_api",
        "services/nex-cx/nex_cx/async_generation_operations.py",
        "@app.get(\"/api/v1/generation-jobs/{job_id}\"",
    ),
    EvidenceToken(
        "cx_handoff_api",
        "services/nex-cx/nex_cx/async_generation_operations.py",
        "@app.get(\"/api/v1/generation-jobs/{job_id}/handoff\"",
    ),
    EvidenceToken(
        "cx_cancel_api",
        "services/nex-cx/nex_cx/async_generation_operations.py",
        "@app.post(\"/api/v1/generation-jobs/{job_id}/cancel\"",
    ),
    EvidenceToken(
        "owner_safe_handoff",
        "services/nex-cx/nex_cx/generation_handoff.py",
        "owner_scope_enforced",
    ),
    EvidenceToken(
        "ae_sync_generation",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "client.create_generation(",
    ),
    EvidenceToken(
        "ae_projection_storage",
        "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
        "generation_summary",
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1032_ae_cx_async_generation_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "async_contract_missing": (
        "docs/slices/1033_ae_async_generation_contract.md"
    ),
    "cx_async_client_missing": (
        "docs/slices/1034_ae_cx_async_generation_client.md"
    ),
    "durable_admission_missing": (
        "docs/slices/1035_ae_async_chat_admission.md"
    ),
    "poll_refresh_api_missing": (
        "docs/slices/1036_ae_async_chat_polling_api.md"
    ),
    "cancel_retry_missing": (
        "docs/slices/1037_ae_async_chat_cancel_retry.md"
    ),
    "activity_observability_missing": (
        "docs/slices/1038_ae_async_chat_observability.md"
    ),
    "contract_openapi_missing": (
        "docs/slices/1039_ae_async_generation_contract_openapi.md"
    ),
    "postgres_evidence_missing": (
        "docs/slices/1040_ae_cx_async_generation_postgresql_smoke.md"
    ),
}

GAP_SLICES = {
    name: f"{1033 + index:04d}"
    for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_cx_async_generation_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in EVIDENCE_TOKENS
    ]
    gap_states = {
        name: "RESOLVED" if (root / path).is_file() else "OPEN"
        for name, path in GAP_RESOLUTION_PATHS.items()
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "cx_async_lifecycle_present": all(
            _group_present(tokens, group)
            for group in (
                "cx_admission_api",
                "cx_poll_api",
                "cx_handoff_api",
                "cx_cancel_api",
            )
        ),
        "cx_owner_safe_handoff_present": _group_present(
            tokens, "owner_safe_handoff"
        ),
        "ae_sync_path_confirmed": _group_present(tokens, "ae_sync_generation"),
        "ae_projection_storage_reusable": _group_present(
            tokens, "ae_projection_storage"
        ),
        "prior_requirement_handoffs_bound": all(
            _group_present(tokens, group)
            for group in (
                "s99_async_foundation",
                "s100_handoff",
                "s103_policy_handoff",
            )
        ),
        "tiered_quality_cadence_confirmed": _group_present(tokens, "tiered_gate"),
        "implementation_gaps_accounted_for": len(gap_states) == 8,
    }
    issues = [
        {"category": "path_missing", "path": item["path"]}
        for item in paths
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "source_token_missing",
            "path": item["path"],
            "group": item["group"],
        }
        for item in tokens
        if not item["present"]
    )
    passed = all(checks.values()) and not issues
    next_slice = next(
        (GAP_SLICES[name] for name, state in gap_states.items() if state == "OPEN"),
        "1041",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1032",
        "requirement": "S104",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "decision": boundary_decision(),
        "summary": {
            "foundation_count": 6,
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "known_drifts": [
            "ae_chat_generation_is_synchronous_only",
            "ae_has_no_cx_async_lifecycle_client",
            "ae_pending_record_has_no_job_projection",
            "ae_has_no_owner_scoped_poll_or_cancel_route",
            "ae_openapi_has_no_async_generation_surface",
        ],
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1032_boundary_audit",
            "1033_async_contract",
            "1034_cx_async_client",
            "1035_durable_async_admission",
            "1036_poll_refresh_api_checkpoint",
            "1037_cancel_retry_owner_scope",
            "1038_activity_observability",
            "1039_contract_openapi_hardening",
            "1040_actual_postgresql_smoke",
            "1041_s104_closure_full_gate",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def boundary_decision() -> dict[str, Any]:
    return {
        "owner": "nex-ae-api",
        "scope": "ae_to_cx_asynchronous_generation_integration",
        "selection_field": "generation.execution_strategy",
        "supported_execution_strategies": ["SYNCHRONOUS", "ASYNCHRONOUS"],
        "default_execution_strategy": "SYNCHRONOUS",
        "cx_lifecycle_owner": "nex-cx",
        "ae_interaction_owner": "nex-ae-api",
        "ae_persisted_projection": (
            "owner-safe job and handoff metadata in "
            "ae_chat_interactions.generation_summary"
        ),
        "raw_generation_content_persisted_by_ae": False,
        "polling_model": "explicit_owner_scoped_refresh",
        "background_poller_in_scope": False,
        "retry_model": "new_idempotent_admission_after_terminal_block",
        "synchronous_backward_compatibility": True,
        "new_tables_expected": 0,
        "actual_postgres_required_slice": "1040",
        "remote_provider_required": False,
        "quality_cadence": {
            "slice_gate": "1032-1041",
            "checkpoint_gate": "1036",
            "full_gate": "1041",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_cx_async_generation_boundary=fail "
            f"issues={len(result.get('issues', []))}"
        )
    summary = result["summary"]
    return (
        "ae_cx_async_generation_boundary=pass "
        f"foundations={summary['foundation_count']} gaps={summary['gap_count']} "
        f"open={summary['open_gap_count']} next={result['next_slice']} "
        f"issues={summary['issue_count']}"
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    return any(item["group"] == group and item["present"] for item in items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_cx_async_generation_boundary_audit()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
