from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

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
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import EOS_METADATA
from .legal_entities import EOS_LEGAL_ENTITY_TABLE

EOS_ACCOUNTING_PERIOD_STATES = frozenset({"OPEN", "CLOSING", "CLOSED"})
FINANCE_PERIOD_READ_SCOPE = "finance:period:read"
FINANCE_PERIOD_CLOSE_SCOPE = "finance:period:close"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")

EOS_ACCOUNTING_PERIOD_TABLE = Table(
    "eos_accounting_period",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("period_id", Uuid(as_uuid=False), primary_key=True),
    Column("fiscal_year", Integer, nullable=False),
    Column("period_no", Integer, nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
    Column("state", String(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("close_proof_ref", String(71), nullable=True),
    Column("closed_at", DateTime(timezone=True), nullable=True),
    Column("ledger_cutoff_watermark", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_accounting_period_company",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "fiscal_year",
        "period_no",
        name="ux_eos_accounting_period_number",
    ),
    CheckConstraint("end_date >= start_date", name="ck_eos_accounting_period_dates"),
    CheckConstraint(
        "state IN ('OPEN', 'CLOSING', 'CLOSED')",
        name="ck_eos_accounting_period_state",
    ),
    CheckConstraint(
        "fiscal_year BETWEEN 1900 AND 9999 AND period_no BETWEEN 1 AND 99",
        name="ck_eos_accounting_period_number",
    ),
    CheckConstraint("version > 0", name="ck_eos_accounting_period_version"),
)
Index(
    "ix_eos_accounting_period_effective",
    EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id,
    EOS_ACCOUNTING_PERIOD_TABLE.c.company_id,
    EOS_ACCOUNTING_PERIOD_TABLE.c.state,
    EOS_ACCOUNTING_PERIOD_TABLE.c.start_date,
    EOS_ACCOUNTING_PERIOD_TABLE.c.end_date,
)


class EosAccountingPeriodError(RuntimeError):
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
class AccountingPeriodInput:
    tenant_id: str
    company_id: str
    period_id: str
    fiscal_year: int
    period_no: int
    start_date: date
    end_date: date


class SqlAlchemyEosAccountingPeriodRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_open_period(self, value: AccountingPeriodInput) -> dict[str, Any]:
        record = _period_record(value)
        try:
            with self._session_factory.begin() as session:
                self._lock_company_scope(
                    session,
                    tenant_id=record["tenant_id"],
                    company_id=record["company_id"],
                )
                existing = self._period_by_id(
                    session,
                    tenant_id=record["tenant_id"],
                    company_id=record["company_id"],
                    period_id=record["period_id"],
                )
                if existing is not None:
                    if _period_semantics(existing) == _period_semantics(record):
                        return _wire(existing)
                    raise _conflict("AccountingPeriod identity has different semantics")
                self._require_effective_company(session, record)
                overlap = session.execute(
                    select(EOS_ACCOUNTING_PERIOD_TABLE.c.period_id)
                    .where(
                        EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id == record["tenant_id"],
                        EOS_ACCOUNTING_PERIOD_TABLE.c.company_id
                        == record["company_id"],
                        EOS_ACCOUNTING_PERIOD_TABLE.c.end_date >= record["start_date"],
                        EOS_ACCOUNTING_PERIOD_TABLE.c.start_date <= record["end_date"],
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if overlap is not None:
                    raise _conflict(
                        "AccountingPeriod date range overlaps another period"
                    )
                session.execute(EOS_ACCOUNTING_PERIOD_TABLE.insert().values(**record))
        except EosAccountingPeriodError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "AccountingPeriod violates an identity or range guard"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return _wire(record)

    def get_period(
        self, *, tenant_id: str, company_id: str, period_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        company_id = _uuid("company_id", company_id)
        period_id = _uuid("period_id", period_id)
        try:
            with self._session_factory() as session:
                found = self._period_by_id(
                    session,
                    tenant_id=tenant_id,
                    company_id=company_id,
                    period_id=period_id,
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return _wire(found) if found is not None else None

    def lock_open_for_post(
        self,
        session: Session,
        *,
        tenant_id: str,
        company_id: str,
        posting_date: date,
    ) -> dict[str, Any]:
        """Lock the exact period inside the caller's posting transaction."""
        tenant_id = _scoped_id("tenant_id", tenant_id)
        company_id = _uuid("company_id", company_id)
        posting_date = _date("posting_date", posting_date)
        rows = (
            session.execute(
                select(EOS_ACCOUNTING_PERIOD_TABLE)
                .where(
                    EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id == tenant_id,
                    EOS_ACCOUNTING_PERIOD_TABLE.c.company_id == company_id,
                    EOS_ACCOUNTING_PERIOD_TABLE.c.start_date <= posting_date,
                    EOS_ACCOUNTING_PERIOD_TABLE.c.end_date >= posting_date,
                )
                .order_by(EOS_ACCOUNTING_PERIOD_TABLE.c.period_id)
                .with_for_update()
            )
            .mappings()
            .all()
        )
        if not rows:
            raise _not_found("No AccountingPeriod contains the posting date")
        if len(rows) != 1:
            raise _conflict("AccountingPeriod range is ambiguous")
        if rows[0]["state"] != "OPEN":
            raise EosAccountingPeriodError(
                "EOS_ACCOUNTING_PERIOD_NOT_OPEN",
                "Posting requires an OPEN AccountingPeriod",
                status_code=409,
            )
        return _wire(rows[0])

    def advance_close(
        self,
        *,
        tenant_id: str,
        company_id: str,
        period_id: str,
        expected_version: int,
        close_proof_ref: str | None = None,
        ledger_cutoff_watermark: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        company_id = _uuid("company_id", company_id)
        period_id = _uuid("period_id", period_id)
        expected_version = _positive_int("expected_version", expected_version)
        if (close_proof_ref is None) != (ledger_cutoff_watermark is None):
            raise _invalid(
                "close_proof_ref and ledger_cutoff_watermark must be supplied together"
            )
        proof = (
            None
            if close_proof_ref is None
            else _hash_ref("close_proof_ref", close_proof_ref)
        )
        watermark = (
            None
            if ledger_cutoff_watermark is None
            else _text("ledger_cutoff_watermark", ledger_cutoff_watermark, maximum=128)
        )
        try:
            with self._session_factory.begin() as session:
                period = (
                    session.execute(
                        select(EOS_ACCOUNTING_PERIOD_TABLE)
                        .where(
                            EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id == tenant_id,
                            EOS_ACCOUNTING_PERIOD_TABLE.c.company_id == company_id,
                            EOS_ACCOUNTING_PERIOD_TABLE.c.period_id == period_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if period is None:
                    raise _not_found("AccountingPeriod was not found")
                updated = self._next_close_state(
                    period,
                    expected_version=expected_version,
                    close_proof_ref=proof,
                    ledger_cutoff_watermark=watermark,
                )
                if updated is None:
                    return _wire(period)
                session.execute(
                    EOS_ACCOUNTING_PERIOD_TABLE.update()
                    .where(
                        EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id == tenant_id,
                        EOS_ACCOUNTING_PERIOD_TABLE.c.company_id == company_id,
                        EOS_ACCOUNTING_PERIOD_TABLE.c.period_id == period_id,
                    )
                    .values(**updated)
                )
                return _wire({**dict(period), **updated})
        except EosAccountingPeriodError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    @staticmethod
    def _next_close_state(
        period: Mapping[str, Any],
        *,
        expected_version: int,
        close_proof_ref: str | None,
        ledger_cutoff_watermark: str | None,
    ) -> dict[str, Any] | None:
        state = period["state"]
        current_version = period["version"]
        if state == "OPEN":
            if expected_version != current_version:
                raise _version_conflict()
            if close_proof_ref is not None:
                raise _conflict("AccountingPeriod must enter CLOSING before closure")
            return {
                "state": "CLOSING",
                "version": current_version + 1,
                "updated_at": datetime.now(UTC),
            }
        if state == "CLOSING":
            if close_proof_ref is None:
                if expected_version in {current_version, current_version - 1}:
                    return None
                raise _version_conflict()
            if expected_version != current_version:
                raise _version_conflict()
            now = datetime.now(UTC)
            return {
                "state": "CLOSED",
                "version": current_version + 1,
                "close_proof_ref": close_proof_ref,
                "ledger_cutoff_watermark": ledger_cutoff_watermark,
                "closed_at": now,
                "updated_at": now,
            }
        if (
            state == "CLOSED"
            and close_proof_ref == period["close_proof_ref"]
            and ledger_cutoff_watermark == period["ledger_cutoff_watermark"]
            and expected_version in {current_version, current_version - 1}
        ):
            return None
        raise _conflict("CLOSED AccountingPeriod cannot be reopened or changed")

    @staticmethod
    def _period_by_id(
        session: Session, *, tenant_id: str, company_id: str, period_id: str
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_ACCOUNTING_PERIOD_TABLE).where(
                    EOS_ACCOUNTING_PERIOD_TABLE.c.tenant_id == tenant_id,
                    EOS_ACCOUNTING_PERIOD_TABLE.c.company_id == company_id,
                    EOS_ACCOUNTING_PERIOD_TABLE.c.period_id == period_id,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _lock_company_scope(
        session: Session, *, tenant_id: str, company_id: str
    ) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"{tenant_id}:{company_id}"},
            )

    @staticmethod
    def _require_effective_company(session: Session, record: Mapping[str, Any]) -> None:
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
            raise _not_found("LegalEntity was not found in tenant scope")
        if (
            company["status"] != "ACTIVE"
            or company["effective_from"] > record["start_date"]
        ):
            raise _conflict("LegalEntity is not active at AccountingPeriod start")


class EosAccountingPeriodService:
    def __init__(
        self,
        repository: SqlAlchemyEosAccountingPeriodRepository,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source

    def get_period(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        company_id: str,
        period_id: str,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=FINANCE_PERIOD_READ_SCOPE,
        )
        found = self._repository.get_period(
            tenant_id=tenant_id,
            company_id=company_id,
            period_id=period_id,
        )
        if found is None:
            raise _not_found("AccountingPeriod was not found in tenant/company scope")
        return found

    def advance_close(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        period_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id("requester_subject_id", requester_subject_id)
        if not isinstance(payload, Mapping):
            raise _invalid("payload must be an object")
        allowed_fields = {
            "company_id",
            "expected_version",
            "close_proof_ref",
            "ledger_cutoff_watermark",
        }
        unknown_fields = sorted(
            str(field) for field in payload if field not in allowed_fields
        )
        if unknown_fields:
            raise _invalid(
                "payload contains unsupported fields: " + ", ".join(unknown_fields)
            )
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=FINANCE_PERIOD_CLOSE_SCOPE,
        )
        return self._repository.advance_close(
            tenant_id=tenant_id,
            company_id=_uuid("company_id", payload.get("company_id")),
            period_id=period_id,
            expected_version=_positive_int(
                "expected_version", payload.get("expected_version")
            ),
            close_proof_ref=payload.get("close_proof_ref"),
            ledger_cutoff_watermark=payload.get("ledger_cutoff_watermark"),
        )

    def _authorize(
        self, *, tenant_id: str, subject_id: str, required_scope: str
    ) -> None:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied(required_scope) from exc
        except Exception as exc:
            raise _authority_unavailable() from exc
        if not isinstance(value, Mapping):
            raise _authority_unavailable()
        if value.get("active") is not True:
            raise _denied(required_scope)
        if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
            raise _denied(required_scope)
        scopes = value.get("scopes")
        if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
            raise _authority_unavailable()
        if any(not isinstance(item, str) or not item for item in scopes):
            raise _authority_unavailable()
        if required_scope not in scopes:
            raise _denied(required_scope)
        revision_hash = value.get("revision_hash")
        if (
            not isinstance(revision_hash, str)
            or _REVISION_HASH.fullmatch(revision_hash) is None
        ):
            raise _authority_unavailable()


def _period_record(value: AccountingPeriodInput) -> dict[str, Any]:
    if not isinstance(value, AccountingPeriodInput):
        raise _invalid("value must be AccountingPeriodInput")
    start_date = _date("start_date", value.start_date)
    end_date = _date("end_date", value.end_date)
    if end_date < start_date:
        raise _invalid("end_date must be on or after start_date")
    now = datetime.now(UTC)
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "company_id": _uuid("company_id", value.company_id),
        "period_id": _uuid("period_id", value.period_id),
        "fiscal_year": _bounded_int("fiscal_year", value.fiscal_year, 1900, 9999),
        "period_no": _bounded_int("period_no", value.period_no, 1, 99),
        "start_date": start_date,
        "end_date": end_date,
        "state": "OPEN",
        "version": 1,
        "close_proof_ref": None,
        "closed_at": None,
        "ledger_cutoff_watermark": None,
        "created_at": now,
        "updated_at": now,
    }


def _period_semantics(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        value[field]
        for field in (
            "tenant_id",
            "company_id",
            "period_id",
            "fiscal_year",
            "period_no",
            "start_date",
            "end_date",
        )
    )


def _wire(value: Mapping[str, Any]) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, datetime):
            aware = item.replace(tzinfo=UTC) if item.tzinfo is None else item
            projection[key] = aware.astimezone(UTC).isoformat()
        elif isinstance(item, date):
            projection[key] = item.isoformat()
        else:
            projection[key] = item
    return projection


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} has invalid stable-reference syntax")
    return normalized


def _date(field_name: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(f"{field_name} must be a date")
    return value


def _positive_int(field_name: str, value: object) -> int:
    return _bounded_int(field_name, value, 1, 2**31 - 1)


def _bounded_int(field_name: str, value: object, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise _invalid(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _hash_ref(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be a SHA-256 hash reference") from exc


def _text(field_name: str, value: object, *, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(f"{field_name} must contain 1..{maximum} characters")
    return normalized


def _invalid(detail: str) -> EosAccountingPeriodError:
    return EosAccountingPeriodError(
        "EOS_ACCOUNTING_PERIOD_INVALID", detail, status_code=422
    )


def _not_found(detail: str) -> EosAccountingPeriodError:
    return EosAccountingPeriodError(
        "EOS_ACCOUNTING_PERIOD_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosAccountingPeriodError:
    return EosAccountingPeriodError(
        "EOS_ACCOUNTING_PERIOD_CONFLICT", detail, status_code=409
    )


def _version_conflict() -> EosAccountingPeriodError:
    return _conflict("AccountingPeriod version changed")


def _denied(required_scope: str) -> EosAccountingPeriodError:
    return EosAccountingPeriodError(
        "EOS_ACCOUNTING_PERIOD_AUTHORIZATION_DENIED",
        f"Fresh OA authority for {required_scope} is required",
        status_code=403,
    )


def _authority_unavailable() -> EosAccountingPeriodError:
    return EosAccountingPeriodError(
        "EOS_ACCOUNTING_PERIOD_AUTHORITY_UNAVAILABLE",
        "OA accounting-period authority is unavailable or malformed",
        status_code=503,
        retryable=True,
    )


def _unavailable() -> EosAccountingPeriodError:
    return EosAccountingPeriodError(
        "EOS_ACCOUNTING_PERIOD_PERSISTENCE_UNAVAILABLE",
        "AccountingPeriod persistence is unavailable",
        status_code=503,
        retryable=True,
    )
