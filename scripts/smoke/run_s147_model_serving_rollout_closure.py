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

from run_s147_canary_rollout import run_canary_rollout
from run_s147_capability_calibration import run_capability_calibration
from run_s147_gpu_capacity_admission import run_gpu_capacity_admission
from run_s147_model_revision_capacity_domain import run_model_revision_capacity_domain
from run_s147_model_serving_rollout_boundary import run_model_serving_rollout_boundary
from run_s147_revision_readiness import run_revision_readiness
from run_s147_rollout_activation_rollback import run_rollout_activation_rollback
from run_s147_rollout_persistence_restart import run_rollout_persistence_restart
from repository_revision_evidence import file_digests_at_revision_match

SCHEMA_VERSION = "s147_model_serving_rollout_closure.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
CANONICAL_PATH = "docs/55_platform_model_serving_capacity_rollout.md"
RUNBOOK_PATH = "docs/runbooks/model_serving_rollout_operations.md"
ATTESTATION_PATH = (
    "deployment/model-serving/s147-model-rollout-acceptance-attestation.json"
)
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s147_model_serving_rollout_closure.py"
PROTECTED_RUNNER = "run_s147_model_rollout_live_acceptance.py"
ACCEPTED_SOURCE_REVISION = "6386a20f3358746beb8e0d9c9d4ed20edc2d4197"
ARTIFACT_DIGESTS = {
    "scripts/smoke/run_s147_model_rollout_live_acceptance.py": (
        "sha256:496f2c4531fa9db227eb8d7ee6fac2549d5d27f459559c97b4698a61cba754df"
    ),
    "database/nex-mo/migrations/1470_mo_model_rollout_persistence.sql": (
        "sha256:77e035d2537de241f5c26065b381288100ffd951767e42baa7c4a90d731c6208"
    ),
    "services/nex-mo/nex_mo/runtime_observability_plan.py": (
        "sha256:32acc60ad4ed4f7fed59f595ceeeaca594542802d42510d7626ce90a5d604640"
    ),
    "services/nex-mo/nex_mo/model_rollout_state.py": (
        "sha256:3ee6d44b62c28f83a1c4af41f096dc3835d66b44b42bd35402031498d0ba4b8e"
    ),
    "services/nex-mo/nex_mo/model_rollout_activation.py": (
        "sha256:bd497d6af4e8895dd0643d89a7f81f9bbbcbf2cf031a7c1d5029e068d75b50c8"
    ),
}
CONTRACT_PATHS = (
    "contracts/schemas/service/nex_mo/model_rollout.v1.schema.json",
    "contracts/schemas/service/nex_mo/model_rollout_event.v1.schema.json",
    "contracts/examples/provider/mo_model_rollout.validating.json",
    "contracts/examples/provider/mo_model_rollout_event.validation_started.json",
    "contracts/tests/negative/provider/mo_model_rollout.endpoint_leak.json",
    "contracts/tests/negative/provider/mo_model_rollout_event.raw_payload.json",
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1463", "s147_model_serving_rollout_boundary"),
        ("1464", "s147_model_revision_capacity_domain"),
        ("1465", "s147_gpu_capacity_admission"),
        ("1466", "s147_revision_bound_readiness"),
        ("1467", "s147_capability_calibration_lifecycle"),
        ("1468", "s147_canary_rollout_checkpoint"),
        ("1469", "s147_rollout_activation_rollback"),
        ("1470", "s147_rollout_persistence_operations"),
        ("1471", "s147_model_rollout_protected_acceptance"),
        ("1472", "s147_model_serving_rollout_closure"),
    )
)
ATTESTATION_FIELDS = {
    "evidence_schema_version",
    "requirement_id",
    "environment_class",
    "execution_mode",
    "actual_execution",
    "source_revision",
    "artifact_digests",
    "checks",
    "metrics",
    "candidate_admission",
    "privacy",
    "residue",
    "production_resources_contacted",
    "production_deployment_approved",
    "evidence_digest",
}


