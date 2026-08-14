from __future__ import annotations

import httpx
import pytest

from nex_mo.remote_provider import (
    RemoteProviderFailureDecision,
    RemoteProviderPreflightConfig,
    build_remote_embedding_execution_config,
    build_remote_generation_execution_config,
    build_remote_provider_preflight_configs,
    build_remote_reranker_execution_config,
    classify_remote_provider_exception,
    classify_remote_provider_http_status,
    execute_remote_embedding_request,
    execute_remote_generation_request,
    execute_remote_rerank_request,
    expected_models_from_env,
    list_remote_provider_telemetry,
    normalize_remote_embedding_response,
    normalize_remote_generation_response,
    normalize_remote_rerank_response,
    remote_provider_response_invalid_decision,
    reset_remote_provider_telemetry,
    run_remote_provider_preflight_check,
    selected_generation_model_names,
    validate_preflight_response,
)
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults


@pytest.fixture(autouse=True)
def clear_remote_provider_telemetry():
    reset_remote_provider_telemetry()
    yield
    reset_remote_provider_telemetry()


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
    assert configs[1].expected_models == ("Qwen3-Reranker-0.6B",)
    assert configs[2].url == "http://dgx.local:12000/v1/models"
    assert configs[2].headers()["Authorization"] == "Bearer secret"
    assert configs[2].timeout_seconds == 8.5
    assert "secret" not in str(configs[2].to_safe_summary())
    assert "request_options" not in configs[0].to_safe_summary()
    assert "request_options" not in configs[1].to_safe_summary()


def test_remote_provider_configs_reject_non_positive_timeout() -> None:
    with pytest.raises(ValueError) as exc_info:
        build_remote_provider_preflight_configs(
            {"NEX_MO_LIVE_TIMEOUT_SECONDS": "0"}
        )

    assert str(exc_info.value) == "NEX_MO_LIVE_TIMEOUT_SECONDS must be positive."

    with pytest.raises(ValueError):
        build_remote_embedding_execution_config(
            {"NEX_MO_LIVE_TIMEOUT_SECONDS": "-0.5"}
        )


def test_remote_provider_configs_support_nex_pcx_request_shapes() -> None:
    configs = build_remote_provider_preflight_configs(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "nex_pcx_embeddings_v1",
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
            "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "nex_pcx_rerank_v1",
        }
    )

    assert [config.request_shape for config in configs[:2]] == [
        "nex_pcx_embeddings_v1",
        "nex_pcx_rerank_v1",
    ]
    assert configs[0].request_json() == {
        "profile_name": "qwen3_4b_2560",
        "model_key": "qwen3_embedding_4b",
        "input_type": "document",
        "texts": ["nex live provider preflight"],
        "output_dimension": 2560,
        "normalize_embeddings": True,
    }
    assert configs[1].request_json() == {
        "query_text": "nex live provider preflight",
        "top_k": 1,
        "reranker_profile_name": "qwen3_reranker_0_6b",
        "reranker_model_id": "Qwen/Qwen3-Reranker-0.6B",
        "candidates": [
            {
                "candidate_key": "doc-1",
                "rank": 1,
                "text": "NeX live provider preflight document.",
                "source_profile_name": "qwen3_4b_2560",
                "source_retrieval_strategy": "preflight",
                "source_score": 0.5,
            }
        ],
    }
    assert configs[0].to_safe_summary()["request_options"]["profile_name"] == (
        "qwen3_4b_2560"
    )
    assert configs[1].to_safe_summary()["request_options"]["reranker_profile_name"] == (
        "qwen3_reranker_0_6b"
    )


def test_remote_embedding_execution_config_uses_model_overrides() -> None:
    config = build_remote_embedding_execution_config(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "EmbeddingA",
            "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "EmbeddingA@2026-08-03",
            "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "dgx-embedding-a",
            "NEX_MO_REMOTE_EMBEDDING_API_KEY": "secret",
        }
    )

    assert config.model_name == "EmbeddingA"
    assert config.model_revision == "EmbeddingA@2026-08-03"
    assert config.deployment_id == "dgx-embedding-a"
    assert config.headers()["Authorization"] == "Bearer secret"
    assert "secret" not in str(config.to_safe_summary())
    assert "request_options" not in config.to_safe_summary()


