from __future__ import annotations

import json

from fastapi.testclient import TestClient

from nex_oa.credential_delivery import (
    OA_SESSION_CREDENTIAL_DELIVERY_SCHEMA_VERSION,
    build_session_credential_delivery_boundary_report,
    register_session_credential_delivery_boundary_routes,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers(*, audience: str = "nex-oa") -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience=audience)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-Request-ID": REQUEST_ID,
    }


def build_client() -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_session_credential_delivery_boundary_routes(app)
    return TestClient(app)


def test_session_credential_delivery_report_freezes_oa_ae_decision() -> None:
    report = build_session_credential_delivery_boundary_report()
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["boundary_schema_version"] == (
        OA_SESSION_CREDENTIAL_DELIVERY_SCHEMA_VERSION
    )
    assert report["decision"] == {
        "selected_delivery_mode": "ae_http_only_cookie_with_oa_session_id",
        "oa_response_contains_raw_user_token": False,
        "browser_json_contains_cookie_value": False,
        "ae_sets_browser_cookie": True,
        "ae_deletes_browser_cookie": True,
        "ae_route_guard_uses_oa_introspection": True,
        "oa_session_id_is_authoritative_handle": True,
    }
    assert report["cookie_policy"]["owner_service"] == "nex-ae-api"
    assert report["cookie_policy"]["cookie_value_kind"] == "opaque_oa_session_id"
    assert "session_introspection" in report["service_responsibilities"]["nex-oa"]
    assert "http_only_cookie_set_and_delete" in report["service_responsibilities"][
        "nex-ae-api"
    ]
    assert [item["slice"] for item in report["delegation_sequence"]] == [
        "0246",
        "0247",
        "0248",
        "0249",
    ]
    assert report["metadata"] == {
        "raw_tokens_included": False,
        "cookie_values_included": False,
        "passwords_included": False,
        "service_credentials_included": False,
        "database_urls_included": False,
    }
    assert "secret-value" not in serialized
    assert "nuri1004" not in serialized
    assert "postgresql://" not in serialized


def test_session_credential_delivery_route_requires_service_claim_and_is_safe() -> None:
    client = build_client()
    missing = client.get("/internal/v1/auth/session-credential-delivery-boundary")
    wrong_audience = client.get(
        "/internal/v1/auth/session-credential-delivery-boundary",
        headers=auth_headers(audience="nex-cx"),
    )
    authorized = client.get(
        "/internal/v1/auth/session-credential-delivery-boundary",
        headers=auth_headers(),
    )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    assert authorized.status_code == 200
    payload = authorized.json()
    assert payload["trace_id"] == TRACE_ID
    assert payload["request_id"] == REQUEST_ID
    assert payload["forbidden_delivery_payloads"] == [
        "raw_user_access_token_in_json",
        "service_token_in_browser",
        "password_or_login_secret",
        "external_identity_provider_payload",
        "database_url",
        "cookie_value_in_logs_or_evidence",
    ]
    assert "Authorization" not in json.dumps(payload)


def test_nex_oa_entrypoint_registers_session_credential_boundary_route() -> None:
    import nex_oa.main as main

    assert "/internal/v1/auth/session-credential-delivery-boundary" in {
        getattr(route, "path", "") for route in main.app.routes
    }
