from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from nex_ag.mvp_acceptance_api import AG_MVP_ACCEPTANCE_OPERATIONS_PATH
from nex_ag.mvp_acceptance_evaluation import evaluate_ag_mvp_acceptance


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
SCHEMA_PATH = CONTRACTS / "schemas/service/nex_ag/mvp_acceptance.v1.schema.json"
EXAMPLE_PATH = (
    CONTRACTS / "examples/operations/ag_mvp_acceptance.mock_success.json"
)
NEGATIVE_PATHS = (
    CONTRACTS
    / "tests/negative/operations/ag_mvp_acceptance.raw_evidence_leak.json",
    CONTRACTS
    / "tests/negative/operations/ag_mvp_acceptance.database_url_leak.json",
)
OPENAPI_PATH = CONTRACTS / "openapi/nex-ag.openapi.yaml"
OBSERVED_AT = "2026-09-20T03:00:00Z"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_projection() -> dict:
    common = {"status": "PASS", "observed_at": OBSERVED_AT}
    evidence = {
        "ag_requirement_closures": {
            **common,
            "requirement_count": 33,
            "issue_count": 0,
        },
        "contract_validation": {
            **common,
            "schema_count": 82,
            "openapi_count": 7,
            "negative_fixture_count": 97,
        },
        "unit_regression": {
            **common,
            "passed_tests": 6216,
            "failed_tests": 0,
        },
        "statement_coverage": {**common, "percent": 98.84},
        "branch_coverage": {**common, "percent": 96.43},
        "postgres_smoke": {
            **common,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "zero_residue": True,
        },
        "privacy_failure_runbooks": {**common, "runbook_count": 27},
        "cx_transition_handoff": {
            **common,
            "target_service": "nex-cx",
            "manifest_status": "SEALED",
        },
    }
    return {
        **evaluate_ag_mvp_acceptance(
            evidence,
            now=datetime(2026, 9, 20, 3, 0, tzinfo=UTC),
        ),
        "request_trace_id": "b" * 32,
        "evidence_source_status": "COLLECTED",
        "server_selected": True,
    }


def test_schema_accepts_example_and_runtime_projection() -> None:
    schema = _json(SCHEMA_PATH)
    validator = Draft202012Validator(schema)

    Draft202012Validator.check_schema(schema)
    validator.validate(_json(EXAMPLE_PATH))
    validator.validate(_runtime_projection())


def test_schema_rejects_privacy_leaks_and_registers_fixtures() -> None:
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

    for path in NEGATIVE_PATHS:
        errors = list(validator.iter_errors(_json(path)))
        assert len(errors) == 1
        assert errors[0].validator == "additionalProperties"
        assert path.relative_to(CONTRACTS).as_posix() in negatives
    assert EXAMPLE_PATH.relative_to(CONTRACTS).as_posix() in examples


def test_openapi_freezes_protected_read_only_route_and_strict_projection() -> None:
    contract = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    validate(contract)
    route = contract["paths"][AG_MVP_ACCEPTANCE_OPERATIONS_PATH]
    operation = route["get"]
    schemas = contract["components"]["schemas"]

    assert set(route) == {"get"}
    assert operation["operationId"] == "getAgMvpAcceptanceOperationsProjection"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgMvpAcceptanceOperationsProjection"
    }
    assert schemas["AgMvpAcceptanceOperationsProjection"]["additionalProperties"] is False
    assert schemas["AgMvpAcceptanceGateResult"]["additionalProperties"] is False
    assert schemas["AgMvpAcceptanceBlocker"]["additionalProperties"] is False
