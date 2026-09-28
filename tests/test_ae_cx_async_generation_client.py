from __future__ import annotations

import json

import httpx
import pytest

from nex_ae_api.cx_async_generation_client import (
    CxAsyncGenerationClientError,
    HttpCxAsyncGenerationClient,
)


def _payload() -> dict:
    return {
        "ownership_ref": {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-1"},
            "owner_subject_ref": {"type": "oa.user", "id": "user-1"},
        },
        "messages": [{"role": "user", "content": "private"}],
    }


def _response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "http://cx.test"),
    )


def test_admit_generation_forwards_owner_trace_and_idempotency(monkeypatch) -> None:
    observed = {}

    def request(method, url, **kwargs):
        observed.update(method=method, url=url, **kwargs)
        return _response(202, {"admission_status": "ENQUEUED", "job": {}})

    monkeypatch.setattr(httpx, "request", request)
    client = HttpCxAsyncGenerationClient(
        base_url="http://cx.test/", service_token="service-secret", timeout_seconds=9
    )

    result = client.admit_generation(
        _payload(),
        request_id="request-1",
        trace_id="1" * 32,
        idempotency_key="interaction-1",
    )

    assert result["admission_status"] == "ENQUEUED"
    assert observed["method"] == "POST"
    assert observed["url"] == "http://cx.test/api/v1/generation-jobs"
    assert observed["json"] == _payload()
    assert observed["timeout"] == 9
    assert observed["headers"]["Authorization"] == "Bearer service-secret"
    assert observed["headers"]["Idempotency-Key"] == "interaction-1"
    assert observed["headers"]["X-NEX-Tenant-ID"] == "tenant-1"
    assert observed["headers"]["X-NEX-Subject-ID"] == "user-1"
    assert observed["headers"]["X-Request-ID"] == "request-1"
    assert "1" * 32 in observed["headers"]["traceparent"]


@pytest.mark.parametrize(
    ("method_name", "method", "suffix"),
    [
        ("get_job", "GET", ""),
        ("get_handoff", "GET", "/handoff"),
        ("cancel_job", "POST", "/cancel"),
    ],
)
def test_owner_job_operations_quote_job_id_and_send_no_body(
    monkeypatch, method_name: str, method: str, suffix: str
) -> None:
    observed = {}

    def request(request_method, url, **kwargs):
        observed.update(method=request_method, url=url, **kwargs)
        return _response(200, {"job_id": "job/one"})

    monkeypatch.setattr(httpx, "request", request)
    client = HttpCxAsyncGenerationClient(service_token="token")

    result = getattr(client, method_name)(
        "job/one",
        tenant_id="tenant-a",
        subject_id="user-a",
        request_id="request-a",
        trace_id="a" * 32,
    )

    assert result == {"job_id": "job/one"}
    assert observed["method"] == method
    assert observed["url"].endswith(f"/generation-jobs/job%2Fone{suffix}")
    assert observed["json"] is None
    assert observed["headers"]["X-NEX-Tenant-ID"] == "tenant-a"
    assert observed["headers"]["X-NEX-Subject-ID"] == "user-a"


def test_default_mock_service_token_is_issued(monkeypatch) -> None:
    observed = {}

    def request(method, url, **kwargs):
        observed.update(kwargs)
        return _response(200, {"job_id": "job-1"})

    monkeypatch.setattr(httpx, "request", request)
    HttpCxAsyncGenerationClient().get_job(
        "job-1",
        tenant_id="tenant",
        subject_id="user",
        request_id="request",
        trace_id="b" * 32,
    )

    assert observed["headers"]["Authorization"].startswith("Bearer ")
    assert len(observed["headers"]["Authorization"]) > len("Bearer ")


