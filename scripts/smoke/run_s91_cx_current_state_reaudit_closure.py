#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_PATH))

from run_cx_capability_traceability_inventory import (  # noqa: E402
    run_cx_capability_traceability_inventory as run_traceability,
)
from run_cx_contract_api_drift_audit import (  # noqa: E402
    run_cx_contract_api_drift_audit as run_contract_drift,
)
from run_cx_current_state_reaudit_boundary import (  # noqa: E402
    run_cx_current_state_reaudit_boundary as run_boundary,
)
from run_cx_database_drift_audit import (  # noqa: E402
    run_cx_database_drift_audit as run_database_drift,
)
from run_cx_ownership_enforcement_audit import (  # noqa: E402
    run_cx_ownership_enforcement_audit as run_ownership,
)
from run_cx_persistence_gap_rebaseline import (  # noqa: E402
    run_cx_persistence_gap_rebaseline as run_persistence,
)
from run_cx_private_payload_boundary_decision import (  # noqa: E402
    run_cx_private_payload_boundary_decision as run_private_payload,
)
from run_cx_runtime_coupling_audit import (  # noqa: E402
    run_cx_runtime_coupling_audit as run_runtime_coupling,
)


SCHEMA_VERSION = "s91_cx_current_state_reaudit_closure.v1"
SLICE_RANGE = "0901-0910"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_EVIDENCE_DOC = "docs/slices/0909_cx_postgresql_reaudit_privacy_runbook.md"
REQUIRED_FILES = (
    "services/nex-cx/nex_cx/current_state_traceability.py",
    "services/nex-cx/nex_cx/persistence_audit.py",
    "services/nex-cx/nex_cx/private_payload_boundary.py",
    "services/nex-cx/nex_cx/ownership_enforcement_audit.py",
    "services/nex-cx/nex_cx/runtime_coupling_audit.py",
    "services/nex-cx/nex_cx/database_drift_audit.py",
    "services/nex-cx/nex_cx/contract_api_drift_audit.py",
    "services/nex-cx/nex_cx/postgres_reaudit.py",
    "scripts/smoke/run_cx_current_state_postgres_reaudit.py",
    "scripts/smoke/run_s91_cx_current_state_reaudit_closure.py",
    "tests/test_s91_cx_current_state_reaudit_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0901", "cx_current_state_reaudit_boundary"),
            ("0902", "cx_capability_traceability_inventory"),
            ("0903", "cx_persistence_gap_rebaseline"),
            ("0904", "cx_private_payload_storage_boundary_decision"),
            ("0905", "cx_ownership_permission_enforcement_audit"),
            ("0906", "cx_runtime_coupling_refactoring_checkpoint"),
            ("0907", "cx_database_migration_drift_audit"),
            ("0908", "cx_contract_api_drift_audit"),
            ("0909", "cx_postgresql_reaudit_privacy_runbook"),
            ("0910", "s91_cx_current_state_reaudit_closure"),
        )
    ),
)
TOKEN_CHECKS = (
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_cx_current_state_reaudit_boundary.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_cx_current_state_postgres_reaudit.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s91_cx_current_state_reaudit_closure.py",
    ),
    ("postgres_pass", POSTGRES_EVIDENCE_DOC, "actual PostgreSQL: PASS"),
    ("postgres_database", POSTGRES_EVIDENCE_DOC, "database=nex_cx_test"),
    ("postgres_migrations", POSTGRES_EVIDENCE_DOC, "migrations=13/13"),
    ("postgres_privacy", POSTGRES_EVIDENCE_DOC, "private columns=0"),
    ("postgres_checks", POSTGRES_EVIDENCE_DOC, "failed checks=0"),
    (
        "docs_index",
        "docs/README.md",
        "0910_s91_cx_current_state_reaudit_closure.md",
    ),
)


