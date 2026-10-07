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
sys.path.insert(0, str(ROOT / "services" / "nex-oa"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_oa_enterprise_oidc_registration import (  # noqa: E402
    run_oa_enterprise_oidc_registration,
)
from run_oa_oidc_rollover_resilience import (  # noqa: E402
    run_oa_oidc_rollover_resilience,
)
from run_oa_openbao_transit_key_lifecycle import (  # noqa: E402
    run_oa_openbao_transit_key_lifecycle,
)
from run_oa_openbao_transit_rotation_checkpoint import (  # noqa: E402
    run_oa_openbao_transit_rotation_checkpoint,
)
from run_oa_openbao_transit_runtime import (  # noqa: E402
    run_oa_openbao_transit_runtime,
)
from run_oa_openbao_transit_signer import (  # noqa: E402
    run_oa_openbao_transit_signer,
)
from run_platform_production_evidence_decision_contract import (  # noqa: E402
    EVIDENCE_FIELDS,
    _forbidden_paths,
)
from run_s144_oa_production_trust_boundary import (  # noqa: E402
    run_oa_production_trust_boundary,
)
from run_s144_staging_trust_rehearsal import (  # noqa: E402
    run_s144_staging_trust_rehearsal,
)


SCHEMA_VERSION = "s144_oa_production_trust_closure.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
CANONICAL_PATH = "docs/52_oa_production_trust_key_custody_federation.md"
RUNBOOK_PATH = "docs/runbooks/oa_production_trust_federation.md"
ATTESTATION_PATH = "deployment/security/s144-trust-federation-attestation.json"
S143_ATTESTATION_PATH = "deployment/security/s143-external-staging-attestation.json"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s144_oa_production_trust_closure.py"
PROTECTED_RUNNER = "run_s144_protected_trust_federation_acceptance.py"
ACCEPTED_SOURCE_REVISION = "6733a7ba3b75e66e0c6d6366dcbaf564cde86b82"
CONFIGURATION_ASSETS = (
    "deployment/compose/s143-staging.compose.yaml",
    "deployment/compose/s144-staging.override.yaml",
    "deployment/compose/openbao/config.hcl",
    "deployment/compose/traefik/static.yaml",
    "deployment/compose/traefik/dynamic.yaml",
)
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, str, EvidenceRunner], ...] = (
    (
        "boundary",
        "run_s144_oa_production_trust_boundary.py",
        run_oa_production_trust_boundary,
    ),
    (
        "signer",
        "run_oa_openbao_transit_signer.py",
        run_oa_openbao_transit_signer,
    ),
    (
        "runtime",
        "run_oa_openbao_transit_runtime.py",
        run_oa_openbao_transit_runtime,
    ),
    (
        "lifecycle",
        "run_oa_openbao_transit_key_lifecycle.py",
        run_oa_openbao_transit_key_lifecycle,
    ),
    (
        "rotation",
        "run_oa_openbao_transit_rotation_checkpoint.py",
        run_oa_openbao_transit_rotation_checkpoint,
    ),
    (
        "registration",
        "run_oa_enterprise_oidc_registration.py",
        run_oa_enterprise_oidc_registration,
    ),
    (
        "rollover",
        "run_oa_oidc_rollover_resilience.py",
        run_oa_oidc_rollover_resilience,
    ),
    (
        "rehearsal",
        "run_s144_staging_trust_rehearsal.py",
        run_s144_staging_trust_rehearsal,
    ),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1433", "oa_production_trust_boundary"),
        ("1434", "oa_openbao_transit_signer"),
        ("1435", "oa_openbao_transit_runtime_wiring"),
        ("1436", "oa_openbao_transit_key_lifecycle"),
        ("1437", "oa_openbao_transit_rotation_checkpoint"),
        ("1438", "oa_enterprise_oidc_registration"),
        ("1439", "oa_oidc_rollover_resilience"),
        ("1440", "s144_staging_trust_rehearsal"),
        ("1441", "s144_protected_trust_federation_acceptance"),
        ("1442", "s144_oa_production_trust_closure"),
    )
)


