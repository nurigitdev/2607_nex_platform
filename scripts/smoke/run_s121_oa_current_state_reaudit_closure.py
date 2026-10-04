#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_oa_capability_traceability_inventory import (
    run_oa_capability_traceability_inventory as run_traceability,
)
from run_oa_contract_api_drift_audit import (
    run_oa_contract_api_drift_audit as run_contract_drift,
)
from run_oa_credential_session_security_audit import (
    run_oa_credential_session_security_audit as run_security,
)
from run_oa_current_state_reaudit_boundary import (
    run_oa_current_state_reaudit_boundary as run_boundary,
)
from run_oa_database_drift_audit import (
    run_oa_database_drift_audit as run_database_drift,
)
from run_oa_identity_lifecycle_audit import (
    run_oa_identity_lifecycle_audit as run_lifecycle,
)
from run_oa_projection_privacy_refactor_checkpoint import (
    run_oa_projection_privacy_checkpoint as run_projection_privacy,
)
from run_oa_trust_coupling_audit import (
    run_oa_trust_coupling_audit as run_trust_coupling,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s121_oa_current_state_reaudit_closure.v1"
SLICE_RANGE = "1202-1211"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_EVIDENCE_DOC = "docs/slices/1210_oa_current_state_postgresql_reaudit.md"

REQUIRED_FILES = (
    "services/nex-oa/nex_oa/current_state_traceability.py",
    "services/nex-oa/nex_oa/database_drift_audit.py",
    "services/nex-oa/nex_oa/identity_lifecycle_audit.py",
    "services/nex-oa/nex_oa/credential_session_security_audit.py",
    "services/nex-oa/nex_oa/contract_api_drift_audit.py",
    "services/nex-oa/nex_oa/trust_coupling_audit.py",
    "services/nex-oa/nex_oa/projection_privacy_checkpoint.py",
    "services/nex-oa/nex_oa/postgres_reaudit.py",
    "scripts/smoke/run_oa_current_state_postgres_reaudit.py",
    "scripts/smoke/run_s121_oa_current_state_reaudit_closure.py",
    "tests/test_s121_oa_current_state_reaudit_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1202", "oa_current_state_reaudit_boundary"),
            ("1203", "oa_capability_traceability_inventory"),
            ("1204", "oa_persistence_migration_drift_audit"),
            ("1205", "oa_identity_membership_lifecycle_audit"),
            ("1206", "oa_credential_session_security_audit"),
            ("1207", "oa_contract_api_drift_audit"),
            ("1208", "oa_cross_service_trust_coupling_audit"),
            ("1209", "oa_projection_privacy_refactoring_checkpoint"),
            ("1210", "oa_current_state_postgresql_reaudit"),
            ("1211", "s121_oa_current_state_reaudit_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_oa_current_state_reaudit_boundary.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_oa_current_state_postgres_reaudit.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s121_oa_current_state_reaudit_closure.py",
    ),
    ("postgres_database", POSTGRES_EVIDENCE_DOC, "`nex_oa_test` / `nex_oa_user`"),
    ("postgres_migrations", POSTGRES_EVIDENCE_DOC, "Migrations: `11/11`"),
    ("postgres_workflow", POSTGRES_EVIDENCE_DOC, "all 22 checks passed"),
    (
        "postgres_cleanup",
        POSTGRES_EVIDENCE_DOC,
        "post-cleanup residue counts for all five were 0",
    ),
    (
        "docs_index",
        "docs/README.md",
        "1211_s121_oa_current_state_reaudit_closure.md",
    ),
)


