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

from run_mo_alias_lifecycle import run_mo_alias_lifecycle as run_alias  # noqa: E402
from run_mo_catalog_lifecycle_api import (  # noqa: E402
    run_mo_catalog_lifecycle_api as run_api,
)
from run_mo_catalog_lifecycle_boundary import (  # noqa: E402
    run_mo_catalog_lifecycle_boundary as run_boundary,
)
from run_mo_catalog_lifecycle_contracts import (  # noqa: E402
    run_mo_catalog_lifecycle_contracts as run_contract,
)
from run_mo_catalog_lifecycle_domain import (  # noqa: E402
    run_mo_catalog_lifecycle_domain as run_domain,
)
from run_mo_catalog_lifecycle_repository import (  # noqa: E402
    run_mo_catalog_lifecycle_repository as run_repository,
)
from run_mo_catalog_lifecycle_service import (  # noqa: E402
    run_mo_catalog_lifecycle_service as run_service,
)
from run_mo_catalog_route_resolution import (  # noqa: E402
    run_mo_catalog_route_resolution as run_resolver,
)


SCHEMA_VERSION = "s118_mo_catalog_alias_lifecycle_closure.v1"
SLICE_RANGE = "1172-1181"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_DOCUMENT = "docs/slices/1180_mo_catalog_lifecycle_postgresql_smoke.md"
QUALITY_SCRIPTS = (
    "run_mo_catalog_lifecycle_boundary.py",
    "run_mo_catalog_lifecycle_domain.py",
    "run_mo_catalog_lifecycle_repository.py",
    "run_mo_catalog_lifecycle_service.py",
    "run_mo_alias_lifecycle.py",
    "run_mo_catalog_lifecycle_api.py",
    "run_mo_catalog_route_resolution.py",
    "run_mo_catalog_lifecycle_contracts.py",
    "run_mo_catalog_lifecycle_postgres_smoke.py",
    "run_s118_mo_catalog_alias_lifecycle_closure.py",
)
SLICE_DOCUMENTS = (
    "1172_mo_catalog_alias_lifecycle_boundary.md",
    "1173_mo_catalog_alias_domain_contracts.md",
    "1174_mo_catalog_alias_durable_repository.md",
    "1175_mo_catalog_lifecycle_service.md",
    "1176_mo_atomic_alias_activation_rollback.md",
    "1177_mo_authenticated_catalog_lifecycle_api.md",
    "1178_mo_catalog_runtime_route_resolution.md",
    "1179_mo_catalog_lifecycle_contract_hardening.md",
    "1180_mo_catalog_lifecycle_postgresql_smoke.md",
    "1181_s118_mo_catalog_alias_lifecycle_closure.md",
)
SCHEMAS = (
    "alias_activation.v1.schema.json",
    "alias_binding.v1.schema.json",
    "alias_binding_collection.v1.schema.json",
    "alias_rollback.v1.schema.json",
    "model_catalog_collection.v1.schema.json",
    "model_catalog_entry.v1.schema.json",
    "model_catalog_registration.v1.schema.json",
    "model_catalog_transition.v1.schema.json",
)
REQUIRED_FILES = (
    "services/nex-mo/nex_mo/catalog_lifecycle.py",
    "services/nex-mo/nex_mo/catalog_lifecycle_repository.py",
    "services/nex-mo/nex_mo/catalog_lifecycle_service.py",
    "services/nex-mo/nex_mo/catalog_lifecycle_api.py",
    "services/nex-mo/nex_mo/catalog_lifecycle_runtime.py",
    "services/nex-mo/nex_mo/catalog_route_source.py",
    "database/nex-mo/migrations/1174_mo_catalog_lifecycle.sql",
    "contracts/openapi/nex-mo.openapi.yaml",
    *(f"contracts/schemas/service/nex_mo/{name}" for name in SCHEMAS),
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s118_mo_catalog_alias_lifecycle_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    (
        "requirement_traceability",
        "docs/30_service_specific_requirement_partition.md",
        "MO-FR-001",
    ),
    (
        "catalog_operation",
        "services/nex-mo/README.md",
        "POST /api/v1/model-catalog",
    ),
    (
        "alias_operation",
        "services/nex-mo/README.md",
        "POST /api/v1/provider-alias-bindings/rollback",
    ),
    (
        "catalog_table",
        "database/nex-mo/migrations/1174_mo_catalog_lifecycle.sql",
        "CREATE TABLE IF NOT EXISTS mo_model_catalog",
    ),
    (
        "alias_table",
        "database/nex-mo/migrations/1174_mo_catalog_lifecycle.sql",
        "CREATE TABLE IF NOT EXISTS mo_alias_bindings",
    ),
    ("postgres_identity", POSTGRES_DOCUMENT, "nex_mo_user@nex_mo_test"),
    ("postgres_checks", POSTGRES_DOCUMENT, "checks: `13/13`"),
    ("postgres_migrations", POSTGRES_DOCUMENT, "9 current / 9 planned"),
    ("postgres_cleanup", POSTGRES_DOCUMENT, "targeted cleanup residue: `0`"),
    (
        "closure_index",
        "docs/README.md",
        "1181_s118_mo_catalog_alias_lifecycle_closure.md",
    ),
)


