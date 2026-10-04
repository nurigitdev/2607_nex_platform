#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_platform_ag_projection_policy import run_platform_ag_projection_policy
from run_platform_complete_process_manifest import run_platform_complete_process_manifest
from run_platform_endpoint_timeout_policy import run_platform_endpoint_timeout_policy
from run_platform_local_mock_process_smoke import run_platform_local_mock_process_smoke
from run_platform_runtime_dependency_graph import run_platform_runtime_dependency_graph
from run_platform_runtime_manifest_domain import build_domain_evidence
from run_platform_runtime_orchestrator import run_platform_runtime_orchestrator
from run_platform_runtime_profile_composition import (
    run_platform_runtime_profile_composition,
)
from run_platform_runtime_topology_boundary import (
    run_platform_runtime_topology_boundary,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s132_platform_runtime_topology_closure.v1"
CANONICAL_DOCUMENT = "docs/39_platform_runtime_topology_and_configuration.md"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s132_platform_runtime_topology_closure.py"
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, EvidenceRunner], ...] = (
    ("boundary", run_platform_runtime_topology_boundary),
    ("domain", build_domain_evidence),
    ("profiles", run_platform_runtime_profile_composition),
    ("dependencies", run_platform_runtime_dependency_graph),
    ("endpoints", run_platform_endpoint_timeout_policy),
    ("process_manifest", run_platform_complete_process_manifest),
    ("ag_projection", run_platform_ag_projection_policy),
    ("orchestrator", run_platform_runtime_orchestrator),
    ("actual_process_smoke", run_platform_local_mock_process_smoke),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1312", "platform_runtime_topology_boundary"),
        ("1313", "platform_runtime_manifest_domain"),
        ("1314", "platform_runtime_profile_composition"),
        ("1315", "platform_runtime_dependency_graph"),
        ("1316", "platform_endpoint_timeout_policy"),
        ("1317", "platform_complete_process_manifest"),
        ("1318", "platform_ag_api_projection_policy"),
        ("1319", "platform_runtime_orchestrator"),
        ("1320", "platform_local_mock_process_smoke"),
        ("1321", "s132_platform_runtime_topology_closure"),
    )
)


def run_s132_platform_runtime_topology_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (
        *SLICE_DOCUMENTS,
        "docs/37_platform_mvp_integration_release_plan.md",
        CANONICAL_DOCUMENT,
    )
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    evidence = _run_evidence(root) if all(document_presence.values()) else {}
    canonical = _read_text(root / CANONICAL_DOCUMENT)
    plan = _read_text(root / "docs/37_platform_mvp_integration_release_plan.md")
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    profiles = _mapping(evidence.get("profiles"))
    process_manifest = _mapping(evidence.get("process_manifest"))
    ag_projection = _mapping(evidence.get("ag_projection"))
    orchestrator = _mapping(evidence.get("orchestrator"))
    process_smoke = _mapping(evidence.get("actual_process_smoke"))
    profile_rows = profiles.get("profiles") or []
    checks = {
        "all_nine_component_evidence_passed": len(evidence) == 9
        and all(item.get("status") == "PASS" for item in evidence.values()),
        "all_slice_and_canonical_documents_present": all(
            document_presence.values()
        ),
        "closure_registered_once_in_full_gate": quality_gate.count(
            CLOSURE_RUNNER
        )
        == 1,
        "canonical_document_marks_s132_complete": all(
            token in canonical
            for token in (
                "Status: S132 complete",
                "| `1321` | Complete |",
                "## S133 Handoff",
            )
        ),
        "completion_signal_is_preserved": (
            "All backend services start from one explicit local runtime profile "
            "with fail-closed configuration."
        )
        in plan
        and "Completion signal: Met." in canonical,
        "five_profiles_resolve_fail_closed": len(profile_rows) == 5
        and sum(bool(item.get("protected")) for item in profile_rows) == 4
        and profiles.get("protected_failure_count") == 25,
        "complete_process_inventory_is_materialized": (
            process_manifest.get("endpoint_count") == 6
            and process_manifest.get("process_count") == 13
            and process_manifest.get("process_kind_counts")
            == {"api": 5, "web": 1, "worker": 5, "daemon": 2}
        ),
        "protected_ag_projection_is_api_only": (
            ag_projection.get("protected_policy", {}).get("mode") == "api"
            and ag_projection.get("decision", {}).get(
                "protected_cross_service_database_reads_allowed"
            )
            is False
        ),
        "orchestrator_reaches_and_stops_all_processes": (
            orchestrator.get("running_status", {})
            .get("process_counts", {})
            .get("READY")
            == 13
            and orchestrator.get("stopped_status", {})
            .get("process_counts", {})
            .get("STOPPED")
            == 13
        ),
        "actual_local_mock_topology_is_proven": (
            process_smoke.get("actual_process_count") == 13
            and process_smoke.get("http_probe_count") == 6
            and process_smoke.get("decision", {}).get("postgres_contacted")
            is False
            and process_smoke.get("decision", {}).get(
                "remote_provider_contacted"
            )
            is False
        ),
        "rollback_path_is_preserved": (
            process_smoke.get("decision", {}).get("rollback_runner")
            == "scripts/dev/run_all_services.py"
            and "run_all_services.py" in canonical
        ),
        "s133_handoff_requires_actual_five_database_restart": all(
            token in canonical
            for token in (
                "five service-owned test databases",
                "migration heads",
                "restart and durable reload",
                "service-local pools",
                "No remote model provider is required for S133",
            )
        ),
        "later_requirement_boundaries_remain_explicit": all(
            token in canonical
            for token in ("(`S134`)", "(`S135`)", "(`S136`/`S137`)", "(`S138`)")
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1321",
        "slice_range": "1312-1321",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s132_platform_runtime_topology_closure_failed",
        "closure_readiness": "READY_FOR_S133" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "required_documents": document_presence,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "profile_count": len(profile_rows),
            "endpoint_count": int(process_manifest.get("endpoint_count") or 0),
            "process_count": int(process_manifest.get("process_count") or 0),
            "http_probe_count": int(process_smoke.get("http_probe_count") or 0),
        },
        "decision": {
            "completion_signal_met": passed,
            "service_ownership_model_retained": True,
            "shared_database_required": False,
            "database_or_provider_mutation_performed": False,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S133" if passed else "blocked",
            "next_requirement_scope": (
                "cross_service_postgresql_migration_startup_restart_orchestration"
                if passed
                else "blocked"
            ),
        },
    }


def _run_evidence(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {name: runner() for name, runner in EVIDENCE_RUNNERS}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "s132_platform_runtime_topology_closure=fail "
            f"checks={len(evidence.get('failed_checks') or [])}"
        )
    summary = evidence.get("summary") or {}
    return (
        "s132_platform_runtime_topology_closure=pass "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"profiles={summary.get('profile_count', 0)} "
        f"processes={summary.get('process_count', 0)} "
        f"http={summary.get('http_probe_count', 0)} "
        f"next={evidence.get('decision', {}).get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s132_platform_runtime_topology_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
