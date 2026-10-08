#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_s148_alert_persistence_restart import run_alert_persistence_restart
from run_s148_alert_routing import run_alert_routing
from run_s148_contract_mock_acceptance import run_contract_mock_acceptance
from run_s148_mock_notification_delivery import run_mock_notification_delivery
from run_s148_observability_api import run_observability_api
from run_s148_observability_incident_boundary import (
    run_observability_incident_boundary,
)
from run_s148_signal_correlation import run_signal_correlation
from run_s148_slo_evaluation import run_slo_evaluation

SCHEMA_VERSION = "s148_observability_incident_closure.v1"
CANONICAL_PATH = "docs/56_platform_observability_slo_incident_integration.md"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
RUNBOOK_PATH = "docs/runbooks/platform_observability_incident_operations.md"
POSTGRES_EVIDENCE_PATH = "docs/slices/1480_s148_observability_postgres_smoke.md"
OPENAPI_PATH = "contracts/openapi/nex-ag.openapi.yaml"
MIGRATION_PATH = "database/nex-ag/migrations/1477_ag_platform_alert_persistence.sql"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1473", "s148_observability_incident_boundary"),
        ("1474", "s148_signal_correlation"),
        ("1475", "s148_sli_slo_evaluation"),
        ("1476", "s148_alert_lifecycle_routing"),
        ("1477", "s148_alert_persistence_checkpoint"),
        ("1478", "s148_mock_notification_delivery"),
        ("1479", "s148_observability_operations_api"),
        ("1480", "s148_observability_postgres_smoke"),
        ("1481", "s148_contract_mock_acceptance"),
        ("1482", "s148_observability_incident_closure"),
    )
)
RUNNERS = (
    "run_s148_observability_incident_boundary.py",
    "run_s148_signal_correlation.py",
    "run_s148_slo_evaluation.py",
    "run_s148_alert_routing.py",
    "run_s148_alert_persistence_restart.py",
    "run_s148_mock_notification_delivery.py",
    "run_s148_observability_api.py",
    "run_s148_observability_postgres.py",
    "run_s148_contract_mock_acceptance.py",
    "run_s148_observability_incident_closure.py",
)
OPENAPI_PATHS = (
    "/admin/v1/observability/dashboard",
    "/admin/v1/observability/slos",
    "/admin/v1/observability/alerts",
    "/admin/v1/observability/notifications",
    "/admin/v1/observability/alerts/{alert_id}/acknowledge",
    "/admin/v1/observability/alerts/{alert_id}/suppress",
)
TABLES = ("ag_alerts", "ag_notify_outbox", "ag_notify_attempts")


