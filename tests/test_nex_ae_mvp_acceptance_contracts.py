from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from nex_ae_api.mvp_acceptance_api import AE_MVP_ACCEPTANCE_OPERATIONS_PATH
from nex_ae_api.mvp_acceptance_evaluation import evaluate_ae_mvp_acceptance
from test_nex_ae_mvp_acceptance_evaluation import passing_evidence


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
SCHEMA_PATH = (
    CONTRACTS / "schemas/service/nex_ae_api/mvp_acceptance.v1.schema.json"
)
EXAMPLE_PATH = (
    CONTRACTS / "examples/operations/ae_mvp_acceptance.mock_success.json"
)
NEGATIVE_PATHS = (
    CONTRACTS
    / "tests/negative/operations/ae_mvp_acceptance.raw_evidence_leak.json",
    CONTRACTS
    / "tests/negative/operations/ae_mvp_acceptance.database_url_leak.json",
)
OPENAPI_PATH = CONTRACTS / "openapi/nex-ae-api.openapi.yaml"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_projection() -> dict:
    return {
        **evaluate_ae_mvp_acceptance(
            passing_evidence(),
            now=datetime(2026, 9, 29, 6, 0, tzinfo=UTC),
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
    route = contract["paths"][AE_MVP_ACCEPTANCE_OPERATIONS_PATH]
    operation = route["get"]
    schemas = contract["components"]["schemas"]

    assert contract["info"]["version"] == "1.7.0"
    assert set(route) == {"get"}
    assert operation["operationId"] == "getAeMvpAcceptanceOperationsProjection"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AeMvpAcceptanceOperationsProjection"
    }
    assert schemas["AeMvpAcceptanceOperationsProjection"]["additionalProperties"] is False
    assert schemas["AeMvpAcceptanceGateResult"]["additionalProperties"] is False
    assert schemas["AeMvpAcceptanceBlocker"]["additionalProperties"] is False
