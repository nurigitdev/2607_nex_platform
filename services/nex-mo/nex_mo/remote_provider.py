from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from nex_mo.provider_normalization import (
    _finish_reason_from_choice,
    normalize_remote_embedding_response,
    normalize_remote_generation_response,
    normalize_remote_rerank_response,
)
from nex_mo.provider_telemetry import (
    RemoteProviderTelemetryBucket,
    list_provider_telemetry,
    record_provider_retry,
    recorded_provider_call as _recorded_remote_provider_call,
    reset_provider_telemetry as reset_remote_provider_telemetry,
)
from nex_mo.provider_retry import build_provider_retry_policy
from nex_mo.provider_retry_transport import execute_remote_json_request_with_retry
from nex_mo.provider_transport import (
    HttpRequester,
    RemoteProviderFailureDecision,
    classify_remote_provider_exception,
    classify_remote_provider_http_status,
    remote_provider_response_invalid_decision,
)
from nex_mo.provider_catalog import (
    DEFAULT_GENERATION_PROFILE,
    build_model_profile_catalog,
)
from nex_mo.provider_registry import (
    ProviderRouteError,
    resolve_provider_route,
)

LEGACY_LIVE_TIMEOUT_ENV = "NEX_MO_LIVE_TIMEOUT_SECONDS"
REMOTE_EMBEDDING_TIMEOUT_ENV = "NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS"
REMOTE_RERANKER_TIMEOUT_ENV = "NEX_MO_REMOTE_RERANKER_TIMEOUT_SECONDS"
VLLM_TIMEOUT_ENV = "NEX_MO_VLLM_TIMEOUT_SECONDS"
DEFAULT_REMOTE_EMBEDDING_TIMEOUT_SECONDS = 15.0
DEFAULT_REMOTE_RERANKER_TIMEOUT_SECONDS = 15.0
DEFAULT_REMOTE_GENERATION_TIMEOUT_SECONDS = 60.0
DEFAULT_TIMEOUT_SECONDS = DEFAULT_REMOTE_EMBEDDING_TIMEOUT_SECONDS
PREFLIGHT_TEXT = "nex live provider preflight"
OPENAI_EMBEDDINGS_SHAPE = "openai_embeddings"
NEX_PCX_EMBEDDINGS_SHAPE = "nex_pcx_embeddings_v1"
GENERIC_RERANK_SHAPE = "rerank"
NEX_PCX_RERANK_SHAPE = "nex_pcx_rerank_v1"
OPENAI_MODELS_SHAPE = "openai_models"


@dataclass(frozen=True)
class RemoteProviderPreflightConfig:
    capability: str
    endpoint_env: str
    url: str
    method: str
    request_shape: str
    expected_models: tuple[str, ...]
    api_key_env: str | None = None
    api_key: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    timeout_env: str = LEGACY_LIVE_TIMEOUT_ENV
    timeout_fallback_env: str = LEGACY_LIVE_TIMEOUT_ENV
    legacy_endpoint_env: str | None = None
    request_options: dict[str, Any] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.url)

    @property
    def authorization_configured(self) -> bool:
        return bool(self.api_key)

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.method == "POST":
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def request_json(self) -> dict[str, Any] | None:
        model_name = self.expected_models[0] if self.expected_models else ""
        if self.request_shape == OPENAI_EMBEDDINGS_SHAPE:
            return {
                "model": model_name,
                "input": [PREFLIGHT_TEXT],
            }
        if self.request_shape == NEX_PCX_EMBEDDINGS_SHAPE:
            return _nex_pcx_embedding_request_payload(
                self,
                texts=[PREFLIGHT_TEXT],
            )
        if self.request_shape == GENERIC_RERANK_SHAPE:
            return {
                "model": model_name,
                "query": PREFLIGHT_TEXT,
                "documents": ["NeX live provider preflight document."],
                "top_n": 1,
            }
        if self.request_shape == NEX_PCX_RERANK_SHAPE:
            return _nex_pcx_rerank_request_payload(
                self,
                query=PREFLIGHT_TEXT,
                documents=["NeX live provider preflight document."],
                top_n=1,
            )
        if self.request_shape == OPENAI_MODELS_SHAPE:
            return None
        raise RemoteProviderPreflightError("unsupported_request_shape")

    def to_safe_summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capability": self.capability,
            "endpoint_env": self.endpoint_env,
            "configured": self.configured,
            "method": self.method,
            "request_shape": self.request_shape,
            "expected_models": list(self.expected_models),
            "authorization_env": self.api_key_env,
            "authorization_configured": self.authorization_configured,
            "timeout_seconds": self.timeout_seconds,
            "timeout_env": self.timeout_env,
            "timeout_fallback_env": self.timeout_fallback_env,
        }
        if self.legacy_endpoint_env is not None:
            payload["legacy_endpoint_env"] = self.legacy_endpoint_env
        if _request_shape_uses_pcx_options(self.request_shape):
            safe_options = _safe_request_options(self.request_options)
            if safe_options:
                payload["request_options"] = safe_options
        return payload


