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
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_METADATA

EOS_ACCOUNT_CATEGORIES = frozenset(
    {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"}
)
EOS_ACCOUNT_STATUSES = frozenset({"ACTIVE", "INACTIVE"})
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_TYPE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")

EOS_ACCOUNT_TABLE = Table(
    "eos_account",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("account_id", Uuid(as_uuid=False), primary_key=True),
    Column("account_code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("category", String(16), nullable=False),
    Column("account_type", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("effective_until", Date, nullable=True),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "account_code", name="ux_eos_account_code"),
    CheckConstraint(
        "effective_until IS NULL OR effective_until > effective_from",
        name="ck_eos_account_period",
    ),
)
Index(
    "ix_eos_account_effective",
    EOS_ACCOUNT_TABLE.c.tenant_id,
    EOS_ACCOUNT_TABLE.c.status,
    EOS_ACCOUNT_TABLE.c.effective_from,
    EOS_ACCOUNT_TABLE.c.effective_until,
)


class EosAccountError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class AccountInput:
    tenant_id: str
    account_id: str
    account_code: str
    name: str
    category: str
    account_type: str
    effective_from: date
    status: str = "ACTIVE"
    effective_until: date | None = None
    version: int = 1


class SqlAlchemyEosAccountRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_account(self, value: AccountInput) -> dict[str, Any]:
        effective_from = _date("effective_from", value.effective_from)
        effective_until = _optional_date("effective_until", value.effective_until)
        if effective_until is not None and effective_until <= effective_from:
            raise _invalid("effective_until", "must follow effective_from")
        version = _positive_int("version", value.version)
        if version != 1:
            raise _invalid("version", "must start at 1")
        now = datetime.now(UTC)
        record = {
            "tenant_id": _scoped_id("tenant_id", value.tenant_id),
            "account_id": _uuid("account_id", value.account_id),
            "account_code": _code(value.account_code),
            "name": _text("name", value.name, 256),
            "category": _choice("category", value.category, EOS_ACCOUNT_CATEGORIES),
            "account_type": _account_type(value.account_type),
            "status": _choice("status", value.status, EOS_ACCOUNT_STATUSES),
            "effective_from": effective_from,
            "effective_until": effective_until,
            "version": version,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                transaction.db.execute(EOS_ACCOUNT_TABLE.insert().values(**record))
        except IntegrityError as exc:
            raise EosAccountError(
                "EOS_ACCOUNT_CONFLICT",
                "Account identity or code already exists in tenant scope",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(record)

    def get_account(
        self, *, tenant_id: str, account_id: str
    ) -> dict[str, Any] | None:
        statement = select(EOS_ACCOUNT_TABLE).where(
            EOS_ACCOUNT_TABLE.c.tenant_id == _scoped_id("tenant_id", tenant_id),
            EOS_ACCOUNT_TABLE.c.account_id == _uuid("account_id", account_id),
        )
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None

    def get_effective_account(
        self,
        *,
        tenant_id: str,
        account_id: str,
        effective_at: date,
    ) -> dict[str, Any] | None:
        effective_at = _date("effective_at", effective_at)
        statement = select(EOS_ACCOUNT_TABLE).where(
            EOS_ACCOUNT_TABLE.c.tenant_id == _scoped_id("tenant_id", tenant_id),
            EOS_ACCOUNT_TABLE.c.account_id == _uuid("account_id", account_id),
            EOS_ACCOUNT_TABLE.c.status == "ACTIVE",
            EOS_ACCOUNT_TABLE.c.effective_from <= effective_at,
            (
                EOS_ACCOUNT_TABLE.c.effective_until.is_(None)
                | (EOS_ACCOUNT_TABLE.c.effective_until > effective_at)
            ),
        )
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None

    def get_effective_account_by_code(
        self,
        *,
        tenant_id: str,
        account_code: str,
        effective_at: date,
    ) -> dict[str, Any] | None:
        effective_at = _date("effective_at", effective_at)
        statement = select(EOS_ACCOUNT_TABLE).where(
            EOS_ACCOUNT_TABLE.c.tenant_id == _scoped_id("tenant_id", tenant_id),
            EOS_ACCOUNT_TABLE.c.account_code == _code(account_code),
            EOS_ACCOUNT_TABLE.c.status == "ACTIVE",
            EOS_ACCOUNT_TABLE.c.effective_from <= effective_at,
            (
                EOS_ACCOUNT_TABLE.c.effective_until.is_(None)
                | (EOS_ACCOUNT_TABLE.c.effective_until > effective_at)
            ),
        )
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None


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
        raise _invalid("account_code", "has invalid code syntax")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field_name, f"must contain 1..{maximum} characters")
    return normalized


def _choice(field_name: str, value: object, choices: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in choices:
        raise _invalid(field_name, f"must be one of {sorted(choices)}")
    return normalized


def _account_type(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if not _TYPE.fullmatch(normalized):
        raise _invalid("account_type", "has invalid type syntax")
    return normalized


def _date(field_name: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(field_name, "must be a date")
    return value


def _optional_date(field_name: str, value: object) -> date | None:
    return None if value is None else _date(field_name, value)


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _invalid(field_name: str, detail: str) -> EosAccountError:
    return EosAccountError(
        "EOS_ACCOUNT_INVALID", f"{field_name} {detail}", status_code=422
    )


def _persistence_error() -> EosAccountError:
    return EosAccountError(
        "EOS_ACCOUNT_PERSISTENCE_FAILED",
        "Account persistence is unavailable",
        status_code=503,
    )
