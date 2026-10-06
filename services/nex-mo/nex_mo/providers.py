from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request

from nex_mo.provider_auth import authorize_mo_service_request
from nex_mo.provider_catalog import (
    DEFAULT_GENERATION_PROFILE,
    DEFAULT_MODEL_ROOT,
    DEFAULT_PROVIDER_MODE,
    GENERATION_PROFILE_CANDIDATES,
    ModelProfile,
    build_generation_model_profiles,
    build_model_profile_catalog as _build_model_profile_catalog,
    generation_model_path,
    list_model_profiles,
    model_profile_status,
)
from nex_mo.provider_registry import (
    DEFAULT_PROVIDER_ROUTES,
    ProviderRoute,
    ProviderRouteError,
    list_provider_routes,
    resolve_provider_route,
)
from nex_mo.provider_trace import emit_provider_trace_event
from nex_runtime import (
    OperationalEventEmitter,
    operational_event_emitter_from_app,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)


def build_model_profile_catalog(
    environ: dict[str, str] | None = None,
) -> tuple[ModelProfile, ...]:
    return _build_model_profile_catalog(environ)


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
                "embedding": _deterministic_vector(
                    text, route.embedding_dimensions or 8
                ),
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
    grounded_citation_label = _grounded_citation_label(payload)
    output_text = (
        f"[mock:{route.alias}] Grounded mock answer {grounded_citation_label}."
        if grounded_citation_label is not None
        else f"[mock:{route.alias}] {prompt_text[:160]}"
    )
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
    trace_emitter = operational_event_emitter_from_app(app, service_id="nex-mo")

    @app.get("/api/v1/provider-routes", response_model=None)
    def get_provider_routes(
        request: Request,
        capability: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_mo_service_request(request, authorization)
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
        auth_problem = authorize_mo_service_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        profiles = list_model_profiles(capability)
        return {
            "data": [profile.to_wire() for profile in profiles],
            "meta": {
                "count": len(profiles),
                "provider_mode": os.getenv(
                    "NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE
                ),
            },
        }

    @app.get("/api/v1/provider-telemetry", response_model=None)
    def get_provider_telemetry(
        request: Request,
        capability: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_mo_service_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        from nex_mo.provider_telemetry_repository import (
            ProviderTelemetryRepositoryError,
        )
        from nex_mo.remote_provider import list_remote_provider_telemetry

        try:
            telemetry = list_remote_provider_telemetry(capability=capability)
        except ProviderTelemetryRepositoryError:
            return problem_response(
                request,
                status_code=503,
                error_code="MO_PROVIDER_TELEMETRY_UNAVAILABLE",
                title="Provider telemetry unavailable",
                detail="Durable provider telemetry is temporarily unavailable.",
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "provider-telemetry-unavailable"
                ),
            )
        return {
            "data": telemetry,
            "meta": {
                "count": len(telemetry),
                "provider_mode": os.getenv(
                    "NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE
                ),
                "schema_version": "mo_provider_telemetry_snapshot.v1",
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
            "embedding",
            _provider_alias(payload, "mock-embedding-default"),
            lambda: create_embedding_response(payload),
            trace_emitter,
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
            "reranking",
            _provider_alias(payload, "mock-reranker-default"),
            lambda: create_rerank_response(payload),
            trace_emitter,
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
            "generation",
            _provider_alias(payload, "general-llm-default"),
            lambda: create_generation_response(
                payload,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            ),
            trace_emitter,
        )


def _handle_provider_request(
    request: Request,
    authorization: str | None,
    capability: str,
    alias: str,
    factory,
    trace_emitter: OperationalEventEmitter,
):
    auth_problem = authorize_mo_service_request(request, authorization)
    if auth_problem is not None:
        return auth_problem

    try:
        response = factory()
        emit_provider_trace_event(
            trace_emitter,
            request=request,
            capability=capability,
            alias=alias,
            response=response,
        )
        return response
    except ProviderRouteError as exc:
        emit_provider_trace_event(
            trace_emitter,
            request=request,
            capability=capability,
            alias=alias,
            route_error=exc,
        )
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="Provider route rejected",
            detail=exc.detail,
            retryable=exc.retryable,
            type_uri="https://nex-platform.local/problems/provider-route-rejected",
            details={"degraded": exc.degraded} if exc.degraded else None,
        )


def _provider_alias(payload: dict[str, Any], default: str) -> str:
    value = payload.get("alias", default)
    return value if isinstance(value, str) and value else default


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
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
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


def _grounded_citation_label(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("grounding_context_policy") != (
        "owner_admitted_untrusted_evidence_v1"
    ):
        return None
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return None
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str) or "\n" not in content:
            continue
        try:
            envelope = json.loads(content.split("\n", maxsplit=1)[1])
        except json.JSONDecodeError:
            continue
        evidence = envelope.get("evidence") if isinstance(envelope, dict) else None
        if not isinstance(evidence, list) or not evidence:
            continue
        first = evidence[0]
        label = first.get("citation_label") if isinstance(first, dict) else None
        if isinstance(label, str) and label:
            return label
    return None


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