def run_s91_cx_current_state_reaudit_closure(
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
        "persistence": _safe_evidence(run_persistence),
        "private_payload": _safe_evidence(run_private_payload),
        "ownership": _safe_evidence(lambda: run_ownership(root)),
        "runtime_coupling": _safe_evidence(lambda: run_runtime_coupling(root)),
        "database_drift": _safe_evidence(lambda: run_database_drift(root)),
        "contract_drift": _safe_evidence(lambda: run_contract_drift(root)),
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
    handoff = _s92_handoff()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_audits_passed": all(
            evidence.get("status") == "PASS" for evidence in audits.values()
        ),
        "all_cx_requirements_traceable": (
            summaries["traceability"].get("requirement_count") == 8
            and summaries["traceability"].get("traceable_count") == 8
        ),
        "metadata_persistence_rebaselined": (
            summaries["persistence"].get("durable_metadata_gap_count") == 0
        ),
        "private_payload_boundary_frozen": (
            summaries["private_payload"].get("adapter_required_count") == 4
        ),
        "ownership_gaps_confirmed": (
            audits["ownership"].get("enforcement_readiness") == "GAPS_CONFIRMED"
            and summaries["ownership"].get("high_risk_gap_count") == 5
        ),
        "targeted_refactoring_confirmed": (
            audits["runtime_coupling"].get("refactoring_readiness")
            == "TARGETED_REFACTOR_REQUIRED_BEFORE_S92_FEATURES"
            and summaries["runtime_coupling"].get("refactor_required_count") == 5
        ),
        "static_database_chain_clean": (
            audits["database_drift"].get("database_readiness")
            == "STATIC_CHAIN_CLEAN_RUNTIME_DATABASE_PENDING"
        ),
        "contract_drift_quantified": (
            audits["contract_drift"].get("contract_readiness") == "GAPS_CONFIRMED"
            and summaries["contract_drift"].get("drift_count") == 6
        ),
        "actual_postgres_evidence_passed": all(postgres_evidence.values()),
        "s92_handoff_ordered": (
            handoff["target_requirement"] == "S92"
            and [item["priority"] for item in handoff["work_items"]]
            == ["P0", "P0", "P0", "P0", "P1", "P1"]
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
        "slice": "0910",
        "slice_range": SLICE_RANGE,
        "requirement": "S91",
        "status": status,
        "failure_code": None if status == "PASS" else "s91_cx_reaudit_closure_failed",
        "closure_readiness": (
            "READY_FOR_TARGETED_S92_REFACTORING"
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
            "confirmed_high_risk_ownership_gap_count": summaries[
                "ownership"
            ].get("high_risk_gap_count", 0),
            "required_refactoring_count": summaries["runtime_coupling"].get(
                "refactor_required_count", 0
            ),
            "private_adapter_count": summaries["private_payload"].get(
                "adapter_required_count", 0
            ),
            "contract_drift_count": summaries["contract_drift"].get(
                "drift_count", 0
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
        "next_requirement": "S92",
    }


def _s92_handoff() -> dict[str, Any]:
    return {
        "target_requirement": "S92",
        "title": "CX ownership, runtime dependency, and private payload hardening",
        "work_items": [
            {
                "priority": "P0",
                "work_item": "centralize CxAccessContext derivation and authorization",
            },
            {
                "priority": "P0",
                "work_item": "replace import-time singleton mutation with app-owned dependencies",
            },
            {
                "priority": "P0",
                "work_item": "introduce private text and vector storage capability ports",
            },
            {
                "priority": "P0",
                "work_item": "enforce owner scope on jobs, processing, retrieval, and generation",
            },
            {
                "priority": "P1",
                "work_item": "close CX OpenAPI and fixture coverage drift",
            },
            {
                "priority": "P1",
                "work_item": "repeat actual PostgreSQL privacy and rollback smoke",
            },
        ],
        "migration_strategy": {
            "canonical": "versioned_sql_schema_migrations_runner",
            "alembic_status": "DEFERRED_UNTIL_DELIBERATE_BASELINE_TRANSITION",
            "alembic_parallel_history_allowed": False,
        },
        "guardrails": [
            "refactor before adding S92 feature behavior",
            "preserve public route behavior one slice at a time",
            "keep deterministic memory adapters for regression",
            "keep public PostgreSQL metadata-only",
            "run actual nex_cx_test smoke for schema-affecting slices",
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
        "s91_cx_current_state_reaudit_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"ownership_gaps={summary.get('confirmed_high_risk_ownership_gap_count', 0)} "
        f"refactors={summary.get('required_refactoring_count', 0)} "
        f"contract_drift={summary.get('contract_drift_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s91_cx_current_state_reaudit_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
