from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime import build_unit_of_work
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    and_,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_METADATA

EOS_ORG_UNIT_TYPES = frozenset({"PART", "TEAM", "GROUP", "COMPANY"})
EOS_POSITION_TYPES = frozenset(
    {"PART_LEAD", "TEAM_LEAD", "GROUP_LEAD", "CEO", "CHAIRMAN"}
)
EOS_ORGANIZATION_STATUSES = frozenset({"ACTIVE", "INACTIVE"})

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

EOS_ORG_UNIT_TABLE = Table(
    "eos_org_unit",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("org_unit_id", Uuid(as_uuid=False), primary_key=True),
    Column("org_unit_code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("org_unit_type", String(16), nullable=False),
    Column("parent_org_unit_id", Uuid(as_uuid=False), nullable=True),
    Column("status", String(16), nullable=False),
    Column("effective_from", DateTime(timezone=True), nullable=False),
    Column("effective_until", DateTime(timezone=True), nullable=True),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "org_unit_code", name="ux_eos_org_unit_code"),
    ForeignKeyConstraint(
        ("tenant_id", "parent_org_unit_id"),
        ("eos_org_unit.tenant_id", "eos_org_unit.org_unit_id"),
        name="fk_eos_org_unit_parent",
    ),
)
EOS_POSITION_TABLE = Table(
    "eos_position",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("position_id", Uuid(as_uuid=False), primary_key=True),
    Column("position_type", String(32), nullable=False),
    Column("org_unit_id", Uuid(as_uuid=False), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "org_unit_id",
        "position_type",
        name="ux_eos_position_type",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "org_unit_id"),
        ("eos_org_unit.tenant_id", "eos_org_unit.org_unit_id"),
        name="fk_eos_position_org_unit",
    ),
)
EOS_POSITION_ASSIGNMENT_TABLE = Table(
    "eos_position_assignment",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("position_assignment_id", Uuid(as_uuid=False), primary_key=True),
    Column("position_id", Uuid(as_uuid=False), nullable=False),
    Column("principal_ref_type", String(32), nullable=False),
    Column("principal_id", String(128), nullable=False),
    Column("effective_from", DateTime(timezone=True), nullable=False),
    Column("effective_until", DateTime(timezone=True), nullable=True),
    Column("status", String(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "position_id"),
        ("eos_position.tenant_id", "eos_position.position_id"),
        name="fk_eos_pos_assignment_position",
    ),
)
Index(
    "ux_eos_pos_assignment_active",
    EOS_POSITION_ASSIGNMENT_TABLE.c.tenant_id,
    EOS_POSITION_ASSIGNMENT_TABLE.c.position_id,
    unique=True,
    sqlite_where=EOS_POSITION_ASSIGNMENT_TABLE.c.status == "ACTIVE",
    postgresql_where=EOS_POSITION_ASSIGNMENT_TABLE.c.status == "ACTIVE",
)
Index(
    "ix_eos_pos_assignment_principal",
    EOS_POSITION_ASSIGNMENT_TABLE.c.tenant_id,
    EOS_POSITION_ASSIGNMENT_TABLE.c.principal_ref_type,
    EOS_POSITION_ASSIGNMENT_TABLE.c.principal_id,
    EOS_POSITION_ASSIGNMENT_TABLE.c.status,
)


class EosOrganizationError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class OrgUnitInput:
    tenant_id: str
    org_unit_id: str
    org_unit_code: str
    name: str
    org_unit_type: str
    effective_from: datetime
    parent_org_unit_id: str | None = None
    effective_until: datetime | None = None
    status: str = "ACTIVE"
    version: int = 1


@dataclass(frozen=True)
class PositionInput:
    tenant_id: str
    position_id: str
    position_type: str
    org_unit_id: str
    status: str = "ACTIVE"


@dataclass(frozen=True)
class PositionAssignmentInput:
    tenant_id: str
    position_assignment_id: str
    position_id: str
    principal_ref: dict[str, str]
    effective_from: datetime
    effective_until: datetime | None = None
    status: str = "ACTIVE"
    version: int = 1


class SqlAlchemyEosOrganizationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_org_unit(self, value: OrgUnitInput) -> dict[str, Any]:
        record = _org_unit_record(value)
        with self._transaction() as transaction:
            if value.parent_org_unit_id is not None:
                _require_reference(
                    transaction.db,
                    EOS_ORG_UNIT_TABLE,
                    tenant_id=record["tenant_id"],
                    id_column="org_unit_id",
                    reference_id=record["parent_org_unit_id"],
                    error_code="EOS_ORG_PARENT_NOT_FOUND",
                )
            self._insert(transaction.db, EOS_ORG_UNIT_TABLE, record)
        return dict(record)

    def create_position(self, value: PositionInput) -> dict[str, Any]:
        record = _position_record(value)
        with self._transaction() as transaction:
            _require_reference(
                transaction.db,
                EOS_ORG_UNIT_TABLE,
                tenant_id=record["tenant_id"],
                id_column="org_unit_id",
                reference_id=record["org_unit_id"],
                error_code="EOS_ORG_UNIT_NOT_FOUND",
            )
            self._insert(transaction.db, EOS_POSITION_TABLE, record)
        return dict(record)

    def assign_position(self, value: PositionAssignmentInput) -> dict[str, Any]:
        record = _assignment_record(value)
        with self._transaction() as transaction:
            _require_reference(
                transaction.db,
                EOS_POSITION_TABLE,
                tenant_id=record["tenant_id"],
                id_column="position_id",
                reference_id=record["position_id"],
                error_code="EOS_POSITION_NOT_FOUND",
            )
            if record["status"] == "ACTIVE":
                duplicate = transaction.db.execute(
                    select(EOS_POSITION_ASSIGNMENT_TABLE.c.position_assignment_id)
                    .where(
                        EOS_POSITION_ASSIGNMENT_TABLE.c.tenant_id
                        == record["tenant_id"],
                        EOS_POSITION_ASSIGNMENT_TABLE.c.position_id
                        == record["position_id"],
                        EOS_POSITION_ASSIGNMENT_TABLE.c.status == "ACTIVE",
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if duplicate is not None:
                    raise EosOrganizationError(
                        "EOS_ACTIVE_POSITION_ASSIGNED",
                        "Position already has an active assignment",
                        status_code=409,
                    )
            self._insert(transaction.db, EOS_POSITION_ASSIGNMENT_TABLE, record)
        return dict(record)

    def effective_assignment(
        self,
        *,
        tenant_id: str,
        position_id: str,
        effective_at: datetime,
    ) -> dict[str, Any] | None:
        normalized_tenant = _scoped_id("tenant_id", tenant_id)
        normalized_position = _uuid("position_id", position_id)
        at = _aware_datetime("effective_at", effective_at)
        with self._session_factory() as session:
            row = session.execute(
                select(EOS_POSITION_ASSIGNMENT_TABLE).where(
                    EOS_POSITION_ASSIGNMENT_TABLE.c.tenant_id
                    == normalized_tenant,
                    EOS_POSITION_ASSIGNMENT_TABLE.c.position_id
                    == normalized_position,
                    EOS_POSITION_ASSIGNMENT_TABLE.c.status == "ACTIVE",
                    EOS_POSITION_ASSIGNMENT_TABLE.c.effective_from <= at,
                    or_(
                        EOS_POSITION_ASSIGNMENT_TABLE.c.effective_until.is_(None),
                        EOS_POSITION_ASSIGNMENT_TABLE.c.effective_until > at,
                    ),
                )
            ).mappings().one_or_none()
        return dict(row) if row is not None else None

    def resolve_active_approver_assignment(
        self,
        *,
        tenant_id: str,
        org_unit_id: str,
        position_type: str,
        effective_at: datetime,
    ) -> dict[str, Any] | None:
        normalized_tenant = _scoped_id("tenant_id", tenant_id)
        normalized_org_unit = _uuid("org_unit_id", org_unit_id)
        normalized_position_type = _choice(
            "position_type", position_type, EOS_POSITION_TYPES
        )
        at = _aware_datetime("effective_at", effective_at)
        statement = (
            select(
                EOS_POSITION_TABLE.c.position_id,
                EOS_POSITION_TABLE.c.position_type,
                EOS_POSITION_TABLE.c.org_unit_id,
                EOS_POSITION_ASSIGNMENT_TABLE.c.position_assignment_id,
                EOS_POSITION_ASSIGNMENT_TABLE.c.principal_ref_type,
                EOS_POSITION_ASSIGNMENT_TABLE.c.principal_id,
                EOS_POSITION_ASSIGNMENT_TABLE.c.version.label(
                    "position_assignment_version"
                ),
                EOS_ORG_UNIT_TABLE.c.version.label("org_unit_version"),
            )
            .select_from(
                EOS_POSITION_TABLE.join(
                    EOS_ORG_UNIT_TABLE,
                    and_(
                        EOS_ORG_UNIT_TABLE.c.tenant_id
                        == EOS_POSITION_TABLE.c.tenant_id,
                        EOS_ORG_UNIT_TABLE.c.org_unit_id
                        == EOS_POSITION_TABLE.c.org_unit_id,
                    ),
                ).join(
                    EOS_POSITION_ASSIGNMENT_TABLE,
                    and_(
                        EOS_POSITION_ASSIGNMENT_TABLE.c.tenant_id
                        == EOS_POSITION_TABLE.c.tenant_id,
                        EOS_POSITION_ASSIGNMENT_TABLE.c.position_id
                        == EOS_POSITION_TABLE.c.position_id,
                    ),
                )
            )
            .where(
                EOS_POSITION_TABLE.c.tenant_id == normalized_tenant,
                EOS_POSITION_TABLE.c.org_unit_id == normalized_org_unit,
                EOS_POSITION_TABLE.c.position_type == normalized_position_type,
                EOS_POSITION_TABLE.c.status == "ACTIVE",
                EOS_ORG_UNIT_TABLE.c.status == "ACTIVE",
                EOS_ORG_UNIT_TABLE.c.effective_from <= at,
                or_(
                    EOS_ORG_UNIT_TABLE.c.effective_until.is_(None),
                    EOS_ORG_UNIT_TABLE.c.effective_until > at,
                ),
                EOS_POSITION_ASSIGNMENT_TABLE.c.status == "ACTIVE",
                EOS_POSITION_ASSIGNMENT_TABLE.c.effective_from <= at,
                or_(
                    EOS_POSITION_ASSIGNMENT_TABLE.c.effective_until.is_(None),
                    EOS_POSITION_ASSIGNMENT_TABLE.c.effective_until > at,
                ),
            )
            .limit(1)
        )
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise EosOrganizationError(
                "EOS_ORGANIZATION_QUERY_FAILED",
                "Organization query is unavailable",
                status_code=503,
            ) from exc
        return dict(row) if row is not None else None

    def _transaction(self):
        return build_unit_of_work(self._session_factory)

    @staticmethod
    def _insert(session: Session, table: Table, record: dict[str, Any]) -> None:
        try:
            session.execute(table.insert().values(**record))
        except IntegrityError as exc:
            raise EosOrganizationError(
                "EOS_ORGANIZATION_CONFLICT",
                "Organization record conflicts with existing state",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise EosOrganizationError(
                "EOS_ORGANIZATION_PERSISTENCE_FAILED",
                "Organization persistence is unavailable",
                status_code=503,
            ) from exc


def _org_unit_record(value: OrgUnitInput) -> dict[str, Any]:
    now = datetime.now(UTC)
    start, end = _period(value.effective_from, value.effective_until)
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "org_unit_id": _uuid("org_unit_id", value.org_unit_id),
        "org_unit_code": _code(value.org_unit_code),
        "name": _text("name", value.name, 256),
        "org_unit_type": _choice("org_unit_type", value.org_unit_type, EOS_ORG_UNIT_TYPES),
        "parent_org_unit_id": (
            _uuid("parent_org_unit_id", value.parent_org_unit_id)
            if value.parent_org_unit_id is not None
            else None
        ),
        "status": _choice("status", value.status, EOS_ORGANIZATION_STATUSES),
        "effective_from": start,
        "effective_until": end,
        "version": _version(value.version),
        "created_at": now,
        "updated_at": now,
    }


def _position_record(value: PositionInput) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "position_id": _uuid("position_id", value.position_id),
        "position_type": _choice("position_type", value.position_type, EOS_POSITION_TYPES),
        "org_unit_id": _uuid("org_unit_id", value.org_unit_id),
        "status": _choice("status", value.status, EOS_ORGANIZATION_STATUSES),
        "created_at": now,
        "updated_at": now,
    }


def _assignment_record(value: PositionAssignmentInput) -> dict[str, Any]:
    now = datetime.now(UTC)
    start, end = _period(value.effective_from, value.effective_until)
    ref_type, principal_id = _principal_ref(value.principal_ref)
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "position_assignment_id": _uuid(
            "position_assignment_id", value.position_assignment_id
        ),
        "position_id": _uuid("position_id", value.position_id),
        "principal_ref_type": ref_type,
        "principal_id": principal_id,
        "effective_from": start,
        "effective_until": end,
        "status": _choice("status", value.status, EOS_ORGANIZATION_STATUSES),
        "version": _version(value.version),
        "created_at": now,
        "updated_at": now,
    }


def _require_reference(
    session: Session,
    table: Table,
    *,
    tenant_id: str,
    id_column: str,
    reference_id: str,
    error_code: str,
) -> None:
    found = session.execute(
        select(table.c[id_column]).where(
            table.c.tenant_id == tenant_id,
            table.c[id_column] == reference_id,
        )
    ).scalar_one_or_none()
    if found is None:
        raise EosOrganizationError(
            error_code,
            "Referenced organization record was not found in tenant scope",
            status_code=422,
        )


def _principal_ref(value: object) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"type", "id"}:
        raise _invalid("principal_ref", "must contain exactly type and id")
    if value.get("type") != "oa.user":
        raise _invalid("principal_ref.type", "must be oa.user")
    return "oa.user", _scoped_id("principal_ref.id", value.get("id"))


def _period(start: datetime, end: datetime | None) -> tuple[datetime, datetime | None]:
    normalized_start = _aware_datetime("effective_from", start)
    normalized_end = _aware_datetime("effective_until", end) if end else None
    if normalized_end is not None and normalized_end <= normalized_start:
        raise _invalid("effective_until", "must be later than effective_from")
    return normalized_start, normalized_end


def _aware_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(field_name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _SCOPED_ID.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _code(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _CODE.fullmatch(normalized):
        raise _invalid("org_unit_code", "has invalid code syntax")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field_name, f"must contain 1..{maximum} characters")
    return normalized


def _choice(field_name: str, value: object, allowed: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in allowed:
        raise _invalid(field_name, f"must be one of {sorted(allowed)}")
    return normalized


def _version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid("version", "must be a positive integer")
    return value


def _invalid(field_name: str, detail: str) -> EosOrganizationError:
    return EosOrganizationError(
        "EOS_ORGANIZATION_INVALID",
        f"{field_name} {detail}",
        status_code=422,
    )
