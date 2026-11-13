from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
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

from .business_transactions import EOS_METADATA

JOURNAL_GET_OPERATION = "FINANCE.JOURNAL.GET"
JOURNAL_VERIFY_OPERATION = "FINANCE.JOURNAL.VERIFY"
POSTED_JOURNAL_SCHEMA = "eos_posted_journal.v1"
JOURNAL_VERIFICATION_SCHEMA = "eos_journal_verification.v1"

_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_JOURNAL_KINDS = frozenset({"STANDARD", "ADJUSTMENT", "REVERSAL"})

EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE = Table(
    "eos_accounting_approval_acceptance",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("acceptance_id", Uuid(as_uuid=False), primary_key=True),
    Column("candidate_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_revision", Integer, nullable=False),
    Column("candidate_hash", String(71), nullable=False),
    Column("accounting_evidence_id", Uuid(as_uuid=False), nullable=False),
    Column("approval_case_id", Uuid(as_uuid=False), nullable=False),
    Column("purpose", String(32), nullable=False),
    Column("proof_hash", String(71), nullable=False),
    Column("wc_decision_id", Uuid(as_uuid=False), nullable=False),
    Column("oa_decision_ref", String(256), nullable=False),
    Column("oa_decision_revision_hash", String(71), nullable=False),
    Column("accepted_by", String(128), nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=False),
    Column("journal_id", Uuid(as_uuid=False), nullable=False),
    Column("acceptance_hash", String(71), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "candidate_id",
        "candidate_revision",
        name="ux_eos_acct_accept_candidate",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "proof_hash",
        name="ux_eos_acct_accept_proof",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "journal_id",
        name="ux_eos_acct_accept_journal",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "candidate_id", "candidate_revision"),
        (
            "eos_voucher_candidate_revision.tenant_id",
            "eos_voucher_candidate_revision.candidate_id",
            "eos_voucher_candidate_revision.revision_no",
        ),
        name="fk_eos_acct_accept_candidate",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "accounting_evidence_id"),
        (
            "eos_accounting_approval_evidence.tenant_id",
            "eos_accounting_approval_evidence.evidence_id",
        ),
        name="fk_eos_acct_accept_evidence",
    ),
    CheckConstraint(
        "purpose = 'ACCOUNTING_POSTING'", name="ck_eos_acct_accept_purpose"
    ),
)

EOS_JOURNAL_HEADER_TABLE = Table(
    "eos_journal_header",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("journal_id", Uuid(as_uuid=False), primary_key=True),
    Column("candidate_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_revision", Integer, nullable=False),
    Column("candidate_hash", String(71), nullable=False),
    Column("period_id", Uuid(as_uuid=False), nullable=False),
    Column("posting_sequence", BigInteger, nullable=False),
    Column("journal_no", String(64), nullable=False),
    Column("state", String(16), nullable=False),
    Column("transaction_kind", String(16), nullable=False),
    Column("recognition_date", Date, nullable=False),
    Column("posting_date", Date, nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("source_document_id", Uuid(as_uuid=False), nullable=False),
    Column("source_document_revision", Integer, nullable=False),
    Column("source_document_hash", String(71), nullable=False),
    Column("accounting_acceptance_id", Uuid(as_uuid=False), nullable=False),
    Column("posting_rule_release_hash", String(71), nullable=False),
    Column("fx_rate_set_hash", String(71), nullable=False),
    Column("reversal_of_journal_id", Uuid(as_uuid=False), nullable=True),
    Column("business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("payload_hash", String(71), nullable=False),
    Column("line_count", Integer, nullable=False),
    Column("total_debit_functional", Numeric(20, 4), nullable=False),
    Column("total_credit_functional", Numeric(20, 4), nullable=False),
    Column("journal_hash", String(71), nullable=False),
    Column("posted_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "candidate_id",
        "candidate_revision",
        name="ux_eos_journal_candidate",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "period_id",
        "posting_sequence",
        name="ux_eos_journal_sequence",
    ),
    UniqueConstraint("tenant_id", "company_id", "journal_no", name="ux_eos_journal_no"),
    UniqueConstraint(
        "tenant_id", "business_operation_id", name="ux_eos_journal_operation"
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "idempotency_key",
        name="ux_eos_journal_idempotency",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "candidate_id", "candidate_revision"),
        (
            "eos_voucher_candidate_revision.tenant_id",
            "eos_voucher_candidate_revision.candidate_id",
            "eos_voucher_candidate_revision.revision_no",
        ),
        name="fk_eos_journal_candidate",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "period_id"),
        (
            "eos_accounting_period.tenant_id",
            "eos_accounting_period.company_id",
            "eos_accounting_period.period_id",
        ),
        name="fk_eos_journal_period",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "source_document_id"),
        (
            "eos_approved_document_envelope.tenant_id",
            "eos_approved_document_envelope.envelope_id",
        ),
        name="fk_eos_journal_document",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "accounting_acceptance_id"),
        (
            "eos_accounting_approval_acceptance.tenant_id",
            "eos_accounting_approval_acceptance.company_id",
            "eos_accounting_approval_acceptance.acceptance_id",
        ),
        name="fk_eos_journal_acceptance",
        deferrable=True,
        initially="DEFERRED",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "reversal_of_journal_id"),
        (
            "eos_journal_header.tenant_id",
            "eos_journal_header.company_id",
            "eos_journal_header.journal_id",
        ),
        name="fk_eos_journal_reversal",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_journal_operation",
    ),
    CheckConstraint("state = 'POSTED'", name="ck_eos_journal_state"),
)

