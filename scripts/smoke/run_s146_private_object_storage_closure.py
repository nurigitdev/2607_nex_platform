#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_platform_production_evidence_decision_contract import (
    EVIDENCE_FIELDS,
    _forbidden_paths,
)
from run_s146_object_storage_compose import (
    run_object_storage_compose,
)
from run_s146_private_object_storage_boundary import (
    run_private_object_storage_boundary,
)

SCHEMA_VERSION = "s146_private_object_storage_closure.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
CANONICAL_PATH = "docs/54_platform_private_object_storage.md"
RUNBOOK_PATH = "docs/runbooks/private_object_storage_operations.md"
ATTESTATION_PATH = (
    "deployment/object-storage/s146-rustfs-acceptance-attestation.json"
)
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s146_private_object_storage_closure.py"
PROTECTED_RUNNER = "run_s146_object_storage_acceptance.py"
ACCEPTED_SOURCE_REVISION = "468961349c404696c708f3bc04b96ea3f0eed4d1"
CONFIGURATION_PATH = "deployment/compose/s146-object-storage.override.yaml"
ARTIFACT_PATHS = (
    "deployment/compose/traefik/s146-dynamic.yaml",
    "services/_shared/nex_runtime/object_storage.py",
    "services/_shared/nex_runtime/object_storage_lifecycle.py",
    "services/_shared/nex_runtime/rustfs_iam.py",
    "scripts/smoke/run_s146_object_storage_acceptance.py",
)
DEPENDENCY_EVIDENCE_DIGESTS = (
    "sha256:257810a76069c8814b7a1ba1cec69cc5b96f935866f7a95d7417be048941fd83",
    "sha256:cedac783308fb720c09fabf1ef5fb3789b9d80845c81498ad9bc4e161a074d52",
    "sha256:6d92326c90e408e562af8032f9af09907daee0e564b840959957182ccf8919d7",
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1453", "s146_private_object_storage_boundary"),
        ("1454", "s146_s3_client_foundation"),
        ("1455", "s146_cx_private_text_adapter"),
        ("1456", "s146_cx_document_blob_adapter"),
        ("1457", "s146_ae_private_payload_adapter"),
        ("1458", "s146_object_storage_migration"),
        ("1459", "s146_object_storage_lifecycle"),
        ("1460", "s146_object_storage_compose"),
        ("1461", "s146_object_storage_protected_acceptance"),
        ("1462", "s146_private_object_storage_closure"),
    )
)
RUNBOOK_RUNNERS = (
    "run_s146_private_object_storage_boundary.py",
    "run_s146_object_storage_migration.py",
    "run_s146_object_storage_lifecycle.py",
    "run_s146_object_storage_compose.py",
    PROTECTED_RUNNER,
    CLOSURE_RUNNER,
)
EXPECTED_METRICS = {
    "database_count": 5,
    "metadata_service_count": 2,
    "managed_reference_count": 20,
    "bucket_count": 2,
    "lifecycle_rule_count": 6,
    "service_identity_count": 2,
    "cross_bucket_deny_count": 2,
    "adapter_round_trip_count": 3,
    "migration_owner_count": 2,
    "migration_item_count": 2,
    "restored_object_count": 1,
    "removed_version_count": 9,
    "protected_check_count": 26,
}
EXPECTED_RESIDUE = {
    "temporary_container_count": 0,
    "named_volume_count": 0,
    "object_bucket_count": 0,
    "production_resource_count": 0,
}


