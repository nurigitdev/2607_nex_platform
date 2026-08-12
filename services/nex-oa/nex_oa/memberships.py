from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.subjects import (
    InMemoryOaSubjectRegistry,
    OA_TENANT_REF_TYPE,
    OA_USER_REF_TYPE,
    OaSubjectRegistry,
    SqlAlchemyOaSubjectRegistry,
    SubjectRegistryError,
    normalize_registry_id,
    payload_has_private_identity_data,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    PERSISTENCE_MODE_POSTGRES,
    ServicePersistenceRuntime,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_TENANT_MEMBERSHIP_SCHEMA_VERSION = "oa_tenant_membership.v1"
OA_TENANT_MEMBERSHIP_SNAPSHOT_SCHEMA_VERSION = "oa_tenant_membership_snapshot.v1"
OA_MEMBERSHIP_STATUSES = ("ACTIVE", "DISABLED")
DEFAULT_MEMBERSHIP_ROLES = ("employee",)
DEFAULT_MEMBERSHIP_SCOPES = (DEFAULT_USER_SCOPE,)
OA_MEMBERSHIP_CAPABILITIES = {
    "stable_tenant_membership": True,
    "oa_session_issuance": False,
    "password_login": False,
    "external_identity_provider": False,
}
OA_MEMBERSHIP_DEFERRED = [
    "oa_session_issuance",
    "password_verification",
    "oidc_or_sso_provider_integration",
    "refresh_token_rotation",
]


@dataclass(frozen=True)
class OaMembershipError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class OaTenantMembershipRegistry(Protocol):
    def ensure_membership(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def get_membership(
        self,
        *,
        tenant_id: str,
        subject_id: str,
    ) -> dict[str, Any] | None:
        ...


@dataclass
class InMemoryOaTenantMembershipRegistry:
    subject_registry: OaSubjectRegistry = field(default_factory=InMemoryOaSubjectRegistry)
    memberships: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def ensure_membership(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        subject_snapshot = _ensure_subject_snapshot(self.subject_registry, payload)
        record = build_membership_record(payload, subject_snapshot=subject_snapshot)
        key = _membership_key(record)
        existing = self.memberships.get(key)
        if existing is None:
            self.memberships[key] = deepcopy(record)
            existing = record
        return build_membership_snapshot(
            membership=existing,
            subject_snapshot=subject_snapshot,
        )

    def get_membership(
        self,
        *,
        tenant_id: str,
        subject_id: str,
    ) -> dict[str, Any] | None:
        normalized_tenant_id = _normalize_ref_id(
            tenant_id,
            field_name="tenant_id",
        )
        normalized_subject_id = _normalize_ref_id(
            subject_id,
            field_name="subject_id",
        )
        record = self.memberships.get((normalized_tenant_id, normalized_subject_id))
        if record is None:
            return None
        subject_snapshot = _get_subject_snapshot(
            self.subject_registry,
            tenant_id=normalized_tenant_id,
            subject_id=normalized_subject_id,
        )
        if subject_snapshot is None:
            raise _membership_unavailable()
        return build_membership_snapshot(
            membership=record,
            subject_snapshot=subject_snapshot,
        )


class SqlAlchemyOaTenantMembershipRegistry:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        subject_registry: OaSubjectRegistry | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._subject_registry = subject_registry or SqlAlchemyOaSubjectRegistry(
            session_factory
        )

    def ensure_membership(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        subject_snapshot = _ensure_subject_snapshot(self._subject_registry, payload)
        record = build_membership_record(payload, subject_snapshot=subject_snapshot)
        try:
            stored = self._run_in_transaction(
                lambda session: self._ensure_membership(session, record)
            )
        except IntegrityError as exc:
            existing = self.get_membership(
                tenant_id=str(record["tenant_ref"]["id"]),
                subject_id=str(record["subject_ref"]["id"]),
            )
            if existing is not None:
                return existing
            raise _membership_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _membership_unavailable() from exc
        return build_membership_snapshot(
            membership=stored,
            subject_snapshot=subject_snapshot,
        )

    def get_membership(
        self,
        *,
        tenant_id: str,
        subject_id: str,
    ) -> dict[str, Any] | None:
        normalized_tenant_id = _normalize_ref_id(
            tenant_id,
            field_name="tenant_id",
        )
        normalized_subject_id = _normalize_ref_id(
            subject_id,
            field_name="subject_id",
        )
        try:
            with self._session_factory() as session:
                record = self._select_membership(
                    session,
                    tenant_id=normalized_tenant_id,
                    subject_id=normalized_subject_id,
                )
        except SQLAlchemyError as exc:
            raise _membership_unavailable() from exc
        if record is None:
            return None
        subject_snapshot = _get_subject_snapshot(
            self._subject_registry,
            tenant_id=normalized_tenant_id,
            subject_id=normalized_subject_id,
        )
        if subject_snapshot is None:
            raise _membership_unavailable()
        return build_membership_snapshot(
            membership=record,
            subject_snapshot=subject_snapshot,
        )

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

    def _ensure_membership(
        self,
        session: Session,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_membership(
            session,
            tenant_id=str(record["tenant_ref"]["id"]),
            subject_id=str(record["subject_ref"]["id"]),
        )
        if existing is not None:
            return existing
        self._insert_membership(session, record)
        stored = self._select_membership(
            session,
            tenant_id=str(record["tenant_ref"]["id"]),
            subject_id=str(record["subject_ref"]["id"]),
        )
        assert stored is not None
        return stored

    def _insert_membership(
        self,
        session: Session,
        record: Mapping[str, Any],
    ) -> None:
        roles_expression = _json_sql_expression(session, "roles")
        scopes_expression = _json_sql_expression(session, "scopes")
        metadata_expression = _json_sql_expression(session, "metadata")
        session.execute(
            text(
                f"""
                INSERT INTO oa_tenant_memberships (
                    tenant_id,
                    subject_ref_type,
                    subject_id,
                    membership_schema_version,
                    status,
                    roles,
                    scopes,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (
                    :tenant_id,
                    :subject_ref_type,
                    :subject_id,
                    :membership_schema_version,
                    :status,
                    {roles_expression},
                    {scopes_expression},
                    {metadata_expression},
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "tenant_id": record["tenant_ref"]["id"],
                "subject_ref_type": record["subject_ref"]["type"],
                "subject_id": record["subject_ref"]["id"],
                "membership_schema_version": record["membership_schema_version"],
                "status": record["status"],
                "roles": _json_dumps(record["roles"]),
                "scopes": _json_dumps(record["scopes"]),
                "metadata": _json_dumps(record["metadata"]),
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            },
        )

    def _select_membership(
        self,
        session: Session,
        *,
        tenant_id: str,
        subject_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT
                    tenant_id,
                    subject_ref_type,
                    subject_id,
                    membership_schema_version,
                    status,
                    roles,
                    scopes,
                    metadata,
                    created_at,
                    updated_at
                FROM oa_tenant_memberships
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                  AND subject_ref_type = :subject_ref_type
                """
            ),
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "subject_ref_type": OA_USER_REF_TYPE,
            },
        ).mappings().first()
        if row is None:
            return None
        return _membership_from_row(row)


DEFAULT_TENANT_MEMBERSHIP_REGISTRY = InMemoryOaTenantMembershipRegistry()


def build_tenant_membership_registry_for_runtime(
    runtime: ServicePersistenceRuntime,
    *,
    subject_registry: OaSubjectRegistry | None = None,
) -> OaTenantMembershipRegistry:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaTenantMembershipRegistry(
            runtime.api_session_factory,
            subject_registry=subject_registry,
        )
    if subject_registry is not None:
        return InMemoryOaTenantMembershipRegistry(subject_registry=subject_registry)
    return DEFAULT_TENANT_MEMBERSHIP_REGISTRY


def register_identity_membership_routes(
    app: FastAPI,
    *,
    registry: OaTenantMembershipRegistry | None = None,
) -> None:
    membership_registry = registry or DEFAULT_TENANT_MEMBERSHIP_REGISTRY

    @app.post("/internal/v1/identity/memberships/ensure", response_model=None)
    def ensure_identity_membership(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_membership_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            snapshot = membership_registry.ensure_membership(payload)
        except OaMembershipError as exc:
            return _membership_problem_response(request, exc)
        return _attach_request_context(snapshot, request)

    @app.get(
        "/internal/v1/identity/memberships/tenants/{tenant_id}/subjects/{subject_id}",
        response_model=None,
    )
    def get_identity_membership(
        tenant_id: str,
        subject_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_membership_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            snapshot = membership_registry.get_membership(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except OaMembershipError as exc:
            return _membership_problem_response(request, exc)
        if snapshot is None:
            return _membership_problem_response(
                request,
                OaMembershipError(
                    status_code=404,
                    error_code="oa.membership_not_found",
                    detail=f"Membership was not found: {tenant_id}/{subject_id}",
                ),
            )
        return _attach_request_context(snapshot, request)


def build_membership_record(
    payload: Mapping[str, Any],
    *,
    subject_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    _reject_private_identity_payload(payload)
    tenant_ref = _typed_ref(
        subject_snapshot.get("tenant_ref"),
        expected_type=OA_TENANT_REF_TYPE,
        id_field_name="tenant_id",
    )
    subject_ref = _typed_ref(
        subject_snapshot.get("subject_ref"),
        expected_type=OA_USER_REF_TYPE,
        id_field_name="subject_id",
    )
    now = _utc_now()
    return {
        "membership_schema_version": OA_TENANT_MEMBERSHIP_SCHEMA_VERSION,
        "tenant_ref": tenant_ref,
        "subject_ref": subject_ref,
        "status": normalize_membership_status(
            payload.get("membership_status", payload.get("status", "ACTIVE"))
        ),
        "roles": list(
            _string_list(
                payload.get("roles"),
                default=DEFAULT_MEMBERSHIP_ROLES,
                field_name="roles",
            )
        ),
        "scopes": list(
            _string_list(
                payload.get("scopes"),
                default=DEFAULT_MEMBERSHIP_SCOPES,
                field_name="scopes",
            )
        ),
        "metadata": _metadata_from_payload(
            payload.get("membership_metadata", payload.get("metadata", {}))
        ),
        "created_at": now,
        "updated_at": now,
    }


def build_membership_snapshot(
    *,
    membership: Mapping[str, Any],
    subject_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    tenant_ref = _typed_ref(
        membership.get("tenant_ref"),
        expected_type=OA_TENANT_REF_TYPE,
        id_field_name="tenant_id",
    )
    subject_ref = _typed_ref(
        membership.get("subject_ref"),
        expected_type=OA_USER_REF_TYPE,
        id_field_name="subject_id",
    )
    return {
        "membership_snapshot_schema_version": (
            OA_TENANT_MEMBERSHIP_SNAPSHOT_SCHEMA_VERSION
        ),
        "service_id": "nex-oa",
        "identity_capability": "stable_tenant_membership",
        "tenant_ref": tenant_ref,
        "subject_ref": subject_ref,
        "membership": _safe_record_copy(membership),
        "subject_registry_snapshot": _safe_record_copy(subject_snapshot),
        "compatibility_aliases": {
            "tenant_id": tenant_ref["id"],
            "owner_user_id": subject_ref["id"],
            "user_id": subject_ref["id"],
        },
        "capabilities": dict(OA_MEMBERSHIP_CAPABILITIES),
        "deferred": list(OA_MEMBERSHIP_DEFERRED),
        "private_payload_policy": _private_payload_policy(),
        "next_slice": "0243_oa_session_issuance_api_foundation",
    }


def normalize_membership_status(value: object) -> str:
    status = _non_empty_text(value, field_name="membership_status").upper()
    if status not in OA_MEMBERSHIP_STATUSES:
        allowed = ", ".join(OA_MEMBERSHIP_STATUSES)
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_status_invalid",
            detail=f"membership_status must be one of: {allowed}.",
        )
    return status


def _ensure_subject_snapshot(
    subject_registry: OaSubjectRegistry,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        return subject_registry.ensure_subject(payload)
    except SubjectRegistryError as exc:
        raise _membership_error_from_subject_error(exc) from exc


def _get_subject_snapshot(
    subject_registry: OaSubjectRegistry,
    *,
    tenant_id: str,
    subject_id: str,
) -> dict[str, Any] | None:
    try:
        return subject_registry.get_subject(tenant_id=tenant_id, subject_id=subject_id)
    except SubjectRegistryError as exc:
        raise _membership_error_from_subject_error(exc) from exc


def _membership_error_from_subject_error(exc: SubjectRegistryError) -> OaMembershipError:
    return OaMembershipError(
        status_code=exc.status_code,
        error_code=exc.error_code,
        detail=exc.detail,
        retryable=exc.retryable,
    )


def _membership_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "membership_schema_version": str(row["membership_schema_version"]),
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": str(row["tenant_id"])},
        "subject_ref": {
            "type": str(row["subject_ref_type"]),
            "id": str(row["subject_id"]),
        },
        "status": str(row["status"]),
        "roles": _json_loads(row["roles"], default=[]),
        "scopes": _json_loads(row["scopes"], default=[]),
        "metadata": _json_loads(row["metadata"], default={}),
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _typed_ref(
    value: object,
    *,
    expected_type: str,
    id_field_name: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_ref_invalid",
            detail=f"{id_field_name} ref must be an object.",
        )
    ref_type = _non_empty_text(value.get("type"), field_name=f"{id_field_name}.type")
    if ref_type != expected_type:
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_ref_invalid",
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
        raise _membership_error_from_subject_error(exc) from exc


def _string_list(
    value: object,
    *,
    default: tuple[str, ...],
    field_name: str,
) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_list_invalid",
            detail=f"{field_name} must be a non-empty list of strings.",
        )
    normalized = tuple(
        _non_empty_text(item, field_name=f"{field_name}[]") for item in value
    )
    if not normalized:
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_list_invalid",
            detail=f"{field_name} must contain at least one value.",
        )
    return normalized


def _metadata_from_payload(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_metadata_invalid",
            detail="membership metadata must be an object.",
        )
    _reject_private_identity_payload(value)
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_metadata_invalid",
            detail="membership metadata must be JSON serializable.",
        ) from exc
    return deepcopy(dict(value))


def _reject_private_identity_payload(value: object) -> None:
    if payload_has_private_identity_data(value):
        raise OaMembershipError(
            status_code=400,
            error_code="oa.private_identity_payload_rejected",
            detail=(
                "OA memberships must not include passwords, tokens, email "
                "addresses, phone numbers, raw profiles, or provider secrets."
            ),
        )


def _attach_request_context(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return {
        **payload,
        "trace_id": trace_id_from_headers(request),
        "request_id": request_id_from_headers(request),
    }


def _authorize_oa_membership_request(
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


def _membership_problem_response(
    request: Request,
    exc: OaMembershipError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="OA membership request failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/oa-membership-failed",
    )


def _membership_key(record: Mapping[str, Any]) -> tuple[str, str]:
    tenant_ref = record["tenant_ref"]
    subject_ref = record["subject_ref"]
    return (
        str(tenant_ref["id"]),
        str(subject_ref["id"]),
    )


def _safe_record_copy(record: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(record))


def _non_empty_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    normalized = value.strip()
    if not normalized:
        raise OaMembershipError(
            status_code=400,
            error_code="oa.membership_field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return normalized


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


def _private_payload_policy() -> str:
    return (
        "Store stable tenant/user refs, membership status, roles, scopes, and "
        "safe membership metadata only. Do not store passwords, raw tokens, "
        "browser cookies, external identity profiles, email addresses, phone "
        "numbers, or provider secrets."
    )


def _membership_unavailable() -> OaMembershipError:
    return OaMembershipError(
        status_code=503,
        error_code="oa.membership_registry_unavailable",
        detail="OA membership registry is unavailable.",
        retryable=True,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