EOS_JOURNAL_LINE_TABLE = Table(
    "eos_journal_line",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("journal_id", Uuid(as_uuid=False), primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("candidate_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_revision", Integer, nullable=False),
    Column("candidate_source_line_no", Integer, nullable=False),
    Column("account_id", Uuid(as_uuid=False), nullable=False),
    Column("account_code_snapshot", String(64), nullable=False),
    Column("account_name_snapshot", String(256), nullable=False),
    Column("account_policy_id", Uuid(as_uuid=False), nullable=False),
    Column("account_policy_release_hash", String(71), nullable=False),
    Column("posting_rule_release_hash", String(71), nullable=False),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(11), nullable=False),
    Column("debit_original", Numeric(20, 4), nullable=False),
    Column("credit_original", Numeric(20, 4), nullable=False),
    Column("original_currency", String(3), nullable=False),
    Column("debit_functional", Numeric(20, 4), nullable=False),
    Column("credit_functional", Numeric(20, 4), nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("fx_rate_snapshot_id", Uuid(as_uuid=False), nullable=True),
    Column("fx_rate_snapshot_hash", String(71), nullable=True),
    Column("source_record_line_ref", String(256), nullable=False),
    Column("description", String(1000), nullable=True),
    Column("dimensions_json", JSON, nullable=False),
    Column("evidence_hash", String(71), nullable=False),
    Column("line_hash", String(71), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "journal_id",
        "candidate_source_line_no",
        name="ux_eos_journal_candidate_line",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "journal_id"),
        (
            "eos_journal_header.tenant_id",
            "eos_journal_header.company_id",
            "eos_journal_header.journal_id",
        ),
        name="fk_eos_journal_line_header",
    ),
    ForeignKeyConstraint(
        (
            "tenant_id",
            "candidate_id",
            "candidate_revision",
            "candidate_source_line_no",
        ),
        (
            "eos_voucher_candidate_line.tenant_id",
            "eos_voucher_candidate_line.candidate_id",
            "eos_voucher_candidate_line.revision_no",
            "eos_voucher_candidate_line.line_no",
        ),
        name="fk_eos_journal_line_candidate",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_journal_line_account",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_policy_id"),
        (
            "eos_company_account_policy.tenant_id",
            "eos_company_account_policy.policy_id",
        ),
        name="fk_eos_journal_line_policy",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_journal_line_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "fx_rate_snapshot_id"),
        ("eos_fx_rate_snapshot.tenant_id", "eos_fx_rate_snapshot.rate_snapshot_id"),
        name="fk_eos_journal_line_fx",
    ),
)
Index(
    "ix_eos_journal_project_date",
    EOS_JOURNAL_LINE_TABLE.c.tenant_id,
    EOS_JOURNAL_LINE_TABLE.c.company_id,
    EOS_JOURNAL_LINE_TABLE.c.project_id,
    EOS_JOURNAL_LINE_TABLE.c.journal_id,
)
Index(
    "ix_eos_journal_account",
    EOS_JOURNAL_LINE_TABLE.c.tenant_id,
    EOS_JOURNAL_LINE_TABLE.c.company_id,
    EOS_JOURNAL_LINE_TABLE.c.account_id,
    EOS_JOURNAL_LINE_TABLE.c.journal_id,
)

