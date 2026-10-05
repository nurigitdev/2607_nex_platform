#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_ae_grounded_artifact_admission import (
    run_ae_grounded_artifact_admission,
)
from run_ae_grounded_artifact_recovery_access import (
    run_ae_grounded_artifact_recovery_access,
)
from run_ae_grounded_response_lineage import run_ae_grounded_response_lineage
from run_cx_grounded_generation_runtime_composition import (
    run_cx_grounded_generation_runtime_composition,
)
from run_cx_grounding_repair_lineage import run_cx_grounding_repair_lineage


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_grounded_generation_artifact_e2e.v1"
CANONICAL_DOCUMENT = "docs/44_platform_grounded_generation_artifact_e2e.md"
CONTRACT_SCHEMA = (
    "contracts/schemas/service/nex_ae_api/"
    "grounded_artifact_admission.v1.schema.json"
)
CONTRACT_EXAMPLE = (
    "contracts/examples/generation/"
    "ae_grounded_artifact_admission.enqueued.json"
)
CONTRACT_NEGATIVE = (
    "contracts/tests/negative/generation/"
    "ae_grounded_artifact_admission.content_leak.json"
)
OPENAPI = "contracts/openapi/nex-ae-api.openapi.yaml"
EvidenceRunner = Callable[[Path], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, EvidenceRunner], ...] = (
    ("cx_runtime", run_cx_grounded_generation_runtime_composition),
    ("cx_repair", run_cx_grounding_repair_lineage),
    ("ae_response", run_ae_grounded_response_lineage),
    ("ae_artifact", run_ae_grounded_artifact_admission),
    ("ae_recovery", run_ae_grounded_artifact_recovery_access),
)
FORBIDDEN_PRIVATE_KEYS = frozenset(
    {
        "generated_content",
        "raw_content",
        "evidence_text",
        "storage_ref",
    }
)


def run_platform_grounded_generation_artifact_e2e(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_paths = (
        CANONICAL_DOCUMENT,
        CONTRACT_SCHEMA,
        CONTRACT_EXAMPLE,
        CONTRACT_NEGATIVE,
        OPENAPI,
    )
    presence = {path: (root / path).is_file() for path in required_paths}
    evidence = _run_evidence(root)
    statuses = {
        name: result.get("status") for name, result in evidence.items()
    }
    example = _read_json(root / CONTRACT_EXAMPLE)
    artifact = _mapping(example.get("artifact"))
    response_binding = _mapping(example.get("response_binding"))
    render_admission = _mapping(example.get("render_admission"))
    render = _mapping(render_admission.get("render"))
    source_refs = artifact.get("source_refs")
    source_ref = (
        _mapping(source_refs[0])
        if isinstance(source_refs, list) and source_refs
        else {}
    )
    render_jobs = artifact.get("render_jobs")
    render_job = (
        _mapping(render_jobs[0])
        if isinstance(render_jobs, list) and render_jobs
        else {}
    )
    cx_repair = _mapping(evidence.get("cx_repair"))
    ae_artifact = _mapping(evidence.get("ae_artifact"))
    ae_recovery = _mapping(evidence.get("ae_recovery"))
    repair_checks = _mapping(cx_repair.get("checks"))
    artifact_checks = _mapping(ae_artifact.get("checks"))
    recovery_checks = _mapping(ae_recovery.get("checks"))

    checks = {
        "all_component_evidence_passes": (
            len(statuses) == len(EVIDENCE_RUNNERS)
            and all(status == "PASS" for status in statuses.values())
        ),
        "contract_artifacts_present": all(presence.values()),
        "success_path_reaches_content_free_render_admission": (
            statuses.get("cx_runtime") == "PASS"
            and statuses.get("ae_response") == "PASS"
            and statuses.get("ae_artifact") == "PASS"
            and render_admission.get("admission_status") == "ENQUEUED"
            and example.get("content_included") is False
        ),
        "repair_path_is_exact_and_bounded_once": (
            statuses.get("cx_repair") == "PASS"
            and repair_checks.get("exact_binding_contract") is True
            and repair_checks.get("repair_transition_contract") is True
            and _mapping(cx_repair.get("decision")).get("repair_attempt_limit")
            == 1
        ),
        "denial_path_covers_lineage_drift_and_cross_owner": (
            artifact_checks.get("lineage_drift_regression") is True
            and recovery_checks.get("cross_owner_regression") is True
        ),
        "recovery_path_covers_restart_and_reconciliation": (
            recovery_checks.get("fresh_runtime_regression") is True
            and recovery_checks.get("idempotent_reconciliation") is True
        ),
        "artifact_and_render_identity_match": (
            bool(artifact.get("artifact_id"))
            and artifact.get("artifact_id") == render.get("artifact_id")
            and render_job.get("render_job_id") == render.get("render_job_id")
        ),
        "response_and_source_lineage_match": (
            bool(response_binding.get("response_id"))
            and response_binding.get("interaction_id")
            == artifact.get("interaction_id")
            and response_binding.get("chat_document_id")
            == artifact.get("chat_document_id")
            and response_binding.get("cx_generation_id")
            == source_ref.get("cx_generation_id")
            and response_binding.get("structured_draft_id")
            == source_ref.get("structured_draft_id")
        ),
        "citation_workflow_is_validated": (
            response_binding.get("citation_workflow_status") == "VALIDATED"
            and _mapping(source_ref.get("quality_summary")).get(
                "citation_status"
            )
            == "VALIDATED"
        ),
        "evidence_is_private_payload_free": (
            bool(example)
            and example.get("content_included") is False
            and response_binding.get("content_included") is False
            and render_admission.get("content_included") is False
            and not _contains_forbidden_key(example)
        ),
        "operations_projection_is_metadata_only": all(
            key not in statuses
            for key in ("prompt", "generated_text", "evidence_text")
        ),
        "protected_dependencies_are_not_required": all(
            _mapping(result.get("decision")).get(
                "remote_provider_required", False
            )
            is False
            for result in evidence.values()
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    scenarios = {
        "SUCCESS": checks["success_path_reaches_content_free_render_admission"],
        "REPAIR": checks["repair_path_is_exact_and_bounded_once"],
        "DENIAL": checks["denial_path_covers_lineage_drift_and_cross_owner"],
        "RECOVERY": checks["recovery_path_covers_restart_and_reconciliation"],
    }
    return {
        "e2e_schema_version": SCHEMA_VERSION,
        "slice": "1369",
        "requirement": "S137",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None
            if passed
            else "platform_grounded_generation_artifact_e2e_failed"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "component_statuses": statuses,
        "scenarios": scenarios,
        "required_artifacts": presence,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "component_count": len(statuses),
            "passed_component_count": sum(
                status == "PASS" for status in statuses.values()
            ),
            "scenario_count": len(scenarios),
            "passed_scenario_count": sum(scenarios.values()),
        },
        "decision": {
            "mock_provider_evidence": True,
            "actual_postgresql_or_provider_execution": False,
            "private_payload_persisted_in_evidence": False,
            "next_slice": "1370" if passed else "blocked",
        },
    }


def _run_evidence(root: Path) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for name, runner in EVIDENCE_RUNNERS:
        try:
            evidence[name] = runner(root)
        except (OSError, ValueError) as exc:
            evidence[name] = {
                "status": "FAIL",
                "failure_code": "evidence_unavailable",
                "error_type": type(exc).__name__,
            }
    return evidence


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in FORBIDDEN_PRIVATE_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def summary_line(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "platform_grounded_generation_artifact_e2e="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"components={summary.get('passed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"scenarios={summary.get('passed_scenario_count', 0)}/"
        f"{summary.get('scenario_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_grounded_generation_artifact_e2e()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
