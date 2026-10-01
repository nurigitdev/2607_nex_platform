from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.auth_events import (
    OaAuthEventRepository,
    auth_event_target,
    record_auth_event_safely,
)
from nex_oa.credentials import (
    LOCKOUT_DURATION_SECONDS,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    InMemoryOaCredentialRegistry,
    OaCredentialError,
    build_failed_login_state,
    hash_password,
    normalize_employee_id,
    password_hash_algorithm,
    verify_password,
)
from nex_oa.sessions import InMemoryOaSessionRegistry, build_revoked_session_record
from nex_oa.subjects import SubjectRegistryError, normalize_registry_id
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    PERSISTENCE_MODE_POSTGRES,
    ServicePersistenceRuntime,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


OA_CREDENTIAL_SECURITY_WRITE_SCOPE = "credential:security:write"
OA_CREDENTIAL_ROTATION_SCHEMA_VERSION = "oa_credential_rotation.v1"
_CHANGE_FIELDS = frozenset(
    {"tenant_id", "employee_id", "current_password", "new_password"}
)
_RESET_FIELDS = frozenset(
    {"tenant_id", "employee_id", "temporary_password", "reason_code"}
)


@dataclass(frozen=True)
class OaCredentialSecurityError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class OaCredentialSecurityRepository(Protocol):
    def change_password(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def reset_password(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass
class InMemoryOaCredentialSecurityRepository:
    credential_registry: InMemoryOaCredentialRegistry
    session_registry: InMemoryOaSessionRegistry

    def change_password(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = normalize_password_change_request(payload)
        record = self._credential(request, missing_is_private=True)
        _guard_change_status(record)
        try:
            verify_password(
                request["current_password"],
                password_hash=str(record["password_hash"]),
            )
        except OaCredentialError as exc:
            if exc.error_code == "oa.credential_not_verified":
                record.update(build_failed_login_state(record))
                raise _not_verified() from exc
            raise _from_credential_error(exc) from exc
        _reject_password_reuse(request["new_password"], record)
        return self._rotate(
            record,
            new_password=request["new_password"],
            operation="PASSWORD_CHANGED",
            target_status="ACTIVE",
            reason_code="user.password_change",
        )

    def reset_password(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = normalize_password_reset_request(payload)
        record = self._credential(request, missing_is_private=False)
        if record.get("status") == "DISABLED":
            raise _disabled_credential()
        return self._rotate(
            record,
            new_password=request["temporary_password"],
            operation="PASSWORD_RESET",
            target_status="PASSWORD_RESET_REQUIRED",
            reason_code=request["reason_code"],
        )

    def _credential(
        self, request: Mapping[str, Any], *, missing_is_private: bool
    ) -> dict[str, Any]:
        record = self.credential_registry.credentials.get(
            (str(request["tenant_id"]), str(request["employee_id"]))
        )
        if record is None:
            raise _not_verified() if missing_is_private else _target_not_found()
        return record

    def _rotate(
        self,
        record: dict[str, Any],
        *,
        new_password: str,
        operation: str,
        target_status: str,
        reason_code: str,
    ) -> dict[str, Any]:
        now = _utc_now()
        new_hash = hash_password(new_password)
        record.update(
            {
                "status": target_status,
                "password_hash": new_hash,
                "password_hash_algorithm": password_hash_algorithm(new_hash),
                "failed_attempt_count": 0,
                "locked_at": None,
                "password_changed_at": now,
                "updated_at": now,
            }
        )
        revoked = 0
        for session_id, session_record in tuple(self.session_registry.sessions.items()):
            if _session_matches_credential(session_record, record):
                updated, _, _ = build_revoked_session_record(session_record)
                self.session_registry.sessions[session_id] = deepcopy(updated)
                revoked += 1
        return build_rotation_response(
            record,
            operation=operation,
            reason_code=reason_code,
            revoked_session_count=revoked,
        )


class SqlAlchemyOaCredentialSecurityRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def change_password(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = normalize_password_change_request(payload)
        return self._run(
            lambda session: self._change_password(session, request)
        )

    def reset_password(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = normalize_password_reset_request(payload)
        return self._run(
            lambda session: self._reset_password(session, request)
        )

    def _run(self, operation: Any) -> dict[str, Any]:
        session = self._session_factory()
        error: OaCredentialSecurityError | None = None
        try:
            try:
                result, error = operation(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
        except OaCredentialSecurityError:
            raise
        except SQLAlchemyError as exc:
            raise _repository_unavailable() from exc
        finally:
            session.close()
        if error is not None:
            raise error
        assert result is not None
        return result

    def _change_password(
        self, session: Session, request: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, OaCredentialSecurityError | None]:
        record = self._select_credential(session, request)
        if record is None:
            return None, _not_verified()
        try:
            _guard_change_status(record)
            verify_password(
                str(request["current_password"]),
                password_hash=str(record["password_hash"]),
            )
        except OaCredentialSecurityError as exc:
            return None, exc
        except OaCredentialError as exc:
            if exc.error_code != "oa.credential_not_verified":
                raise _from_credential_error(exc) from exc
            self._record_failed_attempt(session, record)
            return None, _not_verified()
        _reject_password_reuse(str(request["new_password"]), record)
        return (
            self._rotate(
                session,
                record,
                new_password=str(request["new_password"]),
                operation="PASSWORD_CHANGED",
                target_status="ACTIVE",
                reason_code="user.password_change",
            ),
            None,
        )

    def _reset_password(
        self, session: Session, request: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, OaCredentialSecurityError | None]:
        record = self._select_credential(session, request)
        if record is None:
            return None, _target_not_found()
        if record.get("status") == "DISABLED":
            return None, _disabled_credential()
        return (
            self._rotate(
                session,
                record,
                new_password=str(request["temporary_password"]),
                operation="PASSWORD_RESET",
                target_status="PASSWORD_RESET_REQUIRED",
                reason_code=str(request["reason_code"]),
            ),
            None,
        )

    def _select_credential(
        self, session: Session, request: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        lock = " FOR UPDATE" if session.get_bind().dialect.name == "postgresql" else ""
        row = session.execute(
            text(
                """
                SELECT credential_id, tenant_id, subject_id, employee_id,
                       normalized_employee_id, status, password_hash,
                       password_hash_algorithm, failed_attempt_count, locked_at,
                       password_changed_at, updated_at
                FROM oa_local_credentials
                WHERE tenant_id = :tenant_id
                  AND normalized_employee_id = :employee_id
                """ + lock
            ),
            {
                "tenant_id": request["tenant_id"],
                "employee_id": request["employee_id"],
            },
        ).mappings().first()
        return dict(row) if row is not None else None

    def _record_failed_attempt(
        self, session: Session, record: Mapping[str, Any]
    ) -> None:
        now = _utc_now()
        session.execute(
            text(
                """
                UPDATE oa_local_credentials
                SET failed_attempt_count = failed_attempt_count + 1,
                    status = CASE
                        WHEN failed_attempt_count + 1 >= 5 THEN 'LOCKED'
                        ELSE status
                    END,
                    locked_at = CASE
                        WHEN failed_attempt_count + 1 >= 5 THEN :now
                        ELSE locked_at
                    END,
                    updated_at = :now
                WHERE credential_id = :credential_id
                """
            ),
            {"credential_id": record["credential_id"], "now": now},
        )

    def _rotate(
        self,
        session: Session,
        record: Mapping[str, Any],
        *,
        new_password: str,
        operation: str,
        target_status: str,
        reason_code: str,
    ) -> dict[str, Any]:
        now = _utc_now()
        new_hash = hash_password(new_password)
        session.execute(
            text(
                """
                UPDATE oa_local_credentials
                SET status = :status,
                    password_hash = :password_hash,
                    password_hash_algorithm = :password_hash_algorithm,
                    failed_attempt_count = 0,
                    locked_at = NULL,
                    password_changed_at = :now,
                    updated_at = :now
                WHERE credential_id = :credential_id
                """
            ),
            {
                "credential_id": record["credential_id"],
                "status": target_status,
                "password_hash": new_hash,
                "password_hash_algorithm": password_hash_algorithm(new_hash),
                "now": now,
            },
        )
        revoked = session.execute(
            text(
                """
                UPDATE oa_user_sessions
                SET status = 'REVOKED', revoked_at = :now, updated_at = :now
                WHERE tenant_id = :tenant_id
                  AND subject_id = :subject_id
                  AND status = 'ACTIVE'
                """
            ),
            {
                "tenant_id": record["tenant_id"],
                "subject_id": record["subject_id"],
                "now": now,
            },
        ).rowcount
        return build_rotation_response(
            {
                **record,
                "status": target_status,
                "password_changed_at": now,
                "updated_at": now,
            },
            operation=operation,
            reason_code=reason_code,
            revoked_session_count=int(revoked or 0),
        )


def build_credential_security_repository_for_runtime(
    runtime: ServicePersistenceRuntime,
    *,
    credential_registry: InMemoryOaCredentialRegistry,
    session_registry: InMemoryOaSessionRegistry,
) -> OaCredentialSecurityRepository:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaCredentialSecurityRepository(runtime.api_session_factory)
    return InMemoryOaCredentialSecurityRepository(
        credential_registry=credential_registry,
        session_registry=session_registry,
    )


def register_credential_security_routes(
    app: FastAPI,
    *,
    repository: OaCredentialSecurityRepository,
    auth_event_repository: OaAuthEventRepository | None = None,
) -> None:
    @app.post("/internal/v1/auth/local-credentials/change-password", response_model=None)
    def change_password(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            response = repository.change_password(payload)
        except OaCredentialSecurityError as exc:
            record_auth_event_safely(
                auth_event_repository,
                event_type="PASSWORD_CHANGED",
                outcome=_failure_outcome(exc.status_code),
                request=request,
                authorization=authorization,
                tenant_id=payload.get("tenant_id"),
                details={"error_code": exc.error_code},
            )
            return _problem(request, exc)
        target = auth_event_target(response)
        record_auth_event_safely(
            auth_event_repository,
            event_type="PASSWORD_CHANGED",
            outcome="SUCCEEDED",
            request=request,
            authorization=authorization,
            **target,
            details={
                "credential_status": response["credential_status"],
                "operation": response["operation"],
                "revoked_session_count": response["revoked_session_count"],
            },
        )
        return _with_context(response, request)

    @app.post("/internal/v1/auth/local-credentials/reset-password", response_model=None)
    def reset_password(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        auth_problem = _authorize(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            response = repository.reset_password(payload)
        except OaCredentialSecurityError as exc:
            record_auth_event_safely(
                auth_event_repository,
                event_type="PASSWORD_RESET",
                outcome=_failure_outcome(exc.status_code),
                request=request,
                authorization=authorization,
                tenant_id=payload.get("tenant_id"),
                details={"error_code": exc.error_code},
            )
            return _problem(request, exc)
        target = auth_event_target(response)
        record_auth_event_safely(
            auth_event_repository,
            event_type="PASSWORD_RESET",
            outcome="SUCCEEDED",
            request=request,
            authorization=authorization,
            **target,
            details={
                "credential_status": response["credential_status"],
                "operation": response["operation"],
                "revoked_session_count": response["revoked_session_count"],
            },
        )
        return _with_context(response, request)


def normalize_password_change_request(payload: Mapping[str, Any]) -> dict[str, str]:
    _validate_fields(payload, allowed=_CHANGE_FIELDS)
    return {
        "tenant_id": _tenant_id(payload.get("tenant_id")),
        "employee_id": _employee_id(payload.get("employee_id")),
        "current_password": _password(payload.get("current_password")),
        "new_password": _password(payload.get("new_password")),
    }


def normalize_password_reset_request(payload: Mapping[str, Any]) -> dict[str, str]:
    _validate_fields(payload, allowed=_RESET_FIELDS)
    return {
        "tenant_id": _tenant_id(payload.get("tenant_id")),
        "employee_id": _employee_id(payload.get("employee_id")),
        "temporary_password": _password(payload.get("temporary_password")),
        "reason_code": _text(payload.get("reason_code"), field="reason_code"),
    }


def build_rotation_response(
    record: Mapping[str, Any],
    *,
    operation: str,
    reason_code: str,
    revoked_session_count: int,
) -> dict[str, Any]:
    tenant_id = str(record.get("tenant_id") or (record.get("tenant_ref") or {}).get("id"))
    subject_id = str(record.get("subject_id") or (record.get("subject_ref") or {}).get("id"))
    return {
        "credential_rotation_schema_version": OA_CREDENTIAL_ROTATION_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "operation": operation,
        "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
        "subject_ref": {"type": "oa.user", "id": subject_id},
        "credential_id": str(record["credential_id"]),
        "credential_status": str(record["status"]),
        "password_changed_at": _timestamp_to_wire(record["password_changed_at"]),
        "revoked_session_count": revoked_session_count,
        "reason_code": reason_code,
        "metadata": {
            "password_hash_included": False,
            "raw_password_included": False,
            "session_identifiers_included": False,
            "session_revocation_atomic": True,
        },
    }


def _guard_change_status(record: Mapping[str, Any]) -> None:
    status = str(record.get("status"))
    if status == "DISABLED":
        raise _not_verified()
    if status == "LOCKED" and not _lockout_expired(record.get("locked_at")):
        raise _not_verified()


def _reject_password_reuse(new_password: str, record: Mapping[str, Any]) -> None:
    try:
        verify_password(new_password, password_hash=str(record["password_hash"]))
    except OaCredentialError as exc:
        if exc.error_code == "oa.credential_not_verified":
            return
        raise _from_credential_error(exc) from exc
    raise OaCredentialSecurityError(
        409,
        "oa.password_reuse_not_allowed",
        "New password must differ from the current password.",
    )


def _session_matches_credential(
    session_record: Mapping[str, Any], credential: Mapping[str, Any]
) -> bool:
    tenant_ref = session_record.get("tenant_ref") or {}
    subject_ref = session_record.get("subject_ref") or {}
    return (
        session_record.get("status") == "ACTIVE"
        and tenant_ref.get("id") == credential["tenant_ref"]["id"]
        and subject_ref.get("id") == credential["subject_ref"]["id"]
    )


def _lockout_expired(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, datetime):
        locked_at = value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    elif isinstance(value, str):
        try:
            locked_at = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).astimezone(UTC)
        except ValueError:
            return False
    else:
        return False
    return datetime.now(UTC) >= locked_at + timedelta(seconds=LOCKOUT_DURATION_SECONDS)


def _validate_fields(payload: Mapping[str, Any], *, allowed: frozenset[str]) -> None:
    if not isinstance(payload, Mapping):
        raise OaCredentialSecurityError(400, "oa.credential_security_payload_invalid", "Request must be an object.")
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise OaCredentialSecurityError(400, "oa.credential_security_payload_invalid", f"Unsupported field: {unexpected[0]}")
    missing = sorted(allowed - set(payload))
    if missing:
        raise OaCredentialSecurityError(400, "oa.credential_security_payload_invalid", f"Required field is missing: {missing[0]}")


def _tenant_id(value: object) -> str:
    try:
        return normalize_registry_id(value, field_name="tenant_id")
    except SubjectRegistryError as exc:
        raise OaCredentialSecurityError(exc.status_code, exc.error_code, exc.detail) from exc


def _employee_id(value: object) -> str:
    try:
        return normalize_employee_id(value)
    except OaCredentialError as exc:
        raise _from_credential_error(exc) from exc


def _password(value: object) -> str:
    if not isinstance(value, str):
        raise OaCredentialSecurityError(
            400, "oa.password_invalid", "password must be a string."
        )
    password = value.strip()
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise OaCredentialSecurityError(
            400,
            "oa.password_invalid",
            (
                f"password must be between {MIN_PASSWORD_LENGTH} and "
                f"{MAX_PASSWORD_LENGTH} characters."
            ),
        )
    return password


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OaCredentialSecurityError(400, "oa.credential_security_payload_invalid", f"{field} must be a non-empty string.")
    return value.strip()


def _authorize(request: Request, authorization: str | None) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-oa",
        required_scopes=[DEFAULT_SERVICE_SCOPE, OA_CREDENTIAL_SECURITY_WRITE_SCOPE],
    )
    if result.ok:
        return None
    status = 403 if result.error_code == "TOKEN_SCOPE_MISSING" else 401
    return problem_response(
        request,
        status_code=status,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authorization failed" if status == 403 else "Authentication failed",
        detail=result.detail or "OA credential security requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/oa-credential-security-authorization",
    )


def _problem(request: Request, exc: OaCredentialSecurityError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="OA credential security request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/oa-credential-security-failed",
    )


def _failure_outcome(status_code: int) -> str:
    return "BLOCKED" if status_code in {401, 403, 409} else "FAILED"


def _with_context(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return {
        **payload,
        "request_id": request_id_from_headers(request),
        "trace_id": trace_id_from_headers(request),
    }


def _not_verified() -> OaCredentialSecurityError:
    return OaCredentialSecurityError(401, "oa.credential_not_verified", "Credential could not be verified.")


def _target_not_found() -> OaCredentialSecurityError:
    return OaCredentialSecurityError(404, "oa.credential_security_target_not_found", "Credential security target was not found.")


def _disabled_credential() -> OaCredentialSecurityError:
    return OaCredentialSecurityError(409, "oa.credential_disabled", "Disabled credentials must be re-enabled through identity lifecycle control.")


def _repository_unavailable() -> OaCredentialSecurityError:
    return OaCredentialSecurityError(503, "oa.credential_security_unavailable", "Credential security persistence is unavailable.", True)


def _from_credential_error(exc: OaCredentialError) -> OaCredentialSecurityError:
    return OaCredentialSecurityError(exc.status_code, exc.error_code, exc.detail, exc.retryable)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_to_wire(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
        return parsed.isoformat().replace("+00:00", "Z")
    return str(value)
