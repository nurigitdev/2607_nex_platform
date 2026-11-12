from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    PERSISTENCE_MODE_POSTGRES,
    ServicePersistenceRuntime,
    admit_service_token_from_request,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.authorization import OaAuthorizationError

OA_PROJECT_DECISION_SCOPE = "authorization:read"
OA_PROJECT_DECISION_SCHEMA_VERSION = "oa_project_authorization_decision.v1"
OA_PROJECT_DECISION_RESPONSE_SCHEMA_VERSION = "oa_project_decision_response.v1"

PROJECT_ROLES = frozenset({"OWNER", "MANAGER", "MEMBER", "VIEWER"})
PROJECT_STATUSES = frozenset({"ACTIVE", "INACTIVE", "CLOSING", "CLOSED"})
GRANT_STATUSES = frozenset({"ACTIVE", "REVOKED"})

_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_ACTION = re.compile(r"^[a-z][a-z0-9_-]*(?::[a-z0-9_-]+){1,4}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")

_ACTION_ROLES = {
    "project:project:read": PROJECT_ROLES,
    "project:membership:manage": frozenset({"OWNER", "MANAGER"}),
    "project:project:admin": frozenset({"OWNER", "MANAGER"}),
    "project:work-code:approve": frozenset({"OWNER", "MANAGER"}),
    "project:work-assignment:manage": frozenset({"OWNER", "MANAGER"}),
    "project:work-assignment:read": PROJECT_ROLES,
    "project:work-assignment:perform": frozenset(
        {"OWNER", "MANAGER", "MEMBER"}
    ),
    "finance:voucher-candidate:create": frozenset(
        {"OWNER", "MANAGER", "MEMBER"}
    ),
    "finance:voucher-draft:create": frozenset({"OWNER", "MANAGER", "MEMBER"}),
    "finance:voucher-draft:read": PROJECT_ROLES,
    "finance:journal:request-approval": frozenset(
        {"OWNER", "MANAGER", "MEMBER"}
    ),
    "finance:report:read": PROJECT_ROLES,
}
_CLOSING_ACTIONS = frozenset(
    {
        "project:project:read",
        "project:work-assignment:read",
        "finance:voucher-draft:read",
        "finance:report:read",
    }
)


class OaProjectGrantRepository(Protocol):
    def apply_grant(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def get_grant(
        self, *, tenant_id: str, project_code: str, subject_id: str
    ) -> dict[str, Any] | None: ...


class EffectiveAuthorizationSource(Protocol):
    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, Any]: ...