def test_remote_reranker_execution_config_uses_model_overrides() -> None:
    config = build_remote_reranker_execution_config(
        {
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
            "NEX_MO_REMOTE_RERANKER_MODEL": "RerankerA",
            "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": "RerankerA@2026-08-03",
            "NEX_MO_REMOTE_RERANKER_DEPLOYMENT_ID": "dgx-reranker-a",
            "NEX_MO_REMOTE_RERANKER_API_KEY": "secret",
        }
    )

    assert config.model_name == "RerankerA"
    assert config.model_revision == "RerankerA@2026-08-03"
    assert config.deployment_id == "dgx-reranker-a"
    assert config.headers()["Authorization"] == "Bearer secret"
    assert "secret" not in str(config.to_safe_summary())
    assert "request_options" not in config.to_safe_summary()


def test_remote_generation_execution_config_uses_vllm_base_and_profile() -> None:
    config = build_remote_generation_execution_config(
        {
            "NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000",
            "NEX_MO_VLLM_API_KEY": "secret",
            "NEX_MO_GENERATION_PROFILE": "qwen3_6_27b_nvfp4",
        }
    )

    assert config.url == "http://dgx.local:12000/v1/chat/completions"
    assert config.model_name == "Qwen3.6-27B-NVFP4"
    assert config.model_revision == "Qwen3.6-27B-NVFP4"
    assert config.headers()["Authorization"] == "Bearer secret"
    assert "secret" not in str(config.to_safe_summary())

    explicit = build_remote_generation_execution_config(
        {
            "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://vllm.local/chat",
            "NEX_MO_VLLM_MODEL": "GenerationA",
            "NEX_MO_VLLM_MODEL_REVISION": "GenerationA@rev",
            "NEX_MO_VLLM_DEPLOYMENT_ID": "vllm-a",
        }
    )
    assert explicit.url == "http://vllm.local/chat"
    assert explicit.model_name == "GenerationA"
    assert explicit.model_revision == "GenerationA@rev"
    assert explicit.deployment_id == "vllm-a"


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

    embedding_config = build_remote_embedding_execution_config(
        {
            "NEX_MO_LIVE_EMBEDDING_HEALTH_URL": "http://legacy.local/embed",
        }
    )
    assert embedding_config.url == "http://legacy.local/embed"

    reranker_config = build_remote_reranker_execution_config(
        {
            "NEX_MO_LIVE_RERANKER_HEALTH_URL": "http://legacy.local/rerank",
        }
    )
    assert reranker_config.url == "http://legacy.local/rerank"


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


def test_execute_remote_embedding_request_posts_openai_shape_and_normalizes() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"index": 0, "embedding": [1, 2.5]},
                    {"embedding": [3, 4]},
                ],
                "usage": {"prompt_tokens": 11, "total_tokens": 11},
            },
        )

    response = execute_remote_embedding_request(
        {
            "alias": "mock-embedding-default",
            "inputs": ["alpha", "beta"],
        },
        environ={
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_API_KEY": "secret",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "EmbeddingA",
            "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "EmbeddingA@rev",
            "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "remote-embedding-a",
        },
        requester=requester,
    )

    assert calls == [
        {
            "method": "POST",
            "url": "http://dgx.local:9103/v1/embeddings",
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer secret",
            },
            "json": {"model": "EmbeddingA", "input": ["alpha", "beta"]},
            "timeout": 5.0,
        }
    ]
    assert response == {
        "object": "list",
        "alias": "mock-embedding-default",
        "model_revision": "EmbeddingA@rev",
        "deployment_id": "remote-embedding-a",
        "data": [
            {"object": "embedding", "index": 0, "embedding": [1.0, 2.5]},
            {"object": "embedding", "index": 1, "embedding": [3.0, 4.0]},
        ],
        "usage": {"input_tokens": 11, "output_tokens": 0, "total_tokens": 11},
    }
    assert "dgx.local" not in str(response)
    assert "secret" not in str(response)


def test_execute_remote_embedding_request_posts_nex_pcx_shape_and_normalizes() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "embeddings": [
                    [0.1, 0.2],
                    [0.3, 0.4],
                ]
            },
        )

    response = execute_remote_embedding_request(
        {
            "alias": "mock-embedding-default",
            "inputs": ["alpha", "beta"],
        },
        environ={
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "nex_pcx_embeddings_v1",
            "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "Qwen3-embedding-4B@pcx",
        },
        requester=requester,
    )

    assert calls[0]["json"] == {
        "profile_name": "qwen3_4b_2560",
        "model_key": "qwen3_embedding_4b",
        "input_type": "document",
        "texts": ["alpha", "beta"],
        "output_dimension": 2560,
        "normalize_embeddings": True,
    }
    assert response["model_revision"] == "Qwen3-embedding-4B@pcx"
    assert response["data"] == [
        {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
        {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
    ]
    assert response["usage"]["input_tokens"] == 2
    assert "dgx.local" not in str(response)


def test_execute_remote_embedding_request_rejects_missing_config_and_private_fields() -> None:
    with pytest.raises(Exception) as missing:
        execute_remote_embedding_request(
            {"alias": "mock-embedding-default", "inputs": ["alpha"]},
            environ={},
            requester=lambda *args, **kwargs: httpx.Response(200, json={}),
        )

    assert getattr(missing.value, "error_code") == "mo.remote_embedding_not_configured"
    assert getattr(missing.value, "retryable") is True

    with pytest.raises(Exception) as leaked:
        execute_remote_embedding_request(
            {
                "alias": "mock-embedding-default",
                "inputs": ["alpha"],
                "provider_url": "http://bad.local",
            },
            environ={"NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings"},
        )

    assert getattr(leaked.value, "error_code") == "mo.provider_field_forbidden"


def test_remote_provider_failure_decision_is_safe_and_routeable() -> None:
    decision = RemoteProviderFailureDecision(
        failure_kind="upstream_5xx",
        error_code="mo.remote_embedding_http_error",
        status_code=503,
        detail="Remote provider returned HTTP 503.",
        retryable=True,
        degraded=True,
        upstream_status_code=503,
    )

    route_error = decision.to_route_error()

    assert route_error.status_code == 503
    assert route_error.error_code == "mo.remote_embedding_http_error"
    assert route_error.retryable is True
    assert route_error.degraded is True
    assert decision.to_safe_summary() == {
        "failure_kind": "upstream_5xx",
        "error_code": "mo.remote_embedding_http_error",
        "status_code": 503,
        "retryable": True,
        "degraded": True,
        "upstream_status_code": 503,
    }
    assert "dgx.local" not in str(decision.to_safe_summary())
    assert "secret" not in str(decision.to_safe_summary())


@pytest.mark.parametrize(
    ("upstream_status", "failure_kind", "error_code", "status_code", "retryable", "degraded"),
    [
        (429, "throttled", "mo.remote_embedding_throttled", 429, True, True),
        (500, "upstream_5xx", "mo.remote_embedding_http_error", 503, True, True),
        (503, "upstream_5xx", "mo.remote_embedding_http_error", 503, True, True),
        (400, "upstream_4xx", "mo.remote_embedding_http_error", 502, False, False),
    ],
)
def test_remote_provider_failure_taxonomy_classifies_http_statuses(
    upstream_status: int,
    failure_kind: str,
    error_code: str,
    status_code: int,
    retryable: bool,
    degraded: bool,
) -> None:
    decision = classify_remote_provider_http_status(
        upstream_status,
        error_code_prefix="mo.remote_embedding",
    )

    assert decision.failure_kind == failure_kind
    assert decision.error_code == error_code
    assert decision.status_code == status_code
    assert decision.retryable is retryable
    assert decision.degraded is degraded
    assert decision.upstream_status_code == upstream_status


@pytest.mark.parametrize(
    ("exc", "failure_kind", "error_code", "status_code"),
    [
        (
            httpx.TimeoutException("slow"),
            "timeout",
            "mo.remote_generation_timeout",
            504,
        ),
        (
            httpx.ConnectError("down"),
            "connection_error",
            "mo.remote_generation_unavailable",
            503,
        ),
    ],
)
def test_remote_provider_failure_taxonomy_classifies_exceptions(
    exc: httpx.HTTPError,
    failure_kind: str,
    error_code: str,
    status_code: int,
) -> None:
    decision = classify_remote_provider_exception(
        exc,
        error_code_prefix="mo.remote_generation",
    )

    assert decision.failure_kind == failure_kind
    assert decision.error_code == error_code
    assert decision.status_code == status_code
    assert decision.retryable is True
    assert decision.degraded is True


def test_remote_provider_response_invalid_is_retryable_degraded() -> None:
    decision = remote_provider_response_invalid_decision(
        error_code_prefix="mo.remote_reranker",
        detail="Remote reranker response must include non-empty results.",
    )

    assert decision.failure_kind == "malformed_response"
    assert decision.error_code == "mo.remote_reranker_response_invalid"
    assert decision.status_code == 502
    assert decision.retryable is True
    assert decision.degraded is True
    assert "upstream_status_code" not in decision.to_safe_summary()


def test_remote_provider_telemetry_lists_safe_zero_state_for_current_configs() -> None:
    telemetry = list_remote_provider_telemetry(
        environ={
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_API_KEY": "secret",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "EmbeddingA",
            "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "EmbeddingA@rev",
            "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "remote-embedding-a",
        }
    )

    embedding = [
        item for item in telemetry if item["capability"] == "embedding"
    ][0]
    assert embedding["configured"] is True
    assert embedding["endpoint_env"] == "NEX_MO_REMOTE_EMBEDDING_URL"
    assert embedding["model_name"] == "EmbeddingA"
    assert embedding["model_revision"] == "EmbeddingA@rev"
    assert embedding["deployment_id"] == "remote-embedding-a"
    assert embedding["authorization_configured"] is True
    assert embedding["request_count"] == 0
    assert embedding["last_outcome"] is None
    assert "dgx.local" not in str(telemetry)
    assert "secret" not in str(telemetry)


def test_remote_provider_telemetry_records_success_and_failure() -> None:
    environ = {
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "EmbeddingA",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "EmbeddingA@rev",
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "remote-embedding-a",
    }

    execute_remote_embedding_request(
        {"alias": "mock-embedding-default", "inputs": ["alpha"]},
        environ=environ,
        requester=lambda *args, **kwargs: httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2]}]},
        ),
    )
    with pytest.raises(Exception):
        execute_remote_embedding_request(
            {"alias": "mock-embedding-default", "inputs": ["beta"]},
            environ=environ,
            requester=lambda *args, **kwargs: httpx.Response(
                503,
                json={"error": "down"},
            ),
        )

    telemetry = list_remote_provider_telemetry(
        capability="embedding",
        environ=environ,
    )

    assert len(telemetry) == 1
    assert telemetry[0]["request_count"] == 2
    assert telemetry[0]["success_count"] == 1
    assert telemetry[0]["failure_count"] == 1
    assert telemetry[0]["retryable_failure_count"] == 1
    assert telemetry[0]["degraded_count"] == 1
    assert telemetry[0]["last_outcome"] == "failure"
    assert telemetry[0]["last_status_code"] == 503
    assert telemetry[0]["last_error_code"] == "mo.remote_embedding_http_error"
    assert telemetry[0]["last_failure_kind"] == "upstream_5xx"
    assert telemetry[0]["last_upstream_status_code"] == 503
    assert isinstance(telemetry[0]["last_latency_ms"], int)
    assert isinstance(telemetry[0]["last_observed_at"], str)


