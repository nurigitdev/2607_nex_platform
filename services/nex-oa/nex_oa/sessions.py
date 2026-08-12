from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.memberships import (
    OA_TENANT_MEMBERSHIP_SNAPSHOT_SCHEMA_VERSION,
    OaMembershipError,
    OaTenantMembershipRegistry,
)
from nex_oa.subjects import (
    DEFAULT_SUBJECT_ID,
    DEFAULT_TENANT_ID,
    OA_TENANT_REF_TYPE,
    OA_USER_REF_TYPE,
    SubjectRegistryError,
    normalize_registry_id,
    payload_has_private_identity_data,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    PERSISTENCE_MODE_POSTGRES,
    ServicePersistenceRuntime,
    UserClaims,
    issue_mock_user_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_USER_SESSION_SCHEMA_VERSION = "oa_user_session.v1"
OA_SESSION_ISSUE_SCHEMA_VERSION = "oa_session_issue.v1"
OA_SESSION_INTROSPECTION_SCHEMA_VERSION = "oa_session_introspection.v1"
OA_SESSION_REVOCATION_SCHEMA_VERSION = "oa_session_revocation.v1"
OA_BROWSER_SESSION_SCHEMA_VERSION = "oa_browser_session.v1"
OA_SESSION_STATUSES = ("ACTIVE", "EXPIRED", "REVOKED")
DEFAULT_SESSION_TTL_SECONDS = 3600
MAX_SESSION_TTL_SECONDS = 86400
SESSION_ISSUE_FIELDS = frozenset(
    {
        "tenant_id",
        "subject_id",
        "user_id",
        "owner_user_id",
        "requested_scopes",
        "ttl_seconds",
    }
)
SESSION_INTROSPECTION_FIELDS = frozenset({"session_id"})
SENSITIVE_SESSION_KEY_PARTS = (
    "access",
    "authorization",
    "cookie",
    "credential",
    "passwd",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class OaSessionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass
class InMemoryOaSessionRegistry:
    membership_registry: OaTenantMembershipRegistry
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def issue_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        issue_request = normalize_session_issue_request(payload)
        membership = _required_active_membership(
            self.membership_registry,
            tenant_id=issue_request["tenant_id"],
            subject_id=issue_request["subject_id"],
        )
        record = build_session_record(
            _claims_for_membership(membership, issue_request),
        )
        self.sessions[record["session_id"]] = deepcopy(record)
        return build_session_issue_response(record, membership=membership)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        normalized_session_id = _non_empty_text(session_id, field_name="session_id")
        record = self.sessions.get(normalized_session_id)
        if record is None:
            return None
        return build_session_issue_response(record, membership=None)

    def introspect_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        introspection_request = normalize_session_introspection_request(payload)
        record = self.sessions.get(introspection_request["session_id"])
        return build_session_introspection_response(record)

    def revoke_session(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = _non_empty_text(session_id, field_name="session_id")
        record = self.sessions.get(normalized_session_id)
        if record is None:
            return build_session_revocation_response(
                None,
                session_id=normalized_session_id,
                already_revoked=False,
            )
        revoked_record, already_revoked, _ = build_revoked_session_record(record)
        self.sessions[normalized_session_id] = deepcopy(revoked_record)
        return build_session_revocation_response(
            revoked_record,
            session_id=normalized_session_id,
            already_revoked=already_revoked,
        )


class SqlAlchemyOaSessionRegistry:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        membership_registry: OaTenantMembershipRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._membership_registry = membership_registry

    def issue_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        issue_request = normalize_session_issue_request(payload)
        membership = _required_active_membership(
            self._membership_registry,
            tenant_id=issue_request["tenant_id"],
            subject_id=issue_request["subject_id"],
        )
        record = build_session_record(
            _claims_for_membership(membership, issue_request),
        )
        try:
            stored = self._run_in_transaction(
                lambda session: self._insert_and_read_session(session, record)
            )
        except SQLAlchemyError as exc:
            raise _session_unavailable() from exc
        return build_session_issue_response(stored, membership=membership)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        normalized_session_id = _non_empty_text(session_id, field_name="session_id")
        try:
            with self._session_factory() as session:
                record = self._select_session(session, normalized_session_id)
        except SQLAlchemyError as exc:
            raise _session_unavailable() from exc
        if record is None:
            return None
        return build_session_issue_response(record, membership=None)

    def introspect_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        introspection_request = normalize_session_introspection_request(payload)
        try:
            with self._session_factory() as session:
                record = self._select_session(
                    session,
                    introspection_request["session_id"],
                )
        except SQLAlchemyError as exc:
            raise _session_unavailable() from exc
        return build_session_introspection_response(record)

    def revoke_session(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = _non_empty_text(session_id, field_name="session_id")
        try:
            return self._run_in_transaction(
                lambda session: self._revoke_session(session, normalized_session_id)
            )
        except SQLAlchemyError as exc:
            raise _session_unavailable() from exc

    def _run_in_transaction(self, operation: Any) -> Any:
        session = self._session_factory()
        try:
            try:
                result = operation(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
        finally:
            session.close()

    def _insert_and_read_session(
        self,
        session: Session,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        scopes_expression = _json_sql_expression(session, "scopes")
        roles_expression = _json_sql_expression(session, "roles")
        metadata_expression = _json_sql_expression(session, "metadata")
        session.execute(
            text(
                f"""
                INSERT INTO oa_user_sessions (
                    session_id,
                    session_schema_version,
                    tenant_id,
                    subject_ref_type,
                    subject_id,
                    status,
                    issuer,
                    audience,
                    token_use,
                    scopes,
                    roles,
                    issued_at,
                    expires_at,
                    auth_time,
                    revoked_at,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (
                    :session_id,
                    :session_schema_version,
                    :tenant_id,
                    :subject_ref_type,
                    :subject_id,
                    :status,
                    :issuer,
                    :audience,
                    :token_use,
                    {scopes_expression},
                    {roles_expression},
                    :issued_at,
                    :expires_at,
                    :auth_time,
                    :revoked_at,
                    {metadata_expression},
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "session_id": record["session_id"],
                "session_schema_version": record["session_schema_version"],
                "tenant_id": record["tenant_ref"]["id"],
                "subject_ref_type": record["subject_ref"]["type"],
                "subject_id": record["subject_ref"]["id"],
                "status": record["status"],
                "issuer": record["issuer"],
                "audience": record["audience"],
                "token_use": record["token_use"],
                "scopes": _json_dumps(record["scopes"]),
                "roles": _json_dumps(record["roles"]),
                "issued_at": record["issued_at"],
                "expires_at": record["expires_at"],
                "auth_time": record["auth_time"],
                "revoked_at": record["revoked_at"],
                "metadata": _json_dumps(record["metadata"]),
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            },
        )
        stored = self._select_session(session, str(record["session_id"]))
        assert stored is not None
        return stored

    def _select_session(
        self,
        session: Session,
        session_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT
                    session_id,
                    session_schema_version,
                    tenant_id,
                    subject_ref_type,
                    subject_id,
                    status,
                    issuer,
                    audience,
                    token_use,
                    scopes,
                    roles,
                    issued_at,
                    expires_at,
                    auth_time,
                    revoked_at,
                    metadata,
                    created_at,
                    updated_at
                FROM oa_user_sessions
                WHERE session_id = :session_id
                """
            ),
            {"session_id": session_id},
        ).mappings().first()
        if row is None:
            return None
        return _session_from_row(row)

    def _revoke_session(self, session: Session, session_id: str) -> dict[str, Any]:
        record = self._select_session(session, session_id)
        if record is None:
            return build_session_revocation_response(
                None,
                session_id=session_id,
                already_revoked=False,
            )
        revoked_record, already_revoked, update_required = (
            build_revoked_session_record(record)
        )
        if update_required:
            session.execute(
                text(
                    """
                    UPDATE oa_user_sessions
                    SET
                        status = :status,
                        revoked_at = :revoked_at,
                        updated_at = :updated_at
                    WHERE session_id = :session_id
                    """
                ),
                {
                    "session_id": session_id,
                    "status": revoked_record["status"],
                    "revoked_at": revoked_record["revoked_at"],
                    "updated_at": revoked_record["updated_at"],
                },
            )
            stored = self._select_session(session, session_id)
        else:
            stored = record
        assert stored is not None
        return build_session_revocation_response(
            stored,
            session_id=session_id,
            already_revoked=already_revoked,
        )


def build_oa_session_registry_for_runtime(
    runtime: ServicePersistenceRuntime,
    *,
    membership_registry: OaTenantMembershipRegistry,
) -> InMemoryOaSessionRegistry | SqlAlchemyOaSessionRegistry:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaSessionRegistry(
            runtime.api_session_factory,
            membership_registry=membership_registry,
        )
    return InMemoryOaSessionRegistry(membership_registry=membership_registry)


def register_user_session_routes(
    app: FastAPI,
    *,
    registry: InMemoryOaSessionRegistry | SqlAlchemyOaSessionRegistry,
) -> None:
    @app.post("/internal/v1/auth/user-sessions/issue", response_model=None)
    def issue_user_session(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_session_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            response = registry.issue_session(payload)
        except OaSessionError as exc:
            return _session_problem_response(request, exc)
        return _attach_request_context(response, request)

    @app.post("/internal/v1/auth/user-sessions/introspect", response_model=None)
    def introspect_user_session(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_session_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            response = registry.introspect_session(payload)
        except OaSessionError as exc:
            return _session_problem_response(request, exc)
        return _attach_request_context(response, request)

    @app.post(
        "/internal/v1/auth/user-sessions/{session_id}/revoke",
        response_model=None,
    )
    def revoke_user_session(
        session_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_session_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            response = registry.revoke_session(session_id)
        except OaSessionError as exc:
            return _session_problem_response(request, exc)
        return _attach_request_context(response, request)

    @app.get("/internal/v1/auth/user-sessions/{session_id}", response_model=None)
    def get_user_session(
        session_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_session_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            response = registry.get_session(session_id)
        except OaSessionError as exc:
            return _session_problem_response(request, exc)
        if response is None:
            return _session_problem_response(
                request,
                OaSessionError(
                    status_code=404,
                    error_code="oa.session_not_found",
                    detail=f"Session was not found: {session_id}",
                ),
            )
        return _attach_request_context(response, request)


def normalize_session_issue_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unsupported_or_sensitive_session_fields(
        payload,
        allowed_fields=SESSION_ISSUE_FIELDS,
        error_code="oa.session_issue_field_unsupported",
        request_name="Session issue",
    )
    tenant_id = _normalize_ref_id(
        payload.get("tenant_id", DEFAULT_TENANT_ID),
        field_name="tenant_id",
    )
    subject_id = _normalize_ref_id(
        payload.get("subject_id", payload.get("owner_user_id", payload.get("user_id", DEFAULT_SUBJECT_ID))),
        field_name="subject_id",
    )
    return {
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "requested_scopes": _optional_string_list(
            payload.get("requested_scopes"),
            field_name="requested_scopes",
        ),
        "ttl_seconds": _ttl_seconds(payload.get("ttl_seconds")),
    }


def normalize_session_introspection_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unsupported_or_sensitive_session_fields(
        payload,
        allowed_fields=SESSION_INTROSPECTION_FIELDS,
        error_code="oa.session_introspection_field_unsupported",
        request_name="Session introspection",
    )
    return {
        "session_id": _non_empty_text(payload.get("session_id"), field_name="session_id"),
    }


def build_session_record(
    claims: UserClaims,
    *,
    status: str = "ACTIVE",
) -> dict[str, Any]:
    normalized_status = normalize_session_status(status)
    now = _utc_now()
    return {
        "session_schema_version": OA_USER_SESSION_SCHEMA_VERSION,
        "session_id": stable_session_id(claims),
        "status": normalized_status,
        "issuer": claims.issuer,
        "audience": claims.audience,
        "token_use": claims.token_use,
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": claims.tenant_id},
        "subject_ref": {"type": OA_USER_REF_TYPE, "id": claims.user_id},
        "scopes": list(claims.scopes),
        "roles": list(claims.roles),
        "issued_at": claims.issued_at,
        "expires_at": claims.expires_at,
        "auth_time": claims.issued_at,
        "revoked_at": None,
        "metadata": safe_session_metadata(),
        "created_at": now,
        "updated_at": now,
    }


def build_browser_session_snapshot(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "browser_session_schema_version": OA_BROWSER_SESSION_SCHEMA_VERSION,
        "session_id": _non_empty_text(record.get("session_id"), field_name="session_id"),
        "status": normalize_session_status(record.get("status")),
        "issuer": "nex-oa",
        "audience": "nex-ae-api",
        "token_use": "user",
        "tenant_ref": _typed_ref(
            record.get("tenant_ref"),
            expected_type=OA_TENANT_REF_TYPE,
            id_field_name="tenant_id",
        ),
        "subject_ref": _typed_ref(
            record.get("subject_ref"),
            expected_type=OA_USER_REF_TYPE,
            id_field_name="subject_id",
        ),
        "scopes": list(_non_empty_string_list(record.get("scopes"), field_name="scopes")),
        "roles": list(_string_list(record.get("roles"), field_name="roles")),
        "issued_at": _non_empty_text(record.get("issued_at"), field_name="issued_at"),
        "expires_at": _non_empty_text(record.get("expires_at"), field_name="expires_at"),
        "auth_time": _non_empty_text(record.get("auth_time"), field_name="auth_time"),
        "metadata": safe_session_metadata(),
    }


def build_session_issue_response(
    record: Mapping[str, Any],
    *,
    membership: Mapping[str, Any] | None,
) -> dict[str, Any]:
    session = build_browser_session_snapshot(record)
    return {
        "session_issue_schema_version": OA_SESSION_ISSUE_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "session": session,
        "tenant_ref": session["tenant_ref"],
        "subject_ref": session["subject_ref"],
        "membership_snapshot_schema_version": (
            membership.get("membership_snapshot_schema_version")
            if membership is not None
            else None
        ),
        "credential_delivery": {
            "raw_token_included": False,
            "cookie_set_by_oa": False,
            "ae_facade_delegation": "deferred",
        },
        "metadata": {
            "session_persisted": True,
            "raw_token_stored": False,
            "password_verified": False,
            "external_identity_provider_used": False,
        },
    }


def build_revoked_session_record(
    record: Mapping[str, Any],
) -> tuple[dict[str, Any], bool, bool]:
    status = normalize_session_status(record.get("status"))
    already_revoked = status == "REVOKED"
    if already_revoked and record.get("revoked_at") is not None:
        return deepcopy(dict(record)), True, False

    now = _utc_now()
    revoked_at = (
        _timestamp_to_wire(record.get("revoked_at"))
        if record.get("revoked_at") is not None
        else now
    )
    return (
        {
            **deepcopy(dict(record)),
            "status": "REVOKED",
            "revoked_at": revoked_at,
            "updated_at": now,
        },
        already_revoked,
        True,
    )


def build_session_introspection_response(
    record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    session = build_browser_session_snapshot(record) if record is not None else None
    inactive_reason = (
        _inactive_reason_for_session_snapshot(session) if session is not None else "not_found"
    )
    return {
        "session_introspection_schema_version": (
            OA_SESSION_INTROSPECTION_SCHEMA_VERSION
        ),
        "service_id": "nex-oa",
        "active": inactive_reason is None,
        "inactive_reason": inactive_reason,
        "session": session,
        "tenant_ref": session["tenant_ref"] if session is not None else None,
        "subject_ref": session["subject_ref"] if session is not None else None,
        "credential_delivery": {
            "raw_token_included": False,
            "cookie_value_included": False,
            "service_credential_included": False,
            "ae_cookie_owner": True,
        },
        "metadata": {
            "session_id_authoritative": True,
            "session_status_authoritative": True,
            "session_persisted": record is not None,
            "raw_token_stored": False,
            "browser_payload_owner_authoritative": False,
            "claim_owner_authoritative": True,
        },
    }


def build_session_revocation_response(
    record: Mapping[str, Any] | None,
    *,
    session_id: str,
    already_revoked: bool,
) -> dict[str, Any]:
    introspection = build_session_introspection_response(record)
    return {
        "session_revocation_schema_version": OA_SESSION_REVOCATION_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "session_id": session_id,
        "revoked": record is not None,
        "already_revoked": already_revoked,
        "idempotent": True,
        "active": False,
        "inactive_reason": introspection["inactive_reason"],
        "revoked_at": record.get("revoked_at") if record is not None else None,
        "session": introspection["session"],
        "tenant_ref": introspection["tenant_ref"],
        "subject_ref": introspection["subject_ref"],
        "credential_delivery": introspection["credential_delivery"],
        "metadata": {
            **introspection["metadata"],
            "session_revocation_authoritative": record is not None,
        },
    }


def normalize_session_status(value: object) -> str:
    status = _non_empty_text(value, field_name="session_status").upper()
    if status not in OA_SESSION_STATUSES:
        allowed = ", ".join(OA_SESSION_STATUSES)
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_status_invalid",
            detail=f"session_status must be one of: {allowed}.",
        )
    return status


def stable_session_id(claims: UserClaims) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                [
                    "nex-platform",
                    "oa-browser-session",
                    claims.tenant_id,
                    claims.user_id,
                    claims.issued_at,
                    claims.expires_at,
                ]
            ),
        )
    )


def safe_session_metadata() -> dict[str, bool]:
    return {
        "raw_token_included": False,
        "service_token_included": False,
        "password_included": False,
        "browser_payload_owner_authoritative": False,
        "claim_owner_authoritative": True,
    }


def _inactive_reason_for_session_snapshot(
    session: Mapping[str, Any],
) -> str | None:
    status = normalize_session_status(session.get("status"))
    if status == "REVOKED":
        return "revoked"
    if status == "EXPIRED":
        return "expired"
    expires_at = _wire_timestamp_to_utc(session.get("expires_at"))
    if expires_at <= datetime.now(UTC):
        return "expired"
    return None


def _claims_for_membership(
    membership: Mapping[str, Any],
    issue_request: Mapping[str, Any],
) -> UserClaims:
    membership_record = _membership_record(membership)
    scopes = _effective_scopes(
        tuple(_non_empty_string_list(membership_record.get("scopes"), field_name="scopes")),
        issue_request.get("requested_scopes"),
    )
    roles = tuple(_string_list(membership_record.get("roles"), field_name="roles"))
    issued = issue_mock_user_token(
        tenant_id=str(issue_request["tenant_id"]),
        user_id=str(issue_request["subject_id"]),
        audience="nex-ae-api",
        scopes=scopes,
        roles=roles,
        issued_at=datetime.now(UTC),
        ttl_seconds=int(issue_request["ttl_seconds"]),
    )
    return issued.claims


def _required_active_membership(
    registry: OaTenantMembershipRegistry,
    *,
    tenant_id: str,
    subject_id: str,
) -> dict[str, Any]:
    try:
        membership = registry.get_membership(tenant_id=tenant_id, subject_id=subject_id)
    except OaMembershipError as exc:
        raise _session_error_from_membership_error(exc) from exc
    if membership is None:
        raise OaSessionError(
            status_code=404,
            error_code="oa.membership_not_found",
            detail=f"Membership was not found: {tenant_id}/{subject_id}",
        )
    membership_record = _membership_record(membership)
    if membership_record.get("status") != "ACTIVE":
        raise OaSessionError(
            status_code=403,
            error_code="oa.membership_inactive",
            detail="OA cannot issue a session for an inactive membership.",
        )
    return membership


def _effective_scopes(
    membership_scopes: tuple[str, ...],
    requested_scopes: object,
) -> tuple[str, ...]:
    requested = requested_scopes if isinstance(requested_scopes, tuple) else None
    if requested is None:
        return membership_scopes
    missing = sorted(set(requested) - set(membership_scopes))
    if missing:
        raise OaSessionError(
            status_code=403,
            error_code="oa.session_scope_not_granted",
            detail=f"Requested scope is not granted by membership: {missing[0]}",
        )
    return requested


def _session_error_from_membership_error(exc: OaMembershipError) -> OaSessionError:
    return OaSessionError(
        status_code=exc.status_code,
        error_code=exc.error_code,
        detail=exc.detail,
        retryable=exc.retryable,
    )


def _session_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "session_schema_version": str(row["session_schema_version"]),
        "session_id": str(row["session_id"]),
        "status": str(row["status"]),
        "issuer": str(row["issuer"]),
        "audience": str(row["audience"]),
        "token_use": str(row["token_use"]),
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": str(row["tenant_id"])},
        "subject_ref": {
            "type": str(row["subject_ref_type"]),
            "id": str(row["subject_id"]),
        },
        "scopes": _json_loads(row["scopes"], default=[]),
        "roles": _json_loads(row["roles"], default=[]),
        "issued_at": _timestamp_to_wire(row["issued_at"]),
        "expires_at": _timestamp_to_wire(row["expires_at"]),
        "auth_time": _timestamp_to_wire(row["auth_time"]),
        "revoked_at": (
            _timestamp_to_wire(row["revoked_at"])
            if row.get("revoked_at") is not None
            else None
        ),
        "metadata": _json_loads(row["metadata"], default={}),
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _membership_record(membership: Mapping[str, Any]) -> Mapping[str, Any]:
    record = membership.get("membership")
    if not isinstance(record, Mapping):
        raise OaSessionError(
            status_code=500,
            error_code="oa.membership_snapshot_invalid",
            detail="OA membership snapshot is missing membership details.",
        )
    return record


def _reject_unsupported_or_sensitive_session_fields(
    payload: Mapping[str, Any],
    *,
    allowed_fields: frozenset[str],
    error_code: str,
    request_name: str,
) -> None:
    _reject_private_session_payload(payload)
    for key in payload:
        if key not in allowed_fields:
            raise OaSessionError(
                status_code=400,
                error_code=error_code,
                detail=f"{request_name} request contains an unsupported field.",
            )


def _reject_private_session_payload(value: object) -> None:
    if payload_has_private_identity_data(value):
        raise OaSessionError(
            status_code=400,
            error_code="oa.private_identity_payload_rejected",
            detail="OA session requests must not include private identity data.",
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(part in normalized_key for part in SENSITIVE_SESSION_KEY_PARTS):
                raise OaSessionError(
                    status_code=400,
                    error_code="oa.private_identity_payload_rejected",
                    detail="OA session requests must not include credential material.",
                )
            _reject_private_session_payload(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_private_session_payload(item)


def _typed_ref(
    value: object,
    *,
    expected_type: str,
    id_field_name: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_ref_invalid",
            detail=f"{id_field_name} ref must be an object.",
        )
    ref_type = _non_empty_text(value.get("type"), field_name=f"{id_field_name}.type")
    if ref_type != expected_type:
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_ref_invalid",
            detail=f"{id_field_name}.type must be {expected_type}.",
        )
    return {
        "type": ref_type,
        "id": _normalize_ref_id(value.get("id"), field_name=id_field_name),
    }


def _normalize_ref_id(value: object, *, field_name: str) -> str:
    try:
        return normalize_registry_id(value, field_name=field_name)
    except SubjectRegistryError as exc:
        raise OaSessionError(
            status_code=exc.status_code,
            error_code=exc.error_code,
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc


def _optional_string_list(value: object, *, field_name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _non_empty_string_list(value, field_name=field_name)


def _non_empty_string_list(value: object, *, field_name: str) -> tuple[str, ...]:
    normalized = _string_list(value, field_name=field_name)
    if not normalized:
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_list_invalid",
            detail=f"{field_name} must contain at least one value.",
        )
    return normalized


def _string_list(value: object, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_list_invalid",
            detail=f"{field_name} must be a list of strings.",
        )
    return tuple(_non_empty_text(item, field_name=f"{field_name}[]") for item in value)


def _ttl_seconds(value: object) -> int:
    if value is None:
        return DEFAULT_SESSION_TTL_SECONDS
    if not isinstance(value, int) or isinstance(value, bool):
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_ttl_invalid",
            detail="ttl_seconds must be an integer.",
        )
    if value <= 0 or value > MAX_SESSION_TTL_SECONDS:
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_ttl_invalid",
            detail="ttl_seconds is outside the allowed range.",
        )
    return value


def _non_empty_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    normalized = value.strip()
    if not normalized:
        raise OaSessionError(
            status_code=400,
            error_code="oa.session_field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return normalized


def _attach_request_context(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return {
        **payload,
        "trace_id": trace_id_from_headers(request),
        "request_id": request_id_from_headers(request),
    }


def _authorize_oa_session_request(
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


def _session_problem_response(
    request: Request,
    exc: OaSessionError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="OA session request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/oa-session-failed",
    )


def _json_sql_expression(session: Session, param_name: str) -> str:
    if session.get_bind().dialect.name == "postgresql":
        return f"CAST(:{param_name} AS JSONB)"
    return f":{param_name}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: Any, *, default: Any) -> Any:
    if value is None:
        return deepcopy(default)
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return deepcopy(default)


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        observed = value
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _wire_timestamp_to_utc(value: object) -> datetime:
    text_value = _non_empty_text(value, field_name="expires_at")
    normalized = (
        f"{text_value[:-1]}+00:00" if text_value.endswith("Z") else text_value
    )
    observed = datetime.fromisoformat(normalized)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


def _session_unavailable() -> OaSessionError:
    return OaSessionError(
        status_code=503,
        error_code="oa.session_registry_unavailable",
        detail="OA session registry is unavailable.",
        retryable=True,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
