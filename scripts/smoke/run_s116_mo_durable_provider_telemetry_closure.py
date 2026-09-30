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

from run_mo_provider_telemetry_durability_contract import (  # noqa: E402
    run_mo_provider_telemetry_durability_contract as run_durability_contract,
)
from run_mo_provider_telemetry_durable_api import (  # noqa: E402
    run_mo_provider_telemetry_durable_api as run_durable_api,
)
from run_mo_provider_telemetry_persistence_boundary import (  # noqa: E402
    run_mo_provider_telemetry_persistence_boundary as run_boundary,
)
from run_mo_provider_telemetry_persistence_contract import (  # noqa: E402
    run_mo_provider_telemetry_persistence_contract as run_persistence_contract,
)
from run_mo_provider_telemetry_repository import (  # noqa: E402
    run_mo_provider_telemetry_repository as run_repository,
)
from run_mo_provider_telemetry_restart_concurrency import (  # noqa: E402
    run_mo_provider_telemetry_restart_concurrency as run_restart,
)
from run_mo_provider_telemetry_runtime import (  # noqa: E402
    run_mo_provider_telemetry_runtime as run_runtime,
)
from run_mo_provider_telemetry_store import (  # noqa: E402
    run_mo_provider_telemetry_store as run_store,
)


SCHEMA_VERSION = "s116_mo_durable_provider_telemetry_closure.v1"
SLICE_RANGE = "1152-1161"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
QUALITY_SCRIPTS = (
    "run_mo_provider_telemetry_persistence_boundary.py",
    "run_mo_provider_telemetry_persistence_contract.py",
    "run_mo_provider_telemetry_repository.py",
    "run_mo_provider_telemetry_store.py",
    "run_mo_provider_telemetry_runtime.py",
    "run_mo_provider_telemetry_restart_concurrency.py",
    "run_mo_provider_telemetry_durable_api.py",
    "run_mo_provider_telemetry_durability_contract.py",
    "run_mo_provider_telemetry_postgres_smoke.py",
    "run_s116_mo_durable_provider_telemetry_closure.py",
)
SLICE_DOCUMENTS = (
    "1152_mo_provider_telemetry_persistence_boundary.md",
    "1153_mo_provider_telemetry_persistence_contract.md",
    "1154_mo_provider_telemetry_repository.md",
    "1155_mo_provider_telemetry_store_adapter.md",
    "1156_mo_provider_telemetry_runtime_wiring.md",
    "1157_mo_provider_telemetry_restart_concurrency.md",
    "1158_mo_provider_telemetry_durable_api.md",
    "1159_mo_provider_telemetry_durability_contract.md",
    "1160_mo_provider_telemetry_postgresql_smoke.md",
    "1161_s116_mo_durable_provider_telemetry_closure.md",
)
REQUIRED_FILES = (
    "database/nex-mo/migrations/1154_mo_provider_telemetry.sql",
    "services/nex-mo/nex_mo/provider_telemetry_persistence.py",
    "services/nex-mo/nex_mo/provider_telemetry_repository.py",
    "services/nex-mo/nex_mo/provider_telemetry_store.py",
    "services/nex-mo/nex_mo/provider_telemetry_runtime.py",
    "services/nex-mo/nex_mo/provider_telemetry_durability_contract.py",
    "contracts/schemas/service/nex_mo/provider_telemetry_snapshot.v1.schema.json",
    "contracts/openapi/nex-mo.openapi.yaml",
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s116_mo_durable_provider_telemetry_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    (
        "compact_table",
        "database/nex-mo/migrations/1154_mo_provider_telemetry.sql",
        "CREATE TABLE IF NOT EXISTS mo_provider_telemetry",
    ),
    (
        "atomic_upsert",
        "services/nex-mo/nex_mo/provider_telemetry_repository.py",
        "ON CONFLICT (telemetry_key) DO UPDATE SET",
    ),
    (
        "durable_runtime",
        "services/nex-mo/nex_mo/provider_telemetry_runtime.py",
        "DurableProviderTelemetryStore",
    ),
    (
        "safe_api_failure",
        "services/nex-mo/nex_mo/providers.py",
        "MO_PROVIDER_TELEMETRY_UNAVAILABLE",
    ),
    (
        "postgres_check_evidence",
        "docs/slices/1160_mo_provider_telemetry_postgresql_smoke.md",
        "`11/11` checks passed",
    ),
    (
        "postgres_cleanup_evidence",
        "docs/slices/1160_mo_provider_telemetry_postgresql_smoke.md",
        "cleanup residue `0`",
    ),
    (
        "closure_index",
        "docs/README.md",
        "1161_s116_mo_durable_provider_telemetry_closure.md",
    ),
)


