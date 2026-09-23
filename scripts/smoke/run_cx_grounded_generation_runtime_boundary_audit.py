#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_grounded_generation_runtime_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0960_s96_cx_document_intelligence_summary_similarity_closure.md",
    "services/nex-cx/nex_cx/generation.py",
    "services/nex-cx/nex_cx/drafts.py",
    "services/nex-cx/nex_cx/generation_persistence.py",
    "services/nex-cx/nex_cx/main.py",
    "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql",
    "contracts/schemas/generation/cx_generation_execution_record.v1.schema.json",
    "contracts/schemas/generation/cx_structured_draft.v1.schema.json",
    "contracts/openapi/nex-cx.openapi.yaml",
    "scripts/smoke/run_protected_dgx_live_profile.py",
    "scripts/quality/run_quality_gate.sh",
    "docs/README.md",
    "docs/slices/0961_cx_grounded_generation_runtime_boundary_audit.md",
)
EVIDENCE_TOKENS = (
    EvidenceToken(
        "s96_handoff",
        "docs/slices/0960_s96_cx_document_intelligence_summary_similarity_closure.md",
        "READY_FOR_S97",
    ),
    EvidenceToken(
        "generation_route",
        "services/nex-cx/nex_cx/generation.py",
        '@app.post("/api/v1/generations"',
    ),
    EvidenceToken(
        "owner_authorization",
        "services/nex-cx/nex_cx/generation.py",
        "authorize_cx_owner_request",
    ),
    EvidenceToken(
        "grounded_boundary",
        "services/nex-cx/nex_cx/generation.py",
        "evaluate_grounded_generation_boundary",
    ),
    EvidenceToken(
        "retrieval_quality_guard",
        "services/nex-cx/nex_cx/generation.py",
        "build_retrieval_package_quality_guard",
    ),
    EvidenceToken(
        "structured_draft",
        "services/nex-cx/nex_cx/drafts.py",
        "def build_structured_draft",
    ),
    EvidenceToken(
        "citation_validation",
        "services/nex-cx/nex_cx/drafts.py",
        "def validate_citation_claims",
    ),
    EvidenceToken(
        "generation_persistence_contract",
        "services/nex-cx/nex_cx/generation_persistence.py",
        "def build_generation_persistence_record",
    ),
    EvidenceToken(
        "generation_table",
        "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql",
        "CREATE TABLE IF NOT EXISTS cx_generation_executions",
    ),
    EvidenceToken(
        "owner_index",
        "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql",
        "CREATE INDEX IF NOT EXISTS idx_cx_gen_owner_created",
    ),
    EvidenceToken(
        "mo_client",
        "services/nex-cx/nex_cx/generation.py",
        "class HttpMoGenerationClient",
    ),
    EvidenceToken(
        "current_generation_model",
        "scripts/smoke/run_protected_dgx_live_profile.py",
        '"NEX_MO_VLLM_MODEL": "Qwen3.5-4B"',
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_grounded_generation_runtime_boundary_audit.py",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0961_cx_grounded_generation_runtime_boundary_audit.md",
    ),
)


