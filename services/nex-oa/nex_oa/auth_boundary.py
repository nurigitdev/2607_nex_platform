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


OA_IDENTITY_AUTH_BOUNDARY_SCHEMA_VERSION = "oa_identity_auth_boundary.v1"

_PRIVATE_AUTH_DATA_CATEGORIES = (
    "password",
    "raw_token",
    "authorization_header",
    "browser_cookie",
    "external_identity_profile",
    "provider_secret",
)

_SERVICE_BOUNDARIES: dict[str, dict[str, Any]] = {
    "nex-oa": {
        "owns": [
            "stable_tenant_refs",
            "stable_user_subject_refs",
            "subject_registry",
            "future_user_session_issuance",
            "future_user_session_introspection",
        ],
        "does_not_own": [
            "uploaded_document_owner_scope",
            "cx_content_acl_enforcement",
            "ae_browser_runtime_composition",
        ],
    },
    "nex-ae-api": {
        "owns": [
            "browser_session_facade_for_ae_web",
            "ae_facade_route_guard",
            "claim_derived_owner_scope_for_ae_calls",
        ],
        "does_not_own": [
            "durable_identity_authority",
            "password_verification",
            "subject_registry_storage",
        ],
    },
    "nex-cx": {
        "owns": [
            "content_owner_scope_enforcement",
            "content_acl_entries",
            "retrieval_evidence_persistence",
        ],
        "does_not_own": [
            "user_session_issuance",
            "browser_login_state",
        ],
    },
}


def build_identity_auth_boundary_report() -> dict[str, Any]:
    return {
        "boundary_schema_version": OA_IDENTITY_AUTH_BOUNDARY_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "boundary_name": "oa_identity_auth_authority",
        "current_state": {
            "stable_subject_registry": True,
            "mock_user_token_contract": True,
            "ae_session_facade": True,
            "oa_backed_session_issuance": False,
            "password_login": False,
            "external_identity_provider": False,
        },
        "target_state": {
            "oa_backed_session_issuance": True,
            "oa_session_introspection": True,
            "ae_session_facade_delegates_to_oa": True,
            "password_login": "deferred",
            "external_identity_provider": "deferred",
        },
        "service_boundaries": deepcopy(_SERVICE_BOUNDARIES),
        "safe_claim_fields": [
            "tenant_id",
            "user_id",
            "scopes",
            "roles",
            "audience",
            "token_use",
            "issued_at",
            "expires_at",
        ],
        "private_auth_data_categories": list(_PRIVATE_AUTH_DATA_CATEGORIES),
        "slice_sequence": [
            {
                "slice": "0242",
                "name": "OA user/tenant/membership persistence foundation",
                "decision": "Add durable subject membership tables before session issuance.",
            },
            {
                "slice": "0243",
                "name": "OA session issuance API foundation",
                "decision": "Issue safe browser-session snapshots from OA authority.",
            },
            {
                "slice": "0244",
                "name": "OA session PostgreSQL smoke evidence",
                "decision": "Exercise nex_oa_test with migration and session readback.",
            },
        ],
        "deferred": [
            "password_verification",
            "oidc_or_sso_provider_integration",
            "mfa",
            "refresh_token_rotation",
            "full_user_profile_storage",
        ],
        "metadata": {
            "raw_tokens_included": False,
            "passwords_included": False,
            "provider_endpoints_included": False,
            "database_urls_included": False,
            "session_cookie_values_included": False,
        },
    }


def register_identity_auth_boundary_routes(app: FastAPI) -> None:
    @app.get("/internal/v1/identity-auth-boundary", response_model=None)
    def get_identity_auth_boundary(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_boundary_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        return {
            **build_identity_auth_boundary_report(),
            "trace_id": trace_id_from_headers(request),
            "request_id": request_id_from_headers(request),
        }


def _authorize_oa_boundary_request(
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