def test_remote_provider_telemetry_records_malformed_response_degrade() -> None:
    environ = {
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_MODEL": "RerankerA",
    }

    with pytest.raises(Exception):
        execute_remote_rerank_request(
            {
                "alias": "mock-reranker-default",
                "query": "quality",
                "documents": ["doc-a"],
            },
            environ=environ,
            requester=lambda *args, **kwargs: httpx.Response(
                200,
                json={"results": []},
            ),
        )

    telemetry = list_remote_provider_telemetry(
        capability="reranking",
        environ=environ,
    )

    assert telemetry[0]["failure_count"] == 1
    assert telemetry[0]["retryable_failure_count"] == 1
    assert telemetry[0]["degraded_count"] == 1
    assert telemetry[0]["last_error_code"] == "mo.remote_reranker_response_invalid"
    assert telemetry[0]["last_failure_kind"] == "malformed_response"


@pytest.mark.parametrize(
    ("provider_payload", "expected_detail"),
    [
        ([], "JSON object"),
        ({"data": []}, "count"),
        ({"data": ["bad"]}, "item"),
        ({"data": [{"embedding": []}]}, "vector"),
        ({"data": [{"embedding": [True]}]}, "vector"),
    ],
)
def test_normalize_remote_embedding_response_rejects_bad_shapes(
    provider_payload: object,
    expected_detail: str,
) -> None:
    config = build_remote_embedding_execution_config(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
        }
    )

    with pytest.raises(Exception) as exc_info:
        normalize_remote_embedding_response(
            provider_payload=provider_payload,
            alias="mock-embedding-default",
            config=config,
            input_count=1,
            input_texts=["alpha"],
        )

    assert getattr(exc_info.value, "error_code") == "mo.remote_embedding_response_invalid"
    assert expected_detail in getattr(exc_info.value, "detail")


@pytest.mark.parametrize(
    ("requester", "error_code", "retryable"),
    [
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.TimeoutException("slow")),
            "mo.remote_embedding_timeout",
            True,
        ),
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("down")),
            "mo.remote_embedding_unavailable",
            True,
        ),
        (
            lambda *args, **kwargs: httpx.Response(429, json={"error": "throttled"}),
            "mo.remote_embedding_throttled",
            True,
        ),
        (
            lambda *args, **kwargs: httpx.Response(503, json={"error": "down"}),
            "mo.remote_embedding_http_error",
            True,
        ),
        (
            lambda *args, **kwargs: httpx.Response(200, content=b"not-json"),
            "mo.remote_embedding_response_invalid",
            True,
        ),
    ],
)
def test_execute_remote_embedding_request_reports_safe_provider_errors(
    requester,
    error_code: str,
    retryable: bool,
) -> None:
    with pytest.raises(Exception) as exc_info:
        execute_remote_embedding_request(
            {"alias": "mock-embedding-default", "inputs": ["alpha"]},
            environ={"NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings"},
            requester=requester,
        )

    assert getattr(exc_info.value, "error_code") == error_code
    assert getattr(exc_info.value, "retryable") is retryable


def test_execute_remote_rerank_request_posts_shape_and_normalizes_sorted_results() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "relevance_score": 0.2},
                    {"index": 0, "score": 0.9, "document": "doc-a"},
                ],
                "usage": {"input_tokens": 5, "total_tokens": 5},
            },
        )

    response = execute_remote_rerank_request(
        {
            "alias": "mock-reranker-default",
            "query": "quality",
            "documents": ["doc-a", "doc-b"],
            "top_n": 5,
        },
        environ={
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
            "NEX_MO_REMOTE_RERANKER_MODEL": "RerankerA",
            "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": "RerankerA@rev",
            "NEX_MO_REMOTE_RERANKER_DEPLOYMENT_ID": "remote-reranker-a",
        },
        requester=requester,
    )

    assert calls == [
        {
            "method": "POST",
            "url": "http://dgx.local:9104/v1/rerank",
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            "json": {
                "model": "RerankerA",
                "query": "quality",
                "documents": ["doc-a", "doc-b"],
                "top_n": 2,
            },
            "timeout": 5.0,
        }
    ]
    assert response == {
        "alias": "mock-reranker-default",
        "model_revision": "RerankerA@rev",
        "deployment_id": "remote-reranker-a",
        "results": [
            {"index": 0, "score": 0.9, "document": "doc-a"},
            {"index": 1, "score": 0.2, "document": "doc-b"},
        ],
        "usage": {"input_tokens": 5, "output_tokens": 0, "total_tokens": 5},
    }
    assert "dgx.local" not in str(response)


