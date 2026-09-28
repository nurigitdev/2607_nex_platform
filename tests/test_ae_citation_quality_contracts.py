from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

from nex_ae_api.citation_quality_workflow import build_citation_quality_workflow


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    "contracts/schemas/service/nex_ae_api/"
    "citation_quality_workflow.v1.schema.json"
)
EXAMPLES = (
    "validated",
    "repaired",
    "attention_required",
)
NEGATIVE_EXAMPLES = (
    "raw_output_leak",
    "inconsistent_action",
    "owner_scope_disabled",
)


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_citation_quality_schema_accepts_registered_examples() -> None:
    validator = Draft202012Validator(_json(SCHEMA_PATH))

    for name in EXAMPLES:
        validator.validate(
            _json(
                "contracts/examples/generation/"
                f"ae_citation_quality_workflow.{name}.json"
            )
        )


@pytest.mark.parametrize("name", NEGATIVE_EXAMPLES)
def test_citation_quality_schema_rejects_negative_examples(name: str) -> None:
    validator = Draft202012Validator(_json(SCHEMA_PATH))

    with pytest.raises(ValidationError):
        validator.validate(
            _json(
                "contracts/tests/negative/generation/"
                f"ae_citation_quality_workflow.{name}.json"
            )
        )


def test_runtime_citation_workflow_matches_canonical_schema() -> None:
    workflow = build_citation_quality_workflow(
        {
            "cx_generation_id": "generation-runtime-contract",
            "request_metadata": {
                "grounding_required": True,
                "draft_validation_status": "VALIDATED",
                "grounded_response_quality_status": "PASS",
                "grounded_response_quality_issue_count": 0,
                "citation_repair": {
                    "repair_schema_version": "cx_citation_repair.v1",
                    "attempted": True,
                    "attempt_count": 1,
                    "max_attempts": 1,
                    "trigger_error_code": "cx.citation_required_missing",
                    "same_retrieval_package": True,
                    "original_provider_prompt_package_hash": "a" * 64,
                    "effective_provider_prompt_package_hash": "b" * 64,
                    "invalid_output_included": False,
                },
            },
        },
        interaction_id="interaction-runtime-contract",
    )

    Draft202012Validator(_json(SCHEMA_PATH)).validate(workflow)


def test_chat_interaction_schema_accepts_durable_citation_workflow() -> None:
    schema = _json(
        "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json"
    )
    record = _json(
        "contracts/examples/generation/ae_chat_interaction.async_pending.json"
    )
    workflow = _json(
        "contracts/examples/generation/"
        "ae_citation_quality_workflow.repaired.json"
    )
    workflow["interaction_id"] = record["interaction_id"]
    workflow["cx_generation_id"] = record["cx_generation_id"]
    record["generation"]["citation_workflow"] = workflow

    Draft202012Validator(schema).validate(record)
    leaking = deepcopy(record)
    leaking["generation"]["citation_workflow"]["quality"]["raw_output"] = (
        "private response"
    )
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(leaking)


def test_openapi_exposes_owner_scoped_citation_quality_contract() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    path = spec["paths"][
        "/api/v1/chat/interactions/{interaction_id}/citation-quality"
    ]["get"]
    schema = spec["components"]["schemas"]["AeCitationQualityWorkflow"]

    assert spec["info"]["version"] == "1.5.0"
    assert path["operationId"] == "getAeChatInteractionCitationQuality"
    assert path["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ] == "#/components/schemas/AeCitationQualityWorkflow"
    assert schema["x-nex-canonical-json-schema"].endswith(
        "citation_quality_workflow.v1.schema.json"
    )
    assert schema["properties"]["content_included"]["const"] is False
    assert schema["properties"]["owner_scope_enforced"]["const"] is True
