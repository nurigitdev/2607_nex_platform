from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_USER_BOOTSTRAP_LOGIN_BOUNDARY_SCHEMA_VERSION = (
    "oa_user_bootstrap_login_boundary.v1"
)

_SELECTED_COMPANY_LOGIN_MODE = {
    "mode": "employee_id_password",
    "login_identifier": "employee_id",
    "login_secret": "password",
    "selected_for_mvp": True,
    "external_identity_provider": "deferred",
}

_BOOTSTRAP_AUTHORITY = {
    "nex-oa": [
        "employee_login_identifier_normalization",
        "credential_record_persistence",
        "password_hash_verification",
        "subject_membership_lookup",
        "user_session_issue_after_successful_login",
        "login_success_failure_audit",
    ],
    "nex-ae-api": [
        "browser_login_facade",
        "login_error_projection",
        "http_only_cookie_set_and_delete",
        "oa_session_current_logout_delegation",
    ],
    "nex-ae-web": [
        "employee_id_password_form",
        "current_session_bootstrap",
        "logout_button",
        "credential_free_runtime_config",
    ],
}

_SUBJECT_MAPPING_POLICY = {
    "login_identifier_kind": "employee_id",
    "employee_id_is_lookup_alias": True,
    "downstream_subject_ref_type": "oa.user",
    "default_downstream_subject_id_policy": "stable_oa_subject_id",
    "employee_id_in_downstream_claims": "not_required",
    "reason": (
        "Employee id is the company login handle, but downstream services only "
        "need stable owner subject refs and should not depend on password-era "
        "credential fields."
    ),
}

_CREDENTIAL_RECORD_POLICY = {
    "credential_record_owner": "nex-oa",
    "raw_password_stored": False,
    "password_hash_stored": True,
    "recommended_password_hash_algorithm": "argon2id",
    "password_hash_algorithm_configured_by_env": True,
    "credential_statuses": [
        "ACTIVE",
        "PASSWORD_RESET_REQUIRED",
        "LOCKED",
        "DISABLED",
    ],
    "unique_lookup_scope": ["tenant_id", "employee_id"],
    "raw_password_loggable": False,
    "password_hash_returned_by_api": False,
}

_BOOTSTRAP_SEQUENCE = [
    {
        "slice": "0252",
        "name": "OA local credential registry foundation",
        "decision": "Store employee login aliases and password hashes in OA only.",
    },
    {
        "slice": "0253",
        "name": "OA user login API foundation",
        "decision": "Verify employee id/password and issue an OA browser session.",
    },
    {
        "slice": "0254",
        "name": "OA user login PostgreSQL smoke evidence",
        "decision": "Exercise credential seed/login/session/revoke/readback against nex_oa_test.",
    },
    {
        "slice": "0255",
        "name": "AE auth facade credential-login adapter",
        "decision": "AE delegates employee id/password login to OA and stores only the OA session id cookie.",
    },
]

_FORBIDDEN_LOGIN_PAYLOADS = (
    "password_in_response",
    "password_in_database_plaintext",
    "password_hash_in_response",
    "raw_password_in_logs_or_evidence",
    "service_token_in_browser",
    "database_url",
    "provider_secret",
    "cookie_value_in_logs_or_evidence",
)


def build_user_bootstrap_login_boundary_report() -> dict[str, Any]:
    return {
        "boundary_schema_version": OA_USER_BOOTSTRAP_LOGIN_BOUNDARY_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "boundary_name": "oa_user_bootstrap_login",
        "decision": {
            "company_login_mode": deepcopy(_SELECTED_COMPANY_LOGIN_MODE),
            "password_login_status": "selected_for_mvp_local_credential_registry",
            "bootstrap_account_source": "operator_seeded_employee_accounts",
            "external_idp_status": "deferred_until_after_mvp_login_spine",
            "ae_receives_raw_password": True,
            "ae_persists_raw_password": False,
            "oa_persists_raw_password": False,
            "oa_issues_session_after_successful_login": True,
        },
        "authority": deepcopy(_BOOTSTRAP_AUTHORITY),
        "subject_mapping_policy": deepcopy(_SUBJECT_MAPPING_POLICY),
        "credential_record_policy": deepcopy(_CREDENTIAL_RECORD_POLICY),
        "login_request_contract": {
            "accepted_fields": [
                "tenant_id",
                "employee_id",
                "password",
                "requested_scopes",
                "ttl_seconds",
            ],
            "sensitive_fields": ["password"],
            "unsupported_fields_rejected": True,
            "credential_like_extra_fields_rejected": True,
        },
        "safe_login_response_fields": [
            "session_issue_schema_version",
            "service_id",
            "session",
            "tenant_ref",
            "subject_ref",
            "credential_delivery",
            "metadata",
        ],
        "bootstrap_sequence": deepcopy(_BOOTSTRAP_SEQUENCE),
        "forbidden_login_payloads": list(_FORBIDDEN_LOGIN_PAYLOADS),
        "deferred": [
            "self_service_signup",
            "password_change_ui",
            "password_reset_email",
            "mfa",
            "oidc_saml_sso",
            "hr_roster_sync",
            "rich_org_chart_rbac",
        ],
        "metadata": {
            "raw_passwords_included": False,
            "password_hashes_included": False,
            "raw_tokens_included": False,
            "cookie_values_included": False,
            "service_credentials_included": False,
            "database_urls_included": False,
            "employee_password_examples_included": False,
        },
    }


def register_user_bootstrap_login_boundary_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v1/auth/user-bootstrap-login-boundary",
        response_model=None,
    )
    def get_user_bootstrap_login_boundary(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_bootstrap_login_boundary_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        return {
            **build_user_bootstrap_login_boundary_report(),
            "trace_id": trace_id_from_headers(request),
            "request_id": request_id_from_headers(request),
        }


def _authorize_bootstrap_login_boundary_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "OA requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )
