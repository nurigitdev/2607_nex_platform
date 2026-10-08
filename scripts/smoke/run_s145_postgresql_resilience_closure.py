#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_platform_production_evidence_decision_contract import (  # noqa: E402
    EVIDENCE_FIELDS,
    _forbidden_paths,
)
from run_s145_backup_catalog_retention import run_backup_catalog_retention  # noqa: E402
from run_s145_isolated_restore_guard import run_isolated_restore_guard  # noqa: E402
from run_s145_logical_backup_execution import run_logical_backup_execution  # noqa: E402
from run_s145_postgresql_backup_policy import run_postgresql_backup_policy  # noqa: E402
from run_s145_postgresql_backup_worker import run_postgresql_backup_worker_audit  # noqa: E402
from run_s145_postgresql_compose_rehearsal import run_postgresql_compose_rehearsal  # noqa: E402
from run_s145_postgresql_pitr_plan import run_postgresql_pitr_plan  # noqa: E402
from run_s145_postgresql_resilience_boundary import run_postgresql_resilience_boundary  # noqa: E402


SCHEMA_VERSION = "s145_postgresql_resilience_closure.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
CANONICAL_PATH = "docs/53_platform_postgresql_resilience_disaster_recovery.md"
RUNBOOK_PATH = "docs/runbooks/postgresql_single_host_disaster_recovery.md"
ATTESTATION_PATH = "deployment/postgres/s145-postgres-recovery-attestation.json"
POLICY_PATH = "deployment/postgres/s145-policy.yaml"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s145_postgresql_resilience_closure.py"
PROTECTED_RUNNER = "run_s145_postgresql_recovery_acceptance.py"
ACCEPTED_SOURCE_REVISION = "e432c38ce78e215dc0735f178178d24c4bd4d9bc"
ARTIFACT_PATHS = (
    "deployment/compose/s145-postgres-operations.override.yaml",
    "deployment/oci/postgres-operator.Containerfile",
)
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, str, EvidenceRunner], ...] = (
    (
        "boundary",
        "run_s145_postgresql_resilience_boundary.py",
        run_postgresql_resilience_boundary,
    ),
    (
        "policy",
        "run_s145_postgresql_backup_policy.py",
        run_postgresql_backup_policy,
    ),
    (
        "logical",
        "run_s145_logical_backup_execution.py",
        run_logical_backup_execution,
    ),
    (
        "restore",
        "run_s145_isolated_restore_guard.py",
        run_isolated_restore_guard,
    ),
    (
        "catalog",
        "run_s145_backup_catalog_retention.py",
        run_backup_catalog_retention,
    ),
    (
        "pitr",
        "run_s145_postgresql_pitr_plan.py",
        run_postgresql_pitr_plan,
    ),
    (
        "worker",
        "run_s145_postgresql_backup_worker.py",
        run_postgresql_backup_worker_audit,
    ),
    (
        "compose",
        "run_s145_postgresql_compose_rehearsal.py",
        run_postgresql_compose_rehearsal,
    ),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1443", "s145_postgresql_resilience_boundary"),
        ("1444", "s145_postgresql_backup_policy"),
        ("1445", "s145_logical_backup_execution"),
        ("1446", "s145_isolated_restore_guard"),
        ("1447", "s145_backup_catalog_retention_checkpoint"),
        ("1448", "s145_postgresql_pitr_plan"),
        ("1449", "s145_postgresql_backup_worker"),
        ("1450", "s145_postgresql_compose_rehearsal"),
        ("1451", "s145_postgresql_recovery_acceptance"),
        ("1452", "s145_postgresql_resilience_closure"),
    )
)


