from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from nex_ae_api.mo_generation_client import (
    AE_MO_GENERATION_ALIAS_ENV,
    AE_MO_GENERATION_BUDGET_ENV,
    AE_MO_GENERATION_TIMEOUT_ENV,
    AE_MO_READINESS_TIMEOUT_ENV,
    AE_MO_TIMEOUT_SAFETY_MARGIN_ENV,
    P65_STAGE_MAX_OUTPUT_TOKENS,
    AeMoGenerationClientError,
    AeMoGenerationConfigurationError,
    HttpAeMoGenerationClient,
    build_default_ae_mo_generation_client,
    resolve_ae_mo_generation_timeout_budget,
)


REQUEST_ID = "request-p65-s1"
TRACE_ID = "1" * 32
ALIAS = "general-llm-default"


def _response(status_code: int, body: object, **headers: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json", **headers},
        request=httpx.Request("GET", "http://mo.test"),
    )


def _generation_response(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mo_generation_id": "mo-generation-1",
        "alias": ALIAS,
        "model_revision": "Qwen3.5-4B",
        "deployment_id": "vllm-generation-http",
        "provider_type": "vllm-openai-compatible",
        "output": {"type": "text", "text": '{"intent_label":"ANSWER"}'},
        "finish_reason": "STOP",
        "usage": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
        "runtime_metadata": {
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
            "queue_ms": 1,
            "provider_ms": 8,
            "total_ms": 9,
            "route_id": "route-general-llm-default",
            "admission_decision": "ACCEPTED",
            "provider_request_id": "provider-request-1",
        },
        "created_at": "2026-10-16T01:00:00Z",
        "updated_at": "2026-10-16T01:00:01Z",
    }
    payload.update(changes)
    return payload


def _route(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "route_health_schema_version": "mo_provider_route_health.v1",
        "provider_capability": "generation",
        "alias": ALIAS,
        "route_id": "route-general-llm-default",
        "deployment_id": "vllm-generation-http",
        "model_revision": "Qwen3.5-4B",
        "status": "READY",
        "source": "active_preflight",
        "ok": True,
        "checked_at": "2026-10-16T01:00:00Z",
        "latency_ms": 7,
        "failure_code": None,
        "retryable": False,
        "degraded": False,
    }
    payload.update(changes)
    return payload


def _readiness(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "provider_routes",
        "ok": True,
        "provider_readiness_schema_version": "mo_provider_readiness.v1",
        "provider_mode": "live",
        "readiness_status": "READY",
        "checked_at": "2026-10-16T01:00:00Z",
        "expires_at": "2026-10-16T01:00:30Z",
        "cache_status": "FRESH",
        "required_capabilities": ["embedding", "reranking", "generation"],
        "summary": {
            "required_count": 3,
            "route_count": 1,
            "status_counts": {
                "READY": 1,
                "DEGRADED": 0,
                "UNAVAILABLE": 0,
                "UNKNOWN": 0,
            },
        },
        "routes": [_route()],
        "failure_code": None,
        "error_code": None,
    }
    payload.update(changes)
    return payload


