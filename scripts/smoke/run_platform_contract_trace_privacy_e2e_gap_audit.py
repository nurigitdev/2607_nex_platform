#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_contract_trace_privacy_e2e_gap_audit.v1"
E2E_SCENARIO_COUNT = 10
INVENTORY_EXCLUDED_NAMES = frozenset(
    {
        "run_platform_vertical_spine_reaudit_boundary.py",
        "test_platform_vertical_spine_reaudit_boundary.py",
        "run_platform_contract_trace_privacy_e2e_gap_audit.py",
        "test_platform_contract_trace_privacy_e2e_gap_audit.py",
    }
)
TRACE_CLIENT_PATHS = (
    "services/nex-ae-api/nex_ae_api/uploads.py",
    "services/nex-ae-api/nex_ae_api/documents.py",
    "services/nex-ae-api/nex_ae_api/retrieval.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/nex-ae-api/nex_ae_api/cx_async_generation_client.py",
    "services/nex-ae-api/nex_ae_api/recovery_requests.py",
    "services/nex-ae-api/nex_ae_api/repaired_response_client.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-cx/nex_cx/embedding_index.py",
    "services/nex-cx/nex_cx/retrieval.py",
    "services/nex-cx/nex_cx/generation.py",
    "services/nex-ag/nex_ag/generation_audit.py",
    "services/nex-ag/nex_ag/artifact_operations.py",
)


