from __future__ import annotations

import json

from fastapi.testclient import TestClient

from nex_oa.bootstrap_login_boundary import (
    OA_USER_BOOTSTRAP_LOGIN_BOUNDARY_SCHEMA_VERSION,
    build_user_bootstrap_login_boundary_report,
    register_user_bootstrap_login_boundary_routes,
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
    register_user_bootstrap_login_boundary_routes(app)
    return TestClient(app)


def test_user_bootstrap_login_boundary_selects_employee_password_mode() -> None:
    report = build_user_bootstrap_login_boundary_report()
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["boundary_schema_version"] == (
        OA_USER_BOOTSTRAP_LOGIN_BOUNDARY_SCHEMA_VERSION
    )
    assert report["service_id"] == "nex-oa"
    assert report["decision"]["company_login_mode"] == {
        "mode": "employee_id_password",
        "login_identifier": "employee_id",
        "login_secret": "password",
        "selected_for_mvp": True,
        "external_identity_provider": "deferred",
    }
    assert report["decision"]["bootstrap_account_source"] == (
        "operator_seeded_employee_accounts"
    )
    assert report["decision"]["ae_receives_raw_password"] is True
    assert report["decision"]["ae_persists_raw_password"] is False
    assert report["decision"]["oa_persists_raw_password"] is False
    assert report["decision"]["oa_issues_session_after_successful_login"] is True
    assert "password_hash_verification" in report["authority"]["nex-oa"]
    assert "http_only_cookie_set_and_delete" in report["authority"]["nex-ae-api"]
    assert "employee_id_password_form" in report["authority"]["nex-ae-web"]
    assert report["subject_mapping_policy"]["employee_id_is_lookup_alias"] is True
    assert report["subject_mapping_policy"]["downstream_subject_ref_type"] == "oa.user"
    assert report["subject_mapping_policy"]["default_downstream_subject_id_policy"] == (
        "stable_oa_subject_id"
    )
    assert report["credential_record_policy"]["recommended_password_hash_algorithm"] == (
        "argon2id"
    )
    assert report["credential_record_policy"]["unique_lookup_scope"] == [
        "tenant_id",
        "employee_id",
    ]
    assert report["login_request_contract"]["accepted_fields"] == [
        "tenant_id",
        "employee_id",
        "password",
        "requested_scopes",
        "ttl_seconds",
    ]
    assert report["metadata"] == {
        "raw_passwords_included": False,
        "password_hashes_included": False,
        "raw_tokens_included": False,
        "cookie_values_included": False,
        "service_credentials_included": False,
        "database_urls_included": False,
        "employee_password_examples_included": False,
    }
    assert "nuri1004" not in serialized
    assert "secret-value" not in serialized
    assert "postgresql://" not in serialized


def test_user_bootstrap_login_boundary_sequence_is_next_slice_spine() -> None:
    report = build_user_bootstrap_login_boundary_report()

    assert [item["slice"] for item in report["bootstrap_sequence"]] == [
        "0252",
        "0253",
        "0254",
        "0255",
    ]
    assert report["forbidden_login_payloads"] == [
        "password_in_response",
        "password_in_database_plaintext",
        "password_hash_in_response",
        "raw_password_in_logs_or_evidence",
        "service_token_in_browser",
        "database_url",
        "provider_secret",
        "cookie_value_in_logs_or_evidence",
    ]
    assert "oidc_saml_sso" in report["deferred"]


def test_user_bootstrap_login_boundary_route_requires_service_claim_and_is_safe() -> None:
    client = build_client()

    missing = client.get("/internal/v1/auth/user-bootstrap-login-boundary")
    wrong_audience = client.get(
        "/internal/v1/auth/user-bootstrap-login-boundary",
        headers=auth_headers(audience="nex-cx"),
    )
    authorized = client.get(
        "/internal/v1/auth/user-bootstrap-login-boundary",
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
    assert payload["decision"]["company_login_mode"]["login_identifier"] == "employee_id"
    assert "Authorization" not in json.dumps(payload)
    assert "password_hash" not in json.dumps(payload["safe_login_response_fields"])


def test_nex_oa_entrypoint_registers_user_bootstrap_login_boundary_route() -> None:
    import nex_oa.main as main

    assert "/internal/v1/auth/user-bootstrap-login-boundary" in {
        getattr(route, "path", "") for route in main.app.routes
    }
