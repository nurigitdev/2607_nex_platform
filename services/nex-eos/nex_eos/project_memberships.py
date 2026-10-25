from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import build_unit_of_work
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_METADATA
from .projects import EOS_PROJECT_TABLE

EOS_PROJECT_MEMBER_ROLES = frozenset({"OWNER", "MANAGER", "MEMBER", "VIEWER"})
EOS_PROJECT_MEMBER_STATUSES = frozenset({"ACTIVE", "REMOVED"})
EOS_PROJECT_MEMBERSHIP_BATCH_OUTCOMES = frozenset(
    {"ADDED", "REACTIVATED", "ALREADY_ACTIVE", "ROLE_CONFLICT"}
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")

EOS_PROJECT_MEMBER_TABLE = Table(
    "eos_project_member",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("project_membership_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("subject_id", String(128), nullable=False),
    Column("member_role", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_to", DateTime(timezone=True), nullable=True),
    Column("version", Integer, nullable=False),
    Column("created_by_subject_id", String(128), nullable=False),
    Column("removed_by_subject_id", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "subject_id",
        name="ux_eos_project_member_subject",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_project_member_project",
    ),
    CheckConstraint(
        "member_role IN ('OWNER', 'MANAGER', 'MEMBER', 'VIEWER')",
        name="ck_eos_project_member_role",
    ),
    CheckConstraint(
        "status IN ('ACTIVE', 'REMOVED')",
        name="ck_eos_project_member_status",
    ),
    CheckConstraint(
        "(status = 'ACTIVE' AND valid_to IS NULL "
        "AND removed_by_subject_id IS NULL) OR "
        "(status = 'REMOVED' AND valid_to IS NOT NULL "
        "AND removed_by_subject_id IS NOT NULL)",
        name="ck_eos_project_member_lifecycle",
    ),
    CheckConstraint(
        "valid_to IS NULL OR valid_to >= valid_from",
        name="ck_eos_project_member_period",
    ),
    CheckConstraint("version > 0", name="ck_eos_project_member_version"),
)
Index(
    "ix_eos_project_member_project",
    EOS_PROJECT_MEMBER_TABLE.c.tenant_id,
    EOS_PROJECT_MEMBER_TABLE.c.project_id,
    EOS_PROJECT_MEMBER_TABLE.c.status,
    EOS_PROJECT_MEMBER_TABLE.c.member_role,
)
Index(
    "ix_eos_project_member_subject",
    EOS_PROJECT_MEMBER_TABLE.c.tenant_id,
    EOS_PROJECT_MEMBER_TABLE.c.subject_id,
    EOS_PROJECT_MEMBER_TABLE.c.status,
    EOS_PROJECT_MEMBER_TABLE.c.project_id,
)


class EosProjectMembershipError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class ProjectMembershipInput:
    tenant_id: str
    project_membership_id: str
    project_id: str
    subject_id: str
    member_role: str
    created_by_subject_id: str
    status: str = "ACTIVE"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    version: int = 1
    removed_by_subject_id: str | None = None


class SqlAlchemyEosProjectMembershipRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_membership(self, value: ProjectMembershipInput) -> dict[str, Any]:
        record = _membership_record(value)
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                project_exists = transaction.db.execute(
                    select(EOS_PROJECT_TABLE.c.project_id).where(
                        EOS_PROJECT_TABLE.c.tenant_id == record["tenant_id"],
                        EOS_PROJECT_TABLE.c.project_id == record["project_id"],
                    )
                ).scalar_one_or_none()
                if project_exists is None:
                    raise EosProjectMembershipError(
                        "EOS_PROJECT_NOT_FOUND",
                        "Project does not exist in tenant scope",
                        status_code=404,
                    )
                transaction.db.execute(
                    EOS_PROJECT_MEMBER_TABLE.insert().values(**record)
                )
        except EosProjectMembershipError:
            raise
        except IntegrityError as exc:
            raise EosProjectMembershipError(
                "EOS_PROJECT_MEMBERSHIP_CONFLICT",
                "Project membership identity or subject relationship already exists",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(record)

    def get_membership(
        self,
        *,
        tenant_id: str,
        project_membership_id: str,
    ) -> dict[str, Any] | None:
        statement = select(EOS_PROJECT_MEMBER_TABLE).where(
            EOS_PROJECT_MEMBER_TABLE.c.tenant_id
            == _scoped_id("tenant_id", tenant_id),
            EOS_PROJECT_MEMBER_TABLE.c.project_membership_id
            == _uuid("project_membership_id", project_membership_id),
        )
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None

    def add_membership(self, value: ProjectMembershipInput) -> dict[str, Any]:
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                return self.add_membership_in_session(transaction.db, value)
        except EosProjectMembershipError:
            raise
        except IntegrityError as exc:
            raise EosProjectMembershipError(
                "EOS_PROJECT_MEMBERSHIP_CONFLICT",
                "Project membership identity or subject relationship already exists",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def add_membership_in_session(
        self,
        session: Session,
        value: ProjectMembershipInput,
        *,
        manager_subject_id: str | None = None,
    ) -> dict[str, Any]:
        record = _membership_record(value)
        if record["status"] != "ACTIVE":
            raise _invalid("ADD requires an ACTIVE membership")
        project_status = self._locked_project_status(
            session,
            tenant_id=record["tenant_id"],
            project_id=record["project_id"],
        )
        if project_status != "ACTIVE":
            raise EosProjectMembershipError(
                "EOS_PROJECT_INACTIVE",
                "Project must be active before membership can be added",
                status_code=409,
            )
        if manager_subject_id is not None:
            self._require_manager(
                session,
                tenant_id=record["tenant_id"],
                project_id=record["project_id"],
                subject_id=_scoped_id("manager_subject_id", manager_subject_id),
            )
        existing = self._locked_subject_membership(
            session,
            tenant_id=record["tenant_id"],
            project_id=record["project_id"],
            subject_id=record["subject_id"],
        )
        if existing is None:
            session.execute(EOS_PROJECT_MEMBER_TABLE.insert().values(**record))
            return dict(record)
        if existing["member_role"] != record["member_role"]:
            raise EosProjectMembershipError(
                "EOS_PROJECT_MEMBERSHIP_ROLE_CONFLICT",
                "Existing Project membership has a different role",
                status_code=409,
            )
        if existing["status"] == "ACTIVE":
            return dict(existing)

        now = datetime.now(UTC)
        changes = {
            "status": "ACTIVE",
            "valid_from": record["valid_from"],
            "valid_to": None,
            "removed_by_subject_id": None,
            "version": int(existing["version"]) + 1,
            "updated_at": now,
        }
        result = session.execute(
            update(EOS_PROJECT_MEMBER_TABLE)
            .where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == record["tenant_id"],
                EOS_PROJECT_MEMBER_TABLE.c.project_membership_id
                == existing["project_membership_id"],
                EOS_PROJECT_MEMBER_TABLE.c.status == "REMOVED",
                EOS_PROJECT_MEMBER_TABLE.c.version == existing["version"],
            )
            .values(**changes)
        )
        if int(result.rowcount or 0) != 1:
            raise _concurrent_change()
        return {**dict(existing), **changes}

    def add_memberships_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        target_subject_ids: tuple[str, ...],
        member_role: str,
        created_by_subject_id: str,
        manager_subject_id: str,
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        member_role = _choice(
            "member_role", member_role, EOS_PROJECT_MEMBER_ROLES
        )
        created_by_subject_id = _scoped_id(
            "created_by_subject_id", created_by_subject_id
        )
        manager_subject_id = _scoped_id(
            "manager_subject_id", manager_subject_id
        )
        subjects = tuple(_scoped_id("target_subject_id", item) for item in target_subject_ids)
        if len(subjects) > 50 or len(set(subjects)) != len(subjects):
            raise _invalid("target_subject_ids must contain at most 50 unique subjects")
        if subjects != tuple(sorted(subjects, key=lambda item: item.encode("utf-8"))):
            raise _invalid("target_subject_ids must use canonical byte order")

        project_status = self._locked_project_status(
            session, tenant_id=tenant_id, project_id=project_id
        )
        if project_status != "ACTIVE":
            raise EosProjectMembershipError(
                "EOS_PROJECT_INACTIVE",
                "Project must be active before memberships can be added",
                status_code=409,
            )
        self._require_manager(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            subject_id=manager_subject_id,
        )

        results: list[dict[str, Any]] = []
        for subject_id in subjects:
            existing = self._locked_subject_membership(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                subject_id=subject_id,
            )
            if existing is None:
                record = _membership_record(
                    ProjectMembershipInput(
                        tenant_id=tenant_id,
                        project_membership_id=deterministic_project_membership_id(
                            tenant_id, project_id, subject_id
                        ),
                        project_id=project_id,
                        subject_id=subject_id,
                        member_role=member_role,
                        created_by_subject_id=created_by_subject_id,
                    )
                )
                session.execute(EOS_PROJECT_MEMBER_TABLE.insert().values(**record))
                results.append(_batch_item("ADDED", record))
                continue
            if existing["member_role"] != member_role:
                results.append(_batch_item("ROLE_CONFLICT", existing))
                continue
            if existing["status"] == "ACTIVE":
                results.append(_batch_item("ALREADY_ACTIVE", existing))
                continue

            now = datetime.now(UTC)
            changes = {
                "status": "ACTIVE",
                "valid_from": now,
                "valid_to": None,
                "removed_by_subject_id": None,
                "version": int(existing["version"]) + 1,
                "updated_at": now,
            }
            updated = session.execute(
                update(EOS_PROJECT_MEMBER_TABLE)
                .where(
                    EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_MEMBER_TABLE.c.project_membership_id
                    == existing["project_membership_id"],
                    EOS_PROJECT_MEMBER_TABLE.c.status == "REMOVED",
                    EOS_PROJECT_MEMBER_TABLE.c.version == existing["version"],
                )
                .values(**changes)
            )
            if int(updated.rowcount or 0) != 1:
                raise _concurrent_change()
            results.append(_batch_item("REACTIVATED", {**dict(existing), **changes}))
        return results

    def remove_membership(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        removed_by_subject_id: str,
        removed_at: datetime | None = None,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        subject_id = _scoped_id("subject_id", subject_id)
        removed_by_subject_id = _scoped_id(
            "removed_by_subject_id", removed_by_subject_id
        )
        removed_at = _aware_datetime("removed_at", removed_at or datetime.now(UTC))
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                return self.remove_membership_in_session(
                    transaction.db,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    subject_id=subject_id,
                    removed_by_subject_id=removed_by_subject_id,
                    removed_at=removed_at,
                )
        except EosProjectMembershipError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def remove_membership_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        removed_by_subject_id: str,
        removed_at: datetime | None = None,
        manager_subject_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        subject_id = _scoped_id("subject_id", subject_id)
        removed_by_subject_id = _scoped_id(
            "removed_by_subject_id", removed_by_subject_id
        )
        removed_at = _aware_datetime("removed_at", removed_at or datetime.now(UTC))
        project_status = self._locked_project_status(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if manager_subject_id is not None:
            self._require_manager(
                session,
                tenant_id=tenant_id,
                project_id=project_id,
                subject_id=_scoped_id("manager_subject_id", manager_subject_id),
            )
        existing = self._locked_subject_membership(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            subject_id=subject_id,
        )
        if existing is None:
            raise EosProjectMembershipError(
                "EOS_PROJECT_MEMBERSHIP_NOT_FOUND",
                "Project membership was not found in tenant scope",
                status_code=404,
            )
        if existing["status"] == "REMOVED":
            return dict(existing)
        if existing["member_role"] == "OWNER" and project_status == "ACTIVE":
            active_owner_count = session.execute(
                select(EOS_PROJECT_MEMBER_TABLE.c.project_membership_id).where(
                    EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                    EOS_PROJECT_MEMBER_TABLE.c.member_role == "OWNER",
                    EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
                )
            ).all()
            if len(active_owner_count) <= 1:
                raise EosProjectMembershipError(
                    "EOS_PROJECT_LAST_OWNER_REQUIRED",
                    "An active Project must retain at least one active OWNER",
                    status_code=409,
                )

        changes = {
            "status": "REMOVED",
            "valid_to": removed_at,
            "removed_by_subject_id": removed_by_subject_id,
            "version": int(existing["version"]) + 1,
            "updated_at": removed_at,
        }
        result = session.execute(
            update(EOS_PROJECT_MEMBER_TABLE)
            .where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_MEMBER_TABLE.c.project_membership_id
                == existing["project_membership_id"],
                EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
                EOS_PROJECT_MEMBER_TABLE.c.version == existing["version"],
            )
            .values(**changes)
        )
        if int(result.rowcount or 0) != 1:
            raise _concurrent_change()
        return {**dict(existing), **changes}

    @staticmethod
    def _require_manager(
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
    ) -> None:
        role = session.execute(
            select(EOS_PROJECT_MEMBER_TABLE.c.member_role).where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                EOS_PROJECT_MEMBER_TABLE.c.subject_id == subject_id,
                EOS_PROJECT_MEMBER_TABLE.c.status == "ACTIVE",
            )
        ).scalar_one_or_none()
        if role not in {"OWNER", "MANAGER"}:
            raise EosProjectMembershipError(
                "EOS_PROJECT_MEMBERSHIP_MANAGEMENT_DENIED",
                "An active OWNER or MANAGER membership is required",
                status_code=403,
            )

    @staticmethod
    def _locked_project_status(
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
    ) -> str:
        status = session.execute(
            select(EOS_PROJECT_TABLE.c.status)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_TABLE.c.project_id == project_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if status is None:
            raise EosProjectMembershipError(
                "EOS_PROJECT_NOT_FOUND",
                "Project does not exist in tenant scope",
                status_code=404,
            )
        return str(status)

    @staticmethod
    def _locked_subject_membership(
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
    ) -> Any:
        return (
            session.execute(
                select(EOS_PROJECT_MEMBER_TABLE)
                .where(
                    EOS_PROJECT_MEMBER_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_MEMBER_TABLE.c.project_id == project_id,
                    EOS_PROJECT_MEMBER_TABLE.c.subject_id == subject_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )


def _membership_record(value: ProjectMembershipInput) -> dict[str, Any]:
    now = datetime.now(UTC)
    valid_from = _aware_datetime("valid_from", value.valid_from or now)
    valid_to = (
        _aware_datetime("valid_to", value.valid_to)
        if value.valid_to is not None
        else None
    )
    removed_by_subject_id = (
        _scoped_id("removed_by_subject_id", value.removed_by_subject_id)
        if value.removed_by_subject_id is not None
        else None
    )
    status = _choice("status", value.status, EOS_PROJECT_MEMBER_STATUSES)
    if status == "ACTIVE" and (
        valid_to is not None or removed_by_subject_id is not None
    ):
        raise _invalid("ACTIVE membership cannot contain removal fields")
    if status == "REMOVED" and (
        valid_to is None or removed_by_subject_id is None
    ):
        raise _invalid("REMOVED membership requires removal fields")
    if valid_to is not None and valid_to < valid_from:
        raise _invalid("valid_to must not precede valid_from")
    version = _positive_int("version", value.version)
    if version != 1:
        raise _invalid("version must start at 1")
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "project_membership_id": _uuid(
            "project_membership_id", value.project_membership_id
        ),
        "project_id": _uuid("project_id", value.project_id),
        "subject_id": _scoped_id("subject_id", value.subject_id),
        "member_role": _choice(
            "member_role", value.member_role, EOS_PROJECT_MEMBER_ROLES
        ),
        "status": status,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "version": version,
        "created_by_subject_id": _scoped_id(
            "created_by_subject_id", value.created_by_subject_id
        ),
        "removed_by_subject_id": removed_by_subject_id,
        "created_at": now,
        "updated_at": now,
    }


def deterministic_project_membership_id(
    tenant_id: str, project_id: str, subject_id: str
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "nex:p8:project-operation:membership:"
            f"{_scoped_id('tenant_id', tenant_id)}:"
            f"{_uuid('project_id', project_id)}:"
            f"{_scoped_id('subject_id', subject_id)}",
        )
    )


def _batch_item(outcome: str, membership: Any) -> dict[str, Any]:
    if outcome not in EOS_PROJECT_MEMBERSHIP_BATCH_OUTCOMES:
        raise _invalid("batch item outcome is invalid")
    return {
        "subject_id": str(membership["subject_id"]),
        "outcome": outcome,
        "project_membership_id": str(membership["project_membership_id"]),
        "member_role": str(membership["member_role"]),
        "membership_status": str(membership["status"]),
        "version": int(membership["version"]),
    }


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _scoped_id(field_name: str, value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not _SCOPED_ID.fullmatch(text):
        raise _invalid(f"{field_name} is invalid")
    return text


def _choice(field_name: str, value: object, allowed: frozenset[str]) -> str:
    text = str(value).strip().upper() if value is not None else ""
    if text not in allowed:
        raise _invalid(f"{field_name} is invalid")
    return text


def _aware_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field_name} must be timezone-aware")
    return value


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(f"{field_name} must be a positive integer")
    return value


def _invalid(detail: str) -> EosProjectMembershipError:
    return EosProjectMembershipError(
        "EOS_PROJECT_MEMBERSHIP_INVALID",
        detail,
        status_code=422,
    )


def _persistence_error() -> EosProjectMembershipError:
    return EosProjectMembershipError(
        "EOS_PROJECT_MEMBERSHIP_PERSISTENCE_FAILED",
        "Project membership persistence is unavailable",
        status_code=503,
    )


def _concurrent_change() -> EosProjectMembershipError:
    return EosProjectMembershipError(
        "EOS_PROJECT_MEMBERSHIP_VERSION_CONFLICT",
        "Project membership changed concurrently",
        status_code=409,
    )
