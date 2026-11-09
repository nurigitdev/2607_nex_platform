from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nex_runtime import build_unit_of_work
from nex_runtime.semantic_hashes import validate_hash_ref
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
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import EOS_METADATA
from .projects import EOS_PROJECT_TABLE

EOS_LEGAL_ENTITY_STATUSES = frozenset({"ACTIVE", "INACTIVE"})
EOS_PROJECT_COMPANY_BINDING_STATES = frozenset({"APPROVED", "REVOKED"})
FINANCE_COMPANY_READ_SCOPE = "finance:company:read"
PROJECT_COMPANY_BINDING_READ_SCOPE = "project:company-binding:read"
PROJECT_COMPANY_BINDING_MANAGE_SCOPE = "project:company-binding:manage"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")

EOS_LEGAL_ENTITY_TABLE = Table(
    "eos_legal_entity",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("presentation_currency", String(3), nullable=False),
    Column("business_timezone", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "company_code", name="ux_eos_legal_entity_code"),
    CheckConstraint(
        "length(functional_currency) = 3 AND "
        "functional_currency = upper(functional_currency) AND "
        "length(presentation_currency) = 3 AND "
        "presentation_currency = upper(presentation_currency)",
        name="ck_eos_legal_entity_currency_shape",
    ),
    CheckConstraint(
        "status IN ('ACTIVE', 'INACTIVE')", name="ck_eos_legal_entity_status"
    ),
    CheckConstraint("version > 0", name="ck_eos_legal_entity_version"),
)
Index(
    "ix_eos_legal_entity_effective",
    EOS_LEGAL_ENTITY_TABLE.c.tenant_id,
    EOS_LEGAL_ENTITY_TABLE.c.status,
    EOS_LEGAL_ENTITY_TABLE.c.effective_from,
)

