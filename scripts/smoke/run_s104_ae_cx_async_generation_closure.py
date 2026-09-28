#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "quality"))

from run_ae_cx_async_generation_boundary_audit import (  # noqa: E402
    run_ae_cx_async_generation_boundary_audit as run_boundary,
)
from run_ae_cx_async_generation_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    run_ae_cx_async_generation_postgres_smoke as run_postgres,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s104_ae_cx_async_generation_closure.v1"
SLICE_RANGE = "1032-1041"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/async_generation.py",
    "services/nex-ae-api/nex_ae_api/cx_async_generation_client.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/nex-ae-api/nex_ae_api/workspace_chat_observability.py",
    "services/nex-ae-api/nex_ae_api/workspace_chat_orchestration.py",
    "contracts/schemas/service/nex_ae_api/async_generation.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/async_chat_refresh.v1.schema.json",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "scripts/smoke/run_ae_cx_async_generation_postgres_smoke.py",
    "scripts/smoke/run_s104_ae_cx_async_generation_closure.py",
    "tests/test_s104_ae_cx_async_generation_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1032", "ae_cx_async_generation_boundary_audit"),
            ("1033", "ae_async_generation_contract"),
            ("1034", "ae_cx_async_generation_client"),
            ("1035", "ae_async_chat_admission"),
            ("1036", "ae_async_chat_polling_api"),
            ("1037", "ae_async_chat_cancel_retry"),
            ("1038", "ae_async_chat_observability"),
            ("1039", "ae_async_chat_contract_openapi"),
            ("1040", "ae_cx_async_generation_postgresql_smoke"),
            ("1041", "s104_ae_cx_async_generation_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "execution_strategy_contract",
        "services/nex-ae-api/nex_ae_api/async_generation.py",
        'ASYNCHRONOUS = "ASYNCHRONOUS"',
    ),
    (
        "strict_async_projection",
        "services/nex-ae-api/nex_ae_api/async_generation.py",
        "def validate_async_generation_projection(",
    ),
    (
        "cx_lifecycle_client",
        "services/nex-ae-api/nex_ae_api/cx_async_generation_client.py",
        "class HttpCxAsyncGenerationClient",
    ),
    (
        "durable_async_admission",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "build_async_admitted_chat_interaction_record(",
    ),
    (
        "explicit_owner_refresh",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/refresh"',
    ),
    (
        "cancel_and_retry",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/retry"',
    ),
    (
        "metadata_observability_v3",
        "services/nex-ae-api/nex_ae_api/workspace_chat_observability.py",
        '"ae_workspace_chat_observability.v3"',
    ),
    (
        "workspace_async_activity",
        "services/nex-ae-api/nex_ae_api/workspace_chat_orchestration.py",
        "def append_persisted_workspace_chat_activity(",
    ),
    (
        "async_projection_schema",
        "contracts/schemas/service/nex_ae_api/async_generation.v1.schema.json",
        '"ae_async_generation.v1"',
    ),
    (
        "async_refresh_schema",
        "contracts/schemas/service/nex_ae_api/async_chat_refresh.v1.schema.json",
        '"ae_async_chat_refresh.v1"',
    ),
    (
        "async_openapi",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/refresh:",
    ),
    (
        "actual_ae_test_target",
        "scripts/smoke/run_ae_cx_async_generation_postgres_smoke.py",
        'AE_DATABASE = "nex_ae_test"',
    ),
    (
        "actual_cx_test_target",
        "scripts/smoke/run_ae_cx_async_generation_postgres_smoke.py",
        'CX_DATABASE = "nex_cx_test"',
    ),
    (
        "postgres_cleanup_required",
        "scripts/smoke/run_ae_cx_async_generation_postgres_smoke.py",
        'checks["cleanup_complete"]',
    ),
    (
        "quality_postgres",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_cx_async_generation_postgres_smoke.py",
    ),
    (
        "quality_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s104_ae_cx_async_generation_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1041_s104_ae_cx_async_generation_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "boundary_audit": ("execution_strategy_contract",),
    "async_projection_contract": (
        "execution_strategy_contract",
        "strict_async_projection",
    ),
    "cx_lifecycle_client": ("cx_lifecycle_client",),
    "durable_chat_admission": ("durable_async_admission",),
    "owner_scoped_refresh": ("explicit_owner_refresh",),
    "cancel_retry_lineage": ("cancel_and_retry",),
    "activity_observability": (
        "metadata_observability_v3",
        "workspace_async_activity",
    ),
    "contract_openapi": (
        "async_projection_schema",
        "async_refresh_schema",
        "async_openapi",
    ),
    "actual_postgresql": (
        "actual_ae_test_target",
        "actual_cx_test_target",
        "postgres_cleanup_required",
    ),
    "quality_documentation": (
        "quality_postgres",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s104_ae_cx_async_generation_closure(
    root: Path = ROOT,
    *,
    postgres_evidence: Mapping[str, Any] | None = None,
    contract_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    token_status = {item["name"]: item["present"] for item in token_checks}
    components = {
        name: all(token_status[token] for token in tokens)
        for name, tokens in COMPONENT_TOKEN_NAMES.items()
    }
    boundary = _safe_evidence(lambda: run_boundary(root))
    contract = (
        dict(contract_evidence)
        if contract_evidence is not None
        else _safe_evidence(lambda: _contract_evidence(root))
    )
    postgres = (
        dict(postgres_evidence)
        if postgres_evidence is not None
        else _safe_evidence(run_postgres)
    )
    boundary_summary = _mapping(boundary.get("summary"))
    boundary_decision = _mapping(boundary.get("decision"))
    postgres_checks = _mapping(postgres.get("checks"))
    identity = _mapping(postgres.get("database_identity"))
    ae_identity = _mapping(identity.get("ae"))
    cx_identity = _mapping(identity.get("cx"))
    cleanup = _mapping(postgres.get("cleanup_counts"))
    postgres_requested = os.environ.get(POSTGRES_SMOKE_ENV) == "1"
    postgres_executed = (
        postgres.get("status") == "PASS"
        and postgres.get("actual_postgres") is True
        and postgres.get("execution_state") == "EXECUTED"
        and ae_identity
        == {"database": "nex_ae_test", "role": "nex_ae_user"}
        and cx_identity
        == {"database": "nex_cx_test", "role": "nex_cx_user"}
        and bool(postgres_checks)
        and all(postgres_checks.values())
        and cleanup.get("ae_remaining") == 0
        and cleanup.get("cx_remaining") == 0
    )
    postgres_policy_satisfied = postgres_executed or (
        not postgres_requested and postgres.get("status") == "SKIPPED"
    )
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "boundary_plan_completed": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("gap_count") == 8
            and boundary_summary.get("resolved_gap_count") == 8
            and boundary_summary.get("open_gap_count") == 0
            and boundary.get("next_slice") == "1041"
        ),
        "all_components_closed": all(components.values()),
        "contract_tree_valid": contract.get("status") == "PASS",
        "postgres_policy_satisfied": postgres_policy_satisfied,
        "ownership_boundary_preserved": (
            boundary_decision.get("cx_lifecycle_owner") == "nex-cx"
            and boundary_decision.get("ae_interaction_owner") == "nex-ae-api"
        ),
        "privacy_boundary_preserved": (
            boundary_decision.get("raw_generation_content_persisted_by_ae")
            is False
            and boundary_decision.get("background_poller_in_scope") is False
        ),
        "backward_compatibility_preserved": (
            boundary_decision.get("default_execution_strategy")
            == "SYNCHRONOUS"
            and boundary_decision.get("synchronous_backward_compatibility")
            is True
        ),
        "no_new_table_boundary_preserved": (
            boundary_decision.get("new_tables_expected") == 0
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "1032-1041",
                "checkpoint_gate": "1036",
                "full_gate": "1041",
            }
        ),
        "remote_provider_out_of_scope": (
            boundary_decision.get("remote_provider_required") is False
            and postgres.get("remote_provider_required", False) is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1041",
        "slice_range": SLICE_RANGE,
        "requirement": "S104",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s104_ae_cx_async_generation_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_S105"
            if status == "PASS" and postgres_executed
            else "READY_WITH_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "BLOCKED"
        ),
        "feature_readiness": (
            "AE_CX_ASYNC_GENERATION_READY"
            if status == "PASS" and postgres_executed
            else "REPOSITORY_READY_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "resolved_gap_count": int(
                boundary_summary.get("resolved_gap_count") or 0
            ),
            "contract_schema_count": int(contract.get("schema_count") or 0),
            "contract_example_count": int(contract.get("example_count") or 0),
            "contract_negative_count": int(
                contract.get("negative_example_count") or 0
            ),
            "postgres_check_count": len(postgres_checks)
            if postgres_executed
            else 0,
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "components": components,
        "boundary_status": boundary.get("status"),
        "contract_status": contract.get("status"),
        "postgres_status": postgres.get("status"),
        "postgres_executed": postgres_executed,
        "postgres_evidence": postgres,
        "required_files": required_files,
        "token_checks": token_checks,
        "decision": _closure_decision(),
        "next_requirement": "S105",
    }


