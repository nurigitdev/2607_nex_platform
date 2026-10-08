from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


@pytest.mark.parametrize(
    ("schema_path", "example_path", "negative_path"),
    [
        (
            "schemas/service/nex_mo/model_rollout.v1.schema.json",
            "examples/provider/mo_model_rollout.validating.json",
            "tests/negative/provider/mo_model_rollout.endpoint_leak.json",
        ),
        (
            "schemas/service/nex_mo/model_rollout_event.v1.schema.json",
            "examples/provider/mo_model_rollout_event.validation_started.json",
            "tests/negative/provider/mo_model_rollout_event.raw_payload.json",
        ),
    ],
)
def test_rollout_contract_accepts_canonical_and_rejects_private_fields(
    schema_path: str,
    example_path: str,
    negative_path: str,
) -> None:
    schema = json.loads((CONTRACTS / schema_path).read_text(encoding="utf-8"))
    example = json.loads((CONTRACTS / example_path).read_text(encoding="utf-8"))
    negative = json.loads((CONTRACTS / negative_path).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    validator.validate(example)
    with pytest.raises(ValidationError):
        validator.validate(negative)


def test_rollout_contracts_are_linked_from_openapi() -> None:
    openapi = yaml.safe_load(
        (CONTRACTS / "openapi/nex-mo.openapi.yaml").read_text(encoding="utf-8")
    )
    schemas = openapi["components"]["schemas"]

    assert schemas["ModelRollout"]["x-nex-canonical-json-schema"] == (
        "schemas/service/nex_mo/model_rollout.v1.schema.json"
    )
    assert schemas["ModelRolloutEvent"]["x-nex-canonical-json-schema"] == (
        "schemas/service/nex_mo/model_rollout_event.v1.schema.json"
    )


def test_rollout_contract_fixtures_are_indexed_once() -> None:
    positive = json.loads(
        (CONTRACTS / "examples/index.json").read_text(encoding="utf-8")
    )["examples"]
    negative = json.loads(
        (CONTRACTS / "tests/negative/index.json").read_text(encoding="utf-8")
    )["negative_examples"]
    expected_positive = {
        "examples/provider/mo_model_rollout.validating.json",
        "examples/provider/mo_model_rollout_event.validation_started.json",
    }
    expected_negative = {
        "tests/negative/provider/mo_model_rollout.endpoint_leak.json",
        "tests/negative/provider/mo_model_rollout_event.raw_payload.json",
    }

    assert {
        item["path"] for item in positive if item["path"] in expected_positive
    } == expected_positive
    assert {
        item["path"] for item in negative if item["path"] in expected_negative
    } == expected_negative
    assert sum(item["path"] in expected_positive for item in positive) == 2
    assert sum(item["path"] in expected_negative for item in negative) == 2
