from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts"


def load_json(relative_path: str) -> object:
    return json.loads((CONTRACT_ROOT / relative_path).read_text(encoding="utf-8"))


def test_compatible_provider_contracts_accept_canonical_examples() -> None:
    examples = [
        (
            "schemas/service/nex_mo/compatible_embedding_request.v1.schema.json",
            "examples/provider/mo_compatible_embedding_request.openai_qwen3.json",
        ),
        (
            "schemas/service/nex_mo/compatible_embedding_response.v1.schema.json",
            "examples/provider/mo_compatible_embedding_response.openai_qwen3.json",
        ),
        (
            "schemas/service/nex_mo/compatible_rerank_request.v1.schema.json",
            "examples/provider/mo_compatible_rerank_request.qwen3.json",
        ),
        (
            "schemas/service/nex_mo/compatible_rerank_response.v1.schema.json",
            "examples/provider/mo_compatible_rerank_response.qwen3.json",
        ),
        (
            "schemas/service/nex_mo/compatible_provider_health.v1.schema.json",
            "examples/provider/mo_compatible_provider_health.embedding_bf16.json",
        ),
    ]

    for schema_path, example_path in examples:
        Draft202012Validator(load_json(schema_path)).validate(load_json(example_path))


def test_bf16_required_health_rejects_fp32_loaded_parameters() -> None:
    schema = load_json("schemas/service/nex_mo/compatible_provider_health.v1.schema.json")
    payload = load_json(
        "tests/negative/provider/mo_compatible_provider_health.fp32_loaded_for_bf16.json"
    )

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_embedding_request_contract_rejects_provider_private_fields() -> None:
    schema = load_json("schemas/service/nex_mo/compatible_embedding_request.v1.schema.json")
    payload = load_json(
        "tests/negative/provider/mo_compatible_embedding_request.raw_model_path.json"
    )

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)
