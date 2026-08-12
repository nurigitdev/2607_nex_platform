from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
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
    PERSISTENCE_MODE_POSTGRES,
    ServicePersistenceRuntime,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_LOCAL_CREDENTIAL_SCHEMA_VERSION = "oa_local_credential.v1"
OA_LOCAL_CREDENTIAL_SNAPSHOT_SCHEMA_VERSION = "oa_local_credential_snapshot.v1"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256.v1"
DEFAULT_PBKDF2_ITERATIONS = 210_000
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
OA_CREDENTIAL_STATUSES = (
    "ACTIVE",
    "PASSWORD_RESET_REQUIRED",
    "LOCKED",
    "DISABLED",
)
OA_CREDENTIAL_CAPABILITIES = {
    "employee_id_password_login": True,
    "credential_hash_storage": True,
    "operator_seeded_accounts": True,
    "self_service_signup": False,
    "external_identity_provider": False,
}
OA_CREDENTIAL_DEFERRED = [
    "argon2id_dependency_integration",
    "self_service_signup",
    "password_change_ui",
    "password_reset_email",
    "mfa",
    "oidc_saml_sso",
    "hr_roster_sync",
]

_EMPLOYEE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRIVATE_CREDENTIAL_KEY_PARTS = (
    "authorization",
    "cookie",
    "passwd",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class OaCredentialError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class OaCredentialRegistry(Protocol):
    def ensure_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def get_credential(
        self,
        *,
        tenant_id: str,
        employee_id: str,
    ) -> dict[str, Any] | None:
        ...

    def verify_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class InMemoryOaCredentialRegistry:
    subject_registry: OaSubjectRegistry = field(default_factory=InMemoryOaSubjectRegistry)
    credentials: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def ensure_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        subject_snapshot = _ensure_subject_snapshot(self.subject_registry, payload)
        record = build_credential_record(payload, subject_snapshot=subject_snapshot)
        key = _credential_key(record)
        existing = self.credentials.get(key)
        if existing is None:
            self.credentials[key] = deepcopy(record)
            existing = record
        return build_credential_snapshot(
            credential=existing,
            subject_snapshot=subject_snapshot,
        )

    def get_credential(
        self,
        *,
        tenant_id: str,
        employee_id: str,
    ) -> dict[str, Any] | None:
        normalized_tenant_id = _normalize_tenant_id(tenant_id)
        normalized_employee_id = normalize_employee_id(employee_id)
        record = self.credentials.get((normalized_tenant_id, normalized_employee_id))
        if record is None:
            return None
        subject_snapshot = _get_subject_snapshot(
            self.subject_registry,
            tenant_id=normalized_tenant_id,
            subject_id=str(record["subject_ref"]["id"]),
        )
        if subject_snapshot is None:
            raise _credential_unavailable()
        return build_credential_snapshot(
            credential=record,
            subject_snapshot=subject_snapshot,
        )

    def verify_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = self._private_credential(payload)
        _verify_active_credential(record)
        verify_password(
            _required_password(payload.get("password")),
            password_hash=str(record["password_hash"]),
        )
        subject_snapshot = _get_subject_snapshot(
            self.subject_registry,
            tenant_id=str(record["tenant_ref"]["id"]),
            subject_id=str(record["subject_ref"]["id"]),
        )
        if subject_snapshot is None:
            raise _credential_unavailable()
        return build_credential_snapshot(
            credential=record,
            subject_snapshot=subject_snapshot,
        )

    def _private_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tenant_id = _tenant_id_from_payload(payload)
        employee_id = employee_id_from_payload(payload)
        record = self.credentials.get((tenant_id, employee_id))
        if record is None:
            raise _credential_not_verified()
        return record


class SqlAlchemyOaCredentialRegistry:
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

    def ensure_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        subject_snapshot = _ensure_subject_snapshot(self._subject_registry, payload)
        record = build_credential_record(payload, subject_snapshot=subject_snapshot)
        try:
            stored = self._run_in_transaction(
                lambda session: self._ensure_credential(session, record)
            )
        except IntegrityError as exc:
            existing = self.get_credential(
                tenant_id=str(record["tenant_ref"]["id"]),
                employee_id=str(record["normalized_employee_id"]),
            )
            if existing is not None:
                return existing
            raise _credential_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _credential_unavailable() from exc
        return build_credential_snapshot(
            credential=stored,
            subject_snapshot=subject_snapshot,
        )

    def get_credential(
        self,
        *,
        tenant_id: str,
        employee_id: str,
    ) -> dict[str, Any] | None:
        normalized_tenant_id = _normalize_tenant_id(tenant_id)
        normalized_employee_id = normalize_employee_id(employee_id)
        try:
            with self._session_factory() as session:
                record = self._select_credential(
                    session,
                    tenant_id=normalized_tenant_id,
                    normalized_employee_id=normalized_employee_id,
                )
        except SQLAlchemyError as exc:
            raise _credential_unavailable() from exc
        if record is None:
            return None
        subject_snapshot = _get_subject_snapshot(
            self._subject_registry,
            tenant_id=normalized_tenant_id,
            subject_id=str(record["subject_ref"]["id"]),
        )
        if subject_snapshot is None:
            raise _credential_unavailable()
        return build_credential_snapshot(
            credential=record,
            subject_snapshot=subject_snapshot,
        )

    def verify_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tenant_id = _tenant_id_from_payload(payload)
        employee_id = employee_id_from_payload(payload)
        try:
            with self._session_factory() as session:
                record = self._select_credential(
                    session,
                    tenant_id=tenant_id,
                    normalized_employee_id=employee_id,
                )
        except SQLAlchemyError as exc:
            raise _credential_unavailable() from exc
        if record is None:
            raise _credential_not_verified()
        _verify_active_credential(record)
        verify_password(
            _required_password(payload.get("password")),
            password_hash=str(record["password_hash"]),
        )
        subject_snapshot = _get_subject_snapshot(
            self._subject_registry,
            tenant_id=tenant_id,
            subject_id=str(record["subject_ref"]["id"]),
        )
        if subject_snapshot is None:
            raise _credential_unavailable()
        return build_credential_snapshot(
            credential=record,
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

    def _ensure_credential(
        self,
        session: Session,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_credential(
            session,
            tenant_id=str(record["tenant_ref"]["id"]),
            normalized_employee_id=str(record["normalized_employee_id"]),
        )
        if existing is not None:
            return existing
        self._insert_credential(session, record)
        stored = self._select_credential(
            session,
            tenant_id=str(record["tenant_ref"]["id"]),
            normalized_employee_id=str(record["normalized_employee_id"]),
        )
        assert stored is not None
        return stored

    def _insert_credential(
        self,
        session: Session,
        record: Mapping[str, Any],
    ) -> None:
        metadata_expression = _json_sql_expression(session, "metadata")
        session.execute(
            text(
                f"""
                INSERT INTO oa_local_credentials (
                    credential_id,
                    credential_schema_version,
                    tenant_id,
                    subject_ref_type,
                    subject_id,
                    employee_id,
                    normalized_employee_id,
                    status,
                    password_hash,
                    password_hash_algorithm,
                    failed_attempt_count,
                    locked_at,
                    password_changed_at,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (
                    :credential_id,
                    :credential_schema_version,
                    :tenant_id,
                    :subject_ref_type,
                    :subject_id,
                    :employee_id,
                    :normalized_employee_id,
                    :status,
                    :password_hash,
                    :password_hash_algorithm,
                    :failed_attempt_count,
                    :locked_at,
                    :password_changed_at,
                    {metadata_expression},
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "credential_id": record["credential_id"],
                "credential_schema_version": record["credential_schema_version"],
                "tenant_id": record["tenant_ref"]["id"],
                "subject_ref_type": record["subject_ref"]["type"],
                "subject_id": record["subject_ref"]["id"],
                "employee_id": record["employee_id"],
                "normalized_employee_id": record["normalized_employee_id"],
                "status": record["status"],
                "password_hash": record["password_hash"],
                "password_hash_algorithm": record["password_hash_algorithm"],
                "failed_attempt_count": record["failed_attempt_count"],
                "locked_at": record["locked_at"],
                "password_changed_at": record["password_changed_at"],
                "metadata": _json_dumps(record["metadata"]),
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            },
        )

    def _select_credential(
        self,
        session: Session,
        *,
        tenant_id: str,
        normalized_employee_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT
                    credential_id,
                    credential_schema_version,
                    tenant_id,
                    subject_ref_type,
                    subject_id,
                    employee_id,
                    normalized_employee_id,
                    status,
                    password_hash,
                    password_hash_algorithm,
                    failed_attempt_count,
                    locked_at,
                    password_changed_at,
                    metadata,
                    created_at,
                    updated_at
                FROM oa_local_credentials
                WHERE tenant_id = :tenant_id
                  AND normalized_employee_id = :normalized_employee_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "normalized_employee_id": normalized_employee_id,
            },
        ).mappings().first()
        if row is None:
            return None
        return _credential_from_row(row)


DEFAULT_CREDENTIAL_REGISTRY = InMemoryOaCredentialRegistry()


def build_credential_registry_for_runtime(
    runtime: ServicePersistenceRuntime,
    *,
    subject_registry: OaSubjectRegistry | None = None,
) -> OaCredentialRegistry:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaCredentialRegistry(
            runtime.api_session_factory,
            subject_registry=subject_registry,
        )
    if subject_registry is not None:
        return InMemoryOaCredentialRegistry(subject_registry=subject_registry)
    return DEFAULT_CREDENTIAL_REGISTRY


def register_local_credential_routes(
    app: FastAPI,
    *,
    registry: OaCredentialRegistry | None = None,
) -> None:
    credential_registry = registry or DEFAULT_CREDENTIAL_REGISTRY

    @app.post("/internal/v1/auth/local-credentials/ensure", response_model=None)
    def ensure_local_credential(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_credential_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            snapshot = credential_registry.ensure_credential(payload)
        except OaCredentialError as exc:
            return _credential_problem_response(request, exc)
        return _attach_request_context(snapshot, request)

    @app.get(
        "/internal/v1/auth/local-credentials/tenants/{tenant_id}/employee-ids/{employee_id}",
        response_model=None,
    )
    def get_local_credential(
        tenant_id: str,
        employee_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize_oa_credential_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            snapshot = credential_registry.get_credential(
                tenant_id=tenant_id,
                employee_id=employee_id,
            )
        except OaCredentialError as exc:
            return _credential_problem_response(request, exc)
        if snapshot is None:
            return _credential_problem_response(
                request,
                OaCredentialError(
                    status_code=404,
                    error_code="oa.credential_not_found",
                    detail=f"Credential was not found: {tenant_id}/{employee_id}",
                ),
            )
        return _attach_request_context(snapshot, request)


def build_credential_record(
    payload: Mapping[str, Any],
    *,
    subject_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
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
    employee_id = employee_id_original_from_payload(payload)
    normalized_employee_id = normalize_employee_id(employee_id)
    password_hash = _password_hash_from_payload(payload)
    now = _utc_now()
    status = normalize_credential_status(
        payload.get("credential_status", payload.get("status", "ACTIVE"))
    )
    return {
        "credential_schema_version": OA_LOCAL_CREDENTIAL_SCHEMA_VERSION,
        "credential_id": stable_credential_id(
            tenant_id=tenant_ref["id"],
            normalized_employee_id=normalized_employee_id,
        ),
        "tenant_ref": tenant_ref,
        "subject_ref": subject_ref,
        "employee_id": employee_id,
        "normalized_employee_id": normalized_employee_id,
        "status": status,
        "password_hash": password_hash,
        "password_hash_algorithm": password_hash_algorithm(password_hash),
        "failed_attempt_count": 0,
        "locked_at": now if status == "LOCKED" else None,
        "password_changed_at": now,
        "metadata": _metadata_from_payload(
            payload.get("credential_metadata", payload.get("metadata", {}))
        ),
        "created_at": now,
        "updated_at": now,
    }


def build_credential_snapshot(
    *,
    credential: Mapping[str, Any],
    subject_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    tenant_ref = _typed_ref(
        credential.get("tenant_ref"),
        expected_type=OA_TENANT_REF_TYPE,
        id_field_name="tenant_id",
    )
    subject_ref = _typed_ref(
        credential.get("subject_ref"),
        expected_type=OA_USER_REF_TYPE,
        id_field_name="subject_id",
    )
    return {
        "credential_snapshot_schema_version": (
            OA_LOCAL_CREDENTIAL_SNAPSHOT_SCHEMA_VERSION
        ),
        "service_id": "nex-oa",
        "identity_capability": "employee_id_password_login",
        "tenant_ref": tenant_ref,
        "subject_ref": subject_ref,
        "credential": _safe_credential_copy(credential),
        "subject_registry_snapshot": _safe_record_copy(subject_snapshot),
        "compatibility_aliases": {
            "tenant_id": tenant_ref["id"],
            "employee_id": str(credential["employee_id"]),
            "normalized_employee_id": str(credential["normalized_employee_id"]),
            "owner_user_id": subject_ref["id"],
            "user_id": subject_ref["id"],
        },
        "capabilities": dict(OA_CREDENTIAL_CAPABILITIES),
        "deferred": list(OA_CREDENTIAL_DEFERRED),
        "private_payload_policy": _private_payload_policy(),
        "next_slice": "0253_oa_user_login_api_foundation",
    }


def hash_password(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = DEFAULT_PBKDF2_ITERATIONS,
) -> str:
    normalized_password = _required_password(password)
    if iterations <= 0:
        raise OaCredentialError(
            status_code=500,
            error_code="oa.password_hash_config_invalid",
            detail="Password hash iterations must be positive.",
        )
    salt_bytes = salt if salt is not None else os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized_password.encode("utf-8"),
        salt_bytes,
        iterations,
    )
    return "$".join(
        [
            PASSWORD_HASH_ALGORITHM,
            str(iterations),
            _b64encode(salt_bytes),
            _b64encode(digest),
        ]
    )


def verify_password(password: str, *, password_hash: str) -> bool:
    normalized_password = _required_password(password)
    algorithm, iterations, salt, digest = _parse_password_hash(password_hash)
    if algorithm != PASSWORD_HASH_ALGORITHM:
        raise OaCredentialError(
            status_code=500,
            error_code="oa.password_hash_algorithm_unsupported",
            detail="Password hash algorithm is unsupported.",
        )
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        normalized_password.encode("utf-8"),
        salt,
        iterations,
    )
    if not hmac.compare_digest(candidate, digest):
        raise _credential_not_verified()
    return True


def password_hash_algorithm(password_hash: str) -> str:
    return _parse_password_hash(password_hash)[0]


def normalize_credential_status(value: object) -> str:
    status = _non_empty_text(value, field_name="credential_status").upper()
    if status not in OA_CREDENTIAL_STATUSES:
        allowed = ", ".join(OA_CREDENTIAL_STATUSES)
        raise OaCredentialError(
            status_code=400,
            error_code="oa.credential_status_invalid",
            detail=f"credential_status must be one of: {allowed}.",
        )
    return status


def employee_id_original_from_payload(payload: Mapping[str, Any]) -> str:
    value = payload.get("employee_id")
    if value is None:
        value = payload.get("login_identifier")
    if not isinstance(value, str) or not value.strip():
        raise OaCredentialError(
            status_code=400,
            error_code="oa.employee_id_invalid",
            detail="employee_id must be a non-empty string.",
        )
    normalized = value.strip()
    if _EMPLOYEE_ID_PATTERN.fullmatch(normalized) is None:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.employee_id_invalid",
            detail=(
                "employee_id must start with an ASCII letter or digit and "
                "contain only ASCII letters, digits, dot, underscore, colon, or hyphen."
            ),
        )
    return normalized


def employee_id_from_payload(payload: Mapping[str, Any]) -> str:
    return normalize_employee_id(employee_id_original_from_payload(payload))


def normalize_employee_id(value: object) -> str:
    if not isinstance(value, str):
        raise OaCredentialError(
            status_code=400,
            error_code="oa.employee_id_invalid",
            detail="employee_id must be a non-empty string.",
        )
    return employee_id_original_from_payload({"employee_id": value}).casefold()


def stable_credential_id(*, tenant_id: str, normalized_employee_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "|".join(
                [
                    "nex-platform",
                    "oa-local-credential",
                    tenant_id,
                    normalized_employee_id,
                ]
            ),
        )
    )


def _password_hash_from_payload(payload: Mapping[str, Any]) -> str:
    password = payload.get("password")
    password_hash = payload.get("password_hash")
    if password is not None and password_hash is not None:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.credential_secret_conflict",
            detail="Provide either password or password_hash, not both.",
        )
    if password is not None:
        return hash_password(_required_password(password))
    if isinstance(password_hash, str) and password_hash.strip():
        algorithm = password_hash_algorithm(password_hash.strip())
        if algorithm != PASSWORD_HASH_ALGORITHM:
            raise OaCredentialError(
                status_code=400,
                error_code="oa.password_hash_algorithm_unsupported",
                detail="password_hash uses an unsupported algorithm.",
            )
        return password_hash.strip()
    raise OaCredentialError(
        status_code=400,
        error_code="oa.credential_secret_missing",
        detail="Credential seed requires password or password_hash.",
    )


def _required_password(value: object) -> str:
    if not isinstance(value, str):
        raise OaCredentialError(
            status_code=400,
            error_code="oa.password_invalid",
            detail="password must be a string.",
        )
    password = value.strip()
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.password_invalid",
            detail=(
                f"password must be between {MIN_PASSWORD_LENGTH} and "
                f"{MAX_PASSWORD_LENGTH} characters."
            ),
        )
    return password


def _parse_password_hash(password_hash: str) -> tuple[str, int, bytes, bytes]:
    parts = password_hash.split("$")
    if len(parts) != 4:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.password_hash_invalid",
            detail="password_hash format is invalid.",
        )
    algorithm, raw_iterations, raw_salt, raw_digest = parts
    try:
        iterations = int(raw_iterations)
        salt = _b64decode(raw_salt)
        digest = _b64decode(raw_digest)
    except (TypeError, ValueError) as exc:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.password_hash_invalid",
            detail="password_hash format is invalid.",
        ) from exc
    if iterations <= 0 or not salt or not digest:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.password_hash_invalid",
            detail="password_hash format is invalid.",
        )
    return algorithm, iterations, salt, digest


def _credential_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "credential_schema_version": str(row["credential_schema_version"]),
        "credential_id": str(row["credential_id"]),
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": str(row["tenant_id"])},
        "subject_ref": {
            "type": str(row["subject_ref_type"]),
            "id": str(row["subject_id"]),
        },
        "employee_id": str(row["employee_id"]),
        "normalized_employee_id": str(row["normalized_employee_id"]),
        "status": str(row["status"]),
        "password_hash": str(row["password_hash"]),
        "password_hash_algorithm": str(row["password_hash_algorithm"]),
        "failed_attempt_count": int(row["failed_attempt_count"]),
        "locked_at": _timestamp_to_wire(row["locked_at"]) if row["locked_at"] else None,
        "password_changed_at": _timestamp_to_wire(row["password_changed_at"]),
        "metadata": _json_loads(row["metadata"], default={}),
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _ensure_subject_snapshot(
    subject_registry: OaSubjectRegistry,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    employee_id = employee_id_from_payload(payload)
    subject_payload = {
        "tenant_id": _tenant_id_from_payload(payload),
        "subject_id": payload.get("subject_id") or employee_id,
        "tenant_display_name": payload.get("tenant_display_name"),
        "subject_display_name": payload.get("subject_display_name")
        or payload.get("display_name")
        or employee_id,
        "subject_metadata": payload.get("subject_metadata", {}),
    }
    try:
        return subject_registry.ensure_subject(subject_payload)
    except SubjectRegistryError as exc:
        raise _credential_error_from_subject_error(exc) from exc


def _get_subject_snapshot(
    subject_registry: OaSubjectRegistry,
    *,
    tenant_id: str,
    subject_id: str,
) -> dict[str, Any] | None:
    try:
        return subject_registry.get_subject(tenant_id=tenant_id, subject_id=subject_id)
    except SubjectRegistryError as exc:
        raise _credential_error_from_subject_error(exc) from exc


def _credential_error_from_subject_error(exc: SubjectRegistryError) -> OaCredentialError:
    return OaCredentialError(
        status_code=exc.status_code,
        error_code=exc.error_code,
        detail=exc.detail,
        retryable=exc.retryable,
    )


def _typed_ref(
    value: object,
    *,
    expected_type: str,
    id_field_name: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise OaCredentialError(
            status_code=400,
            error_code="oa.credential_ref_invalid",
            detail=f"{id_field_name} ref must be an object.",
        )
    ref_type = _non_empty_text(value.get("type"), field_name=f"{id_field_name}.type")
    if ref_type != expected_type:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.credential_ref_invalid",
            detail=f"{id_field_name}.type must be {expected_type}.",
        )
    return {
        "type": ref_type,
        "id": _non_empty_text(value.get("id"), field_name=id_field_name),
    }


def _tenant_id_from_payload(payload: Mapping[str, Any]) -> str:
    return _normalize_tenant_id(payload.get("tenant_id"))


def _normalize_tenant_id(value: object) -> str:
    try:
        return normalize_registry_id(value, field_name="tenant_id")
    except SubjectRegistryError as exc:
        raise _credential_error_from_subject_error(exc) from exc


def _verify_active_credential(record: Mapping[str, Any]) -> None:
    if record.get("status") != "ACTIVE":
        raise OaCredentialError(
            status_code=401,
            error_code="oa.credential_not_active",
            detail="Credential is not active.",
        )


def _metadata_from_payload(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise OaCredentialError(
            status_code=400,
            error_code="oa.credential_metadata_invalid",
            detail="credential metadata must be an object.",
        )
    _reject_private_credential_payload(value)
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.credential_metadata_invalid",
            detail="credential metadata must be JSON serializable.",
        ) from exc
    return deepcopy(dict(value))


def _reject_private_credential_payload(value: object) -> None:
    if payload_has_private_identity_data(value) or _payload_has_private_key(value):
        raise OaCredentialError(
            status_code=400,
            error_code="oa.private_credential_payload_rejected",
            detail=(
                "Credential metadata must not include passwords, hashes, tokens, "
                "browser cookies, authorization headers, or secrets."
            ),
        )


def _payload_has_private_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _PRIVATE_CREDENTIAL_KEY_PARTS):
                return True
            if _payload_has_private_key(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_payload_has_private_key(item) for item in value)
    return False


def _attach_request_context(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return {
        **payload,
        "trace_id": trace_id_from_headers(request),
        "request_id": request_id_from_headers(request),
    }


def _authorize_oa_credential_request(
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


def _credential_problem_response(
    request: Request,
    exc: OaCredentialError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="OA credential request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/oa-credential-failed",
    )


def _credential_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(record["tenant_ref"]["id"]),
        str(record["normalized_employee_id"]),
    )


def _safe_credential_copy(record: Mapping[str, Any]) -> dict[str, Any]:
    safe = deepcopy(dict(record))
    safe.pop("password_hash", None)
    safe["hash_algorithm"] = safe.pop("password_hash_algorithm", None)
    return safe


def _safe_record_copy(record: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(record))


def _non_empty_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise OaCredentialError(
            status_code=400,
            error_code="oa.credential_field_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    normalized = value.strip()
    if not normalized:
        raise OaCredentialError(
            status_code=400,
            error_code="oa.credential_field_invalid",
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


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        observed = value
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _private_payload_policy() -> str:
    return (
        "Store employee login aliases, stable tenant/user subject refs, status, "
        "password hashes, and safe metadata only. Never return password hashes "
        "from APIs and never store raw passwords, tokens, cookies, authorization "
        "headers, provider secrets, or database URLs."
    )


def _credential_not_verified() -> OaCredentialError:
    return OaCredentialError(
        status_code=401,
        error_code="oa.credential_not_verified",
        detail="Employee id or password is invalid.",
    )


def _credential_unavailable() -> OaCredentialError:
    return OaCredentialError(
        status_code=503,
        error_code="oa.credential_registry_unavailable",
        detail="OA credential registry is unavailable.",
        retryable=True,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
