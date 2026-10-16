from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import httpx

from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)
from nex_runtime import resolve_service_endpoint
from nex_runtime.semantic_hashes import hash_ref_from_sha256, sha256_text


AE_MO_GENERATION_CLIENT_SCHEMA_VERSION = "ae_mo_generation_client.v1"
AE_MO_GENERATION_ALIAS_ENV = "NEX_AE_MO_GENERATION_ALIAS"
AE_MO_GENERATION_BUDGET_ENV = "NEX_AE_MO_GENERATION_BUDGET_SECONDS"
AE_MO_GENERATION_TIMEOUT_ENV = "NEX_AE_MO_GENERATION_TIMEOUT_SECONDS"
AE_MO_READINESS_TIMEOUT_ENV = "NEX_AE_MO_READINESS_TIMEOUT_SECONDS"
AE_MO_TIMEOUT_SAFETY_MARGIN_ENV = "NEX_AE_MO_TIMEOUT_SAFETY_MARGIN_SECONDS"
AE_MO_SERVICE_TOKEN_ENV = "NEX_AE_TO_MO_SERVICE_TOKEN"

DEFAULT_AE_MO_GENERATION_ALIAS = "general-llm-default"
DEFAULT_AE_MO_GENERATION_BUDGET_SECONDS = 125.0
DEFAULT_AE_MO_GENERATION_TIMEOUT_SECONDS = 130.0
DEFAULT_AE_MO_READINESS_TIMEOUT_SECONDS = 10.0
DEFAULT_AE_MO_TIMEOUT_SAFETY_MARGIN_SECONDS = 5.0

P65_STAGE_MAX_OUTPUT_TOKENS = {
    "INTENT": 768,
    "CONTEXT": 1024,
    "PLAN": 1024,
}

_ALIAS = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SAFE_ERROR_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_MESSAGE_ROLES = {"system", "developer", "user", "assistant"}
_MAX_MESSAGES = 16
_MAX_MESSAGE_CONTENT_CHARS = 65_536
_MAX_TOTAL_MESSAGE_CHARS = 131_072
_MAX_OUTPUT_TEXT_CHARS = 262_144
_FORBIDDEN_PRIVATE_KEYS = {
    "api_key",
    "credential",
    "hidden_reasoning",
    "model_path",
    "provider_endpoint",
    "provider_url",
    "raw_prompt",
    "secret",
}

_GENERATION_RESPONSE_KEYS = {
    "mo_generation_id",
    "alias",
    "model_revision",
    "deployment_id",
    "provider_type",
    "output",
    "finish_reason",
    "usage",
    "runtime_metadata",
    "created_at",
    "updated_at",
}
_GENERATION_OUTPUT_KEYS = {"type", "text"}
_GENERATION_USAGE_KEYS = {"input_tokens", "output_tokens", "total_tokens"}
_GENERATION_RUNTIME_KEYS = {
    "request_id",
    "trace_id",
    "queue_ms",
    "provider_ms",
    "total_ms",
    "route_id",
    "admission_decision",
    "provider_request_id",
}
_READINESS_KEYS = {
    "name",
    "ok",
    "provider_readiness_schema_version",
    "provider_mode",
    "readiness_status",
    "checked_at",
    "expires_at",
    "cache_status",
    "required_capabilities",
    "summary",
    "routes",
    "failure_code",
    "error_code",
}
_READINESS_ROUTE_KEYS = {
    "route_health_schema_version",
    "provider_capability",
    "alias",
    "route_id",
    "deployment_id",
    "model_revision",
    "status",
    "source",
    "ok",
    "checked_at",
    "latency_ms",
    "failure_code",
    "retryable",
    "degraded",
}

HttpRequester = Callable[..., httpx.Response]


