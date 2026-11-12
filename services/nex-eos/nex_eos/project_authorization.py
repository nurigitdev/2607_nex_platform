from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .projects import EOS_PROJECT_TABLE

_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_ACTION = re.compile(r"^[a-z][a-z0-9_-]*(?::[a-z0-9_-]+){1,4}$")
_HASH_REF = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_NO_CACHE = "no-store, max-age=0"


class EosProjectAuthorizationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
        reason_code: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        self.reason_code = reason_code
        super().__init__(detail)


@dataclass(frozen=True)
class EosProjectAuthorizationContext:
    tenant_id: str
    project_id: str
    project_code: str
    project_status: str
    authorization_sync_state: str
    authorization_version: int


@dataclass(frozen=True)
class EosProjectAuthorizationEvidence:
    decision_ref: str
    project_code: str
    project_role: str
    project_status: str
    source_version: int
    projection_event_hash: str
    authorization_revision_hash: str
    decided_at: str


class ProjectAuthorizationContextSource(Protocol):
    def resolve(
        self, *, tenant_id: str, project_id: str
    ) -> EosProjectAuthorizationContext | None: ...


class ProjectAuthorizationDecisionSource(Protocol):
    def decide(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class SqlAlchemyEosProjectAuthorizationContextSource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def resolve(
        self, *, tenant_id: str, project_id: str
    ) -> EosProjectAuthorizationContext | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(
                            EOS_PROJECT_TABLE.c.tenant_id,
                            EOS_PROJECT_TABLE.c.project_id,
                            EOS_PROJECT_TABLE.c.project_code,
                            EOS_PROJECT_TABLE.c.status,
                            EOS_PROJECT_TABLE.c.authorization_sync_state,
                            EOS_PROJECT_TABLE.c.authorization_version,
                        ).where(
                            EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                            EOS_PROJECT_TABLE.c.project_id == project_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as exc:
            raise _unavailable("EOS Project authorization context is unavailable") from exc
        if row is None:
            return None
        return EosProjectAuthorizationContext(
            tenant_id=str(row["tenant_id"]),
            project_id=str(row["project_id"]),
            project_code=str(row["project_code"]),
            project_status=str(row["status"]),
            authorization_sync_state=str(row["authorization_sync_state"]),
            authorization_version=int(row["authorization_version"]),
        )


class HttpOaProjectAuthorizationDecisionSource:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def decide(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self._service_token.strip():
            raise RuntimeError("OA Project authorization service token is not configured")
        request = Request(
            f"{self._base_url}/internal/v1/auth/project-decisions",
            data=json.dumps(dict(payload), separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cache-Control": _NO_CACHE,
                "Pragma": "no-cache",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                document = json.loads(response.read().decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError("OA Project authorization request failed") from exc
        if not isinstance(document, Mapping) or not isinstance(
            document.get("decision"), Mapping
        ):
            raise RuntimeError("OA Project authorization response is malformed")
        return document["decision"]


class EosProjectAuthorizationGate:
    def __init__(
        self,
        *,
        context_source: ProjectAuthorizationContextSource,
        decision_source: ProjectAuthorizationDecisionSource,
    ) -> None:
        self._context_source = context_source
        self._decision_source = decision_source

    def authorize(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        project_id: str,
        action: str,
        correlation_id: str,
        expected_project_code: str | None = None,
    ) -> EosProjectAuthorizationEvidence:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        subject_id = _scoped_id("subject_id", subject_id)
        project_id = _scoped_id("project_id", project_id)
        action = _action(action)
        correlation_id = _scoped_id("correlation_id", correlation_id)
        if expected_project_code is not None:
            expected_project_code = _project_code(expected_project_code)
        try:
            context = self._context_source.resolve(
                tenant_id=tenant_id,
                project_id=project_id,
            )
        except EosProjectAuthorizationError:
            raise
        except Exception as exc:
            raise _unavailable(
                "EOS Project authorization context is unavailable"
            ) from exc
        if context is None:
            raise _denied("PROJECT_NOT_FOUND")
        if (
            expected_project_code is not None
            and context.project_code != expected_project_code
        ):
            raise _denied("PROJECT_CODE_MISMATCH")
        if (
            context.authorization_sync_state != "IN_SYNC"
            or context.authorization_version < 1
        ):
            raise _denied("PROJECT_AUTHORIZATION_NOT_SYNCHRONIZED")
        request = {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "project_code": _project_code(context.project_code),
            "action": action,
            "correlation_id": correlation_id,
            "minimum_source_version": context.authorization_version,
        }
        try:
            value = self._decision_source.decide(request)
        except EosProjectAuthorizationError:
            raise
        except Exception as exc:
            raise _unavailable("OA Project authorization decision is unavailable") from exc
        decision = _admit_decision(value, request=request, context=context)
        if decision["allowed"] is not True:
            raise _denied(str(decision["reason_code"]))
        return EosProjectAuthorizationEvidence(
            decision_ref=str(decision["decision_ref"]),
            project_code=context.project_code,
            project_role=str(decision["project_role"]),
            project_status=str(decision["project_status"]),
            source_version=int(decision["source_version"]),
            projection_event_hash=str(decision["projection_event_hash"]),
            authorization_revision_hash=str(
                decision["authorization_revision_hash"]
            ),
            decided_at=str(decision["decided_at"]),
        )


def _admit_decision(
    value: object,
    *,
    request: Mapping[str, Any],
    context: EosProjectAuthorizationContext,
) -> dict[str, Any]:
    required = {
        "decision_schema_version",
        "decision_ref",
        "tenant_id",
        "subject_id",
        "project_code",
        "action",
        "allowed",
        "reason_code",
        "project_role",
        "project_status",
        "grant_status",
        "source_version",
        "minimum_source_version",
        "projection_event_hash",
        "applicable_global_scopes",
        "authorization_revision_hash",
        "correlation_id",
        "decided_at",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise _unavailable("OA Project authorization decision fields drifted")
    decision = dict(value)
    if (
        decision["decision_schema_version"] != "oa_project_authorization_decision.v1"
        or decision["tenant_id"] != request["tenant_id"]
        or decision["subject_id"] != request["subject_id"]
        or decision["project_code"] != request["project_code"]
        or decision["action"] != request["action"]
        or decision["correlation_id"] != request["correlation_id"]
        or decision["minimum_source_version"] != request["minimum_source_version"]
        or not isinstance(decision["allowed"], bool)
        or not isinstance(decision["reason_code"], str)
    ):
        raise _unavailable("OA Project authorization decision binding drifted")
    if not _HASH_REF.fullmatch(str(decision["decision_ref"])):
        raise _unavailable("OA Project authorization decision reference is invalid")
    if not _HASH_REF.fullmatch(str(decision["authorization_revision_hash"])):
        raise _unavailable("OA authorization revision is invalid")
    global_scopes = decision["applicable_global_scopes"]
    if (
        not isinstance(global_scopes, list)
        or any(not isinstance(item, str) or not item for item in global_scopes)
    ):
        raise _unavailable("OA applicable global scopes are invalid")
    if decision["allowed"] is True:
        if (
            decision["reason_code"] != "ALLOW"
            or decision["grant_status"] != "ACTIVE"
            or decision["project_status"] != context.project_status
            or not isinstance(decision["project_role"], str)
            or decision["source_version"] != context.authorization_version
            or not _HASH_REF.fullmatch(str(decision["projection_event_hash"]))
            or request["action"] not in global_scopes
        ):
            raise _unavailable("OA Project authorization allow evidence drifted")
    return decision


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if isinstance(value, str) else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise EosProjectAuthorizationError(
            "EOS_PROJECT_AUTHORIZATION_REQUEST_INVALID",
            f"{field_name} is invalid",
            status_code=422,
        )
    return normalized


def _project_code(value: object) -> str:
    normalized = str(value).strip().upper() if isinstance(value, str) else ""
    if _PROJECT_CODE.fullmatch(normalized) is None:
        raise EosProjectAuthorizationError(
            "EOS_PROJECT_AUTHORIZATION_REQUEST_INVALID",
            "project_code is invalid",
            status_code=422,
        )
    return normalized


def _action(value: object) -> str:
    normalized = str(value).strip() if isinstance(value, str) else ""
    if _ACTION.fullmatch(normalized) is None:
        raise EosProjectAuthorizationError(
            "EOS_PROJECT_AUTHORIZATION_REQUEST_INVALID",
            "action is invalid",
            status_code=422,
        )
    return normalized


def _denied(reason_code: str) -> EosProjectAuthorizationError:
    return EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_DENIED",
        f"OA denied the exact Project action: {reason_code}",
        status_code=403,
        reason_code=reason_code,
    )


def _unavailable(detail: str) -> EosProjectAuthorizationError:
    return EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )
