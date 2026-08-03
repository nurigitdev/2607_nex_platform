from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)

DEFAULT_MODEL_ROOT = "/data/nex-platform/models"
DEFAULT_PROVIDER_MODE = "mock"
DEFAULT_GENERATION_PROFILE = "qwen3_5_122b_a10b_nvfp4"
GENERATION_PROFILE_CANDIDATES: tuple[dict[str, str], ...] = (
    {
        "profile_name": "qwen3_5_122b_a10b_nvfp4",
        "alias": "general-llm-default",
        "model_name": "Qwen3.5-122B-A10B-NVFP4",
        "model_path_suffix": "qwen3.5-122b-a10b-nvfp4",
        "candidate_role": "primary",
        "selection_reason": "Current DGX-Spark vLLM generation target.",
    },
    {
        "profile_name": "qwen3_6_27b_nvfp4",
        "alias": "general-llm-fast",
        "model_name": "Qwen3.6-27B-NVFP4",
        "model_path_suffix": "qwen3.6-27b-nvfp4",
        "candidate_role": "candidate",
        "selection_reason": "Lower-latency generation candidate.",
    },
    {
        "profile_name": "k_ai_generation_candidate",
        "alias": "general-llm-kai-candidate",
        "model_name": "K-AI generation model",
        "model_path_suffix": "k-ai-generation-candidate",
        "candidate_role": "planned",
        "selection_reason": "Domestic K-AI generation model planned for evaluation.",
    },
)


@dataclass(frozen=True)
class ProviderRoute:
    alias: str
    provider_capability: str
    provider_type: str
    model_revision: str
    deployment_id: str
    route_id: str
    supports_response_formats: tuple[str, ...]
    max_input_tokens: int
    max_output_tokens: int
    status: str = "READY"
    embedding_dimensions: int | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "alias": self.alias,
            "provider_capability": self.provider_capability,
            "provider_type": self.provider_type,
            "model_revision": self.model_revision,
            "deployment_id": self.deployment_id,
            "route_id": self.route_id,
            "supports_response_formats": list(self.supports_response_formats),
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "status": self.status,
        }
        if self.embedding_dimensions is not None:
            payload["embedding_dimensions"] = self.embedding_dimensions
        return payload


@dataclass(frozen=True)
class ModelProfile:
    profile_name: str
    provider_capability: str
    alias: str
    provider_mode: str
    model_name: str
    precision: str
    runtime_engine: str
    model_path: str
    selected: bool
    status: str
    candidate_role: str = "primary"
    selection_reason: str = ""
    live_health_env: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "profile_name": self.profile_name,
            "provider_capability": self.provider_capability,
            "alias": self.alias,
            "provider_mode": self.provider_mode,
            "model_name": self.model_name,
            "precision": self.precision,
            "runtime_engine": self.runtime_engine,
            "model_path": self.model_path,
            "selected": self.selected,
            "status": self.status,
            "candidate_role": self.candidate_role,
            "selection_reason": self.selection_reason,
        }
        if self.live_health_env is not None:
            payload["live_health_env"] = self.live_health_env
        return payload


@dataclass(frozen=True)
class ProviderRouteError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_PROVIDER_ROUTES: tuple[ProviderRoute, ...] = (
    ProviderRoute(
        alias="mock-embedding-default",
        provider_capability="embedding",
        provider_type="mock-embedding",
        model_revision="mock-embedding-v1",
        deployment_id="mock-embedding-local",
        route_id="route-mock-embedding-default",
        supports_response_formats=("vector",),
        max_input_tokens=4096,
        max_output_tokens=0,
        embedding_dimensions=8,
    ),
    ProviderRoute(
        alias="mock-reranker-default",
        provider_capability="reranking",
        provider_type="mock-reranker",
        model_revision="mock-reranker-v1",
        deployment_id="mock-reranker-local",
        route_id="route-mock-reranker-default",
        supports_response_formats=("score",),
        max_input_tokens=4096,
        max_output_tokens=0,
    ),
    ProviderRoute(
        alias="general-llm-default",
        provider_capability="generation",
        provider_type="mock-generation",
        model_revision="mock-llm-v1",
        deployment_id="mock-generation-local",
        route_id="route-general-llm-default",
        supports_response_formats=("text", "json_object"),
        max_input_tokens=8192,
        max_output_tokens=1024,
    ),
)