@pytest.mark.parametrize("field", ["job_id", "request_id", "trace_id"])
def test_required_transport_identifiers_fail_closed(monkeypatch, field: str) -> None:
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: _response(200, {}))
    values = {
        "job_id": "job",
        "tenant_id": "tenant",
        "subject_id": "user",
        "request_id": "request",
        "trace_id": "c" * 32,
    }
    values[field] = " "

    with pytest.raises(CxAsyncGenerationClientError) as exc_info:
        HttpCxAsyncGenerationClient(service_token="token").get_job(**values)

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code.endswith("request_invalid")


def test_admission_requires_idempotency_key(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: _response(200, {}))
    with pytest.raises(CxAsyncGenerationClientError):
        HttpCxAsyncGenerationClient(service_token="token").admit_generation(
            _payload(), request_id="r", trace_id="d" * 32, idempotency_key=""
        )


@pytest.mark.parametrize(
    ("exc", "status_code", "suffix"),
    [
        (httpx.ReadTimeout("slow"), 504, "timeout"),
        (httpx.ConnectError("down"), 503, "unavailable"),
    ],
)
def test_transport_failures_are_retryable(
    monkeypatch, exc: Exception, status_code: int, suffix: str
) -> None:
    def request(*args, **kwargs):
        raise exc

    monkeypatch.setattr(httpx, "request", request)
    with pytest.raises(CxAsyncGenerationClientError) as exc_info:
        HttpCxAsyncGenerationClient(service_token="token").get_job(
            "job",
            tenant_id="tenant",
            subject_id="user",
            request_id="request",
            trace_id="e" * 32,
        )

    assert exc_info.value.status_code == status_code
    assert exc_info.value.error_code.endswith(suffix)
    assert exc_info.value.retryable is True


def test_problem_response_is_normalized(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: _response(
            409,
            {
                "error_code": "cx.async_generation.conflict",
                "detail": "conflict",
                "retryable": True,
            },
        ),
    )

    with pytest.raises(CxAsyncGenerationClientError) as exc_info:
        HttpCxAsyncGenerationClient(service_token="token").get_job(
            "job",
            tenant_id="tenant",
            subject_id="user",
            request_id="request",
            trace_id="f" * 32,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "cx.async_generation.conflict"
    assert exc_info.value.detail == "conflict"
    assert exc_info.value.retryable is True
    assert str(exc_info.value) == "conflict"


def test_problem_response_uses_safe_defaults_for_invalid_json(monkeypatch) -> None:
    response = httpx.Response(
        500,
        content=b"not-json",
        request=httpx.Request("GET", "http://cx.test"),
    )
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: response)

    with pytest.raises(CxAsyncGenerationClientError) as exc_info:
        HttpCxAsyncGenerationClient(service_token="token").get_job(
            "job",
            tenant_id="tenant",
            subject_id="user",
            request_id="request",
            trace_id="0" * 32,
        )

    assert exc_info.value.error_code == "cx.async_generation.request_failed"
    assert exc_info.value.retryable is False


def test_success_response_must_be_an_object(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx, "request", lambda *args, **kwargs: _response(200, ["invalid"])
    )

    with pytest.raises(CxAsyncGenerationClientError) as exc_info:
        HttpCxAsyncGenerationClient(service_token="token").get_job(
            "job",
            tenant_id="tenant",
            subject_id="user",
            request_id="request",
            trace_id="1" * 32,
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code.endswith("response_invalid")
    assert exc_info.value.retryable is True


def test_problem_response_ignores_non_string_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: _response(
            503, {"error_code": 42, "detail": [], "retryable": "yes"}
        ),
    )

    with pytest.raises(CxAsyncGenerationClientError) as exc_info:
        HttpCxAsyncGenerationClient(service_token="token").get_job(
            "job",
            tenant_id="tenant",
            subject_id="user",
            request_id="request",
            trace_id="2" * 32,
        )

    assert exc_info.value.error_code == "cx.async_generation.request_failed"
    assert exc_info.value.detail == "CX asynchronous generation request failed."
    assert exc_info.value.retryable is False
