from __future__ import annotations

import json
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
    validate_authorization_header,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_oa.authorization import OaAuthorizationError
from nex_oa.service_auth import (
    authenticated_oa_service_claims,
    authorize_oa_service_request,
)

from .project_entitlements import (
    PROJECT_ROLES,
    PROJECT_STATUSES,
    OaProjectGrantRepository,
)

OA_PROJECT_ENTITLEMENT_WRITE_SCOPE = "project-entitlement:write"
OA_PROJECT_ENTITLEMENT_EVENT_TYPE = "PROJECT_ENTITLEMENT_SNAPSHOT"
OA_PROJECT_ENTITLEMENT_RECEIPT_SCHEMA_VERSION = "oa_project_entitlement_receipt.v1"

_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")


class OaProjectEntitlementInbox(Protocol):
    def apply_event(self, envelope: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass
class InMemoryOaProjectEntitlementInbox:
    events: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    grants: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)

    def apply_event(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        event = _admit_event(envelope)
        event_key = (event["tenant_id"], event["event_id"])
        current_event = self.events.get(event_key)
        if current_event is not None:
            _require_same_event(current_event, event)
            return _receipt(event, replayed=True)
        project_events = [
            value
            for value in self.events.values()
            if value["tenant_id"] == event["tenant_id"]
            and value["project_code"] == event["project_code"]
        ]
        if project_events and event["source_version"] <= max(
            int(value["source_version"]) for value in project_events
        ):
            raise _conflict(
                "Project entitlement source version is stale or conflicting"
            )
        _replace_memory_snapshot(self.grants, event)
        self.events[event_key] = deepcopy(event)
        return _receipt(event, replayed=False)


class SqlAlchemyOaProjectEntitlementInbox:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def apply_event(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        event = _admit_event(envelope)
        session = self._session_factory()
        try:
            session.begin()
            current = _select_inbox_event(session, event)
            if current is not None:
                _require_same_event(current, event)
                session.rollback()
                return _receipt(event, replayed=True)
            latest = _select_latest_project_event(session, event)
            if latest is not None and event["source_version"] <= int(
                latest["source_version"]
            ):
                raise _conflict(
                    "Project entitlement source version is stale or conflicting"
                )
            _replace_sql_snapshot(session, event)
            _insert_inbox_event(session, event)
            session.commit()
            return _receipt(event, replayed=False)
        except OaAuthorizationError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise _conflict("Project entitlement event changed concurrently") from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise _unavailable() from exc
        finally:
            session.close()


def build_project_entitlement_inbox_for_runtime(
    runtime: Any,
) -> OaProjectEntitlementInbox:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyOaProjectEntitlementInbox(runtime.api_session_factory)
    return InMemoryOaProjectEntitlementInbox()


def register_project_entitlement_sync_routes(
    app: FastAPI,
    *,
    inbox: OaProjectEntitlementInbox,
    repository: OaProjectGrantRepository | None = None,
) -> None:
    @app.post("/internal/v1/auth/project-entitlement-events", response_model=None)
    def apply_project_entitlement_event(
        payload: dict[str, Any],
        request: Request,
        response: Response,
        authorization: str | None = Header(default=None),
    ):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        required_scopes = (
            DEFAULT_SERVICE_SCOPE,
            OA_PROJECT_ENTITLEMENT_WRITE_SCOPE,
        )
        if getattr(request.app.state, "service_token_admission", None) is None:
            checked = validate_authorization_header(
                authorization,
                expected_audience="nex-oa",
                required_scopes=required_scopes,
            )
            if not checked.ok:
                status_code = (
                    403 if checked.error_code == "TOKEN_SCOPE_MISSING" else 401
                )
                return _problem(
                    request,
                    OaAuthorizationError(
                        status_code,
                        checked.error_code or "SERVICE_CLAIM_INVALID",
                        checked.detail or "A valid OA service claim is required.",
                    ),
                )
        problem = authorize_oa_service_request(
            request,
            authorization,
            required_scopes=required_scopes,
            route_class="WRITE",
        )
        if problem is not None:
            return problem
        try:
            claims = authenticated_oa_service_claims(request)
            if claims.service_id != "nex-eos":
                raise OaAuthorizationError(
                    403,
                    "OA_PROJECT_ENTITLEMENT_CALLER_FORBIDDEN",
                    "Project entitlement events are accepted only from NeX-EOS.",
                )
            return inbox.apply_event(payload)
        except OaAuthorizationError as exc:
            return _problem(request, exc)

    if repository is None:
        return

    @app.post(
        "/internal/v1/auth/project-entitlement-projections:resolve",
        response_model=None,
    )
    def resolve_project_entitlement_projection(
        payload: dict[str, Any],
        request: Request,
        response: Response,
        authorization: str | None = Header(default=None),
    ):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        required_scopes = (DEFAULT_SERVICE_SCOPE, OA_PROJECT_ENTITLEMENT_WRITE_SCOPE)
        if getattr(request.app.state, "service_token_admission", None) is None:
            checked = validate_authorization_header(
                authorization,
                expected_audience="nex-oa",
                required_scopes=required_scopes,
            )
            if not checked.ok:
                return _problem(
                    request,
                    OaAuthorizationError(
                        403 if checked.error_code == "TOKEN_SCOPE_MISSING" else 401,
                        checked.error_code or "SERVICE_CLAIM_INVALID",
                        checked.detail or "A valid OA service claim is required.",
                    ),
                )
        problem = authorize_oa_service_request(
            request,
            authorization,
            required_scopes=required_scopes,
            route_class="READ",
        )
        if problem is not None:
            return problem
        try:
            claims = authenticated_oa_service_claims(request)
            if claims.service_id != "nex-eos":
                raise OaAuthorizationError(
                    403,
                    "OA_PROJECT_ENTITLEMENT_CALLER_FORBIDDEN",
                    "Project entitlement projections are available only to NeX-EOS.",
                )
            return _project_projection(repository, payload)
        except OaAuthorizationError as exc:
            return _problem(request, exc)


def _project_projection(
    repository: OaProjectGrantRepository, payload: Mapping[str, Any]
) -> dict[str, Any]:
    if set(payload) != {"tenant_id", "project_code", "correlation_id"}:
        raise _invalid("Project entitlement projection request is incomplete")
    tenant_id = _scoped("tenant_id", payload["tenant_id"], maximum=128)
    project_code = _project_code(payload["project_code"])
    correlation_id = _scoped(
        "correlation_id", payload["correlation_id"], maximum=256
    )
    rows = repository.list_project_grants(
        tenant_id=tenant_id, project_code=project_code
    )
    if not rows:
        semantics = {
            "tenant_id": tenant_id,
            "project_code": project_code,
            "found": False,
            "source_project_id": None,
            "source_version": 0,
            "project_status": None,
            "members": [],
            "correlation_id": correlation_id,
        }
    else:
        latest = max(int(row["source_version"]) for row in rows)
        current = [row for row in rows if int(row["source_version"]) == latest]
        identities = {
            (str(row["source_project_id"]), str(row["project_status"]))
            for row in current
        }
        if len(identities) != 1:
            raise _unavailable()
        source_project_id, project_status = identities.pop()
        semantics = {
            "tenant_id": tenant_id,
            "project_code": project_code,
            "found": True,
            "source_project_id": source_project_id,
            "source_version": latest,
            "project_status": project_status,
            "members": sorted(
                (
                    {
                        "subject_id": str(row["subject_id"]),
                        "project_role": str(row["project_role"]),
                    }
                    for row in current
                    if row["grant_status"] == "ACTIVE"
                ),
                key=lambda item: item["subject_id"],
            ),
            "correlation_id": correlation_id,
        }
    return {
        "schema_version": "oa_project_entitlement_projection.v1",
        **semantics,
        "projection_hash": semantic_sha256_hash_ref(semantics),
    }


def _admit_event(envelope: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "event_id",
        "tenant_id",
        "business_operation_id",
        "event_type",
        "event_payload",
        "event_payload_hash",
    }
    if set(envelope) != required:
        raise _invalid("Project entitlement event envelope is incomplete")
    payload = envelope.get("event_payload")
    if not isinstance(payload, Mapping):
        raise _invalid("Project entitlement event payload must be an object")
    payload = dict(payload)
    payload_required = {
        "schema_version",
        "tenant_id",
        "project_id",
        "project_code",
        "project_status",
        "source_version",
        "members",
        "correlation_id",
        "causation_id",
        "occurred_at",
    }
    if set(payload) != payload_required:
        raise _invalid("Project entitlement event payload is incomplete")
    tenant = _scoped("tenant_id", envelope["tenant_id"], maximum=128)
    if payload["schema_version"] != "eos.project_entitlement_snapshot.v1":
        raise _invalid("Project entitlement schema version is unsupported")
    if payload["tenant_id"] != tenant:
        raise _invalid("Project entitlement tenant binding is invalid")
    if envelope["event_type"] != OA_PROJECT_ENTITLEMENT_EVENT_TYPE:
        raise _invalid("Project entitlement event type is unsupported")
    try:
        payload_hash = validate_hash_ref(envelope["event_payload_hash"])
    except ValueError as exc:
        raise _invalid("Project entitlement event hash is invalid") from exc
    if semantic_sha256_hash_ref(payload) != payload_hash:
        raise _invalid("Project entitlement event hash does not match the payload")
    members = _admit_members(payload["members"])
    occurred_at = _aware_datetime(payload["occurred_at"])
    return {
        "tenant_id": tenant,
        "event_id": _uuid("event_id", envelope["event_id"]),
        "business_operation_id": _uuid(
            "business_operation_id", envelope["business_operation_id"]
        ),
        "event_type": OA_PROJECT_ENTITLEMENT_EVENT_TYPE,
        "event_payload": payload,
        "event_payload_hash": payload_hash,
        "project_code": _project_code(payload["project_code"]),
        "source_project_id": _uuid("project_id", payload["project_id"]),
        "project_status": _choice(
            "project_status", payload["project_status"], PROJECT_STATUSES
        ),
        "source_version": _positive_int("source_version", payload["source_version"]),
        "members": members,
        "occurred_at": occurred_at,
    }


def _admit_members(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise _invalid("Project entitlement members must be a non-empty array")
    members: dict[str, str] = {}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"subject_id", "project_role"}:
            raise _invalid("Project entitlement member is invalid")
        subject = _scoped("subject_id", item["subject_id"], maximum=128)
        role = _choice("project_role", item["project_role"], PROJECT_ROLES)
        if subject in members:
            raise _invalid("Project entitlement member is duplicated")
        members[subject] = role
    return tuple(
        {"subject_id": subject, "project_role": members[subject]}
        for subject in sorted(members)
    )


def _replace_memory_snapshot(
    grants: dict[tuple[str, str, str], dict[str, Any]], event: Mapping[str, Any]
) -> None:
    present = {member["subject_id"] for member in event["members"]}
    for key, current in tuple(grants.items()):
        if key[:2] != (event["tenant_id"], event["project_code"]):
            continue
        if key[2] not in present:
            grants[key] = _grant_record(
                event,
                current["subject_id"],
                current["project_role"],
                "REVOKED",
                current,
            )
    for member in event["members"]:
        key = (event["tenant_id"], event["project_code"], member["subject_id"])
        grants[key] = _grant_record(
            event,
            member["subject_id"],
            member["project_role"],
            "ACTIVE",
            grants.get(key),
        )


def _grant_record(
    event: Mapping[str, Any],
    subject_id: str,
    project_role: str,
    grant_status: str,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    occurred_at = event["occurred_at"]
    return {
        "tenant_id": event["tenant_id"],
        "project_code": event["project_code"],
        "subject_id": subject_id,
        "project_role": project_role,
        "grant_status": grant_status,
        "project_status": event["project_status"],
        "source_project_id": event["source_project_id"],
        "source_version": event["source_version"],
        "source_event_id": event["event_id"],
        "source_event_hash": event["event_payload_hash"],
        "granted_at": (
            current["granted_at"]
            if current is not None and current["grant_status"] == "ACTIVE"
            else occurred_at
        ),
        "revoked_at": occurred_at if grant_status == "REVOKED" else None,
        "updated_at": occurred_at,
    }


def _replace_sql_snapshot(session: Session, event: Mapping[str, Any]) -> None:
    rows = (
        session.execute(
            text(
                "SELECT * FROM oa_project_grant WHERE tenant_id = :tenant_id "
                "AND project_code = :project_code FOR UPDATE"
            ),
            dict(event),
        )
        .mappings()
        .all()
    )
    current = {str(row["subject_id"]): dict(row) for row in rows}
    present = {member["subject_id"] for member in event["members"]}
    for subject_id, record in current.items():
        if subject_id not in present:
            _upsert_grant(
                session,
                _grant_record(
                    event, subject_id, record["project_role"], "REVOKED", record
                ),
            )
    for member in event["members"]:
        _upsert_grant(
            session,
            _grant_record(
                event,
                member["subject_id"],
                member["project_role"],
                "ACTIVE",
                current.get(member["subject_id"]),
            ),
        )


def _upsert_grant(session: Session, record: Mapping[str, Any]) -> None:
    session.execute(
        text(
            "INSERT INTO oa_project_grant (tenant_id, project_code, subject_id, "
            "project_role, grant_status, project_status, source_project_id, "
            "source_version, source_event_id, source_event_hash, granted_at, "
            "revoked_at, updated_at) VALUES (:tenant_id, :project_code, :subject_id, "
            ":project_role, :grant_status, :project_status, :source_project_id, "
            ":source_version, :source_event_id, :source_event_hash, :granted_at, "
            ":revoked_at, :updated_at) ON CONFLICT (tenant_id, project_code, subject_id) "
            "DO UPDATE SET project_role = EXCLUDED.project_role, "
            "grant_status = EXCLUDED.grant_status, project_status = EXCLUDED.project_status, "
            "source_project_id = EXCLUDED.source_project_id, source_version = EXCLUDED.source_version, "
            "source_event_id = EXCLUDED.source_event_id, source_event_hash = EXCLUDED.source_event_hash, "
            "granted_at = EXCLUDED.granted_at, revoked_at = EXCLUDED.revoked_at, "
            "updated_at = EXCLUDED.updated_at"
        ),
        dict(record),
    )


def _select_inbox_event(
    session: Session, event: Mapping[str, Any]
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT * FROM oa_project_entitlement_inbox "
                "WHERE tenant_id = :tenant_id AND event_id = :event_id FOR UPDATE"
            ),
            dict(event),
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _select_latest_project_event(
    session: Session, event: Mapping[str, Any]
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT * FROM oa_project_entitlement_inbox WHERE tenant_id = :tenant_id "
                "AND project_code = :project_code ORDER BY source_version DESC LIMIT 1 FOR UPDATE"
            ),
            dict(event),
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _insert_inbox_event(session: Session, event: Mapping[str, Any]) -> None:
    session.execute(
        text(
            "INSERT INTO oa_project_entitlement_inbox (tenant_id, event_id, project_code, "
            "source_project_id, source_version, event_payload_hash, event_payload, "
            "inbox_state, received_at, applied_at) VALUES (:tenant_id, :event_id, "
            ":project_code, :source_project_id, :source_version, :event_payload_hash, "
            "CAST(:event_payload_json AS JSONB), 'APPLIED', :occurred_at, :occurred_at)"
        ),
        {
            **dict(event),
            "event_payload_json": json.dumps(event["event_payload"], sort_keys=True),
        },
    )


def _require_same_event(current: Mapping[str, Any], event: Mapping[str, Any]) -> None:
    current_payload = current["event_payload"]
    if isinstance(current_payload, str):
        current_payload = json.loads(current_payload)
    if (
        current["event_payload_hash"] != event["event_payload_hash"]
        or current_payload != event["event_payload"]
        or str(current["project_code"]) != event["project_code"]
        or int(current["source_version"]) != event["source_version"]
    ):
        raise _conflict("Project entitlement replay changed immutable semantics")


def _receipt(event: Mapping[str, Any], *, replayed: bool) -> dict[str, Any]:
    return {
        "receipt_schema_version": OA_PROJECT_ENTITLEMENT_RECEIPT_SCHEMA_VERSION,
        "event_id": event["event_id"],
        "event_payload_hash": event["event_payload_hash"],
        "receipt_ref": f"oa.project-entitlement:{event['event_id']}:v{event['source_version']}",
        "tenant_id": event["tenant_id"],
        "project_code": event["project_code"],
        "source_version": event["source_version"],
        "inbox_state": "APPLIED",
        "replayed": replayed,
    }


def _problem(request: Request, exc: OaAuthorizationError) -> JSONResponse:
    from nex_runtime import problem_response

    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Project entitlement synchronization failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/project-entitlement-sync",
    )


def _invalid(detail: str) -> OaAuthorizationError:
    return OaAuthorizationError(400, "OA_PROJECT_ENTITLEMENT_INVALID", detail)


def _conflict(detail: str) -> OaAuthorizationError:
    return OaAuthorizationError(409, "OA_PROJECT_ENTITLEMENT_CONFLICT", detail)


def _unavailable() -> OaAuthorizationError:
    return OaAuthorizationError(
        503,
        "OA_PROJECT_ENTITLEMENT_UNAVAILABLE",
        "Project entitlement persistence is unavailable.",
    )


def _scoped(field: str, value: object, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or _SCOPED_ID.fullmatch(value) is None
    ):
        raise _invalid(f"{field} is invalid")
    return value


def _project_code(value: object) -> str:
    if not isinstance(value, str) or _PROJECT_CODE.fullmatch(value) is None:
        raise _invalid("project_code is invalid")
    return value


def _choice(field: str, value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(f"{field} is invalid")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be positive")
    return value


def _aware_datetime(value: object) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _invalid("occurred_at is invalid") from exc
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise _invalid("occurred_at must be timezone-aware")
    return value.astimezone(UTC)