def run_s146_private_object_storage_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (
        *SLICE_DOCUMENTS,
        PLAN_PATH,
        CANONICAL_PATH,
        RUNBOOK_PATH,
        ATTESTATION_PATH,
        CONFIGURATION_PATH,
        *ARTIFACT_PATHS,
    )
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    repository_ready = all(document_presence.values())
    evidence = _run_evidence(root) if repository_ready else {}
    boundary = _mapping(evidence.get("boundary"))
    compose = _mapping(evidence.get("compose"))
    attestation = _load_json(root / ATTESTATION_PATH)
    attestation_checks = _mapping(attestation.get("checks"))
    metrics = _mapping(attestation.get("metrics"))
    privacy = _mapping(attestation.get("privacy"))
    rollback = _mapping(attestation.get("rollback"))
    recovery_metrics = _mapping(rollback.get("recovery_metrics"))
    residue = _mapping(attestation.get("residue"))
    dependency_digests = tuple(attestation.get("dependency_evidence_digests") or ())
    plan = " ".join(_read_text(root / PLAN_PATH).split())
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    runbook = _read_text(root / RUNBOOK_PATH)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    audit_check_count = sum(
        len(_mapping(item.get("checks"))) for item in evidence.values()
    )

    checks = {
        "repository_documents_and_artifacts_present": repository_ready,
        "deterministic_boundary_and_compose_audits_pass": (
            set(evidence) == {"boundary", "compose"}
            and all(item.get("status") == "PASS" for item in evidence.values())
            and audit_check_count == 21
        ),
        "attestation_shape_digest_and_source_valid": (
            set(attestation) == set(EVIDENCE_FIELDS)
            and attestation.get("evidence_digest") == _evidence_digest(attestation)
            and attestation.get("source_revision") == ACCEPTED_SOURCE_REVISION
            and re.fullmatch(
                r"[0-9a-f]{40}", str(attestation.get("source_revision") or "")
            )
            is not None
        ),
        "attestation_artifact_and_configuration_digests_valid": (
            attestation.get("configuration_digest")
            == _file_digest(root / CONFIGURATION_PATH)
            and attestation.get("artifact_digests")
            == [_file_digest(root / path) for path in ARTIFACT_PATHS]
        ),
        "attestation_identity_and_dependencies_valid": (
            attestation.get("requirement_id") == "S146"
            and attestation.get("environment_class") == "protected_test"
            and attestation.get("execution_mode") == "protected"
            and attestation.get("actual_execution") is True
            and dependency_digests == DEPENDENCY_EVIDENCE_DIGESTS
        ),
        "protected_checks_and_metrics_exact": (
            len(attestation_checks) == 26
            and all(value is True for value in attestation_checks.values())
            and metrics == EXPECTED_METRICS
        ),
        "privacy_rollback_and_residue_valid": (
            not _forbidden_paths(attestation)
            and privacy == {"raw_value_count": 0, "violation_count": 0}
            and rollback.get("drill_status") == "PASS"
            and _mapping(rollback.get("residue_counts")) == EXPECTED_RESIDUE
            and residue == EXPECTED_RESIDUE
            and sum(int(value) for value in residue.values()) == 0
        ),
        "owner_isolation_encryption_and_restart_proven": (
            attestation_checks.get("two_cross_bucket_attempts_denied") is True
            and attestation_checks.get("bucket_default_aes256_enabled") is True
            and attestation_checks.get("bucket_versioning_enabled") is True
            and attestation_checks.get("restart_recovery_verified") is True
            and metrics.get("bucket_count") == 2
            and metrics.get("service_identity_count") == 2
        ),
        "migration_restore_and_rollback_preserve_sources": (
            metrics.get("migration_owner_count") == 2
            and metrics.get("restored_object_count") == 1
            and recovery_metrics
            == {
                "dual_read_available": True,
                "source_copy_preserved": True,
                "historical_restore_verified": True,
                "restart_recovery_verified": True,
                "operator_cutover_required": True,
            }
            and rollback.get("data_migration_strategy")
            == "verified-copy-dual-read-source-preserved"
        ),
        "canonical_completion_and_s147_handoff_frozen": all(
            token in canonical
            for token in (
                "Status: S146 complete through Slice 1462.",
                "Production deployment remains unapproved.",
                "## Closure Decision",
                "## S147, S148, and S149 Handoff",
                "Completion signal: Met.",
            )
        ),
        "program_marks_s146_complete_and_s147_active": all(
            token in plan
            for token in (
                "S146 is complete and its S148/S149 object-storage inputs are ready",
                "At the S146 checkpoint, S147 was the next implementation requirement",
                "## S146 Completion Update",
                "production deployment remains unapproved",
            )
        ),
        "runbook_reproduces_operations_acceptance_closure_and_full_gate": (
            all(name in runbook for name in RUNBOOK_RUNNERS)
            and "scripts/quality/run_quality_gate.sh" in runbook
            and "Credential Rotation" in runbook
            and "Version Restore" in runbook
            and "Rollback" in runbook
        ),
        "protected_runner_registered_once_in_full_gate": quality_gate.count(
            PROTECTED_RUNNER
        )
        == 1,
        "closure_registered_once_in_full_gate": quality_gate.count(CLOSURE_RUNNER)
        == 1,
        "production_contact_approval_ha_and_host_recovery_not_claimed": (
            attestation_checks.get("production_contact_absent") is True
            and attestation_checks.get("production_approval_absent") is True
            and "does not provide high" in runbook
            and "S149" in runbook
            and "host or volume loss" in runbook
        ),
        "repository_inventory_exact": (
            _mapping(boundary.get("summary")).get("payload_family_count") == 7
            and _mapping(boundary.get("summary")).get("slice_count") == 10
            and _mapping(compose.get("metrics"))
            == {
                "bucket_count": 2,
                "credential_pair_count": 2,
                "host_port_count": 0,
                "secret_reference_count": 20,
            }
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1462",
        "slice_range": "1453-1462",
        "requirement": "S146",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s146_private_object_storage_closure_failed",
        "closure_readiness": "READY_FOR_S147" if passed else "BLOCKED",
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
            "database_count": int(metrics.get("database_count") or 0),
            "bucket_count": int(metrics.get("bucket_count") or 0),
            "migration_owner_count": int(metrics.get("migration_owner_count") or 0),
            "restored_object_count": int(metrics.get("restored_object_count") or 0),
            "residue_count": sum(int(value) for value in residue.values()),
        },
        "decision": {
            "single_host_rustfs_accepted": passed,
            "s3_application_boundary_accepted": passed,
            "actual_test_databases_used": metrics.get("database_count") == 5,
            "source_controlled_attestation_present": bool(attestation),
            "raw_protected_report_tracked": False,
            "high_availability_implemented": False,
            "independent_object_backup_proven": False,
            "production_resources_contacted": False,
            "production_deployment_approved": False,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S147" if passed else "blocked",
            "s148_object_storage_input_ready": passed,
            "s149_object_storage_input_ready": passed,
        },
    }


def _run_evidence(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {
        "boundary": run_private_object_storage_boundary(),
        "compose": run_object_storage_compose(),
    }


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
            "s146_private_object_storage_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s146_private_object_storage_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"databases={summary.get('database_count', 0)} "
        f"buckets={summary.get('bucket_count', 0)} "
        f"migrations={summary.get('migration_owner_count', 0)} "
        f"restores={summary.get('restored_object_count', 0)} "
        f"residue={summary.get('residue_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s146_private_object_storage_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