def run_observability_incident_closure(root: Path = ROOT) -> dict[str, Any]:
    required_paths = (
        *SLICE_DOCUMENTS,
        CANONICAL_PATH,
        PLAN_PATH,
        RUNBOOK_PATH,
        POSTGRES_EVIDENCE_PATH,
        OPENAPI_PATH,
        MIGRATION_PATH,
        QUALITY_GATE_PATH,
    )
    presence = {path: (root / path).is_file() for path in required_paths}
    audits = _run_audits(root) if all(presence.values()) else {}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    plan = " ".join(_read_text(root / PLAN_PATH).split())
    runbook = _read_text(root / RUNBOOK_PATH)
    runbook_flat = " ".join(runbook.split())
    postgres_evidence = _read_text(root / POSTGRES_EVIDENCE_PATH)
    openapi = _read_text(root / OPENAPI_PATH)
    migration = _read_text(root / MIGRATION_PATH)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    checks = {
        "repository_documents_and_artifacts_present": all(presence.values()),
        "eight_deterministic_audits_pass": len(audits) == 8
        and all(item.get("status") == "PASS" for item in audits.values()),
        "actual_postgres_evidence_bound": all(
            token in postgres_evidence
            for token in (
                "actual `nex_ag_test`",
                "PostgreSQL smoke: `18/18`",
                "`3` attempts",
                "cleanup residue `0`",
            )
        ),
        "concise_durable_schema_frozen": all(name in migration for name in TABLES)
        and all(len(name) < 32 for name in TABLES),
        "canonical_completion_and_handoff_frozen": all(
            token in canonical
            for token in (
                "Status: S148 complete through Slice 1482.",
                "## Closure Decision",
                "Completion signal: Met.",
                "S149 may execute integrated staging rehearsal",
            )
        ),
        "program_marks_s148_complete_and_s149_active": all(
            token in plan
            for token in (
                "through S148 are complete, S149 is active",
                "## S148 Completion Update",
                "S149 is the next implementation requirement",
                "Production deployment remains unapproved",
            )
        ),
        "runbook_covers_operations_recovery_and_acceptance": all(
            token in runbook
            for token in (
                "## Startup and Readiness",
                "## Normal Operations",
                "## Failure and Recovery",
                "## Protected PostgreSQL Acceptance",
                "## External Activation Checklist",
                "## Single-Host Limitation",
                "## Closure and S149 Handoff",
            )
        ),
        "runbook_references_every_runner": all(name in runbook for name in RUNNERS),
        "openapi_observability_surface_complete": all(
            path in openapi for path in OPENAPI_PATHS
        )
        and "serviceBearer" in openapi,
        "full_gate_registers_every_runner_once": all(
            quality_gate.count(name) == 1 for name in RUNNERS
        ),
        "ten_slice_sequence_complete": len(SLICE_DOCUMENTS) == 10
        and all(presence.get(path) for path in SLICE_DOCUMENTS),
        "privacy_boundary_explicit": all(
            token in runbook
            for token in (
                "Prompts, source documents, generated text, vectors, credentials",
                "complete database URLs",
                "authorization values",
            )
        ),
        "external_activation_remains_honest": all(
            token in canonical + " " + plan + " " + runbook
            for token in ("MOCK_ACCEPTED", "EXTERNAL_NOT_ACTIVATED")
        )
        and "it is not production delivery evidence" in plan,
        "production_and_host_loss_not_claimed": (
            "Production deployment remains unapproved" in canonical
            and "external heartbeat/dead-man receiver" in runbook_flat
            and "time-bounded P1 waiver" in runbook_flat
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1482",
        "slice_range": "1473-1482",
        "requirement": "S148",
        "status": "PASS" if passed else "FAIL",
        "closure_readiness": "READY_FOR_S149" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "audit_statuses": {
            name: item.get("status") for name, item in audits.items()
        },
        "required_paths": presence,
        "summary": {
            "audit_count": len(audits),
            "passed_audit_count": sum(
                item.get("status") == "PASS" for item in audits.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "openapi_path_count": len(OPENAPI_PATHS),
            "alert_table_count": len(TABLES),
        },
        "decision": {
            "observability_framework_complete": passed,
            "protected_postgres_evidence_complete": passed,
            "external_incident_endpoint_activated": False,
            "external_acceptance": "MOCK_ACCEPTED",
            "external_activation": "EXTERNAL_NOT_ACTIVATED",
            "s149_rehearsal_ready": passed,
            "s149_external_delivery_dependency_open": True,
            "production_deployment_approved": False,
            "next_requirement": "S149" if passed else "blocked",
        },
    }


def _run_audits(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {
        "boundary": run_observability_incident_boundary(),
        "signal_correlation": run_signal_correlation(),
        "slo_evaluation": run_slo_evaluation(),
        "alert_routing": run_alert_routing(),
        "persistence_restart": run_alert_persistence_restart(),
        "mock_delivery": run_mock_notification_delivery(),
        "operations_api": run_observability_api(),
        "contract_mock": run_contract_mock_acceptance(),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "s148_observability_incident_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "s148_observability_incident_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/{summary.get('audit_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"paths={summary.get('openapi_path_count', 0)} "
        f"tables={summary.get('alert_table_count', 0)} "
        f"external={decision.get('external_activation', 'unknown')} "
        f"next={decision.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_observability_incident_closure()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