class AeMoGenerationClient(Protocol):
    def generate_candidate(
        self,
        *,
        semantic_stage: str,
        messages: Sequence[Mapping[str, Any]],
        request_id: str,
        trace_id: str,
    ) -> "AeMoGenerationResult":
        ...

    def check_required_mode_readiness(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> "AeMoGenerationReadiness":
        ...


@dataclass(frozen=True)
class AeMoGenerationClientError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False
    upstream_error_code: str | None = None
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AeMoGenerationConfigurationError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AeMoGenerationTimeoutBudget:
    mo_generation_budget_seconds: float
    safety_margin_seconds: float
    minimum_client_timeout_seconds: float
    client_timeout_seconds: float


@dataclass(frozen=True)
class AeMoGenerationResult:
    mo_generation_id: str
    model_profile: str
    model_ref: str
    deployment_id: str
    provider_type: str
    output_text: str = field(repr=False)
    provider_output_sha256: str
    provider_output_size_bytes: int
    finish_reason: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    request_id: str
    trace_id: str
    route_id: str
    provider_request_id: str
    queue_ms: int
    provider_ms: int
    total_ms: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AeMoGenerationReadiness:
    provider_mode: str
    readiness_status: str
    model_profile: str
    model_ref: str
    deployment_id: str
    route_id: str
    checked_at: str
    expires_at: str
    cache_status: str
    source: str


@dataclass(frozen=True)
class HttpAeMoGenerationClient:
    base_url: str
    generation_alias: str = DEFAULT_AE_MO_GENERATION_ALIAS
    service_token: str | None = field(default=None, repr=False)
    generation_timeout_seconds: float = DEFAULT_AE_MO_GENERATION_TIMEOUT_SECONDS
    readiness_timeout_seconds: float = DEFAULT_AE_MO_READINESS_TIMEOUT_SECONDS
    requester: HttpRequester | None = field(default=None, repr=False, compare=False)
    auth_environ: Mapping[str, str] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def generate_candidate(
        self,
        *,
        semantic_stage: str,
        messages: Sequence[Mapping[str, Any]],
        request_id: str,
        trace_id: str,
    ) -> AeMoGenerationResult:
        stage = _semantic_stage(semantic_stage)
        selected_request_id = _request_id(request_id)
        selected_trace_id = _trace_id(trace_id)
        payload = {
            "request_schema_version": "cx_mo_generation_request.v1",
            "client_request_id": selected_request_id,
            "trace_id": selected_trace_id,
            "alias": _generation_alias(self.generation_alias),
            "provider_capability": "generation",
            "messages": _generation_messages(messages),
            "response_format": {"type": "json_object"},
            "reasoning_mode": "disabled",
            "max_output_tokens": P65_STAGE_MAX_OUTPUT_TOKENS[stage],
            "temperature": 0.0,
            "stream": False,
        }
        response = self._request_json(
            "POST",
            "/api/v1/generations",
            request_id=selected_request_id,
            trace_id=selected_trace_id,
            timeout_seconds=self.generation_timeout_seconds,
            json_payload=payload,
        )
        return _generation_result(
            response,
            expected_alias=self.generation_alias,
            expected_request_id=selected_request_id,
            expected_trace_id=selected_trace_id,
        )

    def check_required_mode_readiness(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> AeMoGenerationReadiness:
        selected_request_id = _request_id(request_id)
        selected_trace_id = _trace_id(trace_id)
        response = self._request_json(
            "GET",
            "/api/v1/provider-route-health",
            request_id=selected_request_id,
            trace_id=selected_trace_id,
            timeout_seconds=self.readiness_timeout_seconds,
            json_payload=None,
        )
        return _generation_readiness(
            response,
            expected_alias=self.generation_alias,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        trace_id: str,
        timeout_seconds: float,
        json_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            token = resolve_ae_outbound_service_token(
                self.service_token,
                audience="nex-mo",
                environ=self.auth_environ,
            )
        except AeOutboundServiceTokenError as exc:
            raise AeMoGenerationClientError(
                status_code=503,
                error_code="PROVIDER_NOT_READY",
                detail="MO service authentication is not ready.",
                retryable=False,
                upstream_error_code=exc.error_code,
            ) from exc

        request = self.requester or httpx.request
        try:
            response = request(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                json=json_payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": "nex-ae-api",
                },
                timeout=_positive_runtime_timeout(timeout_seconds),
            )
        except httpx.TimeoutException as exc:
            raise AeMoGenerationClientError(
                status_code=504,
                error_code="PROVIDER_TIMEOUT",
                detail="MO generation boundary timed out.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AeMoGenerationClientError(
                status_code=503,
                error_code="PROVIDER_NOT_READY",
                detail="MO generation boundary is unavailable.",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            raise _http_failure(response)
        payload = _response_object(response)
        _reject_private_material(payload)
        return payload


def build_default_ae_mo_generation_client(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
) -> HttpAeMoGenerationClient:
    env = os.environ if environ is None else environ
    budget = resolve_ae_mo_generation_timeout_budget(env)
    try:
        base_url = resolve_service_endpoint("nex-mo", environ=env).base_url
    except ValueError as exc:
        raise AeMoGenerationConfigurationError(
            "AE_MO_BASE_URL_INVALID",
            "NEX_MO_BASE_URL must be a safe HTTP or HTTPS service base URL.",
        ) from exc
    return HttpAeMoGenerationClient(
        base_url=base_url,
        generation_alias=_generation_alias(
            env.get(AE_MO_GENERATION_ALIAS_ENV, DEFAULT_AE_MO_GENERATION_ALIAS)
        ),
        service_token=env.get(AE_MO_SERVICE_TOKEN_ENV) or None,
        generation_timeout_seconds=budget.client_timeout_seconds,
        readiness_timeout_seconds=_positive_float(
            env,
            AE_MO_READINESS_TIMEOUT_ENV,
            DEFAULT_AE_MO_READINESS_TIMEOUT_SECONDS,
        ),
        requester=requester,
        auth_environ=env,
    )


def resolve_ae_mo_generation_timeout_budget(
    environ: Mapping[str, str] | None = None,
) -> AeMoGenerationTimeoutBudget:
    env = os.environ if environ is None else environ
    mo_budget = _positive_float(
        env,
        AE_MO_GENERATION_BUDGET_ENV,
        DEFAULT_AE_MO_GENERATION_BUDGET_SECONDS,
    )
    safety_margin = _positive_float(
        env,
        AE_MO_TIMEOUT_SAFETY_MARGIN_ENV,
        DEFAULT_AE_MO_TIMEOUT_SAFETY_MARGIN_SECONDS,
    )
    minimum = mo_budget + safety_margin
    configured = env.get(AE_MO_GENERATION_TIMEOUT_ENV)
    if configured is None or not configured.strip():
        client_timeout = max(DEFAULT_AE_MO_GENERATION_TIMEOUT_SECONDS, minimum)
    else:
        client_timeout = _positive_float(
            env,
            AE_MO_GENERATION_TIMEOUT_ENV,
            DEFAULT_AE_MO_GENERATION_TIMEOUT_SECONDS,
        )
    if client_timeout < minimum:
        raise AeMoGenerationConfigurationError(
            "AE_MO_GENERATION_TIMEOUT_TOO_SHORT",
            (
                f"{AE_MO_GENERATION_TIMEOUT_ENV} must be at least "
                f"{minimum:g} seconds for the configured MO retry budget."
            ),
        )
    return AeMoGenerationTimeoutBudget(
        mo_generation_budget_seconds=mo_budget,
        safety_margin_seconds=safety_margin,
        minimum_client_timeout_seconds=minimum,
        client_timeout_seconds=client_timeout,
    )


def _generation_result(
    payload: Mapping[str, Any],
    *,
    expected_alias: str,
    expected_request_id: str,
    expected_trace_id: str,
) -> AeMoGenerationResult:
    _exact_keys(payload, _GENERATION_RESPONSE_KEYS, "generation response")
    alias = _bounded_text(payload.get("alias"), "alias", maximum=128)
    if alias != _generation_alias(expected_alias):
        raise _invalid_response("MO generation alias does not match the request.")

    output = _object(payload.get("output"), "output")
    _exact_keys(output, _GENERATION_OUTPUT_KEYS, "generation output")
    if output.get("type") != "text":
        raise _invalid_response("MO generation output type is invalid.")
    output_text = _bounded_text(
        output.get("text"),
        "output.text",
        maximum=_MAX_OUTPUT_TEXT_CHARS,
        preserve=True,
    )

    usage = _object(payload.get("usage"), "usage")
    _exact_keys(usage, _GENERATION_USAGE_KEYS, "generation usage")
    input_tokens = _non_negative_int(usage.get("input_tokens"), "input_tokens")
    output_tokens = _non_negative_int(usage.get("output_tokens"), "output_tokens")
    total_tokens = _non_negative_int(usage.get("total_tokens"), "total_tokens")
    if input_tokens + output_tokens != total_tokens:
        raise _invalid_response("MO generation token usage is inconsistent.")

    runtime = _object(payload.get("runtime_metadata"), "runtime_metadata")
    _exact_keys(runtime, _GENERATION_RUNTIME_KEYS, "generation runtime metadata")
    response_request_id = _bounded_text(runtime.get("request_id"), "request_id")
    response_trace_id = _bounded_text(runtime.get("trace_id"), "trace_id")
    if response_request_id != expected_request_id or response_trace_id != expected_trace_id:
        raise _invalid_response("MO generation correlation does not match the request.")

    created_at = _timestamp(payload.get("created_at"), "created_at")
    updated_at = _timestamp(payload.get("updated_at"), "updated_at")
    output_bytes = output_text.encode("utf-8")
    return AeMoGenerationResult(
        mo_generation_id=_bounded_text(
            payload.get("mo_generation_id"), "mo_generation_id"
        ),
        model_profile=alias,
        model_ref=_bounded_text(payload.get("model_revision"), "model_revision"),
        deployment_id=_bounded_text(payload.get("deployment_id"), "deployment_id"),
        provider_type=_bounded_text(payload.get("provider_type"), "provider_type"),
        output_text=output_text,
        provider_output_sha256=hash_ref_from_sha256(sha256_text(output_text)),
        provider_output_size_bytes=len(output_bytes),
        finish_reason=_bounded_text(payload.get("finish_reason"), "finish_reason"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        request_id=response_request_id,
        trace_id=response_trace_id,
        route_id=_bounded_text(runtime.get("route_id"), "route_id"),
        provider_request_id=_bounded_text(
            runtime.get("provider_request_id"), "provider_request_id"
        ),
        queue_ms=_non_negative_int(runtime.get("queue_ms"), "queue_ms"),
        provider_ms=_non_negative_int(runtime.get("provider_ms"), "provider_ms"),
        total_ms=_non_negative_int(runtime.get("total_ms"), "total_ms"),
        created_at=created_at,
        updated_at=updated_at,
    )


def _generation_readiness(
    payload: Mapping[str, Any],
    *,
    expected_alias: str,
) -> AeMoGenerationReadiness:
    _exact_keys(payload, _READINESS_KEYS, "provider readiness")
    if payload.get("provider_readiness_schema_version") != "mo_provider_readiness.v1":
        raise _invalid_response("MO provider readiness schema version is invalid.")
    if (
        payload.get("name") != "provider_routes"
        or payload.get("provider_mode") != "live"
        or payload.get("readiness_status") != "READY"
        or payload.get("ok") is not True
    ):
        raise _not_ready("MO live provider readiness is not READY.")
    required = payload.get("required_capabilities")
    if not isinstance(required, list) or "generation" not in required:
        raise _invalid_response("MO generation readiness capability is missing.")
    routes = payload.get("routes")
    if not isinstance(routes, list):
        raise _invalid_response("MO provider readiness routes are invalid.")
    selected_alias = _generation_alias(expected_alias)
    matches = [
        route
        for route in routes
        if isinstance(route, dict)
        and route.get("provider_capability") == "generation"
        and route.get("alias") == selected_alias
    ]
    if len(matches) != 1:
        raise _not_ready("The configured MO generation route is not ready.")
    route = matches[0]
    _exact_keys(route, _READINESS_ROUTE_KEYS, "generation readiness route")
    if (
        route.get("route_health_schema_version") != "mo_provider_route_health.v1"
        or route.get("status") != "READY"
        or route.get("ok") is not True
        or route.get("source") != "active_preflight"
        or route.get("degraded") is not False
    ):
        raise _not_ready("The configured MO generation preflight is not READY.")
    cache_status = payload.get("cache_status")
    if cache_status not in {"MISS", "FRESH", "REFRESHED"}:
        raise _not_ready("MO provider readiness evidence is stale.")
    return AeMoGenerationReadiness(
        provider_mode="live",
        readiness_status="READY",
        model_profile=selected_alias,
        model_ref=_bounded_text(route.get("model_revision"), "model_revision"),
        deployment_id=_bounded_text(route.get("deployment_id"), "deployment_id"),
        route_id=_bounded_text(route.get("route_id"), "route_id"),
        checked_at=_timestamp(payload.get("checked_at"), "checked_at"),
        expires_at=_timestamp(payload.get("expires_at"), "expires_at"),
        cache_status=str(cache_status),
        source="active_preflight",
    )


def _http_failure(response: httpx.Response) -> AeMoGenerationClientError:
    body = _optional_response_object(response)
    upstream_error_code = _safe_upstream_error_code(body.get("error_code"))
    status_code = response.status_code
    if status_code in {408, 504}:
        error_code = "PROVIDER_TIMEOUT"
        detail = "MO generation boundary timed out."
        retryable = True
    elif status_code == 429:
        error_code = "PROVIDER_RATE_LIMIT"
        detail = "MO generation capacity is temporarily rate limited."
        retryable = True
    elif status_code in {401, 403, 404} or _is_not_ready_code(upstream_error_code):
        error_code = "PROVIDER_NOT_READY"
        detail = "MO generation route is not ready."
        retryable = status_code not in {401, 403}
    elif status_code >= 500:
        error_code = "PROVIDER_SERVER_ERROR"
        detail = "MO generation boundary returned a server error."
        retryable = True
    else:
        error_code = "PROVIDER_RESPONSE_INVALID"
        detail = "MO rejected the bounded generation request."
        retryable = False
    return AeMoGenerationClientError(
        status_code=status_code,
        error_code=error_code,
        detail=detail,
        retryable=retryable,
        upstream_error_code=upstream_error_code,
        retry_after_seconds=_retry_after_seconds(response),
    )


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise _invalid_response("MO generation boundary returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise _invalid_response("MO generation boundary did not return a JSON object.")
    return payload


def _optional_response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _generation_messages(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    if isinstance(messages, (str, bytes)) or not 1 <= len(messages) <= _MAX_MESSAGES:
        raise _invalid_request(f"messages must contain 1 to {_MAX_MESSAGES} entries.")
    normalized: list[dict[str, str]] = []
    total_chars = 0
    for message in messages:
        if not isinstance(message, Mapping) or set(message) != {"role", "content"}:
            raise _invalid_request("each message must contain only role and content.")
        role = message.get("role")
        content = message.get("content")
        if role not in _MESSAGE_ROLES:
            raise _invalid_request("message role is not supported.")
        if (
            not isinstance(content, str)
            or not content.strip()
            or len(content) > _MAX_MESSAGE_CONTENT_CHARS
        ):
            raise _invalid_request("message content is empty or exceeds its bound.")
        total_chars += len(content)
        normalized.append({"role": str(role), "content": content})
    if total_chars > _MAX_TOTAL_MESSAGE_CHARS:
        raise _invalid_request("total message content exceeds its bound.")
    return normalized


def _semantic_stage(value: object) -> str:
    if not isinstance(value, str) or value not in P65_STAGE_MAX_OUTPUT_TOKENS:
        raise _invalid_request("semantic_stage must be INTENT, CONTEXT, or PLAN.")
    return value


def _generation_alias(value: object) -> str:
    if not isinstance(value, str) or _ALIAS.fullmatch(value) is None:
        raise AeMoGenerationConfigurationError(
            "AE_MO_GENERATION_ALIAS_INVALID",
            f"{AE_MO_GENERATION_ALIAS_ENV} must be a bounded logical alias.",
        )
    return value


def _request_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise _invalid_request("request_id must be a bounded non-empty string.")
    return value


def _trace_id(value: object) -> str:
    if not isinstance(value, str) or _TRACE_ID.fullmatch(value) is None:
        raise _invalid_request("trace_id must be 32 lowercase hexadecimal characters.")
    return value


def _object(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _invalid_response(f"MO {field_name} must be a JSON object.")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise _invalid_response(f"MO {label} fields do not match the contract.")


def _bounded_text(
    value: object,
    field_name: str,
    *,
    maximum: int = 512,
    preserve: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid_response(f"MO {field_name} is invalid.")
    return value if preserve else value.strip()


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_response(f"MO {field_name} must be a non-negative integer.")
    return value


def _timestamp(value: object, field_name: str) -> str:
    text = _bounded_text(value, field_name, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid_response(f"MO {field_name} must be an ISO timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid_response(f"MO {field_name} must include a timezone.")
    return text


def _reject_private_material(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_PRIVATE_KEYS:
                raise _invalid_response("MO response contains provider-private material.")
            _reject_private_material(item)
    elif isinstance(value, list):
        for item in value:
            _reject_private_material(item)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw_value = response.headers.get("Retry-After")
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    return value if 0 <= value <= 300 else None


def _safe_upstream_error_code(value: object) -> str | None:
    if isinstance(value, str) and _SAFE_ERROR_CODE.fullmatch(value):
        return value
    return None


def _is_not_ready_code(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in ("not_ready", "not_configured", "unavailable", "alias_not_found")
    )


def _positive_runtime_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise AeMoGenerationConfigurationError(
            "AE_MO_TIMEOUT_INVALID",
            "AE-to-MO timeout must be a positive number.",
        )
    return float(value)


def _positive_float(
    environ: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw_value = environ.get(name)
    try:
        value = default if raw_value is None or not raw_value.strip() else float(raw_value)
    except (AttributeError, ValueError) as exc:
        raise AeMoGenerationConfigurationError(
            "AE_MO_TIMEOUT_INVALID",
            f"{name} must be a positive number.",
        ) from exc
    if value <= 0:
        raise AeMoGenerationConfigurationError(
            "AE_MO_TIMEOUT_INVALID",
            f"{name} must be a positive number.",
        )
    return value


def _invalid_request(detail: str) -> AeMoGenerationClientError:
    return AeMoGenerationClientError(
        status_code=400,
        error_code="AE_MO_GENERATION_REQUEST_INVALID",
        detail=detail,
        retryable=False,
    )


def _invalid_response(detail: str) -> AeMoGenerationClientError:
    return AeMoGenerationClientError(
        status_code=502,
        error_code="PROVIDER_RESPONSE_INVALID",
        detail=detail,
        retryable=False,
    )


def _not_ready(detail: str) -> AeMoGenerationClientError:
    return AeMoGenerationClientError(
        status_code=503,
        error_code="PROVIDER_NOT_READY",
        detail=detail,
        retryable=True,
    )