def run_s145_postgresql_resilience_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (
        *SLICE_DOCUMENTS,
        PLAN_PATH,
        CANONICAL_PATH,
        RUNBOOK_PATH,
        ATTESTATION_PATH,
        POLICY_PATH,
        *ARTIFACT_PATHS,
    )
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    repository_ready = all(document_presence.values())
    evidence = _run_evidence(root) if repository_ready else {}
    attestation = _load_json(root / ATTESTATION_PATH)
    plan = " ".join(_read_text(root / PLAN_PATH).split())
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    runbook = _read_text(root / RUNBOOK_PATH)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)

    attestation_checks = _mapping(attestation.get("checks"))
    metrics = _mapping(attestation.get("metrics"))
    privacy = _mapping(attestation.get("privacy"))
    rollback = _mapping(attestation.get("rollback"))
    residue = _mapping(attestation.get("residue"))
    dependency_digests = attestation.get("dependency_evidence_digests") or []
    audit_check_count = sum(
        len(_mapping(item.get("checks"))) for item in evidence.values()
    )

    checks = {
        "all_eight_repository_audits_passed": len(evidence) == 8
        and all(item.get("status") == "PASS" for item in evidence.values()),
        "all_slice_canonical_runbook_attestation_documents_present": (
            repository_ready
        ),
        "closure_registered_once_in_full_gate": quality_gate.count(
            CLOSURE_RUNNER
        )
        == 1,
        "protected_runner_registered_once_in_full_gate": quality_gate.count(
            PROTECTED_RUNNER
        )
        == 1,
        "canonical_completion_and_handoffs_frozen": all(
            token in canonical
            for token in (
                "Status: S145 complete through Slice 1452.",
                "Production deployment remains unapproved.",
                "## Closure Decision",
                "## S146, S148, and S149 Handoff",
                "Completion signal: Met.",
            )
        ),
        "program_marks_s145_complete_and_s146_active": all(
            token in plan
            for token in (
                "S145 is complete and its S148/S149 dependencies are ready",
                "S146 is the next implementation requirement",
                "## S145 Completion Update",
                "production deployment remains unapproved",
            )
        ),
        "repository_inventory_exact": (
            audit_check_count == 64
            and _summary(evidence, "boundary").get("gap_count") == 8
            and _summary(evidence, "boundary").get("database_count") == 5
            and _mapping(_mapping(evidence.get("compose")).get("metrics")).get(
                "service_count"
            )
            == 5
        ),
        "attestation_shape_digest_and_artifacts_valid": (
            set(attestation) == set(EVIDENCE_FIELDS)
            and attestation.get("evidence_digest") == _evidence_digest(attestation)
            and attestation.get("configuration_digest")
            == _file_digest(root / POLICY_PATH)
            and attestation.get("artifact_digests")
            == [_file_digest(root / path) for path in ARTIFACT_PATHS]
            and re.fullmatch(
                r"[0-9a-f]{40}", str(attestation.get("source_revision") or "")
            )
            is not None
        ),
        "attestation_identity_matches_protected_execution": (
            attestation.get("requirement_id") == "S145"
            and attestation.get("environment_class") == "protected_test"
            and attestation.get("execution_mode") == "protected"
            and attestation.get("actual_execution") is True
            and attestation.get("source_revision") == ACCEPTED_SOURCE_REVISION
            and len(dependency_digests) == 2
        ),
        "attestation_acceptance_checks_pass": len(attestation_checks) == 16
        and all(value is True for value in attestation_checks.values()),
        "attestation_metrics_exact": metrics
        == {
            "database_count": 5,
            "migration_count": 95,
            "table_count": 121,
            "required_extension_count": 3,
            "wal_segment_count": 6,
            "elapsed_seconds": 13.326,
            "protected_check_count": 10,
            "protected_pytest_passed": 3,
            "protected_pytest_skipped": 0,
        },
        "attestation_privacy_rollback_and_residue_valid": (
            not _forbidden_paths(attestation)
            and privacy == {"raw_value_count": 0, "violation_count": 0}
            and rollback.get("drill_status") == "PASS"
            and _mapping(rollback.get("residue_counts")) == residue
            and residue
            == {
                "source_marker_table_count": 0,
                "temporary_process_count": 0,
                "production_resource_count": 0,
            }
        ),
        "single_host_no_ha_operator_cutover_preserved": (
            attestation_checks.get("automatic_failover_disabled") is True
            and _mapping(rollback.get("recovery_metrics")).get(
                "operator_cutover_required"
            )
            is True
            and "automatic failover" in runbook.lower()
            and "operator" in runbook.lower()
        ),
        "runbook_reproduces_audits_acceptance_closure_and_full_gate": all(
            script_name in runbook for _, script_name, _ in EVIDENCE_RUNNERS
        )
        and PROTECTED_RUNNER in runbook
        and CLOSURE_RUNNER in runbook
        and "scripts/quality/run_quality_gate.sh" in runbook,
        "production_sized_recovery_and_approval_not_claimed": (
            attestation_checks.get("production_contact_absent") is True
            and attestation_checks.get("production_approval_absent") is True
            and "S149" in runbook
            and "production-sized" in runbook
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1452",
        "slice_range": "1443-1452",
        "requirement": "S145",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s145_postgresql_resilience_closure_failed",
        "closure_readiness": "READY_FOR_S146" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "required_documents": document_presence,
        "summary": {
            "audit_count": len(evidence),
            "passed_audit_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "audit_check_count": audit_check_count,
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "gap_count": int(_summary(evidence, "boundary").get("gap_count") or 0),
            "database_count": int(metrics.get("database_count") or 0),
            "wal_segment_count": int(metrics.get("wal_segment_count") or 0),
            "residue_count": sum(int(value) for value in residue.values()),
        },
        "decision": {
            "single_host_cold_recovery_accepted": passed,
            "high_availability_implemented": False,
            "automatic_failover_implemented": False,
            "operator_cutover_required": True,
            "actual_test_databases_used": metrics.get("database_count") == 5,
            "source_controlled_attestation_present": bool(attestation),
            "raw_protected_report_tracked": False,
            "production_resources_contacted": False,
            "production_deployment_approved": False,
            "production_sized_recovery_deferred_to_s149": True,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S146" if passed else "blocked",
            "s148_dependency_ready": passed,
            "s149_dependency_ready": passed,
        },
    }


def _run_evidence(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {name: runner() for name, _, runner in EVIDENCE_RUNNERS}


def _summary(
    evidence: Mapping[str, Mapping[str, Any]], name: str
) -> dict[str, Any]:
    return _mapping(_mapping(evidence.get(name)).get("summary"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return _mapping(value)


def _file_digest(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError:
        return ""
    return f"sha256:{sha256(payload).hexdigest()}"


def _evidence_digest(evidence: Mapping[str, Any]) -> str:
    canonical = {
        key: value for key, value in evidence.items() if key != "evidence_digest"
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "s145_postgresql_resilience_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s145_postgresql_resilience_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"databases={summary.get('database_count', 0)} "
        f"wal={summary.get('wal_segment_count', 0)} "
        f"residue={summary.get('residue_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s145_postgresql_resilience_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
