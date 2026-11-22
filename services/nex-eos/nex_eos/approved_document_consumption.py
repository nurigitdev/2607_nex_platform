from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .approved_documents import EOS_APPROVED_DOCUMENT_TABLE
from .business_transactions import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_METADATA,
    EosBusinessOperationError,
)

APPROVED_DOCUMENT_CONSUMPTION_STATES = frozenset({"COMMITTED"})

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE = Table(
    "eos_approved_document_consumption",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("consumption_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("envelope_id", Uuid(as_uuid=False), nullable=False),
    Column("source_document_line_ref", String(256), nullable=False),
    Column("supplier_invoice_ref", String(256), nullable=True),
    Column("payroll_period_ref", String(256), nullable=True),
    Column("source_identity_hash", String(71), nullable=False),
    Column("candidate_revision_id", Uuid(as_uuid=False), nullable=False),
    Column("posted_journal_id", Uuid(as_uuid=False), nullable=False),
    Column("consumed_amount", Numeric(20, 4), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("state", String(16), nullable=False),
    Column("operation_id", Uuid(as_uuid=False), nullable=False),
    Column("posted_at", DateTime(timezone=True), nullable=False),
    Column("reversed_journal_ref", Uuid(as_uuid=False), nullable=True),
    Column("consumption_hash", String(71), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "candidate_revision_id",
        name="ux_eos_doc_cons_candidate",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "envelope_id",
        "source_identity_hash",
        name="ux_eos_doc_cons_source",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "envelope_id"),
        (
            "eos_approved_document_envelope.tenant_id",
            "eos_approved_document_envelope.envelope_id",
        ),
        name="fk_eos_doc_cons_envelope",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_doc_cons_operation",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "candidate_revision_id"),
        (
            "eos_voucher_candidate_revision.tenant_id",
            "eos_voucher_candidate_revision.revision_id",
        ),
        name="fk_eos_doc_cons_candidate_revision",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "posted_journal_id"),
        (
            "eos_journal_header.tenant_id",
            "eos_journal_header.company_id",
            "eos_journal_header.journal_id",
        ),
        name="fk_eos_doc_cons_journal",
        deferrable=True,
        initially="DEFERRED",
    ),
    CheckConstraint("consumed_amount > 0", name="ck_eos_doc_cons_amount"),
    CheckConstraint("state = 'COMMITTED'", name="ck_eos_doc_cons_state"),
)
Index(
    "ix_eos_doc_cons_envelope",
    EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.tenant_id,
    EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.envelope_id,
    EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.state,
)


class EosApprovedDocumentConsumptionError(EosBusinessOperationError):
    pass


@dataclass(frozen=True)
class ApprovedDocumentConsumptionInput:
    tenant_id: str
    consumption_id: str
    company_id: str
    envelope_id: str
    source_document_line_ref: str
    candidate_revision_id: str
    posted_journal_id: str
    consumed_amount: Decimal
    currency: str
    operation_id: str
    supplier_invoice_ref: str | None = None
    payroll_period_ref: str | None = None
    reversed_journal_ref: str | None = None


