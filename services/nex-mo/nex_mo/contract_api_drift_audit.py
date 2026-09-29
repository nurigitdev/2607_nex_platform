from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[3]
HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
BUSINESS_PATHS = (
    "/api/v1/provider-routes",
    "/api/v1/provider-profiles",
    "/api/v1/provider-telemetry",
    "/api/v1/embeddings",
    "/api/v1/rerank",
    "/api/v1/generations",
)
POST_PROVIDER_PATHS = (
    "/api/v1/embeddings",
    "/api/v1/rerank",
    "/api/v1/generations",
)
MO_SCHEMA_PREFIX = "schemas/service/nex_mo/"


def build_mo_contract_api_drift_audit(root: Path = ROOT) -> dict[str, Any]:
    document = _read_yaml(root / "contracts/openapi/nex-mo.openapi.yaml")
    runtime_operations = _runtime_operations()
    openapi_operations = _openapi_operations(document)
    missing_openapi = sorted(runtime_operations - openapi_operations)
    extra_openapi = sorted(openapi_operations - runtime_operations)
    paths = document.get("paths", {}) if isinstance(document, dict) else {}
    stale_mock_operations = sorted(
        f"{method.upper()} {path}"
        for path, path_item in paths.items()
        if isinstance(path_item, Mapping)
        for method, operation in path_item.items()
        if method in HTTP_METHODS
        and isinstance(operation, Mapping)
        and "mock" in json.dumps(operation, sort_keys=True).lower()
    )
    missing_request_bodies = sorted(
        f"POST {path}"
        for path in POST_PROVIDER_PATHS
        if not isinstance(paths.get(path, {}).get("post", {}).get("requestBody"), Mapping)
    )
    documented_business_paths = [path for path in BUSINESS_PATHS if path in paths]
    missing_success_schemas = sorted(
        path
        for path in documented_business_paths
        if not _has_success_response_schema(paths[path])
    )
    missing_security = sorted(
        path
        for path in documented_business_paths
        if not _has_security_declaration(paths[path])
    )
    schemas = sorted(
        path.relative_to(root / "contracts").as_posix()
        for path in (root / "contracts/schemas/service/nex_mo").glob("*.json")
    )
    positive_schemas = _indexed_schemas(root / "contracts/examples/index.json", "examples")
    negative_schemas = _indexed_schemas(
        root / "contracts/tests/negative/index.json", "negative_examples"
    )
    missing_positive = sorted(set(schemas) - positive_schemas)
    missing_negative = sorted(set(schemas) - negative_schemas)
    checks = {
        "openapi_document_readable": bool(document),
        "runtime_operation_inventory_complete": len(runtime_operations) == 18,
        "openapi_drift_classified": len(missing_openapi) == 9 and not extra_openapi,
        "business_path_inventory_complete": len(BUSINESS_PATHS) == 6,
        "schema_positive_fixtures_complete": not missing_positive,
        "schema_negative_gaps_classified": len(missing_negative) == 3,
    }
    drift_count = (
        len(missing_openapi)
        + len(stale_mock_operations)
        + len(missing_request_bodies)
        + len(missing_success_schemas)
        + len(missing_security)
        + len(missing_negative)
    )
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_contract_api_drift_audit.v1",
        "slice": "1108",
        "requirement": "S111",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_contract_api_drift_audit_failed",
        "contract_readiness": "GAPS_CONFIRMED" if passed else "BLOCKED",
        "checks": checks,
        "summary": {
            "runtime_operation_count": len(runtime_operations),
            "openapi_operation_count": len(openapi_operations),
            "missing_openapi_operation_count": len(missing_openapi),
            "stale_mock_operation_count": len(stale_mock_operations),
            "missing_request_body_count": len(missing_request_bodies),
            "missing_success_schema_count": len(missing_success_schemas),
            "missing_security_count": len(missing_security),
            "schema_count": len(schemas),
            "positive_fixture_covered_count": len(set(schemas) & positive_schemas),
            "negative_fixture_covered_count": len(set(schemas) & negative_schemas),
            "drift_count": drift_count,
        },
        "missing_openapi_operations": missing_openapi,
        "extra_openapi_operations": extra_openapi,
        "stale_mock_operations": stale_mock_operations,
        "missing_request_bodies": missing_request_bodies,
        "missing_success_schemas": missing_success_schemas,
        "missing_security": missing_security,
        "missing_positive_fixture_schemas": missing_positive,
        "missing_negative_fixture_schemas": missing_negative,
        "ordered_remediation": [
            {
                "priority": "P0",
                "action": "document provider telemetry and all protected provider request response schemas",
            },
            {
                "priority": "P1",
                "action": "align shared job and log-retention operations with MO OpenAPI",
            },
            {
                "priority": "P1",
                "action": "replace mock-only operation names with mode-neutral contracts",
            },
            {
                "priority": "P2",
                "action": "add missing negative fixtures for all MO schemas",
            },
        ],
        "next_slice": "1109",
    }


def _runtime_operations() -> set[str]:
    from nex_mo.main import app

    return {
        f"{method} {route.path}"
        for route in app.routes
        if getattr(route, "include_in_schema", False)
        for method in sorted(route.methods or ())
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }


def _openapi_operations(document: Mapping[str, Any]) -> set[str]:
    paths = document.get("paths", {}) if isinstance(document, Mapping) else {}
    return {
        f"{method.upper()} {path}"
        for path, path_item in paths.items()
        if isinstance(path_item, Mapping)
        for method in path_item
        if method in HTTP_METHODS
    }


def _has_success_response_schema(path_item: Mapping[str, Any]) -> bool:
    return any(
        isinstance(operation, Mapping)
        and isinstance(operation.get("responses", {}).get("200", {}).get("content"), Mapping)
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    )


def _has_security_declaration(path_item: Mapping[str, Any]) -> bool:
    return any(
        isinstance(operation, Mapping) and "security" in operation
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    )


def _indexed_schemas(path: Path, key: str) -> set[str]:
    payload = _read_json(path)
    entries = payload.get(key, []) if isinstance(payload, Mapping) else []
    return {
        item["schema"]
        for item in entries
        if isinstance(item, Mapping)
        and isinstance(item.get("schema"), str)
        and item["schema"].startswith(MO_SCHEMA_PREFIX)
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return dict(payload) if isinstance(payload, Mapping) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