@dataclass(frozen=True)
class RemoteProviderExecutionConfig:
    capability: str
    endpoint_env: str
    url: str
    method: str
    request_shape: str
    model_name: str
    model_revision: str
    deployment_id: str
    api_key_env: str | None = None
    api_key: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    timeout_env: str = LEGACY_LIVE_TIMEOUT_ENV
    timeout_fallback_env: str = LEGACY_LIVE_TIMEOUT_ENV
    request_options: dict[str, Any] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.method == "POST":
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def to_safe_summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capability": self.capability,
            "endpoint_env": self.endpoint_env,
            "configured": self.configured,
            "method": self.method,
            "request_shape": self.request_shape,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "deployment_id": self.deployment_id,
            "authorization_env": self.api_key_env,
            "authorization_configured": bool(self.api_key),
            "timeout_seconds": self.timeout_seconds,
            "timeout_env": self.timeout_env,
            "timeout_fallback_env": self.timeout_fallback_env,
        }
        if _request_shape_uses_pcx_options(self.request_shape):
            safe_options = _safe_request_options(self.request_options)
            if safe_options:
                payload["request_options"] = safe_options
        return payload


class RemoteProviderPreflightError(Exception):
    def __init__(self, failure_code: str) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code


def build_remote_provider_preflight_configs(
    environ: dict[str, str] | None = None,
) -> tuple[RemoteProviderPreflightConfig, ...]:
    env = environ if environ is not None else os.environ
    embedding_timeout = _timeout_seconds(env, "embedding")
    reranker_timeout = _timeout_seconds(env, "reranking")
    generation_timeout = _timeout_seconds(env, "generation")

    return (
        RemoteProviderPreflightConfig(
            capability="embedding",
            endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
            legacy_endpoint_env="NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
            url=_env_first(env, "NEX_MO_REMOTE_EMBEDDING_URL", "NEX_MO_LIVE_EMBEDDING_HEALTH_URL"),
            method="POST",
            request_shape=_env_or_default(
                env,
                "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE",
                OPENAI_EMBEDDINGS_SHAPE,
            ),
            expected_models=expected_models_from_env(
                env.get("NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS"),
                ("Qwen3-Embedding-4B",),
            ),
            api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
            api_key=_empty_to_none(env.get("NEX_MO_REMOTE_EMBEDDING_API_KEY")),
            timeout_seconds=embedding_timeout,
            timeout_env=REMOTE_EMBEDDING_TIMEOUT_ENV,
            timeout_fallback_env=LEGACY_LIVE_TIMEOUT_ENV,
            request_options=_embedding_request_options(env),
        ),
        RemoteProviderPreflightConfig(
            capability="reranking",
            endpoint_env="NEX_MO_REMOTE_RERANKER_URL",
            legacy_endpoint_env="NEX_MO_LIVE_RERANKER_HEALTH_URL",
            url=_env_first(env, "NEX_MO_REMOTE_RERANKER_URL", "NEX_MO_LIVE_RERANKER_HEALTH_URL"),
            method="POST",
            request_shape=_env_or_default(
                env,
                "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE",
                GENERIC_RERANK_SHAPE,
            ),
            expected_models=expected_models_from_env(
                env.get("NEX_MO_LIVE_EXPECTED_RERANKER_MODELS"),
                ("Qwen3-Reranker-4B",),
            ),
            api_key_env="NEX_MO_REMOTE_RERANKER_API_KEY",
            api_key=_empty_to_none(env.get("NEX_MO_REMOTE_RERANKER_API_KEY")),
            timeout_seconds=reranker_timeout,
            timeout_env=REMOTE_RERANKER_TIMEOUT_ENV,
            timeout_fallback_env=LEGACY_LIVE_TIMEOUT_ENV,
            request_options=_reranker_request_options(env),
        ),
        RemoteProviderPreflightConfig(
            capability="generation",
            endpoint_env="NEX_MO_VLLM_MODELS_URL",
            legacy_endpoint_env="NEX_MO_LIVE_VLLM_MODELS_URL",
            url=_vllm_models_url(env),
            method="GET",
            request_shape=OPENAI_MODELS_SHAPE,
            expected_models=expected_models_from_env(
                env.get("NEX_MO_LIVE_EXPECTED_GENERATION_MODELS"),
                selected_generation_model_names(env),
            ),
            api_key_env="NEX_MO_VLLM_API_KEY",
            api_key=_empty_to_none(env.get("NEX_MO_VLLM_API_KEY")),
            timeout_seconds=generation_timeout,
            timeout_env=VLLM_TIMEOUT_ENV,
            timeout_fallback_env=LEGACY_LIVE_TIMEOUT_ENV,
        ),
    )