def test_direct_vllm_profile_executes_three_providers_and_records_safe_telemetry() -> None:
    calls: list[dict[str, object]] = []
    environ = {
        **protected_dgx_vllm_profile_defaults(),
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "secret",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000",
        "NEX_MO_VLLM_API_KEY": "secret",
    }

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/v1/embeddings"):
            return httpx.Response(
                200,
                json={
                    "id": "embd-vllm-001",
                    "created": 1780000000,
                    "object": "list",
                    "model": "Qwen3-Embedding-4B",
                    "data": [
                        {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
                        {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 0,
                        "prompt_tokens_details": {},
                        "total_tokens": 2,
                    },
                },
            )
        if url.endswith("/v1/rerank"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "index": 1,
                            "relevance_score": 0.4,
                            "document": {"text": "vllm-doc-b"},
                        },
                        {
                            "index": 0,
                            "relevance_score": 0.9,
                            "document": {"text": "vllm-doc-a"},
                        },
                    ],
                    "usage": {"prompt_tokens": 6, "total_tokens": 6},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-vllm-001",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "direct vLLM answer",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
            },
        )

    embedding = execute_remote_embedding_request(
        {"alias": "mock-embedding-default", "inputs": ["alpha", "beta"]},
        environ=environ,
        requester=requester,
    )
    rerank = execute_remote_rerank_request(
        {
            "alias": "mock-reranker-default",
            "query": "quality",
            "documents": ["doc-a", "doc-b"],
            "top_n": 1,
        },
        environ=environ,
        requester=requester,
    )
    generation = execute_remote_generation_request(
        {
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "prompt": "Say hello.",
            "max_output_tokens": 32,
        },
        request_id="req-001",
        trace_id="trace-001",
        environ=environ,
        requester=requester,
    )
    telemetry = {
        item["capability"]: item for item in list_remote_provider_telemetry(environ=environ)
    }

    assert [call["url"] for call in calls] == [
        "http://dgx.local:9112/v1/embeddings",
        "http://dgx.local:9113/v1/rerank",
        "http://dgx.local:12000/v1/chat/completions",
    ]
    assert calls[0]["json"] == {
        "model": "Qwen3-Embedding-4B",
        "input": ["alpha", "beta"],
    }
    assert calls[1]["json"] == {
        "model": "Qwen3-Reranker-0.6B",
        "query": "quality",
        "documents": ["doc-a", "doc-b"],
        "top_n": 1,
    }
    assert calls[2]["json"]["model"] == "Qwen3.5-122B-A10B-NVFP4"
    assert calls[2]["json"]["messages"] == [{"role": "user", "content": "Say hello."}]
    assert all(call["headers"]["Authorization"] == "Bearer secret" for call in calls)

    assert embedding["model_revision"] == "Qwen3-Embedding-4B"
    assert embedding["usage"] == {"input_tokens": 2, "output_tokens": 0, "total_tokens": 2}
    assert rerank["results"] == [
        {"index": 0, "score": 0.9, "document": "vllm-doc-a"},
        {"index": 1, "score": 0.4, "document": "vllm-doc-b"},
    ]
    assert generation["mo_generation_id"] == "chatcmpl-vllm-001"
    assert generation["output"]["text"] == "direct vLLM answer"
    assert telemetry["embedding"]["request_count"] == 1
    assert telemetry["reranking"]["request_count"] == 1
    assert telemetry["generation"]["request_count"] == 1
    assert "dgx.local" not in str(embedding)
    assert "dgx.local" not in str(rerank)
    assert "dgx.local" not in str(generation)
    assert "dgx.local" not in str(telemetry)
    assert "secret" not in str(telemetry)


def test_execute_remote_rerank_request_posts_nex_pcx_shape_and_normalizes() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "results": [
                    {"candidate_key": "doc-2", "rank": 1, "score": 9.5},
                    {"candidate_key": "doc-1", "rank": 2, "score": 2.0},
                ]
            },
        )

    response = execute_remote_rerank_request(
        {
            "alias": "mock-reranker-default",
            "query": "quality",
            "documents": ["doc-a", "doc-b"],
        },
        environ={
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
            "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "nex_pcx_rerank_v1",
            "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": "Qwen3-Reranker-0.6B@pcx",
        },
        requester=requester,
    )

    assert calls[0]["json"] == {
        "query_text": "quality",
        "top_k": 2,
        "reranker_profile_name": "qwen3_reranker_0_6b",
        "reranker_model_id": "Qwen/Qwen3-Reranker-0.6B",
        "candidates": [
            {
                "candidate_key": "doc-1",
                "rank": 1,
                "text": "doc-a",
                "source_profile_name": "qwen3_4b_2560",
                "source_retrieval_strategy": "preflight",
                "source_score": 0.5,
            },
            {
                "candidate_key": "doc-2",
                "rank": 2,
                "text": "doc-b",
                "source_profile_name": "qwen3_4b_2560",
                "source_retrieval_strategy": "preflight",
                "source_score": 0.5,
            },
        ],
    }
    assert response["model_revision"] == "Qwen3-Reranker-0.6B@pcx"
    assert response["results"] == [
        {"index": 0, "score": 9.5, "document": "doc-a"},
        {"index": 1, "score": 2.0, "document": "doc-b"},
    ]


def test_execute_remote_rerank_request_rejects_missing_config_and_bad_top_n() -> None:
    with pytest.raises(Exception) as missing:
        execute_remote_rerank_request(
            {
                "alias": "mock-reranker-default",
                "query": "quality",
                "documents": ["doc-a"],
            },
            environ={},
        )

    assert getattr(missing.value, "error_code") == "mo.remote_reranker_not_configured"
    assert getattr(missing.value, "retryable") is True

    with pytest.raises(Exception) as invalid:
        execute_remote_rerank_request(
            {
                "alias": "mock-reranker-default",
                "query": "quality",
                "documents": ["doc-a"],
                "top_n": 0,
            },
            environ={"NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank"},
        )

    assert getattr(invalid.value, "error_code") == "mo.request_invalid"


