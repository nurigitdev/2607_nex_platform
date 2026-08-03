from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from nex_mo.providers import (
    DEFAULT_GENERATION_PROFILE,
    ProviderRouteError,
    build_model_profile_catalog,
)

DEFAULT_TIMEOUT_SECONDS = 5.0
PREFLIGHT_TEXT = "nex live provider preflight"


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
        if self.request_shape == "openai_embeddings":
            return {
                "model": model_name,
                "input": [PREFLIGHT_TEXT],
            }
        if self.request_shape == "rerank":
            return {
                "model": model_name,
                "query": PREFLIGHT_TEXT,
                "documents": ["NeX live provider preflight document."],
                "top_n": 1,
            }
        if self.request_shape == "openai_models":
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
        return {
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


class RemoteProviderPreflightError(Exception):
    def __init__(self, failure_code: str) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code


HttpRequester = Callable[..., httpx.Response]


def build_remote_provider_preflight_configs(
    environ: dict[str, str] | None = None,
) -> tuple[RemoteProviderPreflightConfig, ...]:
    env = environ if environ is not None else os.environ
    timeout_seconds = float(env.get("NEX_MO_LIVE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))

    return (
        RemoteProviderPreflightConfig(
            capability="embedding",
            endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
            legacy_endpoint_env="NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
            url=_env_first(env, "NEX_MO_REMOTE_EMBEDDING_URL", "NEX_MO_LIVE_EMBEDDING_HEALTH_URL"),
            method="POST",
            request_shape="openai_embeddings",
            expected_models=expected_models_from_env(
                env.get("NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS"),
                ("Qwen3-embedding-4B",),
            ),
            api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
            api_key=_empty_to_none(env.get("NEX_MO_REMOTE_EMBEDDING_API_KEY")),
            timeout_seconds=timeout_seconds,
        ),
        RemoteProviderPreflightConfig(
            capability="reranking",
            endpoint_env="NEX_MO_REMOTE_RERANKER_URL",
            legacy_endpoint_env="NEX_MO_LIVE_RERANKER_HEALTH_URL",
            url=_env_first(env, "NEX_MO_REMOTE_RERANKER_URL", "NEX_MO_LIVE_RERANKER_HEALTH_URL"),
            method="POST",
            request_shape="rerank",
            expected_models=expected_models_from_env(
                env.get("NEX_MO_LIVE_EXPECTED_RERANKER_MODELS"),
                ("Qwen3-reranker-4B",),
            ),
            api_key_env="NEX_MO_REMOTE_RERANKER_API_KEY",
            api_key=_empty_to_none(env.get("NEX_MO_REMOTE_RERANKER_API_KEY")),
            timeout_seconds=timeout_seconds,
        ),
        RemoteProviderPreflightConfig(
            capability="generation",
            endpoint_env="NEX_MO_VLLM_MODELS_URL",
            legacy_endpoint_env="NEX_MO_LIVE_VLLM_MODELS_URL",
            url=_vllm_models_url(env),
            method="GET",
            request_shape="openai_models",
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
        request_shape="openai_embeddings",
        model_name=model_name,
        model_revision=env.get("NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION", model_name),
        deployment_id=env.get("NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID", "remote-embedding-http"),
        api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
        api_key=_empty_to_none(env.get("NEX_MO_REMOTE_EMBEDDING_API_KEY")),
        timeout_seconds=float(env.get("NEX_MO_LIVE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
    )


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

    response_payload = _execute_remote_json_request(
        config,
        json_payload={
            "model": config.model_name,
            "input": inputs,
        },
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


def normalize_remote_embedding_response(
    *,
    provider_payload: Any,
    alias: str,
    config: RemoteProviderExecutionConfig,
    input_count: int,
    input_texts: list[str],
) -> dict[str, Any]:
    if not isinstance(provider_payload, dict):
        raise ProviderRouteError(
            status_code=502,
            error_code="mo.remote_embedding_response_invalid",
            detail="Remote embedding response must be a JSON object.",
            retryable=True,
        )
    response_items = provider_payload.get("data")
    if not isinstance(response_items, list) or len(response_items) != input_count:
        raise ProviderRouteError(
            status_code=502,
            error_code="mo.remote_embedding_response_invalid",
            detail="Remote embedding response count did not match request count.",
            retryable=True,
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


def validate_preflight_response(
    config: RemoteProviderPreflightConfig,
    payload: Any,
) -> dict[str, Any]:
    if config.request_shape == "openai_embeddings":
        return _validate_embedding_response(payload)
    if config.request_shape == "rerank":
        return _validate_rerank_response(payload)
    if config.request_shape == "openai_models":
        return _validate_openai_models_response(config.expected_models, payload)
    raise RemoteProviderPreflightError("unsupported_request_shape")


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


def _validate_embedding_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RemoteProviderPreflightError("response_not_json_object")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise RemoteProviderPreflightError("embedding_data_missing")
    first_item = data[0]
    if not isinstance(first_item, dict) or not isinstance(first_item.get("embedding"), list):
        raise RemoteProviderPreflightError("embedding_vector_missing")
    return {
        "response_observed": True,
        "validated_shape": "openai_embeddings",
        "observed_items": len(data),
    }


def _validate_rerank_response(payload: Any) -> dict[str, Any]:
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
        "validated_shape": "rerank",
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
        raise ProviderRouteError(
            status_code=504,
            error_code=f"{error_code_prefix}_timeout",
            detail="Remote provider request timed out.",
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderRouteError(
            status_code=503,
            error_code=f"{error_code_prefix}_unavailable",
            detail="Remote provider request failed before a valid response was received.",
            retryable=True,
        ) from exc

    if response.is_error:
        retryable = response.status_code >= 500
        raise ProviderRouteError(
            status_code=502,
            error_code=f"{error_code_prefix}_http_error",
            detail=f"Remote provider returned HTTP {response.status_code}.",
            retryable=retryable,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderRouteError(
            status_code=502,
            error_code=f"{error_code_prefix}_response_invalid",
            detail="Remote provider response was not valid JSON.",
            retryable=True,
        ) from exc


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


def _embedding_item_index(item: Any, fallback: int) -> int:
    if isinstance(item, dict) and isinstance(item.get("index"), int):
        return item["index"]
    return fallback


def _embedding_vector_from_item(item: Any) -> list[float]:
    if not isinstance(item, dict):
        raise ProviderRouteError(
            status_code=502,
            error_code="mo.remote_embedding_response_invalid",
            detail="Remote embedding item must be an object.",
            retryable=True,
        )
    vector = item.get("embedding")
    if not isinstance(vector, list) or not vector or not all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in vector
    ):
        raise ProviderRouteError(
            status_code=502,
            error_code="mo.remote_embedding_response_invalid",
            detail="Remote embedding vector must be a non-empty numeric list.",
            retryable=True,
        )
    return [float(value) for value in vector]


def _normalize_usage(value: Any, input_texts: list[str]) -> dict[str, int]:
    usage = value if isinstance(value, dict) else {}
    input_tokens = _int_usage_value(
        usage,
        "input_tokens",
        "prompt_tokens",
        default=sum(_token_count(text) for text in input_texts),
    )
    output_tokens = _int_usage_value(usage, "output_tokens", default=0)
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


def _env_first(env: dict[str, str], primary: str, legacy: str) -> str:
    return env.get(primary) or env.get(legacy, "")


def _vllm_models_url(env: dict[str, str]) -> str:
    if env.get("NEX_MO_VLLM_MODELS_URL"):
        return env["NEX_MO_VLLM_MODELS_URL"]
    if env.get("NEX_MO_VLLM_BASE_URL"):
        return f"{env['NEX_MO_VLLM_BASE_URL'].rstrip('/')}/v1/models"
    return env.get("NEX_MO_LIVE_VLLM_MODELS_URL", "")


def _empty_to_none(value: str | None) -> str | None:
    return value or None


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, RemoteProviderPreflightError):
        return exc.failure_code
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return exc.__class__.__name__
