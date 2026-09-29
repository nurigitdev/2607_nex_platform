from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

from nex_ae_api.async_generation import build_async_generation_projection


ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _projection() -> dict:
    return build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": {
                "job_id": "job-runtime-contract",
                "cx_generation_id": "cx-runtime-contract",
                "status": "QUEUED",
                "attempt_count": 0,
                "max_attempts": 3,
                "retryable": True,
                "links": {
                    "generation": "/api/v1/generations/cx-runtime-contract",
                    "async_job": "/api/v1/generation-jobs/job-runtime-contract",
                },
                "error": None,
            },
        }
    )


def test_async_projection_schema_accepts_fixture_and_runtime_projection() -> None:
    schema = _json(
        "contracts/schemas/service/nex_ae_api/async_generation.v1.schema.json"
    )
    validator = Draft202012Validator(schema)

    validator.validate(
        _json("contracts/examples/generation/ae_async_generation.queued.json")
    )
    validator.validate(_projection())


def test_chat_schema_accepts_async_runtime_projection_and_nullable_failure() -> None:
    schema = _json(
        "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json"
    )
    record = _json(
        "contracts/examples/generation/ae_chat_interaction.async_pending.json"
    )
    record["generation"]["async_generation"] = _projection()
    record["cx_generation_id"] = "cx-runtime-contract"
    record["failure"] = None

    Draft202012Validator(schema).validate(record)


def test_async_contracts_reject_inconsistent_state_and_private_fields() -> None:
    projection_schema = _json(
        "contracts/schemas/service/nex_ae_api/async_generation.v1.schema.json"
    )
    inconsistent = deepcopy(_projection())
    inconsistent.update(
        lifecycle_status="COMPLETED",
        handoff_status="READY",
        next_action="PRESENT_GENERATION_TO_OWNER",
    )
    with pytest.raises(ValidationError):
        Draft202012Validator(projection_schema).validate(inconsistent)

    for schema_path, fixture_path in (
        (
            "contracts/schemas/service/nex_ae_api/async_generation.v1.schema.json",
            "contracts/tests/negative/generation/"
            "ae_async_generation.content_leak.json",
        ),
        (
            "contracts/schemas/service/nex_ae_api/chat_interaction.v1.schema.json",
            "contracts/tests/negative/generation/"
            "ae_chat_interaction.async_provider_leak.json",
        ),
    ):
        with pytest.raises(ValidationError):
            Draft202012Validator(_json(schema_path)).validate(_json(fixture_path))


def test_refresh_contract_requires_ready_content_to_be_persisted_by_ae() -> None:
    schema = _json(
        "contracts/schemas/service/nex_ae_api/async_chat_refresh.v1.schema.json"
    )
    validator = Draft202012Validator(schema)

    validator.validate(
        _json("contracts/examples/generation/ae_async_chat_refresh.ready.json")
    )
    with pytest.raises(ValidationError):
        validator.validate(
            _json(
                "contracts/tests/negative/generation/"
                "ae_async_chat_refresh.persisted_content.json"
            )
        )


def test_openapi_exposes_async_chat_lifecycle_contracts() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    paths = spec["paths"]
    schemas = spec["components"]["schemas"]

    assert spec["info"]["version"] == "1.7.0"
    assert "202" in paths["/api/v1/chat/interactions"]["post"]["responses"]
    assert {
        "/api/v1/chat/interactions/{interaction_id}/refresh",
        "/api/v1/chat/interactions/{interaction_id}/cancel",
        "/api/v1/chat/interactions/{interaction_id}/retry",
    }.issubset(paths)
    assert schemas["AeAsyncGeneration"]["x-nex-canonical-json-schema"].endswith(
        "async_generation.v1.schema.json"
    )
    assert schemas["AeAsyncChatRefresh"]["x-nex-canonical-json-schema"].endswith(
        "async_chat_refresh.v1.schema.json"
    )
    assert schemas["AeAsyncChatRefresh"]["properties"][
        "content_persisted_by_ae"
    ]["type"] == "boolean"
    assert (
        paths["/api/v1/chat/interactions/{interaction_id}/response"]["get"]
        ["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/AeGeneratedResponse"
    )
    assert schemas["AeGeneratedResponse"]["x-nex-canonical-json-schema"].endswith(
        "generated_response.v1.schema.json"
    )
