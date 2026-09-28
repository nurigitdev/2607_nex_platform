#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_generation_lifecycle_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1041_s104_ae_cx_async_generation_closure.md",
    "services/nex-ae-api/nex_ae_api/async_generation.py",
    "services/nex-ae-api/nex_ae_api/cx_async_generation_client.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/nex-cx/nex_cx/async_generation_operations.py",
    "services/nex-cx/nex_cx/progress.py",
    "database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql",
    "docs/development_process.md",
    "docs/slices/1042_ae_generation_lifecycle_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s104_closure",
        "scripts/smoke/run_s104_ae_cx_async_generation_closure.py",
        '"READY_FOR_S105"',
    ),
    EvidenceToken(
        "ae_async_projection",
        "services/nex-ae-api/nex_ae_api/async_generation.py",
        "def refresh_async_generation_projection(",
    ),
    EvidenceToken(
        "ae_cx_job_poll",
        "services/nex-ae-api/nex_ae_api/cx_async_generation_client.py",
        "def get_job(",
    ),
    EvidenceToken(
        "ae_refresh_route",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/refresh"',
    ),
    EvidenceToken(
        "ae_cancel_route",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/cancel"',
    ),
    EvidenceToken(
        "ae_retry_route",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/retry"',
    ),
    EvidenceToken(
        "cx_owner_job_api",
        "services/nex-cx/nex_cx/async_generation_operations.py",
        '@app.get("/api/v1/generation-jobs/{job_id}"',
    ),
    EvidenceToken(
        "canonical_progress_contract",
        "services/nex-cx/nex_cx/progress.py",
        '"generation_progress_event.v1"',
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
        "1042_ae_generation_lifecycle_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "progress_contract_missing": (
        "docs/slices/1043_ae_generation_progress_contract.md"
    ),
    "lifecycle_orchestration_missing": (
        "docs/slices/1044_ae_generation_lifecycle_orchestration.md"
    ),
    "progress_api_missing": (
        "docs/slices/1045_ae_generation_progress_api.md"
    ),
    "cancel_race_convergence_missing": (
        "docs/slices/1046_ae_generation_cancellation_convergence.md"
    ),
    "recovery_orchestration_missing": (
        "docs/slices/1047_ae_generation_recovery_orchestration.md"
    ),
    "lifecycle_observability_missing": (
        "docs/slices/1048_ae_generation_lifecycle_observability.md"
    ),
    "contract_openapi_missing": (
        "docs/slices/1049_ae_generation_lifecycle_contract_openapi.md"
    ),
    "postgres_evidence_missing": (
        "docs/slices/1050_ae_generation_lifecycle_postgresql_smoke.md"
    ),
}

GAP_SLICES = {
    name: f"{1043 + index:04d}"
    for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_generation_lifecycle_boundary_audit(
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
        "s104_handoff_bound": _group_present(tokens, "s104_closure"),
        "ae_async_projection_reusable": _group_present(
            tokens, "ae_async_projection"
        ),
        "ae_owner_lifecycle_routes_present": all(
            _group_present(tokens, group)
            for group in (
                "ae_refresh_route",
                "ae_cancel_route",
                "ae_retry_route",
            )
        ),
        "cx_job_polling_present": all(
            _group_present(tokens, group)
            for group in ("ae_cx_job_poll", "cx_owner_job_api")
        ),
        "canonical_progress_contract_present": _group_present(
            tokens, "canonical_progress_contract"
        ),
        "ae_projection_storage_reusable": _group_present(
            tokens, "ae_projection_storage"
        ),
        "tiered_quality_cadence_confirmed": _group_present(
            tokens, "tiered_gate"
        ),
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
        "1051",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1042",
        "requirement": "S105",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "decision": boundary_decision(),
        "summary": {
            "foundation_count": 7,
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "known_drifts": [
            "ae_has_no_dedicated_progress_projection",
            "ae_has_no_owner_scoped_progress_route",
            "refresh_is_handoff_oriented_not_progress_oriented",
            "cancel_does_not_reconcile_terminal_races",
            "retry_has_no_read_only_recovery_plan",
            "progress_contract_is_not_exposed_by_ae",
            "lifecycle_observability_has_no_progress_stage",
        ],
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1042_boundary_audit",
            "1043_progress_projection_contract",
            "1044_lifecycle_orchestration",
            "1045_owner_scoped_progress_api",
            "1046_cancellation_race_convergence_checkpoint",
            "1047_recovery_plan_and_retry_orchestration",
            "1048_lifecycle_observability",
            "1049_contract_openapi_hardening",
            "1050_actual_postgresql_smoke",
            "1051_s105_closure_full_gate",
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
        "scope": "ae_generation_progress_cancellation_recovery_orchestration",
        "cx_lifecycle_owner": "nex-cx",
        "ae_interaction_owner": "nex-ae-api",
        "progress_source": "cx_durable_job_and_handoff",
        "progress_model": "explicit_owner_scoped_polling_snapshot",
        "background_poller_in_scope": False,
        "terminal_state_precedence": True,
        "cancellation_model": "delegate_to_cx_then_reconcile",
        "recovery_model": "read_only_plan_then_new_child_admission",
        "ae_persisted_projection": (
            "privacy-safe lifecycle metadata in "
            "ae_chat_interactions.generation_summary"
        ),
        "raw_generation_content_in_progress": False,
        "raw_failure_detail_in_progress": False,
        "synchronous_backward_compatibility": True,
        "new_tables_expected": 0,
        "actual_postgres_required_slice": "1050",
        "remote_provider_required": False,
        "quality_cadence": {
            "slice_gate": "1042-1051",
            "checkpoint_gate": "1046",
            "full_gate": "1051",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_generation_lifecycle_boundary=fail "
            f"issues={len(result.get('issues', []))}"
        )
    summary = result["summary"]
    return (
        "ae_generation_lifecycle_boundary=pass "
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
    result = run_ae_generation_lifecycle_boundary_audit()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