EOS_PROJECT_COMPANY_BINDING_TABLE = Table(
    "eos_project_company_binding",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("binding_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_until", Date, nullable=True),
    Column("approved_proof_hash", String(71), nullable=False),
    Column("state", String(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_project_company_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_project_company_entity",
    ),
    CheckConstraint(
        "valid_until IS NULL OR valid_until > valid_from",
        name="ck_eos_project_company_period",
    ),
    CheckConstraint(
        "state IN ('APPROVED', 'REVOKED')", name="ck_eos_project_company_state"
    ),
    CheckConstraint("version > 0", name="ck_eos_project_company_version"),
)
Index(
    "ix_eos_project_company_effective",
    EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id,
    EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id,
    EOS_PROJECT_COMPANY_BINDING_TABLE.c.state,
    EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from,
    EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until,
)
Index(
    "ix_eos_project_company_entity",
    EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id,
    EOS_PROJECT_COMPANY_BINDING_TABLE.c.company_id,
)


class EosLegalEntityError(RuntimeError):
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


@dataclass(frozen=True)
class LegalEntityInput:
    tenant_id: str
    company_id: str
    company_code: str
    name: str
    functional_currency: str
    presentation_currency: str
    business_timezone: str
    effective_from: date
    status: str = "ACTIVE"
    version: int = 1


@dataclass(frozen=True)
class ProjectCompanyBindingInput:
    tenant_id: str
    binding_id: str
    project_id: str
    company_id: str
    valid_from: date
    approved_proof_hash: str
    valid_until: date | None = None
    state: str = "APPROVED"
    version: int = 1


class SqlAlchemyEosLegalEntityRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_legal_entity(self, value: LegalEntityInput) -> dict[str, Any]:
        record = _legal_entity_record(value)
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                transaction.db.execute(EOS_LEGAL_ENTITY_TABLE.insert().values(**record))
        except IntegrityError as exc:
            raise EosLegalEntityError(
                "EOS_LEGAL_ENTITY_CONFLICT",
                "LegalEntity identity or company code already exists in tenant scope",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(record)

    def get_legal_entity(
        self,
        *,
        tenant_id: str,
        company_id: str,
        effective_on: date | None = None,
        active_only: bool = False,
    ) -> dict[str, Any] | None:
        statement = select(EOS_LEGAL_ENTITY_TABLE).where(
            EOS_LEGAL_ENTITY_TABLE.c.tenant_id == _scoped_id("tenant_id", tenant_id),
            EOS_LEGAL_ENTITY_TABLE.c.company_id == _uuid("company_id", company_id),
        )
        if active_only:
            statement = statement.where(EOS_LEGAL_ENTITY_TABLE.c.status == "ACTIVE")
        if effective_on is not None:
            statement = statement.where(
                EOS_LEGAL_ENTITY_TABLE.c.effective_from
                <= _date("effective_on", effective_on)
            )
        try:
            with self._session_factory() as session:
                row = session.execute(statement).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(row) if row is not None else None

    def create_project_company_binding(
        self, value: ProjectCompanyBindingInput
    ) -> dict[str, Any]:
        record = _binding_record(value)
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                session = transaction.db
                existing = (
                    session.execute(
                        select(EOS_PROJECT_COMPANY_BINDING_TABLE).where(
                            EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id
                            == record["tenant_id"],
                            EOS_PROJECT_COMPANY_BINDING_TABLE.c.binding_id
                            == record["binding_id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if _binding_semantics(existing) == _binding_semantics(record):
                        return dict(existing)
                    raise _binding_conflict("binding identity has different semantics")

                self._lock_binding_scope(
                    session,
                    tenant_id=record["tenant_id"],
                    project_id=record["project_id"],
                )
                self._require_project_and_company(session, record)
                if record["state"] == "APPROVED":
                    overlap = session.execute(
                        _overlap_statement(record)
                    ).scalar_one_or_none()
                    if overlap is not None:
                        raise _binding_conflict(
                            "effective period overlaps another binding"
                        )
                session.execute(
                    EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(**record)
                )
        except EosLegalEntityError:
            raise
        except IntegrityError as exc:
            raise _binding_conflict(
                "binding violates an EOS identity or range guard"
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(record)

    def get_effective_project_company_binding(
        self,
        *,
        tenant_id: str,
        project_id: str,
        effective_on: date,
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        project_id = _uuid("project_id", project_id)
        effective_on = _date("effective_on", effective_on)
        statement = select(EOS_PROJECT_COMPANY_BINDING_TABLE).where(
            EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id == tenant_id,
            EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == project_id,
            EOS_PROJECT_COMPANY_BINDING_TABLE.c.state == "APPROVED",
            EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from <= effective_on,
            or_(
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until.is_(None),
                EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until > effective_on,
            ),
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(statement).mappings().all()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        if len(rows) > 1:
            raise EosLegalEntityError(
                "EOS_PROJECT_COMPANY_BINDING_AMBIGUOUS",
                "Project has multiple effective accounting companies",
                status_code=409,
            )
        return dict(rows[0]) if rows else None

    @staticmethod
    def _lock_binding_scope(
        session: Session, *, tenant_id: str, project_id: str
    ) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"{tenant_id}:{project_id}"},
            )

    @staticmethod
    def _require_project_and_company(
        session: Session, record: Mapping[str, Any]
    ) -> None:
        project = session.execute(
            select(EOS_PROJECT_TABLE.c.project_id)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == record["tenant_id"],
                EOS_PROJECT_TABLE.c.project_id == record["project_id"],
            )
            .with_for_update()
        ).scalar_one_or_none()
        if project is None:
            raise EosLegalEntityError(
                "EOS_PROJECT_NOT_FOUND",
                "A real tenant-scoped Project is required for company binding",
                status_code=404,
            )
        company = (
            session.execute(
                select(
                    EOS_LEGAL_ENTITY_TABLE.c.status,
                    EOS_LEGAL_ENTITY_TABLE.c.effective_from,
                )
                .where(
                    EOS_LEGAL_ENTITY_TABLE.c.tenant_id == record["tenant_id"],
                    EOS_LEGAL_ENTITY_TABLE.c.company_id == record["company_id"],
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise EosLegalEntityError(
                "EOS_LEGAL_ENTITY_NOT_FOUND",
                "LegalEntity was not found in tenant scope",
                status_code=404,
            )
        if (
            company["status"] != "ACTIVE"
            or company["effective_from"] > record["valid_from"]
        ):
            raise EosLegalEntityError(
                "EOS_LEGAL_ENTITY_NOT_EFFECTIVE",
                "LegalEntity is not active and effective at binding start",
                status_code=409,
            )


class EosLegalEntityService:
    def __init__(
        self,
        repository: SqlAlchemyEosLegalEntityRepository,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source

    def get_legal_entity(
        self,
        *,
        tenant_id: str,
        company_id: str,
        requester_subject_id: str,
        effective_on: date | None = None,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=FINANCE_COMPANY_READ_SCOPE,
        )
        found = self._repository.get_legal_entity(
            tenant_id=tenant_id,
            company_id=company_id,
            effective_on=effective_on,
            active_only=True,
        )
        if found is None:
            raise EosLegalEntityError(
                "EOS_LEGAL_ENTITY_NOT_FOUND",
                "LegalEntity was not found in the admitted tenant and effective scope",
                status_code=404,
            )
        return _wire(found)

    def bind_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        requester_subject_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=PROJECT_COMPANY_BINDING_MANAGE_SCOPE,
        )
        created = self._repository.create_project_company_binding(
            ProjectCompanyBindingInput(
                tenant_id=tenant_id,
                binding_id=_uuid("binding_id", payload.get("binding_id")),
                project_id=_uuid("project_id", project_id),
                company_id=_uuid("company_id", payload.get("company_id")),
                valid_from=_date_input("valid_from", payload.get("valid_from")),
                valid_until=_optional_date_input(
                    "valid_until", payload.get("valid_until")
                ),
                approved_proof_hash=_hash_ref(
                    "approved_proof_hash", payload.get("approved_proof_hash")
                ),
            )
        )
        return _wire(created)

    def get_project_company_binding(
        self,
        *,
        tenant_id: str,
        project_id: str,
        requester_subject_id: str,
        effective_on: date,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=PROJECT_COMPANY_BINDING_READ_SCOPE,
        )
        found = self._repository.get_effective_project_company_binding(
            tenant_id=tenant_id,
            project_id=project_id,
            effective_on=effective_on,
        )
        if found is None:
            raise EosLegalEntityError(
                "EOS_PROJECT_COMPANY_BINDING_NOT_FOUND",
                "Project has no effective accounting company at the requested date",
                status_code=404,
            )
        return _wire(found)

    def _authorize(
        self, *, tenant_id: str, subject_id: str, required_scope: str
    ) -> None:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _authorization_denied(required_scope) from exc
        except Exception as exc:
            raise EosLegalEntityError(
                "EOS_LEGAL_ENTITY_AUTHORIZATION_UNAVAILABLE",
                "OA effective authorization is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        _admit_authorization(
            value,
            tenant_id=tenant_id,
            subject_id=subject_id,
            required_scope=required_scope,
        )


def _legal_entity_record(value: LegalEntityInput) -> dict[str, Any]:
    version = _positive_int("version", value.version)
    if version != 1:
        raise _invalid("version", "must start at 1")
    now = datetime.now(UTC)
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "company_id": _uuid("company_id", value.company_id),
        "company_code": _code("company_code", value.company_code),
        "name": _text("name", value.name, 256),
        "functional_currency": _currency(
            "functional_currency", value.functional_currency
        ),
        "presentation_currency": _currency(
            "presentation_currency", value.presentation_currency
        ),
        "business_timezone": _timezone(value.business_timezone),
        "status": _choice("status", value.status, EOS_LEGAL_ENTITY_STATUSES),
        "effective_from": _date("effective_from", value.effective_from),
        "version": version,
        "created_at": now,
        "updated_at": now,
    }


def _binding_record(value: ProjectCompanyBindingInput) -> dict[str, Any]:
    valid_from = _date("valid_from", value.valid_from)
    valid_until = _optional_date("valid_until", value.valid_until)
    if valid_until is not None and valid_until <= valid_from:
        raise _invalid("valid_until", "must follow valid_from")
    version = _positive_int("version", value.version)
    if version != 1:
        raise _invalid("version", "must start at 1")
    now = datetime.now(UTC)
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "binding_id": _uuid("binding_id", value.binding_id),
        "project_id": _uuid("project_id", value.project_id),
        "company_id": _uuid("company_id", value.company_id),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "approved_proof_hash": _hash_ref(
            "approved_proof_hash", value.approved_proof_hash
        ),
        "state": _choice("state", value.state, EOS_PROJECT_COMPANY_BINDING_STATES),
        "version": version,
        "created_at": now,
        "updated_at": now,
    }


def _binding_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        value[field]
        for field in (
            "tenant_id",
            "binding_id",
            "project_id",
            "company_id",
            "valid_from",
            "valid_until",
            "approved_proof_hash",
            "state",
            "version",
        )
    )


def _overlap_statement(record: Mapping[str, Any]):
    existing = EOS_PROJECT_COMPANY_BINDING_TABLE
    predicates = [
        existing.c.tenant_id == record["tenant_id"],
        existing.c.project_id == record["project_id"],
        existing.c.state == "APPROVED",
        or_(
            existing.c.valid_until.is_(None),
            existing.c.valid_until > record["valid_from"],
        ),
    ]
    if record["valid_until"] is not None:
        predicates.append(existing.c.valid_from < record["valid_until"])
    return select(existing.c.binding_id).where(*predicates).limit(1)


def _admit_authorization(
    value: object, *, tenant_id: str, subject_id: str, required_scope: str
) -> None:
    if not isinstance(value, Mapping):
        raise _authorization_unavailable("OA response is not an object")
    if value.get("active") is not True:
        raise _authorization_denied(required_scope)
    if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
        raise _authorization_denied(required_scope)
    scopes = value.get("scopes")
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
        raise _authorization_unavailable("OA scopes are malformed")
    if any(not isinstance(item, str) or not item for item in scopes):
        raise _authorization_unavailable("OA scopes are malformed")
    if required_scope not in scopes:
        raise _authorization_denied(required_scope)
    revision_hash = value.get("revision_hash")
    if (
        not isinstance(revision_hash, str)
        or _REVISION_HASH.fullmatch(revision_hash) is None
    ):
        raise _authorization_unavailable("OA revision hash is malformed")


def _authorization_denied(required_scope: str) -> EosLegalEntityError:
    return EosLegalEntityError(
        "EOS_LEGAL_ENTITY_AUTHORIZATION_DENIED",
        f"Fresh OA authority for {required_scope} is required",
        status_code=403,
    )


def _authorization_unavailable(detail: str) -> EosLegalEntityError:
    return EosLegalEntityError(
        "EOS_LEGAL_ENTITY_AUTHORIZATION_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )


def _wire(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item.isoformat() if isinstance(item, (date, datetime)) else item
        for key, item in value.items()
    }


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _code(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _CODE.fullmatch(normalized) is None:
        raise _invalid(field_name, "has invalid code syntax")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field_name, f"must contain 1..{maximum} characters")
    return normalized


def _currency(field_name: str, value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _CURRENCY.fullmatch(normalized) is None:
        raise _invalid(field_name, "must be a three-letter currency code")
    return normalized


def _timezone(value: object) -> str:
    normalized = _text("business_timezone", value, 64)
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise _invalid("business_timezone", "must be an IANA timezone") from exc
    return normalized


def _choice(field_name: str, value: object, choices: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in choices:
        raise _invalid(field_name, f"must be one of {sorted(choices)}")
    return normalized


def _date(field_name: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(field_name, "must be a date")
    return value


def _date_input(field_name: str, value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise _invalid(field_name, "must be an ISO date") from exc
    raise _invalid(field_name, "must be an ISO date")


def _optional_date(field_name: str, value: object) -> date | None:
    return None if value is None else _date(field_name, value)


def _optional_date_input(field_name: str, value: object) -> date | None:
    return None if value is None else _date_input(field_name, value)


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _hash_ref(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(field_name, "must be a SHA-256 hash reference") from exc


def _invalid(field_name: str, detail: str) -> EosLegalEntityError:
    return EosLegalEntityError(
        "EOS_LEGAL_ENTITY_INVALID", f"{field_name} {detail}", status_code=422
    )


def _binding_conflict(detail: str) -> EosLegalEntityError:
    return EosLegalEntityError(
        "EOS_PROJECT_COMPANY_BINDING_CONFLICT", detail, status_code=409
    )


def _persistence_error() -> EosLegalEntityError:
    return EosLegalEntityError(
        "EOS_LEGAL_ENTITY_PERSISTENCE_FAILED",
        "LegalEntity persistence is unavailable",
        status_code=503,
        retryable=True,
    )
