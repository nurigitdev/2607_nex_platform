from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from nex_mo.providers import DEFAULT_GENERATION_PROFILE, build_model_profile_catalog

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