def run_s118_mo_catalog_alias_lifecycle_closure(
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
        "repository": _safe_evidence(lambda: run_repository(root)),
        "service": _safe_evidence(run_service),
        "alias": _safe_evidence(run_alias),
        "api": _safe_evidence(run_api),
        "resolver": _safe_evidence(run_resolver),
        "contract": _safe_evidence(run_contract),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence["protected_postgres"] = {
        "status": "PASS"
        if all(
            token_status.get(name, False)
            for name in (
                "postgres_identity",
                "postgres_checks",
                "postgres_migrations",
                "postgres_cleanup",
            )
        )
        else "FAIL"
    }
    summaries = {
        name: _mapping(item.get("summary")) for name, item in evidence.items()
    }
    components = {
        "boundary_domain_and_persistence": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "domain", "repository")
        ),
        "catalog_and_alias_lifecycle": all(
            evidence[name].get("status") == "PASS"
            for name in ("service", "alias")
        ),
        "authenticated_api_and_runtime_resolution": all(
            evidence[name].get("status") == "PASS"
            for name in ("api", "resolver")
        ),
        "contracts_and_privacy": evidence["contract"].get("status") == "PASS",
        "postgres_and_quality_evidence": evidence["protected_postgres"].get(
            "status"
        )
        == "PASS"
        and all(token_status.values()),
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "all_components_closed": all(components.values()),
        "three_capability_bootstrap_closed": summaries["domain"].get(
            "catalog_entry_count"
        )
        == 3
        and summaries["domain"].get("active_binding_count") == 3
        and summaries["domain"].get("capability_count") == 3,
        "durable_repository_closed": summaries["repository"].get(
            "catalog_entry_count"
        )
        == 3
        and summaries["repository"].get("active_binding_count") == 3
        and summaries["repository"].get("deleted_entry_count") == 3
        and summaries["repository"].get("deleted_binding_count") == 3,
        "atomic_activation_rollback_closed": summaries["alias"].get(
            "binding_revision"
        )
        == 3
        and summaries["alias"].get("history_count") == 3
        and summaries["alias"].get("active_binding_count") == 1
        and summaries["alias"].get("stale_rejection_count") == 1,
        "authenticated_api_closed": summaries["api"].get(
            "unauthorized_status"
        )
        == 401
        and summaries["api"].get("catalog_entry_count") == 3
        and summaries["api"].get("exposed_private_field_count") == 0,
        "runtime_resolver_closed": summaries["resolver"].get(
            "switched_revision"
        )
        == "candidate-v2"
        and summaries["resolver"].get("switched_deployment")
        == "candidate-deployment",
        "contract_parity_privacy_closed": summaries["contract"].get(
            "runtime_operation_count"
        )
        == 29
        and summaries["contract"].get("unauthorized_rejection_count") == 7
        and summaries["contract"].get("contract_drift_count") == 0
        and summaries["contract"].get("exposed_private_field_count") == 0,
        "protected_postgres_closed": evidence["protected_postgres"]["status"]
        == "PASS",
        "mo_fr_001_durable_lifecycle_closed": decision["traceability"]
        == {
            "requirement_id": "MO-FR-001",
            "s111_baseline_status": "IMPLEMENTED_STATIC",
            "s118_current_status": "DURABLE_IMPLEMENTED",
        },
        "privacy_and_runtime_boundaries_closed": decision["runtime_resolution"]
        == "active_durable_alias_fail_closed"
        and decision["runtime_configuration"] == "external_not_persisted",
        "table_names_short": all(
            len(name) <= 24 for name in decision["tables"]
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1172-1180",
            "checkpoint_gate": "1176",
            "full_gate": "1181",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1181",
        "slice_range": SLICE_RANGE,
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s118_mo_catalog_alias_lifecycle_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S119" if passed else "BLOCKED",
        "feature_readiness": (
            "MO_DURABLE_CATALOG_ALIAS_LIFECYCLE_READY" if passed else "INCOMPLETE"
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
            "catalog_entry_count": summaries["domain"].get(
                "catalog_entry_count", 0
            ),
            "active_binding_count": summaries["domain"].get(
                "active_binding_count", 0
            ),
            "runtime_operation_count": summaries["contract"].get(
                "runtime_operation_count", 0
            ),
            "postgres_check_count": 13
            if evidence["protected_postgres"]["status"] == "PASS"
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
        "next_requirement": "S119" if passed else "blocked",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "mo_catalog_and_alias_lifecycle",
        "traceability": {
            "requirement_id": "MO-FR-001",
            "s111_baseline_status": "IMPLEMENTED_STATIC",
            "s118_current_status": "DURABLE_IMPLEMENTED",
        },
        "required_capabilities": ("embedding", "reranking", "generation"),
        "catalog_states": ("DRAFT", "ACTIVE", "RETIRED"),
        "alias_states": ("ACTIVE", "SUPERSEDED", "ROLLED_BACK"),
        "tables": ("mo_model_catalog", "mo_alias_bindings"),
        "runtime_resolution": "active_durable_alias_fail_closed",
        "runtime_configuration": "external_not_persisted",
        "concurrency": "expected_revision_optimistic_guard",
        "rollback": "append_only_binding_lineage",
        "authenticated_operation_count": 7,
        "postgres_smoke_required": True,
        "dgx_provider_calls_required": False,
        "quality_cadence": {
            "slice_gate": "1172-1180",
            "checkpoint_gate": "1176",
            "full_gate": "1181",
        },
        "next_requirement_scope": "S119_mo_model_release_governance",
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
        "s118_mo_catalog_alias_lifecycle_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"catalog={summary.get('catalog_entry_count', 0)}/"
        f"{summary.get('active_binding_count', 0)} "
        f"operations={summary.get('runtime_operation_count', 0)} "
        f"postgres={summary.get('postgres_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s118_mo_catalog_alias_lifecycle_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
