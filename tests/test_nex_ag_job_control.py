from __future__ import annotations

from typing import Any

import httpx
import pytest

from nex_ag.job_control import (
    AG_JOB_CONTROL_TIMEOUT_ENV,
    AgJobControlError,
    HttpAgJobControlClient,
    ag_job_control_base_url_env,
    ag_job_control_token_env,
    build_ag_job_control_base_urls,
    build_ag_job_control_service_tokens,
    build_default_ag_job_control_client,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def test_ag_job_control_env_helpers_match_service_conventions() -> None:
    assert ag_job_control_base_url_env("nex-ae-api") == "NEX_AE_API_BASE_URL"
    assert ag_job_control_base_url_env("nex-cx") == "NEX_CX_BASE_URL"
    assert ag_job_control_token_env("nex-ae-api") == "NEX_AG_TO_AE_SERVICE_TOKEN"
    assert ag_job_control_token_env("nex-cx") == "NEX_AG_TO_CX_SERVICE_TOKEN"

    with pytest.raises(AgJobControlError) as exc_info:
        ag_job_control_base_url_env("unknown")

    assert exc_info.value.error_code == "ag.job_control_service_invalid"


def test_build_default_ag_job_control_client_reads_env_values() -> None:
    env = {
        "NEX_CX_BASE_URL": "http://cx.local/",
        "NEX_AG_TO_CX_SERVICE_TOKEN": "cx-token",
        AG_JOB_CONTROL_TIMEOUT_ENV: "1.5",
    }

    base_urls = build_ag_job_control_base_urls(env)
    tokens = build_ag_job_control_service_tokens(env)
    client = build_default_ag_job_control_client(env)

    assert base_urls["nex-cx"] == "http://cx.local"
    assert base_urls["nex-mo"] == "http://127.0.0.1:8105"
    assert tokens == {"nex-cx": "cx-token"}
    assert client.service_base_urls["nex-cx"] == "http://cx.local"
    assert client.service_tokens["nex-cx"] == "cx-token"
    assert client.timeout_seconds == 1.5


@pytest.mark.parametrize("timeout_value", ["0", "-1", "slow"])
def test_build_default_ag_job_control_client_rejects_bad_timeout(timeout_value: str) -> None:
    with pytest.raises(AgJobControlError) as exc_info:
        build_default_ag_job_control_client({AG_JOB_CONTROL_TIMEOUT_ENV: timeout_value})

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "ag.job_control_timeout_invalid"


def test_http_ag_job_control_client_gets_job_with_service_claim(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "job_control_schema_version": "service_job_control.v1",
                "service_id": "nex-cx",
                "action": "read",
                "job": {"job_id": "job/001"},
                "controls": {"allowed_actions": ["read"]},
            },
        )

    monkeypatch.setattr("nex_ag.job_control.httpx.request", fake_request)
    client = HttpAgJobControlClient(
        service_base_urls={"nex-cx": "http://cx.local/"},
        service_tokens={"nex-cx": "fixed-token"},
        timeout_seconds=2.0,
    )

    payload = client.get_job(
        "nex-cx",
        "job/001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert payload["job"]["job_id"] == "job/001"
    assert calls == [
        {
            "method": "GET",
            "url": "http://cx.local/internal/v1/jobs/job%2F001",
            "json": None,
            "headers": {
                "Authorization": "Bearer fixed-token",
                "X-Request-ID": REQUEST_ID,
                "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-ag",
            },
            "timeout": 2.0,
        }
    ]


def test_http_ag_job_control_client_posts_cancel_and_retry_payloads(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "job_control_schema_version": "service_job_control.v1",
                "service_id": "nex-cx",
                "action": "control",
                "job": {"job_id": "job-001"},
                "controls": {"allowed_actions": ["read"]},
            },
        )

    monkeypatch.setattr("nex_ag.job_control.httpx.request", fake_request)
    client = HttpAgJobControlClient(service_base_urls={"nex-cx": "http://cx.local"})

    client.cancel_job("nex-cx", "job-001", request_id=REQUEST_ID, trace_id=TRACE_ID)
    client.retry_job(
        "nex-cx",
        "job-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        error_code="operator.retry",
        detail="Operator requested retry.",
        observed_at="2026-08-05T00:00:00Z",
    )

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://cx.local/internal/v1/jobs/job-001/cancel"
    assert calls[0]["json"] is None
    assert calls[0]["headers"]["Authorization"].startswith("Bearer nex-mock-service.")
    assert calls[1]["method"] == "POST"
    assert calls[1]["url"] == "http://cx.local/internal/v1/jobs/job-001/retry"
    assert calls[1]["json"] == {
        "error_code": "operator.retry",
        "detail": "Operator requested retry.",
        "observed_at": "2026-08-05T00:00:00Z",
    }


def test_http_ag_job_control_client_maps_problem_responses(monkeypatch) -> None:
    def fake_request(method, url, **kwargs):
        return httpx.Response(
            409,
            json={
                "error_code": "job.retry_status_invalid",
                "detail": "only RUNNING jobs can be retried",
                "retryable": False,
            },
        )

    monkeypatch.setattr("nex_ag.job_control.httpx.request", fake_request)
    client = HttpAgJobControlClient(service_base_urls={"nex-cx": "http://cx.local"})

    with pytest.raises(AgJobControlError) as exc_info:
        client.retry_job("nex-cx", "job-001", request_id=REQUEST_ID, trace_id=TRACE_ID)

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "job.retry_status_invalid"
    assert exc_info.value.retryable is False


def test_http_ag_job_control_client_maps_transport_and_json_failures(monkeypatch) -> None:
    def fail_request(method, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("nex_ag.job_control.httpx.request", fail_request)
    client = HttpAgJobControlClient(service_base_urls={"nex-cx": "http://cx.local"})

    with pytest.raises(AgJobControlError) as unavailable:
        client.get_job("nex-cx", "job-001", request_id=REQUEST_ID, trace_id=TRACE_ID)

    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True

    def invalid_json(method, url, **kwargs):
        return httpx.Response(200, json=["not", "object"])

    monkeypatch.setattr("nex_ag.job_control.httpx.request", invalid_json)
    with pytest.raises(AgJobControlError) as invalid_response:
        client.get_job("nex-cx", "job-001", request_id=REQUEST_ID, trace_id=TRACE_ID)

    assert invalid_response.value.error_code == "ag.job_control_response_invalid"


def test_http_ag_job_control_client_rejects_invalid_or_missing_service_endpoint() -> None:
    client = HttpAgJobControlClient(service_base_urls={"nex-cx": ""})

    with pytest.raises(AgJobControlError) as invalid_service:
        client.get_job("unknown", "job-001", request_id=REQUEST_ID, trace_id=TRACE_ID)
    with pytest.raises(AgJobControlError) as missing_endpoint:
        client.get_job("nex-cx", "job-001", request_id=REQUEST_ID, trace_id=TRACE_ID)

    assert invalid_service.value.status_code == 400
    assert missing_endpoint.value.status_code == 404
