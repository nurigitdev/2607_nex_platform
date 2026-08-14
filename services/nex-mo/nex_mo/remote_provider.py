from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

import httpx

from nex_mo.providers import (
    DEFAULT_GENERATION_PROFILE,
    ProviderRouteError,
    build_model_profile_catalog,
    resolve_provider_route,
)

DEFAULT_TIMEOUT_SECONDS = 5.0
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
        }
        if _request_shape_uses_pcx_options(self.request_shape):
            safe_options = _safe_request_options(self.request_options)
            if safe_options:
                payload["request_options"] = safe_options
        return payload


@dataclass(frozen=True)
class RemoteProviderFailureDecision:
    failure_kind: str
    error_code: str
    status_code: int
    detail: str
    retryable: bool
    degraded: bool
    upstream_status_code: int | None = None

    def to_route_error(self) -> ProviderRouteError:
        return ProviderRouteError(
            status_code=self.status_code,
            error_code=self.error_code,
            detail=self.detail,
            retryable=self.retryable,
            degraded=self.degraded,
            failure_kind=self.failure_kind,
            upstream_status_code=self.upstream_status_code,
        )

    def to_safe_summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "failure_kind": self.failure_kind,
            "error_code": self.error_code,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "degraded": self.degraded,
        }
        if self.upstream_status_code is not None:
            payload["upstream_status_code"] = self.upstream_status_code
        return payload


class RemoteProviderPreflightError(Exception):
    def __init__(self, failure_code: str) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code


@dataclass
class RemoteProviderTelemetryBucket:
    capability: str
    endpoint_env: str
    configured: bool
    request_shape: str
    model_name: str
    model_revision: str
    deployment_id: str
    authorization_env: str | None
    authorization_configured: bool
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    retryable_failure_count: int = 0
    degraded_count: int = 0
    last_outcome: str | None = None
    last_observed_at: str | None = None
    last_latency_ms: int | None = None
    last_status_code: int | None = None
    last_error_code: str | None = None
    last_failure_kind: str | None = None
    last_upstream_status_code: int | None = None

    @classmethod
    def from_config(
        cls,
        config: RemoteProviderExecutionConfig,
    ) -> RemoteProviderTelemetryBucket:
        return cls(
            capability=config.capability,
            endpoint_env=config.endpoint_env,
            configured=config.configured,
            request_shape=config.request_shape,
            model_name=config.model_name,
            model_revision=config.model_revision,
            deployment_id=config.deployment_id,
            authorization_env=config.api_key_env,
            authorization_configured=bool(config.api_key),
        )

    def record_success(self, *, latency_ms: int, observed_at: str) -> None:
        self.request_count += 1
        self.success_count += 1
        self.last_outcome = "success"
        self.last_observed_at = observed_at
        self.last_latency_ms = latency_ms
        self.last_status_code = 200
        self.last_error_code = None
        self.last_failure_kind = None
        self.last_upstream_status_code = None

    def record_failure(
        self,
        *,
        route_error: ProviderRouteError,
        latency_ms: int,
        observed_at: str,
    ) -> None:
        self.request_count += 1
        self.failure_count += 1
        if route_error.retryable:
            self.retryable_failure_count += 1
        if route_error.degraded:
            self.degraded_count += 1
        self.last_outcome = "failure"
        self.last_observed_at = observed_at
        self.last_latency_ms = latency_ms
        self.last_status_code = route_error.status_code
        self.last_error_code = route_error.error_code
        self.last_failure_kind = route_error.failure_kind or "provider_route_error"
        self.last_upstream_status_code = route_error.upstream_status_code

    def to_wire(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "endpoint_env": self.endpoint_env,
            "configured": self.configured,
            "request_shape": self.request_shape,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "deployment_id": self.deployment_id,
            "authorization_env": self.authorization_env,
            "authorization_configured": self.authorization_configured,
            "request_count": self.request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "retryable_failure_count": self.retryable_failure_count,
            "degraded_count": self.degraded_count,
            "last_outcome": self.last_outcome,
            "last_observed_at": self.last_observed_at,
            "last_latency_ms": self.last_latency_ms,
            "last_status_code": self.last_status_code,
            "last_error_code": self.last_error_code,
            "last_failure_kind": self.last_failure_kind,
            "last_upstream_status_code": self.last_upstream_status_code,
        }


HttpRequester = Callable[..., httpx.Response]
_TELEMETRY_LOCK = Lock()
_TELEMETRY_BUCKETS: dict[str, RemoteProviderTelemetryBucket] = {}


