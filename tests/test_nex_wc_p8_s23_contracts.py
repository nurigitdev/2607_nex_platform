from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
P7_CONTRACTS = ROOT / "docs/transition/P7/contracts"

POLICY_SCHEMA = CONTRACTS / "schemas/service/nex_wc/delegation_policy.v1.schema.json"
LINEAGE_SCHEMA = CONTRACTS / "schemas/service/nex_wc/delegation_lineage.v1.schema.json"
SPEC_SCHEMA = CONTRACTS / "schemas/service/nex_wc/delegation_spec.v1_1.schema.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "schema_path,example_path",
    (
        (POLICY_SCHEMA, CONTRACTS / "examples/service/wc_delegation_policy.initial.json"),
        (LINEAGE_SCHEMA, CONTRACTS / "examples/service/wc_delegation_lineage.nested.json"),
        (SPEC_SCHEMA, CONTRACTS / "examples/service/wc_delegation_spec.nested.json"),
    ),
)
def test_s23_positive_contract_examples_validate(schema_path, example_path):
    schema = _json(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        _json(example_path)
    )


@pytest.mark.parametrize(
    "schema_path,payload_path",
    (
        (POLICY_SCHEMA, CONTRACTS / "tests/negative/service/wc_delegation_policy.llm_override.json"),
        (LINEAGE_SCHEMA, CONTRACTS / "tests/negative/service/wc_delegation_lineage.missing_parent_claim.json"),
        (SPEC_SCHEMA, CONTRACTS / "tests/negative/service/wc_delegation_spec.partial_parent_claim.json"),
    ),
)
def test_s23_negative_contract_examples_are_rejected(schema_path, payload_path):
    with pytest.raises(ValidationError):
        Draft202012Validator(
            _json(schema_path), format_checker=FormatChecker()
        ).validate(_json(payload_path))


def test_s23_first_level_lineage_contract_requires_depth_one_and_no_parent_claim():
    payload = _json(CONTRACTS / "examples/service/wc_delegation_lineage.nested.json")
    payload.update(
        root_work_item_id=payload["work_item_id"],
        parent_work_item_id=None,
        parent_claim_ref=None,
        parent_claim_generation=None,
        delegation_depth=1,
    )
    validator = Draft202012Validator(
        _json(LINEAGE_SCHEMA), format_checker=FormatChecker()
    )
    validator.validate(payload)

    payload["delegation_depth"] = 2
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_s23_p7_delegation_contract_remains_unchanged_and_valid():
    schema = _json(P7_CONTRACTS / "p7-delegation-spec-v1.schema.json")
    example = _json(P7_CONTRACTS / "examples/p7-delegation-spec-v1.json")
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert "parent_work_item_id" not in schema["properties"]
    Draft202012Validator(schema).validate(example)


def test_s23_contract_inventory_registers_only_the_guard_pack():
    examples = _json(CONTRACTS / "examples/index.json")["examples"]
    negatives = _json(CONTRACTS / "tests/negative/index.json")["negative_examples"]
    guard_schemas = {
        "schemas/service/nex_wc/delegation_policy.v1.schema.json",
        "schemas/service/nex_wc/delegation_lineage.v1.schema.json",
        "schemas/service/nex_wc/delegation_spec.v1_1.schema.json",
    }
    assert {item["schema"] for item in examples} >= guard_schemas
    assert {item["schema"] for item in negatives} >= guard_schemas

    policy = _json(CONTRACTS / "examples/service/wc_delegation_policy.initial.json")
    assert policy == {
        "schema_version": "wc_delegation_policy.v1",
        "policy_ref": "wc.delegation.guard.initial-v1",
        "max_delegation_depth": 10,
        "max_children_per_work_item": 5,
        "max_descendants_per_root": 50,
        "cycle_detection": True,
        "governance_controlled": True,
        "llm_overridable": False,
    }
