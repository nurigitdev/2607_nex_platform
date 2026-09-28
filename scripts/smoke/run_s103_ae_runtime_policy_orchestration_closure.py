#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from run_ae_intent_template_policy_boundary_audit import (
    run_ae_intent_template_policy_boundary_audit as run_boundary,
)
from run_ae_runtime_policy_contract_observability import (
    run_ae_runtime_policy_contract_observability as run_contract_observability,
)
from run_ae_runtime_policy_postgres_smoke import (
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    run_ae_runtime_policy_postgres_smoke as run_postgres,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s103_ae_runtime_policy_orchestration_closure.v1"
SLICE_RANGE = "1022-1031"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/intent_policy.py",
    "services/nex-ae-api/nex_ae_api/prompt_persistence.py",
    "services/nex-ae-api/nex_ae_api/runtime_policy.py",
    "services/nex-ae-api/nex_ae_api/runtime_policy_api.py",
    "services/nex-ae-api/nex_ae_api/generation_policy.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/_shared/nex_runtime/compatibility.py",
    "contracts/schemas/service/nex_ae_api/intent_decision.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/runtime_policy.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/generation_policy_package.v1.schema.json",
    "scripts/smoke/run_ae_runtime_policy_postgres_smoke.py",
    "scripts/smoke/run_s103_ae_runtime_policy_orchestration_closure.py",
    "tests/test_s103_ae_runtime_policy_orchestration_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1022", "ae_intent_template_policy_boundary_audit"),
            ("1023", "ae_intent_execution_mode_contract"),
            ("1024", "ae_prompt_template_registry_postgresql_adapter"),
            ("1025", "ae_runtime_compatibility_policy_resolver"),
            ("1026", "ae_runtime_policy_inspection_api"),
            ("1027", "ae_generation_policy_package"),
            ("1028", "ae_chat_runtime_policy_orchestration"),
            ("1029", "ae_runtime_policy_contract_openapi_observability"),
            ("1030", "ae_runtime_policy_postgresql_smoke"),
            ("1031", "s103_ae_runtime_policy_orchestration_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "canonical_execution_modes",
        "services/nex-ae-api/nex_ae_api/intent_policy.py",
        "CANONICAL_EXECUTION_MODES = (",
    ),
    (
        "durable_prompt_registry",
        "services/nex-ae-api/nex_ae_api/prompt_persistence.py",
        "class SqlAlchemyAePromptRegistryStore",
    ),
    (
        "exact_runtime_policy_resolver",
        "services/nex-ae-api/nex_ae_api/runtime_policy.py",
        "def resolve_runtime_policy(",
    ),
    (
        "protected_runtime_policy_routes",
        "services/nex-ae-api/nex_ae_api/runtime_policy_api.py",
        "def register_runtime_policy_routes(",
    ),
    (
        "generation_policy_package",
        "services/nex-ae-api/nex_ae_api/generation_policy.py",
        "def build_generation_policy_package(",
    ),
    (
        "chat_policy_attachment",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "def attach_generation_policy_package(",
    ),
    (
        "canonical_cx_compatibility",
        "services/_shared/nex_runtime/compatibility.py",
        '"compat-ae-document-summary-v1"',
    ),
    (
        "intent_contract",
        "contracts/schemas/service/nex_ae_api/intent_decision.v1.schema.json",
        '"ae_intent_decision.v1"',
    ),
    (
        "runtime_policy_contract",
        "contracts/schemas/service/nex_ae_api/runtime_policy.v1.schema.json",
        '"ae_runtime_policy.v1"',
    ),
    (
        "generation_package_contract",
        "contracts/schemas/service/nex_ae_api/generation_policy_package.v1.schema.json",
        '"ae_generation_policy_package.v1"',
    ),
    (
        "runtime_policy_openapi",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/runtime-policies/resolve:",
    ),
    (
        "metadata_only_observability",
        "services/nex-ae-api/nex_ae_api/workspace_chat_observability.py",
        '"ae_workspace_chat_observability.v2"',
    ),
    (
        "protected_postgres_target",
        "scripts/smoke/run_ae_runtime_policy_postgres_smoke.py",
        'EXPECTED_DATABASE = "nex_ae_test"',
    ),
    (
        "postgres_cleanup_required",
        "scripts/smoke/run_ae_runtime_policy_postgres_smoke.py",
        'checks["cleanup_complete"]',
    ),
    (
        "quality_postgres",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_runtime_policy_postgres_smoke.py",
    ),
    (
        "quality_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s103_ae_runtime_policy_orchestration_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1031_s103_ae_runtime_policy_orchestration_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "boundary_audit": ("canonical_execution_modes",),
    "intent_execution_mode": ("canonical_execution_modes", "intent_contract"),
    "prompt_registry_persistence": ("durable_prompt_registry",),
    "runtime_policy_resolution": (
        "exact_runtime_policy_resolver",
        "runtime_policy_contract",
        "canonical_cx_compatibility",
    ),
    "protected_policy_api": (
        "protected_runtime_policy_routes",
        "runtime_policy_openapi",
    ),
    "generation_policy_package": (
        "generation_policy_package",
        "generation_package_contract",
    ),
    "chat_policy_orchestration": ("chat_policy_attachment",),
    "contract_and_observability": (
        "intent_contract",
        "runtime_policy_contract",
        "generation_package_contract",
        "metadata_only_observability",
        "canonical_cx_compatibility",
    ),
    "protected_postgresql": (
        "protected_postgres_target",
        "postgres_cleanup_required",
    ),
    "quality_and_documentation": (
        "quality_postgres",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s103_ae_runtime_policy_orchestration_closure(
    root: Path = ROOT,
    *,
    postgres_evidence: Mapping[str, Any] | None = None,
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
    contract = _safe_evidence(run_contract_observability)
    postgres = (
        dict(postgres_evidence)
        if postgres_evidence is not None
        else _safe_evidence(run_postgres)
    )
    boundary_summary = _mapping(boundary.get("summary"))
    boundary_decision = _mapping(boundary.get("decision"))
    postgres_checks = _mapping(postgres.get("checks"))
    postgres_requested = os.environ.get(POSTGRES_SMOKE_ENV) == "1"
    postgres_executed = (
        postgres.get("status") == "PASS"
        and postgres.get("actual_postgres") is True
        and postgres.get("execution_state") == "EXECUTED"
        and postgres.get("database") == "nex_ae_test"
        and postgres.get("role") == "nex_ae_user"
        and bool(postgres_checks)
        and all(postgres_checks.values())
        and _mapping(postgres.get("cleanup_counts")).get("remaining") == 0
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
            and boundary.get("next_slice") == "1031"
        ),
        "all_components_closed": all(components.values()),
        "contract_observability_passed": contract.get("status") == "PASS"
        and all(_mapping(contract.get("checks")).values()),
        "postgres_policy_satisfied": postgres_policy_satisfied,
        "policy_privacy_boundary_preserved": (
            boundary_decision.get("raw_prompt_in_policy_snapshot") is False
            and boundary_decision.get("direct_provider_runtime_fields_allowed")
            is False
        ),
        "exact_version_policy_preserved": (
            boundary_decision.get("version_policy")
            == "explicit_versions_no_latest_in_resolved_records"
            and boundary_decision.get("compatibility_policy")
            == "exact_active_rule_required_fail_closed"
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "1022-1031",
                "checkpoint_gate": "1026",
                "full_gate": "1031",
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
        "slice": "1031",
        "slice_range": SLICE_RANGE,
        "requirement": "S103",
        "status": status,
        "failure_code": None
        if status == "PASS"
        else "s103_ae_runtime_policy_closure_failed",
        "closure_readiness": (
            "READY_FOR_S104"
            if status == "PASS" and postgres_executed
            else "READY_WITH_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "BLOCKED"
        ),
        "feature_readiness": (
            "AE_RUNTIME_POLICY_ORCHESTRATION_READY"
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
            "contract_check_count": len(_mapping(contract.get("checks"))),
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
        "contract_observability_status": contract.get("status"),
        "postgres_status": postgres.get("status"),
        "postgres_executed": postgres_executed,
        "postgres_evidence": postgres,
        "required_files": required_files,
        "token_checks": token_checks,
        "decision": _closure_decision(),
        "next_requirement": "S104",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "ae_intent_template_prompt_runtime_policy_orchestration",
        "execution_mode_policy": "canonical_explicit_precedence_deterministic_fallback",
        "prompt_policy": "durable_exact_versioned_binding_and_render_lineage",
        "compatibility_policy": "exact_active_rule_required_fail_closed",
        "chat_policy": "resolved_snapshot_and_package_hash_persisted",
        "privacy_policy": "no_raw_prompt_evidence_or_provider_runtime_fields",
        "postgres_smoke_target": "nex_ae_user@nex_ae_test",
        "remote_provider_required": False,
        "new_tables_added": [],
        "next_requirement_scope": "S104_to_be_confirmed",
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
        "s103_ae_runtime_policy_orchestration_closure="
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
    evidence = run_s103_ae_runtime_policy_orchestration_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