def build_remote_provider_preflight_configs(
    environ: dict[str, str] | None = None,
) -> tuple[RemoteProviderPreflightConfig, ...]:
    env = environ if environ is not None else os.environ
    timeout_seconds = _timeout_seconds(env)

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
                ("Qwen3-embedding-4B",),
            ),
            api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
            api_key=_empty_to_none(env.get("NEX_MO_REMOTE_EMBEDDING_API_KEY")),
            timeout_seconds=timeout_seconds,
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
                ("Qwen3-Reranker-0.6B",),
            ),
            api_key_env="NEX_MO_REMOTE_RERANKER_API_KEY",
            api_key=_empty_to_none(env.get("NEX_MO_REMOTE_RERANKER_API_KEY")),
            timeout_seconds=timeout_seconds,
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
            timeout_seconds=timeout_seconds,
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
        timeout_seconds=_timeout_seconds(env),
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
        timeout_seconds=_timeout_seconds(env),
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
        timeout_seconds=_timeout_seconds(env),
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
    configured_buckets = {
        _telemetry_key(config): RemoteProviderTelemetryBucket.from_config(config)
        for config in configs
    }
    with _TELEMETRY_LOCK:
        buckets = {
            **configured_buckets,
            **_TELEMETRY_BUCKETS,
        }
        wire_items = [bucket.to_wire() for bucket in buckets.values()]

    if capability is not None:
        wire_items = [
            item for item in wire_items if item["capability"] == capability
        ]
    return sorted(
        wire_items,
        key=lambda item: (str(item["capability"]), str(item["deployment_id"])),
    )


def reset_remote_provider_telemetry() -> None:
    with _TELEMETRY_LOCK:
        _TELEMETRY_BUCKETS.clear()


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
        response_payload = _execute_remote_json_request(
            config,
            json_payload=_remote_embedding_request_payload(config, inputs),
            requester=requester,
            error_code_prefix="mo.remote_embedding",
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
        response_payload = _execute_remote_json_request(
            config,
            json_payload=_chat_completion_request_payload(
                payload,
                model_name=config.model_name,
                max_output_tokens=max_output_tokens,
            ),
            requester=requester,
            error_code_prefix="mo.remote_generation",
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
        response_payload = _execute_remote_json_request(
            config,
            json_payload=_remote_rerank_request_payload(config, query, documents, top_n),
            requester=requester,
            error_code_prefix="mo.remote_reranker",
        )
        return normalize_remote_rerank_response(
            provider_payload=response_payload,
            alias=alias,
            config=config,
            documents=documents,
            query=query,
        )

    return _recorded_remote_provider_call(config, operation)


def normalize_remote_generation_response(
    *,
    provider_payload: Any,
    alias: str,
    route_id: str,
    config: RemoteProviderExecutionConfig,
    request_id: str,
    trace_id: str,
    input_texts: list[str],
) -> dict[str, Any]:
    if not isinstance(provider_payload, dict):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation response must be a JSON object.",
        )
    choices = provider_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation response must include non-empty choices.",
        )
    first_choice = choices[0]
    output_text = _choice_output_text(first_choice)
    finish_reason = _finish_reason_from_choice(first_choice)
    provider_request_id = provider_payload.get("id")
    if not isinstance(provider_request_id, str) or not provider_request_id:
        provider_request_id = str(
            uuid5(
                NAMESPACE_URL,
                _stable_json(
                    {
                        "alias": alias,
                        "trace_id": trace_id,
                        "output_text": output_text,
                    }
                ),
            )
        )
    now = _utc_now()
    return {
        "mo_generation_id": provider_request_id,
        "alias": alias,
        "model_revision": config.model_revision,
        "deployment_id": config.deployment_id,
        "provider_type": "vllm",
        "output": {
            "type": "text",
            "text": output_text,
        },
        "finish_reason": finish_reason,
        "usage": _normalize_usage(provider_payload.get("usage"), input_texts),
        "runtime_metadata": {
            "request_id": request_id,
            "trace_id": trace_id,
            "queue_ms": 0,
            "provider_ms": 0,
            "total_ms": 0,
            "route_id": route_id,
            "admission_decision": "ACCEPTED",
            "provider_request_id": provider_request_id,
        },
        "created_at": now,
        "updated_at": now,
    }


def normalize_remote_embedding_response(
    *,
    provider_payload: Any,
    alias: str,
    config: RemoteProviderExecutionConfig,
    input_count: int,
    input_texts: list[str],
) -> dict[str, Any]:
    if not isinstance(provider_payload, dict):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_embedding",
            detail="Remote embedding response must be a JSON object.",
        )
    response_items = _embedding_response_items(provider_payload)
    if not isinstance(response_items, list) or len(response_items) != input_count:
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_embedding",
            detail="Remote embedding response count did not match request count.",
        )

    normalized_items = [
        {
            "object": "embedding",
            "index": _embedding_item_index(item, index),
            "embedding": _embedding_vector_from_item(item),
        }
        for index, item in enumerate(response_items)
    ]
    return {
        "object": provider_payload.get("object", "list"),
        "alias": alias,
        "model_revision": config.model_revision,
        "deployment_id": config.deployment_id,
        "data": normalized_items,
        "usage": _normalize_usage(provider_payload.get("usage"), input_texts),
    }


