#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_ae_auth_ownership_privacy_audit import (
    run_ae_auth_ownership_privacy_audit as run_ownership,
)
from run_ae_capability_traceability_inventory import (
    run_ae_capability_traceability_inventory as run_traceability,
)
from run_ae_contract_api_drift_audit import (
    run_ae_contract_api_drift_audit as run_contract_drift,
)
from run_ae_current_state_reaudit_boundary import (
    run_ae_current_state_reaudit_boundary as run_boundary,
)
from run_ae_database_drift_audit import (
    run_ae_database_drift_audit as run_database_drift,
)
from run_ae_persistence_gap_rebaseline import (
    run_ae_persistence_gap_rebaseline as run_persistence,
)
from run_ae_runtime_coupling_audit import (
    run_ae_runtime_coupling_audit as run_runtime_coupling,
)
from run_ae_web_runtime_audit import (
    run_ae_web_runtime_audit as run_web_runtime,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s101_ae_current_state_reaudit_closure.v1"
SLICE_RANGE = "1002-1011"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_EVIDENCE_DOC = (
    "docs/slices/1010_ae_current_state_postgresql_browser_reaudit.md"
)

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/current_state_traceability.py",
    "services/nex-ae-api/nex_ae_api/persistence_audit.py",
    "services/nex-ae-api/nex_ae_api/ownership_privacy_audit.py",
    "services/nex-ae-api/nex_ae_api/runtime_coupling_audit.py",
    "services/nex-ae-api/nex_ae_api/database_drift_audit.py",
    "services/nex-ae-api/nex_ae_api/contract_api_drift_audit.py",
    "services/nex-ae-api/nex_ae_api/web_runtime_audit.py",
    "services/nex-ae-api/nex_ae_api/postgres_reaudit.py",
    "scripts/smoke/run_ae_current_state_postgres_reaudit.py",
    "scripts/smoke/run_s101_ae_current_state_reaudit_closure.py",
    "tests/test_s101_ae_current_state_reaudit_closure.py",
    "docs/runbooks/ae_current_state_reaudit_privacy.md",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1002", "ae_current_state_reaudit_boundary"),
            ("1003", "ae_capability_traceability_inventory"),
            ("1004", "ae_persistence_gap_rebaseline"),
            ("1005", "ae_auth_ownership_privacy_audit"),
            ("1006", "ae_runtime_coupling_refactoring_checkpoint"),
            ("1007", "ae_database_migration_drift_audit"),
            ("1008", "ae_contract_api_drift_audit"),
            ("1009", "ae_web_runtime_i18n_accessibility_drift_audit"),
            ("1010", "ae_current_state_postgresql_browser_reaudit"),
            ("1011", "s101_ae_current_state_reaudit_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_ae_current_state_reaudit_boundary.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_ae_current_state_postgres_reaudit.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s101_ae_current_state_reaudit_closure.py",
    ),
    ("postgres_database", POSTGRES_EVIDENCE_DOC, "database=nex_ae_test"),
    ("postgres_migrations", POSTGRES_EVIDENCE_DOC, "migrations=22/22"),
    ("postgres_browser", POSTGRES_EVIDENCE_DOC, "browser=PASS"),
    ("postgres_privacy", POSTGRES_EVIDENCE_DOC, "forbidden_columns=0"),
    ("postgres_checks", POSTGRES_EVIDENCE_DOC, "failed_checks=0"),
    (
        "docs_index",
        "docs/README.md",
        "1011_s101_ae_current_state_reaudit_closure.md",
    ),
)


