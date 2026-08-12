from __future__ import annotations

from typing import Any

import httpx
import pytest

from nex_ae_api.oa_session_client import (
    AE_OA_SESSION_CLIENT_SCHEMA_VERSION,
    HttpOaUserSessionClient,
    OaUserSessionClientError,
    build_default_oa_user_session_client,
    oa_session_issue_payload,
)


def login_request() -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "scopes": ["workspace:use", "documents:upload"],
        "ttl_seconds": 1800,
    }


def test_http_oa_session_client_calls_issue_introspect_and_revoke_shapes() -> None:
    calls: list[dict[str, Any]] = []

    def requester(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/issue"):
            return httpx.Response(
                200,
                json={
                    "session_issue_schema_version": "oa_session_issue.v1",
                    "session": {"session_id": "session/a"},
                },
            )
        if url.endswith("/introspect"):
            return httpx.Response(
                200,
                json={
                    "session_introspection_schema_version": (
                        "oa_session_introspection.v1"
                    ),
                    "active": True,
                },
            )
        return httpx.Response(
            200,
            json={
                "session_revocation_schema_version": "oa_session_revocation.v1",
                "revoked": True,
            },
        )

    client = HttpOaUserSessionClient(
        base_url="http://oa.local/",
        service_token="service-secret",
        timeout_seconds=2.5,
        requester=requester,
    )

    issued = client.issue_session(
        login_request(),
        request_id="request-a",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    introspection = client.introspect_session(
        " session/a ",
        request_id="request-b",
        trace_id="5bf92f3577b34da6a3ce929d0e0e4736",
    )
    revocation = client.revoke_session(
        "session/a",
        request_id="request-c",
        trace_id="6bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert AE_OA_SESSION_CLIENT_SCHEMA_VERSION == "ae_oa_session_client.v1"
    assert issued["session"]["session_id"] == "session/a"
    assert introspection["active"] is True
    assert revocation["revoked"] is True
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://oa.local/internal/v1/auth/user-sessions/issue"
    assert calls[0]["json"] == {
        "tenant_id": "tenant-a",
        "subject_id": "user-a",
        "requested_scopes": ["workspace:use", "documents:upload"],
        "ttl_seconds": 1800,
    }
    assert calls[1]["json"] == {"session_id": "session/a"}
    assert calls[2]["url"].endswith("/user-sessions/session%2Fa/revoke")
    for call in calls:
        assert call["headers"]["Authorization"] == "Bearer service-secret"
        assert call["headers"]["X-Service-ID"] == "nex-ae-api"
        assert call["timeout"] == 2.5


def test_oa_session_issue_payload_rejects_malformed_login_request() -> None:
    assert oa_session_issue_payload(login_request())["subject_id"] == "user-a"

    for payload, detail in [
        ({**login_request(), "tenant_id": ""}, "tenant_id"),
        ({**login_request(), "user_id": None}, "user_id"),
        ({**login_request(), "scopes": []}, "scopes"),
        ({**login_request(), "scopes": ["workspace:use", ""]}, "scopes"),
        ({**login_request(), "ttl_seconds": True}, "ttl_seconds"),
        ({**login_request(), "ttl_seconds": 0}, "ttl_seconds"),
    ]:
        with pytest.raises(OaUserSessionClientError) as exc:
            oa_session_issue_payload(payload)
        assert exc.value.status_code == 422
        assert exc.value.error_code == "oa.session_client_request_invalid"
        assert detail in str(exc.value)


def test_http_oa_session_client_maps_problem_and_transport_failures() -> None:
    def problem_request(*_: Any, **__: Any) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "error_code": "oa.session_registry_unavailable",
                "detail": "registry unavailable",
                "retryable": True,
            },
        )

    def timeout_request(*_: Any, **__: Any) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    def down_request(*_: Any, **__: Any) -> httpx.Response:
        raise httpx.ConnectError("offline")

    for requester, status_code, error_code in [
        (problem_request, 503, "oa.session_registry_unavailable"),
        (timeout_request, 504, "oa.session_client_timeout"),
        (down_request, 503, "oa.session_client_unavailable"),
    ]:
        client = HttpOaUserSessionClient(requester=requester)
        with pytest.raises(OaUserSessionClientError) as exc:
            client.introspect_session(
                "session-a",
                request_id="request-a",
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            )
        assert exc.value.status_code == status_code
        assert exc.value.error_code == error_code
        assert exc.value.retryable is True


def test_http_oa_session_client_rejects_invalid_response_payloads() -> None:
    for response in [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=["not", "object"]),
    ]:
        client = HttpOaUserSessionClient(
            requester=lambda *args, **kwargs: response,
        )
        with pytest.raises(OaUserSessionClientError) as exc:
            client.revoke_session(
                "session-a",
                request_id="request-a",
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            )
        assert exc.value.error_code == "oa.session_client_response_invalid"


def test_default_oa_session_client_reads_safe_env_and_validates_timeout() -> None:
    client = build_default_oa_user_session_client(
        {
            "NEX_OA_BASE_URL": "http://oa.test",
            "NEX_AE_TO_OA_SERVICE_TOKEN": "pre-issued-service-token",
            "NEX_AE_OA_SESSION_TIMEOUT_SECONDS": "1.25",
        }
    )

    assert client.base_url == "http://oa.test"
    assert client.service_token == "pre-issued-service-token"
    assert client.timeout_seconds == 1.25
    default_client = build_default_oa_user_session_client({})
    blank_timeout_client = build_default_oa_user_session_client(
        {"NEX_AE_OA_SESSION_TIMEOUT_SECONDS": ""}
    )
    assert default_client.base_url == "http://127.0.0.1:8101"
    assert default_client.service_token is None
    assert default_client.timeout_seconds == 5.0
    assert blank_timeout_client.timeout_seconds == 5.0

    for timeout in ["0", "-1", "slow"]:
        with pytest.raises(OaUserSessionClientError) as exc:
            build_default_oa_user_session_client(
                {"NEX_AE_OA_SESSION_TIMEOUT_SECONDS": timeout}
            )
        assert exc.value.error_code == "oa.session_client_timeout_invalid"