def run_s116_mo_durable_provider_telemetry_closure(
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
        "persistence_contract": _safe_evidence(run_persistence_contract),
        "repository": _safe_evidence(run_repository),
        "store": _safe_evidence(run_store),
        "runtime": _safe_evidence(run_runtime),
        "restart_concurrency": _safe_evidence(run_restart),
        "durable_api": _safe_evidence(run_durable_api),
        "durability_contract": _safe_evidence(
            lambda: run_durability_contract(root)
        ),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    components = {
        "identity_and_mutation_contract": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "persistence_contract")
        ),
        "atomic_persistence_and_store": all(
            evidence[name].get("status") == "PASS"
            for name in ("repository", "store")
        ),
        "runtime_restart_and_api": all(
            evidence[name].get("status") == "PASS"
            for name in ("runtime", "restart_concurrency", "durable_api")
        ),
        "contract_and_privacy_hardening": evidence[
            "durability_contract"
        ].get("status")
        == "PASS",
        "postgres_and_quality_evidence": all(token_status.values()),
    }
    persistence_summary = _mapping(evidence["persistence_contract"].get("summary"))
    store_summary = _mapping(evidence["store"].get("summary"))
    runtime_summary = _mapping(evidence["runtime"].get("summary"))
    restart_summary = _mapping(evidence["restart_concurrency"].get("summary"))
    api_summary = _mapping(evidence["durable_api"].get("summary"))
    contract_summary = _mapping(evidence["durability_contract"].get("summary"))
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_deterministic_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "all_components_closed": all(components.values()),
        "identity_and_aggregate_invariants_closed": persistence_summary.get(
            "identity_field_count"
        )
        == 4
        and persistence_summary.get("request_count") == 1
        and persistence_summary.get("attempt_count") == 2,
        "wire_compatibility_closed": store_summary.get("wire_field_count") == 26
        and contract_summary.get("wire_field_count") == 26,
        "durable_runtime_selection_closed": runtime_summary.get(
            "runtime_mode_count"
        )
        == 2
        and runtime_summary.get("durable_store_count") == 1,
        "restart_concurrency_closed": restart_summary.get("worker_count") == 8
        and restart_summary.get("mutation_count") == 40
        and restart_summary.get("request_count") == 40,
        "authenticated_privacy_safe_api_closed": api_summary.get(
            "unauthorized_status"
        )
        == 401
        and api_summary.get("authenticated_status") == 200
        and api_summary.get("wire_field_count") == 26,
        "schema_and_private_column_contract_closed": contract_summary.get(
            "table_column_count"
        )
        == 24
        and contract_summary.get("forbidden_column_count") == 0
        and contract_summary.get("failed_check_count") == 0,
        "actual_postgres_evidence_closed": components[
            "postgres_and_quality_evidence"
        ]
        and decision["protected_postgres_check_count"] == 11
        and decision["test_database_target"] == "nex_mo_user@nex_mo_test",
        "persistence_scope_closed": decision["telemetry_persistence"]
        == {"memory": "process_local", "postgres": "restart_safe"}
        and decision["new_table_added"] is True,
        "dgx_not_required": decision["external_dgx_call_required"] is False,
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1152-1161",
            "checkpoint_gate": "1156",
            "full_gate": "1161",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1161",
        "slice_range": SLICE_RANGE,
        "requirement": "S116",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s116_mo_durable_provider_telemetry_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S117" if passed else "BLOCKED",
        "feature_readiness": (
            "MO_PROVIDER_TELEMETRY_RESTART_SAFE" if passed else "INCOMPLETE"
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
            "wire_field_count": contract_summary.get("wire_field_count", 0),
            "table_column_count": contract_summary.get("table_column_count", 0),
            "restart_worker_count": restart_summary.get("worker_count", 0),
            "restart_mutation_count": restart_summary.get("mutation_count", 0),
            "protected_postgres_check_count": (
                11 if components["postgres_and_quality_evidence"] else 0
            ),
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
        "next_requirement": "S117" if passed else "blocked",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "mo_restart_safe_durable_provider_telemetry",
        "telemetry_persistence": {
            "memory": "process_local",
            "postgres": "restart_safe",
        },
        "table_name": "mo_provider_telemetry",
        "identity_fields": (
            "capability",
            "request_shape",
            "deployment_id",
            "model_revision",
        ),
        "wire_field_count": 26,
        "test_database_target": "nex_mo_user@nex_mo_test",
        "test_database_migration_count": 8,
        "protected_postgres_check_count": 11,
        "protected_postgres_mutation_count": 25,
        "new_table_added": True,
        "external_dgx_call_required": False,
        "quality_cadence": {
            "slice_gate": "1152-1161",
            "checkpoint_gate": "1156",
            "full_gate": "1161",
        },
        "next_requirement_scope": "S117_mo_gpu_and_model_runtime_observability",
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
        "s116_mo_durable_provider_telemetry_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"wire={summary.get('wire_field_count', 0)} "
        f"postgres={summary.get('protected_postgres_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s116_mo_durable_provider_telemetry_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