def normalize_remote_rerank_response(
    *,
    provider_payload: Any,
    alias: str,
    config: RemoteProviderExecutionConfig,
    documents: list[str],
    query: str,
) -> dict[str, Any]:
    if not isinstance(provider_payload, dict):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker response must be a JSON object.",
        )
    response_items = provider_payload.get("results", provider_payload.get("data"))
    if not isinstance(response_items, list) or not response_items:
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker response must include non-empty results.",
        )

    normalized_items = [
        _normalize_rerank_item(item, rank=index, documents=documents)
        for index, item in enumerate(response_items)
    ]
    normalized_items = sorted(
        normalized_items,
        key=lambda item: item["score"],
        reverse=True,
    )
    return {
        "alias": alias,
        "model_revision": config.model_revision,
        "deployment_id": config.deployment_id,
        "results": normalized_items,
        "usage": _normalize_usage(provider_payload.get("usage"), [query, *documents]),
    }


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


def _recorded_remote_provider_call(
    config: RemoteProviderExecutionConfig,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    started_at = perf_counter()
    try:
        result = operation()
    except ProviderRouteError as exc:
        _record_remote_provider_failure(
            config,
            route_error=exc,
            latency_ms=_elapsed_ms(started_at),
        )
        raise
    _record_remote_provider_success(config, latency_ms=_elapsed_ms(started_at))
    return result


def _record_remote_provider_success(
    config: RemoteProviderExecutionConfig,
    *,
    latency_ms: int,
) -> None:
    with _TELEMETRY_LOCK:
        _telemetry_bucket(config).record_success(
            latency_ms=latency_ms,
            observed_at=_utc_now(),
        )


def _record_remote_provider_failure(
    config: RemoteProviderExecutionConfig,
    *,
    route_error: ProviderRouteError,
    latency_ms: int,
) -> None:
    with _TELEMETRY_LOCK:
        _telemetry_bucket(config).record_failure(
            route_error=route_error,
            latency_ms=latency_ms,
            observed_at=_utc_now(),
        )


def _telemetry_bucket(
    config: RemoteProviderExecutionConfig,
) -> RemoteProviderTelemetryBucket:
    key = _telemetry_key(config)
    if key not in _TELEMETRY_BUCKETS:
        _TELEMETRY_BUCKETS[key] = RemoteProviderTelemetryBucket.from_config(config)
    return _TELEMETRY_BUCKETS[key]


def _telemetry_key(config: RemoteProviderExecutionConfig) -> str:
    return "|".join(
        (
            config.capability,
            config.request_shape,
            config.deployment_id,
            config.model_revision,
        )
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((perf_counter() - started_at) * 1000)))


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


def _execute_remote_json_request(
    config: RemoteProviderExecutionConfig,
    *,
    json_payload: dict[str, Any],
    requester: HttpRequester | None,
    error_code_prefix: str,
) -> Any:
    selected_requester = requester or httpx.request
    try:
        response = selected_requester(
            config.method,
            config.url,
            headers=config.headers(),
            json=json_payload,
            timeout=config.timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise classify_remote_provider_exception(
            exc,
            error_code_prefix=error_code_prefix,
        ).to_route_error() from exc
    except httpx.HTTPError as exc:
        raise classify_remote_provider_exception(
            exc,
            error_code_prefix=error_code_prefix,
        ).to_route_error() from exc

    if response.is_error:
        raise classify_remote_provider_http_status(
            response.status_code,
            error_code_prefix=error_code_prefix,
        ).to_route_error()
    try:
        return response.json()
    except ValueError as exc:
        raise remote_provider_response_invalid_decision(
            error_code_prefix=error_code_prefix,
            detail="Remote provider response was not valid JSON.",
        ).to_route_error() from exc


def classify_remote_provider_exception(
    exc: httpx.HTTPError,
    *,
    error_code_prefix: str,
) -> RemoteProviderFailureDecision:
    if isinstance(exc, httpx.TimeoutException):
        return RemoteProviderFailureDecision(
            failure_kind="timeout",
            error_code=f"{error_code_prefix}_timeout",
            status_code=504,
            detail="Remote provider request timed out.",
            retryable=True,
            degraded=True,
        )
    return RemoteProviderFailureDecision(
        failure_kind="connection_error",
        error_code=f"{error_code_prefix}_unavailable",
        status_code=503,
        detail="Remote provider request failed before a valid response was received.",
        retryable=True,
        degraded=True,
    )


def classify_remote_provider_http_status(
    status_code: int,
    *,
    error_code_prefix: str,
) -> RemoteProviderFailureDecision:
    if status_code == 429:
        return RemoteProviderFailureDecision(
            failure_kind="throttled",
            error_code=f"{error_code_prefix}_throttled",
            status_code=429,
            detail="Remote provider throttled the request.",
            retryable=True,
            degraded=True,
            upstream_status_code=status_code,
        )
    if status_code >= 500:
        return RemoteProviderFailureDecision(
            failure_kind="upstream_5xx",
            error_code=f"{error_code_prefix}_http_error",
            status_code=503,
            detail=f"Remote provider returned HTTP {status_code}.",
            retryable=True,
            degraded=True,
            upstream_status_code=status_code,
        )
    return RemoteProviderFailureDecision(
        failure_kind="upstream_4xx",
        error_code=f"{error_code_prefix}_http_error",
        status_code=502,
        detail=f"Remote provider returned HTTP {status_code}.",
        retryable=False,
        degraded=False,
        upstream_status_code=status_code,
    )


def remote_provider_response_invalid_decision(
    *,
    error_code_prefix: str,
    detail: str,
) -> RemoteProviderFailureDecision:
    return RemoteProviderFailureDecision(
        failure_kind="malformed_response",
        error_code=f"{error_code_prefix}_response_invalid",
        status_code=502,
        detail=detail,
        retryable=True,
        degraded=True,
    )


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
    response_format = payload.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") == "json_object":
        request_payload["response_format"] = {"type": "json_object"}
    return request_payload


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


def _choice_output_text(choice: Any) -> str:
    if not isinstance(choice, dict):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation choice must be an object.",
        )
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else choice.get("text")
    if not isinstance(content, str) or not content:
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation output text was missing.",
        )
    return content


