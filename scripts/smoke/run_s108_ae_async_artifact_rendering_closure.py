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

from run_ae_async_artifact_render_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    run_ae_async_artifact_render_postgres_smoke as run_postgres,
)
from run_ae_async_artifact_rendering_boundary_audit import (  # noqa: E402
    run_ae_async_artifact_rendering_boundary_audit as run_boundary,
)
from validate_contracts import validate_contract_tree  # noqa: E402

SCHEMA_VERSION = "s108_ae_async_artifact_rendering_closure.v1"
SLICE_RANGE = "1072-1081"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
    "services/nex-ae-api/nex_ae_api/async_artifact_render_worker.py",
    "services/nex-ae-api/nex_ae_api/async_artifact_render_recovery.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/nex_ae_api/generated_response_lineage.py",
    "database/nex-ae-api/migrations/0402_ae_artifact_persistence_foundation.sql",
    "database/nex-ae-api/migrations/0083_service_job_queue_foundation.sql",
    "contracts/schemas/service/nex_ae_api/async_artifact_render_request.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/async_artifact_render_admission.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/async_artifact_render_projection.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/async_artifact_render_recovery.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/async_artifact_render_reconciliation.v1.schema.json",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "scripts/smoke/run_ae_async_artifact_render_postgres_smoke.py",
    "scripts/smoke/run_s108_ae_async_artifact_rendering_closure.py",
    "tests/test_s108_ae_async_artifact_rendering_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1072", "ae_async_artifact_rendering_boundary_audit"),
            ("1073", "ae_async_artifact_render_contract"),
            ("1074", "ae_async_artifact_render_admission"),
            ("1075", "ae_async_artifact_render_api"),
            ("1076", "ae_async_artifact_render_worker"),
            ("1077", "ae_async_artifact_response_lineage"),
            ("1078", "ae_async_artifact_render_recovery"),
            ("1079", "ae_async_artifact_render_contract_hardening"),
            ("1080", "ae_async_artifact_render_postgres_smoke"),
            ("1081", "s108_ae_async_artifact_rendering_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "render_contract",
        "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
        "def build_async_artifact_render_request(",
    ),
    (
        "durable_admission",
        "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
        "def admit_async_artifact_render(",
    ),
    (
        "owner_scoped_api",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifacts/{artifact_id}/async-render-jobs"',
    ),
    (
        "render_worker",
        "services/nex-ae-api/nex_ae_api/async_artifact_render_worker.py",
        "def run_async_artifact_render_worker_once(",
    ),
    (
        "response_lineage",
        "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
        "def validate_async_artifact_response_lineage(",
    ),
    (
        "recovery_reconciliation",
        "services/nex-ae-api/nex_ae_api/async_artifact_render_recovery.py",
        "def reconcile_async_artifact_render(",
    ),
    (
        "private_storage",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "class LocalRenderedArtifactStorage:",
    ),
    (
        "request_schema",
        "contracts/schemas/service/nex_ae_api/async_artifact_render_request.v1.schema.json",
        '"ae_async_artifact_render_request.v1"',
    ),
    (
        "async_openapi",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/artifacts/{artifact_id}/async-render-jobs:",
    ),
    (
        "actual_ae_test_target",
        "scripts/smoke/run_ae_async_artifact_render_postgres_smoke.py",
        'DATABASE_NAME = "nex_ae_test"',
    ),
    (
        "actual_ae_test_role",
        "scripts/smoke/run_ae_async_artifact_render_postgres_smoke.py",
        'DATABASE_ROLE = "nex_ae_user"',
    ),
    (
        "bounded_retry_smoke",
        "scripts/smoke/run_ae_async_artifact_render_postgres_smoke.py",
        '"bounded_retry_persisted"',
    ),
    (
        "quality_postgres",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_async_artifact_render_postgres_smoke.py",
    ),
    (
        "quality_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s108_ae_async_artifact_rendering_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1081_s108_ae_async_artifact_rendering_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "boundary_audit": ("render_contract",),
    "deterministic_render_contract": ("render_contract",),
    "durable_queue_admission": ("durable_admission",),
    "owner_scoped_lifecycle_api": ("owner_scoped_api",),
    "restart_safe_render_worker": ("render_worker",),
    "generated_response_lineage": ("response_lineage",),
    "retry_recovery_reconciliation": ("recovery_reconciliation",),
    "contract_openapi": ("request_schema", "async_openapi"),
    "actual_postgresql_private_storage": (
        "private_storage",
        "actual_ae_test_target",
        "actual_ae_test_role",
        "bounded_retry_smoke",
    ),
    "quality_documentation": (
        "quality_postgres",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s108_ae_async_artifact_rendering_closure(
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
        and identity == {"database": "nex_ae_test", "role": "nex_ae_user"}
        and bool(postgres_checks)
        and all(postgres_checks.values())
        and postgres_checks.get("worker_completed_after_restart") is True
        and postgres_checks.get("metadata_only_in_postgres") is True
        and postgres_checks.get("bounded_retry_persisted") is True
        and postgres_checks.get("retry_state_reconciled") is True
        and cleanup.get("remaining") == 0
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
            and boundary.get("next_slice") == "1081"
        ),
        "all_components_closed": all(components.values()),
        "contract_tree_valid": contract.get("status") == "PASS",
        "postgres_policy_satisfied": postgres_policy_satisfied,
        "ownership_boundary_preserved": (
            boundary_decision.get("owner") == "nex-ae-api"
            and boundary_decision.get("source_content_owner")
            == "nex-cx_structured_draft"
            and boundary_decision.get("response_lineage_owner") == "nex-ae-api"
        ),
        "durable_state_boundary_preserved": (
            boundary_decision.get("render_state_store") == "ae_artifact_render_jobs"
            and boundary_decision.get("execution_queue_store") == "service_jobs"
            and boundary_decision.get("execution_model")
            == "durable_queue_backed_asynchronous_render"
        ),
        "privacy_boundary_preserved": (
            boundary_decision.get("rendered_payload_store")
            == "ae_private_rendered_artifact_storage"
            and boundary_decision.get("raw_rendered_content_in_postgresql") is False
            and boundary_decision.get("raw_rendered_content_in_operational_events")
            is False
            and boundary_decision.get("storage_path_in_public_api") is False
        ),
        "owner_and_compatibility_preserved": (
            boundary_decision.get("exact_owner_scope_required") is True
            and boundary_decision.get("legacy_sync_route_preserved") is True
            and boundary_decision.get("explicit_async_admission_required") is True
        ),
        "existing_tables_reused": (
            boundary_decision.get("new_tables_expected") == 0
            and boundary_decision.get("restart_safe_render_required") is True
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "every_slice",
                "checkpoint_gate": "1076",
                "full_gate": "1081",
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
        "slice": "1081",
        "slice_range": SLICE_RANGE,
        "requirement": "S108",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s108_async_artifact_rendering_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_S109"
            if status == "PASS" and postgres_executed
            else (
                "READY_WITH_PROTECTED_POSTGRES_PENDING"
                if status == "PASS"
                else "BLOCKED"
            )
        ),
        "feature_readiness": (
            "AE_ASYNC_ARTIFACT_RENDERING_READY"
            if status == "PASS" and postgres_executed
            else (
                "REPOSITORY_READY_PROTECTED_POSTGRES_PENDING"
                if status == "PASS"
                else "INCOMPLETE"
            )
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "resolved_gap_count": int(boundary_summary.get("resolved_gap_count") or 0),
            "contract_schema_count": int(contract.get("schema_count") or 0),
            "contract_example_count": int(contract.get("example_count") or 0),
            "contract_negative_count": int(contract.get("negative_example_count") or 0),
            "postgres_check_count": (len(postgres_checks) if postgres_executed else 0),
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
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
        "next_requirement": "S109",
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
        "feature_scope": "ae_asynchronous_artifact_rendering_integration",
        "render_owner": "nex-ae-api",
        "structured_draft_owner": "nex-cx",
        "execution_model": "durable_queue_backed_worker",
        "metadata_stores": ["ae_artifact_render_jobs", "service_jobs"],
        "payload_storage_policy": "private_storage_outside_postgresql",
        "postgres_smoke_target": "nex_ae_user@nex_ae_test",
        "remote_provider_required": False,
        "new_tables_added": [],
        "next_requirement_scope": "S109_to_be_confirmed",
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
        "s108_ae_async_artifact_rendering_closure="
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
    evidence = run_s108_ae_async_artifact_rendering_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