EOS_JOURNAL_SEQUENCE_TABLE = Table(
    "eos_journal_sequence",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), primary_key=True),
    Column("period_id", Uuid(as_uuid=False), primary_key=True),
    Column("last_sequence", BigInteger, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id", "period_id"),
        (
            "eos_accounting_period.tenant_id",
            "eos_accounting_period.company_id",
            "eos_accounting_period.period_id",
        ),
        name="fk_eos_journal_sequence_period",
    ),
)


class EosJournalError(RuntimeError):
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


class SqlAlchemyEosJournalRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(
        self, *, tenant_id: str, company_id: str, journal_id: str
    ) -> dict[str, Any] | None:
        key = _journal_key(tenant_id, company_id, journal_id)
        try:
            with self._session_factory() as session:
                return self.get_in_session(session, **key)
        except EosJournalError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        company_id: str,
        journal_id: str,
    ) -> dict[str, Any] | None:
        header = (
            session.execute(
                select(EOS_JOURNAL_HEADER_TABLE).where(
                    EOS_JOURNAL_HEADER_TABLE.c.tenant_id == tenant_id,
                    EOS_JOURNAL_HEADER_TABLE.c.company_id == company_id,
                    EOS_JOURNAL_HEADER_TABLE.c.journal_id == journal_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if header is None:
            return None
        lines = (
            session.execute(
                select(EOS_JOURNAL_LINE_TABLE)
                .where(
                    EOS_JOURNAL_LINE_TABLE.c.tenant_id == tenant_id,
                    EOS_JOURNAL_LINE_TABLE.c.company_id == company_id,
                    EOS_JOURNAL_LINE_TABLE.c.journal_id == journal_id,
                )
                .order_by(EOS_JOURNAL_LINE_TABLE.c.line_no)
            )
            .mappings()
            .all()
        )
        acceptance = (
            session.execute(
                select(EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE).where(
                    EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE.c.tenant_id == tenant_id,
                    EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE.c.company_id == company_id,
                    EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE.c.acceptance_id
                    == header["accounting_acceptance_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if acceptance is None:
            raise _corrupt("PostedJournal accounting acceptance is missing")
        return {
            "header": dict(header),
            "lines": [dict(line) for line in lines],
            "acceptance": dict(acceptance),
        }

    def stage_in_session(
        self,
        session: Session,
        *,
        acceptance: Mapping[str, Any],
        header: Mapping[str, Any],
        lines: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        admitted = admit_posted_journal(
            acceptance=acceptance,
            header=header,
            lines=lines,
        )
        try:
            session.execute(
                EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE.insert().values(
                    **admitted["acceptance"]
                )
            )
            session.execute(
                EOS_JOURNAL_HEADER_TABLE.insert().values(**admitted["header"])
            )
            session.execute(EOS_JOURNAL_LINE_TABLE.insert(), admitted["lines"])
        except IntegrityError as exc:
            raise EosJournalError(
                "EOS_JOURNAL_CONFLICT",
                "PostedJournal identity, source Candidate, or proof already exists",
                status_code=409,
            ) from exc
        return admitted


def admit_posted_journal(
    *,
    acceptance: Mapping[str, Any],
    header: Mapping[str, Any],
    lines: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    admitted_header = _admit_header(header)
    admitted_acceptance = _admit_acceptance(acceptance, header=admitted_header)
    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)):
        raise _invalid("lines must be an ordered collection")
    admitted_lines = [_admit_line(line, header=admitted_header) for line in lines]
    admitted_lines.sort(key=lambda line: line["line_no"])
    if len(admitted_lines) < 2 or [line["line_no"] for line in admitted_lines] != list(
        range(1, len(admitted_lines) + 1)
    ):
        raise _invalid(
            "Journal lines must be contiguous and contain at least two lines"
        )
    debit = sum((line["debit_functional"] for line in admitted_lines), Decimal(0))
    credit = sum((line["credit_functional"] for line in admitted_lines), Decimal(0))
    if (
        debit <= 0
        or debit != credit
        or admitted_header["line_count"] != len(admitted_lines)
        or admitted_header["total_debit_functional"] != debit
        or admitted_header["total_credit_functional"] != credit
    ):
        raise _invalid("Journal line count and functional totals must balance")
    if (
        admitted_acceptance["acceptance_id"]
        != admitted_header["accounting_acceptance_id"]
    ):
        raise _invalid("Accounting acceptance identity does not match Journal")
    line_hashes = [line["line_hash"] for line in admitted_lines]
    if admitted_header["journal_hash"] != build_journal_hash(
        admitted_header, line_hashes=line_hashes
    ):
        raise _invalid("journal_hash does not match immutable Journal semantics")
    return {
        "acceptance": admitted_acceptance,
        "header": admitted_header,
        "lines": admitted_lines,
    }


def build_line_hash(value: Mapping[str, Any]) -> str:
    semantics = {
        "schema_version": "eos_journal_line.v1",
        **{
            key: _hash_value(item)
            for key, item in sorted(value.items())
            if key != "line_hash"
        },
    }
    return semantic_sha256_hash_ref(semantics)


def build_acceptance_hash(value: Mapping[str, Any]) -> str:
    semantics = {
        "schema_version": "eos_accounting_approval_acceptance.v1",
        **{
            key: _hash_value(item)
            for key, item in sorted(value.items())
            if key != "acceptance_hash"
        },
    }
    return semantic_sha256_hash_ref(semantics)


def build_journal_hash(header: Mapping[str, Any], *, line_hashes: Sequence[str]) -> str:
    semantics = {
        "schema_version": POSTED_JOURNAL_SCHEMA,
        "header": {
            key: _hash_value(item)
            for key, item in sorted(header.items())
            if key != "journal_hash"
        },
        "line_hashes": list(line_hashes),
    }
    return semantic_sha256_hash_ref(semantics)


def wire_posted_journal(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": POSTED_JOURNAL_SCHEMA,
        "operation_id": JOURNAL_GET_OPERATION,
        "header": _wire_record(value["header"]),
        "lines": [_wire_record(line) for line in value["lines"]],
        "accounting_acceptance": _wire_record(value["acceptance"]),
    }


def _admit_header(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _exact_record(EOS_JOURNAL_HEADER_TABLE, value, "Journal header")
    normalized = {
        **record,
        "tenant_id": _scoped_id("tenant_id", record["tenant_id"]),
        "company_id": _uuid("company_id", record["company_id"]),
        "journal_id": _uuid("journal_id", record["journal_id"]),
        "candidate_id": _uuid("candidate_id", record["candidate_id"]),
        "candidate_revision": _positive_int(
            "candidate_revision", record["candidate_revision"]
        ),
        "period_id": _uuid("period_id", record["period_id"]),
        "posting_sequence": _positive_int(
            "posting_sequence", record["posting_sequence"]
        ),
        "journal_no": _scoped_id("journal_no", record["journal_no"]),
        "source_document_id": _uuid("source_document_id", record["source_document_id"]),
        "source_document_revision": _positive_int(
            "source_document_revision", record["source_document_revision"]
        ),
        "accounting_acceptance_id": _uuid(
            "accounting_acceptance_id", record["accounting_acceptance_id"]
        ),
        "business_operation_id": _uuid(
            "business_operation_id", record["business_operation_id"]
        ),
        "idempotency_key": _scoped_id("idempotency_key", record["idempotency_key"]),
        "line_count": _positive_int("line_count", record["line_count"]),
        "total_debit_functional": _money(
            "total_debit_functional", record["total_debit_functional"], positive=True
        ),
        "total_credit_functional": _money(
            "total_credit_functional", record["total_credit_functional"], positive=True
        ),
        "recognition_date": _date("recognition_date", record["recognition_date"]),
        "posting_date": _date("posting_date", record["posting_date"]),
        "posted_at": _datetime("posted_at", record["posted_at"]),
    }
    if (
        normalized["state"] != "POSTED"
        or normalized["transaction_kind"] not in _JOURNAL_KINDS
    ):
        raise _invalid("Journal must be POSTED with a supported transaction kind")
    if normalized["posting_date"] < normalized["recognition_date"]:
        raise _invalid("posting_date cannot precede recognition_date")
    normalized["functional_currency"] = _currency(
        "functional_currency", normalized["functional_currency"]
    )
    normalized["reversal_of_journal_id"] = _optional_uuid(
        "reversal_of_journal_id", normalized["reversal_of_journal_id"]
    )
    for field in (
        "candidate_hash",
        "source_document_hash",
        "posting_rule_release_hash",
        "fx_rate_set_hash",
        "payload_hash",
        "journal_hash",
    ):
        normalized[field] = _hash_ref(field, normalized[field])
    return normalized


def _admit_acceptance(
    value: Mapping[str, Any], *, header: Mapping[str, Any]
) -> dict[str, Any]:
    record = _exact_record(
        EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE, value, "Accounting acceptance"
    )
    for field in (
        "company_id",
        "acceptance_id",
        "candidate_id",
        "accounting_evidence_id",
        "approval_case_id",
        "wc_decision_id",
        "journal_id",
    ):
        record[field] = _uuid(field, record[field])
    record["tenant_id"] = _scoped_id("tenant_id", record["tenant_id"])
    record["candidate_revision"] = _positive_int(
        "candidate_revision", record["candidate_revision"]
    )
    record["accepted_by"] = _scoped_id("accepted_by", record["accepted_by"])
    record["oa_decision_ref"] = _scoped_id("oa_decision_ref", record["oa_decision_ref"])
    record["accepted_at"] = _datetime("accepted_at", record["accepted_at"])
    if record["purpose"] != "ACCOUNTING_POSTING":
        raise _invalid("Accounting acceptance purpose must be ACCOUNTING_POSTING")
    for field in (
        "candidate_hash",
        "proof_hash",
        "oa_decision_revision_hash",
        "acceptance_hash",
    ):
        record[field] = _hash_ref(field, record[field])
    for field in (
        "tenant_id",
        "company_id",
        "candidate_id",
        "candidate_revision",
        "candidate_hash",
        "journal_id",
    ):
        if record[field] != header[field]:
            raise _invalid(f"Accounting acceptance {field} does not match Journal")
    if record["acceptance_hash"] != build_acceptance_hash(record):
        raise _invalid("acceptance_hash does not match immutable acceptance semantics")
    return record


def _admit_line(
    value: Mapping[str, Any], *, header: Mapping[str, Any]
) -> dict[str, Any]:
    record = _exact_record(EOS_JOURNAL_LINE_TABLE, value, "Journal line")
    for field in (
        "company_id",
        "journal_id",
        "candidate_id",
        "account_id",
        "account_policy_id",
        "project_id",
    ):
        record[field] = _uuid(field, record[field])
    record["tenant_id"] = _scoped_id("tenant_id", record["tenant_id"])
    for field in ("line_no", "candidate_revision", "candidate_source_line_no"):
        record[field] = _positive_int(field, record[field])
    for field in (
        "debit_original",
        "credit_original",
        "debit_functional",
        "credit_functional",
    ):
        record[field] = _money(field, record[field])
    debit_side = (
        record["debit_original"] > 0
        and record["credit_original"] == 0
        and record["debit_functional"] > 0
        and record["credit_functional"] == 0
    )
    credit_side = (
        record["credit_original"] > 0
        and record["debit_original"] == 0
        and record["credit_functional"] > 0
        and record["debit_functional"] == 0
    )
    if not (debit_side or credit_side):
        raise _invalid(
            "Journal line must have exactly one consistent debit or credit side"
        )
    record["original_currency"] = _currency(
        "original_currency", record["original_currency"]
    )
    record["functional_currency"] = _currency(
        "functional_currency", record["functional_currency"]
    )
    if record["functional_currency"] != header["functional_currency"]:
        raise _invalid("Journal line functional currency does not match Journal")
    record["project_code"] = _project_code(record["project_code"])
    record["fx_rate_snapshot_id"] = _optional_uuid(
        "fx_rate_snapshot_id", record["fx_rate_snapshot_id"]
    )
    if record["original_currency"] == record["functional_currency"]:
        if (
            record["fx_rate_snapshot_id"] is not None
            or record["fx_rate_snapshot_hash"] is not None
        ):
            raise _invalid("Same-currency line cannot carry an FX snapshot")
    elif record["fx_rate_snapshot_id"] is None:
        raise _invalid("Foreign-currency line requires an FX snapshot")
    else:
        record["fx_rate_snapshot_hash"] = _hash_ref(
            "fx_rate_snapshot_hash", record["fx_rate_snapshot_hash"]
        )
    if not isinstance(record["dimensions_json"], Mapping):
        raise _invalid("dimensions_json must be an object")
    record["dimensions_json"] = dict(record["dimensions_json"])
    for field in (
        "account_policy_release_hash",
        "posting_rule_release_hash",
        "evidence_hash",
        "line_hash",
    ):
        record[field] = _hash_ref(field, record[field])
    for field in (
        "tenant_id",
        "company_id",
        "journal_id",
        "candidate_id",
        "candidate_revision",
    ):
        if record[field] != header[field]:
            raise _invalid(f"Journal line {field} does not match Journal")
    if record["line_hash"] != build_line_hash(record):
        raise _invalid("line_hash does not match immutable line semantics")
    return record


def _exact_record(table: Table, value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        column.name for column in table.c
    }:
        raise _invalid(f"{label} fields do not match the canonical contract")
    return dict(value)


def _journal_key(
    tenant_id: object, company_id: object, journal_id: object
) -> dict[str, str]:
    return {
        "tenant_id": _scoped_id("tenant_id", tenant_id),
        "company_id": _uuid("company_id", company_id),
        "journal_id": _uuid("journal_id", journal_id),
    }


def _wire_record(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _wire_value(item) for key, item in value.items()}


def _wire_value(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _hash_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _hash_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_hash_value(item) for item in value]
    return _wire_value(value)


def _scoped_id(field_name: str, value: object) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} has invalid stable-reference syntax")
    return normalized


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _optional_uuid(field_name: str, value: object) -> str | None:
    return None if value is None else _uuid(field_name, value)


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{field_name} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be a positive integer") from exc
    if normalized < 1 or str(normalized) != str(value):
        raise _invalid(f"{field_name} must be a positive integer")
    return normalized


def _money(field_name: str, value: object, *, positive: bool = False) -> Decimal:
    try:
        normalized = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid(f"{field_name} must be a four-decimal amount") from exc
    if not normalized.is_finite() or normalized < 0 or (positive and normalized <= 0):
        raise _invalid(f"{field_name} has an invalid amount")
    return normalized


def _date(field_name: str, value: object) -> date:
    if isinstance(value, datetime):
        raise _invalid(f"{field_name} must be a date")
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be an ISO date") from exc


def _datetime(field_name: str, value: object) -> datetime:
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _currency(field_name: str, value: object) -> str:
    normalized = str(value) if isinstance(value, str) else ""
    if _CURRENCY.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} must be an uppercase ISO currency")
    return normalized


def _project_code(value: object) -> str:
    normalized = str(value) if isinstance(value, str) else ""
    if _PROJECT_CODE.fullmatch(normalized) is None:
        raise _invalid("project_code is invalid")
    return normalized


def _hash_ref(field_name: str, value: object) -> str:
    normalized = str(value) if isinstance(value, str) else ""
    if _HASH_REF.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} must be a sha256 hash reference")
    return normalized


def _invalid(detail: str) -> EosJournalError:
    return EosJournalError("EOS_JOURNAL_INVALID", detail, status_code=422)


def _corrupt(detail: str) -> EosJournalError:
    return EosJournalError("EOS_JOURNAL_STATE_INVALID", detail, status_code=503)


def _unavailable() -> EosJournalError:
    return EosJournalError(
        "EOS_JOURNAL_PERSISTENCE_UNAVAILABLE",
        "PostedJournal persistence is unavailable",
        status_code=503,
        retryable=True,
    )
