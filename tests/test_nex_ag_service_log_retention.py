from __future__ import annotations

from typing import Any

import httpx
import pytest

from nex_ag.service_log_retention import (
    AG_SERVICE_LOG_RETENTION_TIMEOUT_ENV,
    AgServiceLogRetentionError,
    HttpAgServiceLogRetentionClient,
    ag_service_log_retention_base_url_env,
    ag_service_log_retention_token_env,
    build_ag_service_log_retention_base_urls,
    build_ag_service_log_retention_service_tokens,
    build_default_ag_service_log_retention_client,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def test_ag_service_log_retention_env_helpers_match_service_conventions() -> None:
    assert ag_service_log_retention_base_url_env("nex-cx") == "NEX_CX_BASE_URL"
    assert ag_service_log_retention_token_env("nex-cx") == (
        "NEX_AG_TO_CX_SERVICE_TOKEN"
    )

    with pytest.raises(AgServiceLogRetentionError) as exc_info:
        ag_service_log_retention_base_url_env("unknown")

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "ag.service_log_retention_service_invalid"


def test_build_default_ag_service_log_retention_client_reads_env_values() -> None:
    env = {
        "NEX_CX_BASE_URL": "http://cx.local/",
        "NEX_AG_TO_CX_SERVICE_TOKEN": "cx-token",
        AG_SERVICE_LOG_RETENTION_TIMEOUT_ENV: "1.5",
    }

    base_urls = build_ag_service_log_retention_base_urls(env)
    tokens = build_ag_service_log_retention_service_tokens(env)
    client = build_default_ag_service_log_retention_client(env)

    assert base_urls["nex-cx"] == "http://cx.local"
    assert base_urls["nex-mo"] == "http://127.0.0.1:8105"
    assert tokens == {"nex-cx": "cx-token"}
    assert client.service_base_urls["nex-cx"] == "http://cx.local"
    assert client.service_tokens["nex-cx"] == "cx-token"
    assert client.timeout_seconds == 1.5


@pytest.mark.parametrize("timeout_value", ["0", "-1", "slow"])
def test_build_default_ag_service_log_retention_client_rejects_bad_timeout(
    timeout_value: str,
) -> None:
    with pytest.raises(AgServiceLogRetentionError) as exc_info:
        build_default_ag_service_log_retention_client(
            {AG_SERVICE_LOG_RETENTION_TIMEOUT_ENV: timeout_value}
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "ag.service_log_retention_timeout_invalid"


def test_http_ag_service_log_retention_client_posts_guarded_payload(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "retention_execution_schema_version": (
                    "service_log_retention_execution.v1"
                ),
                "service_id": "nex-cx",
                "mode": "EXECUTE",
                "execution_status": "SUCCEEDED",
                "candidate_count": 2,
                "deleted_count": 1,
                "delete_enabled": True,
            },
        )

    monkeypatch.setattr("nex_ag.service_log_retention.httpx.request", fake_request)
    client = HttpAgServiceLogRetentionClient(
        service_base_urls={"nex-cx": "http://cx.local/"},
        service_tokens={"nex-cx": "fixed-token"},
        timeout_seconds=2.0,
    )

    payload = client.purge_logs(
        "nex-cx",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        retention_cutoff="2026-07-06T00:00:00Z",
        retention_days=30,
        checked_at="2026-08-05T00:00:00Z",
        dry_run=False,
        delete_enabled=True,
        max_delete_count=10,
        requested_by={
            "actor_type": "service",
            "actor_id": "nex-ag",
            "service_id": "nex-ag",
        },
        idempotency_key="purge-001",
    )

    assert payload["execution_status"] == "SUCCEEDED"
    assert calls == [
        {
            "method": "POST",
            "url": "http://cx.local/internal/v1/service-logs/retention/purge",
            "json": {
                "retention_cutoff": "2026-07-06T00:00:00Z",
                "retention_days": 30,
                "checked_at": "2026-08-05T00:00:00Z",
                "dry_run": False,
                "delete_enabled": True,
                "max_delete_count": 10,
                "requested_by": {
                    "actor_type": "service",
                    "actor_id": "nex-ag",
                    "service_id": "nex-ag",
                },
                "idempotency_key": "purge-001",
            },
            "headers": {
                "Authorization": "Bearer fixed-token",
                "X-Request-ID": REQUEST_ID,
                "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-ag",
            },
            "timeout": 2.0,
        }
    ]


def test_http_ag_service_log_retention_client_maps_failures(monkeypatch) -> None:
    assert str(
        AgServiceLogRetentionError(
            status_code=503,
            error_code="example",
            detail="example failure",
        )
    ) == "example failure"

    def problem_request(method, url, **kwargs):
        return httpx.Response(
            409,
            json={
                "error_code": "service_log_retention.execute_not_enabled",
                "detail": "execute purge requires delete_enabled.",
                "retryable": False,
            },
        )

    monkeypatch.setattr("nex_ag.service_log_retention.httpx.request", problem_request)
    client = HttpAgServiceLogRetentionClient(
        service_base_urls={"nex-cx": "http://cx.local"}
    )

    with pytest.raises(AgServiceLogRetentionError) as problem:
        client.purge_logs(
            "nex-cx",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            retention_cutoff="2026-07-06T00:00:00Z",
        )

    assert problem.value.status_code == 409
    assert problem.value.error_code == "service_log_retention.execute_not_enabled"

    def unavailable_request(method, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        "nex_ag.service_log_retention.httpx.request",
        unavailable_request,
    )
    with pytest.raises(AgServiceLogRetentionError) as unavailable:
        client.purge_logs(
            "nex-cx",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            retention_cutoff="2026-07-06T00:00:00Z",
        )

    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True

    def malformed_request(method, url, **kwargs):
        return httpx.Response(200, content=b"{not-json")

    monkeypatch.setattr(
        "nex_ag.service_log_retention.httpx.request",
        malformed_request,
    )
    with pytest.raises(AgServiceLogRetentionError) as malformed:
        client.purge_logs(
            "nex-cx",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            retention_cutoff="2026-07-06T00:00:00Z",
        )

    assert malformed.value.error_code == "ag.service_log_retention_response_invalid"

    def list_response_request(method, url, **kwargs):
        return httpx.Response(200, json=["not", "object"])

    monkeypatch.setattr(
        "nex_ag.service_log_retention.httpx.request",
        list_response_request,
    )
    with pytest.raises(AgServiceLogRetentionError) as list_response:
        client.purge_logs(
            "nex-cx",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            retention_cutoff="2026-07-06T00:00:00Z",
        )

    assert list_response.value.error_code == (
        "ag.service_log_retention_response_invalid"
    )


def test_http_ag_service_log_retention_client_rejects_bad_or_missing_endpoint() -> None:
    client = HttpAgServiceLogRetentionClient(service_base_urls={"nex-cx": ""})

    with pytest.raises(AgServiceLogRetentionError) as invalid_service:
        client.purge_logs(
            "unknown",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            retention_cutoff="2026-07-06T00:00:00Z",
        )
    with pytest.raises(AgServiceLogRetentionError) as missing_endpoint:
        client.purge_logs(
            "nex-cx",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            retention_cutoff="2026-07-06T00:00:00Z",
        )

    assert invalid_service.value.status_code == 400
    assert missing_endpoint.value.status_code == 404