def run_remote_provider_preflight_check(
    config: RemoteProviderPreflightConfig,
    *,
    requester: HttpRequester = httpx.request,
) -> dict[str, Any]:
    base_result = config.to_safe_summary()
    if not config.configured:
        return {
            **base_result,
            "status": "FAIL",
            "failure_code": "endpoint_not_configured",
        }

    request_kwargs: dict[str, Any] = {
        "headers": config.headers(),
        "timeout": config.timeout_seconds,
    }
    try:
        request_json = config.request_json()
    except RemoteProviderPreflightError as exc:
        return {
            **base_result,
            "status": "FAIL",
            "failure_code": exc.failure_code,
        }
    if request_json is not None:
        request_kwargs["json"] = request_json

    try:
        response = requester(config.method, config.url, **request_kwargs)
        if response.is_error:
            return {
                **base_result,
                "status": "FAIL",
                "failure_code": f"http_status_{response.status_code}",
            }
        payload = response.json()
        observation = validate_preflight_response(config, payload)
    except (httpx.HTTPError, ValueError, RemoteProviderPreflightError) as exc:
        return {
            **base_result,
            "status": "FAIL",
            "failure_code": _failure_code(exc),
        }

    if observation.get("status") == "FAIL":
        return {
            **base_result,
            **observation,
        }
    return {
        **base_result,
        **observation,
        "status": "PASS",
    }


def build_remote_embedding_execution_config(
    environ: dict[str, str] | None = None,
) -> RemoteProviderExecutionConfig:
    env = environ if environ is not None else os.environ
    profile = _selected_profile(env, "embedding")
    model_name = env.get("NEX_MO_REMOTE_EMBEDDING_MODEL", profile.model_name)
    return RemoteProviderExecutionConfig(
        capability="embedding",
        endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
        url=_env_first(env, "NEX_MO_REMOTE_EMBEDDING_URL", "NEX_MO_LIVE_EMBEDDING_HEALTH_URL"),
        method="POST",
        request_shape=_env_or_default(
            env,
            "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE",
            OPENAI_EMBEDDINGS_SHAPE,
        ),
        model_name=model_name,
        model_revision=env.get("NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION", model_name),
        deployment_id=env.get("NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID", "remote-embedding-http"),
        api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
        api_key=_empty_to_none(env.get("NEX_MO_REMOTE_EMBEDDING_API_KEY")),
        timeout_seconds=_timeout_seconds(env, "embedding"),
        timeout_env=REMOTE_EMBEDDING_TIMEOUT_ENV,
        timeout_fallback_env=LEGACY_LIVE_TIMEOUT_ENV,
        request_options=_embedding_request_options(env),
    )


def build_remote_reranker_execution_config(
    environ: dict[str, str] | None = None,
) -> RemoteProviderExecutionConfig:
    env = environ if environ is not None else os.environ
    profile = _selected_profile(env, "reranking")
    model_name = env.get("NEX_MO_REMOTE_RERANKER_MODEL", profile.model_name)
    return RemoteProviderExecutionConfig(
        capability="reranking",
        endpoint_env="NEX_MO_REMOTE_RERANKER_URL",
        url=_env_first(env, "NEX_MO_REMOTE_RERANKER_URL", "NEX_MO_LIVE_RERANKER_HEALTH_URL"),
        method="POST",
        request_shape=_env_or_default(
            env,
            "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE",
            GENERIC_RERANK_SHAPE,
        ),
        model_name=model_name,
        model_revision=env.get("NEX_MO_REMOTE_RERANKER_MODEL_REVISION", model_name),
        deployment_id=env.get("NEX_MO_REMOTE_RERANKER_DEPLOYMENT_ID", "remote-reranker-http"),
        api_key_env="NEX_MO_REMOTE_RERANKER_API_KEY",
        api_key=_empty_to_none(env.get("NEX_MO_REMOTE_RERANKER_API_KEY")),
        timeout_seconds=_timeout_seconds(env, "reranking"),
        timeout_env=REMOTE_RERANKER_TIMEOUT_ENV,
        timeout_fallback_env=LEGACY_LIVE_TIMEOUT_ENV,
        request_options=_reranker_request_options(env),
    )


