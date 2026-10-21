from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
FROZEN = (
    ROOT
    / "docs/frozen/v2.1/10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS"
    / "NeX_Platform_v2.1_Controlled_Amendment_Batch04_CP04/APPROVAL_CP04"
)

PACK = (
    ("approval_work_item.v1.schema.json", "wc_approval_work_item.nsl_write.json", "wc_approval_work_item.nsl_missing_binding.json"),
    ("approval_decision.v1.schema.json", "wc_approval_decision.approved.json", "wc_approval_decision.raw_token.json"),
    ("human_gate_view.v1.schema.json", "wc_human_gate_view.business_formal.json", "wc_human_gate_view.domain_provider_mismatch.json"),
    ("approval_event.v1.schema.json", "wc_approval_event.nsl_approved.json", "wc_approval_event.domain_event_mismatch.json"),
)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("schema_name,example_name,_negative_name", PACK)
def test_s32_positive_transition_contracts_validate(
    schema_name, example_name, _negative_name
):
    schema = _json(CONTRACTS / "schemas/service/nex_wc" / schema_name)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        _json(CONTRACTS / "examples/service" / example_name)
    )


@pytest.mark.parametrize("schema_name,_example_name,negative_name", PACK)
def test_s32_negative_transition_contracts_fail_closed(
    schema_name, _example_name, negative_name
):
    schema = _json(CONTRACTS / "schemas/service/nex_wc" / schema_name)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            _json(CONTRACTS / "tests/negative/service" / negative_name)
        )


def test_s32_business_formal_is_additive_and_frozen_contracts_are_unchanged():
    frozen_work = _json(FROZEN / "approval-work-item-v1.schema.json")
    frozen_gate = _json(FROZEN / "human-gate-view-v2.1.schema.json")
    transition_work = _json(
        CONTRACTS / "schemas/service/nex_wc/approval_work_item.v1.schema.json"
    )
    transition_gate = _json(
        CONTRACTS / "schemas/service/nex_wc/human_gate_view.v1.schema.json"
    )

    assert frozen_work["properties"]["approval_domain"]["enum"] == [
        "AGENT_FORMAL",
        "NSL_WRITE",
    ]
    assert "BUSINESS_FORMAL" not in frozen_gate["properties"]["approval_domain"]["enum"]
    assert transition_work["properties"]["approval_domain"]["enum"] == [
        "AGENT_FORMAL",
        "NSL_WRITE",
        "BUSINESS_FORMAL",
    ]
    assert transition_gate["properties"]["approval_domain"]["enum"] == [
        "AGENT_FORMAL",
        "NSL_WRITE",
        "BUSINESS_FORMAL",
        "HUMAN_CONFIRMATION",
        "STEP_UP",
    ]


def test_s32_approval_aggregate_contract_does_not_absorb_delegation_runtime():
    schema = _json(
        CONTRACTS / "schemas/service/nex_wc/approval_work_item.v1.schema.json"
    )
    assert {
        "delegation_spec",
        "delegation_semantic_hash",
        "routing_decision_id",
        "assignment_id",
        "claim_id",
        "claim_generation",
        "lease_verifier",
    }.isdisjoint(schema["properties"])


def test_s32_contract_inventory_registers_the_four_transition_contracts():
    examples = _json(CONTRACTS / "examples/index.json")["examples"]
    negatives = _json(CONTRACTS / "tests/negative/index.json")["negative_examples"]
    wc_examples = [
        item for item in examples if item["schema"].startswith("schemas/service/nex_wc/")
    ]
    wc_negatives = [
        item for item in negatives if item["schema"].startswith("schemas/service/nex_wc/")
    ]
    assert len(wc_examples) == 7
    assert len(wc_negatives) == 7
