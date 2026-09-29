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

from run_ae_generated_response_lineage_boundary_audit import (  # noqa: E402
    run_ae_generated_response_lineage_boundary_audit as run_boundary,
)
from run_ae_generated_response_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    run_ae_generated_response_postgres_smoke as run_postgres,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s107_ae_generated_response_lineage_closure.v1"
SLICE_RANGE = "1062-1071"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/generated_response_storage.py",
    "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
    "services/nex-ae-api/nex_ae_api/generated_response_api.py",
    "services/nex-ae-api/nex_ae_api/generated_response_handoff.py",
    "services/nex-ae-api/nex_ae_api/generated_response_observability.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "contracts/schemas/service/nex_ae_api/generated_response_lineage.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/generated_response.v1.schema.json",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "scripts/smoke/run_ae_generated_response_postgres_smoke.py",
    "scripts/smoke/run_s107_ae_generated_response_lineage_closure.py",
    "tests/test_s107_ae_generated_response_lineage_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1062", "ae_generated_response_lineage_boundary_audit"),
            ("1063", "ae_private_generated_response_storage"),
            ("1064", "ae_generated_response_lineage_projection"),
            ("1065", "ae_generated_response_api"),
            ("1066", "ae_async_response_handoff_integration"),
            ("1067", "ae_generated_response_retry_repair_lineage"),
            ("1068", "ae_generated_response_observability"),
            ("1069", "ae_generated_response_contract_hardening"),
            ("1070", "ae_generated_response_postgres_smoke"),
            ("1071", "s107_ae_generated_response_lineage_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "private_storage",
        "services/nex-ae-api/nex_ae_api/generated_response_storage.py",
        "class LocalGeneratedResponseStorage:",
    ),
    (
        "lineage_projection",
        "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
        "def prepare_generated_response(",
    ),
    (
        "lineage_validation",
        "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
        "def validate_generated_response_lineage(",
    ),
    (
        "owner_response_api",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/response"',
    ),
    (
        "durable_handoff",
        "services/nex-ae-api/nex_ae_api/generated_response_handoff.py",
        "def persist_ready_generated_response(",
    ),
    (
        "durable_ready_flag",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"content_persisted_by_ae": content_persisted',
    ),
    (
        "retry_parent_response",
        "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
        '"parent_response_id": normalized_parent_response_id',
    ),
    (
        "metadata_observability",
        "services/nex-ae-api/nex_ae_api/generated_response_observability.py",
        'AE_GENERATED_RESPONSE_PERSISTED_EVENT = "ae.generated_response.persisted"',
    ),
    (
        "lineage_schema",
        "contracts/schemas/service/nex_ae_api/generated_response_lineage.v1.schema.json",
        '"ae_generated_response_lineage.v1"',
    ),
    (
        "owner_response_schema",
        "contracts/schemas/service/nex_ae_api/generated_response.v1.schema.json",
        '"ae_generated_response.v1"',
    ),
    (
        "response_openapi",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/response:",
    ),
    (
        "actual_ae_test_target",
        "scripts/smoke/run_ae_generated_response_postgres_smoke.py",
        'AE_DATABASE = "nex_ae_test"',
    ),
    (
        "actual_cx_test_target",
        "scripts/smoke/run_ae_generated_response_postgres_smoke.py",
        'CX_DATABASE = "nex_cx_test"',
    ),
    (
        "private_storage_smoke",
        "scripts/smoke/run_ae_generated_response_postgres_smoke.py",
        '"private_storage_mode": "temporary-local-filesystem"',
    ),
    (
        "quality_postgres",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_generated_response_postgres_smoke.py",
    ),
    (
        "quality_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s107_ae_generated_response_lineage_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1071_s107_ae_generated_response_lineage_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "boundary_audit": ("lineage_projection",),
    "private_response_storage": ("private_storage",),
    "chat_lineage_projection": ("lineage_projection", "lineage_validation"),
    "owner_scoped_response_api": ("owner_response_api",),
    "durable_async_handoff": ("durable_handoff", "durable_ready_flag"),
    "retry_repair_lineage": ("retry_parent_response",),
    "metadata_observability": ("metadata_observability",),
    "contract_openapi": (
        "lineage_schema",
        "owner_response_schema",
        "response_openapi",
    ),
    "actual_postgresql": (
        "actual_ae_test_target",
        "actual_cx_test_target",
        "private_storage_smoke",
    ),
    "quality_documentation": (
        "quality_postgres",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s107_ae_generated_response_lineage_closure(
    root: Path = ROOT,
    *,
    postgres_evidence: Mapping[str, Any] | None = None,
    contract_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {"name": name, "path": path, "present": token in _read_text(root / path)}
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
    cleanup = _mapping(postgres.get("cleanup_counts"))
    postgres_requested = os.environ.get(POSTGRES_SMOKE_ENV) == "1"
    postgres_executed = (
        postgres.get("status") == "PASS"
        and postgres.get("actual_postgres") is True
        and postgres.get("execution_state") == "EXECUTED"
        and _mapping(identity.get("ae"))
        == {"database": "nex_ae_test", "role": "nex_ae_user"}
        and _mapping(identity.get("cx"))
        == {"database": "nex_cx_test", "role": "nex_cx_user"}
        and bool(postgres_checks)
        and all(postgres_checks.values())
        and postgres_checks.get("content_persisted_privately_and_verified") is True
        and postgres_checks.get("response_metadata_only_in_postgres") is True
        and postgres_checks.get("ae_restart_read") is True
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
            and boundary.get("next_slice") == "1071"
        ),
        "all_components_closed": all(components.values()),
        "contract_tree_valid": contract.get("status") == "PASS",
        "postgres_policy_satisfied": postgres_policy_satisfied,
        "ownership_boundary_preserved": (
            boundary_decision.get("cx_generation_source_owner") == "nex-cx"
            and boundary_decision.get("ae_chat_response_owner") == "nex-ae-api"
            and boundary_decision.get("ae_web_consumer") == "nex-ae-web"
        ),
        "private_storage_boundary_preserved": (
            boundary_decision.get("content_storage_model")
            == "private_storage_outside_postgresql"
            and boundary_decision.get("metadata_storage_model")
            == "ae_chat_interactions.generation_summary"
            and boundary_decision.get("raw_response_in_postgresql") is False
            and boundary_decision.get("storage_path_in_public_api") is False
        ),
        "owner_scope_preserved": (
            boundary_decision.get("owner_scope")
            == "tenant_and_owner_user_exact_match"
        ),
        "retry_repair_lineage_preserved": (
            boundary_decision.get("retry_lineage_model")
            == "parent_interaction_and_parent_response_refs"
            and boundary_decision.get("bounded_repair_lineage_model")
            == "same_cx_generation_final_content"
        ),
        "existing_table_reused": (
            boundary_decision.get("database_table_reused")
            == "ae_chat_interactions"
            and boundary_decision.get("new_tables_expected") == 0
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "1062-1071",
                "checkpoint_gate": "1066",
                "full_gate": "1071",
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
        "slice": "1071",
        "slice_range": SLICE_RANGE,
        "requirement": "S107",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s107_generated_response_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_S108"
            if status == "PASS" and postgres_executed
            else "READY_WITH_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "BLOCKED"
        ),
        "feature_readiness": (
            "AE_GENERATED_RESPONSE_LINEAGE_READY"
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
            "postgres_check_count": len(postgres_checks) if postgres_executed else 0,
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
        "next_requirement": "S108",
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
        "feature_scope": "ae_generated_response_and_chat_lineage_integration",
        "generation_source_owner": "nex-cx",
        "response_projection_owner": "nex-ae-api",
        "response_consumer": "nex-ae-web",
        "content_storage_policy": "private_storage_outside_postgresql",
        "metadata_storage_policy": "ae_chat_generation_summary",
        "postgres_smoke_targets": [
            "nex_ae_user@nex_ae_test",
            "nex_cx_user@nex_cx_test",
        ],
        "remote_provider_required": False,
        "new_tables_added": [],
        "next_requirement_scope": "S108_to_be_confirmed",
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
        "s107_ae_generated_response_lineage_closure="
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
    evidence = run_s107_ae_generated_response_lineage_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
