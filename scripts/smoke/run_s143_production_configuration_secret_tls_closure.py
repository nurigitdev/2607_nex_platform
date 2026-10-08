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

from nex_runtime.s143_staging import validate_s143_compose_assets  # noqa: E402
from run_platform_production_api_key_custody import (  # noqa: E402
    run_platform_production_api_key_custody,
)
from run_platform_production_configuration_manifest import (  # noqa: E402
    run_platform_production_configuration_manifest,
)
from run_platform_production_evidence_decision_contract import (  # noqa: E402
    EVIDENCE_FIELDS,
    _forbidden_paths,
)
from run_platform_production_secret_materialization import (  # noqa: E402
    run_platform_production_secret_materialization,
)
from run_platform_production_secret_rotation import (  # noqa: E402
    run_platform_production_secret_rotation,
)
from run_platform_production_security_boundary import (  # noqa: E402
    run_platform_production_security_boundary,
)
from run_platform_production_startup_admission import (  # noqa: E402
    run_platform_production_startup_admission,
)
from run_platform_production_tls_lifecycle import (  # noqa: E402
    run_platform_production_tls_lifecycle,
)


SCHEMA_VERSION = "s143_production_configuration_secret_tls_closure.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
CANONICAL_PATH = "docs/51_platform_production_configuration_secret_tls.md"
RUNBOOK_PATH = "docs/runbooks/platform_production_configuration_secret_tls.md"
ATTESTATION_PATH = "deployment/security/s143-external-staging-attestation.json"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s143_production_configuration_secret_tls_closure.py"
PROTECTED_RUNNER = "run_s143_external_staging_acceptance.py"
ACCEPTED_SOURCE_REVISION = "f7dcef7562e39aa15873eba9c6087eb3ff1201b1"
CONFIGURATION_ASSETS = (
    "deployment/compose/s143-staging.compose.yaml",
    "deployment/compose/openbao/config.hcl",
    "deployment/compose/traefik/static.yaml",
    "deployment/compose/traefik/dynamic.yaml",
)
EvidenceRunner = Callable[[Path], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, str, EvidenceRunner], ...] = (
    (
        "boundary",
        "run_platform_production_security_boundary.py",
        run_platform_production_security_boundary,
    ),
    (
        "manifest",
        "run_platform_production_configuration_manifest.py",
        run_platform_production_configuration_manifest,
    ),
    (
        "admission",
        "run_platform_production_startup_admission.py",
        run_platform_production_startup_admission,
    ),
    (
        "materialization",
        "run_platform_production_secret_materialization.py",
        run_platform_production_secret_materialization,
    ),
    (
        "rotation",
        "run_platform_production_secret_rotation.py",
        run_platform_production_secret_rotation,
    ),
    (
        "custody",
        "run_platform_production_api_key_custody.py",
        run_platform_production_api_key_custody,
    ),
    (
        "tls",
        "run_platform_production_tls_lifecycle.py",
        run_platform_production_tls_lifecycle,
    ),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1423", "platform_production_security_boundary"),
        ("1424", "platform_production_configuration_manifest"),
        ("1425", "platform_production_startup_admission"),
        ("1426", "platform_production_secret_materialization"),
        ("1427", "platform_production_secret_rotation"),
        ("1428", "platform_production_api_key_custody"),
        ("1429", "platform_production_tls_lifecycle"),
        ("1430", "platform_production_security_local_rehearsal"),
        ("1431", "s143_external_staging_acceptance"),
        ("1432", "s143_production_configuration_secret_tls_closure"),
    )
)