def run_s144_oa_production_trust_closure(root: Path = ROOT) -> dict[str, Any]:
    required_documents = (
        *SLICE_DOCUMENTS,
        PLAN_PATH,
        CANONICAL_PATH,
        RUNBOOK_PATH,
        ATTESTATION_PATH,
        S143_ATTESTATION_PATH,
    )
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    repository_ready = all(document_presence.values())
    evidence = _run_evidence(root) if repository_ready else {}
    attestation = _load_json(root / ATTESTATION_PATH)
    predecessor = _load_json(root / S143_ATTESTATION_PATH)
    plan = " ".join(_read_text(root / PLAN_PATH).split())
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    runbook = _read_text(root / RUNBOOK_PATH)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)

    boundary = _summary(evidence, "boundary")
    signer = _summary(evidence, "signer")
    runtime = _summary(evidence, "runtime")
    lifecycle = _summary(evidence, "lifecycle")
    rotation = _summary(evidence, "rotation")
    registration = _summary(evidence, "registration")
    rollover = _summary(evidence, "rollover")
    rehearsal = _summary(evidence, "rehearsal")
    acceptance_checks = _mapping(attestation.get("checks"))
    metrics = _mapping(attestation.get("metrics"))
    privacy = _mapping(attestation.get("privacy"))
    rollback = _mapping(attestation.get("rollback"))
    residue = _mapping(attestation.get("residue"))
    dependency_digests = attestation.get("dependency_evidence_digests") or []

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
        "canonical_completion_and_s148_handoff_frozen": all(
            token in canonical
            for token in (
                "Status: S144 complete through Slice 1442.",
                "Production deployment remains unapproved.",
                "## Closure Decision",
                "## S148 Handoff",
                "Completion signal: Met.",
            )
        ),
        "program_marks_s144_complete_and_s148_dependency_ready": all(
            token in plan
            for token in (
                "S144 is complete and its S148 dependency is ready",
                "production deployment remains unapproved",
                "## S144 Completion Update",
            )
        ),
        "repository_inventory_exact": (
            boundary.get("gap_count") == 8
            and signer == {
                "check_count": 10,
                "request_count": 3,
                "key_version": 1,
                "signature_bytes": 384,
            }
            and runtime.get("signature_bytes") == 384
            and lifecycle.get("key_version") == 1
            and rotation.get("jwks_key_count") == 2
            and registration.get("check_count") == 14
            and rollover.get("refresh_generation") == 4
            and rehearsal.get("tls_route_count") == 10
        ),
        "attestation_shape_digest_and_configuration_valid": (
            set(attestation) == set(EVIDENCE_FIELDS)
            and attestation.get("evidence_digest") == _evidence_digest(attestation)
            and attestation.get("configuration_digest")
            == _configuration_digest(root)
            and re.fullmatch(
                r"[0-9a-f]{40}", str(attestation.get("source_revision") or "")
            )
            is not None
        ),
        "attestation_identity_matches_accepted_execution": (
            attestation.get("requirement_id") == "S144"
            and attestation.get("environment_class") == "external_staging"
            and attestation.get("execution_mode") == "protected"
            and attestation.get("actual_execution") is True
            and attestation.get("source_revision") == ACCEPTED_SOURCE_REVISION
            and len(attestation.get("artifact_digests") or []) == 1
            and len(dependency_digests) == 2
            and predecessor.get("evidence_digest") in dependency_digests
        ),
        "attestation_acceptance_checks_pass": len(acceptance_checks) == 21
        and all(value is True for value in acceptance_checks.values()),
        "attestation_metrics_exact": metrics
        == {
            "application_service_count": 1,
            "database_service_count": 1,
            "execution_duration_recorded": False,
            "managed_route_count": 10,
            "migration_count": 18,
            "oidc_jwks_key_count": 2,
            "transit_version_count": 2,
        },
        "attestation_privacy_rollback_and_residue_valid": (
            not _forbidden_paths(attestation)
            and privacy == {"raw_value_count": 0, "violation_count": 0}
            and rollback.get("drill_status") == "PASS"
            and _mapping(rollback.get("residue_counts")) == residue
            and residue
            == {
                "container_count": 0,
                "network_count": 0,
                "oa_test_row_count": 0,
                "volume_count": 0,
            }
        ),
        "runbook_reproduces_audits_acceptance_closure_and_full_gate": all(
            script_name in runbook for _, script_name, _ in EVIDENCE_RUNNERS
        )
        and PROTECTED_RUNNER in runbook
        and CLOSURE_RUNNER in runbook
        and "scripts/quality/run_quality_gate.sh" in runbook
        and "No host installation" in runbook,
        "browser_callback_deferral_is_explicit": (
            "browser callback" in canonical.lower()
            and "S149" in canonical
            and acceptance_checks.get("browser_callback_deferred") is True
        ),
        "production_and_registry_actions_not_claimed": (
            acceptance_checks.get("production_approval_absent") is True
            and acceptance_checks.get("production_contact_absent") is True
            and acceptance_checks.get("registry_push_absent") is True
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1442",
        "slice_range": "1433-1442",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s144_oa_production_trust_closure_failed",
        "closure_readiness": "READY_FOR_S148" if passed else "BLOCKED",
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
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "gap_count": int(boundary.get("gap_count") or 0),
            "transit_version_count": int(metrics.get("transit_version_count") or 0),
            "oidc_jwks_key_count": int(metrics.get("oidc_jwks_key_count") or 0),
            "managed_route_count": int(metrics.get("managed_route_count") or 0),
            "protected_database_count": int(metrics.get("database_service_count") or 0),
        },
        "decision": {
            "single_host_acceptance_passed": passed,
            "source_controlled_attestation_present": bool(attestation),
            "raw_protected_report_tracked": False,
            "additional_host_software_install_required": False,
            "corporate_idp_contacted": False,
            "registry_push_performed": False,
            "production_resources_contacted": False,
            "production_deployment_approved": False,
            "browser_callback_deferred_to_s149": True,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S145" if passed else "blocked",
            "s148_dependency_ready": passed,
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


def _configuration_digest(root: Path) -> str:
    digest = sha256()
    try:
        for relative in CONFIGURATION_ASSETS:
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update((root / relative).read_bytes())
            digest.update(b"\0")
    except OSError:
        return ""
    return f"sha256:{digest.hexdigest()}"


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
            "s144_oa_production_trust_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s144_oa_production_trust_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"transit_versions={summary.get('transit_version_count', 0)} "
        f"oidc_jwks={summary.get('oidc_jwks_key_count', 0)} "
        f"routes={summary.get('managed_route_count', 0)} "
        f"databases={summary.get('protected_database_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s144_oa_production_trust_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