@dataclass
class InMemoryOaProjectGrantRepository:
    grants: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    event_keys: dict[tuple[str, str], tuple[str, str, str]] = field(
        default_factory=dict
    )

    def apply_grant(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admitted = _admit_grant(payload)
        key = _grant_key(admitted)
        event_key = (admitted["tenant_id"], admitted["source_event_id"])
        event_owner = self.event_keys.get(event_key)
        if event_owner is not None and event_owner != key:
            raise _grant_conflict("source event is already bound to another grant")
        current = self.grants.get(key)
        planned, created, replayed = _plan_grant(admitted, current)
        self.grants[key] = deepcopy(planned)
        self.event_keys[event_key] = key
        return _grant_result(planned, created=created, replayed=replayed)

    def get_grant(
        self, *, tenant_id: str, project_code: str, subject_id: str
    ) -> dict[str, Any] | None:
        key = (
            _scoped_id("tenant_id", tenant_id),
            _project_code(project_code),
            _scoped_id("subject_id", subject_id),
        )
        found = self.grants.get(key)
        return deepcopy(found) if found is not None else None


class SqlAlchemyOaProjectGrantRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def apply_grant(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admitted = _admit_grant(payload)
        rejected: OaAuthorizationError | None = None
        try:
            with self._session_factory.begin() as session:
                try:
                    event_owner = _select_event_owner(session, admitted)
                    key = _grant_key(admitted)
                    if event_owner is not None and _grant_key(event_owner) != key:
                        raise _grant_conflict(
                            "source event is already bound to another grant"
                        )
                    current = _select_grant(session, admitted, for_update=True)
                    planned, created, replayed = _plan_grant(admitted, current)
                    if created:
                        _insert_grant(session, planned)
                    elif not replayed:
                        _update_grant(session, planned, expected=current)
                except OaAuthorizationError as exc:
                    rejected = exc
        except IntegrityError as exc:
            raise _grant_conflict("Project grant identity changed concurrently") from exc
        except SQLAlchemyError as exc:
            raise _grant_unavailable() from exc
        if rejected is not None:
            raise rejected
        return _grant_result(planned, created=created, replayed=replayed)

    def get_grant(
        self, *, tenant_id: str, project_code: str, subject_id: str
    ) -> dict[str, Any] | None:
        identity = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "project_code": _project_code(project_code),
            "subject_id": _scoped_id("subject_id", subject_id),
        }
        try:
            with self._session_factory() as session:
                return _select_grant(session, identity)
        except SQLAlchemyError as exc:
            raise _grant_unavailable() from exc


@dataclass
class OaProjectAuthorizationDecisionService:
    repository: OaProjectGrantRepository
    authorization_source: EffectiveAuthorizationSource
    clock: Any = field(default_factory=lambda: lambda: datetime.now(UTC))

    def decide(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = _admit_decision_request(payload)
        authorization = self.authorization_source.effective_authorization(
            tenant_id=request["tenant_id"],
            subject_id=request["subject_id"],
        )
        effective = _effective_authorization(authorization, request)
        grant = self.repository.get_grant(
            tenant_id=request["tenant_id"],
            project_code=request["project_code"],
            subject_id=request["subject_id"],
        )
        allowed, reason = _evaluate_project_decision(request, grant, effective)
        decided_at = _aware_datetime("clock", self.clock())
        project_role = grant["project_role"] if grant else None
        source_version = int(grant["source_version"]) if grant else None
        decision_semantics = {
            "schema_version": OA_PROJECT_DECISION_SCHEMA_VERSION,
            **request,
            "allowed": allowed,
            "reason_code": reason,
            "project_role": project_role,
            "source_version": source_version,
            "authorization_revision_hash": effective["revision_hash"],
            "projection_event_hash": grant["source_event_hash"] if grant else None,
        }
        return {
            "decision_schema_version": OA_PROJECT_DECISION_SCHEMA_VERSION,
            "decision_ref": semantic_sha256_hash_ref(decision_semantics),
            "tenant_id": request["tenant_id"],
            "subject_id": request["subject_id"],
            "project_code": request["project_code"],
            "action": request["action"],
            "allowed": allowed,
            "reason_code": reason,
            "project_role": project_role,
            "project_status": grant["project_status"] if grant else None,
            "grant_status": grant["grant_status"] if grant else None,
            "source_version": source_version,
            "minimum_source_version": request["minimum_source_version"],
            "projection_event_hash": grant["source_event_hash"] if grant else None,
            "applicable_global_scopes": (
                [request["action"]] if request["action"] in effective["scopes"] else []
            ),
            "authorization_revision_hash": effective["revision_hash"],
            "correlation_id": request["correlation_id"],
            "decided_at": _timestamp(decided_at),
        }


def build_project_grant_repository_for_runtime(
    runtime: ServicePersistenceRuntime,
) -> OaProjectGrantRepository:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaProjectGrantRepository(runtime.api_session_factory)
    return InMemoryOaProjectGrantRepository()


def register_project_entitlement_routes(
    app: FastAPI, *, service: OaProjectAuthorizationDecisionService
) -> None:
    @app.post("/internal/v1/auth/project-decisions", response_model=None)
    def decide_project_authorization(
        payload: dict[str, Any],
        request: Request,
        response: Response,
        authorization: str | None = Header(default=None),
    ):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        auth_problem = _authorize_decision_route(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            decision = service.decide(payload)
        except OaAuthorizationError as exc:
            return _problem(request, exc)
        return {
            "response_schema_version": OA_PROJECT_DECISION_RESPONSE_SCHEMA_VERSION,
            "service_id": "nex-oa",
            "decision": decision,
            "request_id": request_id_from_headers(request),
            "trace_id": trace_id_from_headers(request),
        }


def _authorize_decision_route(
    request: Request, authorization: str | None
) -> JSONResponse | None:
    required = (DEFAULT_SERVICE_SCOPE, OA_PROJECT_DECISION_SCOPE)
    if getattr(request.app.state, "service_token_admission", None) is None:
        result = validate_authorization_header(
            authorization,
            expected_audience="nex-oa",
            required_scopes=required,
        )
        if result.ok:
            return None
        status_code = 403 if result.error_code == "TOKEN_SCOPE_MISSING" else 401
        return problem_response(
            request,
            status_code=status_code,
            error_code=result.error_code or "SERVICE_CLAIM_INVALID",
            title="Project authorization admission failed",
            detail=result.detail or "A valid OA service claim is required.",
            type_uri="https://nex-platform.local/problems/project-authorization-admission",
        )
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-oa",
        required_scopes=required,
        route_class="READ",
    )
    return admitted if isinstance(admitted, JSONResponse) else None


def _admit_grant(payload: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "tenant_id",
        "project_code",
        "subject_id",
        "project_role",
        "grant_status",
        "project_status",
        "source_project_id",
        "source_version",
        "source_event_id",
        "source_event_hash",
        "occurred_at",
    }
    if set(payload) != required:
        raise _grant_invalid("Project grant fields are incomplete or unsupported")
    source_version = _positive_int("source_version", payload["source_version"])
    occurred_at = _aware_datetime("occurred_at", payload["occurred_at"])
    grant_status = _choice("grant_status", payload["grant_status"], GRANT_STATUSES)
    return {
        "tenant_id": _scoped_id("tenant_id", payload["tenant_id"]),
        "project_code": _project_code(payload["project_code"]),
        "subject_id": _scoped_id("subject_id", payload["subject_id"]),
        "project_role": _choice("project_role", payload["project_role"], PROJECT_ROLES),
        "grant_status": grant_status,
        "project_status": _choice(
            "project_status", payload["project_status"], PROJECT_STATUSES
        ),
        "source_project_id": _uuid("source_project_id", payload["source_project_id"]),
        "source_version": source_version,
        "source_event_id": _uuid("source_event_id", payload["source_event_id"]),
        "source_event_hash": _hash_ref(
            "source_event_hash", payload["source_event_hash"]
        ),
        "granted_at": occurred_at,
        "revoked_at": occurred_at if grant_status == "REVOKED" else None,
        "updated_at": occurred_at,
    }


def _plan_grant(
    admitted: Mapping[str, Any], current: Mapping[str, Any] | None
) -> tuple[dict[str, Any], bool, bool]:
    if current is None:
        return dict(admitted), True, False
    if admitted["source_event_id"] == current["source_event_id"]:
        if _grant_semantics(admitted) != _grant_semantics(current):
            raise _grant_conflict("source event replay changed immutable semantics")
        return dict(current), False, True
    if int(admitted["source_version"]) <= int(current["source_version"]):
        raise _grant_conflict("Project grant source version is stale or conflicting")
    planned = dict(admitted)
    if admitted["grant_status"] == "ACTIVE" and current["grant_status"] == "ACTIVE":
        planned["granted_at"] = current["granted_at"]
    return planned, False, False


def _grant_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        value[field]
        for field in (
            "tenant_id",
            "project_code",
            "subject_id",
            "project_role",
            "grant_status",
            "project_status",
            "source_project_id",
            "source_version",
            "source_event_id",
            "source_event_hash",
        )
    )


def _select_event_owner(
    session: Session, admitted: Mapping[str, Any]
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            "SELECT * FROM oa_project_grant "
            "WHERE tenant_id = :tenant_id AND source_event_id = :source_event_id"
        ),
        dict(admitted),
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def _select_grant(
    session: Session, identity: Mapping[str, Any], *, for_update: bool = False
) -> dict[str, Any] | None:
    statement = (
        "SELECT * FROM oa_project_grant WHERE tenant_id = :tenant_id "
        "AND project_code = :project_code AND subject_id = :subject_id"
    )
    if for_update and session.bind.dialect.name == "postgresql":
        statement += " FOR UPDATE"
    row = session.execute(text(statement), dict(identity)).mappings().one_or_none()
    return dict(row) if row is not None else None


def _insert_grant(session: Session, record: Mapping[str, Any]) -> None:
    columns = tuple(record)
    session.execute(
        text(
            f"INSERT INTO oa_project_grant ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + item for item in columns)})"
        ),
        dict(record),
    )


def _update_grant(
    session: Session,
    record: Mapping[str, Any],
    *,
    expected: Mapping[str, Any] | None,
) -> None:
    if expected is None:
        raise _grant_conflict("Project grant disappeared during update")
    mutable = tuple(
        field
        for field in record
        if field not in {"tenant_id", "project_code", "subject_id"}
    )
    params = {**dict(record), "expected_source_version": expected["source_version"]}
    result = session.execute(
        text(
            "UPDATE oa_project_grant SET "
            + ", ".join(f"{field} = :{field}" for field in mutable)
            + " WHERE tenant_id = :tenant_id AND project_code = :project_code "
            "AND subject_id = :subject_id "
            "AND source_version = :expected_source_version"
        ),
        params,
    )
    if int(result.rowcount or 0) != 1:
        raise _grant_conflict("Project grant changed concurrently")


def _admit_decision_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "tenant_id",
        "subject_id",
        "project_code",
        "action",
        "correlation_id",
        "minimum_source_version",
    }
    if not set(payload).issubset(allowed) or set(payload) - {"minimum_source_version"} != allowed - {"minimum_source_version"}:
        raise _grant_invalid("Project decision fields are incomplete or unsupported")
    action = str(payload["action"]).strip()
    if _ACTION.fullmatch(action) is None:
        raise _grant_invalid("action is malformed")
    return {
        "tenant_id": _scoped_id("tenant_id", payload["tenant_id"]),
        "subject_id": _scoped_id("subject_id", payload["subject_id"]),
        "project_code": _project_code(payload["project_code"]),
        "action": action,
        "correlation_id": _scoped_id("correlation_id", payload["correlation_id"]),
        "minimum_source_version": _positive_int(
            "minimum_source_version", payload.get("minimum_source_version", 1)
        ),
    }