def test_execute_remote_rerank_request_rejects_private_fields() -> None:
    with pytest.raises(Exception) as leaked:
        execute_remote_rerank_request(
            {
                "alias": "mock-reranker-default",
                "query": "quality",
                "documents": ["doc-a"],
                "api_key": "bad",
            },
            environ={"NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank"},
        )

    assert getattr(leaked.value, "error_code") == "mo.provider_field_forbidden"


@pytest.mark.parametrize(
    ("provider_payload", "expected_detail"),
    [
        ([], "JSON object"),
        ({}, "results"),
        ({"results": ["bad"]}, "item"),
        ({"results": [{"index": -1, "score": 0.1}]}, "index"),
        ({"results": [{"index": 0}]}, "score"),
        ({"results": [{"index": 0, "score": True}]}, "score"),
    ],
)
def test_normalize_remote_rerank_response_rejects_bad_shapes(
    provider_payload: object,
    expected_detail: str,
) -> None:
    config = build_remote_reranker_execution_config(
        {
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
        }
    )

    with pytest.raises(Exception) as exc_info:
        normalize_remote_rerank_response(
            provider_payload=provider_payload,
            alias="mock-reranker-default",
            config=config,
            documents=["doc-a"],
            query="quality",
        )

    assert getattr(exc_info.value, "error_code") == "mo.remote_reranker_response_invalid"
    assert expected_detail in getattr(exc_info.value, "detail")


@pytest.mark.parametrize(
    ("requester", "error_code", "retryable"),
    [
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.TimeoutException("slow")),
            "mo.remote_reranker_timeout",
            True,
        ),
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("down")),
            "mo.remote_reranker_unavailable",
            True,
        ),
        (
            lambda *args, **kwargs: httpx.Response(503, json={"error": "down"}),
            "mo.remote_reranker_http_error",
            True,
        ),
        (
            lambda *args, **kwargs: httpx.Response(200, content=b"not-json"),
            "mo.remote_reranker_response_invalid",
            True,
        ),
    ],
)
def test_execute_remote_rerank_request_reports_safe_provider_errors(
    requester,
    error_code: str,
    retryable: bool,
) -> None:
    with pytest.raises(Exception) as exc_info:
        execute_remote_rerank_request(
            {
                "alias": "mock-reranker-default",
                "query": "quality",
                "documents": ["doc-a"],
            },
            environ={"NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank"},
            requester=requester,
        )

    assert getattr(exc_info.value, "error_code") == error_code
    assert getattr(exc_info.value, "retryable") is retryable


def test_execute_remote_generation_request_posts_chat_completion_and_normalizes() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "id": "cmpl-001",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Draft complete."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            },
        )

    response = execute_remote_generation_request(
        {
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Draft the summary."},
            ],
            "response_format": {"type": "json_object"},
            "max_output_tokens": 128,
            "temperature": 0.2,
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        },
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        trace_id="fallback-trace",
        environ={
            "NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000",
            "NEX_MO_VLLM_API_KEY": "secret",
            "NEX_MO_VLLM_MODEL": "GenerationA",
            "NEX_MO_VLLM_MODEL_REVISION": "GenerationA@rev",
            "NEX_MO_VLLM_DEPLOYMENT_ID": "vllm-a",
        },
        requester=requester,
    )

    assert calls == [
        {
            "method": "POST",
            "url": "http://dgx.local:12000/v1/chat/completions",
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer secret",
            },
            "json": {
                "model": "GenerationA",
                "messages": [
                    {"role": "system", "content": "Be concise."},
                    {"role": "user", "content": "Draft the summary."},
                ],
                "temperature": 0.2,
                "max_tokens": 128,
                "stream": False,
                "response_format": {"type": "json_object"},
            },
            "timeout": 5.0,
        }
    ]
    assert response["mo_generation_id"] == "cmpl-001"
    assert response["alias"] == "general-llm-default"
    assert response["model_revision"] == "GenerationA@rev"
    assert response["deployment_id"] == "vllm-a"
    assert response["provider_type"] == "vllm"
    assert response["output"] == {"type": "text", "text": "Draft complete."}
    assert response["finish_reason"] == "STOP"
    assert response["usage"] == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    assert response["runtime_metadata"]["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert "dgx.local" not in str(response)
    assert "secret" not in str(response)


def test_execute_remote_generation_request_uses_prompt_fallback_and_text_choice() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        assert kwargs["json"]["messages"] == [
            {"role": "user", "content": "Plain prompt."}
        ]
        assert "response_format" not in kwargs["json"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "text": "Plain completion.",
                        "finish_reason": "length",
                    }
                ],
            },
        )

    response = execute_remote_generation_request(
        {
            "prompt": "Plain prompt.",
            "response_format": {"type": "text"},
        },
        request_id="req-001",
        trace_id="trace-001",
        environ={"NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://vllm.local/chat"},
        requester=requester,
    )

    assert response["finish_reason"] == "LENGTH"
    assert response["output"]["text"] == "Plain completion."
    assert response["usage"]["total_tokens"] == 2
    assert response["mo_generation_id"]


