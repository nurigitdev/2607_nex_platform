from __future__ import annotations

import httpx
import pytest

from nex_mo.remote_provider import (
    RemoteProviderPreflightConfig,
    build_remote_provider_preflight_configs,
    expected_models_from_env,
    run_remote_provider_preflight_check,
    selected_generation_model_names,
    validate_preflight_response,
)


def test_remote_provider_configs_use_current_env_contract() -> None:
    configs = build_remote_provider_preflight_configs(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
            "NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000",
            "NEX_MO_VLLM_API_KEY": "secret",
            "NEX_MO_LIVE_TIMEOUT_SECONDS": "8.5",
        }
    )

    assert [config.endpoint_env for config in configs] == [
        "NEX_MO_REMOTE_EMBEDDING_URL",
        "NEX_MO_REMOTE_RERANKER_URL",
        "NEX_MO_VLLM_MODELS_URL",
    ]
    assert [config.method for config in configs] == ["POST", "POST", "GET"]
    assert [config.request_shape for config in configs] == [
        "openai_embeddings",
        "rerank",
        "openai_models",
    ]
    assert configs[2].url == "http://dgx.local:12000/v1/models"
    assert configs[2].headers()["Authorization"] == "Bearer secret"
    assert configs[2].timeout_seconds == 8.5
    assert "secret" not in str(configs[2].to_safe_summary())


def test_remote_provider_configs_keep_legacy_live_endpoint_fallbacks() -> None:
    configs = build_remote_provider_preflight_configs(
        {
            "NEX_MO_LIVE_EMBEDDING_HEALTH_URL": "http://legacy.local/embed",
            "NEX_MO_LIVE_RERANKER_HEALTH_URL": "http://legacy.local/rerank",
            "NEX_MO_LIVE_VLLM_MODELS_URL": "http://legacy.local/models",
        }
    )

    assert [config.url for config in configs] == [
        "http://legacy.local/embed",
        "http://legacy.local/rerank",
        "http://legacy.local/models",
    ]
    assert configs[0].to_safe_summary()["legacy_endpoint_env"] == (
        "NEX_MO_LIVE_EMBEDDING_HEALTH_URL"
    )


def test_selected_generation_model_default_follows_profile_catalog() -> None:
    assert selected_generation_model_names({}) == ("Qwen3.5-122B-A10B-NVFP4",)
    assert selected_generation_model_names(
        {
            "NEX_MO_GENERATION_PROFILE": "qwen3_6_27b_nvfp4",
        }
    ) == ("Qwen3.6-27B-NVFP4",)
    assert selected_generation_model_names(
        {
            "NEX_MO_GENERATION_PROFILE": "custom_model",
            "NEX_MO_GENERATION_MODEL_NAME": "Custom Model",
        }
    ) == ("Custom Model",)


def test_run_remote_provider_preflight_check_posts_embedding_shape() -> None:
    calls: list[dict[str, object]] = []
    config = RemoteProviderPreflightConfig(
        capability="embedding",
        endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
        url="http://dgx.local:9103/v1/embeddings",
        method="POST",
        request_shape="openai_embeddings",
        expected_models=("EmbedA",),
        api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
        api_key="embed-secret",
        timeout_seconds=3,
    )

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    result = run_remote_provider_preflight_check(config, requester=requester)

    assert result["status"] == "PASS"
    assert result["validated_shape"] == "openai_embeddings"
    assert calls == [
        {
            "method": "POST",
            "url": "http://dgx.local:9103/v1/embeddings",
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer embed-secret",
            },
            "timeout": 3,
            "json": {"model": "EmbedA", "input": ["nex live provider preflight"]},
        }
    ]
    assert "embed-secret" not in str(result)


def test_run_remote_provider_preflight_check_validates_rerank_data_alias() -> None:
    config = RemoteProviderPreflightConfig(
        capability="reranking",
        endpoint_env="NEX_MO_REMOTE_RERANKER_URL",
        url="http://dgx.local:9104/v1/rerank",
        method="POST",
        request_shape="rerank",
        expected_models=("RerankA",),
    )

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert kwargs["json"] == {
            "model": "RerankA",
            "query": "nex live provider preflight",
            "documents": ["NeX live provider preflight document."],
            "top_n": 1,
        }
        return httpx.Response(200, json={"data": [{"relevance_score": 0.7}]})

    result = run_remote_provider_preflight_check(config, requester=requester)

    assert result["status"] == "PASS"
    assert result["validated_shape"] == "rerank"
    assert result["authorization_configured"] is False