def run_s147_model_serving_rollout_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_paths = (
        *SLICE_DOCUMENTS,
        PLAN_PATH,
        CANONICAL_PATH,
        RUNBOOK_PATH,
        ATTESTATION_PATH,
        *CONTRACT_PATHS,
        *ARTIFACT_DIGESTS,
    )
    presence = {path: (root / path).is_file() for path in required_paths}
    repository_ready = all(presence.values())
    audits = _run_audits(root) if repository_ready else {}
    attestation = _read_json(root / ATTESTATION_PATH)
    attestation_checks = _mapping(attestation.get("checks"))
    metrics = _mapping(attestation.get("metrics"))
    admission = _mapping(attestation.get("candidate_admission"))
    privacy = _mapping(attestation.get("privacy"))
    residue = _mapping(attestation.get("residue"))
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    plan = " ".join(_read_text(root / PLAN_PATH).split())
    runbook = _read_text(root / RUNBOOK_PATH)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    artifact_digests = list(attestation.get("artifact_digests") or ())
    expected_artifact_digests = list(ARTIFACT_DIGESTS.values())

    checks = {
        "repository_documents_contracts_and_artifacts_present": repository_ready,
        "all_deterministic_rollout_audits_pass": (
            len(audits) == 8
            and all(item.get("status") == "PASS" for item in audits.values())
        ),
        "attestation_shape_source_and_digest_valid": (
            set(attestation) == ATTESTATION_FIELDS
            and attestation.get("evidence_digest") == _evidence_digest(attestation)
            and attestation.get("source_revision") == ACCEPTED_SOURCE_REVISION
            and re.fullmatch(
                r"[0-9a-f]{40}", str(attestation.get("source_revision") or "")
            )
            is not None
        ),
        "attestation_artifact_digests_exact": (
            artifact_digests == expected_artifact_digests
            and file_digests_at_revision_match(
                root,
                ACCEPTED_SOURCE_REVISION,
                ARTIFACT_DIGESTS,
            )
        ),
        "protected_execution_identity_valid": (
            attestation.get("requirement_id") == "S147"
            and attestation.get("environment_class") == "protected_test"
            and attestation.get("execution_mode") == "protected"
            and attestation.get("actual_execution") is True
        ),
        "protected_checks_and_metrics_exact": (
            len(attestation_checks) == 12
            and all(value is True for value in attestation_checks.values())
            and metrics
            == {
                "provider_count": 3,
                "model_match_count": 3,
                "runtime_ready_count": 3,
                "rollout_count": 3,
                "event_count": 6,
                "api_item_count": 3,
                "residue_count": 0,
            }
        ),
        "candidate_admission_remained_fail_closed": admission
        == {
            "status": "CALIBRATION_REQUIRED",
            "promotion_eligible": False,
            "live_mutation_performed": False,
        },
        "privacy_and_zero_residue_proven": (
            privacy == {"raw_value_count": 0, "violation_count": 0}
            and residue
            == {
                "rollout_row_count": 0,
                "event_row_count": 0,
                "catalog_row_count": 0,
            }
            and sum(int(value) for value in residue.values()) == 0
        ),
        "production_contact_and_approval_not_claimed": (
            attestation.get("production_resources_contacted") is False
            and attestation.get("production_deployment_approved") is False
        ),
        "canonical_s147_completion_and_handoff_frozen": all(
            token in canonical
            for token in (
                "Status: S147 complete through Slice 1472.",
                "Completion signal: Met.",
                "## S148 and S149 Handoff",
                "Production deployment remains unapproved.",
            )
        ),
        "program_preserves_s147_handoff_and_marks_s149_active": all(
            token in plan
            for token in (
                "through S148 are complete, S149 is active",
                "## S147 Completion Update",
                "S148 is the next implementation requirement",
                "Production deployment remains unapproved",
            )
        ),
        "runbook_covers_admission_rollback_acceptance_and_handoff": all(
            token in runbook
            for token in (
                "## Admission Sequence",
                "## Rollback",
                "## Protected Test Acceptance",
                "run_s147_model_rollout_live_acceptance.py",
                CLOSURE_RUNNER,
                "run_quality_gate.sh",
                "S148 consumes",
            )
        ),
        "canonical_contracts_registered_and_openapi_linked": (
            _index_contains(
                root / "contracts/examples/index.json",
                tuple(path.removeprefix("contracts/") for path in CONTRACT_PATHS[2:4]),
            )
            and _index_contains(
                root / "contracts/tests/negative/index.json",
                tuple(path.removeprefix("contracts/") for path in CONTRACT_PATHS[4:6]),
            )
            and all(
                marker.removeprefix("contracts/")
                in _read_text(root / "contracts/openapi/nex-mo.openapi.yaml")
                for marker in CONTRACT_PATHS[:2]
            )
        ),
        "protected_and_closure_runners_registered_once": (
            quality_gate.count(PROTECTED_RUNNER) == 1
            and quality_gate.count(CLOSURE_RUNNER) == 1
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1472",
        "slice_range": "1463-1472",
        "requirement": "S147",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s147_model_serving_rollout_closure_failed",
        "closure_readiness": "READY_FOR_S148" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "audit_statuses": {name: item.get("status") for name, item in audits.items()},
        "required_paths": presence,
        "summary": {
            "audit_count": len(audits),
            "passed_audit_count": sum(
                item.get("status") == "PASS" for item in audits.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "provider_count": int(metrics.get("provider_count") or 0),
            "runtime_ready_count": int(metrics.get("runtime_ready_count") or 0),
            "rollout_count": int(metrics.get("rollout_count") or 0),
            "event_count": int(metrics.get("event_count") or 0),
            "residue_count": sum(int(value) for value in residue.values()),
        },
        "decision": {
            "model_independent_rollout_ready": passed,
            "protected_current_revision_observation_complete": passed,
            "candidate_promotion_claimed": False,
            "production_deployment_approved": False,
            "next_requirement": "S148" if passed else "blocked",
            "s148_model_serving_input_ready": passed,
            "s149_rollout_rehearsal_input_ready": passed,
        },
    }


def _run_audits(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {
        "boundary": run_model_serving_rollout_boundary(),
        "revision_capacity": run_model_revision_capacity_domain(),
        "gpu_admission": run_gpu_capacity_admission(),
        "revision_readiness": run_revision_readiness(),
        "calibration": run_capability_calibration(),
        "canary": run_canary_rollout(),
        "activation_rollback": run_rollout_activation_rollback(),
        "persistence_restart": run_rollout_persistence_restart(),
    }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _read_json(path: Path) -> dict[str, Any]:
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


def _index_contains(path: Path, expected_paths: tuple[str, ...]) -> bool:
    payload = _read_json(path)
    entries = payload.get("examples") or payload.get("negative_examples") or []
    indexed = {
        str(item.get("path"))
        for item in entries
        if isinstance(item, Mapping)
    }
    return all(path in indexed for path in expected_paths)


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "s147_model_serving_rollout_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s147_model_serving_rollout_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"providers={summary.get('provider_count', 0)} "
        f"runtime={summary.get('runtime_ready_count', 0)} "
        f"rollouts={summary.get('rollout_count', 0)} "
        f"events={summary.get('event_count', 0)} "
        f"residue={summary.get('residue_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s147_model_serving_rollout_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