def _finish_reason_from_choice(choice: Any) -> str:
    if not isinstance(choice, dict):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation choice must be an object.",
        )
    raw_finish_reason = choice.get("finish_reason", "stop")
    if not isinstance(raw_finish_reason, str) or not raw_finish_reason:
        return "UNKNOWN"
    return {
        "stop": "STOP",
        "length": "LENGTH",
        "content_filter": "CONTENT_FILTER",
        "tool_calls": "TOOL_CALLS",
    }.get(raw_finish_reason, raw_finish_reason.upper())


def _embedding_item_index(item: Any, fallback: int) -> int:
    if isinstance(item, dict) and isinstance(item.get("index"), int):
        return item["index"]
    return fallback


def _embedding_vector_from_item(item: Any) -> list[float]:
    if not isinstance(item, dict):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_embedding",
            detail="Remote embedding item must be an object.",
        )
    vector = item.get("embedding")
    if not isinstance(vector, list) or not vector or not all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in vector
    ):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_embedding",
            detail="Remote embedding vector must be a non-empty numeric list.",
        )
    return [float(value) for value in vector]


def _normalize_rerank_item(
    item: Any,
    *,
    rank: int,
    documents: list[str],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker item must be an object.",
        )
    index = item.get("index", rank)
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker item index must be a non-negative integer.",
        )
    score = _rerank_score_from_item(item)
    document = _rerank_document_from_item(item, index=index, documents=documents)
    return {
        "index": index,
        "score": score,
        "document": document,
    }


def _rerank_score_from_item(item: dict[str, Any]) -> float:
    value = item.get("score", item.get("relevance_score"))
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise _remote_provider_response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker score must be numeric.",
        )
    return round(float(value), 6)


def _rerank_document_from_item(
    item: dict[str, Any],
    *,
    index: int,
    documents: list[str],
) -> str:
    document = item.get("document")
    if isinstance(document, str):
        return document
    if isinstance(document, dict) and isinstance(document.get("text"), str):
        return document["text"]
    return documents[index] if index < len(documents) else ""


def _normalize_usage(value: Any, input_texts: list[str]) -> dict[str, int]:
    usage = value if isinstance(value, dict) else {}
    input_tokens = _int_usage_value(
        usage,
        "input_tokens",
        "prompt_tokens",
        default=sum(_token_count(text) for text in input_texts),
    )
    output_tokens = _int_usage_value(
        usage,
        "output_tokens",
        "completion_tokens",
        default=0,
    )
    total_tokens = _int_usage_value(
        usage,
        "total_tokens",
        default=input_tokens + output_tokens,
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _int_usage_value(
    usage: dict[str, Any],
    key: str,
    fallback_key: str | None = None,
    *,
    default: int,
) -> int:
    value = usage.get(key)
    if value is None and fallback_key is not None:
        value = usage.get(fallback_key)
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return default


def _token_count(text: str) -> int:
    return max(1, len(text.split()))


def _timeout_seconds(env: dict[str, str]) -> float:
    return _positive_float_env(
        env,
        "NEX_MO_LIVE_TIMEOUT_SECONDS",
        DEFAULT_TIMEOUT_SECONDS,
    )


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


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
