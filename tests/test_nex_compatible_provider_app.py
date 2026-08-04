from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, ValidationError

from nex_compatible_provider.app import (
    CompatibleProviderSettings,
    build_health_payload,
    create_app,
)


CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts"


def load_schema(relative_path: str) -> dict[str, object]:
    return json.loads((CONTRACT_ROOT / relative_path).read_text(encoding="utf-8"))


def validate_contract(schema_path: str, payload: dict[str, object]) -> None:
    Draft202012Validator(load_schema(schema_path)).validate(payload)


def test_embedding_health_matches_contract_and_hides_runtime_paths() -> None:
    settings = CompatibleProviderSettings.from_env(
        {
            "NEX_COMPAT_PROVIDER_CAPABILITY": "embedding",
            "NEX_COMPAT_PROVIDER_BACKEND": "mock",
            "NEX_COMPAT_PROVIDER_MODEL_ROOT": "/home/nexpcx/2608_nex_platform/models",
            "NEX_COMPAT_EMBEDDING_DIMENSIONS": "6",
        }
    )
    response = TestClient(create_app(settings)).get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    validate_contract(
        "schemas/service/nex_mo/compatible_provider_health.v1.schema.json",
        payload,
    )
    serialized = json.dumps(payload)
    assert "/home/nexpcx" not in serialized
    assert "2608_nex_platform" not in serialized
    assert payload["runtime_metadata"] == {
        "backend": "mock",
        "request_shape": "openai_embeddings",
        "embedding_dimensions": 6,
    }


def test_reranker_health_uses_current_qwen_0_6b_default() -> None:
    settings = CompatibleProviderSettings.from_env(
        {"NEX_COMPAT_PROVIDER_CAPABILITY": "reranking"}
    )
    payload = build_health_payload(settings)

    validate_contract(
        "schemas/service/nex_mo/compatible_provider_health.v1.schema.json",
        payload,
    )
    assert payload["model_name"] == "Qwen3-Reranker-0.6B"
    assert payload["provider_model_id"] == "Qwen/Qwen3-Reranker-0.6B"
    assert payload["runtime_metadata"] == {
        "backend": "mock",
        "request_shape": "nex_rerank_v1",
    }


def test_embedding_endpoint_accepts_openai_shape_and_dimensions() -> None:
    client = TestClient(
        create_app(CompatibleProviderSettings(embedding_dimensions=5))
    )
    response = client.post(
        "/v1/embeddings",
        json={
            "model": "Qwen3-embedding-4B",
            "input": ["alpha document", "beta document"],
            "encoding_format": "float",
            "dimensions": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    validate_contract(
        "schemas/service/nex_mo/compatible_embedding_response.v1.schema.json",
        payload,
    )
    assert payload["model"] == "Qwen3-embedding-4B"
    assert [item["index"] for item in payload["data"]] == [0, 1]
    assert all(len(item["embedding"]) == 3 for item in payload["data"])
    assert payload["usage"] == {"prompt_tokens": 4, "total_tokens": 4}


def test_embedding_endpoint_accepts_single_string_with_default_dimensions() -> None:
    settings = CompatibleProviderSettings(embedding_dimensions=4)
    client = TestClient(create_app(settings))
    first = client.post(
        "/v1/embeddings",
        json={"model": "Qwen3-embedding-4B", "input": "same text"},
    )
    second = client.post(
        "/v1/embeddings",
        json={"model": "Qwen3-embedding-4B", "input": "same text"},
    )

    assert first.status_code == 200
    assert len(first.json()["data"][0]["embedding"]) == 4
    assert first.json()["data"][0]["embedding"] == second.json()["data"][0]["embedding"]


def test_embedding_endpoint_rejects_private_or_wrong_model_requests() -> None:
    client = TestClient(create_app(CompatibleProviderSettings()))

    private_field = client.post(
        "/v1/embeddings",
        json={
            "model": "Qwen3-embedding-4B",
            "input": ["alpha"],
            "model_path": "/home/nexpcx/models/qwen3",
        },
    )
    wrong_model = client.post(
        "/v1/embeddings",
        json={"model": "OtherEmbedding", "input": ["alpha"]},
    )

    assert private_field.status_code == 422
    assert wrong_model.status_code == 404
    assert wrong_model.json()["detail"]["error_code"] == "provider.model_not_available"


def test_rerank_endpoint_sorts_caps_and_optionally_returns_documents() -> None:
    settings = CompatibleProviderSettings(provider_capability="reranking")
    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/rerank",
        json={
            "model": "Qwen3-Reranker-0.6B",
            "query": "alpha beta",
            "documents": ["alpha beta document", "unrelated", "alpha only"],
            "top_n": 2,
            "return_documents": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    validate_contract(
        "schemas/service/nex_mo/compatible_rerank_response.v1.schema.json",
        payload,
    )
    assert [result["index"] for result in payload["results"]] == [0, 2]
    assert payload["results"][0]["document"] == "alpha beta document"
    assert payload["usage"]["prompt_tokens"] == 8


def test_rerank_endpoint_omits_documents_by_default_and_caps_to_available_docs() -> None:
    settings = CompatibleProviderSettings(provider_capability="reranking")
    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/rerank",
        json={
            "model": "Qwen3-Reranker-0.6B",
            "query": "alpha",
            "documents": ["beta", "alpha"],
            "top_n": 10,
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    assert results[0]["index"] == 1
    assert "document" not in results[0]


def test_provider_process_rejects_disabled_capability_endpoint() -> None:
    embedding_client = TestClient(create_app(CompatibleProviderSettings()))
    reranker_client = TestClient(
        create_app(CompatibleProviderSettings(provider_capability="reranking"))
    )

    assert embedding_client.post(
        "/v1/rerank",
        json={
            "model": "Qwen3-Reranker-0.6B",
            "query": "alpha",
            "documents": ["alpha"],
        },
    ).status_code == 404
    assert reranker_client.post(
        "/v1/embeddings",
        json={"model": "Qwen3-embedding-4B", "input": ["alpha"]},
    ).status_code == 404


def test_bf16_required_health_flags_fp32_loaded_parameters() -> None:
    settings = CompatibleProviderSettings.from_env(
        {
            "NEX_COMPAT_PROVIDER_BACKEND": "torch_local",
            "NEX_COMPAT_PRECISION_POLICY": "bf16_required",
            "NEX_COMPAT_REQUESTED_TORCH_DTYPE": "bfloat16",
            "NEX_COMPAT_LOADED_PARAMETER_DTYPE": "float32",
        }
    )
    response = TestClient(create_app(settings)).get("/healthz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "DEGRADED"
    assert payload["dtype_match"] is False
    with pytest.raises(ValidationError):
        validate_contract(
            "schemas/service/nex_mo/compatible_provider_health.v1.schema.json",
            payload,
        )


def test_invalid_environment_values_fall_back_to_mock_defaults() -> None:
    settings = CompatibleProviderSettings.from_env(
        {
            "NEX_COMPAT_PROVIDER_CAPABILITY": "unknown",
            "NEX_COMPAT_EMBEDDING_DIMENSIONS": "-1",
            "NEX_COMPAT_PRECISION_POLICY": "unknown",
            "NEX_COMPAT_REQUESTED_TORCH_DTYPE": "bad",
            "NEX_COMPAT_LOADED_PARAMETER_DTYPE": "bad",
        }
    )

    assert settings.provider_capability == "embedding"
    assert settings.embedding_dimensions == 8
    assert settings.precision_policy == "mock_no_model"
    assert settings.requested_torch_dtype == "mock"
    assert settings.loaded_parameter_dtype == "mock"
