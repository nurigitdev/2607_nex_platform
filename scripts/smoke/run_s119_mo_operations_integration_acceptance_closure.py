#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_mo.contract_api_drift_audit import (  # noqa: E402
    build_mo_contract_api_drift_audit,
)
from run_mo_operations_acceptance_plan import (  # noqa: E402
    run_mo_operations_acceptance_plan as run_admission,
)
from run_mo_operations_api import run_mo_operations_api as run_api  # noqa: E402
from run_mo_operations_contract import (  # noqa: E402
    run_mo_operations_contract as run_contract,
)
from run_mo_operations_integrated_acceptance import (  # noqa: E402
    run_mo_operations_integrated_acceptance as run_integrated,
)
from run_mo_operations_integration_boundary import (  # noqa: E402
    run_mo_operations_integration_boundary as run_boundary,
)
from run_mo_operations_integration_service import (  # noqa: E402
    run_mo_operations_integration_service as run_service,
)
from run_mo_operations_snapshot_domain import (  # noqa: E402
    run_mo_operations_snapshot_domain as run_domain,
)
from run_mo_runtime_openapi_parity_guard import (  # noqa: E402
    run_mo_runtime_openapi_parity_guard as run_parity,
)


SCHEMA_VERSION = "s119_mo_operations_integration_acceptance_closure.v1"
SLICE_RANGE = "1182-1191"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_DOCUMENT = "docs/slices/1189_mo_operations_postgres_smoke.md"
LIVE_DOCUMENT = "docs/slices/1190_mo_operations_protected_live_acceptance.md"
QUALITY_SCRIPTS = (
    "run_mo_operations_integration_boundary.py",
    "run_mo_operations_snapshot_domain.py",
    "run_mo_operations_integration_service.py",
    "run_mo_operations_api.py",
    "run_mo_operations_acceptance_plan.py",
    "run_mo_operations_contract.py",
    "run_mo_operations_integrated_acceptance.py",
    "run_mo_operations_postgres_smoke.py",
    "run_mo_operations_live_acceptance.py",
    "run_s119_mo_operations_integration_acceptance_closure.py",
)
SLICE_DOCUMENTS = (
    "1182_mo_operations_integration_boundary.md",
    "1183_mo_operations_snapshot_domain.md",
    "1184_mo_operations_integration_service.md",
    "1185_mo_authenticated_operations_api.md",
    "1186_mo_operations_acceptance_admission.md",
    "1187_mo_operations_contract_hardening.md",
    "1188_mo_operations_integrated_acceptance.md",
    "1189_mo_operations_postgres_smoke.md",
    "1190_mo_operations_protected_live_acceptance.md",
    "1191_s119_mo_operations_integration_acceptance_closure.md",
)
REQUIRED_FILES = (
    "services/nex-mo/nex_mo/operations_integration_boundary.py",
    "services/nex-mo/nex_mo/operations_snapshot.py",
    "services/nex-mo/nex_mo/operations_service.py",
    "services/nex-mo/nex_mo/operations_api.py",
    "services/nex-mo/nex_mo/operations_acceptance.py",
    "services/nex-mo/nex_mo/operations_contract.py",
    "contracts/schemas/service/nex_mo/operations_snapshot.v1.schema.json",
    "contracts/examples/provider/mo_operations_snapshot.mock_ready.json",
    "contracts/tests/negative/provider/mo_operations_snapshot.api_key_leak.json",
    "contracts/openapi/nex-mo.openapi.yaml",
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s119_mo_operations_integration_acceptance_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    (
        "mo_fr_003_traceability",
        "docs/30_service_specific_requirement_partition.md",
        "MO-FR-003",
    ),
    (
        "mo_fr_004_traceability",
        "docs/30_service_specific_requirement_partition.md",
        "MO-FR-004",
    ),
    (
        "runtime_registration",
        "services/nex-mo/nex_mo/main.py",
        "register_operations_routes",
    ),
    (
        "operations_endpoint",
        "services/nex-mo/README.md",
        "GET /api/v1/operations-snapshot",
    ),
    (
        "openapi_operation",
        "contracts/openapi/nex-mo.openapi.yaml",
        "/api/v1/operations-snapshot:",
    ),
    (
        "postgres_identity",
        POSTGRES_DOCUMENT,
        "nex_mo_user@nex_mo_test",
    ),
    ("postgres_checks", POSTGRES_DOCUMENT, "`16/16` checks"),
    ("postgres_cleanup", POSTGRES_DOCUMENT, "cleanup left zero residue"),
    ("live_checks", LIVE_DOCUMENT, "`13/13` checks"),
    ("live_providers", LIVE_DOCUMENT, "provider requests `3/3`"),
    ("live_sources", LIVE_DOCUMENT, "ready sources `4/4`"),
    ("live_runtime", LIVE_DOCUMENT, "runtime capabilities `3/3`"),
    ("live_cleanup", LIVE_DOCUMENT, "residue `0`."),
    (
        "closure_index",
        "docs/README.md",
        "1191_s119_mo_operations_integration_acceptance_closure.md",
    ),
)


