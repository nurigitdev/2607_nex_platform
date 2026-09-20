from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
CX_CONTRACT_API_DRIFT_AUDIT_SCHEMA_VERSION = "cx_contract_api_drift_audit.v1"
HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
CORE_GENERATION_SCHEMA_NAMES = frozenset(
    {
        "cx_generation_execution_record.v1.schema.json",
        "cx_structured_draft.v1.schema.json",
        "cx_remediation_execution_request.v1.schema.json",
        "cx_remediation_execution_result.v1.schema.json",
        "generation_progress_event.v1.schema.json",
        "generation_compatibility_rule.v1.schema.json",
        "generation_recovery_policy.v1.schema.json",
    }
)


def build_cx_contract_api_drift_audit(root: Path = ROOT) -> dict[str, Any]:
    issues = []
    cx_source_root = root / "services/nex-cx/nex_cx"
    openapi_path = root / "contracts/openapi/nex-cx.openapi.yaml"
    examples_index_path = root / "contracts/examples/index.json"
    negative_index_path = root / "contracts/tests/negative/index.json"
    validator_path = root / "scripts/quality/validate_contracts.py"

    runtime_operations = _runtime_operations(cx_source_root)
    openapi = _load_mapping(openapi_path)
    openapi_operations = _openapi_operations(openapi)
    openapi_version = str(_mapping(openapi.get("info")).get("version") or "")
    examples = _index_entries(examples_index_path, "examples")
    negative_examples = _index_entries(negative_index_path, "negative_examples")
    cx_schemas = sorted(
        (root / "contracts/schemas/service/nex_cx").glob("*.schema.json")
    )
    generation_schemas = sorted(
        path
        for path in (root / "contracts/schemas/generation").glob("*.schema.json")
        if path.name in CORE_GENERATION_SCHEMA_NAMES
    )

    if not runtime_operations:
        issues.append({"category": "runtime_operations_missing"})
    if not openapi_operations:
        issues.append({"category": "openapi_operations_missing"})
    if not cx_schemas:
        issues.append({"category": "cx_schemas_missing"})
    if not validator_path.is_file():
        issues.append({"category": "contract_validator_missing"})

    local_openapi_operations = {
        item for item in openapi_operations if item[1].startswith("/api/v1/")
    }
    missing_openapi_operations = sorted(
        runtime_operations - local_openapi_operations,
        key=lambda item: (item[1], item[0]),
    )
    shared_openapi_operations = sorted(
        local_openapi_operations - runtime_operations,
        key=lambda item: (item[1], item[0]),
    )
    positive_schema_refs = {str(item.get("schema") or "") for item in examples}
    negative_schema_refs = {
        str(item.get("schema") or "") for item in negative_examples
    }
    cx_schema_refs = {
        str(path.relative_to(root / "contracts")) for path in cx_schemas
    }
    generation_schema_refs = {
        str(path.relative_to(root / "contracts")) for path in generation_schemas
    }
    cx_positive_missing = sorted(cx_schema_refs - positive_schema_refs)
    cx_negative_missing = sorted(cx_schema_refs - negative_schema_refs)
    generation_positive_missing = sorted(
        generation_schema_refs - positive_schema_refs
    )
    generation_negative_missing = sorted(
        generation_schema_refs - negative_schema_refs
    )
    version_stale = "slice0003" in openapi_version.lower()
    drift_items = [
        {
            "category": "openapi_operation_missing",
            "method": method,
            "path": path,
        }
        for method, path in missing_openapi_operations
    ]
    drift_items.extend(
        {"category": "negative_fixture_missing", "schema": schema}
        for schema in cx_negative_missing
    )
    if version_stale:
        drift_items.append(
            {
                "category": "openapi_version_stale",
                "version": openapi_version,
            }
        )

    checks = {
        "audit_inputs_present": not issues,
        "runtime_operation_inventory_complete": len(runtime_operations) == 29,
        "cx_schema_inventory_complete": len(cx_schemas) == 11,
        "generation_schema_inventory_complete": len(generation_schemas) == 7,
        "positive_examples_complete": (
            not cx_positive_missing and not generation_positive_missing
        ),
        "generation_negative_examples_complete": not generation_negative_missing,
    }
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": CX_CONTRACT_API_DRIFT_AUDIT_SCHEMA_VERSION,
        "slice": "0908",
        "requirement": "S91",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "cx_contract_api_drift_audit_failed",
        "contract_readiness": "GAPS_CONFIRMED" if passed else "AUDIT_FAILED",
        "summary": {
            "runtime_operation_count": len(runtime_operations),
            "openapi_operation_count": len(openapi_operations),
            "runtime_openapi_covered_count": len(
                runtime_operations & local_openapi_operations
            ),
            "missing_openapi_operation_count": len(missing_openapi_operations),
            "shared_openapi_operation_count": len(shared_openapi_operations),
            "cx_schema_count": len(cx_schemas),
            "cx_positive_fixture_covered_count": len(
                cx_schema_refs & positive_schema_refs
            ),
            "cx_negative_fixture_covered_count": len(
                cx_schema_refs & negative_schema_refs
            ),
            "generation_schema_count": len(generation_schemas),
            "drift_count": len(drift_items),
            "audit_issue_count": len(issues),
        },
        "openapi_version": openapi_version,
        "missing_openapi_operations": [
            {"method": method, "path": path}
            for method, path in missing_openapi_operations
        ],
        "shared_openapi_operations": [
            {"method": method, "path": path}
            for method, path in shared_openapi_operations
        ],
        "missing_negative_fixtures": cx_negative_missing,
        "drift_items": drift_items,
        "checks": checks,
        "issues": issues,
        "target_hardening": {
            "requirement": "S92",
            "actions": [
                "document all four missing runtime operations in CX OpenAPI",
                "add a negative fixture for source ownership boundary decision",
                "replace the slice0003 OpenAPI version with a maintained API version",
                "add contract-index completeness checks to the validator",
            ],
        },
        "next_slice": "0909",
    }


def _runtime_operations(source_root: Path) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    if not source_root.is_dir():
        return operations
    for path in source_root.glob("*.py"):
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
            if isinstance(route_path, str) and route_path.startswith("/api/v1/"):
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
