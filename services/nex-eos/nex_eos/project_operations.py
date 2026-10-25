from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from nex_runtime import DEFAULT_OPERATION_REGISTRY, OperationNameError
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import (
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .project_memberships import (
    EOS_PROJECT_MEMBER_TABLE,
    EosProjectMembershipError,
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
)
from .projects import (
    EOS_PROJECT_TABLE,
    EosProjectError,
    ProjectInput,
    SqlAlchemyEosProjectRepository,
)
from .voucher_commands import EosServiceCaller

PROJECT_CREATE_SCOPE = "project:project:create"
PROJECT_READ_SCOPE = "project:project:read"
PROJECT_ADMIN_SCOPE = "project:project:admin"
PROJECT_MEMBERSHIP_MANAGE_SCOPE = "project:membership:manage"

PROJECT_CREATE_OPERATION = "PROJECT.PROJECT.CREATE"
PROJECT_DEACTIVATE_OPERATION = "PROJECT.PROJECT.DEACTIVATE"
PROJECT_MEMBERSHIP_ADD_OPERATION = "PROJECT.MEMBERSHIP.ADD"
PROJECT_MEMBERSHIP_REMOVE_OPERATION = "PROJECT.MEMBERSHIP.REMOVE"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")


class EosGovernedProjectError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


class EosGovernedProjectService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        coordinator: EosBusinessTransactionCoordinator,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._session_factory = session_factory
        self._coordinator = coordinator
        self._authorization_source = authorization_source
        self._projects = SqlAlchemyEosProjectRepository(session_factory)
        self._memberships = SqlAlchemyEosProjectMembershipRepository(session_factory)

    def create_project(
        self,
        payload: Mapping[str, Any],
        *,
        caller: EosServiceCaller,
    ) -> dict[str, Any]:
        _require_service_caller(caller)
        envelope = _write_envelope(payload, PROJECT_CREATE_OPERATION)
        requester = _scoped_id("requester_subject_id", payload.get("requester_subject_id"))
        project_payload = _object("project", payload.get("project"))
        owner_subject = _scoped_id(
            "initial_owner_subject_id", payload.get("initial_owner_subject_id")
        )
        membership_id = _uuid(
            "initial_owner_membership_id",
            payload.get("initial_owner_membership_id"),
        )
        project = ProjectInput(
            tenant_id=envelope["tenant_id"],
            project_id=_uuid("project.project_id", project_payload.get("project_id")),
            project_code=_text("project.project_code", project_payload.get("project_code")),
            name=_text("project.name", project_payload.get("name")),
            parent_project_id=project_payload.get("parent_project_id"),
            nvt_project_id=project_payload.get("nvt_project_id"),
            start_date=_optional_date(project_payload.get("start_date")),
            end_date=_optional_date(project_payload.get("end_date")),
            currency=_text("project.currency", project_payload.get("currency", "KRW")),
        )
        authorization = self._authorize(
            tenant_id=envelope["tenant_id"],
            subject_id=requester,
            required_scope=PROJECT_CREATE_SCOPE,
        )
        self._require_active_subject(
            tenant_id=envelope["tenant_id"], subject_id=owner_subject
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise RuntimeError("Project creation requires a database transaction")
            created_project = self._projects.create_project_in_session(session, project)
            owner = self._memberships.add_membership_in_session(
                session,
                ProjectMembershipInput(
                    envelope["tenant_id"],
                    membership_id,
                    project.project_id,
                    owner_subject,
                    "OWNER",
                    requester,
                ),
            )
            return {
                "business_result_ref": f"eos.project:{project.project_id}",
                "project": _wire(created_project),
                "initial_owner_membership": _wire(owner),
                "authorization_revision_hash": authorization["revision_hash"],
            }

        return self._execute_write(envelope, mutation)

    def add_membership(
        self,
        payload: Mapping[str, Any],
        *,
        caller: EosServiceCaller,
    ) -> dict[str, Any]:
        _require_service_caller(caller)
        envelope = _write_envelope(payload, PROJECT_MEMBERSHIP_ADD_OPERATION)
        requester = _scoped_id("requester_subject_id", payload.get("requester_subject_id"))
        project_id = _uuid("project_id", payload.get("project_id"))
        target_subject = _scoped_id("target_subject_id", payload.get("target_subject_id"))
        membership_id = _uuid("project_membership_id", payload.get("project_membership_id"))
        role = _text("member_role", payload.get("member_role")).upper()
        authorization = self._authorize(
            tenant_id=envelope["tenant_id"],
            subject_id=requester,
            required_scope=PROJECT_MEMBERSHIP_MANAGE_SCOPE,
            project_id=project_id,
        )
        self._require_active_subject(
            tenant_id=envelope["tenant_id"], subject_id=target_subject
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise RuntimeError("Membership ADD requires a database transaction")
            membership = self._memberships.add_membership_in_session(
                session,
                ProjectMembershipInput(
                    envelope["tenant_id"],
                    membership_id,
                    project_id,
                    target_subject,
                    role,
                    requester,
                ),
                manager_subject_id=requester,
            )
            return {
                "business_result_ref": (
                    f"eos.project-membership:{membership['project_membership_id']}"
                ),
                "membership": _wire(membership),
                "authorization_revision_hash": authorization["revision_hash"],
            }

        return self._execute_write(envelope, mutation)

    def remove_membership(
        self,
        payload: Mapping[str, Any],
        *,
        caller: EosServiceCaller,
    ) -> dict[str, Any]:
        _require_service_caller(caller)
        envelope = _write_envelope(payload, PROJECT_MEMBERSHIP_REMOVE_OPERATION)
        requester = _scoped_id("requester_subject_id", payload.get("requester_subject_id"))
        project_id = _uuid("project_id", payload.get("project_id"))
        target_subject = _scoped_id("target_subject_id", payload.get("target_subject_id"))
        authorization = self._authorize(
            tenant_id=envelope["tenant_id"],
            subject_id=requester,
            required_scope=PROJECT_MEMBERSHIP_MANAGE_SCOPE,
            project_id=project_id,
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise RuntimeError("Membership REMOVE requires a database transaction")
            membership = self._memberships.remove_membership_in_session(
                session,
                tenant_id=envelope["tenant_id"],
                project_id=project_id,
                subject_id=target_subject,
                removed_by_subject_id=requester,
                manager_subject_id=requester,
            )
            return {
                "business_result_ref": (
                    f"eos.project-membership:{membership['project_membership_id']}"
                ),
                "membership": _wire(membership),
                "authorization_revision_hash": authorization["revision_hash"],
            }

        return self._execute_write(envelope, mutation)

    def deactivate_project(
        self,
        payload: Mapping[str, Any],
        *,
        caller: EosServiceCaller,
    ) -> dict[str, Any]:
        _require_service_caller(caller)
        envelope = _write_envelope(payload, PROJECT_DEACTIVATE_OPERATION)
        requester = _scoped_id("requester_subject_id", payload.get("requester_subject_id"))
        project_id = _uuid("project_id", payload.get("project_id"))
        expected_version = _positive_int("expected_version", payload.get("expected_version"))
        authorization = self._authorize(
            tenant_id=envelope["tenant_id"],
            subject_id=requester,
            required_scope=PROJECT_ADMIN_SCOPE,
            project_id=project_id,
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise RuntimeError("Project deactivation requires a database transaction")
            self._require_project_role(
                session,
                tenant_id=envelope["tenant_id"],
                project_id=project_id,
                subject_id=requester,
                roles={"OWNER"},
            )
            project = (
                session.execute(
                    select(EOS_PROJECT_TABLE)
                    .where(
                        EOS_PROJECT_TABLE.c.tenant_id == envelope["tenant_id"],
                        EOS_PROJECT_TABLE.c.project_id == project_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if project is None:
                raise EosGovernedProjectError(
                    "EOS_PROJECT_NOT_FOUND",
                    "Project was not found in tenant scope",
                    status_code=404,
                )
            if int(project["version"]) != expected_version:
                raise EosGovernedProjectError(
                    "EOS_PROJECT_VERSION_CONFLICT",
                    "Project version changed before deactivation",
                    status_code=409,
                )
            if project["status"] == "ACTIVE":
                changed = {
                    "status": "INACTIVE",
                    "version": expected_version + 1,
                    "updated_at": datetime.now(UTC),
                }
                session.execute(
                    update(EOS_PROJECT_TABLE)
                    .where(
                        EOS_PROJECT_TABLE.c.tenant_id == envelope["tenant_id"],
                        EOS_PROJECT_TABLE.c.project_id == project_id,
                        EOS_PROJECT_TABLE.c.version == expected_version,
                    )
                    .values(**changed)
                )
                project = {**dict(project), **changed}
            return {
                "business_result_ref": f"eos.project:{project_id}",
                "project": _wire(project),
                "authorization_revision_hash": authorization["revision_hash"],
            }

        return self._execute_write(envelope, mutation)

    def get_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        requester_subject_id: str,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id
        )
        authorization = self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=PROJECT_READ_SCOPE,
            project_id=project_id,
        )
        try:
            with self._session_factory() as session:
                if PROJECT_ADMIN_SCOPE not in authorization["scopes"]:
                    self._require_project_role(
                        session,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        subject_id=requester_subject_id,
                    )
                project = session.execute(
                    select(EOS_PROJECT_TABLE).where(
                        EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                        EOS_PROJECT_TABLE.c.project_id == project_id,
                    )
                ).mappings().one_or_none()
        except EosGovernedProjectError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        if project is None:
            raise EosGovernedProjectError(
                "EOS_PROJECT_NOT_FOUND",
                "Project was not found in tenant scope",
                status_code=404,
            )
        return _wire(project)

    def list_projects(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id
        )
        limit = _limit(limit)
        offset = _offset(offset)
        authorization = self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=PROJECT_READ_SCOPE,
        )
        statement = select(EOS_PROJECT_TABLE).where(
            EOS_PROJECT_TABLE.c.tenant_id == tenant_id
        )
        if PROJECT_ADMIN_SCOPE not in authorization["scopes"]:
            statement = statement.join(
                EOS_PROJECT_MEMBER_TABLE,
                (EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id)
                & (
                    EOS_PROJECT_MEMBER_TABLE.c.project_id
                    == EOS_PROJECT_TABLE.c.project_id
                )
                & (EOS_PROJECT_MEMBER_TABLE.c.subject_id == requester_subject_id)
                & (EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE"),
            )
        statement = statement.order_by(EOS_PROJECT_TABLE.c.project_code).limit(
            limit
        ).offset(offset)
        try:
            with self._session_factory() as session:
                rows = session.execute(statement).mappings().all()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return [_wire(row) for row in rows]

    def list_memberships(
        self,
        *,
        tenant_id: str,
        project_id: str,
        requester_subject_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id
        )
        authorization = self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=PROJECT_READ_SCOPE,
            project_id=project_id,
        )
        statement = (
            select(EOS_PROJECT_MEMBER_TABLE)
            .where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
            )
            .order_by(
                EOS_PROJECT_MEMBER_TABLE.c.status,
                EOS_PROJECT_MEMBER_TABLE.c.member_role,
                EOS_PROJECT_MEMBER_TABLE.c.subject_id,
            )
            .limit(_limit(limit))
            .offset(_offset(offset))
        )
        try:
            with self._session_factory() as session:
                if PROJECT_ADMIN_SCOPE not in authorization["scopes"]:
                    self._require_project_role(
                        session,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        subject_id=requester_subject_id,
                    )
                rows = session.execute(statement).mappings().all()
        except EosGovernedProjectError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return [_wire(row) for row in rows]

    def _execute_write(self, envelope, mutation) -> dict[str, Any]:
        requested_operation = envelope.pop("requested_operation")
        canonical_operation = envelope["operation"]

        def admitted_mutation(session: Session | None) -> Mapping[str, Any]:
            try:
                return {
                    **mutation(session),
                    "requested_operation": requested_operation,
                    "canonical_operation": canonical_operation,
                }
            except (
                EosGovernedProjectError,
                EosProjectError,
                EosProjectMembershipError,
            ) as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=getattr(exc, "retryable", False),
                ) from exc
            except IntegrityError as exc:
                raise EosBusinessOperationError(
                    "EOS_PROJECT_OPERATION_CONFLICT",
                    "Project operation conflicts with existing state",
                    status_code=409,
                ) from exc

        try:
            result = self._coordinator.execute(
                EosBusinessOperationRequest(**envelope), admitted_mutation
            )
        except EosBusinessOperationError as exc:
            raise EosGovernedProjectError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return result.to_public_projection()

    def _authorize(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        required_scope: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _authorization_denied(required_scope) from exc
        except Exception as exc:
            raise EosGovernedProjectError(
                "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE",
                "OA effective authorization is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        return _admit_authorization(
            value,
            tenant_id=tenant_id,
            subject_id=subject_id,
            required_scope=required_scope,
            project_id=project_id,
        )

    def _require_active_subject(self, *, tenant_id: str, subject_id: str) -> None:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _authorization_denied("active subject") from exc
        except Exception as exc:
            raise EosGovernedProjectError(
                "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE",
                "OA target subject status is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        _admit_authorization(
            value,
            tenant_id=tenant_id,
            subject_id=subject_id,
            required_scope=None,
        )

    @staticmethod
    def _require_project_role(
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        roles: set[str] | None = None,
    ) -> None:
        role = session.execute(
            select(EOS_PROJECT_MEMBER_TABLE.c.member_role).where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                EOS_PROJECT_MEMBER_TABLE.c.subject_id == subject_id,
                EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
            )
        ).scalar_one_or_none()
        if role is None or (roles is not None and role not in roles):
            raise EosGovernedProjectError(
                "EOS_PROJECT_MEMBERSHIP_REQUIRED",
                "An admitted active Project membership is required",
                status_code=403,
            )


def project_operation_payload_hash(
    payload: Mapping[str, Any], operation: str
) -> str:
    try:
        canonical_operation = DEFAULT_OPERATION_REGISTRY.resolve(
            operation
        ).canonical_operation
    except OperationNameError as exc:
        raise _invalid("operation is not admitted") from exc
    projected = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "business_operation_id",
            "idempotency_key",
            "payload_hash",
            "requested_operation",
            "trace",
        }
    }
    return nsl_write_payload_hash_ref(
        {"operation": canonical_operation, **projected}
    )


def _write_envelope(
    payload: Mapping[str, Any], operation: str
) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        raise _invalid("payload must be an object")
    requested_operation = payload.get("requested_operation", operation)
    try:
        resolution = DEFAULT_OPERATION_REGISTRY.resolve(requested_operation)
    except OperationNameError as exc:
        raise _invalid("requested_operation is not admitted") from exc
    if resolution.canonical_operation != operation:
        raise _invalid("requested_operation does not match the route operation")
    tenant_id = _scoped_id("tenant_id", payload.get("tenant_id"))
    supplied_hash = _text("payload_hash", payload.get("payload_hash"))
    computed_hash = project_operation_payload_hash(payload, operation)
    if supplied_hash != computed_hash:
        raise EosGovernedProjectError(
            "EOS_PROJECT_PAYLOAD_HASH_MISMATCH",
            "Canonical Project operation payload hash does not match",
            status_code=422,
        )
    return {
        "tenant_id": tenant_id,
        "business_operation_id": _uuid(
            "business_operation_id", payload.get("business_operation_id")
        ),
        "idempotency_key": _text("idempotency_key", payload.get("idempotency_key")),
        "operation": operation,
        "payload_hash": supplied_hash,
        "requested_operation": resolution.requested_operation,
    }


def _admit_authorization(
    value: object,
    *,
    tenant_id: str,
    subject_id: str,
    required_scope: str | None,
    project_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("active") is not True:
        raise _authorization_denied(required_scope or "active subject")
    if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
        raise _authorization_denied(required_scope or "active subject")
    scopes = _string_set(value.get("scopes"))
    if required_scope is not None and required_scope not in scopes:
        raise _authorization_denied(required_scope)
    revision_hash = value.get("revision_hash")
    if not isinstance(revision_hash, str) or _REVISION_HASH.fullmatch(revision_hash) is None:
        raise _authorization_denied(required_scope or "active subject")
    project_ids = value.get("project_ids")
    if project_id is not None and project_ids is not None and project_id not in _string_set(project_ids):
        raise _authorization_denied(required_scope or "Project scope")
    return {"scopes": scopes, "revision_hash": revision_hash}


def _require_service_caller(value: object) -> None:
    if (
        not isinstance(value, EosServiceCaller)
        or value.audience != "nex-eos"
        or "service:call" not in value.scopes
    ):
        raise EosGovernedProjectError(
            "EOS_SERVICE_TRUST_DENIED",
            "Authenticated service trust for nex-eos is required",
            status_code=403,
        )


def _string_set(value: object) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _authorization_denied("valid scope set")
    normalized = {item for item in value if isinstance(item, str) and item}
    if len(normalized) != len(value):
        raise _authorization_denied("valid scope set")
    return normalized


def _wire(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item.isoformat() if isinstance(item, (date, datetime)) else item
        for key, item in value.items()
    }


def _object(field: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object")
    return value


def _scoped_id(field: str, value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(text) is None:
        raise _invalid(f"{field} is invalid")
    return text


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _text(field: str, value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not text or len(text) > 256:
        raise _invalid(f"{field} is invalid")
    return text


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(f"{field} must be a positive integer")
    return value


def _limit(value: object) -> int:
    value = _positive_int("limit", value)
    if value > 500:
        raise _invalid("limit must not exceed 500")
    return value


def _offset(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid("offset must be a non-negative integer")
    return value


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise _invalid("Project date must use ISO-8601") from exc


def _authorization_denied(scope: str) -> EosGovernedProjectError:
    return EosGovernedProjectError(
        "EOS_PROJECT_AUTHORIZATION_DENIED",
        f"Current {scope} authorization was denied",
        status_code=403,
    )


def _invalid(detail: str) -> EosGovernedProjectError:
    return EosGovernedProjectError(
        "EOS_PROJECT_OPERATION_INVALID", detail, status_code=422
    )


def _persistence_error() -> EosGovernedProjectError:
    return EosGovernedProjectError(
        "EOS_PROJECT_OPERATION_PERSISTENCE_FAILED",
        "Project operation persistence is unavailable",
        status_code=503,
        retryable=True,
    )
