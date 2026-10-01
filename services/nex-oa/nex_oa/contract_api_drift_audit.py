from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Iterable

import yaml


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "oa_contract_api_drift_audit.v1"
HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
INVENTORY_BASELINE = {
    "runtime_operations": 34,
    "openapi_operations": 8,
    "oa_schemas": 4,
}


def build_oa_contract_api_drift_audit(root: Path = ROOT) -> dict[str, Any]:
    source_paths = (
        root / "services/nex-oa/nex_oa",
        root / "services/_shared/nex_runtime/app.py",
        root / "services/_shared/nex_runtime/job_control.py",
        root / "services/_shared/nex_runtime/service_logs.py",
    )
    openapi_path = root / "contracts/openapi/nex-oa.openapi.yaml"
    examples_index_path = root / "contracts/examples/index.json"
    negative_index_path = root / "contracts/tests/negative/index.json"
    validator_path = root / "scripts/quality/validate_contracts.py"
    issues = []

    runtime_operations = _runtime_operations(source_paths)
    openapi = _load_mapping(openapi_path)
    openapi_operations = _openapi_operations(openapi)
    openapi_version = str(_mapping(openapi.get("info")).get("version") or "")
    examples = _index_entries(examples_index_path, "examples")
    negative_examples = _index_entries(negative_index_path, "negative_examples")
    oa_schemas = sorted(
        (root / "contracts/schemas/service/nex_oa").glob("*.schema.json")
    )

    if not runtime_operations:
        issues.append({"category": "runtime_operations_missing"})
    if not openapi_operations:
        issues.append({"category": "openapi_operations_missing"})
    if not oa_schemas:
        issues.append({"category": "oa_schemas_missing"})
    if not validator_path.is_file():
        issues.append({"category": "contract_validator_missing"})

    missing_openapi_operations = sorted(
        runtime_operations - openapi_operations,
        key=lambda item: (item[1], item[0]),
    )
    undocumented_openapi_operations = sorted(
        openapi_operations - runtime_operations,
        key=lambda item: (item[1], item[0]),
    )
    positive_schema_refs = {str(item.get("schema") or "") for item in examples}
    negative_schema_refs = {
        str(item.get("schema") or "") for item in negative_examples
    }
    schema_refs = {
        str(path.relative_to(root / "contracts")) for path in oa_schemas
    }
    positive_missing = sorted(schema_refs - positive_schema_refs)
    negative_missing = sorted(schema_refs - negative_schema_refs)
    version_stale = "slice0003" in openapi_version.lower()

    drift_items = [
        {"category": "openapi_operation_missing", "method": method, "path": path}
        for method, path in missing_openapi_operations
    ]
    drift_items.extend(
        {
            "category": "openapi_operation_without_runtime_route",
            "method": method,
            "path": path,
        }
        for method, path in undocumented_openapi_operations
    )
    drift_items.extend(
        {"category": "positive_fixture_missing", "schema": schema}
        for schema in positive_missing
    )
    drift_items.extend(
        {"category": "negative_fixture_missing", "schema": schema}
        for schema in negative_missing
    )
    if version_stale:
        drift_items.append(
            {"category": "openapi_version_stale", "version": openapi_version}
        )

    classified_drift_count = (
        len(missing_openapi_operations)
        + len(undocumented_openapi_operations)
        + len(positive_missing)
        + len(negative_missing)
        + int(version_stale)
    )
    checks = {
        "audit_inputs_present": not issues,
        "runtime_operation_inventory_complete": len(runtime_operations)
        >= INVENTORY_BASELINE["runtime_operations"],
        "openapi_operation_inventory_complete": len(openapi_operations)
        >= INVENTORY_BASELINE["openapi_operations"],
        "oa_schema_inventory_complete": len(oa_schemas)
        >= INVENTORY_BASELINE["oa_schemas"],
        "drift_classified": len(drift_items) == classified_drift_count,
    }
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1207",
        "requirement": "S121",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_contract_api_drift_audit_failed",
        "contract_readiness": (
            "GAPS_CONFIRMED"
            if passed and drift_items
            else "HARDENED" if passed else "BLOCKED"
        ),
        "summary": {
            "runtime_operation_count": len(runtime_operations),
            "openapi_operation_count": len(openapi_operations),
            "runtime_openapi_covered_count": len(
                runtime_operations & openapi_operations
            ),
            "missing_openapi_operation_count": len(missing_openapi_operations),
            "undocumented_openapi_operation_count": len(
                undocumented_openapi_operations
            ),
            "schema_count": len(schema_refs),
            "positive_fixture_covered_count": len(
                schema_refs & positive_schema_refs
            ),
            "negative_fixture_covered_count": len(
                schema_refs & negative_schema_refs
            ),
            "drift_count": len(drift_items),
            "audit_issue_count": len(issues),
        },
        "openapi_version": openapi_version,
        "missing_openapi_operations": [
            {"method": method, "path": path}
            for method, path in missing_openapi_operations
        ],
        "undocumented_openapi_operations": [
            {"method": method, "path": path}
            for method, path in undocumented_openapi_operations
        ],
        "missing_positive_fixtures": positive_missing,
        "missing_negative_fixtures": negative_missing,
        "drift_items": drift_items,
        "checks": checks,
        "issues": issues,
        "hardening_handoff": {
            "target_requirement": "S122",
            "canonical_schema_required_per_wire_shape": True,
            "security_required_for_internal_routes": True,
            "runtime_openapi_parity_required": True,
            "update_openapi_before_new_routes": True,
        },
        "next_slice": "1208",
    }


def _runtime_operations(source_paths: Iterable[Path]) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for source_path in source_paths:
        paths = source_path.glob("*.py") if source_path.is_dir() else (source_path,)
        for path in paths:
            if not path.is_file():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if not isinstance(function, ast.Attribute):
                    continue
                if function.attr not in HTTP_METHODS or not node.args:
                    continue
                try:
                    route_path = ast.literal_eval(node.args[0])
                except (ValueError, TypeError):
                    continue
                if isinstance(route_path, str) and route_path.startswith("/"):
                    operations.add((function.attr.upper(), route_path))
    return operations


def _openapi_operations(payload: dict[str, Any]) -> set[tuple[str, str]]:
    operations = set()
    for path, path_item in _mapping(payload.get("paths")).items():
        if not isinstance(path, str):
            continue
        for method in _mapping(path_item):
            normalized = str(method).lower()
            if normalized in HTTP_METHODS:
                operations.add((normalized.upper(), path))
    return operations


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _index_entries(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    entries = payload.get(key, []) if isinstance(payload, dict) else []
    return [dict(item) for item in entries if isinstance(item, dict)]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