def _contract_evidence(root: Path) -> dict[str, Any]:
    result = validate_contract_tree(root / "contracts")
    return {
        "status": "PASS" if result.ok else "FAIL",
        "schema_count": result.schema_count,
        "example_count": result.example_count,
        "negative_example_count": result.negative_example_count,
        "openapi_count": result.openapi_count,
        "failure_count": len(result.failures),
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "ae_to_cx_asynchronous_generation_integration",
        "selection_policy": "explicit_async_with_synchronous_default",
        "lifecycle_owner": "nex-cx",
        "interaction_owner": "nex-ae-api",
        "polling_policy": "explicit_owner_scoped_refresh_no_background_poller",
        "content_policy": "transient_verified_content_not_persisted_by_ae",
        "retry_policy": "new_hash_bound_interaction_with_safe_parent_lineage",
        "postgres_smoke_targets": [
            "nex_ae_user@nex_ae_test",
            "nex_cx_user@nex_cx_test",
        ],
        "remote_provider_required": False,
        "new_tables_added": [],
        "next_requirement_scope": "S105",
    }


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s104_ae_cx_async_generation_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"gaps={summary.get('resolved_gap_count', 0)}/8 "
        f"postgres={str(evidence.get('postgres_status') or 'not-run').lower()} "
        f"postgres_checks={summary.get('postgres_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s104_ae_cx_async_generation_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
