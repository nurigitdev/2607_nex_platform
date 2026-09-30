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

from run_mo_provider_resilience_boundary import (  # noqa: E402
    run_mo_provider_resilience_boundary as run_boundary,
)
from run_mo_provider_resilience_composition import (  # noqa: E402
    run_mo_provider_resilience_composition as run_composition,
)
from run_mo_provider_resilience_contract import (  # noqa: E402
    run_mo_provider_resilience_contract as run_contract,
)
from run_mo_provider_retry_executor import (  # noqa: E402
    run_mo_provider_retry_executor as run_executor,
)
from run_mo_provider_retry_loopback_http_smoke import (  # noqa: E402
    run_mo_provider_retry_loopback_http_smoke as run_loopback,
)
from run_mo_provider_retry_policy import (  # noqa: E402
    run_mo_provider_retry_policy as run_policy,
)
from run_mo_provider_retry_telemetry import (  # noqa: E402
    run_mo_provider_retry_telemetry as run_telemetry,
)
from run_mo_provider_retry_transport import (  # noqa: E402
    run_mo_provider_retry_transport as run_transport,
)
from run_mo_provider_retry_wiring import (  # noqa: E402
    run_mo_provider_retry_wiring as run_wiring,
)


SCHEMA_VERSION = "s115_mo_provider_resilience_retry_closure.v1"
SLICE_RANGE = "1142-1151"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
QUALITY_SCRIPTS = (
    "run_mo_provider_resilience_boundary.py",
    "run_mo_provider_retry_policy.py",
    "run_mo_provider_retry_executor.py",
    "run_mo_provider_retry_transport.py",
    "run_mo_provider_retry_wiring.py",
    "run_mo_provider_retry_telemetry.py",
    "run_mo_provider_resilience_composition.py",
    "run_mo_provider_retry_loopback_http_smoke.py",
    "run_mo_provider_resilience_contract.py",
    "run_s115_mo_provider_resilience_retry_closure.py",
)
SLICE_DOCUMENTS = (
    "1142_mo_provider_resilience_retry_boundary.md",
    "1143_mo_provider_retry_policy_failure_taxonomy.md",
    "1144_mo_bounded_retry_executor.md",
    "1145_mo_provider_retry_transport_integration.md",
    "1146_mo_provider_retry_capability_wiring.md",
    "1147_mo_provider_retry_telemetry.md",
    "1148_mo_provider_readiness_resilience_composition.md",
    "1149_mo_provider_retry_loopback_http_smoke.md",
    "1150_mo_provider_resilience_contract_hardening.md",
    "1151_s115_mo_provider_resilience_retry_closure.md",
)
REQUIRED_FILES = (
    "services/nex-mo/nex_mo/provider_retry.py",
    "services/nex-mo/nex_mo/provider_retry_transport.py",
    "services/nex-mo/nex_mo/provider_resilience.py",
    "services/nex-mo/nex_mo/provider_resilience_contract.py",
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s115_mo_provider_resilience_retry_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    (
        "attempt_policy",
        "services/nex-mo/nex_mo/provider_retry.py",
        '"generation": 2',
    ),
    (
        "ambiguous_replay_guard",
        "services/nex-mo/nex_mo/provider_retry.py",
        "GENERATION_AMBIGUOUS_FAILURE_KINDS",
    ),
    (
        "retry_telemetry",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        "def record_provider_retry",
    ),
    (
        "explicit_openapi_retry",
        "contracts/openapi/nex-mo.openapi.yaml",
        "ProviderTelemetryItem",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1151_s115_mo_provider_resilience_retry_closure.md",
    ),
)


