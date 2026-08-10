from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    PERSISTENCE_MODE_POSTGRES,
    ServicePersistenceRuntime,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_SUBJECT_REGISTRY_SCHEMA_VERSION = "oa_subject_registry.v1"
OA_SUBJECT_REGISTRY_SNAPSHOT_SCHEMA_VERSION = "oa_subject_registry_snapshot.v1"
OA_TENANT_REF_TYPE = "oa.tenant"
OA_USER_REF_TYPE = "oa.user"
DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_TENANT_DISPLAY_NAME = "Local Tenant"
DEFAULT_SUBJECT_ID = "local-user"
DEFAULT_SUBJECT_DISPLAY_NAME = "Local User"
OA_SUBJECT_STATUSES = ("ACTIVE", "DISABLED", "DELETED")
OA_SUBJECT_REGISTRY_CAPABILITIES = {
    "stable_subject_registry": True,
    "password_login": False,
    "external_identity_provider_mapping": False,
    "role_management": False,
    "full_user_profile": False,
}
OA_SUBJECT_REGISTRY_DEFERRED = [
    "password_login",
    "external_identity_provider_mapping",
    "role_management",
    "full_user_profile",
]

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRIVATE_IDENTITY_KEY_PARTS = (
    "authorization",
    "email",
    "passwd",
    "password",
    "phone",
    "raw_profile",
    "secret",
    "token",
)


@dataclass(frozen=True)
class SubjectRegistryError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class OaSubjectRegistry(Protocol):
    def ensure_tenant(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        ...

    def ensure_subject(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def get_subject(self, *, tenant_id: str, subject_id: str) -> dict[str, Any] | None:
        ...


@dataclass
class InMemoryOaSubjectRegistry:
    tenants: dict[str, dict[str, Any]] = field(default_factory=dict)
    subjects: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def ensure_tenant(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = build_tenant_record(payload)
        existing = self.tenants.get(record["tenant_id"])
        if existing is not None:
            return deepcopy(existing)
        self.tenants[record["tenant_id"]] = deepcopy(record)
        return deepcopy(record)

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        normalized_tenant_id = normalize_registry_id(
            tenant_id,
            field_name="tenant_id",
        )
        record = self.tenants.get(normalized_tenant_id)
        return deepcopy(record) if record is not None else None

    def ensure_subject(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tenant = self.ensure_tenant(payload)
        record = build_subject_record(payload, tenant=tenant)
        key = _subject_key(record)
        existing = self.subjects.get(key)
        if existing is not None:
            return build_subject_registry_snapshot(tenant=tenant, subject=existing)
        self.subjects[key] = deepcopy(record)
        return build_subject_registry_snapshot(tenant=tenant, subject=record)

    def get_subject(self, *, tenant_id: str, subject_id: str) -> dict[str, Any] | None:
        normalized_tenant_id = normalize_registry_id(
            tenant_id,
            field_name="tenant_id",
        )
        normalized_subject_id = normalize_registry_id(
            subject_id,
            field_name="subject_id",
        )
        tenant = self.tenants.get(normalized_tenant_id)
        subject = self.subjects.get((normalized_tenant_id, normalized_subject_id))
        if tenant is None or subject is None:
            return None
        return build_subject_registry_snapshot(tenant=tenant, subject=subject)


class SqlAlchemyOaSubjectRegistry:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_tenant(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = build_tenant_record(payload)
        try:
            return self._run_in_transaction(
                lambda session: self._ensure_tenant(session, record)
            )
        except IntegrityError as exc:
            existing = self.get_tenant(str(record["tenant_id"]))
            if existing is not None:
                return existing
            raise _subject_registry_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _subject_registry_unavailable() from exc

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        normalized_tenant_id = normalize_registry_id(
            tenant_id,
            field_name="tenant_id",
        )
        try:
            with self._session_factory() as session:
                return self._select_tenant(session, normalized_tenant_id)
        except SQLAlchemyError as exc:
            raise _subject_registry_unavailable() from exc

    def ensure_subject(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return self._run_in_transaction(
                lambda session: self._ensure_subject(session, payload)
            )
        except IntegrityError as exc:
            tenant_id = _tenant_id_from_payload(payload)
            subject_id = _subject_id_from_payload(payload)
            existing = self.get_subject(tenant_id=tenant_id, subject_id=subject_id)
            if existing is not None:
                return existing
            raise _subject_registry_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _subject_registry_unavailable() from exc

    def get_subject(self, *, tenant_id: str, subject_id: str) -> dict[str, Any] | None:
        normalized_tenant_id = normalize_registry_id(
            tenant_id,
            field_name="tenant_id",
        )
        normalized_subject_id = normalize_registry_id(
            subject_id,
            field_name="subject_id",
        )
        try:
            with self._session_factory() as session:
                tenant = self._select_tenant(session, normalized_tenant_id)
                subject = self._select_subject(
                    session,
                    tenant_id=normalized_tenant_id,
                    subject_id=normalized_subject_id,
                )
        except SQLAlchemyError as exc:
            raise _subject_registry_unavailable() from exc
        if tenant is None or subject is None:
            return None
        return build_subject_registry_snapshot(tenant=tenant, subject=subject)

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

    def _ensure_tenant(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_tenant(session, str(record["tenant_id"]))
        if existing is not None:
            return existing
        metadata_expression = _json_sql_expression(session, "metadata")
        session.execute(
            text(
                f"""
                INSERT INTO oa_tenants (
                    tenant_id,
                    tenant_ref_type,
                    display_name,
                    status,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (
                    :tenant_id,
                    :tenant_ref_type,
                    :display_name,
                    :status,
                    {metadata_expression},
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "tenant_id": record["tenant_id"],
                "tenant_ref_type": record["tenant_ref"]["type"],
                "display_name": record["display_name"],
                "status": record["status"],
                "metadata": _json_dumps(record["metadata"]),
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            },
        )
        stored = self._select_tenant(session, str(record["tenant_id"]))
        assert stored is not None
        return stored

    def _ensure_subject(
        self,
        session: Session,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_record = build_tenant_record(payload)
        tenant = self._ensure_tenant(session, tenant_record)
        subject_record = build_subject_record(payload, tenant=tenant)
        existing = self._select_subject(
            session,
            tenant_id=str(subject_record["tenant_ref"]["id"]),
            subject_id=str(subject_record["subject_ref"]["id"]),
        )
        if existing is None:
            self._insert_subject(session, subject_record)
            existing = self._select_subject(
                session,
                tenant_id=str(subject_record["tenant_ref"]["id"]),
                subject_id=str(subject_record["subject_ref"]["id"]),
            )
        assert existing is not None
        return build_subject_registry_snapshot(tenant=tenant, subject=existing)

    def _insert_subject(self, session: Session, record: dict[str, Any]) -> None:
        metadata_expression = _json_sql_expression(session, "metadata")
        session.execute(
            text(
                f"""
                INSERT INTO oa_subjects (
                    tenant_id,
                    subject_id,
                    subject_ref_type,
                    display_name,
                    status,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (
                    :tenant_id,
                    :subject_id,
                    :subject_ref_type,
                    :display_name,
                    :status,
                    {metadata_expression},
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "tenant_id": record["tenant_ref"]["id"],
                "subject_id": record["subject_ref"]["id"],
                "subject_ref_type": record["subject_ref"]["type"],
                "display_name": record["display_name"],
                "status": record["status"],
                "metadata": _json_dumps(record["metadata"]),
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            },
        )

    def _select_tenant(
        self,
        session: Session,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT
                    tenant_id,
                    tenant_ref_type,
                    display_name,
                    status,
                    metadata,
                    created_at,
                    updated_at
                FROM oa_tenants
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().first()
        if row is None:
            return None
        return _tenant_from_row(row)

    def _select_subject(
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
                    subject_id,
                    subject_ref_type,
                    display_name,
                    status,
                    metadata,
                    created_at,
                    updated_at
                FROM oa_subjects
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
        return _subject_from_row(row)


DEFAULT_SUBJECT_REGISTRY = InMemoryOaSubjectRegistry()


def build_subject_registry_for_runtime(
    runtime: ServicePersistenceRuntime,
) -> OaSubjectRegistry:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaSubjectRegistry(runtime.api_session_factory)
    return DEFAULT_SUBJECT_REGISTRY


def register_subject_registry_routes(
    app: FastAPI,
    *,
    registry: OaSubjectRegistry | None = None,
) -> None:
    subject_registry = registry or DEFAULT_SUBJECT_REGISTRY

    @app.post("/internal/v1/subject-registry/ensure", response_model=None)
    def ensure_subject_registry_entry(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_oa_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            snapshot = subject_registry.ensure_subject(payload)
        except SubjectRegistryError as exc:
            return _subject_registry_problem_response(request, exc)
        return _attach_request_context(snapshot, request)

    @app.get("/internal/v1/subject-registry/tenants/{tenant_id}", response_model=None)
    def get_tenant(
        tenant_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_oa_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            tenant = subject_registry.get_tenant(tenant_id)
        except SubjectRegistryError as exc:
            return _subject_registry_problem_response(request, exc)
        if tenant is None:
            return _subject_registry_problem_response(
                request,
                SubjectRegistryError(
                    status_code=404,
                    error_code="oa.tenant_not_found",
                    detail=f"Tenant was not found: {tenant_id}",
                ),
            )
        return _attach_request_context(
            {
                "snapshot_schema_version": OA_SUBJECT_REGISTRY_SNAPSHOT_SCHEMA_VERSION,
                "service_id": "nex-oa",
                "registry_capability": "stable_subject_registry",
                "tenant_ref": tenant["tenant_ref"],
                "tenant": tenant,
                "subject_ref": None,
                "subject": None,
                "compatibility_aliases": {"tenant_id": tenant["tenant_ref"]["id"]},
                "capabilities": dict(OA_SUBJECT_REGISTRY_CAPABILITIES),
                "deferred": list(OA_SUBJECT_REGISTRY_DEFERRED),
                "private_payload_policy": _private_payload_policy(),
                "next_slice": "0198_oa_subject_registry_resolver_client",
            },
            request,
        )

    @app.get(
        "/internal/v1/subject-registry/tenants/{tenant_id}/subjects/{subject_id}",
        response_model=None,
    )
    def get_subject(
        tenant_id: str,
        subject_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_oa_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            snapshot = subject_registry.get_subject(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except SubjectRegistryError as exc:
            return _subject_registry_problem_response(request, exc)
        if snapshot is None:
            return _subject_registry_problem_response(
                request,
                SubjectRegistryError(
                    status_code=404,
                    error_code="oa.subject_not_found",
                    detail=f"Subject was not found: {tenant_id}/{subject_id}",
                ),
            )
        return _attach_request_context(snapshot, request)


def build_tenant_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_private_identity_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    display_name = _bounded_display_name(
        payload.get("tenant_display_name"),
        default=DEFAULT_TENANT_DISPLAY_NAME,
        field_name="tenant_display_name",
    )
    now = _utc_now()
    return {
        "registry_schema_version": OA_SUBJECT_REGISTRY_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": tenant_id},
        "display_name": display_name,
        "status": normalize_subject_status(payload.get("tenant_status", "ACTIVE")),
        "metadata": _metadata_from_payload(payload.get("tenant_metadata", {})),
        "created_at": now,
        "updated_at": now,
    }


def build_subject_record(
    payload: Mapping[str, Any],
    *,
    tenant: Mapping[str, Any],
) -> dict[str, Any]:
    _reject_private_identity_payload(payload)
    subject_id = _subject_id_from_payload(payload)
    display_name = _bounded_display_name(
        payload.get("subject_display_name", payload.get("display_name")),
        default=DEFAULT_SUBJECT_DISPLAY_NAME,
        field_name="subject_display_name",
    )
    now = _utc_now()
    tenant_ref = _mapping_value(tenant.get("tenant_ref"))
    return {
        "registry_schema_version": OA_SUBJECT_REGISTRY_SCHEMA_VERSION,
        "tenant_ref": {
            "type": _non_empty_text(tenant_ref.get("type"), field_name="tenant_ref.type"),
            "id": _non_empty_text(tenant_ref.get("id"), field_name="tenant_ref.id"),
        },
        "subject_id": subject_id,
        "subject_ref": {"type": OA_USER_REF_TYPE, "id": subject_id},
        "display_name": display_name,
        "status": normalize_subject_status(payload.get("subject_status", "ACTIVE")),
        "metadata": _metadata_from_payload(payload.get("subject_metadata", {})),
        "created_at": now,
        "updated_at": now,
    }


def build_subject_registry_snapshot(
    *,
    tenant: Mapping[str, Any],
    subject: Mapping[str, Any],
) -> dict[str, Any]:
    tenant_ref = _mapping_value(tenant.get("tenant_ref"))
    subject_ref = _mapping_value(subject.get("subject_ref"))
    return {
        "snapshot_schema_version": OA_SUBJECT_REGISTRY_SNAPSHOT_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "registry_capability": "stable_subject_registry",
        "tenant_ref": {
            "type": _non_empty_text(tenant_ref.get("type"), field_name="tenant_ref.type"),
            "id": _non_empty_text(tenant_ref.get("id"), field_name="tenant_ref.id"),
        },
        "subject_ref": {
            "type": _non_empty_text(
                subject_ref.get("type"),
                field_name="subject_ref.type",
            ),
            "id": _non_empty_text(subject_ref.get("id"), field_name="subject_ref.id"),
        },
        "tenant": _safe_record_copy(tenant),
        "subject": _safe_record_copy(subject),
        "compatibility_aliases": {
            "tenant_id": tenant_ref["id"],
            "owner_user_id": subject_ref["id"],
            "user_id": subject_ref["id"],
        },
        "capabilities": dict(OA_SUBJECT_REGISTRY_CAPABILITIES),
        "deferred": list(OA_SUBJECT_REGISTRY_DEFERRED),
        "private_payload_policy": _private_payload_policy(),
        "next_slice": "0198_oa_subject_registry_resolver_client",
    }


def normalize_subject_status(value: object) -> str:
    status = _non_empty_text(value, field_name="status").upper()
    if status not in OA_SUBJECT_STATUSES:
        allowed = ", ".join(OA_SUBJECT_STATUSES)
        raise SubjectRegistryError(
            status_code=400,
            error_code="oa.subject_status_invalid",
            detail=f"status must be one of: {allowed}.",
        )
    return status


def normalize_registry_id(
    value: object,
    *,
    field_name: str,
    default: str | None = None,
) -> str:
    normalized = _non_empty_text(value, field_name=field_name, default=default)
    if _ID_PATTERN.fullmatch(normalized) is None:
        raise SubjectRegistryError(
            status_code=400,
            error_code="oa.subject_ref_invalid",
            detail=(
                f"{field_name} must start with an ASCII letter or digit and "
                "contain only ASCII letters, digits, dot, underscore, colon, or hyphen."
            ),
        )
    return normalized


def payload_has_private_identity_data(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _PRIVATE_IDENTITY_KEY_PARTS):
                return True
            if payload_has_private_identity_data(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(payload_has_private_identity_data(item) for item in value)
    return False


def _tenant_id_from_payload(payload: Mapping[str, Any]) -> str:
    return normalize_registry_id(
        payload.get("tenant_id"),
        field_name="tenant_id",
        default=DEFAULT_TENANT_ID,
    )


def _subject_id_from_payload(payload: Mapping[str, Any]) -> str:
    value = payload.get(
        "subject_id",
        payload.get("owner_user_id", payload.get("user_id")),
    )
    return normalize_registry_id(
        value,
        field_name="subject_id",
        default=DEFAULT_SUBJECT_ID,
    )


def _bounded_display_name(
    value: object,
    *,
    default: str,
    field_name: str,
) -> str:
    normalized = _non_empty_text(value, field_name=field_name, default=default)
    return normalized[:120]


def _metadata_from_payload(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SubjectRegistryError(
            status_code=400,
            error_code="oa.subject_metadata_invalid",
            detail="metadata must be an object.",
        )
    _reject_private_identity_payload(value)
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise SubjectRegistryError(
            status_code=400,
            error_code="oa.subject_metadata_invalid",
            detail="metadata must be JSON serializable.",
        ) from exc
    return deepcopy(dict(value))


def _reject_private_identity_payload(value: object) -> None:
    if payload_has_private_identity_data(value):
        raise SubjectRegistryError(
            status_code=400,
            error_code="oa.private_identity_payload_rejected",
            detail=(
                "Subject registry records must not include passwords, tokens, "
                "email addresses, phone numbers, raw profiles, or secrets."
            ),
        )


def _attach_request_context(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return {
        **payload,
        "trace_id": trace_id_from_headers(request),
        "request_id": request_id_from_headers(request),
    }


def _authorize_oa_request(
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


def _subject_registry_problem_response(
    request: Request,
    exc: SubjectRegistryError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Subject registry request failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/subject-registry-failed",
    )


def _subject_key(record: Mapping[str, Any]) -> tuple[str, str]:
    tenant_ref = _mapping_value(record.get("tenant_ref"))
    subject_ref = _mapping_value(record.get("subject_ref"))
    return (
        str(tenant_ref["id"]),
        str(subject_ref["id"]),
    )


def _tenant_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "registry_schema_version": OA_SUBJECT_REGISTRY_SCHEMA_VERSION,
        "tenant_id": str(row["tenant_id"]),
        "tenant_ref": {
            "type": str(row["tenant_ref_type"]),
            "id": str(row["tenant_id"]),
        },
        "display_name": str(row["display_name"]),
        "status": str(row["status"]),
        "metadata": _json_loads(row["metadata"], default={}),
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _subject_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "registry_schema_version": OA_SUBJECT_REGISTRY_SCHEMA_VERSION,
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": str(row["tenant_id"])},
        "subject_id": str(row["subject_id"]),
        "subject_ref": {
            "type": str(row["subject_ref_type"]),
            "id": str(row["subject_id"]),
        },
        "display_name": str(row["display_name"]),
        "status": str(row["status"]),
        "metadata": _json_loads(row["metadata"], default={}),
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _safe_record_copy(record: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(record))


def _mapping_value(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _non_empty_text(
    value: object,
    *,
    field_name: str,
    default: str | None = None,
) -> str:
    if value is None:
        if default is None:
            raise SubjectRegistryError(
                status_code=400,
                error_code="oa.subject_field_invalid",
                detail=f"{field_name} must be a non-empty string.",
            )
        value = default
    if not isinstance(value, str):
        raise SubjectRegistryError(
            status_code=400,
            error_code="oa.subject_field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    normalized = value.strip()
    if not normalized:
        raise SubjectRegistryError(
            status_code=400,
            error_code="oa.subject_field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return normalized


def _json_sql_expression(session: Session, param_name: str) -> str:
    if _dialect_name(session) == "postgresql":
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


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _private_payload_policy() -> str:
    return (
        "Store stable tenant/user subject refs, display names, status, and safe "
        "metadata only. Do not store passwords, tokens, raw identity profiles, "
        "email addresses, phone numbers, or other identity secrets."
    )


def _subject_registry_unavailable() -> SubjectRegistryError:
    return SubjectRegistryError(
        status_code=503,
        error_code="oa.subject_registry_unavailable",
        detail="OA subject registry is unavailable.",
        retryable=True,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