def run_s143_production_configuration_secret_tls_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (
        *SLICE_DOCUMENTS,
        PLAN_PATH,
        CANONICAL_PATH,
        RUNBOOK_PATH,
        ATTESTATION_PATH,
    )
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    repository_ready = all(document_presence.values())
    evidence = _run_evidence(root) if repository_ready else {}
    compose = _compose_contract(root) if repository_ready else {}
    attestation = _load_json(root / ATTESTATION_PATH)
    plan = " ".join(_read_text(root / PLAN_PATH).split())
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    runbook = _read_text(root / RUNBOOK_PATH)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)

    boundary = _summary(evidence, "boundary")
    manifest = _summary(evidence, "manifest")
    admission = _summary(evidence, "admission")
    materialization = _summary(evidence, "materialization")
    rotation = _summary(evidence, "rotation")
    custody = _summary(evidence, "custody")
    tls = _summary(evidence, "tls")
    acceptance_checks = _mapping(attestation.get("checks"))
    metrics = _mapping(attestation.get("metrics"))
    privacy = _mapping(attestation.get("privacy"))
    rollback = _mapping(attestation.get("rollback"))
    residue = _mapping(attestation.get("residue"))

    attestation_fields = set(attestation)
    digest_valid = bool(attestation) and attestation.get(
        "evidence_digest"
    ) == _evidence_digest(attestation)
    configuration_digest = _configuration_digest(root)
    checks = {
        "all_seven_repository_audits_passed": len(evidence) == 7
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
        "canonical_completion_and_parallel_handoff_frozen": all(
            token in canonical
            for token in (
                "Status: S143 complete through Slice 1432.",
                "Production deployment remains unapproved.",
                "## Closure Decision",
                "## S144-S147 Handoff",
                "Completion signal: Met.",
            )
        ),
        "program_marks_s143_complete_and_s144_s147_ready": all(
            token in plan
            for token in (
                "S143 completed through Slice 1432",
                "The wave-two requirements S144, S145, S146, and S147 "
                "may now proceed independently",
                "production deployment remains unapproved",
                "## S143 Completion Update",
            )
        ),
        "repository_inventory_exact": (
            boundary.get("required_environment_count") == 25
            and boundary.get("secret_environment_count") == 16
            and boundary.get("public_connection_count") == 9
            and boundary.get("tls_endpoint_count") == 9
            and boundary.get("gap_count") == 9
            and manifest
            == {
                "binding_count": 31,
                "secret_reference_count": 20,
                "public_connection_count": 11,
                "control_environment_count": 6,
                "owner_count": 6,
            }
            and admission.get("fail_closed_case_count") == 6
            and materialization
            == {
                "owner_count": 5,
                "secret_count": 20,
                "fail_closed_case_count": 3,
                "secret_value_leak_count": 0,
            }
            and rotation.get("owner_count") == 5
            and rotation.get("verified_owner_count") == 5
            and custody.get("provider_api_key_count") == 3
            and custody.get("non_owner_exposure_count") == 0
            and custody.get("redaction_leak_count") == 0
            and tls.get("private_key_exposure_count") == 0
        ),
        "single_host_compose_contract_exact": compose
        == {
            "schema_version": "s143_external_staging.v1",
            "status": "VALID",
            "orchestrator": "docker-compose-single-host",
            "service_count": 9,
            "runtime_service_count": 8,
            "initializer_service_count": 1,
            "secret_reference_count": 16,
            "tls_route_count": 9,
            "external_images": compose.get("external_images", []),
            "host_software_install_required": False,
            "raw_secret_values_included": False,
        }
        and len(compose.get("external_images", [])) == 2,
        "attestation_shape_digest_and_configuration_valid": (
            attestation_fields == set(EVIDENCE_FIELDS)
            and digest_valid
            and attestation.get("configuration_digest")
            == configuration_digest
            and re.fullmatch(
                r"[0-9a-f]{40}", str(attestation.get("source_revision") or "")
            )
            is not None
        ),
        "attestation_identity_matches_accepted_execution": (
            attestation.get("requirement_id") == "S143"
            and attestation.get("environment_class") == "external_staging"
            and attestation.get("execution_mode") == "protected"
            and attestation.get("actual_execution") is True
            and attestation.get("source_revision") == ACCEPTED_SOURCE_REVISION
            and len(attestation.get("artifact_digests") or []) == 1
            and len(attestation.get("dependency_evidence_digests") or []) == 2
        ),
        "attestation_acceptance_checks_pass": (
            len(acceptance_checks) == 13
            and all(value is True for value in acceptance_checks.values())
        ),
        "attestation_metrics_exact": metrics
        == {
            "application_ready_count": 6,
            "database_service_count": 5,
            "generation_transition_count": 3,
            "managed_route_count": 9,
            "owner_count": 5,
            "provider_capability_count": 3,
            "execution_duration_recorded": False,
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
                "runtime_file_count": 0,
                "volume_count": 0,
            }
        ),
        "runbook_reproduces_audits_protected_acceptance_and_full_gate": all(
            script_name in runbook for _, script_name, _ in EVIDENCE_RUNNERS
        )
        and PROTECTED_RUNNER in runbook
        and CLOSURE_RUNNER in runbook
        and "scripts/quality/run_quality_gate.sh" in runbook
        and "No host installation" in runbook,
        "production_and_registry_actions_not_claimed": (
            acceptance_checks.get("registry_push_absent") is True
            and acceptance_checks.get("production_contact_absent") is True
            and acceptance_checks.get("production_approval_absent") is True
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1432",
        "slice_range": "1423-1432",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s143_production_configuration_secret_tls_closure_failed",
        "closure_readiness": "READY_FOR_S144_S147" if passed else "BLOCKED",
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
            "required_environment_count": int(
                boundary.get("required_environment_count") or 0
            ),
            "secret_reference_count": int(
                manifest.get("secret_reference_count") or 0
            ),
            "compose_service_count": int(compose.get("service_count") or 0),
            "protected_database_count": int(
                metrics.get("database_service_count") or 0
            ),
            "protected_provider_count": int(
                metrics.get("provider_capability_count") or 0
            ),
            "managed_route_count": int(metrics.get("managed_route_count") or 0),
        },
        "decision": {
            "external_staging_acceptance_passed": passed,
            "source_controlled_attestation_present": bool(attestation),
            "raw_protected_report_tracked": False,
            "additional_host_software_install_required": False,
            "registry_push_performed": False,
            "production_resources_contacted": False,
            "production_deployment_approved": False,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S144" if passed else "blocked",
            "parallel_requirements_ready": (
                ["S144", "S145", "S146", "S147"] if passed else []
            ),
        },
    }


def _run_evidence(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {name: runner(root) for name, _, runner in EVIDENCE_RUNNERS}


def _compose_contract(root: Path) -> dict[str, Any]:
    if root.resolve() != ROOT.resolve():
        return {}
    return validate_s143_compose_assets(root)


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
            "s143_production_configuration_secret_tls_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s143_production_configuration_secret_tls_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"secrets={summary.get('secret_reference_count', 0)} "
        f"compose={summary.get('compose_service_count', 0)} "
        f"databases={summary.get('protected_database_count', 0)} "
        f"providers={summary.get('protected_provider_count', 0)} "
        f"routes={summary.get('managed_route_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s143_production_configuration_secret_tls_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