def run_cx_grounded_generation_runtime_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {"path": relative_path, "present": (root / relative_path).is_file()}
        for relative_path in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in EVIDENCE_TOKENS
    ]
    generation_source = _read_text(root / "services/nex-cx/nex_cx/generation.py")
    draft_source = _read_text(root / "services/nex-cx/nex_cx/drafts.py")
    main_source = _read_text(root / "services/nex-cx/nex_cx/main.py")
    mo_payload_source = generation_source.split(
        "def build_mo_generation_payload", maxsplit=1
    )[-1].split("\ndef build_generation_execution_record", maxsplit=1)[0]
    generation_migration_source = _read_text(
        root / "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql"
    )
    gap_observations = {
        "provider_prompt_evidence_binding_missing": (
            "evidence_items" not in mo_payload_source
            or "selected_evidence" not in mo_payload_source
        ),
        "provider_output_structure_validation_weak": (
            "CITATION_PATTERN" in draft_source
            and "provider_output_schema" not in draft_source
        ),
        "durable_private_generated_output_missing": not (
            root / "services/nex-cx/nex_cx/generation_private_output.py"
        ).is_file(),
        "sql_generation_runtime_store_missing": (
            "DEFAULT_GENERATION_STORE = GenerationExecutionStore()" in generation_source
            and "store=DEFAULT_GENERATION_STORE" in main_source
            and "SqlAlchemyGenerationRuntimeStore" not in generation_source
        ),
        "idempotent_execution_admission_missing": (
            "idempotency_key" not in generation_source.lower()
            and "idempotency_key" not in generation_migration_source.lower()
        ),
        "restart_safe_generation_read_model_missing": not (
            root / "services/nex-cx/nex_cx/generation_read_model.py"
        ).is_file(),
        "grounded_generation_observability_missing": not (
            root / "services/nex-cx/nex_cx/generation_observability.py"
        ).is_file(),
        "protected_live_grounded_runtime_evidence_missing": not (
            root
            / "scripts/smoke/run_cx_grounded_generation_live_postgres_smoke.py"
        ).is_file(),
    }
    resolution_checks = {
        "provider_prompt_evidence_binding_missing": (
            root / "services/nex-cx/nex_cx/grounded_prompt.py"
        ).is_file(),
        "provider_output_structure_validation_weak": (
            root / "services/nex-cx/nex_cx/grounded_output_validation.py"
        ).is_file(),
        "durable_private_generated_output_missing": (
            root / "services/nex-cx/nex_cx/generation_private_output.py"
        ).is_file(),
        "sql_generation_runtime_store_missing": all(
            (
                (root / "services/nex-cx/nex_cx/generation_repository.py").is_file(),
                (
                    root
                    / "database/nex-cx/migrations/0965_cx_grounded_generation_runtime.sql"
                ).is_file(),
            )
        ),
        "idempotent_execution_admission_missing": (
            root / "services/nex-cx/nex_cx/generation_runtime.py"
        ).is_file(),
        "restart_safe_generation_read_model_missing": (
            root / "services/nex-cx/nex_cx/generation_read_model.py"
        ).is_file(),
        "grounded_generation_observability_missing": (
            root / "services/nex-cx/nex_cx/generation_observability.py"
        ).is_file(),
        "protected_live_grounded_runtime_evidence_missing": (
            root
            / "scripts/smoke/run_cx_grounded_generation_live_postgres_smoke.py"
        ).is_file(),
    }
    gap_checks = {
        name: gap_observations[name] or resolution_checks[name]
        for name in gap_observations
    }
    gap_states = {
        name: "RESOLVED" if resolution_checks[name] else "OPEN"
        for name in gap_observations
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s96_handoff_bound": _group_present(tokens, "s96_handoff"),
        "owner_grounding_admission_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "generation_route",
                "owner_authorization",
                "grounded_boundary",
                "retrieval_quality_guard",
            )
        ),
        "structured_draft_citation_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in ("structured_draft", "citation_validation")
        ),
        "metadata_persistence_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "generation_persistence_contract",
                "generation_table",
                "owner_index",
            )
        ),
        "provider_boundary_confirmed": all(
            _group_present(tokens, group)
            for group in ("mo_client", "current_generation_model")
        ),
        "implementation_gaps_accounted_for": all(gap_checks.values()),
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
    issues.extend(
        {"category": "implementation_gap_unaccounted", "gap": name}
        for name, confirmed in gap_checks.items()
        if not confirmed
    )
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "0961",
        "requirement": "S97",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_grounded_generation_runtime_boundary_failed"
        ),
        "boundary_readiness": "BOUNDARY_CURRENT" if passed else "AUDIT_FAILED",
        "decision": _boundary_decision(),
        "summary": {
            "foundation_count": 5,
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "implementation_gaps": list(gap_observations),
        "slice_plan": [
            "0961_boundary_audit",
            "0962_grounded_prompt_package_evidence_binding",
            "0963_provider_output_citation_validation",
            "0964_durable_private_generation_output",
            "0965_sql_generation_runtime_repository",
            "0966_idempotent_grounded_execution_runtime",
            "0967_restart_safe_generation_read_model",
            "0968_operations_observability_contract_hardening",
            "0969_postgres_live_generation_smoke",
            "0970_s97_closure",
        ],
        "checks": checks,
        "gap_checks": gap_checks,
        "gap_observations": gap_observations,
        "gap_resolutions": resolution_checks,
        "gap_states": gap_states,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": "0962",
    }


def _boundary_decision() -> dict[str, Any]:
    return {
        "feature_scope": "owner_private_grounded_generation_runtime",
        "generation_model": "Qwen3.5-4B",
        "generation_provider_port": 9111,
        "retrieval_input_policy": "owner_admitted_ready_package_only",
        "provider_prompt_policy": "cx_assembled_untrusted_evidence_envelope",
        "provider_output_policy": "citation_validated_structured_draft",
        "private_output_policy": "durable_private_payload_reference",
        "public_persistence_policy": "metadata_hashes_lineage_only",
        "execution_policy": "bounded_synchronous_idempotent_write_through",
        "cross_owner_behavior": "not_found_without_disclosure",
        "observability_policy": "metadata_only_best_effort",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "remote_provider_required_now": False,
        "remote_provider_required_slice": "0969",
        "migration_strategy": "versioned_sql_schema_migrations_runner",
        "deferred_scope": [
            "asynchronous_generation_worker",
            "streaming_generation_transport",
            "automatic_multi_attempt_citation_repair",
            "production_provider_slo_baseline",
        ],
    }


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    matches = [item["present"] for item in tokens if item["group"] == group]
    return bool(matches) and all(matches)


def _read_tree(path: Path, pattern: str) -> str:
    if not path.is_dir():
        return ""
    return "\n".join(
        item.read_text(encoding="utf-8") for item in sorted(path.glob(pattern))
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(result: Mapping[str, Any]) -> str:
    summary = result.get("summary") or {}
    decision = result.get("decision") or {}
    return (
        "cx_grounded_generation_runtime_boundary="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"scope={decision.get('feature_scope', 'unknown')} "
        f"remote_required_now={decision.get('remote_provider_required_now', True)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_grounded_generation_runtime_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