def run_s115_mo_provider_resilience_retry_closure(
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
        "policy": _safe_evidence(run_policy),
        "executor": _safe_evidence(run_executor),
        "transport": _safe_evidence(run_transport),
        "wiring": _safe_evidence(run_wiring),
        "telemetry": _safe_evidence(run_telemetry),
        "composition": _safe_evidence(run_composition),
        "loopback_http": _safe_evidence(run_loopback),
        "contract": _safe_evidence(run_contract),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    components = {
        "bounded_retry_policy": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "policy", "executor")
        ),
        "transport_and_capability_wiring": all(
            evidence[name].get("status") == "PASS"
            for name in ("transport", "wiring")
        ),
        "telemetry_and_readiness_composition": all(
            evidence[name].get("status") == "PASS"
            for name in ("telemetry", "composition")
        ),
        "real_http_fault_evidence": evidence["loopback_http"].get("status")
        == "PASS",
        "contract_and_quality_handoff": evidence["contract"].get("status")
        == "PASS"
        and all(token_status.values()),
    }
    decision = _closure_decision()
    boundary_policy = _mapping(evidence["boundary"].get("resilience_policy"))
    wiring_summary = _mapping(evidence["wiring"].get("summary"))
    telemetry_summary = _mapping(evidence["telemetry"].get("summary"))
    loopback_summary = _mapping(evidence["loopback_http"].get("summary"))
    contract_summary = _mapping(evidence["contract"].get("summary"))
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_deterministic_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "all_components_closed": all(components.values()),
        "capability_attempt_limits_closed": boundary_policy.get("attempt_limits")
        == {"embedding": 3, "reranking": 3, "generation": 2},
        "generation_ambiguous_replay_closed": wiring_summary.get(
            "ambiguous_generation_attempt_count"
        )
        == 1,
        "logical_request_attempt_telemetry_closed": telemetry_summary.get(
            "request_count"
        )
        == 1
        and telemetry_summary.get("attempt_count") == 2
        and telemetry_summary.get("retry_count") == 1,
        "real_http_retry_evidence_closed": loopback_summary.get(
            "capability_count"
        )
        == 3
        and loopback_summary.get("http_request_count") == 6,
        "contract_drift_remains_zero": contract_summary.get("drift_count") == 0,
        "scope_deferrals_preserved": decision["durable_telemetry_requirement"]
        == "S116"
        and decision["gpu_observability_requirement"] == "S117",
        "no_database_or_dgx_dependency_added": decision["new_table_added"] is False
        and decision["database_smoke_required"] is False
        and decision["external_dgx_call_required"] is False,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1151",
        "slice_range": SLICE_RANGE,
        "requirement": "S115",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s115_mo_provider_resilience_retry_closure_failed",
        "closure_readiness": "READY_FOR_S116" if passed else "BLOCKED",
        "feature_readiness": "MO_PROVIDER_RETRY_HARDENED" if passed else "INCOMPLETE",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "capability_count": loopback_summary.get("capability_count", 0),
            "loopback_http_request_count": loopback_summary.get(
                "http_request_count", 0
            ),
            "contract_drift_count": contract_summary.get("drift_count", -1),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S116" if passed else "blocked",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "mo_provider_resilience_and_retry_hardening",
        "attempt_limits": {"embedding": 3, "reranking": 3, "generation": 2},
        "retry_budget_scope": "single_logical_provider_request",
        "generation_ambiguous_replay": "blocked",
        "readiness_authority": "active_provider_route_readiness",
        "retry_pressure_projection": "separate_from_current_health",
        "telemetry_persistence": "process_local",
        "durable_telemetry_requirement": "S116",
        "gpu_observability_requirement": "S117",
        "new_table_added": False,
        "database_smoke_required": False,
        "external_dgx_call_required": False,
        "quality_cadence": {
            "slice_gate": "1142-1151",
            "checkpoint_gate": "1146",
            "full_gate": "1151",
        },
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
        "s115_mo_provider_resilience_retry_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"http={summary.get('loopback_http_request_count', 0)} "
        f"drift={summary.get('contract_drift_count', -1)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s115_mo_provider_resilience_retry_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