def test_execute_remote_generation_request_rejects_missing_config_and_streaming() -> None:
    with pytest.raises(Exception) as missing:
        execute_remote_generation_request(
            {"prompt": "hello"},
            request_id="req-001",
            trace_id="trace-001",
            environ={},
        )

    assert getattr(missing.value, "error_code") == "mo.remote_generation_not_configured"
    assert getattr(missing.value, "retryable") is True

    with pytest.raises(Exception) as streaming:
        execute_remote_generation_request(
            {"prompt": "hello", "stream": True},
            request_id="req-001",
            trace_id="trace-001",
            environ={"NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://vllm.local/chat"},
        )

    assert getattr(streaming.value, "error_code") == (
        "mo.remote_generation_streaming_unsupported"
    )


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({"messages": ["bad"]}, "mo.request_invalid"),
        ({"messages": [{"role": "", "content": "x"}]}, "mo.request_invalid"),
        ({"messages": [{"role": "user", "content": ""}]}, "mo.request_invalid"),
        ({"prompt": "x", "temperature": "warm"}, "mo.request_invalid"),
        ({"prompt": "x", "max_output_tokens": 0}, "mo.request_invalid"),
        ({"prompt": "x", "max_output_tokens": 2048}, "mo.generation_parameter_out_of_bounds"),
        ({"prompt": "x", "provider_endpoint": "http://bad.local"}, "mo.provider_field_forbidden"),
    ],
)
def test_execute_remote_generation_request_rejects_invalid_requests(
    payload: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(Exception) as exc_info:
        execute_remote_generation_request(
            payload,
            request_id="req-001",
            trace_id="trace-001",
            environ={"NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://vllm.local/chat"},
        )

    assert getattr(exc_info.value, "error_code") == error_code


@pytest.mark.parametrize(
    ("provider_payload", "expected_detail"),
    [
        ([], "JSON object"),
        ({}, "choices"),
        ({"choices": ["bad"]}, "choice"),
        ({"choices": [{"message": {"content": ""}}]}, "output text"),
    ],
)
def test_normalize_remote_generation_response_rejects_bad_shapes(
    provider_payload: object,
    expected_detail: str,
) -> None:
    config = build_remote_generation_execution_config(
        {"NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://vllm.local/chat"}
    )

    with pytest.raises(Exception) as exc_info:
        normalize_remote_generation_response(
            provider_payload=provider_payload,
            alias="general-llm-default",
            route_id="route-general-llm-default",
            config=config,
            request_id="req-001",
            trace_id="trace-001",
            input_texts=["hello"],
        )

    assert getattr(exc_info.value, "error_code") == "mo.remote_generation_response_invalid"
    assert expected_detail in getattr(exc_info.value, "detail")


@pytest.mark.parametrize(
    ("requester", "error_code", "retryable"),
    [
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.TimeoutException("slow")),
            "mo.remote_generation_timeout",
            True,
        ),
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("down")),
            "mo.remote_generation_unavailable",
            True,
        ),
        (
            lambda *args, **kwargs: httpx.Response(500, json={"error": "down"}),
            "mo.remote_generation_http_error",
            True,
        ),
        (
            lambda *args, **kwargs: httpx.Response(200, content=b"not-json"),
            "mo.remote_generation_response_invalid",
            True,
        ),
    ],
)
def test_execute_remote_generation_request_reports_safe_provider_errors(
    requester,
    error_code: str,
    retryable: bool,
) -> None:
    with pytest.raises(Exception) as exc_info:
        execute_remote_generation_request(
            {"prompt": "hello"},
            request_id="req-001",
            trace_id="trace-001",
            environ={"NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://vllm.local/chat"},
            requester=requester,
        )

    assert getattr(exc_info.value, "error_code") == error_code
    assert getattr(exc_info.value, "retryable") is retryable


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
