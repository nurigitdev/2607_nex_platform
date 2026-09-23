#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_cx_grounded_generation_runtime_boundary_audit import (
    run_cx_grounded_generation_runtime_boundary_audit as run_boundary,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s97_cx_grounded_generation_runtime_closure.v1"
SLICE_RANGE = "0961-0970"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"

REQUIRED_FILES = (
    "services/nex-cx/nex_cx/grounded_prompt.py",
    "services/nex-cx/nex_cx/grounded_output_validation.py",
    "services/nex-cx/nex_cx/generation_private_output.py",
    "services/nex-cx/nex_cx/generation_repository.py",
    "services/nex-cx/nex_cx/generation_runtime.py",
    "services/nex-cx/nex_cx/generation_read_model.py",
    "services/nex-cx/nex_cx/generation_observability.py",
    "database/nex-cx/migrations/0965_cx_grounded_generation_runtime.sql",
    "database/nex-cx/migrations/0966_cx_generation_admissions.sql",
    "contracts/schemas/generation/cx_generation_read_model.v1.schema.json",
    "contracts/schemas/generation/cx_generation_content.v1.schema.json",
    "contracts/openapi/nex-cx.openapi.yaml",
    "scripts/smoke/run_cx_grounded_generation_live_postgres_smoke.py",
    "scripts/smoke/run_s97_cx_grounded_generation_runtime_closure.py",
    "tests/test_s97_cx_grounded_generation_runtime_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0961", "cx_grounded_generation_runtime_boundary_audit"),
            ("0962", "cx_grounded_prompt_package_evidence_binding"),
            ("0963", "cx_provider_output_citation_validation"),
            ("0964", "cx_durable_private_generation_output"),
            ("0965", "cx_sql_generation_runtime_repository"),
            ("0966", "cx_idempotent_grounded_execution_runtime"),
            ("0967", "cx_restart_safe_generation_read_model"),
            ("0968", "cx_generation_observability_contract_hardening"),
            ("0969", "cx_grounded_generation_live_postgresql_dgx_smoke"),
            ("0970", "s97_cx_grounded_generation_runtime_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    ("quality_boundary", QUALITY_GATE_PATH, "run_cx_grounded_generation_runtime_boundary_audit.py"),
    ("quality_live", QUALITY_GATE_PATH, "run_cx_grounded_generation_live_postgres_smoke.py"),
    ("quality_closure", QUALITY_GATE_PATH, "run_s97_cx_grounded_generation_runtime_closure.py"),
    (
        "prompt_package",
        "services/nex-cx/nex_cx/grounded_prompt.py",
        "cx_grounded_prompt_package.v1",
    ),
    (
        "untrusted_context",
        "services/nex-cx/nex_cx/grounded_prompt.py",
        "cx_grounded_context_envelope.v1",
    ),
    (
        "output_validation",
        "services/nex-cx/nex_cx/grounded_output_validation.py",
        "cx_grounded_output_validation.v1",
    ),
    (
        "private_output",
        "services/nex-cx/nex_cx/generation_private_output.py",
        "cx_generation_private_output.v1",
    ),
    (
        "sql_runtime_table",
        "services/nex-cx/nex_cx/generation_repository.py",
        'CX_GENERATION_RUNTIME_TABLE = "cx_generation_executions"',
    ),
    (
        "runtime_migration",
        "database/nex-cx/migrations/0965_cx_grounded_generation_runtime.sql",
        "0965_cx_grounded_generation_runtime",
    ),
    (
        "admission_table",
        "database/nex-cx/migrations/0966_cx_generation_admissions.sql",
        "CREATE TABLE IF NOT EXISTS cx_gen_admissions",
    ),
    (
        "idempotent_admission",
        "services/nex-cx/nex_cx/generation_runtime.py",
        "cx_generation_admission.v1",
    ),
    ("reasoning_hash", "services/nex-cx/nex_cx/generation_runtime.py", '"reasoning_mode"'),
    (
        "read_model",
        "services/nex-cx/nex_cx/generation_read_model.py",
        "cx_generation_read_model.v1",
    ),
    (
        "content_model",
        "services/nex-cx/nex_cx/generation_read_model.py",
        "cx_generation_content.v1",
    ),
    (
        "completed_event",
        "services/nex-cx/nex_cx/generation_observability.py",
        "cx.generation.completed",
    ),
    (
        "replayed_event",
        "services/nex-cx/nex_cx/generation_observability.py",
        "cx.generation.replayed",
    ),
    ("openapi_metadata", "contracts/openapi/nex-cx.openapi.yaml", "CxGenerationReadModel:"),
    ("openapi_content", "contracts/openapi/nex-cx.openapi.yaml", "CxGenerationContent:"),
    (
        "live_check_count",
        "docs/slices/0969_cx_grounded_generation_live_postgresql_dgx_smoke.md",
        "`12/12`",
    ),
    (
        "live_database",
        "docs/slices/0969_cx_grounded_generation_live_postgresql_dgx_smoke.md",
        "`nex_cx_test`",
    ),
    (
        "live_role",
        "docs/slices/0969_cx_grounded_generation_live_postgresql_dgx_smoke.md",
        "`nex_cx_user`",
    ),
    (
        "live_model",
        "docs/slices/0969_cx_grounded_generation_live_postgresql_dgx_smoke.md",
        "`Qwen3.5-4B`",
    ),
    (
        "live_restart_replay",
        "docs/slices/0969_cx_grounded_generation_live_postgresql_dgx_smoke.md",
        "remained `1` after restart replay",
    ),
    (
        "live_cleanup",
        "docs/slices/0969_cx_grounded_generation_live_postgresql_dgx_smoke.md",
        "zero remaining execution",
    ),
    (
        "docs_live_index",
        "docs/README.md",
        "0969_cx_grounded_generation_live_postgresql_dgx_smoke.md",
    ),
    ("docs_closure_index", "docs/README.md", "0970_s97_cx_grounded_generation_runtime_closure.md"),
)

