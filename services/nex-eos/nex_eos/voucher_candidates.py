from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime import build_unit_of_work
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import (
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
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .accounts import EOS_ACCOUNT_TABLE
from .approved_documents import EOS_APPROVED_DOCUMENT_TABLE
from .business_transactions import EOS_METADATA
from .projects import EOS_PROJECT_TABLE

EOS_VOUCHER_CANDIDATE_STATES = frozenset(
    {"DRAFT", "READY_FOR_REVIEW", "RETURNED_FOR_CORRECTION"}
)
EOS_CREATE_VOUCHER_CANDIDATE_OPERATION = "FINANCE.VOUCHER_CANDIDATE.CREATE_V2"
EOS_VOUCHER_CANDIDATE_CREATE_SCOPE = "finance:voucher-candidate:create"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT_REGISTRATION_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_MONEY_QUANTUM = Decimal("0.0001")
_MAX_MONEY = Decimal("9999999999999999.9999")


EOS_VOUCHER_CANDIDATE_TABLE = Table(
    "eos_voucher_candidate",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("candidate_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(11), nullable=False),
    Column("document_envelope_id", Uuid(as_uuid=False), nullable=False),
    Column("preparer_subject_id", String(128), nullable=False),
    Column("source_kind", String(32), nullable=False),
    Column("source_record_ref", String(256), nullable=False),
    Column("business_work_code", String(16), nullable=False),
    Column("transaction_currency", String(3), nullable=False),
    Column("recognition_date", Date, nullable=False),
    Column("state", String(32), nullable=False),
    Column("current_revision_no", Integer, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "created_business_operation_id",
        name="ux_eos_candidate_operation",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_candidate_company",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_candidate_project",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "document_envelope_id"),
        (
            "eos_approved_document_envelope.tenant_id",
            "eos_approved_document_envelope.envelope_id",
        ),
        name="fk_eos_candidate_document",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "created_business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_candidate_operation",
    ),
    CheckConstraint(
        "state IN ('DRAFT', 'READY_FOR_REVIEW', 'RETURNED_FOR_CORRECTION', 'POSTED')",
        name="ck_eos_candidate_s3_state",
    ),
    CheckConstraint(
        "current_revision_no > 0 AND version > 0",
        name="ck_eos_candidate_versions",
    ),
)
Index(
    "ix_eos_candidate_document",
    EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id,
    EOS_VOUCHER_CANDIDATE_TABLE.c.document_envelope_id,
)
Index(
    "ix_eos_candidate_project",
    EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id,
    EOS_VOUCHER_CANDIDATE_TABLE.c.project_id,
    EOS_VOUCHER_CANDIDATE_TABLE.c.state,
)

EOS_VOUCHER_CANDIDATE_REVISION_TABLE = Table(
    "eos_voucher_candidate_revision",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("candidate_id", Uuid(as_uuid=False), primary_key=True),
    Column("revision_no", Integer, primary_key=True),
    Column("revision_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_hash", String(71), nullable=False),
    Column("source_evidence_hash", String(71), nullable=False),
    Column("approved_document_hash", String(71), nullable=False),
    Column("attachment_manifest_hash", String(71), nullable=False),
    Column("fx_rate_set_hash", String(71), nullable=True),
    Column("posting_rule_release_hash", String(71), nullable=True),
    Column("account_policy_release_hash", String(71), nullable=True),
    Column("journal_payload_hash", String(71), nullable=True),
    Column("created_by", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "revision_id", name="ux_eos_candidate_revision_id"),
    ForeignKeyConstraint(
        ("tenant_id", "candidate_id"),
        ("eos_voucher_candidate.tenant_id", "eos_voucher_candidate.candidate_id"),
        name="fk_eos_candidate_revision",
        ondelete="RESTRICT",
    ),
    CheckConstraint("revision_no > 0", name="ck_eos_candidate_revision_no"),
)

EOS_VOUCHER_CANDIDATE_LINE_TABLE = Table(
    "eos_voucher_candidate_line",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("candidate_id", Uuid(as_uuid=False), primary_key=True),
    Column("revision_no", Integer, primary_key=True),
    Column("line_no", Integer, primary_key=True),
    Column("account_id", Uuid(as_uuid=False), nullable=False),
    Column("project_id", Uuid(as_uuid=False), nullable=False),
    Column("project_code", String(11), nullable=False),
    Column("debit_original", Numeric(20, 4), nullable=False),
    Column("credit_original", Numeric(20, 4), nullable=False),
    Column("original_currency", String(3), nullable=False),
    Column("source_record_line_ref", String(256), nullable=False),
    Column("description", String(1000), nullable=True),
    Column("evidence_hash", String(71), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "candidate_id", "revision_no"),
        (
            "eos_voucher_candidate_revision.tenant_id",
            "eos_voucher_candidate_revision.candidate_id",
            "eos_voucher_candidate_revision.revision_no",
        ),
        name="fk_eos_candidate_line_revision",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_candidate_line_account",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "project_id"),
        ("eos_project.tenant_id", "eos_project.project_id"),
        name="fk_eos_candidate_line_project",
    ),
    CheckConstraint("line_no > 0", name="ck_eos_candidate_line_no"),
    CheckConstraint(
        "(debit_original > 0 AND credit_original = 0) OR "
        "(credit_original > 0 AND debit_original = 0)",
        name="ck_eos_candidate_line_side",
    ),
)