def _client(requester, **changes: object) -> HttpAeMoGenerationClient:
    values = {
        "base_url": "http://mo.test/",
        "service_token": "service-token",
        "requester": requester,
    }
    values.update(changes)
    return HttpAeMoGenerationClient(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("stage", "max_output_tokens"),
    sorted(P65_STAGE_MAX_OUTPUT_TOKENS.items()),
)
def test_generate_candidate_enforces_closed_wire_shape(
    stage: str,
    max_output_tokens: int,
) -> None:
    observed: dict[str, object] = {}

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        observed.update(method=method, url=url, **kwargs)
        return _response(200, _generation_response())

    result = _client(request).generate_candidate(
        semantic_stage=stage,
        messages=(
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "untrusted input"},
        ),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    payload = observed["json"]
    assert isinstance(payload, dict)
    assert payload == {
        "request_schema_version": "cx_mo_generation_request.v1",
        "client_request_id": REQUEST_ID,
        "trace_id": TRACE_ID,
        "alias": ALIAS,
        "provider_capability": "generation",
        "messages": [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "untrusted input"},
        ],
        "response_format": {"type": "json_object"},
        "reasoning_mode": "disabled",
        "max_output_tokens": max_output_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    assert observed["method"] == "POST"
    assert observed["url"] == "http://mo.test/api/v1/generations"
    headers = observed["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer service-token"
    assert headers["X-Request-ID"] == REQUEST_ID
    assert headers["X-Service-ID"] == "nex-ae-api"
    assert TRACE_ID in headers["traceparent"]
    assert observed["timeout"] == 130.0
    assert result.model_profile == ALIAS
    assert result.model_ref == "Qwen3.5-4B"
    assert result.output_text == '{"intent_label":"ANSWER"}'
    assert result.provider_output_sha256 == (
        hashlib.sha256(result.output_text.encode()).hexdigest()
    )
    assert result.provider_output_size_bytes == len(result.output_text.encode())
    assert "intent_label" not in repr(result)


def test_generate_candidate_issues_test_mock_service_token() -> None:
    observed: dict[str, object] = {}

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        observed.update(kwargs)
        return _response(200, _generation_response())

    client = HttpAeMoGenerationClient(
        base_url="http://mo.test",
        requester=request,
        auth_environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"},
    )
    client.generate_candidate(
        semantic_stage="INTENT",
        messages=({"role": "user", "content": "hello"},),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert str(observed["headers"]["Authorization"]).startswith("Bearer ")  # type: ignore[index]


def test_missing_signed_service_token_fails_closed_without_http_call() -> None:
    called = False

    def request(*args: object, **kwargs: object) -> httpx.Response:
        nonlocal called
        called = True
        return _response(200, _generation_response())

    client = HttpAeMoGenerationClient(
        base_url="http://mo.test",
        requester=request,
        auth_environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"},
    )
    with pytest.raises(AeMoGenerationClientError) as raised:
        client.generate_candidate(
            semantic_stage="INTENT",
            messages=({"role": "user", "content": "hello"},),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code == "PROVIDER_NOT_READY"
    assert raised.value.retryable is False
    assert raised.value.upstream_error_code == "ae.outbound_service_token_missing"
    assert called is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("semantic_stage", "WRITE"),
        ("request_id", ""),
        ("request_id", "x" * 201),
        ("trace_id", "not-a-trace"),
        ("trace_id", "A" * 32),
    ],
)
def test_generation_identifiers_and_stage_fail_closed(field: str, value: str) -> None:
    arguments = {
        "semantic_stage": "INTENT",
        "messages": ({"role": "user", "content": "hello"},),
        "request_id": REQUEST_ID,
        "trace_id": TRACE_ID,
    }
    arguments[field] = value

    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(lambda *args, **kwargs: _response(200, _generation_response())).generate_candidate(  # type: ignore[arg-type]
            **arguments
        )

    assert raised.value.error_code == "AE_MO_GENERATION_REQUEST_INVALID"


@pytest.mark.parametrize(
    "messages",
    [
        (),
        "not-a-sequence",
        tuple({"role": "user", "content": "x"} for _ in range(17)),
        ({"role": "tool", "content": "x"},),
        ({"role": "user", "content": " "},),
        ({"role": "user", "content": "x", "api_key": "forbidden"},),
        ({"role": "user", "content": "x" * 65_537},),
        (
            {"role": "user", "content": "x" * 65_536},
            {"role": "user", "content": "y" * 65_536},
            {"role": "user", "content": "z"},
        ),
    ],
)
def test_message_shape_and_bounds_fail_closed(messages: object) -> None:
    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(lambda *args, **kwargs: _response(200, _generation_response())).generate_candidate(  # type: ignore[arg-type]
            semantic_stage="INTENT",
            messages=messages,  # type: ignore[arg-type]
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code == "AE_MO_GENERATION_REQUEST_INVALID"


@pytest.mark.parametrize(
    ("error", "error_code", "status_code"),
    [
        (httpx.ReadTimeout("slow"), "PROVIDER_TIMEOUT", 504),
        (httpx.ConnectError("down"), "PROVIDER_NOT_READY", 503),
    ],
)
def test_transport_errors_are_normalized(
    error: Exception,
    error_code: str,
    status_code: int,
) -> None:
    def request(*args: object, **kwargs: object) -> httpx.Response:
        raise error

    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(request).generate_candidate(
            semantic_stage="INTENT",
            messages=({"role": "user", "content": "hello"},),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code == error_code
    assert raised.value.status_code == status_code
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("status", "body", "expected_code", "retryable"),
    [
        (408, {}, "PROVIDER_TIMEOUT", True),
        (429, {"error_code": "mo.capacity_limited"}, "PROVIDER_RATE_LIMIT", True),
        (
            503,
            {"error_code": "mo.remote_generation_not_configured"},
            "PROVIDER_NOT_READY",
            True,
        ),
        (500, {"error_code": "mo.internal"}, "PROVIDER_SERVER_ERROR", True),
        (422, {"error_code": "mo.request_invalid"}, "PROVIDER_RESPONSE_INVALID", False),
        (401, {"error_code": "mo.auth_failed"}, "PROVIDER_NOT_READY", False),
    ],
)
def test_http_failures_map_to_p65_taxonomy(
    status: int,
    body: dict[str, object],
    expected_code: str,
    retryable: bool,
) -> None:
    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(lambda *args, **kwargs: _response(status, body)).generate_candidate(
            semantic_stage="INTENT",
            messages=({"role": "user", "content": "hello"},),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code == expected_code
    assert raised.value.retryable is retryable
    assert raised.value.upstream_error_code == body.get("error_code")


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [("4", 4.0), ("invalid", None), ("301", None), ("-1", None)],
)
def test_rate_limit_retry_after_is_bounded(
    retry_after: str,
    expected: float | None,
) -> None:
    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(
            lambda *args, **kwargs: _response(
                429,
                {"error_code": 123, "detail": "private ignored"},
                **{"Retry-After": retry_after},
            )
        ).generate_candidate(
            semantic_stage="INTENT",
            messages=({"role": "user", "content": "hello"},),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.retry_after_seconds == expected
    assert raised.value.upstream_error_code is None
    assert "private ignored" not in raised.value.detail


def test_non_json_error_body_uses_safe_mapping() -> None:
    response = httpx.Response(
        500,
        content=b"provider endpoint leaked here",
        request=httpx.Request("POST", "http://mo.test"),
    )
    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(lambda *args, **kwargs: response).generate_candidate(
            semantic_stage="INTENT",
            messages=({"role": "user", "content": "hello"},),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code == "PROVIDER_SERVER_ERROR"
    assert "leaked" not in raised.value.detail


@pytest.mark.parametrize(
    "body",
    [
        ["not-an-object"],
        {**_generation_response(), "api_key": "secret"},
        {**_generation_response(), "unexpected": True},
        _generation_response(alias="other-alias"),
        _generation_response(output={"type": "json", "text": "{}"}),
        _generation_response(output={"type": "text", "text": " "}),
        _generation_response(usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 5}),
        _generation_response(runtime_metadata={}),
        _generation_response(created_at="no-timezone"),
    ],
)
def test_success_response_contract_drift_fails_closed(body: object) -> None:
    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(lambda *args, **kwargs: _response(200, body)).generate_candidate(
            semantic_stage="INTENT",
            messages=({"role": "user", "content": "hello"},),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code == "PROVIDER_RESPONSE_INVALID"
    assert raised.value.retryable is False


def test_invalid_json_success_response_fails_closed() -> None:
    response = httpx.Response(
        200,
        content=b"not-json",
        request=httpx.Request("POST", "http://mo.test"),
    )
    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(lambda *args, **kwargs: response).generate_candidate(
            semantic_stage="INTENT",
            messages=({"role": "user", "content": "hello"},),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code == "PROVIDER_RESPONSE_INVALID"


def test_required_mode_readiness_requires_live_matching_active_preflight() -> None:
    observed: dict[str, object] = {}

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        observed.update(method=method, url=url, **kwargs)
        return _response(200, _readiness())

    readiness = _client(request, readiness_timeout_seconds=7).check_required_mode_readiness(
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert observed["method"] == "GET"
    assert observed["url"] == "http://mo.test/api/v1/provider-route-health"
    assert observed["json"] is None
    assert observed["timeout"] == 7.0
    assert readiness.provider_mode == "live"
    assert readiness.readiness_status == "READY"
    assert readiness.model_profile == ALIAS
    assert readiness.model_ref == "Qwen3.5-4B"
    assert readiness.source == "active_preflight"


@pytest.mark.parametrize(
    "body",
    [
        _readiness(provider_mode="mock"),
        _readiness(readiness_status="NOT_READY", ok=False),
        _readiness(required_capabilities=["embedding", "reranking"]),
        _readiness(routes="invalid"),
        _readiness(routes=[]),
        _readiness(routes=[_route(), _route()]),
        _readiness(routes=[_route(status="DEGRADED", ok=False, degraded=True)]),
        _readiness(routes=[_route(source="mock_registry")]),
        _readiness(cache_status="STALE"),
        _readiness(provider_readiness_schema_version="future.v2"),
        {**_readiness(), "provider_endpoint": "private"},
    ],
)
def test_required_mode_readiness_fails_closed(body: object) -> None:
    with pytest.raises(AeMoGenerationClientError) as raised:
        _client(lambda *args, **kwargs: _response(200, body)).check_required_mode_readiness(
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code in {"PROVIDER_NOT_READY", "PROVIDER_RESPONSE_INVALID"}


def test_default_timeout_budget_is_above_mo_retry_budget() -> None:
    budget = resolve_ae_mo_generation_timeout_budget({})

    assert budget.mo_generation_budget_seconds == 125
    assert budget.minimum_client_timeout_seconds == 130
    assert budget.client_timeout_seconds == 130


def test_dynamic_default_timeout_grows_with_mo_budget() -> None:
    budget = resolve_ae_mo_generation_timeout_budget(
        {
            AE_MO_GENERATION_BUDGET_ENV: "218",
            AE_MO_TIMEOUT_SAFETY_MARGIN_ENV: "7",
        }
    )

    assert budget.minimum_client_timeout_seconds == 225
    assert budget.client_timeout_seconds == 225


def test_configured_timeout_below_mo_budget_fails_closed() -> None:
    with pytest.raises(AeMoGenerationConfigurationError) as raised:
        resolve_ae_mo_generation_timeout_budget({AE_MO_GENERATION_TIMEOUT_ENV: "129"})

    assert raised.value.error_code == "AE_MO_GENERATION_TIMEOUT_TOO_SHORT"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (AE_MO_GENERATION_BUDGET_ENV, "bad"),
        (AE_MO_GENERATION_BUDGET_ENV, "0"),
        (AE_MO_GENERATION_TIMEOUT_ENV, "bad"),
        (AE_MO_TIMEOUT_SAFETY_MARGIN_ENV, ""),
    ],
)
def test_invalid_timeout_configuration_is_rejected(name: str, value: str) -> None:
    environ = {name: value}
    if name == AE_MO_TIMEOUT_SAFETY_MARGIN_ENV and value == "":
        environ[name] = "false"
    with pytest.raises(AeMoGenerationConfigurationError) as raised:
        resolve_ae_mo_generation_timeout_budget(environ)

    assert raised.value.error_code == "AE_MO_TIMEOUT_INVALID"


def test_default_builder_uses_safe_service_configuration() -> None:
    client = build_default_ae_mo_generation_client(
        {
            "NEX_MO_BASE_URL": "https://mo.internal/",
            AE_MO_GENERATION_ALIAS_ENV: "planner-default",
            AE_MO_GENERATION_TIMEOUT_ENV: "140",
            AE_MO_READINESS_TIMEOUT_ENV: "8",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )

    assert client.base_url == "https://mo.internal"
    assert client.generation_alias == "planner-default"
    assert client.generation_timeout_seconds == 140
    assert client.readiness_timeout_seconds == 8


@pytest.mark.parametrize(
    "environ",
    [
        {AE_MO_GENERATION_ALIAS_ENV: "https://provider.private"},
        {"NEX_MO_BASE_URL": "http://user:secret@mo.internal"},
        {AE_MO_READINESS_TIMEOUT_ENV: "0"},
    ],
)
def test_default_builder_rejects_unsafe_configuration(
    environ: dict[str, str],
) -> None:
    with pytest.raises(AeMoGenerationConfigurationError):
        build_default_ae_mo_generation_client(environ)


def test_runtime_timeout_mutation_is_rejected_before_http() -> None:
    client = _client(
        lambda *args, **kwargs: _response(200, _generation_response()),
        generation_timeout_seconds=0,
    )
    with pytest.raises(AeMoGenerationConfigurationError) as raised:
        client.generate_candidate(
            semantic_stage="INTENT",
            messages=({"role": "user", "content": "hello"},),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert raised.value.error_code == "AE_MO_TIMEOUT_INVALID"