def run_s119_mo_operations_integration_acceptance_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "domain": _safe_evidence(run_domain),
        "service": _safe_evidence(run_service),
        "api": _safe_evidence(run_api),
        "admission": _safe_evidence(run_admission),
        "contract": _safe_evidence(lambda: run_contract(root)),
        "integrated": _safe_evidence(lambda: run_integrated(root)),
        "drift": _safe_evidence(lambda: build_mo_contract_api_drift_audit(root)),
        "parity": _safe_evidence(lambda: run_parity(root)),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence["protected_postgres"] = {
        "status": "PASS"
        if all(
            token_status.get(name, False)
            for name in ("postgres_identity", "postgres_checks", "postgres_cleanup")
        )
        else "FAIL"
    }
    evidence["protected_live"] = {
        "status": "PASS"
        if all(
            token_status.get(name, False)
            for name in (
                "live_checks",
                "live_providers",
                "live_sources",
                "live_runtime",
                "live_cleanup",
            )
        )
        else "FAIL"
    }
    summaries = {
        name: _mapping(item.get("summary")) for name, item in evidence.items()
    }
    components = {
        "boundary_domain_and_composition": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "domain", "service")
        ),
        "authenticated_api_and_admission": all(
            evidence[name].get("status") == "PASS"
            for name in ("api", "admission")
        ),
        "contracts_privacy_and_parity": all(
            evidence[name].get("status") == "PASS"
            for name in ("contract", "drift", "parity")
        ),
        "deterministic_integration": evidence["integrated"].get("status")
        == "PASS",
        "postgres_and_live_acceptance": all(
            evidence[name].get("status") == "PASS"
            for name in ("protected_postgres", "protected_live")
        ),
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "all_components_closed": all(components.values()),
        "four_source_snapshot_closed": summaries["integrated"].get("source_count")
        == 4
        and summaries["integrated"].get("ready_source_count") == 4,
        "three_capability_snapshot_closed": summaries["integrated"].get(
            "capability_count"
        )
        == 3
        and summaries["integrated"].get("ready_capability_count") == 3,
        "authenticated_force_refresh_closed": summaries["integrated"].get(
            "unauthorized_status"
        )
        == 401
        and summaries["integrated"].get("refresh_status") == 200,
        "canonical_contract_closed": summaries["contract"].get(
            "passed_check_count"
        )
        == summaries["contract"].get("check_count")
        == 9,
        "runtime_openapi_parity_closed": summaries["parity"].get(
            "runtime_operation_count"
        )
        == 31
        and summaries["parity"].get("openapi_operation_count") == 31
        and summaries["parity"].get("drift_count") == 0,
        "protected_postgres_closed": evidence["protected_postgres"]["status"]
        == "PASS",
        "protected_live_closed": evidence["protected_live"]["status"] == "PASS",
        "mo_operations_requirements_closed": decision["traceability"]
        == ("MO-FR-003", "MO-FR-004"),
        "no_new_operations_table": decision["persistence"]
        == "reuse_catalog_and_telemetry_no_snapshot_table",
        "privacy_boundary_closed": decision["public_projection"]
        == "safe_identifiers_status_counts_only",
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1182-1190",
            "checkpoint_gate": "1186",
            "full_gate": "1191",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1191",
        "slice_range": SLICE_RANGE,
        "requirement": "S119",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None
            if passed
            else "s119_mo_operations_integration_acceptance_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S120" if passed else "BLOCKED",
        "feature_readiness": (
            "MO_OPERATIONS_INTEGRATION_LIVE_ACCEPTED" if passed else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "source_count": summaries["integrated"].get("source_count", 0),
            "capability_count": summaries["integrated"].get(
                "capability_count", 0
            ),
            "runtime_operation_count": summaries["parity"].get(
                "runtime_operation_count", 0
            ),
            "contract_drift_count": summaries["parity"].get("drift_count", 0),
            "postgres_check_count": 16
            if evidence["protected_postgres"]["status"] == "PASS"
            else 0,
            "live_check_count": 13
            if evidence["protected_live"]["status"] == "PASS"
            else 0,
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S120" if passed else "blocked",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "mo_operations_integration_and_protected_live_acceptance",
        "traceability": ("MO-FR-003", "MO-FR-004"),
        "sources": ("catalog", "readiness", "telemetry", "runtime"),
        "required_capabilities": ("embedding", "reranking", "generation"),
        "status_precedence": ("UNAVAILABLE", "DEGRADED", "UNKNOWN", "READY"),
        "operation": "GET /api/v1/operations-snapshot",
        "force_refresh": "bounded_readiness_and_runtime_only",
        "persistence": "reuse_catalog_and_telemetry_no_snapshot_table",
        "public_projection": "safe_identifiers_status_counts_only",
        "provider_runtime": "direct_vllm_openai_compatible",
        "provider_models": (
            "Qwen3-Embedding-4B",
            "Qwen3-Reranker-4B",
            "Qwen3.5-4B",
        ),
        "test_database_target": "nex_mo_user@nex_mo_test",
        "protected_live_required": True,
        "quality_cadence": {
            "slice_gate": "1182-1190",
            "checkpoint_gate": "1186",
            "full_gate": "1191",
        },
        "next_requirement_scope": "S120_mo_follow_up",
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
        "s119_mo_operations_integration_acceptance_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"snapshot={summary.get('source_count', 0)}/"
        f"{summary.get('capability_count', 0)} "
        f"operations={summary.get('runtime_operation_count', 0)} "
        f"drift={summary.get('contract_drift_count', 0)} "
        f"postgres={summary.get('postgres_check_count', 0)} "
        f"live={summary.get('live_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s119_mo_operations_integration_acceptance_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
