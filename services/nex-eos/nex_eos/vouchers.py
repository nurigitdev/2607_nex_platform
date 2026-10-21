from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime import build_unit_of_work
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .accounts import EOS_ACCOUNT_TABLE
from .business_transactions import EOS_METADATA
from .projects import EOS_PROJECT_TABLE

EOS_VOUCHER_DRAFT_STATES = frozenset({"DRAFT"})
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REF_TYPE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_MONEY_QUANTUM = Decimal("0.01")
_MAX_MONEY = Decimal("999999999999999999.99")

EOS_VOUCHER_DRAFT_TABLE = Table(
    "eos_voucher_draft",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("voucher_id", Uuid(as_uuid=False), primary_key=True),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("voucher_type", String(32), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("transaction_date", Date, nullable=False),
    Column("description", String(2000), nullable=False),
    Column("requester_ref_type", String(64), nullable=False),
    Column("requester_id", String(128), nullable=False),
    Column("source_ref_type", String(64), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("state", String(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_voucher_project",
    ),
)

EOS_VOUCHER_DRAFT_LINE_TABLE = Table(
    "eos_voucher_draft_line",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("voucher_id", Uuid(as_uuid=False), primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("account_id", Uuid(as_uuid=False), nullable=False),
    Column("signed_amount", Numeric(20, 2), nullable=False),
    Column("economic_category", String(32), nullable=False),
    Column("description", String(1000), nullable=True),
    Column("evidence_refs", JSON, nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "voucher_id"),
        ("eos_voucher_draft.tenant_id", "eos_voucher_draft.voucher_id"),
        name="fk_eos_voucher_line_draft",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_voucher_line_account",
    ),
    UniqueConstraint(
        "tenant_id", "voucher_id", "account_id", "line_no",
        name="ux_eos_voucher_line_account",
    ),
    CheckConstraint("line_no > 0", name="ck_eos_voucher_line_no"),
    CheckConstraint("signed_amount <> 0", name="ck_eos_voucher_line_amount"),
)


class EosVoucherError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class VoucherLineInput:
    account_id: str
    signed_amount: Decimal
    economic_category: str
    description: str | None = None
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class VoucherDraftInput:
    tenant_id: str
    voucher_id: str
    project_id: str
    transaction_date: date
    description: str
    requester_ref: Mapping[str, Any]
    source_ref: Mapping[str, Any]
    lines: Sequence[VoucherLineInput]
    voucher_type: str = "GENERAL"
    currency: str = "KRW"
    state: str = "DRAFT"
    version: int = 1


class SqlAlchemyEosVoucherRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_draft(self, value: VoucherDraftInput) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", value.tenant_id)
        voucher_id = _uuid("voucher_id", value.voucher_id)
        project_id = _uuid("project_id", value.project_id)
        transaction_date = _date("transaction_date", value.transaction_date)
        requester_type, requester_id = _entity_ref(
            "requester_ref", value.requester_ref
        )
        source_type, source_id = _entity_ref("source_ref", value.source_ref)
        state = _choice("state", value.state, EOS_VOUCHER_DRAFT_STATES)
        version = _positive_int("version", value.version)
        if version != 1:
            raise _invalid("version", "must start at 1")
        lines = _lines(value.lines)
        if sum((line["signed_amount"] for line in lines), Decimal("0.00")) != 0:
            raise EosVoucherError(
                "EOS_VOUCHER_UNBALANCED",
                "Voucher line signed amounts must sum to zero",
                status_code=422,
            )
        now = datetime.now(UTC)
        draft = {
            "tenant_id": tenant_id,
            "voucher_id": voucher_id,
            "project_id": project_id,
            "voucher_type": _code("voucher_type", value.voucher_type),
            "currency": _currency(value.currency),
            "transaction_date": transaction_date,
            "description": _text("description", value.description, 2000),
            "requester_ref_type": requester_type,
            "requester_id": requester_id,
            "source_ref_type": source_type,
            "source_id": source_id,
            "state": state,
            "version": version,
            "created_at": now,
            "updated_at": now,
        }
        line_records = [
            {"tenant_id": tenant_id, "voucher_id": voucher_id, **line}
            for line in lines
        ]

        try:
            with build_unit_of_work(self._session_factory) as transaction:
                self._require_effective_project(
                    transaction.db,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    effective_at=transaction_date,
                )
                for line in line_records:
                    self._require_effective_account(
                        transaction.db,
                        tenant_id=tenant_id,
                        account_id=line["account_id"],
                        effective_at=transaction_date,
                    )
                transaction.db.execute(EOS_VOUCHER_DRAFT_TABLE.insert().values(**draft))
                transaction.db.execute(EOS_VOUCHER_DRAFT_LINE_TABLE.insert(), line_records)
        except EosVoucherError:
            raise
        except IntegrityError as exc:
            raise EosVoucherError(
                "EOS_VOUCHER_CONFLICT",
                "Voucher Draft identity already exists in tenant scope",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return {**draft, "lines": [dict(line) for line in line_records]}

    def get_draft(
        self, *, tenant_id: str, voucher_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        voucher_id = _uuid("voucher_id", voucher_id)
        try:
            with self._session_factory() as session:
                draft = session.execute(
                    select(EOS_VOUCHER_DRAFT_TABLE).where(
                        EOS_VOUCHER_DRAFT_TABLE.c.tenant_id == tenant_id,
                        EOS_VOUCHER_DRAFT_TABLE.c.voucher_id == voucher_id,
                    )
                ).mappings().one_or_none()
                if draft is None:
                    return None
                lines = session.execute(
                    select(EOS_VOUCHER_DRAFT_LINE_TABLE)
                    .where(
                        EOS_VOUCHER_DRAFT_LINE_TABLE.c.tenant_id == tenant_id,
                        EOS_VOUCHER_DRAFT_LINE_TABLE.c.voucher_id == voucher_id,
                    )
                    .order_by(EOS_VOUCHER_DRAFT_LINE_TABLE.c.line_no)
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return {**dict(draft), "lines": [dict(line) for line in lines]}

    @staticmethod
    def _require_effective_project(
        session: Session, *, tenant_id: str, project_id: str, effective_at: date
    ) -> None:
        row = session.execute(
            select(
                EOS_PROJECT_TABLE.c.status,
                EOS_PROJECT_TABLE.c.start_date,
                EOS_PROJECT_TABLE.c.end_date,
            ).where(
                EOS_PROJECT_TABLE.c.tenant_id == tenant_id,
                EOS_PROJECT_TABLE.c.project_id == project_id,
            )
        ).mappings().one_or_none()
        if row is None:
            raise EosVoucherError(
                "EOS_VOUCHER_PROJECT_NOT_FOUND",
                "Project was not found in tenant scope",
                status_code=422,
            )
        if (
            row["status"] != "ACTIVE"
            or (row["start_date"] is not None and row["start_date"] > effective_at)
            or (row["end_date"] is not None and row["end_date"] < effective_at)
        ):
            raise EosVoucherError(
                "EOS_VOUCHER_PROJECT_NOT_EFFECTIVE",
                "Project is not effective for the transaction date",
                status_code=422,
            )

    @staticmethod
    def _require_effective_account(
        session: Session, *, tenant_id: str, account_id: str, effective_at: date
    ) -> None:
        row = session.execute(
            select(
                EOS_ACCOUNT_TABLE.c.status,
                EOS_ACCOUNT_TABLE.c.effective_from,
                EOS_ACCOUNT_TABLE.c.effective_until,
            ).where(
                EOS_ACCOUNT_TABLE.c.tenant_id == tenant_id,
                EOS_ACCOUNT_TABLE.c.account_id == account_id,
            )
        ).mappings().one_or_none()
        if row is None:
            raise EosVoucherError(
                "EOS_VOUCHER_ACCOUNT_NOT_FOUND",
                "Account was not found in tenant scope",
                status_code=422,
            )
        if (
            row["status"] != "ACTIVE"
            or row["effective_from"] > effective_at
            or (
                row["effective_until"] is not None
                and row["effective_until"] <= effective_at
            )
        ):
            raise EosVoucherError(
                "EOS_VOUCHER_ACCOUNT_NOT_EFFECTIVE",
                "Account is not effective for the transaction date",
                status_code=422,
            )


def _lines(values: Sequence[VoucherLineInput]) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise _invalid("lines", "must contain at least one line")
    records = []
    for line_no, value in enumerate(values, start=1):
        if not isinstance(value, VoucherLineInput):
            raise _invalid("lines", "must contain VoucherLineInput values")
        records.append(
            {
                "line_no": line_no,
                "account_id": _uuid("account_id", value.account_id),
                "signed_amount": _money(value.signed_amount),
                "economic_category": _code(
                    "economic_category", value.economic_category
                ),
                "description": (
                    _text("line.description", value.description, 1000)
                    if value.description is not None
                    else None
                ),
                "evidence_refs": _evidence_refs(value.evidence_refs),
            }
        )
    return records


def _money(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value == 0:
        raise _invalid("signed_amount", "must be a finite non-zero Decimal")
    try:
        normalized = value.quantize(_MONEY_QUANTUM)
    except InvalidOperation as exc:
        raise _invalid("signed_amount", "is outside Decimal(20,2)") from exc
    if normalized != value or abs(normalized) > _MAX_MONEY:
        raise _invalid("signed_amount", "must fit Decimal(20,2) exactly")
    return normalized


def _evidence_refs(values: object) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("evidence_refs", "must be a sequence")
    if len(values) > 20:
        raise _invalid("evidence_refs", "must contain at most 20 refs")
    return [_scoped_id("evidence_ref", value) for value in values]


def _entity_ref(field_name: str, value: object) -> tuple[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"type", "id"}:
        raise _invalid(field_name, "must contain exactly type and id")
    ref_type = str(value["type"]).strip()
    if not _REF_TYPE.fullmatch(ref_type):
        raise _invalid(field_name, "has invalid type syntax")
    return ref_type, _scoped_id(f"{field_name}.id", value["id"])


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
    normalized = str(value).strip().upper() if value is not None else ""
    if not _CODE.fullmatch(normalized):
        raise _invalid(field_name, "has invalid code syntax")
    return normalized


def _currency(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if not _CURRENCY.fullmatch(normalized):
        raise _invalid("currency", "must be a three-letter code")
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


def _date(field_name: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(field_name, "must be a date")
    return value


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _invalid(field_name: str, detail: str) -> EosVoucherError:
    return EosVoucherError(
        "EOS_VOUCHER_INVALID", f"{field_name} {detail}", status_code=422
    )


def _persistence_error() -> EosVoucherError:
    return EosVoucherError(
        "EOS_VOUCHER_PERSISTENCE_FAILED",
        "Voucher persistence is unavailable",
        status_code=503,
    )
