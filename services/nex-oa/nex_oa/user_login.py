from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_oa.credentials import OaCredentialError, OaCredentialRegistry
from nex_oa.sessions import OaSessionError
from nex_oa.subjects import (
    OA_TENANT_REF_TYPE,
    OA_USER_REF_TYPE,
    SubjectRegistryError,
    normalize_registry_id,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_USER_LOGIN_RESPONSE_SCHEMA_VERSION = "oa_user_login_response.v1"
USER_LOGIN_REQUEST_FIELDS = frozenset(
    {
        "tenant_id",
        "employee_id",
        "password",
        "requested_scopes",
        "ttl_seconds",
    }
)
_SENSITIVE_UNSUPPORTED_LOGIN_KEY_PARTS = (
    "access",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "database_url",
    "hash",
    "passwd",
    "secret",
    "token",
)


@dataclass(frozen=True)
class OaUserLoginError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class OaSessionIssuer(Protocol):
    def issue_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class OaUserLoginService:
    credential_registry: OaCredentialRegistry
    session_registry: OaSessionIssuer

    def login(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        login_request = normalize_user_login_request(payload)
        try:
            credential_snapshot = self.credential_registry.verify_credential(
                login_request
            )
        except OaCredentialError as exc:
            raise _login_error_from_credential_error(exc) from exc

        session_issue_payload = build_session_issue_payload_for_login(
            login_request,
            credential_snapshot=credential_snapshot,
        )
        try:
            session_issue = self.session_registry.issue_session(session_issue_payload)
        except OaSessionError as exc:
            raise _login_error_from_session_error(exc) from exc
        return build_user_login_response(
            session_issue,
            credential_snapshot=credential_snapshot,
        )


def register_user_login_routes(
    app: FastAPI,
    *,
    service: OaUserLoginService,
) -> None:
    @app.post("/internal/v1/auth/user-login", response_model=None)
    def login_user(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_user_login_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            login_response = service.login(payload)
        except OaUserLoginError as exc:
            return _user_login_problem_response(request, exc)
        return _attach_request_context(login_response, request)


def normalize_user_login_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise OaUserLoginError(
            status_code=400,
            error_code="oa.login_payload_invalid",
            detail="OA user login request must be an object.",
        )
    _reject_unsupported_or_sensitive_login_fields(payload)
    return {
        key: deepcopy(payload[key])
        for key in USER_LOGIN_REQUEST_FIELDS
        if key in payload
    }


def build_session_issue_payload_for_login(
    login_request: Mapping[str, Any],
    *,
    credential_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    tenant_ref = _typed_ref(
        credential_snapshot.get("tenant_ref"),
        expected_type=OA_TENANT_REF_TYPE,
        id_field_name="tenant_id",
    )
    subject_ref = _typed_ref(
        credential_snapshot.get("subject_ref"),
        expected_type=OA_USER_REF_TYPE,
        id_field_name="subject_id",
    )
    session_payload: dict[str, Any] = {
        "tenant_id": tenant_ref["id"],
        "subject_id": subject_ref["id"],
    }
    if "requested_scopes" in login_request:
        session_payload["requested_scopes"] = deepcopy(
            login_request["requested_scopes"]
        )
    if "ttl_seconds" in login_request:
        session_payload["ttl_seconds"] = login_request["ttl_seconds"]
    return session_payload


def build_user_login_response(
    session_issue: Mapping[str, Any],
    *,
    credential_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    response = deepcopy(dict(session_issue))
    metadata = _safe_mapping(response.get("metadata"))
    credential = _safe_mapping(credential_snapshot.get("credential"))
    response["login_response_schema_version"] = OA_USER_LOGIN_RESPONSE_SCHEMA_VERSION
    response["metadata"] = {
        **metadata,
        "password_verified": True,
        "credential_lookup": "employee_id",
        "credential_status": str(credential.get("status", "UNKNOWN")),
        "credential_snapshot_included": False,
        "hash_material_included": False,
        "raw_password_included": False,
    }
    return response


def _reject_unsupported_or_sensitive_login_fields(payload: Mapping[str, Any]) -> None:
    for key in payload:
        key_text = str(key)
        if key_text in USER_LOGIN_REQUEST_FIELDS:
            continue
        if _login_key_is_sensitive(key_text):
            raise OaUserLoginError(
                status_code=400,
                error_code="oa.login_private_payload_rejected",
                detail="OA user login request must not include credential material.",
            )
        raise OaUserLoginError(
            status_code=400,
            error_code="oa.login_field_unsupported",
            detail="OA user login request contains an unsupported field.",
        )


def _login_key_is_sensitive(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in _SENSITIVE_UNSUPPORTED_LOGIN_KEY_PARTS)


def _typed_ref(
    value: object,
    *,
    expected_type: str,
    id_field_name: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise OaUserLoginError(
            status_code=500,
            error_code="oa.login_credential_snapshot_invalid",
            detail=f"{id_field_name} ref is missing from the credential snapshot.",
        )
    ref_type = _non_empty_text(value.get("type"), field_name=f"{id_field_name}.type")
    if ref_type != expected_type:
        raise OaUserLoginError(
            status_code=500,
            error_code="oa.login_credential_snapshot_invalid",
            detail=f"{id_field_name}.type must be {expected_type}.",
        )
    return {
        "type": ref_type,
        "id": _normalize_ref_id(value.get("id"), field_name=id_field_name),
    }


def _safe_mapping(value: object) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _normalize_ref_id(value: object, *, field_name: str) -> str:
    try:
        return normalize_registry_id(value, field_name=field_name)
    except SubjectRegistryError as exc:
        raise OaUserLoginError(
            status_code=500,
            error_code="oa.login_credential_snapshot_invalid",
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc


def _non_empty_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise OaUserLoginError(
            status_code=500,
            error_code="oa.login_credential_snapshot_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    normalized = value.strip()
    if not normalized:
        raise OaUserLoginError(
            status_code=500,
            error_code="oa.login_credential_snapshot_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return normalized


def _login_error_from_credential_error(exc: OaCredentialError) -> OaUserLoginError:
    return OaUserLoginError(
        status_code=exc.status_code,
        error_code=exc.error_code,
        detail=exc.detail,
        retryable=exc.retryable,
    )


def _login_error_from_session_error(exc: OaSessionError) -> OaUserLoginError:
    return OaUserLoginError(
        status_code=exc.status_code,
        error_code=exc.error_code,
        detail=exc.detail,
        retryable=exc.retryable,
    )


def _authorize_user_login_request(
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


def _user_login_problem_response(
    request: Request,
    exc: OaUserLoginError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="OA user login request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/oa-user-login-failed",
    )


def _attach_request_context(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return {
        **payload,
        "trace_id": trace_id_from_headers(request),
        "request_id": request_id_from_headers(request),
    }