def _effective_authorization(
    value: Mapping[str, Any], request: Mapping[str, Any]
) -> dict[str, Any]:
    authorization = value.get("authorization", value)
    if not isinstance(authorization, Mapping):
        raise _grant_unavailable("OA effective authorization is malformed")
    scopes = authorization.get("scopes")
    revision_hash = authorization.get("revision_hash")
    if (
        authorization.get("tenant_id") != request["tenant_id"]
        or authorization.get("subject_id") != request["subject_id"]
        or not isinstance(scopes, list)
        or any(not isinstance(item, str) or not item for item in scopes)
        or not isinstance(revision_hash, str)
        or re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", revision_hash) is None
    ):
        raise _grant_unavailable("OA effective authorization is malformed")
    return {"scopes": frozenset(scopes), "revision_hash": revision_hash}


def _evaluate_project_decision(
    request: Mapping[str, Any],
    grant: Mapping[str, Any] | None,
    authorization: Mapping[str, Any],
) -> tuple[bool, str]:
    roles = _ACTION_ROLES.get(request["action"])
    if roles is None:
        return False, "ACTION_UNKNOWN"
    if grant is None:
        return False, "PROJECT_GRANT_NOT_FOUND"
    if int(grant["source_version"]) < int(request["minimum_source_version"]):
        return False, "PROJECT_PROJECTION_STALE"
    if grant["grant_status"] != "ACTIVE":
        return False, "PROJECT_GRANT_REVOKED"
    if grant["project_status"] in {"INACTIVE", "CLOSED"}:
        return False, f"PROJECT_{grant['project_status']}"
    if grant["project_status"] == "CLOSING" and request["action"] not in _CLOSING_ACTIONS:
        return False, "PROJECT_CLOSING_ACTION_DENIED"
    if grant["project_role"] not in roles:
        return False, "PROJECT_ROLE_INSUFFICIENT"
    if request["action"] not in authorization["scopes"]:
        return False, "GLOBAL_SCOPE_MISSING"
    return True, "ALLOW"