class EosApprovedDocumentConsumptionAdapter:
    """Consumes an allowance only inside an existing EOS business transaction."""

    def __init__(self, *, clock=None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def consume_in_session(
        self,
        session: Session | None,
        value: ApprovedDocumentConsumptionInput,
    ) -> tuple[dict[str, Any], bool]:
        if session is None:
            raise _invalid(
                "session", "must be the active EOS business transaction session"
            )
        semantics = _consumption_semantics(value)
        consumption_hash = approved_document_consumption_hash(semantics)
        now = _aware_datetime("clock", self._clock())
        try:
            envelope = self._lock_envelope(session, semantics)
            self._require_pending_operation(session, semantics)
            self._require_usable_envelope(envelope, semantics=semantics, now=now)

            existing = self._load_existing(session, semantics)
            if existing is not None:
                if existing["consumption_hash"] != consumption_hash:
                    raise _conflict(
                        "Candidate revision or consumption identity is already bound "
                        "to different immutable semantics"
                    )
                total = self._consumed_total(session, semantics)
                return _projection(existing, envelope=envelope, total=total), False

            duplicate_source = (
                session.execute(
                    select(EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE).where(
                        EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.tenant_id
                        == semantics["tenant_id"],
                        EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.company_id
                        == semantics["company_id"],
                        EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.envelope_id
                        == semantics["envelope_id"],
                        EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.source_identity_hash
                        == semantics["source_identity_hash"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            if duplicate_source is not None:
                raise _conflict(
                    "Approved source document line or supplier/payroll identity was "
                    "already consumed"
                )

            total = self._consumed_total(session, semantics)
            approved = _decimal(envelope["approved_amount"])
            if total + semantics["consumed_amount"] > approved:
                raise EosApprovedDocumentConsumptionError(
                    "EOS_APPROVED_DOCUMENT_ALLOWANCE_EXCEEDED",
                    "Consumption would exceed the approved original-currency allowance",
                    status_code=409,
                )
            record = {
                **semantics,
                "state": "COMMITTED",
                "posted_at": now,
                "consumption_hash": consumption_hash,
            }
            session.execute(
                EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.insert().values(**record)
            )
            return (
                _projection(
                    record,
                    envelope=envelope,
                    total=total + semantics["consumed_amount"],
                ),
                True,
            )
        except EosApprovedDocumentConsumptionError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Consumption identity, candidate revision, or source identity is "
                "already committed"
            ) from exc
        except SQLAlchemyError as exc:
            raise EosApprovedDocumentConsumptionError(
                "EOS_APPROVED_DOCUMENT_CONSUMPTION_UNAVAILABLE",
                "Approved document consumption persistence is unavailable",
                status_code=503,
                retryable=True,
            ) from exc

    @staticmethod
    def _lock_envelope(
        session: Session, semantics: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        envelope = (
            session.execute(
                select(EOS_APPROVED_DOCUMENT_TABLE)
                .where(
                    EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id == semantics["tenant_id"],
                    EOS_APPROVED_DOCUMENT_TABLE.c.envelope_id
                    == semantics["envelope_id"],
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if envelope is None:
            raise EosApprovedDocumentConsumptionError(
                "EOS_APPROVED_DOCUMENT_CONSUMPTION_NOT_FOUND",
                "Approved document envelope was not found in tenant scope",
                status_code=404,
            )
        return envelope

    @staticmethod
    def _require_pending_operation(
        session: Session, semantics: Mapping[str, Any]
    ) -> None:
        state = session.execute(
            select(EOS_BUSINESS_OPERATION_TABLE.c.commit_state).where(
                EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == semantics["tenant_id"],
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == semantics["operation_id"],
            )
        ).scalar_one_or_none()
        if state != "PENDING":
            raise _conflict(
                "Consumption requires the matching pending EOS business operation"
            )

    @staticmethod
    def _require_usable_envelope(
        envelope: Mapping[str, Any],
        *,
        semantics: Mapping[str, Any],
        now: datetime,
    ) -> None:
        if str(envelope["company_id"]) != semantics["company_id"]:
            raise _conflict("Approved document belongs to a different company")
        if envelope["approved_currency"] != semantics["currency"]:
            raise EosApprovedDocumentConsumptionError(
                "EOS_APPROVED_DOCUMENT_CURRENCY_MISMATCH",
                "Consumption currency must match the approved original currency",
                status_code=409,
            )
        valid_from = _aware_datetime("valid_from", envelope["valid_from"])
        valid_until = (
            _aware_datetime("valid_until", envelope["valid_until"])
            if envelope["valid_until"] is not None
            else None
        )
        if (
            envelope["state"] != "ACTIVE"
            or now < valid_from
            or (valid_until is not None and now >= valid_until)
        ):
            raise _conflict("Approved document is not active and valid for consumption")

    @staticmethod
    def _load_existing(
        session: Session, semantics: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE).where(
                    EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.tenant_id
                    == semantics["tenant_id"],
                    (
                        EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.consumption_id
                        == semantics["consumption_id"]
                    )
                    | (
                        (
                            EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.company_id
                            == semantics["company_id"]
                        )
                        & (
                            EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.candidate_revision_id
                            == semantics["candidate_revision_id"]
                        )
                    ),
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _consumed_total(session: Session, semantics: Mapping[str, Any]) -> Decimal:
        total = session.execute(
            select(
                func.sum(EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.consumed_amount)
            ).where(
                EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.tenant_id
                == semantics["tenant_id"],
                EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.envelope_id
                == semantics["envelope_id"],
                EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.state == "COMMITTED",
            )
        ).scalar_one()
        return _decimal(total or 0)


def approved_document_source_identity_hash(
    *,
    source_document_line_ref: str,
    supplier_invoice_ref: str | None,
    payroll_period_ref: str | None,
) -> str:
    return semantic_sha256_hash_ref(
        {
            "schema_version": "eos.approved-document-source-identity.v1",
            "source_document_line_ref": source_document_line_ref,
            "supplier_invoice_ref": supplier_invoice_ref or "",
            "payroll_period_ref": payroll_period_ref or "",
        }
    )


def approved_document_consumption_hash(semantics: Mapping[str, Any]) -> str:
    canonical = dict(semantics)
    if "consumed_amount" in canonical:
        canonical["consumed_amount"] = _decimal_text(canonical["consumed_amount"])
    return semantic_sha256_hash_ref(
        {
            "schema_version": "eos.approved-document-consumption.v1",
            **canonical,
        }
    )


def _consumption_semantics(
    value: ApprovedDocumentConsumptionInput,
) -> dict[str, Any]:
    source_document_line_ref = _reference(
        "source_document_line_ref", value.source_document_line_ref, required=True
    )
    supplier_invoice_ref = _reference(
        "supplier_invoice_ref", value.supplier_invoice_ref, required=False
    )
    payroll_period_ref = _reference(
        "payroll_period_ref", value.payroll_period_ref, required=False
    )
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id, 128),
        "consumption_id": _uuid("consumption_id", value.consumption_id),
        "company_id": _uuid("company_id", value.company_id),
        "envelope_id": _uuid("envelope_id", value.envelope_id),
        "source_document_line_ref": source_document_line_ref,
        "supplier_invoice_ref": supplier_invoice_ref,
        "payroll_period_ref": payroll_period_ref,
        "source_identity_hash": approved_document_source_identity_hash(
            source_document_line_ref=source_document_line_ref,
            supplier_invoice_ref=supplier_invoice_ref,
            payroll_period_ref=payroll_period_ref,
        ),
        "candidate_revision_id": _uuid(
            "candidate_revision_id", value.candidate_revision_id
        ),
        "posted_journal_id": _uuid("posted_journal_id", value.posted_journal_id),
        "consumed_amount": _positive_decimal("consumed_amount", value.consumed_amount),
        "currency": _currency("currency", value.currency),
        "operation_id": _uuid("operation_id", value.operation_id),
        "reversed_journal_ref": (
            _uuid("reversed_journal_ref", value.reversed_journal_ref)
            if value.reversed_journal_ref is not None
            else None
        ),
    }


def _projection(
    value: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any],
    total: Decimal,
) -> dict[str, Any]:
    approved = _decimal(envelope["approved_amount"])
    return {
        "schema_version": "eos_approved_document_consumption.v1",
        "tenant_id": value["tenant_id"],
        "consumption_id": str(value["consumption_id"]),
        "company_id": str(value["company_id"]),
        "envelope_id": str(value["envelope_id"]),
        "source_document_line_ref": value["source_document_line_ref"],
        "supplier_invoice_ref": value["supplier_invoice_ref"],
        "payroll_period_ref": value["payroll_period_ref"],
        "source_identity_hash": value["source_identity_hash"],
        "candidate_revision_id": str(value["candidate_revision_id"]),
        "posted_journal_id": str(value["posted_journal_id"]),
        "consumed_amount": _decimal_text(value["consumed_amount"]),
        "currency": value["currency"],
        "state": value["state"],
        "operation_id": str(value["operation_id"]),
        "posted_at": _timestamp(value["posted_at"]),
        "reversed_journal_ref": (
            str(value["reversed_journal_ref"])
            if value["reversed_journal_ref"] is not None
            else None
        ),
        "consumption_hash": value["consumption_hash"],
        "approved_amount": _decimal_text(approved),
        "consumed_total": _decimal_text(total),
        "remaining_amount": _decimal_text(approved - total),
    }


def _scoped_id(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or not _SCOPED_ID.fullmatch(value)
    ):
        raise _invalid(field, "must be a stable scoped identifier")
    return value


def _reference(field: str, value: object, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise _invalid(field, "must be a stable non-blank reference")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field, "must be a UUID") from exc


def _positive_decimal(field: str, value: object) -> Decimal:
    try:
        admitted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid(field, "must be a decimal") from exc
    if not admitted.is_finite() or admitted <= 0 or admitted.as_tuple().exponent < -4:
        raise _invalid(field, "must be positive with at most four decimal places")
    try:
        return admitted.quantize(Decimal("0.0001"))
    except InvalidOperation as exc:
        raise _invalid(field, "must fit the approved monetary precision") from exc


def _currency(field: str, value: object) -> str:
    if not isinstance(value, str) or not _CURRENCY.fullmatch(value):
        raise _invalid(field, "must be an uppercase ISO 4217 code")
    return value


def _aware_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise _invalid(field, "must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal(value: object) -> Decimal:
    try:
        admitted = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError) as exc:
        raise _conflict("Stored approved-document amount is invalid") from exc
    if not admitted.is_finite() or admitted < 0:
        raise _conflict("Stored approved-document amount is invalid")
    return admitted


def _decimal_text(value: object) -> str:
    return format(_decimal(value), "f")


def _timestamp(value: object) -> str:
    return _aware_datetime("timestamp", value).isoformat().replace("+00:00", "Z")


def _invalid(field: str, detail: str) -> EosApprovedDocumentConsumptionError:
    return EosApprovedDocumentConsumptionError(
        "EOS_APPROVED_DOCUMENT_CONSUMPTION_INVALID",
        f"{field}: {detail}",
        status_code=422,
    )


def _conflict(detail: str) -> EosApprovedDocumentConsumptionError:
    return EosApprovedDocumentConsumptionError(
        "EOS_APPROVED_DOCUMENT_CONSUMPTION_CONFLICT",
        detail,
        status_code=409,
    )
