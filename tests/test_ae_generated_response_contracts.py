from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

from nex_ae_api.generated_response_api import build_generated_response_owner_view
from test_nex_ae_generated_response_lineage import sample_bundle, sample_record


ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_generated_response_schemas_accept_examples_and_runtime_values() -> None:
    lineage_schema = _json(
        "contracts/schemas/service/nex_ae_api/"
        "generated_response_lineage.v1.schema.json"
    )
    response_schema = _json(
        "contracts/schemas/service/nex_ae_api/generated_response.v1.schema.json"
    )
    lineage_validator = Draft202012Validator(lineage_schema)
    response_validator = Draft202012Validator(response_schema)

    lineage_validator.validate(
        _json(
            "contracts/examples/generation/"
            "ae_generated_response_lineage.retry_repaired.json"
        )
    )
    response_validator.validate(
        _json("contracts/examples/generation/ae_generated_response.owner.json")
    )

    bundle = sample_bundle(retry=True, repaired=True)
    lineage_validator.validate(bundle["lineage"])
    owner_view = build_generated_response_owner_view(
        sample_record(retry=True),
        bundle["lineage"],
        bundle["storage_payload"]["content"],
    )
    response_validator.validate(owner_view)


@pytest.mark.parametrize(
    ("schema_path", "fixture_path"),
    [
        (
            "contracts/schemas/service/nex_ae_api/"
            "generated_response_lineage.v1.schema.json",
            "contracts/tests/negative/generation/"
            "ae_generated_response_lineage.raw_content_leak.json",
        ),
        (
            "contracts/schemas/service/nex_ae_api/generated_response.v1.schema.json",
            "contracts/tests/negative/generation/"
            "ae_generated_response.storage_ref_leak.json",
        ),
    ],
)
def test_generated_response_contracts_reject_private_metadata_leaks(
    schema_path: str,
    fixture_path: str,
) -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(_json(schema_path)).validate(_json(fixture_path))


def test_chat_contract_accepts_public_generated_response_lineage_only() -> None:
    schema = _json(
        "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json"
    )
    record = sample_record(retry=True)
    record["generation"]["async_generation"] = {
        "async_generation_schema_version": "ae_async_generation.v1",
        "execution_strategy": "ASYNCHRONOUS",
        "lifecycle_status": "COMPLETED",
        "admission_status": "ENQUEUED",
        "job_id": "cx-job-001",
        "cx_generation_id": record["cx_generation_id"],
        "cx_job_status": "SUCCEEDED",
        "attempt_count": 1,
        "max_attempts": 3,
        "retryable": False,
        "handoff_status": "READY",
        "next_action": "PRESENT_GENERATION_TO_OWNER",
        "error": None,
        "links": {
            "generation": "/api/v1/generations/cx-generation-001",
            "async_job": "/api/v1/generation-jobs/cx-job-001",
        },
        "owner_scope_enforced": True,
        "content_included": False,
    }
    record["generation"]["generated_response"] = sample_bundle(
        retry=True, repaired=True
    )["lineage"]
    record["retrieval"] = {
        "cx_retrieval_package_id": "retrieval-001",
        "cx_package_hash": "b" * 64,
        "cx_status": "READY",
        "evidence_count": 1,
        "best_score": 0.95,
        "confidence_bucket": "HIGH",
        "no_answer_reason": None,
        "warnings": [],
        "quality_warnings": {
            "contract_schema_version": "ae_chat_retrieval_quality_warning.v1",
            "warning_count": 0,
            "warning_kinds": [],
            "quality_flag_count": 0,
            "quality_flag_kinds": [],
            "low_confidence_threshold": 0.5,
            "best_score_below_threshold": False,
            "status_caveat_required": False,
            "recommended_action": "proceed",
            "raw_warning_details_included": False,
        },
    }

    Draft202012Validator(schema).validate(record)

    leaked = deepcopy(record)
    leaked["generation"]["generated_response"]["content"] = "private response"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(leaked)


def test_generated_response_contract_rejects_private_grounding_evidence() -> None:
    schema = _json(
        "contracts/schemas/service/nex_ae_api/"
        "generated_response_lineage.v1.schema.json"
    )
    lineage = sample_bundle()["lineage"]
    lineage["cx_grounding_lineage"]["private_evidence_included"] = True

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(lineage)


def test_openapi_exposes_owner_response_and_metadata_only_lineage() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    schemas = spec["components"]["schemas"]
    operation = spec["paths"][
        "/api/v1/chat/interactions/{interaction_id}/response"
    ]["get"]

    assert spec["info"]["version"] == "1.7.0"
    assert operation["operationId"] == "getAeGeneratedResponse"
    assert (
        operation["responses"]["200"]["content"]["application/json"]["schema"]
        ["$ref"]
        == "#/components/schemas/AeGeneratedResponse"
    )
    assert schemas["AeGeneratedResponseLineage"][
        "x-nex-canonical-json-schema"
    ].endswith("generated_response_lineage.v1.schema.json")
    lineage_properties = schemas["AeGeneratedResponseLineage"]["properties"]
    assert "content" not in lineage_properties
    assert "storage_ref" not in lineage_properties
    assert lineage_properties["cx_grounding_lineage"]["oneOf"][1]["$ref"] == (
        "#/components/schemas/CxGroundedGenerationLineage"
    )
    assert schemas["CxGroundedGenerationLineage"][
        "x-nex-canonical-json-schema"
    ].endswith("cx_grounded_generation_lineage.v1.schema.json")
    assert schemas["AeChatInteraction"]["properties"]["generation"]["anyOf"][0][
        "properties"
    ]["generated_response"]["$ref"] == (
        "#/components/schemas/AeGeneratedResponseLineage"
    )
