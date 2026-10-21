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

EOS_PROJECT_STATUSES = frozenset({"ACTIVE", "INACTIVE"})
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

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


class SqlAlchemyEosProjectRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_nvt_project(self, value: NvtProjectInput) -> dict[str, Any]:
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
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                transaction.db.execute(EOS_NVT_PROJECT_TABLE.insert().values(**record))
        except IntegrityError as exc:
            raise EosProjectError(
                "EOS_NVT_PROJECT_CONFLICT",
                "NVTProject identity or code already exists in tenant scope",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(record)

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

    def update_nvt_project(self, value: NvtProjectUpdate) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", value.tenant_id)
        nvt_project_id = _uuid("nvt_project_id", value.nvt_project_id)
        expected_version = _positive_int("expected_version", value.expected_version)
        changes: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if value.name is not None:
            changes["name"] = _text("name", value.name, 256)
        if value.status is not None:
            changes["status"] = _status(value.status)
        if len(changes) == 1:
            raise _invalid("update", "must change name or status")
        changes["version"] = expected_version + 1

        try:
            with build_unit_of_work(self._session_factory) as transaction:
                result = transaction.db.execute(
                    update(EOS_NVT_PROJECT_TABLE)
                    .where(
                        EOS_NVT_PROJECT_TABLE.c.tenant_id == tenant_id,
                        EOS_NVT_PROJECT_TABLE.c.nvt_project_id == nvt_project_id,
                        EOS_NVT_PROJECT_TABLE.c.version == expected_version,
                    )
                    .values(**changes)
                )
                if result.rowcount != 1:
                    current = transaction.db.execute(
                        select(EOS_NVT_PROJECT_TABLE.c.version).where(
                            EOS_NVT_PROJECT_TABLE.c.tenant_id == tenant_id,
                            EOS_NVT_PROJECT_TABLE.c.nvt_project_id == nvt_project_id,
                        )
                    ).scalar_one_or_none()
                    if current is None:
                        raise EosProjectError(
                            "EOS_NVT_PROJECT_NOT_FOUND",
                            "NVTProject was not found in tenant scope",
                            status_code=404,
                        )
                    raise EosProjectError(
                        "EOS_NVT_PROJECT_VERSION_CONFLICT",
                        "NVTProject version changed before update",
                        status_code=409,
                    )
        except EosProjectError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        found = self.get_nvt_project(
            tenant_id=tenant_id,
            nvt_project_id=nvt_project_id,
        )
        if found is None:  # pragma: no cover - committed update guarantees the row
            raise _persistence_error()
        return found


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