def test_run_remote_provider_preflight_check_validates_vllm_model_list() -> None:
    config = RemoteProviderPreflightConfig(
        capability="generation",
        endpoint_env="NEX_MO_VLLM_MODELS_URL",
        url="http://dgx.local:12000/v1/models",
        method="GET",
        request_shape="openai_models",
        expected_models=("Qwen3.5-122B-A10B-NVFP4",),
    )

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert "json" not in kwargs
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "Qwen3.5-122B-A10B-NVFP4"},
                    {"id": "Qwen3.6-27B-NVFP4"},
                ]
            },
        )

    result = run_remote_provider_preflight_check(config, requester=requester)

    assert result["status"] == "PASS"
    assert result["observed_model_count"] == 2


def test_run_remote_provider_preflight_check_reports_missing_config_and_models() -> None:
    missing_config = RemoteProviderPreflightConfig(
        capability="generation",
        endpoint_env="NEX_MO_VLLM_MODELS_URL",
        url="",
        method="GET",
        request_shape="openai_models",
        expected_models=("Qwen3.5-122B-A10B-NVFP4",),
    )

    assert run_remote_provider_preflight_check(missing_config)["failure_code"] == (
        "endpoint_not_configured"
    )

    configured = RemoteProviderPreflightConfig(
        capability="generation",
        endpoint_env="NEX_MO_VLLM_MODELS_URL",
        url="http://dgx.local:12000/v1/models",
        method="GET",
        request_shape="openai_models",
        expected_models=("Qwen3.5-122B-A10B-NVFP4",),
    )

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"models": ["OtherModel"]})

    result = run_remote_provider_preflight_check(configured, requester=requester)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "expected_model_missing"
    assert result["missing_expected_models"] == ["Qwen3.5-122B-A10B-NVFP4"]


def test_run_remote_provider_preflight_check_reports_http_and_response_errors() -> None:
    request = httpx.Request("GET", "http://dgx.local:12000/v1/models")
    response = httpx.Response(503, request=request, json={"detail": "down"})
    config = RemoteProviderPreflightConfig(
        capability="generation",
        endpoint_env="NEX_MO_VLLM_MODELS_URL",
        url="http://dgx.local:12000/v1/models",
        method="GET",
        request_shape="openai_models",
        expected_models=("Qwen3.5-122B-A10B-NVFP4",),
    )

    assert run_remote_provider_preflight_check(
        config,
        requester=lambda *args, **kwargs: response,
    )["failure_code"] == "http_status_503"

    bad_shape = run_remote_provider_preflight_check(
        config,
        requester=lambda *args, **kwargs: httpx.Response(200, json={"data": []}),
    )
    assert bad_shape["failure_code"] == "model_list_missing"

    bad_json = run_remote_provider_preflight_check(
        config,
        requester=lambda *args, **kwargs: httpx.Response(200, content=b"not-json"),
    )
    assert bad_json["failure_code"] == "JSONDecodeError"


@pytest.mark.parametrize(
    ("payload", "failure_code"),
    [
        ([], "response_not_json_object"),
        ({}, "embedding_data_missing"),
        ({"data": [{}]}, "embedding_vector_missing"),
    ],
)
def test_embedding_response_validation_failures(payload: object, failure_code: str) -> None:
    config = RemoteProviderPreflightConfig(
        capability="embedding",
        endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
        url="http://dgx.local:9103/v1/embeddings",
        method="POST",
        request_shape="openai_embeddings",
        expected_models=("EmbedA",),
    )

    with pytest.raises(Exception) as exc_info:
        validate_preflight_response(config, payload)

    assert getattr(exc_info.value, "failure_code") == failure_code


@pytest.mark.parametrize(
    ("payload", "failure_code"),
    [
        ([], "response_not_json_object"),
        ({}, "rerank_results_missing"),
        ({"results": ["bad"]}, "rerank_result_invalid"),
        ({"results": [{"index": 0}]}, "rerank_score_missing"),
    ],
)
def test_rerank_response_validation_failures(payload: object, failure_code: str) -> None:
    config = RemoteProviderPreflightConfig(
        capability="reranking",
        endpoint_env="NEX_MO_REMOTE_RERANKER_URL",
        url="http://dgx.local:9104/v1/rerank",
        method="POST",
        request_shape="rerank",
        expected_models=("RerankA",),
    )

    with pytest.raises(Exception) as exc_info:
        validate_preflight_response(config, payload)

    assert getattr(exc_info.value, "failure_code") == failure_code


def test_unsupported_request_shape_is_reported() -> None:
    config = RemoteProviderPreflightConfig(
        capability="embedding",
        endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
        url="http://dgx.local:9103/v1/embeddings",
        method="POST",
        request_shape="custom_shape",
        expected_models=(),
    )

    result = run_remote_provider_preflight_check(
        config,
        requester=lambda *args, **kwargs: httpx.Response(200, json={}),
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "unsupported_request_shape"


def test_expected_models_parser_uses_non_empty_defaults() -> None:
    assert expected_models_from_env(None, ("Default",)) == ("Default",)
    assert expected_models_from_env("A, B,,", ("Default",)) == ("A", "B")
    assert expected_models_from_env(" , ", ("Default",)) == ("Default",)
