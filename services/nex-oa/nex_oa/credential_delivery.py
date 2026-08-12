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


OA_SESSION_CREDENTIAL_DELIVERY_SCHEMA_VERSION = (
    "oa_session_credential_delivery_boundary.v1"
)

_COOKIE_POLICY = {
    "owner_service": "nex-ae-api",
    "cookie_name": "nex_ae_user_session",
    "http_only": True,
    "same_site": "lax",
    "secure_in_production": True,
    "local_development_secure": False,
    "path": "/",
    "max_age_source": "oa_session.expires_at",
    "cookie_value_kind": "opaque_oa_session_id",
}

_SERVICE_RESPONSIBILITIES = {
    "nex-oa": [
        "membership_backed_session_issuance",
        "session_persistence",
        "session_introspection",
        "session_revocation",
    ],
    "nex-ae-api": [
        "browser_login_facade",
        "http_only_cookie_set_and_delete",
        "route_guard_introspection_client",
        "browser_safe_session_projection",
    ],
    "nex-cx": [
        "owner_scope_authorization_after_ae_guard",
        "content_acl_enforcement",
    ],
}

_FORBIDDEN_DELIVERY_PAYLOADS = (
    "raw_user_access_token_in_json",
    "service_token_in_browser",
    "password_or_login_secret",
    "external_identity_provider_payload",
    "database_url",
    "cookie_value_in_logs_or_evidence",
)


def build_session_credential_delivery_boundary_report() -> dict[str, Any]:
    return {
        "boundary_schema_version": OA_SESSION_CREDENTIAL_DELIVERY_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "boundary_name": "oa_ae_session_credential_delivery",
        "decision": {
            "selected_delivery_mode": "ae_http_only_cookie_with_oa_session_id",
            "oa_response_contains_raw_user_token": False,
            "browser_json_contains_cookie_value": False,
            "ae_sets_browser_cookie": True,
            "ae_deletes_browser_cookie": True,
            "ae_route_guard_uses_oa_introspection": True,
            "oa_session_id_is_authoritative_handle": True,
        },
        "cookie_policy": deepcopy(_COOKIE_POLICY),
        "service_responsibilities": deepcopy(_SERVICE_RESPONSIBILITIES),
        "allowed_oa_issue_response_fields": [
            "session_issue_schema_version",
            "service_id",
            "session",
            "tenant_ref",
            "subject_ref",
            "membership_snapshot_schema_version",
            "credential_delivery",
            "metadata",
        ],
        "forbidden_delivery_payloads": list(_FORBIDDEN_DELIVERY_PAYLOADS),
        "delegation_sequence": [
            {
                "slice": "0246",
                "name": "OA session introspection API foundation",
                "decision": "AE can validate opaque OA session ids without parsing browser credentials.",
            },
            {
                "slice": "0247",
                "name": "OA session revocation API foundation",
                "decision": "AE logout delegates durable session invalidation to OA.",
            },
            {
                "slice": "0248",
                "name": "AE API OA session client adapter foundation",
                "decision": "AE owns cookie lifecycle and calls OA with service credentials.",
            },
            {
                "slice": "0249",
                "name": "AE auth session facade delegates to OA",
                "decision": "AE login/current/logout can switch from mock user tokens to OA-backed sessions.",
            },
        ],
        "metadata": {
            "raw_tokens_included": False,
            "cookie_values_included": False,
            "passwords_included": False,
            "service_credentials_included": False,
            "database_urls_included": False,
        },
    }


def register_session_credential_delivery_boundary_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v1/auth/session-credential-delivery-boundary",
        response_model=None,
    )
    def get_session_credential_delivery_boundary(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_credential_delivery_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        return {
            **build_session_credential_delivery_boundary_report(),
            "trace_id": trace_id_from_headers(request),
            "request_id": request_id_from_headers(request),
        }


def _authorize_credential_delivery_request(
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