def build_model_profile_catalog(environ: dict[str, str] | None = None) -> tuple[ModelProfile, ...]:
    env = environ if environ is not None else os.environ
    provider_mode = env.get("NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE)
    model_root = Path(env.get("NEX_MO_MODEL_ROOT", DEFAULT_MODEL_ROOT))
    status = "READY" if provider_mode == "mock" else "CONFIGURED"
    live_runtime_engine = "local_mock" if provider_mode == "mock" else "remote_http"
    selected_generation_profile = env.get(
        "NEX_MO_GENERATION_PROFILE",
        DEFAULT_GENERATION_PROFILE,
    )

    profiles: list[ModelProfile] = [
        ModelProfile(
            profile_name=env.get("NEX_MO_EMBEDDING_PROFILE", "qwen3_embedding_4b_bf16"),
            provider_capability="embedding",
            alias="mock-embedding-default",
            provider_mode=provider_mode,
            model_name="Qwen3-embedding-4B",
            precision="BF16",
            runtime_engine=live_runtime_engine,
            model_path=env.get(
                "NEX_MO_EMBEDDING_MODEL_PATH",
                str(model_root / "qwen3-embedding-4b-bf16"),
            ),
            selected=True,
            status=status,
            candidate_role="primary",
            selection_reason="Current default embedding model from NeX-PCX.",
            live_health_env="NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
        ),
        ModelProfile(
            profile_name=env.get("NEX_MO_RERANKER_PROFILE", "qwen3_reranker_4b_bf16"),
            provider_capability="reranking",
            alias="mock-reranker-default",
            provider_mode=provider_mode,
            model_name="Qwen3-reranker-4B",
            precision="BF16",
            runtime_engine=live_runtime_engine,
            model_path=env.get(
                "NEX_MO_RERANKER_MODEL_PATH",
                str(model_root / "qwen3-reranker-4b-bf16"),
            ),
            selected=True,
            status=status,
            candidate_role="primary",
            selection_reason="Current default reranker model from NeX-PCX.",
            live_health_env="NEX_MO_LIVE_RERANKER_HEALTH_URL",
        ),
    ]
    profiles.extend(
        build_generation_model_profiles(
            env=env,
            model_root=model_root,
            provider_mode=provider_mode,
            selected_generation_profile=selected_generation_profile,
        )
    )
    return tuple(profiles)


def build_generation_model_profiles(
    *,
    env: dict[str, str],
    model_root: Path,
    provider_mode: str,
    selected_generation_profile: str,
) -> tuple[ModelProfile, ...]:
    profiles: list[ModelProfile] = []
    selected_known_profile = selected_generation_profile in {
        candidate["profile_name"] for candidate in GENERATION_PROFILE_CANDIDATES
    }
    selected_profile_name = selected_generation_profile if selected_known_profile else ""
    for candidate in GENERATION_PROFILE_CANDIDATES:
        profile_name = candidate["profile_name"]
        selected = profile_name == selected_profile_name
        planned = candidate["candidate_role"] == "planned"
        profiles.append(
            ModelProfile(
                profile_name=profile_name,
                provider_capability="generation",
                alias=candidate["alias"],
                provider_mode=provider_mode,
                model_name=candidate["model_name"],
                precision="NVFP4",
                runtime_engine="vllm",
                model_path=generation_model_path(
                    env,
                    model_root,
                    profile_name=profile_name,
                    default_suffix=candidate["model_path_suffix"],
                    selected=selected,
                ),
                selected=selected,
                status=model_profile_status(
                    provider_mode=provider_mode,
                    selected=selected,
                    planned=planned,
                ),
                candidate_role=candidate["candidate_role"],
                selection_reason=candidate["selection_reason"],
                live_health_env="NEX_MO_LIVE_VLLM_MODELS_URL",
            )
        )
    if not selected_known_profile:
        profiles.append(
            ModelProfile(
                profile_name=selected_generation_profile,
                provider_capability="generation",
                alias="general-llm-custom",
                provider_mode=provider_mode,
                model_name=env.get("NEX_MO_GENERATION_MODEL_NAME", selected_generation_profile),
                precision="NVFP4",
                runtime_engine="vllm",
                model_path=env.get(
                    "NEX_MO_GENERATION_MODEL_PATH",
                    str(model_root / selected_generation_profile),
                ),
                selected=True,
                status=model_profile_status(
                    provider_mode=provider_mode,
                    selected=True,
                    planned=False,
                ),
                candidate_role="custom",
                selection_reason="Operator-selected generation profile override.",
                live_health_env="NEX_MO_LIVE_VLLM_MODELS_URL",
            )
        )
    return tuple(profiles)


def generation_model_path(
    env: dict[str, str],
    model_root: Path,
    *,
    profile_name: str,
    default_suffix: str,
    selected: bool,
) -> str:
    profile_specific_env = {
        "qwen3_5_122b_a10b_nvfp4": "NEX_MO_GENERATION_QWEN35_122B_MODEL_PATH",
        "qwen3_6_27b_nvfp4": "NEX_MO_GENERATION_QWEN36_27B_MODEL_PATH",
        "k_ai_generation_candidate": "NEX_MO_GENERATION_KAI_MODEL_PATH",
    }[profile_name]
    if profile_specific_env in env:
        return env[profile_specific_env]
    if selected and "NEX_MO_GENERATION_MODEL_PATH" in env:
        return env["NEX_MO_GENERATION_MODEL_PATH"]
    return str(model_root / default_suffix)


def model_profile_status(*, provider_mode: str, selected: bool, planned: bool) -> str:
    if planned:
        return "PLANNED"
    if provider_mode == "mock" and selected:
        return "READY"
    return "CONFIGURED"


def list_model_profiles(
    capability: str | None = None,
    profiles: tuple[ModelProfile, ...] | None = None,
) -> list[ModelProfile]:
    selected_profiles = profiles or build_model_profile_catalog()
    if capability is None:
        return list(selected_profiles)
    return [
        profile
        for profile in selected_profiles
        if profile.provider_capability == capability
    ]


def list_provider_routes(
    capability: str | None = None,
    routes: tuple[ProviderRoute, ...] = DEFAULT_PROVIDER_ROUTES,
) -> list[ProviderRoute]:
    if capability is None:
        return list(routes)
    return [route for route in routes if route.provider_capability == capability]


def resolve_provider_route(
    alias: str,
    provider_capability: str,
    routes: tuple[ProviderRoute, ...] = DEFAULT_PROVIDER_ROUTES,
) -> ProviderRoute:
    matches = [route for route in routes if route.alias == alias]
    if not matches:
        raise ProviderRouteError(404, "mo.alias_not_found", f"Unknown provider alias: {alias}")

    route = matches[0]
    if route.provider_capability != provider_capability:
        raise ProviderRouteError(
            422,
            "mo.capability_not_supported",
            f"Alias {alias} does not support {provider_capability}.",
        )
    if route.status != "READY":
        raise ProviderRouteError(
            503,
            "mo.deployment_unavailable",
            f"Alias {alias} is not ready.",
            retryable=True,
        )
    return route


def create_embedding_response(
    payload: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
    requester=None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get("NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE) == "live":
        from nex_mo.remote_provider import execute_remote_embedding_request

        return execute_remote_embedding_request(
            payload,
            environ=env,
            requester=requester,
        )
    return create_mock_embedding_response(payload)


def create_mock_embedding_response(payload: dict[str, Any]) -> dict[str, Any]:
    route = resolve_provider_route(
        _string_field(payload, "alias", "mock-embedding-default"),
        "embedding",
    )
    inputs = _string_list_field(payload, "inputs")

    return {
        "object": "list",
        "alias": route.alias,
        "model_revision": route.model_revision,
        "deployment_id": route.deployment_id,
        "data": [
            {
                "object": "embedding",
                "index": index,
                "embedding": _deterministic_vector(text, route.embedding_dimensions or 8),
            }
            for index, text in enumerate(inputs)
        ],
        "usage": {
            "input_tokens": sum(_token_count(text) for text in inputs),
            "output_tokens": 0,
            "total_tokens": sum(_token_count(text) for text in inputs),
        },
    }


def create_mock_rerank_response(payload: dict[str, Any]) -> dict[str, Any]:
    route = resolve_provider_route(
        _string_field(payload, "alias", "mock-reranker-default"),
        "reranking",
    )
    query = _string_field(payload, "query")
    documents = _string_list_field(payload, "documents")
    results = [
        {
            "index": index,
            "score": _deterministic_score(f"{query}\n{document}"),
            "document": document,
        }
        for index, document in enumerate(documents)
    ]

    return {
        "alias": route.alias,
        "model_revision": route.model_revision,
        "deployment_id": route.deployment_id,
        "results": sorted(results, key=lambda item: item["score"], reverse=True),
        "usage": {
            "input_tokens": _token_count(query)
            + sum(_token_count(document) for document in documents),
            "output_tokens": 0,
            "total_tokens": _token_count(query)
            + sum(_token_count(document) for document in documents),
        },
    }


def create_rerank_response(
    payload: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
    requester=None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get("NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE) == "live":
        from nex_mo.remote_provider import execute_remote_rerank_request

        return execute_remote_rerank_request(
            payload,
            environ=env,
            requester=requester,
        )
    return create_mock_rerank_response(payload)


def create_mock_generation_response(
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    _reject_raw_provider_fields(payload)
    alias = _string_field(payload, "alias", "general-llm-default")
    provider_capability = _string_field(payload, "provider_capability", "generation")
    route = resolve_provider_route(alias, provider_capability)
    max_output_tokens = int(payload.get("max_output_tokens", 256))
    if max_output_tokens > route.max_output_tokens:
        raise ProviderRouteError(
            422,
            "mo.generation_parameter_out_of_bounds",
            f"max_output_tokens must be <= {route.max_output_tokens}.",
        )

    prompt_text = _prompt_text(payload)
    normalized = _stable_json(
        {
            "alias": route.alias,
            "prompt_text": prompt_text,
            "seed": payload.get("seed"),
            "trace_id": payload.get("trace_id", trace_id),
        }
    )
    input_tokens = _token_count(prompt_text)
    output_text = f"[mock:{route.alias}] {prompt_text[:160]}"
    output_tokens = _token_count(output_text)
    now = _utc_now()

    return {
        "mo_generation_id": str(uuid5(NAMESPACE_URL, normalized)),
        "alias": route.alias,
        "model_revision": route.model_revision,
        "deployment_id": route.deployment_id,
        "provider_type": route.provider_type,
        "output": {
            "type": "text",
            "text": output_text,
        },
        "finish_reason": "STOP",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        "runtime_metadata": {
            "request_id": request_id,
            "trace_id": payload.get("trace_id", trace_id),
            "queue_ms": 0,
            "provider_ms": _deterministic_latency_ms(normalized),
            "total_ms": _deterministic_latency_ms(normalized),
            "route_id": route.route_id,
            "admission_decision": "ACCEPTED",
            "provider_request_id": str(uuid5(NAMESPACE_URL, f"provider:{normalized}")),
        },
        "created_at": now,
        "updated_at": now,
    }


def create_generation_response(
    payload: dict[str, Any],
    *,
    request_id: str,
    trace_id: str,
    environ: dict[str, str] | None = None,
    requester=None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get("NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE) == "live":
        from nex_mo.remote_provider import execute_remote_generation_request

        return execute_remote_generation_request(
            payload,
            request_id=request_id,
            trace_id=trace_id,
            environ=env,
            requester=requester,
        )
    return create_mock_generation_response(
        payload,
        request_id=request_id,
        trace_id=trace_id,
    )


def register_mock_provider_routes(app: FastAPI) -> None:
    @app.get("/api/v1/provider-routes", response_model=None)
    def get_provider_routes(
        request: Request,
        capability: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_mo_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        routes = list_provider_routes(capability)
        return {
            "data": [route.to_wire() for route in routes],
            "meta": {
                "count": len(routes),
                "profile": "local_mock",
            },
        }

    @app.get("/api/v1/provider-profiles", response_model=None)
    def get_provider_profiles(
        request: Request,
        capability: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_mo_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        profiles = list_model_profiles(capability)
        return {
            "data": [profile.to_wire() for profile in profiles],
            "meta": {
                "count": len(profiles),
                "provider_mode": os.getenv("NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE),
                "model_root": os.getenv("NEX_MO_MODEL_ROOT", DEFAULT_MODEL_ROOT),
            },
        }

    @app.post("/api/v1/embeddings", response_model=None)
    def create_embeddings(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _handle_provider_request(
            request,
            authorization,
            lambda: create_embedding_response(payload),
        )

    @app.post("/api/v1/rerank", response_model=None)
    def rerank_documents(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _handle_provider_request(
            request,
            authorization,
            lambda: create_rerank_response(payload),
        )

    @app.post("/api/v1/generations", response_model=None)
    def create_generation(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _handle_provider_request(
            request,
            authorization,
            lambda: create_generation_response(
                payload,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            ),
        )


def _handle_provider_request(
    request: Request,
    authorization: str | None,
    factory,
):
    auth_problem = _authorize_mo_request(request, authorization)
    if auth_problem is not None:
        return auth_problem

    try:
        return factory()
    except ProviderRouteError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="Provider route rejected",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri="https://nex-platform.local/problems/provider-route-rejected",
        )


def _authorize_mo_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-mo",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "MO requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
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


def _prompt_text(payload: dict[str, Any]) -> str:
    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt:
        return prompt

    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        parts = [
            str(message.get("content", ""))
            for message in messages
            if isinstance(message, dict) and message.get("content")
        ]
        if parts:
            return "\n".join(parts)

    raise ProviderRouteError(
        400,
        "mo.request_invalid",
        "prompt or messages are required.",
    )


def _reject_raw_provider_fields(payload: dict[str, Any]) -> None:
    forbidden = {"provider_url", "model_path", "provider_endpoint", "api_key"}
    leaked = sorted(forbidden & set(payload))
    if leaked:
        raise ProviderRouteError(
            422,
            "mo.provider_field_forbidden",
            f"Provider-private field is not allowed: {leaked[0]}",
        )


def _deterministic_vector(text: str, dimensions: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [round(digest[index] / 255, 6) for index in range(dimensions)]


def _deterministic_score(text: str) -> float:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return round(int.from_bytes(digest[:4], "big") / 0xFFFFFFFF, 6)


def _deterministic_latency_ms(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return 10 + digest[0] % 40


def _token_count(text: str) -> int:
    return max(1, len(text.split()))


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
