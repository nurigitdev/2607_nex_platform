from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from nex_runtime import build_unit_of_work
from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    literal,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_METADATA

EOS_PROJECT_STATUSES = frozenset({"ACTIVE", "INACTIVE"})
EOS_PROJECT_MAX_DEPTH = 3
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

EOS_NVT_PROJECT_TABLE = Table(
    "eos_nvt_project",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("nvt_project_id", Uuid(as_uuid=False), primary_key=True),
    Column("nvt_project_code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("status", String(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id", "nvt_project_code", name="ux_eos_nvt_project_code"
    ),
)
Index(
    "ix_eos_nvt_project_status",
    EOS_NVT_PROJECT_TABLE.c.tenant_id,
    EOS_NVT_PROJECT_TABLE.c.status,
    EOS_NVT_PROJECT_TABLE.c.nvt_project_code,
)

EOS_PROJECT_TABLE = Table(
    "eos_project",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("parent_project_id", Uuid(as_uuid=False), nullable=True),
    Column("nvt_project_id", Uuid(as_uuid=False), nullable=True),
    Column("hierarchy_depth", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("start_date", Date, nullable=True),
    Column("end_date", Date, nullable=True),
    Column("currency", String(3), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "project_code", name="ux_eos_project_code"),
    ForeignKeyConstraint(
        ("tenant_id", "nvt_project_id"),
        ("eos_nvt_project.tenant_id", "eos_nvt_project.nvt_project_id"),
        name="fk_eos_project_nvt",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "parent_project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_project_parent",
    ),
    CheckConstraint(
        "(parent_project_id IS NULL AND nvt_project_id IS NOT NULL) OR "
        "(parent_project_id IS NOT NULL AND nvt_project_id IS NULL)",
        name="ck_eos_project_lineage",
    ),
    CheckConstraint(
        "hierarchy_depth BETWEEN 1 AND 3", name="ck_eos_project_depth"
    ),
)
Index(
    "ix_eos_project_parent",
    EOS_PROJECT_TABLE.c.tenant_id,
    EOS_PROJECT_TABLE.c.parent_project_id,
)
Index(
    "ix_eos_project_nvt",
    EOS_PROJECT_TABLE.c.tenant_id,
    EOS_PROJECT_TABLE.c.nvt_project_id,
)


class EosProjectError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class NvtProjectInput:
    tenant_id: str
    nvt_project_id: str
    nvt_project_code: str
    name: str
    status: str = "ACTIVE"
    version: int = 1


@dataclass(frozen=True)
class NvtProjectUpdate:
    tenant_id: str
    nvt_project_id: str
    expected_version: int
    name: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class ProjectInput:
    tenant_id: str
    project_id: str
    project_code: str
    name: str
    parent_project_id: str | None = None
    nvt_project_id: str | None = None
    status: str = "ACTIVE"
    start_date: date | None = None
    end_date: date | None = None
    currency: str = "KRW"
    version: int = 1


class SqlAlchemyEosProjectRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_nvt_project(self, value: NvtProjectInput) -> dict[str, Any]:
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                return self.create_nvt_project_in_session(transaction.db, value)
        except EosProjectError:
            raise
        except IntegrityError as exc:
            raise EosProjectError(
                "EOS_NVT_PROJECT_CONFLICT",
                "NVTProject identity or code already exists in tenant scope",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @staticmethod
    def create_nvt_project_in_session(
        session: Session,
        value: NvtProjectInput,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        record = {
            "tenant_id": _scoped_id("tenant_id", value.tenant_id),
            "nvt_project_id": _uuid("nvt_project_id", value.nvt_project_id),
            "nvt_project_code": _code("nvt_project_code", value.nvt_project_code),
            "name": _text("name", value.name, 256),
            "status": _status(value.status),
            "version": _positive_int("version", value.version),
            "created_at": now,
            "updated_at": now,
        }
        if record["version"] != 1:
            raise _invalid("version", "must start at 1")
        session.execute(EOS_NVT_PROJECT_TABLE.insert().values(**record))
        return dict(record)

    def create_project(self, value: ProjectInput) -> dict[str, Any]:
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                return self.create_project_in_session(transaction.db, value)
        except EosProjectError:
            raise
        except IntegrityError as exc:
            raise EosProjectError(
                "EOS_PROJECT_CONFLICT",
                "Project identity or code already exists in tenant scope",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def create_project_in_session(
        self,
        session: Session,
        value: ProjectInput,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", value.tenant_id)
        project_id = _uuid("project_id", value.project_id)
        parent_project_id = _optional_uuid(
            "parent_project_id", value.parent_project_id
        )
        nvt_project_id = _optional_uuid("nvt_project_id", value.nvt_project_id)
        version = _positive_int("version", value.version)
        if version != 1:
            raise _invalid("version", "must start at 1")
        start_date = _optional_date("start_date", value.start_date)
        end_date = _optional_date("end_date", value.end_date)
        if start_date is not None and end_date is not None and end_date < start_date:
            raise _invalid("end_date", "must not precede start_date")
        now = datetime.now(UTC)

        depth = self._admit_hierarchy(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            parent_project_id=parent_project_id,
            nvt_project_id=nvt_project_id,
        )
        record = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "project_code": _code("project_code", value.project_code),
            "name": _text("name", value.name, 256),
            "parent_project_id": parent_project_id,
            "nvt_project_id": nvt_project_id,
            "hierarchy_depth": depth,
            "status": _status(value.status),
            "start_date": start_date,
            "end_date": end_date,
            "currency": _currency(value.currency),
            "version": version,
            "created_at": now,
            "updated_at": now,
        }
        session.execute(EOS_PROJECT_TABLE.insert().values(**record))
        return dict(record)

    def get_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        active_only: bool = False,
    ) -> dict[str, Any] | None:
        statement = select(EOS_PROJECT_TABLE).where(
            EOS_PROJECT_TABLE.c.tenant_id == _scoped_id("tenant_id", tenant_id),
            EOS_PROJECT_TABLE.c.project_id == _uuid("project_id", project_id),
        )
        if active_only:
            statement = statement.where(EOS_PROJECT_TABLE.c.status == "ACTIVE")
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None

    def find_project_tenants(
        self,
        *,
        project_id: str,
        limit: int = 2,
    ) -> tuple[str, ...]:
        statement = (
            select(EOS_PROJECT_TABLE.c.tenant_id)
            .where(
                EOS_PROJECT_TABLE.c.project_id == _uuid("project_id", project_id)
            )
            .order_by(EOS_PROJECT_TABLE.c.tenant_id)
            .limit(_bounded_limit(limit))
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(statement).scalars().all()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return tuple(str(item) for item in rows)

    def list_projects_for_nvt(
        self,
        *,
        tenant_id: str,
        nvt_project_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        nvt_project_id = _uuid("nvt_project_id", nvt_project_id)
        limit = _bounded_limit(limit)
        project_tree = (
            select(EOS_PROJECT_TABLE)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_TABLE.c.parent_project_id.is_(None),
                EOS_PROJECT_TABLE.c.nvt_project_id == nvt_project_id,
            )
            .cte("eos_project_tree", recursive=True)
        )
        descendants = select(EOS_PROJECT_TABLE).join(
            project_tree,
            (EOS_PROJECT_TABLE.c.tenant_id == project_tree.c.tenant_id)
            & (
                EOS_PROJECT_TABLE.c.parent_project_id
                == project_tree.c.project_id
            ),
        )
        project_tree = project_tree.union_all(descendants)
        statement = (
            select(project_tree)
            .where(project_tree.c.hierarchy_depth <= EOS_PROJECT_MAX_DEPTH)
            .order_by(project_tree.c.hierarchy_depth, project_tree.c.project_code)
            .limit(limit)
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(statement).mappings().all()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return [dict(row) for row in rows]

    def resolve_nvt_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        ancestry = (
            select(
                EOS_PROJECT_TABLE.c.project_id,
                EOS_PROJECT_TABLE.c.parent_project_id,
                EOS_PROJECT_TABLE.c.nvt_project_id,
                literal(1).label("walk_depth"),
            )
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_TABLE.c.project_id == project_id,
            )
            .cte("eos_project_ancestry", recursive=True)
        )
        parents = (
            select(
                EOS_PROJECT_TABLE.c.project_id,
                EOS_PROJECT_TABLE.c.parent_project_id,
                EOS_PROJECT_TABLE.c.nvt_project_id,
                (ancestry.c.walk_depth + 1).label("walk_depth"),
            )
            .join(
                ancestry,
                (EOS_PROJECT_TABLE.c.tenant_id == tenant_id)
                & (EOS_PROJECT_TABLE.c.project_id == ancestry.c.parent_project_id),
            )
            .where(ancestry.c.walk_depth < EOS_PROJECT_MAX_DEPTH)
        )
        ancestry = ancestry.union_all(parents)
        statement = (
            select(ancestry.c.nvt_project_id)
            .where(ancestry.c.nvt_project_id.is_not(None))
            .order_by(ancestry.c.walk_depth.desc())
            .limit(1)
        )
        try:
            with self._session_factory() as session:
                nvt_project_id = session.execute(statement).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        if nvt_project_id is None:
            return None
        return self.get_nvt_project(
            tenant_id=tenant_id,
            nvt_project_id=str(nvt_project_id),
        )

    @staticmethod
    def _admit_hierarchy(
        session: Session,
        *,
        tenant_id: str,
        project_id: str,
        parent_project_id: str | None,
        nvt_project_id: str | None,
    ) -> int:
        if parent_project_id is None:
            if nvt_project_id is None:
                raise _invalid("nvt_project_id", "is required for a Mother Project")
            nvt_status = session.execute(
                select(EOS_NVT_PROJECT_TABLE.c.status).where(
                    EOS_NVT_PROJECT_TABLE.c.tenant_id == tenant_id,
                    EOS_NVT_PROJECT_TABLE.c.nvt_project_id == nvt_project_id,
                )
            ).scalar_one_or_none()
            if nvt_status is None:
                raise EosProjectError(
                    "EOS_NVT_PROJECT_NOT_FOUND",
                    "NVTProject was not found in tenant scope",
                    status_code=404,
                )
            if nvt_status != "ACTIVE":
                raise EosProjectError(
                    "EOS_NVT_PROJECT_NOT_ACTIVE",
                    "NVTProject is not active",
                    status_code=409,
                )
            return 1

        if nvt_project_id is not None:
            raise _invalid(
                "nvt_project_id", "must be omitted for a Child Project"
            )
        if parent_project_id == project_id:
            raise EosProjectError(
                "EOS_PROJECT_CYCLE",
                "Project cannot be its own parent or ancestor",
                status_code=409,
            )

        visited = {project_id}
        current_id: str | None = parent_project_id
        parent_depth: int | None = None
        while current_id is not None:
            if current_id in visited:
                raise EosProjectError(
                    "EOS_PROJECT_CYCLE",
                    "Project hierarchy contains a cycle",
                    status_code=409,
                )
            visited.add(current_id)
            row = session.execute(
                select(
                    EOS_PROJECT_TABLE.c.parent_project_id,
                    EOS_PROJECT_TABLE.c.hierarchy_depth,
                ).where(
                    EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_TABLE.c.project_id == current_id,
                )
            ).mappings().one_or_none()
            if row is None:
                raise EosProjectError(
                    "EOS_PROJECT_PARENT_NOT_FOUND",
                    "Parent Project was not found in tenant scope",
                    status_code=404,
                )
            if parent_depth is None:
                parent_depth = int(row["hierarchy_depth"])
            current_id = (
                str(row["parent_project_id"])
                if row["parent_project_id"] is not None
                else None
            )

        depth = (parent_depth or 0) + 1
        if depth > EOS_PROJECT_MAX_DEPTH:
            raise EosProjectError(
                "EOS_PROJECT_DEPTH_EXCEEDED",
                f"Project hierarchy depth must not exceed {EOS_PROJECT_MAX_DEPTH}",
                status_code=409,
            )
        return depth

    def get_nvt_project(
        self,
        *,
        tenant_id: str,
        nvt_project_id: str,
        active_only: bool = False,
    ) -> dict[str, Any] | None:
        statement = select(EOS_NVT_PROJECT_TABLE).where(
            EOS_NVT_PROJECT_TABLE.c.tenant_id == _scoped_id("tenant_id", tenant_id),
            EOS_NVT_PROJECT_TABLE.c.nvt_project_id
            == _uuid("nvt_project_id", nvt_project_id),
        )
        if active_only:
            statement = statement.where(EOS_NVT_PROJECT_TABLE.c.status == "ACTIVE")
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None

    def list_nvt_projects(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        statement = select(EOS_NVT_PROJECT_TABLE).where(
            EOS_NVT_PROJECT_TABLE.c.tenant_id == _scoped_id("tenant_id", tenant_id)
        )
        if status is not None:
            statement = statement.where(
                EOS_NVT_PROJECT_TABLE.c.status == _status(status)
            )
        statement = statement.order_by(
            EOS_NVT_PROJECT_TABLE.c.nvt_project_code,
            EOS_NVT_PROJECT_TABLE.c.nvt_project_id,
        ).limit(_bounded_limit(limit)).offset(_bounded_offset(offset))
        try:
            with self._session_factory() as session:
                rows = session.execute(statement).mappings().all()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return [dict(row) for row in rows]

    def update_nvt_project(self, value: NvtProjectUpdate) -> dict[str, Any]:
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                return self.update_nvt_project_in_session(transaction.db, value)
        except EosProjectError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @staticmethod
    def update_nvt_project_in_session(
        session: Session,
        value: NvtProjectUpdate,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", value.tenant_id)
        nvt_project_id = _uuid("nvt_project_id", value.nvt_project_id)
        expected_version = _positive_int("expected_version", value.expected_version)
        requested_changes: dict[str, Any] = {}
        if value.name is not None:
            requested_changes["name"] = _text("name", value.name, 256)
        if value.status is not None:
            requested_changes["status"] = _status(value.status)
        if not requested_changes:
            raise _invalid("update", "must change name or status")

        current = (
            session.execute(
                select(EOS_NVT_PROJECT_TABLE)
                .where(
                    EOS_NVT_PROJECT_TABLE.c.tenant_id == tenant_id,
                    EOS_NVT_PROJECT_TABLE.c.nvt_project_id == nvt_project_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if current is None:
            raise EosProjectError(
                "EOS_NVT_PROJECT_NOT_FOUND",
                "NVTProject was not found in tenant scope",
                status_code=404,
            )
        if int(current["version"]) != expected_version:
            raise EosProjectError(
                "EOS_NVT_PROJECT_VERSION_CONFLICT",
                "NVTProject version changed before update",
                status_code=409,
            )

        semantic_changes = {
            field_name: field_value
            for field_name, field_value in requested_changes.items()
            if current[field_name] != field_value
        }
        if not semantic_changes:
            return dict(current)

        if current["status"] == "ACTIVE" and semantic_changes.get("status") == "INACTIVE":
            active_project_id = session.execute(
                select(EOS_PROJECT_TABLE.c.project_id)
                .where(
                    EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                    EOS_PROJECT_TABLE.c.nvt_project_id == nvt_project_id,
                    EOS_PROJECT_TABLE.c.parent_project_id.is_(None),
                    EOS_PROJECT_TABLE.c.status == "ACTIVE",
                )
                .limit(1)
            ).scalar_one_or_none()
            if active_project_id is not None:
                raise EosProjectError(
                    "EOS_NVT_PROJECT_IN_USE",
                    "NVTProject has an active Mother Project",
                    status_code=409,
                )

        changes = {
            **semantic_changes,
            "version": expected_version + 1,
            "updated_at": datetime.now(UTC),
        }
        result = session.execute(
            update(EOS_NVT_PROJECT_TABLE)
            .where(
                EOS_NVT_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_NVT_PROJECT_TABLE.c.nvt_project_id == nvt_project_id,
                EOS_NVT_PROJECT_TABLE.c.version == expected_version,
            )
            .values(**changes)
        )
        if result.rowcount != 1:
            raise EosProjectError(
                "EOS_NVT_PROJECT_VERSION_CONFLICT",
                "NVTProject version changed before update",
                status_code=409,
            )
        return {**dict(current), **changes}


def _status(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in EOS_PROJECT_STATUSES:
        raise _invalid("status", f"must be one of {sorted(EOS_PROJECT_STATUSES)}")
    return normalized


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _optional_uuid(field_name: str, value: object) -> str | None:
    return None if value is None else _uuid(field_name, value)


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _SCOPED_ID.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _code(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _CODE.fullmatch(normalized):
        raise _invalid(field_name, "has invalid code syntax")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field_name, f"must contain 1..{maximum} characters")
    return normalized


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _bounded_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        raise _invalid("limit", "must be an integer between 1 and 1000")
    return value


def _bounded_offset(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid("offset", "must be a non-negative integer")
    return value


def _currency(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if not _CURRENCY.fullmatch(normalized):
        raise _invalid("currency", "must be a three-letter uppercase code")
    return normalized


def _optional_date(field_name: str, value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(field_name, "must be a date")
    return value


def _invalid(field_name: str, detail: str) -> EosProjectError:
    return EosProjectError(
        "EOS_PROJECT_INVALID", f"{field_name} {detail}", status_code=422
    )


def _persistence_error() -> EosProjectError:
    return EosProjectError(
        "EOS_PROJECT_PERSISTENCE_FAILED",
        "Project persistence is unavailable",
        status_code=503,
    )
