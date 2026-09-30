from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[3]
RETRY_FIELDS = frozenset(
    {
        "attempt_count",
        "retry_count",
        "last_retry_at",
        "last_retry_delay_ms",
        "last_retry_failure_kind",
    }
)
FORBIDDEN_KEYS = frozenset(
    {
        "provider_endpoint",
        "provider_api_key",
        "api_key",
        "authorization_header",
        "request_payload",
        "response_payload",
        "exception_detail",
    }
)


def build_mo_provider_resilience_contract(
    root: Path = ROOT,
    *,
    telemetry_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    schema = _read_json(
        root
        / "contracts/schemas/service/nex_mo/provider_telemetry_snapshot.v1.schema.json"
    )
    fixture = _read_json(
        root / "contracts/examples/provider/mo_provider_telemetry_snapshot.mock.json"
    )
    openapi = _read_yaml(root / "contracts/openapi/nex-mo.openapi.yaml")
    payload = dict(telemetry_payload) if telemetry_payload is not None else fixture

    canonical_item = _mapping(
        _mapping(_mapping(schema.get("properties")).get("data")).get("items")
    )
    canonical_properties = set(_mapping(canonical_item.get("properties")))
    canonical_required = set(_string_list(canonical_item.get("required")))
    components = _mapping(_mapping(openapi.get("components")).get("schemas"))
    openapi_item = _mapping(components.get("ProviderTelemetryItem"))
    openapi_properties = set(_mapping(openapi_item.get("properties")))
    openapi_required = set(_string_list(openapi_item.get("required")))
    snapshot = _mapping(components.get("ProviderTelemetrySnapshot"))
    data_items = _mapping(
        _mapping(_mapping(snapshot.get("properties")).get("data")).get("items")
    )
    payload_items = _mapping_list(payload.get("data"))
    payload_keys = _all_keys(payload)
    checks = {
        "canonical_schema_present": bool(schema),
        "openapi_document_present": bool(openapi),
        "telemetry_item_reference_explicit": data_items.get("$ref")
        == "#/components/schemas/ProviderTelemetryItem",
        "openapi_properties_match_canonical": openapi_properties
        == canonical_properties,
        "openapi_required_fields_match_canonical": openapi_required
        == canonical_required,
        "retry_fields_explicit": RETRY_FIELDS.issubset(openapi_properties)
        and RETRY_FIELDS.issubset(openapi_required),
        "runtime_payload_contract_valid": _schema_accepts(schema, payload),
        "runtime_retry_fields_complete": bool(payload_items)
        and all(RETRY_FIELDS.issubset(item) for item in payload_items),
        "private_runtime_keys_absent": not (payload_keys & FORBIDDEN_KEYS),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_resilience_contract.v1",
        "slice": "1150",
        "requirement": "S115",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_resilience_contract_failed",
        "checks": checks,
        "summary": {
            "canonical_property_count": len(canonical_properties),
            "openapi_property_count": len(openapi_properties),
            "retry_field_count": len(RETRY_FIELDS),
            "runtime_item_count": len(payload_items),
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "guardrails": [
            "keep the existing authenticated telemetry operation",
            "document every canonical retry field explicitly",
            "never expose endpoints credentials payloads or exception details",
            "keep aggregate telemetry process-local until S116",
        ],
        "next_slice": "1151" if passed else "blocked",
    }


def _schema_accepts(schema: Mapping[str, Any], payload: Any) -> bool:
    return bool(schema) and not list(
        Draft202012Validator(dict(schema)).iter_errors(payload)
    )


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {
            key for item in value.values() for key in _all_keys(item)
        }
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value] if isinstance(value, list) and all(
        isinstance(item, Mapping) for item in value
    ) else []


def _string_list(value: Any) -> list[str]:
    return list(value) if isinstance(value, list) and all(
        isinstance(item, str) for item in value
    ) else []


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return dict(payload) if isinstance(payload, Mapping) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return dict(payload) if isinstance(payload, Mapping) else {}
    except (OSError, yaml.YAMLError):
        return {}
