from __future__ import annotations

import json

from fastapi.testclient import TestClient

from nex_oa.auth_boundary import (
    OA_IDENTITY_AUTH_BOUNDARY_SCHEMA_VERSION,
    build_identity_auth_boundary_report,
    register_identity_auth_boundary_routes,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-oa")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-Request-ID": REQUEST_ID,
    }


def build_client() -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_identity_auth_boundary_routes(app)
    return TestClient(app)


def test_identity_auth_boundary_report_freezes_authority_split() -> None:
    report = build_identity_auth_boundary_report()
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["boundary_schema_version"] == OA_IDENTITY_AUTH_BOUNDARY_SCHEMA_VERSION
    assert report["service_id"] == "nex-oa"
    assert report["current_state"]["stable_subject_registry"] is True
    assert report["current_state"]["oa_backed_session_issuance"] is False
    assert report["target_state"]["ae_session_facade_delegates_to_oa"] is True
    assert "future_user_session_issuance" in report["service_boundaries"]["nex-oa"]["owns"]
    assert "durable_identity_authority" in report["service_boundaries"]["nex-ae-api"][
        "does_not_own"
    ]
    assert [item["slice"] for item in report["slice_sequence"]] == [
        "0242",
        "0243",
        "0244",
    ]
    assert report["metadata"] == {
        "raw_tokens_included": False,
        "passwords_included": False,
        "provider_endpoints_included": False,
        "database_urls_included": False,
        "session_cookie_values_included": False,
    }
    assert "secret-value" not in serialized
    assert "postgresql://" not in serialized


def test_identity_auth_boundary_route_requires_service_claim_and_is_safe() -> None:
    client = build_client()

    unauthorized = client.get("/internal/v1/identity-auth-boundary")
    authorized = client.get(
        "/internal/v1/identity-auth-boundary",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert authorized.status_code == 200
    payload = authorized.json()
    assert payload["trace_id"] == TRACE_ID
    assert payload["request_id"] == REQUEST_ID
    assert payload["safe_claim_fields"] == [
        "tenant_id",
        "user_id",
        "scopes",
        "roles",
        "audience",
        "token_use",
        "issued_at",
        "expires_at",
    ]
    assert "Authorization" not in json.dumps(payload)


def test_nex_oa_entrypoint_registers_identity_auth_boundary_route() -> None:
    import nex_oa.main as main

    assert "/internal/v1/identity-auth-boundary" in {
        getattr(route, "path", "") for route in main.app.routes
    }
