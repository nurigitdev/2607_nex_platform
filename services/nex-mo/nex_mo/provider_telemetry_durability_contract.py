from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[3]
REQUIRED_IDENTITY_COLUMNS = frozenset(
    {
        "telemetry_key",
        "capability",
        "request_shape",
        "deployment_id",
        "model_revision",
    }
)
REQUIRED_COUNTER_COLUMNS = frozenset(
    {
        "request_count",
        "success_count",
        "failure_count",
        "retryable_failure_count",
        "degraded_count",
        "attempt_count",
        "retry_count",
    }
)
FORBIDDEN_PERSISTENCE_COLUMNS = frozenset(
    {
        "provider_endpoint",
        "provider_api_key",
        "api_key",
        "authorization_header",
        "request_payload",
        "response_payload",
        "exception_detail",
        "database_url",
    }
)


def build_mo_provider_telemetry_durability_contract(
    root: Path = ROOT,
) -> dict[str, Any]:
    schema = _read_json(
        root
        / "contracts/schemas/service/nex_mo/provider_telemetry_snapshot.v1.schema.json"
    )
    fixture = _read_json(
        root / "contracts/examples/provider/mo_provider_telemetry_snapshot.mock.json"
    )
    openapi = _read_yaml(root / "contracts/openapi/nex-mo.openapi.yaml")
    migration = _read(
        root / "database/nex-mo/migrations/1154_mo_provider_telemetry.sql"
    )
    repository = _read(
        root / "services/nex-mo/nex_mo/provider_telemetry_repository.py"
    )
    runtime = _read(
        root / "services/nex-mo/nex_mo/provider_telemetry_runtime.py"
    )
    providers = _read(root / "services/nex-mo/nex_mo/providers.py")
    readme = _read(root / "services/nex-mo/README.md")

    canonical_item = _mapping(
        _mapping(_mapping(schema.get("properties")).get("data")).get("items")
    )
    canonical_fields = set(_mapping(canonical_item.get("properties")))
    canonical_required = set(_string_list(canonical_item.get("required")))
    components = _mapping(_mapping(openapi.get("components")).get("schemas"))
    openapi_item = _mapping(components.get("ProviderTelemetryItem"))
    openapi_fields = set(_mapping(openapi_item.get("properties")))
    openapi_required = set(_string_list(openapi_item.get("required")))
    telemetry_operation = _mapping(
        _mapping(_mapping(openapi.get("paths")).get("/api/v1/provider-telemetry")).get(
            "get"
        )
    )
    responses = _mapping(telemetry_operation.get("responses"))
    success_description = str(_mapping(responses.get("200")).get("description") or "")
    table_columns = _table_columns(migration, "mo_provider_telemetry")
    fixture_valid = bool(schema) and not list(
        Draft202012Validator(schema).iter_errors(fixture)
    )
    checks = {
        "canonical_fixture_valid": fixture_valid,
        "wire_contract_has_26_fields": len(canonical_fields) == 26
        and canonical_required == canonical_fields,
        "openapi_fields_match_canonical": openapi_fields == canonical_fields
        and openapi_required == canonical_required,
        "openapi_documents_restart_safe_aggregate": (
            "restart-safe" in success_description
            and "process-local" not in success_description
        ),
        "openapi_documents_safe_503": "503" in responses,
        "migration_registered": (
            "1154_mo_provider_telemetry" in migration
            and "INSERT INTO schema_migrations" in migration
        ),
        "identity_columns_complete": REQUIRED_IDENTITY_COLUMNS.issubset(
            table_columns
        ),
        "counter_columns_complete": REQUIRED_COUNTER_COLUMNS.issubset(
            table_columns
        ),
        "private_columns_absent": not (
            table_columns & FORBIDDEN_PERSISTENCE_COLUMNS
        ),
        "atomic_monotonic_upsert_present": all(
            token in repository
            for token in (
                "ON CONFLICT (telemetry_key) DO UPDATE SET",
                "request_count = mo_provider_telemetry.request_count",
                "excluded.last_observed_at >= mo_provider_telemetry.last_observed_at",
                "excluded.last_retry_at >= mo_provider_telemetry.last_retry_at",
            )
        ),
        "persistence_modes_are_explicit": (
            'mode == "memory"' in runtime and 'mode != "postgres"' in runtime
        ),
        "repository_failure_is_redacted": (
            "MO_PROVIDER_TELEMETRY_UNAVAILABLE" in providers
            and "private database" not in providers
        ),
        "operations_runbook_is_current": (
            "restart-safe atomic aggregates" in readme
            and "mo_provider_telemetry" in readme
        ),
    }
    issues = [check for check, passed in checks.items() if not passed]
    passed = not issues
    return {
        "audit_schema_version": "mo_provider_telemetry_durability_contract.v1",
        "slice": "1159",
        "requirement": "S116",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo_provider_telemetry_durability_contract_failed"
        ),
        "checks": checks,
        "summary": {
            "wire_field_count": len(canonical_fields),
            "openapi_field_count": len(openapi_fields),
            "table_column_count": len(table_columns),
            "identity_column_count": len(
                table_columns & REQUIRED_IDENTITY_COLUMNS
            ),
            "counter_column_count": len(table_columns & REQUIRED_COUNTER_COLUMNS),
            "forbidden_column_count": len(
                table_columns & FORBIDDEN_PERSISTENCE_COLUMNS
            ),
            "failed_check_count": len(issues),
        },
        "issues": issues,
        "guardrails": [
            "preserve the provider telemetry snapshot v1 wire contract",
            "keep counters atomic and last-observation timestamps monotonic",
            "never persist provider endpoints credentials payloads or exceptions",
            "keep memory mode deterministic and postgres mode restart-safe",
            "return a privacy-safe 503 when durable telemetry is unavailable",
        ],
        "next_slice": "1160" if passed else None,
    }


def _table_columns(sql: str, table_name: str) -> set[str]:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table_name)}\s*\((.*?)\n\);",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if match is None:
        return set()
    columns = set()
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper().startswith(("CONSTRAINT ", "CHECK ")):
            continue
        name = stripped.split(maxsplit=1)[0].rstrip(",")
        if re.fullmatch(r"[a-z][a-z0-9_]*", name):
            columns.add(name)
    return columns


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    return list(value) if isinstance(value, list) and all(
        isinstance(item, str) for item in value
    ) else []


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read(path))
        return dict(value) if isinstance(value, Mapping) else {}
    except json.JSONDecodeError:
        return {}


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(_read(path))
        return dict(value) if isinstance(value, Mapping) else {}
    except yaml.YAMLError:
        return {}