class EosVoucherCandidateError(RuntimeError):
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
class VoucherCandidateLineInput:
    account_id: str
    debit_original: Decimal
    credit_original: Decimal
    source_record_line_ref: str
    evidence_hash: str
    description: str | None = None


@dataclass(frozen=True)
class VoucherCandidateInput:
    tenant_id: str
    candidate_id: str
    revision_id: str
    company_id: str
    project_id: str
    project_code: str
    document_envelope_id: str
    approved_document_id: str
    document_revision: int
    approved_document_hash: str
    attachment_manifest_hash: str
    preparer_subject_id: str
    source_kind: str
    source_record_ref: str
    business_work_code: str
    transaction_currency: str
    recognition_date: date
    lines: Sequence[VoucherCandidateLineInput]
    created_business_operation_id: str


@dataclass(frozen=True)
class VoucherCandidateRevisionInput:
    tenant_id: str
    candidate_id: str
    revision_id: str
    expected_candidate_version: int
    expected_revision_no: int
    expected_candidate_hash: str
    actor_subject_id: str
    lines: Sequence[VoucherCandidateLineInput]


class SqlAlchemyEosVoucherCandidateRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create(self, value: VoucherCandidateInput) -> dict[str, Any]:
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                return self.create_in_session(transaction.db, value)
        except EosVoucherCandidateError:
            raise
        except IntegrityError as exc:
            raise EosVoucherCandidateError(
                "EOS_VOUCHER_CANDIDATE_CONFLICT",
                "VoucherCandidate identity or immutable lineage already exists.",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def create_in_session(
        self,
        session: Session,
        value: VoucherCandidateInput,
    ) -> dict[str, Any]:
        semantics = _candidate_semantics(value)
        now = _aware_datetime("clock", self._clock())
        document = self._require_document(session, semantics=semantics, now=now)
        project = self._require_project(session, semantics=semantics)
        self._require_accounts(session, semantics=semantics)

        source_evidence_hash = _hash_ref(
            "source_evidence_hash", document["business_proof_hash"]
        )
        candidate_hash = semantic_sha256_hash_ref(
            _hashable_candidate_semantics(
                semantics,
                source_evidence_hash=source_evidence_hash,
                approved_document_payload_hash=_hash_ref(
                    "approved_document_payload_hash", document["payload_hash"]
                ),
            )
        )
        candidate = {
            "tenant_id": semantics["tenant_id"],
            "candidate_id": semantics["candidate_id"],
            "company_id": semantics["company_id"],
            "project_id": semantics["project_id"],
            "project_code": project["project_code"],
            "document_envelope_id": semantics["document_envelope_id"],
            "preparer_subject_id": semantics["preparer_subject_id"],
            "source_kind": semantics["source_kind"],
            "source_record_ref": semantics["source_record_ref"],
            "business_work_code": semantics["business_work_code"],
            "transaction_currency": semantics["transaction_currency"],
            "recognition_date": semantics["recognition_date"],
            "state": "DRAFT",
            "current_revision_no": 1,
            "version": 1,
            "created_business_operation_id": semantics["created_business_operation_id"],
            "created_at": now,
            "updated_at": now,
        }
        revision = {
            "tenant_id": semantics["tenant_id"],
            "candidate_id": semantics["candidate_id"],
            "revision_no": 1,
            "revision_id": semantics["revision_id"],
            "candidate_hash": candidate_hash,
            "source_evidence_hash": source_evidence_hash,
            "approved_document_hash": semantics["approved_document_hash"],
            "attachment_manifest_hash": semantics["attachment_manifest_hash"],
            "fx_rate_set_hash": None,
            "posting_rule_release_hash": None,
            "account_policy_release_hash": None,
            "journal_payload_hash": None,
            "created_by": semantics["preparer_subject_id"],
            "created_at": now,
        }
        lines = [
            {
                "tenant_id": semantics["tenant_id"],
                "candidate_id": semantics["candidate_id"],
                "revision_no": 1,
                "line_no": line["line_no"],
                "account_id": line["account_id"],
                "project_id": semantics["project_id"],
                "project_code": semantics["project_code"],
                "debit_original": line["debit_original"],
                "credit_original": line["credit_original"],
                "original_currency": semantics["transaction_currency"],
                "source_record_line_ref": line["source_record_line_ref"],
                "description": line["description"],
                "evidence_hash": line["evidence_hash"],
            }
            for line in semantics["lines"]
        ]
        session.execute(EOS_VOUCHER_CANDIDATE_TABLE.insert().values(**candidate))
        session.execute(
            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.insert().values(**revision)
        )
        session.execute(EOS_VOUCHER_CANDIDATE_LINE_TABLE.insert(), lines)
        return _projection(candidate, revision, lines)

    def get(self, *, tenant_id: str, candidate_id: str) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id, 128)
        candidate_id = _uuid("candidate_id", candidate_id)
        try:
            with self._session_factory() as session:
                candidate = (
                    session.execute(
                        select(EOS_VOUCHER_CANDIDATE_TABLE).where(
                            EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == tenant_id,
                            EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == candidate_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if candidate is None:
                    return None
                revision = (
                    session.execute(
                        select(EOS_VOUCHER_CANDIDATE_REVISION_TABLE).where(
                            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id
                            == tenant_id,
                            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.candidate_id
                            == candidate_id,
                            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.revision_no
                            == candidate["current_revision_no"],
                        )
                    )
                    .mappings()
                    .one()
                )
                lines = (
                    session.execute(
                        select(EOS_VOUCHER_CANDIDATE_LINE_TABLE)
                        .where(
                            EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.tenant_id == tenant_id,
                            EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.candidate_id
                            == candidate_id,
                            EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.revision_no
                            == candidate["current_revision_no"],
                        )
                        .order_by(EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.line_no)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return _projection(candidate, revision, lines)

    def append_revision(self, value: VoucherCandidateRevisionInput) -> dict[str, Any]:
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                return self.append_revision_in_session(transaction.db, value)
        except EosVoucherCandidateError:
            raise
        except IntegrityError as exc:
            raise EosVoucherCandidateError(
                "EOS_VOUCHER_CANDIDATE_REVISION_CONFLICT",
                "VoucherCandidate revision identity already exists.",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def append_revision_in_session(
        self,
        session: Session,
        value: VoucherCandidateRevisionInput,
    ) -> dict[str, Any]:
        if not isinstance(value, VoucherCandidateRevisionInput):
            raise _invalid("value must be VoucherCandidateRevisionInput.")
        tenant_id = _scoped_id("tenant_id", value.tenant_id, 128)
        candidate_id = _uuid("candidate_id", value.candidate_id)
        revision_id = _uuid("revision_id", value.revision_id)
        expected_version = _positive_int(
            "expected_candidate_version", value.expected_candidate_version
        )
        expected_revision_no = _positive_int(
            "expected_revision_no", value.expected_revision_no
        )
        expected_candidate_hash = _hash_ref(
            "expected_candidate_hash", value.expected_candidate_hash
        )
        actor_subject_id = _scoped_id("actor_subject_id", value.actor_subject_id, 128)
        lines = _lines(value.lines)

        candidate = (
            session.execute(
                select(EOS_VOUCHER_CANDIDATE_TABLE)
                .where(
                    EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == tenant_id,
                    EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == candidate_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if candidate is None:
            raise EosVoucherCandidateError(
                "EOS_VOUCHER_CANDIDATE_NOT_FOUND",
                "VoucherCandidate was not found in tenant scope.",
                status_code=404,
            )
        if (
            candidate["state"] != "RETURNED_FOR_CORRECTION"
            or int(candidate["version"]) != expected_version
            or int(candidate["current_revision_no"]) != expected_revision_no
        ):
            raise EosVoucherCandidateError(
                "EOS_VOUCHER_CANDIDATE_REVISION_STALE",
                "VoucherCandidate state, version, or current revision changed.",
                status_code=409,
            )

        current_revision = (
            session.execute(
                select(EOS_VOUCHER_CANDIDATE_REVISION_TABLE).where(
                    EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id == tenant_id,
                    EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.candidate_id == candidate_id,
                    EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.revision_no
                    == expected_revision_no,
                )
            )
            .mappings()
            .one()
        )
        if current_revision["candidate_hash"] != expected_candidate_hash:
            raise EosVoucherCandidateError(
                "EOS_VOUCHER_CANDIDATE_REVISION_STALE",
                "VoucherCandidate hash changed before correction.",
                status_code=409,
            )

        document = (
            session.execute(
                select(EOS_APPROVED_DOCUMENT_TABLE).where(
                    EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVED_DOCUMENT_TABLE.c.envelope_id
                    == candidate["document_envelope_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if document is None:
            raise _invalid("Approved document envelope was not found.")
        semantics = {
            "tenant_id": tenant_id,
            "candidate_id": candidate_id,
            "revision_id": revision_id,
            "company_id": str(candidate["company_id"]),
            "project_id": str(candidate["project_id"]),
            "project_code": str(candidate["project_code"]),
            "document_envelope_id": str(candidate["document_envelope_id"]),
            "approved_document_id": str(document["approved_document_id"]),
            "document_revision": int(document["document_revision"]),
            "approved_document_hash": str(current_revision["approved_document_hash"]),
            "attachment_manifest_hash": str(
                current_revision["attachment_manifest_hash"]
            ),
            "preparer_subject_id": str(candidate["preparer_subject_id"]),
            "source_kind": str(candidate["source_kind"]),
            "source_record_ref": str(candidate["source_record_ref"]),
            "business_work_code": str(candidate["business_work_code"]),
            "transaction_currency": str(candidate["transaction_currency"]),
            "recognition_date": _date(
                "recognition_date", candidate["recognition_date"]
            ),
            "lines": lines,
            "created_business_operation_id": str(
                candidate["created_business_operation_id"]
            ),
        }
        now = _aware_datetime("clock", self._clock())
        admitted_document = self._require_document(
            session, semantics=semantics, now=now
        )
        project = self._require_project(session, semantics=semantics)
        self._require_accounts(session, semantics=semantics)
        source_evidence_hash = _hash_ref(
            "source_evidence_hash", admitted_document["business_proof_hash"]
        )
        candidate_hash = semantic_sha256_hash_ref(
            _hashable_candidate_semantics(
                semantics,
                source_evidence_hash=source_evidence_hash,
                approved_document_payload_hash=_hash_ref(
                    "approved_document_payload_hash",
                    admitted_document["payload_hash"],
                ),
            )
        )
        if candidate_hash == expected_candidate_hash:
            raise EosVoucherCandidateError(
                "EOS_VOUCHER_CANDIDATE_REVISION_NO_CHANGE",
                "Corrected VoucherCandidate revision must change its semantics.",
                status_code=409,
            )

        revision_no = expected_revision_no + 1
        revision = {
            "tenant_id": tenant_id,
            "candidate_id": candidate_id,
            "revision_no": revision_no,
            "revision_id": revision_id,
            "candidate_hash": candidate_hash,
            "source_evidence_hash": source_evidence_hash,
            "approved_document_hash": semantics["approved_document_hash"],
            "attachment_manifest_hash": semantics["attachment_manifest_hash"],
            "fx_rate_set_hash": None,
            "posting_rule_release_hash": None,
            "account_policy_release_hash": None,
            "journal_payload_hash": None,
            "created_by": actor_subject_id,
            "created_at": now,
        }
        line_records = [
            {
                "tenant_id": tenant_id,
                "candidate_id": candidate_id,
                "revision_no": revision_no,
                "line_no": line["line_no"],
                "account_id": line["account_id"],
                "project_id": str(candidate["project_id"]),
                "project_code": str(project["project_code"]),
                "debit_original": line["debit_original"],
                "credit_original": line["credit_original"],
                "original_currency": str(candidate["transaction_currency"]),
                "source_record_line_ref": line["source_record_line_ref"],
                "description": line["description"],
                "evidence_hash": line["evidence_hash"],
            }
            for line in lines
        ]
        session.execute(
            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.insert().values(**revision)
        )
        session.execute(EOS_VOUCHER_CANDIDATE_LINE_TABLE.insert(), line_records)
        advanced = session.execute(
            update(EOS_VOUCHER_CANDIDATE_TABLE)
            .where(
                EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == tenant_id,
                EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == candidate_id,
                EOS_VOUCHER_CANDIDATE_TABLE.c.state == "RETURNED_FOR_CORRECTION",
                EOS_VOUCHER_CANDIDATE_TABLE.c.version == expected_version,
                EOS_VOUCHER_CANDIDATE_TABLE.c.current_revision_no
                == expected_revision_no,
            )
            .values(
                state="DRAFT",
                current_revision_no=revision_no,
                version=expected_version + 1,
                updated_at=now,
            )
        )
        if advanced.rowcount != 1:
            raise EosVoucherCandidateError(
                "EOS_VOUCHER_CANDIDATE_REVISION_STALE",
                "VoucherCandidate changed during correction.",
                status_code=409,
            )
        projected_candidate = {
            **dict(candidate),
            "state": "DRAFT",
            "current_revision_no": revision_no,
            "version": expected_version + 1,
            "updated_at": now,
        }
        return _projection(projected_candidate, revision, line_records)

    @staticmethod
    def _require_document(
        session: Session,
        *,
        semantics: Mapping[str, Any],
        now: datetime,
    ) -> Mapping[str, Any]:
        row = (
            session.execute(
                select(EOS_APPROVED_DOCUMENT_TABLE).where(
                    EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id == semantics["tenant_id"],
                    EOS_APPROVED_DOCUMENT_TABLE.c.envelope_id
                    == semantics["document_envelope_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _invalid("Approved document envelope was not found.")
        expected = (
            row["company_id"] == semantics["company_id"]
            and row["approved_document_id"] == semantics["approved_document_id"]
            and row["document_revision"] == semantics["document_revision"]
            and row["document_content_hash"] == semantics["approved_document_hash"]
            and row["attachment_manifest_hash"] == semantics["attachment_manifest_hash"]
            and row["work_code"] == semantics["business_work_code"]
            and row["approved_currency"] == semantics["transaction_currency"]
        )
        if not expected:
            raise _invalid("Approved document lineage does not match the command.")
        valid_from = _stored_time(row["valid_from"])
        valid_until = (
            _stored_time(row["valid_until"]) if row["valid_until"] is not None else None
        )
        if (
            row["state"] != "ACTIVE"
            or valid_from > now
            or (valid_until is not None and valid_until <= now)
        ):
            raise _invalid("Approved document envelope is not currently active.")
        project_ids = tuple(str(item) for item in row["allowed_project_ids"])
        project_codes = tuple(str(item) for item in row["allowed_project_codes"])
        if (
            semantics["project_id"] not in project_ids
            or semantics["project_code"] not in project_codes
        ):
            raise _invalid("Approved document does not admit the Project identity.")
        return row

    @staticmethod
    def _require_project(
        session: Session,
        *,
        semantics: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        row = (
            session.execute(
                select(EOS_PROJECT_TABLE).where(
                    EOS_PROJECT_TABLE.c.tenant_id == semantics["tenant_id"],
                    EOS_PROJECT_TABLE.c.project_id == semantics["project_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _invalid("Project was not found in tenant scope.")
        if (
            row["project_code"] != semantics["project_code"]
            or row["origin"] != "APPROVED_APPLICATION"
            or row["status"] != "ACTIVE"
            or (
                row["start_date"] is not None
                and row["start_date"] > semantics["recognition_date"]
            )
            or (
                row["end_date"] is not None
                and row["end_date"] < semantics["recognition_date"]
            )
        ):
            raise _invalid(
                "Project must be an active approved application with the exact "
                "registration code."
            )
        return row

    @staticmethod
    def _require_accounts(session: Session, *, semantics: Mapping[str, Any]) -> None:
        account_ids = {line["account_id"] for line in semantics["lines"]}
        observed = set(
            session.scalars(
                select(EOS_ACCOUNT_TABLE.c.account_id).where(
                    EOS_ACCOUNT_TABLE.c.tenant_id == semantics["tenant_id"],
                    EOS_ACCOUNT_TABLE.c.account_id.in_(account_ids),
                )
            ).all()
        )
        if observed != account_ids:
            raise _invalid("One or more Candidate account identities do not exist.")


def _candidate_semantics(value: VoucherCandidateInput) -> dict[str, Any]:
    if not isinstance(value, VoucherCandidateInput):
        raise _invalid("value must be VoucherCandidateInput.")
    project_code = str(value.project_code).strip().upper()
    if _PROJECT_REGISTRATION_CODE.fullmatch(project_code) is None:
        raise _invalid("project_code must be an approved registration code.")
    lines = _lines(value.lines)
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id, 128),
        "candidate_id": _uuid("candidate_id", value.candidate_id),
        "revision_id": _uuid("revision_id", value.revision_id),
        "company_id": _uuid("company_id", value.company_id),
        "project_id": _uuid("project_id", value.project_id),
        "project_code": project_code,
        "document_envelope_id": _uuid(
            "document_envelope_id", value.document_envelope_id
        ),
        "approved_document_id": _scoped_id(
            "approved_document_id", value.approved_document_id, 128
        ),
        "document_revision": _positive_int(
            "document_revision", value.document_revision
        ),
        "approved_document_hash": _hash_ref(
            "approved_document_hash", value.approved_document_hash
        ),
        "attachment_manifest_hash": _hash_ref(
            "attachment_manifest_hash", value.attachment_manifest_hash
        ),
        "preparer_subject_id": _scoped_id(
            "preparer_subject_id", value.preparer_subject_id, 128
        ),
        "source_kind": _code("source_kind", value.source_kind),
        "source_record_ref": _scoped_id(
            "source_record_ref", value.source_record_ref, 256
        ),
        "business_work_code": _work_code(value.business_work_code),
        "transaction_currency": _currency(value.transaction_currency),
        "recognition_date": _date("recognition_date", value.recognition_date),
        "lines": lines,
        "created_business_operation_id": _uuid(
            "created_business_operation_id", value.created_business_operation_id
        ),
    }


def _lines(values: Sequence[VoucherCandidateLineInput]) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("lines must be a sequence.")
    if not 2 <= len(values) <= 1000:
        raise _invalid("lines must contain 2..1000 items.")
    records = []
    for line_no, value in enumerate(values, start=1):
        if not isinstance(value, VoucherCandidateLineInput):
            raise _invalid("lines must contain VoucherCandidateLineInput values.")
        debit = _nonnegative_money("debit_original", value.debit_original)
        credit = _nonnegative_money("credit_original", value.credit_original)
        if (debit > 0) == (credit > 0):
            raise _invalid(
                "Each Candidate line must contain exactly one debit or credit."
            )
        records.append(
            {
                "line_no": line_no,
                "account_id": _uuid("account_id", value.account_id),
                "debit_original": debit,
                "credit_original": credit,
                "source_record_line_ref": _scoped_id(
                    "source_record_line_ref", value.source_record_line_ref, 256
                ),
                "description": (
                    _text("description", value.description, 1000)
                    if value.description is not None
                    else None
                ),
                "evidence_hash": _hash_ref("evidence_hash", value.evidence_hash),
            }
        )
    return records


def _projection(
    candidate: Mapping[str, Any],
    revision: Mapping[str, Any],
    lines: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        **dict(candidate),
        "revision": dict(revision),
        "lines": [dict(line) for line in lines],
    }


def _hashable_candidate_semantics(
    semantics: Mapping[str, Any],
    *,
    source_evidence_hash: str,
    approved_document_payload_hash: str,
) -> dict[str, Any]:
    return {
        "tenant_id": semantics["tenant_id"],
        "company_id": semantics["company_id"],
        "project_id": semantics["project_id"],
        "project_code": semantics["project_code"],
        "document_envelope_id": semantics["document_envelope_id"],
        "approved_document_id": semantics["approved_document_id"],
        "document_revision": semantics["document_revision"],
        "approved_document_hash": semantics["approved_document_hash"],
        "attachment_manifest_hash": semantics["attachment_manifest_hash"],
        "source_evidence_hash": source_evidence_hash,
        "approved_document_payload_hash": approved_document_payload_hash,
        "preparer_subject_id": semantics["preparer_subject_id"],
        "source_kind": semantics["source_kind"],
        "source_record_ref": semantics["source_record_ref"],
        "business_work_code": semantics["business_work_code"],
        "transaction_currency": semantics["transaction_currency"],
        "recognition_date": semantics["recognition_date"].isoformat(),
        "lines": [
            {
                **line,
                "debit_original": format(line["debit_original"], ".4f"),
                "credit_original": format(line["credit_original"], ".4f"),
            }
            for line in semantics["lines"]
        ],
    }


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID.") from exc


def _scoped_id(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if len(normalized) > maximum or _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} has invalid stable-reference syntax.")
    return normalized


def _code(field_name: str, value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _CODE.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} has invalid code syntax.")
    return normalized


def _work_code(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if re.fullmatch(r"^FL[0-9]{7}$", normalized) is None:
        raise _invalid("business_work_code must be an FL work code.")
    return normalized


def _currency(value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _CURRENCY.fullmatch(normalized) is None:
        raise _invalid("transaction_currency must be a three-letter code.")
    return normalized


def _hash_ref(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _HASH_REF.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} must be a SHA-256 hash reference.")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(f"{field_name} must contain 1..{maximum} characters.")
    return normalized


def _date(field_name: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(f"{field_name} must be a date.")
    return value


def _aware_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _stored_time(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise _invalid("Stored document validity is not a datetime.")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field_name} must be a positive integer.")
    return value


def _nonnegative_money(field_name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise _invalid(f"{field_name} must be a finite non-negative Decimal.")
    try:
        normalized = value.quantize(_MONEY_QUANTUM)
    except InvalidOperation as exc:
        raise _invalid(f"{field_name} is outside Decimal(20,4).") from exc
    if normalized != value or normalized > _MAX_MONEY:
        raise _invalid(f"{field_name} must fit Decimal(20,4) exactly.")
    return normalized


def _invalid(detail: str) -> EosVoucherCandidateError:
    return EosVoucherCandidateError(
        "EOS_VOUCHER_CANDIDATE_INVALID",
        detail,
        status_code=422,
    )


def _persistence_error() -> EosVoucherCandidateError:
    return EosVoucherCandidateError(
        "EOS_VOUCHER_CANDIDATE_PERSISTENCE_FAILED",
        "VoucherCandidate persistence is unavailable.",
        status_code=503,
        retryable=True,
    )
