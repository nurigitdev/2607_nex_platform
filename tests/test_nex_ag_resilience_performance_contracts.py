from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from nex_ag.resilience_performance import (
    AgConcurrencyAdmissionGuard,
    AgSourceIsolationExecutor,
    build_ag_resilience_performance_policy,
)
from nex_ag.resilience_performance_operations import (
    AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH,
    build_ag_resilience_performance_operations_projection,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
SCHEMA_PATH = (
    CONTRACTS
    / "schemas/service/nex_ag/resilience_performance.v1.schema.json"
)
EXAMPLE_PATH = (
    CONTRACTS
    / "examples/operations/ag_resilience_performance_operations.mock_success.json"
)
NEGATIVE_PATH = (
    CONTRACTS
    / "tests/negative/operations/ag_resilience_performance_operations.database_url_leak.json"
)
AUDIT_SCHEMA_PATH = (
    CONTRACTS / "schemas/service/nex_ag/audit_evidence.v1.schema.json"
)
AUDIT_EXAMPLE_PATH = (
    CONTRACTS
    / "examples/operations/ag_audit_evidence_operations_projection.mock_success.json"
)
OPENAPI_PATH = CONTRACTS / "openapi/nex-ag.openapi.yaml"
MIGRATION_PATH = (
    ROOT
    / "database/nex-ag/migrations/0877_ag_resilience_read_indexes.sql"
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_resilience_contract_accepts_example_and_runtime_projection() -> None:
    schema = _json(SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    guard = AgConcurrencyAdmissionGuard(max_in_flight=8, wait_timeout_ms=100)
    executor = AgSourceIsolationExecutor(
        timeout_ms=2000,
        slow_operation_ms=1000,
        max_workers=2,
    )
    try:
        runtime = build_ag_resilience_performance_operations_projection(
            policy=build_ag_resilience_performance_policy({}),
            admission_snapshot=guard.snapshot(),
            source_snapshot=executor.snapshot(),
            request_trace_id="a" * 32,
        )
    finally:
        executor.close()

    Draft202012Validator.check_schema(schema)
    validator.validate(_json(EXAMPLE_PATH))
    validator.validate(runtime)


def test_resilience_contract_rejects_database_url_and_registers_fixtures() -> None:
    validator = Draft202012Validator(_json(SCHEMA_PATH))
    examples = {
        entry["path"] for entry in _json(CONTRACTS / "examples/index.json")["examples"]
    }
    negatives = {
        entry["path"]
        for entry in _json(CONTRACTS / "tests/negative/index.json")[
            "negative_examples"
        ]
    }

    assert list(validator.iter_errors(_json(NEGATIVE_PATH)))
    assert (
        "examples/operations/ag_resilience_performance_operations.mock_success.json"
        in examples
    )
    assert (
        "tests/negative/operations/"
        "ag_resilience_performance_operations.database_url_leak.json"
        in negatives
    )


def test_audit_pagination_is_required_and_frozen() -> None:
    schema = _json(AUDIT_SCHEMA_PATH)
    operations_schema = {
        "$ref": "#/$defs/operations_projection",
        "$defs": schema["$defs"],
    }
    fixture = _json(AUDIT_EXAMPLE_PATH)
    missing = dict(fixture)
    missing.pop("action_pagination")
    validator = Draft202012Validator(operations_schema)

    validator.validate(fixture)
    assert list(validator.iter_errors(missing))
    assert fixture["action_pagination"]["stable_ordering"] == [
        "created_at",
        "event_id",
    ]


def test_openapi_freezes_resilience_route_cursor_and_strict_response() -> None:
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    validate(contract)
    audit_get = contract["paths"]["/admin/v1/operations/audit-integrity"][
        "get"
    ]
    resilience_get = contract["paths"][
        AG_RESILIENCE_PERFORMANCE_OPERATIONS_PATH
    ]["get"]
    cursor = next(
        item for item in audit_get["parameters"] if item.get("name") == "cursor"
    )

    assert cursor["schema"]["maxLength"] == 1024
    assert resilience_get["operationId"] == (
        "getAgResiliencePerformanceOperationsProjection"
    )
    assert resilience_get["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {
        "$ref": "#/components/schemas/AgResiliencePerformanceOperationsProjection"
    }
    assert contract["components"]["schemas"][
        "AgResiliencePerformanceOperationsProjection"
    ]["additionalProperties"] is False
    assert "action_pagination" in contract["components"]["schemas"][
        "AgAuditEvidenceOperationsProjection"
    ]["required"]


def test_migration_adds_short_indexes_matching_deterministic_read_order() -> None:
    sql = " ".join(MIGRATION_PATH.read_text(encoding="utf-8").lower().split())
    index_names = [
        "idx_ag_evt_type_page",
        "idx_ag_evt_trace_page",
        "idx_ag_exp_trace_page",
    ]

    assert all(len(name) <= 30 for name in index_names)
    assert (
        "on service_operational_events (event_type, created_at desc, event_id desc)"
        in sql
    )
    assert (
        "on service_operational_events (trace_id, created_at desc, event_id desc)"
        in sql
    )
    assert (
        "on ag_ev_exports (trace_id, updated_at desc, export_id desc)" in sql
    )
    assert "0877_ag_resilience_read_indexes" in sql
