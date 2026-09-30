#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.contract_api_drift_audit import (  # noqa: E402
    _runtime_operations,
    build_mo_contract_api_drift_audit,
)


HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
PUBLIC_OPERATIONS = frozenset({"GET /", "GET /health", "GET /ready", "GET /version"})
CANONICAL_SCHEMA_PREFIX = "schemas/service/nex_mo/"


def run_mo_runtime_openapi_parity_guard(
    root: Path = ROOT,
    *,
    document: Mapping[str, Any] | None = None,
    runtime_operations: set[str] | None = None,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(document) if document is not None else _read_openapi(root)
    runtime = runtime_operations if runtime_operations is not None else _runtime_operations()
    drift = dict(audit) if audit is not None else build_mo_contract_api_drift_audit(root)
    operations = _operation_map(payload)
    openapi = set(operations)
    operation_ids = [
        operation.get("operationId")
        for operation in operations.values()
        if isinstance(operation.get("operationId"), str)
        and operation["operationId"].strip()
    ]
    protected = openapi - PUBLIC_OPERATIONS
    secured = {
        key
        for key in protected
        if operations[key].get("security") == [{"serviceBearer": []}]
    }
    schemas = _mapping(_mapping(payload.get("components")).get("schemas"))
    canonical_components = {
        name: marker
        for name, component in schemas.items()
        if isinstance(name, str)
        and isinstance(component, Mapping)
        and isinstance(
            marker := component.get("x-nex-canonical-json-schema"), str
        )
        and marker.startswith(CANONICAL_SCHEMA_PREFIX)
        and (root / "contracts" / marker).is_file()
    }
    root_operation = operations.get("GET /", {})
    root_response = _mapping(_mapping(root_operation.get("responses")).get("200"))
    root_content = _mapping(root_response.get("content"))
    root_schema = _mapping(_mapping(root_content.get("application/json")).get("schema"))
    summary = _mapping(drift.get("summary"))
    schema_count = _count(summary, "schema_count")
    checks = {
        "openapi_document_present": bool(payload),
        "audit_passed": drift.get("status") == "PASS",
        "contract_readiness_hardened": drift.get("contract_readiness") == "HARDENED",
        "runtime_inventory_complete": len(runtime) == 20,
        "openapi_inventory_complete": len(openapi) == 20,
        "runtime_openapi_operations_equal": runtime == openapi,
        "operation_ids_complete": len(operation_ids) == len(openapi),
        "operation_ids_unique": len(operation_ids) == len(set(operation_ids)),
        "protected_operations_secured": protected == secured,
        "root_response_schema_bound": root_schema.get("$ref")
        == "#/components/schemas/ServiceRoot",
        "canonical_provider_components_complete": len(canonical_components) == 11,
        "positive_fixtures_complete": (
            schema_count > 0
            and _count(summary, "positive_fixture_covered_count") == schema_count
        ),
        "negative_fixtures_complete": (
            schema_count > 0
            and _count(summary, "negative_fixture_covered_count") == schema_count
        ),
        "zero_contract_drift": _count(summary, "drift_count") == 0,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_runtime_openapi_parity_guard.v1",
        "slice": "1138",
        "requirement": "S114",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_openapi_parity_failed",
        "checks": checks,
        "summary": {
            "runtime_operation_count": len(runtime),
            "openapi_operation_count": len(openapi),
            "operation_id_count": len(operation_ids),
            "protected_operation_count": len(protected),
            "secured_operation_count": len(secured),
            "canonical_component_count": len(canonical_components),
            "drift_count": _count(summary, "drift_count"),
        },
        "missing_openapi_operations": sorted(runtime - openapi),
        "extra_openapi_operations": sorted(openapi - runtime),
        "duplicate_operation_ids": sorted(
            {item for item in operation_ids if operation_ids.count(item) > 1}
        ),
        "unsecured_operations": sorted(protected - secured),
        "canonical_components": canonical_components,
        "next_slice": "1139" if passed else "blocked",
    }


def _read_openapi(root: Path) -> dict[str, Any]:
    path = root / "contracts" / "openapi" / "nex-mo.openapi.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _operation_map(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    paths = _mapping(document.get("paths"))
    return {
        f"{method.upper()} {path}": dict(operation)
        for path, path_item in paths.items()
        if isinstance(path, str) and isinstance(path_item, Mapping)
        for method, operation in path_item.items()
        if method in HTTP_METHODS and isinstance(operation, Mapping)
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _count(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key, 0)
    return item if isinstance(item, int) and item >= 0 else 0


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "mo_runtime_openapi_parity_guard="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"operations={summary.get('openapi_operation_count', 0)}/"
        f"{summary.get('runtime_operation_count', 0)} "
        f"secured={summary.get('secured_operation_count', 0)}/"
        f"{summary.get('protected_operation_count', 0)} "
        f"canonical={summary.get('canonical_component_count', 0)} "
        f"drift={summary.get('drift_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_openapi_parity_guard()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