def run_s101_ae_current_state_reaudit_closure(
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
        "persistence": _safe_evidence(lambda: run_persistence(root)),
        "ownership": _safe_evidence(lambda: run_ownership(root)),
        "runtime_coupling": _safe_evidence(lambda: run_runtime_coupling(root)),
        "database_drift": _safe_evidence(lambda: run_database_drift(root)),
        "contract_drift": _safe_evidence(lambda: run_contract_drift(root)),
        "web_runtime": _safe_evidence(lambda: run_web_runtime(root)),
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
    handoff = _s102_handoff()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_audits_passed": all(
            evidence.get("status") == "PASS" for evidence in audits.values()
        ),
        "boundary_plan_completed": (
            len(audits["boundary"].get("slice_plan") or ()) == 10
            and audits["boundary"].get("decision", {}).get("next_requirement")
            == "S102"
        ),
        "all_ae_requirements_traceable": (
            summaries["traceability"].get("requirement_count") == 11
            and summaries["traceability"].get("traceable_count") == 11
        ),
        "persistence_gaps_confirmed": (
            summaries["persistence"].get("gap_count") == 7
            and audits["persistence"].get("checkpoint_status") == "GAPS_CONFIRMED"
        ),
        "ownership_gaps_confirmed": (
            summaries["ownership"].get("high_risk_count", 4) <= 3
            and audits["ownership"].get("readiness") == "GAPS_CONFIRMED"
        ),
        "ordered_refactoring_confirmed": (
            summaries["runtime_coupling"].get("refactor_required_count", 9) <= 8
            and audits["runtime_coupling"].get("refactoring_readiness")
            == "ORDERED_REFACTOR_REQUIRED_BEFORE_NEW_AE_FEATURES"
        ),
        "database_drift_quantified": (
            summaries["database_drift"].get("overlength_identifier_count") == 8
            and audits["database_drift"].get("database_readiness")
            == "STATIC_CHAIN_VALID_DRIFT_REMEDIATION_REQUIRED"
        ),
        "contract_drift_quantified": (
            summaries["contract_drift"].get("drift_count") == 33
            and audits["contract_drift"].get("contract_readiness")
            == "GAPS_CONFIRMED"
        ),
        "web_gaps_quantified": (
            summaries["web_runtime"].get("refactor_required_count", 5) <= 4
            and audits["web_runtime"].get("web_readiness") == "GAPS_CONFIRMED"
        ),
        "actual_postgres_browser_evidence_passed": all(
            postgres_evidence.values()
        ),
        "s102_handoff_ordered": (
            handoff["target_requirement"] == "S102"
            and [item["priority"] for item in handoff["work_items"]]
            == ["P0", "P0", "P1", "P1", "P1", "P1", "P2", "P2"]
        ),
        "single_migration_history_frozen": (
            handoff["migration_strategy"]["canonical"]
            == "versioned_sql_schema_migrations_runner"
            and handoff["migration_strategy"]["alembic_parallel_history_allowed"]
            is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1011",
        "slice_range": SLICE_RANGE,
        "requirement": "S101",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s101_ae_reaudit_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_TARGETED_S102_HARDENING"
            if status == "PASS"
            else "BLOCKED"
        ),
        "feature_readiness": "CONFIRMED_GAPS_NOT_FEATURE_COMPLETE",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "audit_count": len(audits),
            "passed_audit_count": sum(
                evidence.get("status") == "PASS" for evidence in audits.values()
            ),
            "persistence_gap_count": summaries["persistence"].get("gap_count", 0),
            "high_risk_ownership_gap_count": summaries["ownership"].get(
                "high_risk_count", 0
            ),
            "required_refactoring_count": summaries["runtime_coupling"].get(
                "refactor_required_count", 0
            ),
            "database_identifier_drift_count": summaries["database_drift"].get(
                "overlength_identifier_count", 0
            ),
            "contract_drift_count": summaries["contract_drift"].get(
                "drift_count", 0
            ),
            "web_refactor_count": summaries["web_runtime"].get(
                "refactor_required_count", 0
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
        "postgres_browser_evidence": postgres_evidence,
        "handoff": handoff,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S102",
    }


def _s102_handoff() -> dict[str, Any]:
    return {
        "target_requirement": "S102",
        "title": "AE ownership, persistence, contract, and Web hardening",
        "work_items": [
            {
                "priority": "P0",
                "work_item": "centralize browser-claim owner authorization",
            },
            {
                "priority": "P0",
                "work_item": "decide durable schemas and adapters for four core gaps",
            },
            {
                "priority": "P1",
                "work_item": "wire prompt registry and analytics persistent adapters",
            },
            {
                "priority": "P1",
                "work_item": "introduce app-factory-owned AE runtime dependencies",
            },
            {
                "priority": "P1",
                "work_item": "canonicalize PostgreSQL identifiers and duplicate indexes",
            },
            {
                "priority": "P1",
                "work_item": "close OpenAPI and fixture coverage drift",
            },
            {
                "priority": "P2",
                "work_item": "split Web composition and add i18n/accessibility automation",
            },
            {
                "priority": "P2",
                "work_item": "repeat actual PostgreSQL and browser privacy smoke",
            },
        ],
        "migration_strategy": {
            "canonical": "versioned_sql_schema_migrations_runner",
            "alembic_status": "DEFERRED_UNTIL_DELIBERATE_BASELINE_TRANSITION",
            "alembic_parallel_history_allowed": False,
        },
        "guardrails": [
            "refactor before adding new browser-facing feature behavior",
            "preserve public routes and owner-not-found behavior per slice",
            "retain deterministic memory adapters for regression",
            "keep private payloads out of evidence output",
            "run actual nex_ae_test smoke for schema-affecting slices",
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
        "s101_ae_current_state_reaudit_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"persistence_gaps={summary.get('persistence_gap_count', 0)} "
        f"ownership_gaps={summary.get('high_risk_ownership_gap_count', 0)} "
        f"contract_drift={summary.get('contract_drift_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s101_ae_current_state_reaudit_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