def build_remote_generation_execution_config(
    environ: dict[str, str] | None = None,
) -> RemoteProviderExecutionConfig:
    env = environ if environ is not None else os.environ
    profile = _selected_profile(env, "generation")
    model_name = env.get("NEX_MO_VLLM_MODEL", profile.model_name)
    return RemoteProviderExecutionConfig(
        capability="generation",
        endpoint_env="NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
        url=_vllm_chat_completions_url(env),
        method="POST",
        request_shape="openai_chat_completions",
        model_name=model_name,
        model_revision=env.get("NEX_MO_VLLM_MODEL_REVISION", model_name),
        deployment_id=env.get("NEX_MO_VLLM_DEPLOYMENT_ID", "vllm-generation-http"),
        api_key_env="NEX_MO_VLLM_API_KEY",
        api_key=_empty_to_none(env.get("NEX_MO_VLLM_API_KEY")),
        timeout_seconds=_timeout_seconds(env, "generation"),
        timeout_env=VLLM_TIMEOUT_ENV,
        timeout_fallback_env=LEGACY_LIVE_TIMEOUT_ENV,
    )


def list_remote_provider_telemetry(
    *,
    capability: str | None = None,
    environ: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    configs = [
        build_remote_embedding_execution_config(environ),
        build_remote_reranker_execution_config(environ),
        build_remote_generation_execution_config(environ),
    ]
    return list_provider_telemetry(configs, capability=capability)


def execute_remote_embedding_request(
    payload: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    _reject_raw_provider_fields(payload)
    alias = _string_field(payload, "alias", "mock-embedding-default")
    inputs = _string_list_field(payload, "inputs")
    config = build_remote_embedding_execution_config(environ)
    if not config.configured:
        raise ProviderRouteError(
            status_code=503,
            error_code="mo.remote_embedding_not_configured",
            detail="Remote embedding provider endpoint is not configured.",
            retryable=True,
        )

    def operation() -> dict[str, Any]:
        response_payload = _execute_remote_request_with_retry(
            config,
            json_payload=_remote_embedding_request_payload(config, inputs),
            requester=requester,
            error_code_prefix="mo.remote_embedding",
            environ=environ,
        )
        return normalize_remote_embedding_response(
            provider_payload=response_payload,
            alias=alias,
            config=config,
            input_count=len(inputs),
            input_texts=inputs,
        )

    return _recorded_remote_provider_call(config, operation)


def execute_remote_generation_request(
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str,
    environ: dict[str, str] | None = None,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    _reject_raw_provider_fields(payload)
    alias = _string_field(payload, "alias", "general-llm-default")
    provider_capability = _string_field(payload, "provider_capability", "generation")
    route = resolve_provider_route(alias, provider_capability)
    max_output_tokens = _max_output_tokens(payload, route.max_output_tokens)
    if _bool_field(payload, "stream", False):
        raise ProviderRouteError(
            status_code=422,
            error_code="mo.remote_generation_streaming_unsupported",
            detail="Remote generation streaming is not supported by this adapter.",
        )

    config = build_remote_generation_execution_config(environ)
    if not config.configured:
        raise ProviderRouteError(
            status_code=503,
            error_code="mo.remote_generation_not_configured",
            detail="Remote generation provider endpoint is not configured.",
            retryable=True,
        )

    def operation() -> dict[str, Any]:
        response_payload = _execute_remote_request_with_retry(
            config,
            json_payload=_chat_completion_request_payload(
                payload,
                model_name=config.model_name,
                max_output_tokens=max_output_tokens,
            ),
            requester=requester,
            error_code_prefix="mo.remote_generation",
            environ=environ,
        )
        return normalize_remote_generation_response(
            provider_payload=response_payload,
            alias=alias,
            route_id=route.route_id,
            config=config,
            request_id=request_id,
            trace_id=payload.get("trace_id", trace_id),
            input_texts=_message_texts_from_payload(payload),
        )

    return _recorded_remote_provider_call(config, operation)


def execute_remote_rerank_request(
    payload: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    _reject_raw_provider_fields(payload)
    alias = _string_field(payload, "alias", "mock-reranker-default")
    query = _string_field(payload, "query")
    documents = _string_list_field(payload, "documents")
    top_n = _top_n(payload, default=len(documents))
    config = build_remote_reranker_execution_config(environ)
    if not config.configured:
        raise ProviderRouteError(
            status_code=503,
            error_code="mo.remote_reranker_not_configured",
            detail="Remote reranker provider endpoint is not configured.",
            retryable=True,
        )

    def operation() -> dict[str, Any]:
        response_payload = _execute_remote_request_with_retry(
            config,
            json_payload=_remote_rerank_request_payload(config, query, documents, top_n),
            requester=requester,
            error_code_prefix="mo.remote_reranker",
            environ=environ,
        )
        return normalize_remote_rerank_response(
            provider_payload=response_payload,
            alias=alias,
            config=config,
            documents=documents,
            query=query,
        )

    return _recorded_remote_provider_call(config, operation)


def validate_preflight_response(
    config: RemoteProviderPreflightConfig,
    payload: Any,
) -> dict[str, Any]:
    if config.request_shape == OPENAI_EMBEDDINGS_SHAPE:
        return _validate_embedding_response(payload, validated_shape=config.request_shape)
    if config.request_shape == NEX_PCX_EMBEDDINGS_SHAPE:
        return _validate_embedding_response(payload, validated_shape=config.request_shape)
    if config.request_shape == GENERIC_RERANK_SHAPE:
        return _validate_rerank_response(payload, validated_shape=config.request_shape)
    if config.request_shape == NEX_PCX_RERANK_SHAPE:
        return _validate_rerank_response(payload, validated_shape=config.request_shape)
    if config.request_shape == OPENAI_MODELS_SHAPE:
        return _validate_openai_models_response(config.expected_models, payload)
    raise RemoteProviderPreflightError("unsupported_request_shape")


def _execute_remote_request_with_retry(
    config: RemoteProviderExecutionConfig,
    *,
    json_payload: dict[str, Any],
    requester: HttpRequester | None,
    error_code_prefix: str,
    environ: dict[str, str] | None,
) -> Any:
    kwargs: dict[str, Any] = {}
    if requester is not None:
        kwargs["sleeper"] = lambda _: None
    kwargs["on_retry"] = lambda event: record_provider_retry(config, event)
    return execute_remote_json_request_with_retry(
        config,
        json_payload=json_payload,
        requester=requester,
        error_code_prefix=error_code_prefix,
        retry_policy=build_provider_retry_policy(config.capability, environ),
        **kwargs,
    )


def expected_models_from_env(
    value: str | None,
    defaults: tuple[str, ...],
) -> tuple[str, ...]:
    if not value:
        return defaults
    parsed = tuple(item.strip() for item in value.split(",") if item.strip())
    return parsed or defaults


def selected_generation_model_names(env: dict[str, str]) -> tuple[str, ...]:
    selected_profile = env.get("NEX_MO_GENERATION_PROFILE", DEFAULT_GENERATION_PROFILE)
    selected = [
        profile.model_name
        for profile in build_model_profile_catalog(env)
        if profile.provider_capability == "generation"
        and profile.selected
        and profile.profile_name == selected_profile
    ]
    return tuple(selected) or (selected_profile,)


def _remote_embedding_request_payload(
    config: RemoteProviderExecutionConfig,
    inputs: list[str],
) -> dict[str, Any]:
    if config.request_shape == OPENAI_EMBEDDINGS_SHAPE:
        return {
            "model": config.model_name,
            "input": inputs,
        }
    if config.request_shape == NEX_PCX_EMBEDDINGS_SHAPE:
        return _nex_pcx_embedding_request_payload(config, texts=inputs)
    raise ProviderRouteError(
        500,
        "mo.remote_embedding_request_shape_unsupported",
        "Remote embedding request shape is unsupported.",
    )


def _remote_rerank_request_payload(
    config: RemoteProviderExecutionConfig,
    query: str,
    documents: list[str],
    top_n: int,
) -> dict[str, Any]:
    if config.request_shape == GENERIC_RERANK_SHAPE:
        return {
            "model": config.model_name,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        }
    if config.request_shape == NEX_PCX_RERANK_SHAPE:
        return _nex_pcx_rerank_request_payload(
            config,
            query=query,
            documents=documents,
            top_n=top_n,
        )
    raise ProviderRouteError(
        500,
        "mo.remote_reranker_request_shape_unsupported",
        "Remote reranker request shape is unsupported.",
    )


def _nex_pcx_embedding_request_payload(
    config: RemoteProviderPreflightConfig | RemoteProviderExecutionConfig,
    *,
    texts: list[str],
) -> dict[str, Any]:
    options = config.request_options
    return {
        "profile_name": str(options["profile_name"]),
        "model_key": str(options["model_key"]),
        "input_type": str(options["input_type"]),
        "texts": texts,
        "output_dimension": int(options["output_dimension"]),
        "normalize_embeddings": bool(options["normalize_embeddings"]),
    }


def _nex_pcx_rerank_request_payload(
    config: RemoteProviderPreflightConfig | RemoteProviderExecutionConfig,
    *,
    query: str,
    documents: list[str],
    top_n: int,
) -> dict[str, Any]:
    options = config.request_options
    return {
        "query_text": query,
        "top_k": top_n,
        "reranker_profile_name": str(options["reranker_profile_name"]),
        "reranker_model_id": str(options["reranker_model_id"]),
        "candidates": [
            {
                "candidate_key": f"doc-{index + 1}",
                "rank": index + 1,
                "text": document,
                "source_profile_name": str(options["source_profile_name"]),
                "source_retrieval_strategy": str(
                    options["source_retrieval_strategy"]
                ),
                "source_score": float(options["source_score"]),
            }
            for index, document in enumerate(documents)
        ],
    }


def _embedding_response_items(payload: dict[str, Any]) -> Any:
    data = payload.get("data")
    if isinstance(data, list):
        return data
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list):
        return [{"embedding": embedding} for embedding in embeddings]
    return data


def _validate_embedding_response(
    payload: Any,
    *,
    validated_shape: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RemoteProviderPreflightError("response_not_json_object")
    data = _embedding_response_items(payload)
    if not isinstance(data, list) or not data:
        raise RemoteProviderPreflightError("embedding_data_missing")
    first_item = data[0]
    if not isinstance(first_item, dict) or not isinstance(first_item.get("embedding"), list):
        raise RemoteProviderPreflightError("embedding_vector_missing")
    return {
        "response_observed": True,
        "validated_shape": validated_shape,
        "observed_items": len(data),
    }


def _validate_rerank_response(
    payload: Any,
    *,
    validated_shape: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RemoteProviderPreflightError("response_not_json_object")
    results = payload.get("results", payload.get("data"))
    if not isinstance(results, list) or not results:
        raise RemoteProviderPreflightError("rerank_results_missing")
    first_item = results[0]
    if not isinstance(first_item, dict):
        raise RemoteProviderPreflightError("rerank_result_invalid")
    if not any(key in first_item for key in ("score", "relevance_score")):
        raise RemoteProviderPreflightError("rerank_score_missing")
    return {
        "response_observed": True,
        "validated_shape": validated_shape,
        "observed_items": len(results),
    }


def _validate_openai_models_response(
    expected_models: tuple[str, ...],
    payload: Any,
) -> dict[str, Any]:
    observed_models = _extract_model_ids(payload)
    if not observed_models:
        raise RemoteProviderPreflightError("model_list_missing")
    missing_models = [
        model_name for model_name in expected_models if model_name not in observed_models
    ]
    if missing_models:
        return {
            "status": "FAIL",
            "failure_code": "expected_model_missing",
            "missing_expected_models": missing_models,
            "observed_model_count": len(observed_models),
        }
    return {
        "response_observed": True,
        "validated_shape": "openai_models",
        "observed_model_count": len(observed_models),
    }


def _extract_model_ids(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()

    raw_models = payload.get("data", payload.get("models"))
    if not isinstance(raw_models, list):
        return ()

    model_ids: list[str] = []
    for item in raw_models:
        if isinstance(item, str):
            model_ids.append(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            model_ids.append(item["id"])
    return tuple(model_ids)


def _embedding_request_options(env: dict[str, str]) -> dict[str, Any]:
    return {
        "profile_name": _env_or_default(
            env,
            "NEX_MO_REMOTE_EMBEDDING_PROFILE_NAME",
            "qwen3_4b_2560",
        ),
        "model_key": _env_or_default(
            env,
            "NEX_MO_REMOTE_EMBEDDING_MODEL_KEY",
            "qwen3_embedding_4b",
        ),
        "input_type": _env_or_default(
            env,
            "NEX_MO_REMOTE_EMBEDDING_INPUT_TYPE",
            "document",
        ),
        "output_dimension": _int_env(
            env,
            "NEX_MO_REMOTE_EMBEDDING_OUTPUT_DIMENSION",
            2560,
        ),
        "normalize_embeddings": _bool_env(
            env,
            "NEX_MO_REMOTE_EMBEDDING_NORMALIZE",
            True,
        ),
    }


def _reranker_request_options(env: dict[str, str]) -> dict[str, Any]:
    return {
        "reranker_profile_name": _env_or_default(
            env,
            "NEX_MO_REMOTE_RERANKER_PROFILE_NAME",
            "qwen3_reranker_0_6b",
        ),
        "reranker_model_id": _env_or_default(
            env,
            "NEX_MO_REMOTE_RERANKER_MODEL_ID",
            "Qwen/Qwen3-Reranker-0.6B",
        ),
        "source_profile_name": _env_or_default(
            env,
            "NEX_MO_REMOTE_RERANKER_SOURCE_PROFILE_NAME",
            "qwen3_4b_2560",
        ),
        "source_retrieval_strategy": _env_or_default(
            env,
            "NEX_MO_REMOTE_RERANKER_SOURCE_RETRIEVAL_STRATEGY",
            "preflight",
        ),
        "source_score": _float_env(
            env,
            "NEX_MO_REMOTE_RERANKER_SOURCE_SCORE",
            0.5,
        ),
    }


def _safe_request_options(options: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in options.items()
        if key
        in {
            "profile_name",
            "model_key",
            "input_type",
            "output_dimension",
            "normalize_embeddings",
            "reranker_profile_name",
            "reranker_model_id",
            "source_profile_name",
            "source_retrieval_strategy",
            "source_score",
        }
    }


def _request_shape_uses_pcx_options(request_shape: str) -> bool:
    return request_shape in {NEX_PCX_EMBEDDINGS_SHAPE, NEX_PCX_RERANK_SHAPE}


def _env_or_default(env: dict[str, str], key: str, default: str) -> str:
    return env.get(key) or default


def _int_env(env: dict[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _float_env(env: dict[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or value == "":
        return default
    return float(value)


def _bool_env(env: dict[str, str], key: str, default: bool) -> bool:
    value = env.get(key)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean value.")


def _remote_provider_response_invalid(
    *,
    error_code_prefix: str,
    detail: str,
) -> ProviderRouteError:
    return remote_provider_response_invalid_decision(
        error_code_prefix=error_code_prefix,
        detail=detail,
    ).to_route_error()


def _selected_profile(env: dict[str, str], capability: str):
    profiles = [
        profile
        for profile in build_model_profile_catalog(env)
        if profile.provider_capability == capability and profile.selected
    ]
    if profiles:
        return profiles[0]
    return [
        profile
        for profile in build_model_profile_catalog(env)
        if profile.provider_capability == capability
    ][0]


def _reject_raw_provider_fields(payload: dict[str, Any]) -> None:
    forbidden = {"provider_url", "model_path", "provider_endpoint", "api_key"}
    leaked = sorted(forbidden & set(payload))
    if leaked:
        raise ProviderRouteError(
            422,
            "mo.provider_field_forbidden",
            f"Provider-private field is not allowed: {leaked[0]}",
        )


def _string_field(
    payload: dict[str, Any],
    key: str,
    default: str | None = None,
) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value:
        raise ProviderRouteError(400, "mo.request_invalid", f"{key} is required.")
    return value


def _string_list_field(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ProviderRouteError(
            400,
            "mo.request_invalid",
            f"{key} must be a non-empty list of strings.",
        )
    return value


def _top_n(payload: dict[str, Any], *, default: int) -> int:
    value = payload.get("top_n", default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderRouteError(
            400,
            "mo.request_invalid",
            "top_n must be a positive integer when provided.",
        )
    return min(value, default)


def _max_output_tokens(payload: dict[str, Any], route_limit: int) -> int:
    value = payload.get("max_output_tokens", 256)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderRouteError(
            400,
            "mo.request_invalid",
            "max_output_tokens must be a positive integer.",
        )
    if value > route_limit:
        raise ProviderRouteError(
            422,
            "mo.generation_parameter_out_of_bounds",
            f"max_output_tokens must be <= {route_limit}.",
        )
    return value


def _bool_field(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    raise ProviderRouteError(
        400,
        "mo.request_invalid",
        f"{key} must be a boolean when provided.",
    )


def _chat_completion_request_payload(
    payload: dict[str, Any],
    *,
    model_name: str,
    max_output_tokens: int,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "model": model_name,
        "messages": _chat_messages_from_payload(payload),
        "temperature": _temperature(payload),
        "max_tokens": max_output_tokens,
        "stream": False,
    }
    reasoning_mode = _reasoning_mode(payload)
    if reasoning_mode != "provider_default":
        request_payload["chat_template_kwargs"] = {
            "enable_thinking": reasoning_mode == "enabled"
        }
    response_format = payload.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") == "json_object":
        request_payload["response_format"] = {"type": "json_object"}
    return request_payload


def _reasoning_mode(payload: dict[str, Any]) -> str:
    value = payload.get("reasoning_mode", "provider_default")
    if value not in {"provider_default", "enabled", "disabled"}:
        raise ProviderRouteError(
            400,
            "mo.request_invalid",
            "reasoning_mode must be provider_default, enabled, or disabled.",
        )
    return str(value)


def _chat_messages_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        normalized_messages: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, dict):
                raise ProviderRouteError(
                    400,
                    "mo.request_invalid",
                    "messages must contain objects.",
                )
            role = message.get("role", "user")
            content = message.get("content")
            if not isinstance(role, str) or not role:
                raise ProviderRouteError(400, "mo.request_invalid", "message.role is required.")
            if not isinstance(content, str) or not content:
                raise ProviderRouteError(
                    400,
                    "mo.request_invalid",
                    "message.content is required.",
                )
            normalized_messages.append({"role": role, "content": content})
        return normalized_messages

    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt:
        return [{"role": "user", "content": prompt}]

    raise ProviderRouteError(
        400,
        "mo.request_invalid",
        "prompt or messages are required.",
    )


def _message_texts_from_payload(payload: dict[str, Any]) -> list[str]:
    return [message["content"] for message in _chat_messages_from_payload(payload)]


def _temperature(payload: dict[str, Any]) -> float:
    value = payload.get("temperature", 0.0)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise ProviderRouteError(
        400,
        "mo.request_invalid",
        "temperature must be numeric when provided.",
    )


def _token_count(text: str) -> int:
    return max(1, len(text.split()))


def _timeout_seconds(env: dict[str, str], capability: str) -> float:
    timeout_env = _timeout_env_for_capability(capability)
    default = _default_timeout_for_capability(capability)
    if env.get(timeout_env) not in {None, ""}:
        return _positive_float_env(env, timeout_env, default)
    return _positive_float_env(env, LEGACY_LIVE_TIMEOUT_ENV, default)


def _timeout_env_for_capability(capability: str) -> str:
    if capability == "embedding":
        return REMOTE_EMBEDDING_TIMEOUT_ENV
    if capability == "reranking":
        return REMOTE_RERANKER_TIMEOUT_ENV
    if capability == "generation":
        return VLLM_TIMEOUT_ENV
    raise ValueError(f"Unsupported remote provider capability: {capability}")


def _default_timeout_for_capability(capability: str) -> float:
    if capability == "embedding":
        return DEFAULT_REMOTE_EMBEDDING_TIMEOUT_SECONDS
    if capability == "reranking":
        return DEFAULT_REMOTE_RERANKER_TIMEOUT_SECONDS
    if capability == "generation":
        return DEFAULT_REMOTE_GENERATION_TIMEOUT_SECONDS
    raise ValueError(f"Unsupported remote provider capability: {capability}")


def _positive_float_env(
    env: dict[str, str],
    key: str,
    default: float,
) -> float:
    raw_value = env.get(key)
    if raw_value is None or raw_value == "":
        return default
    value = float(raw_value)
    if value <= 0:
        raise ValueError(f"{key} must be positive.")
    return value


def _env_first(env: dict[str, str], primary: str, legacy: str) -> str:
    return env.get(primary) or env.get(legacy, "")


def _vllm_models_url(env: dict[str, str]) -> str:
    if env.get("NEX_MO_VLLM_MODELS_URL"):
        return env["NEX_MO_VLLM_MODELS_URL"]
    if env.get("NEX_MO_VLLM_BASE_URL"):
        return f"{env['NEX_MO_VLLM_BASE_URL'].rstrip('/')}/v1/models"
    return env.get("NEX_MO_LIVE_VLLM_MODELS_URL", "")


def _vllm_chat_completions_url(env: dict[str, str]) -> str:
    if env.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL"):
        return env["NEX_MO_VLLM_CHAT_COMPLETIONS_URL"]
    if env.get("NEX_MO_VLLM_BASE_URL"):
        return f"{env['NEX_MO_VLLM_BASE_URL'].rstrip('/')}/v1/chat/completions"
    return ""


def _empty_to_none(value: str | None) -> str | None:
    return value or None


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, RemoteProviderPreflightError):
        return exc.failure_code
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return exc.__class__.__name__
