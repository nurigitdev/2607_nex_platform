from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from nex_ag.audit_retention import (
    InMemoryAgRetentionCandidateStore,
    build_ag_audit_retention_policy,
)
from nex_ag.audit_retention_archive import InMemoryAgArchiveReceiptStore
from nex_ag.audit_retention_operations import (
    AG_AUDIT_RETENTION_OPERATIONS_PATH,
    AG_AUDIT_RETENTION_PURGE_PATH,
    build_ag_audit_retention_operations_projection,
)
from nex_ag.audit_retention_purge import (
    InMemoryAgRetentionPurgeStore,
    execute_ag_retention_purge,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
SCHEMA_PATH = CONTRACTS / "schemas/service/nex_ag/audit_retention.v1.schema.json"
OPERATIONS_EXAMPLE = (
    CONTRACTS
    / "examples/operations/ag_audit_retention_operations.mock_success.json"
)
PURGE_EXAMPLE = (
    CONTRACTS / "examples/operations/ag_audit_retention_purge.mock_success.json"
)
NEGATIVE_OPERATIONS = (
    CONTRACTS
    / "tests/negative/operations/ag_audit_retention_operations.object_ref_leak.json"
)
NEGATIVE_PURGE = (
    CONTRACTS
    / "tests/negative/operations/ag_audit_retention_purge.confirmation_leak.json"
)
OPENAPI_PATH = CONTRACTS / "openapi/nex-ag.openapi.yaml"
MIGRATION_PATH = (
    ROOT / "database/nex-ag/migrations/0887_ag_retention_candidate_indexes.sql"
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_retention_contract_accepts_examples_and_runtime_projections() -> None:
    schema = _json(SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    policy = build_ag_audit_retention_policy({})
    receipt_store = InMemoryAgArchiveReceiptStore()
    operations = build_ag_audit_retention_operations_projection(
        policy=policy,
        candidate_store=InMemoryAgRetentionCandidateStore(),
        receipt_store=receipt_store,
        as_of="2026-09-20T12:00:00Z",
    )
    purge = execute_ag_retention_purge(
        store=InMemoryAgRetentionPurgeStore(receipt_store=receipt_store),
        policy=policy,
        source_kind="operational_event",
        source_id="missing-event",
        as_of="2026-09-20T12:00:00Z",
    )

    Draft202012Validator.check_schema(schema)
    validator.validate(_json(OPERATIONS_EXAMPLE))
    validator.validate(_json(PURGE_EXAMPLE))
    validator.validate(operations)
    validator.validate(purge)


def test_retention_contract_rejects_privacy_leaks_and_registers_fixtures() -> None:
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

    assert list(validator.iter_errors(_json(NEGATIVE_OPERATIONS)))
    assert list(validator.iter_errors(_json(NEGATIVE_PURGE)))
    assert OPERATIONS_EXAMPLE.relative_to(CONTRACTS).as_posix() in examples
    assert PURGE_EXAMPLE.relative_to(CONTRACTS).as_posix() in examples
    assert NEGATIVE_OPERATIONS.relative_to(CONTRACTS).as_posix() in negatives
    assert NEGATIVE_PURGE.relative_to(CONTRACTS).as_posix() in negatives


def test_openapi_freezes_retention_routes_and_strict_components() -> None:
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    validate(contract)
    operations = contract["paths"][AG_AUDIT_RETENTION_OPERATIONS_PATH]["get"]
    purge = contract["paths"][AG_AUDIT_RETENTION_PURGE_PATH]["post"]
    schemas = contract["components"]["schemas"]

    assert operations["operationId"] == "getAgAuditRetentionOperationsProjection"
    assert purge["operationId"] == "executeAgAuditRetentionPurge"
    assert operations["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AgAuditRetentionOperationsProjection"}
    assert purge["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgAuditRetentionPurgeRequest"
    }
    assert schemas["AgAuditRetentionOperationsProjection"][
        "additionalProperties"
    ] is False
    assert schemas["AgAuditRetentionPurgeRequest"]["additionalProperties"] is False
    assert schemas["AgAuditRetentionPurgeExecution"]["additionalProperties"] is False


def test_migration_adds_short_indexes_matching_candidate_read_order() -> None:
    sql = " ".join(MIGRATION_PATH.read_text(encoding="utf-8").lower().split())
    index_names = ["idx_ag_evt_retention_time", "idx_ag_exp_retention_time"]

    assert all(len(name) <= 30 for name in index_names)
    assert (
        "on service_operational_events (created_at asc, event_id asc)" in sql
    )
    assert "on ag_ev_exports (updated_at asc, export_id asc)" in sql
    assert "0887_ag_retention_candidate_indexes" in sql