def run_s121_oa_current_state_reaudit_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    audits = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "traceability": _safe_evidence(lambda: run_traceability(root)),
        "database_drift": _safe_evidence(lambda: run_database_drift(root)),
        "lifecycle": _safe_evidence(lambda: run_lifecycle(root)),
        "security": _safe_evidence(lambda: run_security(root)),
        "contract_drift": _safe_evidence(lambda: run_contract_drift(root)),
        "trust_coupling": _safe_evidence(lambda: run_trust_coupling(root)),
        "projection_privacy": _safe_evidence(
            lambda: run_projection_privacy(root)
        ),
    }
    summaries = {
        name: _mapping(evidence.get("summary"))
        for name, evidence in audits.items()
    }
    postgres_evidence = {
        item["name"]: item["present"]
        for item in token_checks
        if item["name"].startswith("postgres_")
    }
    handoff = _s122_handoff()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_audits_passed": all(
            evidence.get("status") == "PASS" for evidence in audits.values()
        ),
        "boundary_plan_completed": (
            len(audits["boundary"].get("slice_plan") or ()) == 10
            and audits["boundary"].get("decision", {}).get("next_requirement")
            == "S122"
        ),
        "all_oa_requirements_traceable": (
            summaries["traceability"].get("requirement_count") == 5
            and summaries["traceability"].get("traceable_count") == 5
            and summaries["traceability"].get("partial_count") == 4
        ),
        "database_chain_clean": (
            summaries["database_drift"].get("migration_count", 0) >= 11
            and summaries["database_drift"].get("overlength_identifier_count") == 0
        ),
        "lifecycle_gaps_quantified": (
            summaries["lifecycle"].get("gap_count", 99) <= 4
            and summaries["lifecycle"].get("stale_projection_count") == 0
        ),
        "security_gaps_quantified": (
            summaries["security"].get("control_count") == 8
            and summaries["security"].get("gap_count", 99) <= 5
            and summaries["security"].get("partial_count", 99) <= 1
            and sum(
                int(summaries["security"].get(name) or 0)
                for name in ("implemented_count", "partial_count", "gap_count")
            )
            == summaries["security"].get("control_count")
        ),
        "contract_drift_quantified": (
            summaries["contract_drift"].get("drift_count", 99) <= 25
            and summaries["contract_drift"].get("missing_openapi_operation_count")
            <= 23
        ),
        "trust_refactoring_quantified": (
            int(summaries["trust_coupling"].get("refactor_required_count") or 99)
            <= 4
            and int(summaries["trust_coupling"].get("hardened_count") or 0) >= 1
            and summaries["trust_coupling"].get("high_risk_count") == 2
        ),
        "projection_privacy_repaired": (
            summaries["projection_privacy"].get("repair_count") == 5
            and summaries["projection_privacy"].get("forbidden_stale_count") == 0
        ),
        "actual_postgres_evidence_passed": (
            bool(postgres_evidence) and all(postgres_evidence.values())
        ),
        "s122_handoff_ordered": (
            handoff["target_requirement"] == "S122"
            and [item["priority"] for item in handoff["work_items"]]
            == ["P0", "P0", "P0", "P0", "P1", "P1", "P1", "P1", "P2", "P2"]
        ),
        "single_migration_history_preserved": (
            handoff["migration_strategy"]["canonical"]
            == "versioned_sql_schema_migrations_runner"
            and handoff["migration_strategy"]["parallel_history_allowed"] is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1211",
        "slice_range": SLICE_RANGE,
        "requirement": "S121",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s121_oa_reaudit_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_TARGETED_S122_HARDENING"
            if status == "PASS"
            else "BLOCKED"
        ),
        "feature_readiness": "CONFIRMED_GAPS_NOT_PRODUCTION_AUTH_COMPLETE",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "audit_count": len(audits),
            "passed_audit_count": sum(
                evidence.get("status") == "PASS" for evidence in audits.values()
            ),
            "traceable_requirement_count": summaries["traceability"].get(
                "traceable_count", 0
            ),
            "lifecycle_gap_count": summaries["lifecycle"].get("gap_count", 0),
            "security_gap_count": summaries["security"].get("gap_count", 0),
            "contract_drift_count": summaries["contract_drift"].get(
                "drift_count", 0
            ),
            "trust_refactor_count": summaries["trust_coupling"].get(
                "refactor_required_count", 0
            ),
            "repaired_surface_count": summaries["projection_privacy"].get(
                "repair_count", 0
            ),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "audit_statuses": {
            name: evidence.get("status") for name, evidence in audits.items()
        },
        "postgres_evidence": postgres_evidence,
        "handoff": handoff,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S122",
    }


def _s122_handoff() -> dict[str, Any]:
    return {
        "target_requirement": "S122",
        "title": "OA production identity trust and security hardening",
        "work_items": [
            {
                "priority": "P0",
                "work_item": "replace unsigned mock service-token fallback with fail-closed signing and JWKS verification",
            },
            {
                "priority": "P0",
                "work_item": "introduce route-specific service scopes and dedicated bootstrap administration authorization",
            },
            {
                "priority": "P0",
                "work_item": "replace deterministic session ids and implement atomic failed-login lockout",
            },
            {
                "priority": "P0",
                "work_item": "make OA-backed auth and secure browser cookies the production defaults",
            },
            {
                "priority": "P1",
                "work_item": "add Argon2id migration, login-time rehash, password rotation, and reset transitions",
            },
            {
                "priority": "P1",
                "work_item": "add subject and membership transitions with deprovision session revocation",
            },
            {
                "priority": "P1",
                "work_item": "emit safe auth audit events and compose cross-service retry and admission policy",
            },
            {
                "priority": "P1",
                "work_item": "close OA OpenAPI operation coverage and negative fixture drift",
            },
            {
                "priority": "P2",
                "work_item": "decide group registry and group membership persistence boundaries",
            },
            {
                "priority": "P2",
                "work_item": "retain SSO, MFA, and recovery as explicit post-MVP enterprise identity scope",
            },
        ],
        "migration_strategy": {
            "canonical": "versioned_sql_schema_migrations_runner",
            "alembic_status": "NOT_CONFIGURED",
            "parallel_history_allowed": False,
        },
        "guardrails": [
            "refactor trust and security boundaries before new identity features",
            "preserve stable OA subject references and service HTTP boundaries",
            "retain deterministic memory adapters for fast regression",
            "keep passwords tokens and endpoint internals out of evidence",
            "run actual nex_oa_test smoke for schema or identity workflow changes",
            "DGX providers remain outside the OA hardening boundary",
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
        "s121_oa_current_state_reaudit_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"lifecycle_gaps={summary.get('lifecycle_gap_count', 0)} "
        f"security_gaps={summary.get('security_gap_count', 0)} "
        f"contract_drift={summary.get('contract_drift_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s121_oa_current_state_reaudit_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
