from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_RELATIVE = (
    "contracts/schemas/service/nex_mo/runtime_observability.v1.schema.json"
)
EXAMPLE_RELATIVE = (
    "contracts/examples/provider/mo_runtime_observability.mock_healthy.json"
)
NEGATIVE_RELATIVE = (
    "contracts/tests/negative/provider/mo_runtime_observability.ssh_target_leak.json"
)
FORBIDDEN_PUBLIC_FIELDS = {
    "ssh_target",
    "provider_endpoint",
    "provider_api_key",
    "process_id",
    "process_command_line",
    "model_path",
    "gpu_uuid",
}


def build_runtime_observability_contract_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    schema = _read_json(root / SCHEMA_RELATIVE)
    example = _read_json(root / EXAMPLE_RELATIVE)
    negative = _read_json(root / NEGATIVE_RELATIVE)
    openapi = _read_yaml(root / "contracts/openapi/nex-mo.openapi.yaml")
    main_source = _read_text(root / "services/nex-mo/nex_mo/main.py")
    readme = _read_text(root / "services/nex-mo/README.md")
    migrations = "\n".join(
        _read_text(path)
        for path in (root / "database/nex-mo/migrations").glob("*.sql")
    )

    validator = Draft202012Validator(schema) if schema else None
    positive_errors = list(validator.iter_errors(example)) if validator else [None]
    negative_errors = list(validator.iter_errors(negative)) if validator else []
    paths = _mapping(openapi.get("paths"))
    operation = _mapping(
        _mapping(paths.get("/api/v1/model-runtime-observability")).get("get")
    )
    response = _mapping(_mapping(operation.get("responses")).get("200"))
    content = _mapping(response.get("content"))
    response_schema = _mapping(_mapping(content.get("application/json")).get("schema"))
    components = _mapping(_mapping(openapi.get("components")).get("schemas"))
    component = _mapping(components.get("RuntimeObservability"))
    serialized_example = json.dumps(example, sort_keys=True)

    checks = {
        "canonical_schema_present": bool(schema),
        "positive_fixture_valid": not positive_errors,
        "negative_privacy_fixture_rejected": bool(negative_errors),
        "openapi_operation_authenticated": operation.get("security")
        == [{"serviceBearer": []}],
        "openapi_response_uses_canonical_component": response_schema.get("$ref")
        == "#/components/schemas/RuntimeObservability"
        and component.get("x-nex-canonical-json-schema")
        == "schemas/service/nex_mo/runtime_observability.v1.schema.json",
        "main_app_route_registered": "register_runtime_observability_routes"
        in main_source,
        "positive_fixture_private_fields_omitted": not any(
            field in serialized_example for field in FORBIDDEN_PUBLIC_FIELDS
        ),
        "operations_documented": (
            "GET /api/v1/model-runtime-observability" in readme
            and "process-local TTL" in readme
        ),
        "no_runtime_observability_table": "runtime_observability" not in migrations,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_observability_contract.v1",
        "slice": "1169",
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo_runtime_observability_contract_failed"
        ),
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "forbidden_field_count": len(FORBIDDEN_PUBLIC_FIELDS),
            "positive_error_count": len(positive_errors),
            "negative_error_count": len(negative_errors),
        },
        "next_slice": "1170" if passed else None,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