def _grant_key(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(value["tenant_id"]),
        str(value["project_code"]),
        str(value["subject_id"]),
    )


def _grant_result(
    record: Mapping[str, Any], *, created: bool, replayed: bool
) -> dict[str, Any]:
    return {
        "record": _wire_grant(record),
        "created": created,
        "replayed": replayed,
    }


def _wire_grant(value: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(value))
    for timestamp_field in ("granted_at", "revoked_at", "updated_at"):
        if isinstance(result.get(timestamp_field), datetime):
            result[timestamp_field] = _timestamp(result[timestamp_field])
    return result


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if isinstance(value, str) else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _grant_invalid(f"{field_name} is invalid")
    return normalized


def _project_code(value: object) -> str:
    normalized = str(value).strip().upper() if isinstance(value, str) else ""
    if _PROJECT_CODE.fullmatch(normalized) is None:
        raise _grant_invalid("project_code is invalid")
    return normalized


def _choice(field_name: str, value: object, choices: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if isinstance(value, str) else ""
    if normalized not in choices:
        raise _grant_invalid(f"{field_name} is invalid")
    return normalized


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _grant_invalid(f"{field_name} must be a UUID") from exc


def _hash_ref(field_name: str, value: object) -> str:
    normalized = str(value).strip() if isinstance(value, str) else ""
    if _HASH_REF.fullmatch(normalized) is None:
        raise _grant_invalid(f"{field_name} must be a SHA-256 hash reference")
    return normalized


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool):
        raise _grant_invalid(f"{field_name} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise _grant_invalid(f"{field_name} must be a positive integer") from exc
    if normalized < 1 or str(value) != str(normalized):
        raise _grant_invalid(f"{field_name} must be a positive integer")
    return normalized


def _aware_datetime(field_name: str, value: object) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _grant_invalid(f"{field_name} must be an ISO-8601 timestamp") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _grant_invalid(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _grant_invalid(detail: str) -> OaAuthorizationError:
    return OaAuthorizationError(400, "oa.project_grant_invalid", detail)


def _grant_conflict(detail: str) -> OaAuthorizationError:
    return OaAuthorizationError(409, "oa.project_grant_conflict", detail)


def _grant_unavailable(
    detail: str = "Project grant persistence is temporarily unavailable",
) -> OaAuthorizationError:
    return OaAuthorizationError(503, "oa.project_grant_unavailable", detail)


def _problem(request: Request, exc: OaAuthorizationError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Project authorization request failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/project-authorization",
    )