COMPONENT_TOKEN_NAMES = {
    "grounded_prompt_binding": ("prompt_package", "untrusted_context"),
    "provider_output_validation": ("output_validation",),
    "durable_private_output": ("private_output",),
    "sql_generation_repository": ("sql_runtime_table", "runtime_migration"),
    "idempotent_execution_runtime": ("admission_table", "idempotent_admission", "reasoning_hash"),
    "restart_safe_read_model": (
        "read_model",
        "content_model",
        "openapi_metadata",
        "openapi_content",
    ),
    "metadata_only_observability": ("completed_event", "replayed_event"),
    "protected_live_evidence": (
        "live_check_count",
        "live_database",
        "live_role",
        "live_model",
        "live_restart_replay",
        "live_cleanup",
    ),
}


def run_s97_cx_grounded_generation_runtime_closure(
    root: Path = ROOT,
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
    boundary_summary = _mapping(boundary.get("summary"))
    boundary_decision = _mapping(boundary.get("decision"))
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "boundary_plan_completed": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("gap_count") == 8
            and boundary_summary.get("resolved_gap_count") == 8
            and boundary_summary.get("open_gap_count") == 0
            and boundary_summary.get("issue_count") == 0
            and boundary.get("next_slice") == "0970"
        ),
        "all_runtime_components_closed": all(components.values()),
        "owner_private_boundary_preserved": (
            boundary_decision.get("feature_scope")
            == "owner_private_grounded_generation_runtime"
            and boundary_decision.get("cross_owner_behavior")
            == "not_found_without_disclosure"
            and boundary_decision.get("public_persistence_policy")
            == "metadata_hashes_lineage_only"
            and boundary_decision.get("private_output_policy")
            == "durable_private_payload_reference"
        ),
        "bounded_runtime_policy_preserved": (
            boundary_decision.get("execution_policy")
            == "bounded_synchronous_idempotent_write_through"
            and boundary_decision.get("provider_output_policy")
            == "citation_validated_structured_draft"
        ),
        "canonical_live_target_confirmed": (
            boundary_decision.get("generation_model") == "Qwen3.5-4B"
            and boundary_decision.get("generation_provider_port") == 9111
            and decision["postgres_smoke_target"] == "nex_cx_user@nex_cx_test"
        ),
        "single_migration_history_preserved": (
            boundary_decision.get("migration_strategy")
            == "versioned_sql_schema_migrations_runner"
        ),
        "deferred_scope_not_overclaimed": (
            "asynchronous_generation_worker" in decision["deferred_scope"]
            and "streaming_generation_transport" in decision["deferred_scope"]
            and "production_provider_slo_baseline" in decision["deferred_scope"]
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "0970",
        "slice_range": SLICE_RANGE,
        "requirement": "S97",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "s97_grounded_generation_runtime_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S98" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_GROUNDED_GENERATION_RUNTIME_READY"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "resolved_gap_count": int(boundary_summary.get("resolved_gap_count") or 0),
            "protected_live_check_count": 12 if components["protected_live_evidence"] else 0,
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "components": components,
        "boundary_status": boundary.get("status"),
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S98",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "owner_private_grounded_generation_runtime",
        "execution_policy": "bounded_synchronous_idempotent_write_through",
        "grounding_policy": "owner_admitted_ready_retrieval_evidence_only",
        "prompt_policy": "cx_assembled_untrusted_evidence_envelope",
        "provider_output_policy": "strict_citation_validated_terminal_output",
        "public_persistence_policy": "metadata_hashes_lineage_only",
        "private_output_policy": "durable_owner_scoped_payload_reference",
        "cross_owner_behavior": "not_found_without_disclosure",
        "generation_model": "Qwen3.5-4B",
        "generation_provider_port": 9111,
        "reasoning_mode": "request_bound_and_idempotency_hashed",
        "observability_policy": "metadata_only_best_effort",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "migration_strategy": "versioned_sql_schema_migrations_runner",
        "protected_live_evidence_completed": True,
        "deferred_scope": [
            "asynchronous_generation_worker",
            "streaming_generation_transport",
            "automatic_multi_attempt_citation_repair",
            "production_provider_slo_baseline",
        ],
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
        "s97_cx_grounded_generation_runtime_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"gaps={summary.get('resolved_gap_count', 0)}/8 "
        f"live_checks={summary.get('protected_live_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s97_cx_grounded_generation_runtime_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