def run_platform_contract_trace_privacy_e2e_gap_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    e2e_plan = _read_text(
        root / "docs/28_generation_e2e_acceptance_contract_test_plan.md"
    )
    quality_gate = _read_text(root / "scripts/quality/run_quality_gate.sh")
    operational_events = _read_text(
        root / "services/_shared/nex_runtime/operational_events.py"
    )
    service_logs = _read_text(root / "services/_shared/nex_runtime/service_logs.py")
    jobs = _read_text(root / "services/_shared/nex_runtime/jobs.py")
    ag_operations = _read_text(
        root / "services/nex-ag/nex_ag/cross_service_trace.py"
    )
    ag_generation = _read_text(root / "services/nex-ag/nex_ag/generation_audit.py")
    ag_openapi = _read_text(root / "contracts/openapi/nex-ag.openapi.yaml")

    contract_counts = {
        "schemas": len(tuple((root / "contracts/schemas").glob("**/*.schema.json"))),
        "examples": _index_count(
            root / "contracts/examples/index.json",
            "examples",
        ),
        "negative_examples": _index_count(
            root / "contracts/tests/negative/index.json",
            "negative_examples",
        ),
        "openapi": len(
            tuple(
                path
                for path in (root / "contracts/openapi").glob("*")
                if path.is_file() and path.suffix in {".json", ".yaml", ".yml"}
            )
        ),
    }
    scenario_ids = [f"GEN-E2E-{index:03d}" for index in range(1, 11)]
    executable_scenario_ids = _executable_e2e_ids(root)
    trace_clients = [
        {
            "path": path,
            "present": (root / path).is_file(),
            "request_id": '"X-Request-ID"' in _read_text(root / path),
            "traceparent": '"traceparent"' in _read_text(root / path),
        }
        for path in TRACE_CLIENT_PATHS
    ]
    shared_sensitive_tokens = (
        '"api_key"',
        '"authorization"',
        '"password"',
        '"raw_prompt"',
        '"source_text"',
        '"token"',
    )
    ag_forbidden_tokens = (
        '"raw_prompt"',
        '"raw_output"',
        '"provider_url"',
        '"storage_path"',
        '"authorization"',
    )
    checks = {
        "ten_golden_scenarios_are_defined": all(
            scenario_id in e2e_plan for scenario_id in scenario_ids
        ),
        "contract_catalogs_are_populated": all(
            count > 0 for count in contract_counts.values()
        ),
        "full_gate_runs_contract_validation": (
            "scripts/quality/validate_contracts.py" in quality_gate
        ),
        "core_http_clients_propagate_request_and_trace": all(
            item["present"] and item["request_id"] and item["traceparent"]
            for item in trace_clients
        ),
        "durable_jobs_events_and_logs_store_trace_fields": all(
            token in source
            for source in (jobs, operational_events, service_logs)
            for token in ('"trace_id"', '"request_id"')
        ),
        "ag_exposes_cross_service_trace_projection": (
            'AG_TRACE_OPERATIONS_PATH = "/admin/v1/operations/traces/{trace_id}"'
            in ag_operations
            and "/admin/v1/operations/traces/{trace_id}:" in ag_openapi
        ),
        "shared_and_ag_privacy_denylists_cover_raw_sensitive_data": (
            all(token in operational_events for token in shared_sensitive_tokens)
            and all(token in service_logs for token in shared_sensitive_tokens)
            and "FORBIDDEN_DETAIL_KEYS" in ag_generation
            and all(token in ag_generation for token in ag_forbidden_tokens)
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    privacy_test_count = len(tuple(root.glob("tests/test_*privacy*.py")))
    privacy_runner_count = len(tuple(root.glob("scripts/smoke/run_*privacy*.py")))
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1310",
        "requirement": "S131",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None
        if not issues
        else "platform_contract_trace_privacy_e2e_gap_audit_failed",
        "checks": checks,
        "issues": issues,
        "contract_counts": contract_counts,
        "trace_clients": trace_clients,
        "findings": {
            "golden_scenario_contract_count": len(scenario_ids),
            "executable_named_golden_scenario_count": len(executable_scenario_ids),
            "executable_named_golden_scenario_ids": executable_scenario_ids,
            "trace_propagating_http_client_count": sum(
                item["request_id"] and item["traceparent"] for item in trace_clients
            ),
            "privacy_test_count": privacy_test_count,
            "privacy_runner_count": privacy_runner_count,
            "single_trace_vertical_spine_evidence_present": False,
            "named_generation_e2e_suite_present": bool(executable_scenario_ids),
        },
        "scenario_handoff": {
            "001": "S137/S140 general-answer orchestration",
            "002": "S136/S137 grounded evidence and citations",
            "003": "S137/S139 report artifact export",
            "004": "S136/S137/S139 no-answer guardrail",
            "005": "S137 compatibility mismatch rejection",
            "006": "S137 provider timeout retry lineage",
            "007": "S137 citation repair boundary",
            "008": "S137/S139 render retry",
            "009": "S137/S139 artifact permission",
            "010": "S138 redacted AG audit export",
        },
        "refactoring_candidates": [
            {
                "priority": "P0",
                "owner": "platform-acceptance",
                "gap": "add one deterministic named runner for all ten generation golden scenarios",
                "target_requirement": "S140",
            },
            {
                "priority": "P0",
                "owner": "platform-observability",
                "gap": "prove one trace ID across OA, AE, CX, MO, artifact, and AG API projections",
                "target_requirement": "S138",
            },
            {
                "priority": "P1",
                "owner": "platform-contracts",
                "gap": "bind each named golden scenario to exact schema, OpenAPI route, privacy, and recovery evidence",
                "target_requirement": "S137/S140",
            },
        ],
        "decision": {
            "existing_contract_and_privacy_regressions_are_retained": True,
            "distributed_component_tests_equal_named_e2e_acceptance": False,
            "live_provider_evidence_replaces_mock_e2e": False,
            "database_or_provider_mutation_performed": False,
            "next_slice": "1311",
        },
    }


def _executable_e2e_ids(root: Path) -> list[str]:
    found: set[str] = set()
    for directory in (root / "tests", root / "scripts"):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if (
                not path.is_file()
                or path.suffix not in {".py", ".sh", ".mjs"}
                or path.name in INVENTORY_EXCLUDED_NAMES
            ):
                continue
            source = _read_text(path)
            for index in range(1, E2E_SCENARIO_COUNT + 1):
                scenario_id = f"GEN-E2E-{index:03d}"
                if scenario_id in source:
                    found.add(scenario_id)
    return sorted(found)


def _index_count(path: Path, key: str) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    entries = payload.get(key)
    return len(entries) if isinstance(entries, list) else 0


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "platform_contract_trace_privacy_e2e_gap=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    findings = evidence.get("findings") or {}
    contracts = evidence.get("contract_counts") or {}
    return (
        "platform_contract_trace_privacy_e2e_gap=pass "
        f"contracts={contracts.get('schemas', 0)}/{contracts.get('examples', 0)}/"
        f"{contracts.get('negative_examples', 0)}/{contracts.get('openapi', 0)} "
        f"trace_clients={findings.get('trace_propagating_http_client_count', 0)} "
        f"named_e2e={findings.get('executable_named_golden_scenario_count', 0)}/10 "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_contract_trace_privacy_e2e_gap_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
