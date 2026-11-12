from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime import build_unit_of_work
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .approval_instances import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
)
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import EOS_METADATA
from .legal_entities import (
    EOS_LEGAL_ENTITY_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
)
from .projects import EOS_PROJECT_TABLE

BUSINESS_DOCUMENT_APPROVED_GET_OPERATION = "BUSINESS.DOCUMENT_APPROVED.GET"
APPROVED_DOCUMENT_PROTECTED_OPERATION = "APPROVE_BUSINESS_DOCUMENT"
FINANCE_DOCUMENT_READ_SCOPE = "finance:document:read"
APPROVED_DOCUMENT_SCOPE_TYPES = frozenset({"COMPANY", "PROJECT", "PROJECT_SET"})
APPROVED_DOCUMENT_STATES = frozenset({"ACTIVE", "REVOKED", "EXPIRED", "SUPERSEDED"})

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_PROJECT_REGISTRATION_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")

EOS_APPROVED_DOCUMENT_TABLE = Table(
    "eos_approved_document_envelope",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("envelope_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("approved_document_id", String(128), nullable=False),
    Column("document_revision", Integer, nullable=False),
    Column("document_type", String(64), nullable=False),
    Column("work_code", String(16), nullable=False),
    Column("document_content_hash", String(71), nullable=False),
    Column("attachment_manifest_hash", String(71), nullable=False),
    Column("business_approval_proof_id", Uuid(as_uuid=False), nullable=True),
    Column("scoped_document_evidence_id", Uuid(as_uuid=False), nullable=True),
    Column("business_proof_hash", String(71), nullable=False),
    Column("approval_policy_id", Uuid(as_uuid=False), nullable=False),
    Column("approval_policy_version", Integer, nullable=False),
    Column("approval_policy_hash", String(71), nullable=False),
    Column("scope_type", String(16), nullable=False),
    Column("project_set_hash", String(71), nullable=False),
    Column("allowed_project_ids", JSON, nullable=False),
    Column(
        "allowed_project_codes",
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    ),
    Column("approved_amount", Numeric(20, 4), nullable=False),
    Column("approved_currency", String(3), nullable=False),
    Column("tolerance_policy_hash", String(71), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    Column("state", String(16), nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("approved_by_ref_type", String(32), nullable=False),
    Column("approved_by_id", String(128), nullable=False),
    Column("source_work_item_ref", String(256), nullable=False),
    Column("payload_hash", String(71), nullable=False),
    Column("created_business_operation_id", Uuid(as_uuid=False), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "approved_document_id",
        "document_revision",
        name="ux_eos_approved_doc_revision",
    ),
    UniqueConstraint(
        "tenant_id",
        "business_approval_proof_id",
        name="ux_eos_approved_doc_proof",
    ),
    UniqueConstraint(
        "tenant_id",
        "scoped_document_evidence_id",
        name="ux_eos_approved_doc_scoped_evidence",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_approved_doc_company",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "business_approval_proof_id"),
        ("eos_approval_proof.tenant_id", "eos_approval_proof.approval_proof_id"),
        name="fk_eos_approved_doc_proof",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "scoped_document_evidence_id"),
        (
            "eos_document_signoff_evidence.tenant_id",
            "eos_document_signoff_evidence.evidence_id",
        ),
        name="fk_eos_approved_doc_scoped_evidence",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "approval_policy_id"),
        ("eos_approval_policy.tenant_id", "eos_approval_policy.approval_policy_id"),
        name="fk_eos_approved_doc_policy",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "created_business_operation_id"),
        (
            "eos_business_operation.tenant_id",
            "eos_business_operation.business_operation_id",
        ),
        name="fk_eos_approved_doc_operation",
    ),
    CheckConstraint("document_revision > 0", name="ck_eos_approved_doc_revision"),
    CheckConstraint(
        "((business_approval_proof_id IS NOT NULL AND "
        "scoped_document_evidence_id IS NULL) OR "
        "(business_approval_proof_id IS NULL AND "
        "scoped_document_evidence_id IS NOT NULL))",
        name="ck_eos_approved_doc_proof_source",
    ),
    CheckConstraint(
        "approval_policy_version > 0", name="ck_eos_approved_doc_policy_version"
    ),
    CheckConstraint("approved_amount > 0", name="ck_eos_approved_doc_amount"),
    CheckConstraint(
        "scope_type IN ('COMPANY', 'PROJECT', 'PROJECT_SET')",
        name="ck_eos_approved_doc_scope",
    ),
    CheckConstraint(
        "state IN ('ACTIVE', 'REVOKED', 'EXPIRED', 'SUPERSEDED')",
        name="ck_eos_approved_doc_state",
    ),
    CheckConstraint(
        "valid_until IS NULL OR valid_until > valid_from",
        name="ck_eos_approved_doc_period",
    ),
)
Index(
    "ix_eos_approved_doc_lookup",
    EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id,
    EOS_APPROVED_DOCUMENT_TABLE.c.company_id,
    EOS_APPROVED_DOCUMENT_TABLE.c.approved_document_id,
    EOS_APPROVED_DOCUMENT_TABLE.c.document_revision,
)
Index(
    "ix_eos_approved_doc_validity",
    EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id,
    EOS_APPROVED_DOCUMENT_TABLE.c.state,
    EOS_APPROVED_DOCUMENT_TABLE.c.valid_from,
    EOS_APPROVED_DOCUMENT_TABLE.c.valid_until,
)


class EosApprovedDocumentError(RuntimeError):
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
class ApprovedDocumentInput:
    tenant_id: str
    envelope_id: str
    company_id: str
    approved_document_id: str
    document_revision: int
    document_type: str
    work_code: str
    document_content_hash: str
    attachment_manifest_hash: str
    business_approval_proof_id: str
    scope_type: str
    allowed_project_ids: Sequence[str]
    approved_amount: Decimal
    approved_currency: str
    valid_from: datetime
    allowed_project_codes: Sequence[str] = ()
    valid_until: datetime | None = None
    tolerance_policy_hash: str | None = None


class SqlAlchemyEosApprovedDocumentRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create(self, value: ApprovedDocumentInput) -> tuple[dict[str, Any], bool]:
        semantics = _document_semantics(value)
        payload_hash = _payload_hash(semantics)
        approval_proof_id = _uuid(
            "business_approval_proof_id", value.business_approval_proof_id
        )
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                existing = self._load_revision(
                    transaction.db,
                    tenant_id=semantics["tenant_id"],
                    approved_document_id=semantics["approved_document_id"],
                    document_revision=semantics["document_revision"],
                )
                if existing is not None:
                    if (
                        existing["payload_hash"] != payload_hash
                        or str(existing["business_approval_proof_id"])
                        != approval_proof_id
                    ):
                        raise _conflict(
                            "Approved document revision has different immutable semantics "
                            "or final proof identity"
                        )
                    consumed_amount = self._consumed_amount(
                        transaction.db,
                        tenant_id=semantics["tenant_id"],
                        envelope_id=str(existing["envelope_id"]),
                    )
                    return (
                        _projection(
                            existing,
                            now=self._now(),
                            consumed_amount=consumed_amount,
                        ),
                        False,
                    )

                company = self._load_company(transaction.db, semantics)
                proof, instance, decision = self._load_proof_bundle(
                    transaction.db,
                    tenant_id=semantics["tenant_id"],
                    approval_proof_id=approval_proof_id,
                )
                _require_exact_proof(
                    proof,
                    instance,
                    decision,
                    payload_hash=payload_hash,
                )
                approved_at = _aware_datetime("approved_at", proof["issued_at"])
                if semantics["valid_from"] < approved_at:
                    raise _invalid(
                        "valid_from", "cannot precede final business approval proof"
                    )
                self._require_project_scope(
                    transaction.db,
                    semantics=semantics,
                    company=company,
                )
                now = self._now()
                record = {
                    **semantics,
                    "business_approval_proof_id": str(proof["approval_proof_id"]),
                    "scoped_document_evidence_id": None,
                    "business_proof_hash": proof["proof_hash"],
                    "approval_policy_id": str(instance["approval_policy_id"]),
                    "approval_policy_version": instance["policy_version"],
                    "approval_policy_hash": proof["policy_hash"],
                    "state": "ACTIVE",
                    "approved_at": approved_at,
                    "approved_by_ref_type": decision["decided_by_ref_type"],
                    "approved_by_id": decision["decided_by_id"],
                    "source_work_item_ref": (
                        f"wc.approval-work-item:{decision['wc_approval_work_item_id']}"
                    ),
                    "payload_hash": payload_hash,
                    "created_business_operation_id": str(
                        proof["business_operation_id"]
                    ),
                    "created_at": now,
                }
                transaction.db.execute(
                    EOS_APPROVED_DOCUMENT_TABLE.insert().values(**record)
                )
                return _projection(record, now=now), True
        except EosApprovedDocumentError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Approved document envelope identity or proof is already bound"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def create_from_scoped_evidence_in_session(
        self,
        session: Session,
        *,
        value: ApprovedDocumentInput,
        evidence: Mapping[str, Any],
        approval_policy: Mapping[str, Any],
        source_business_operation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        """Materialize one envelope from admitted scoped document evidence."""

        semantics = _document_semantics(value)
        payload_hash = _payload_hash(semantics)
        evidence_id = _uuid("evidence_id", evidence.get("evidence_id"))
        if (
            evidence.get("tenant_id") != semantics["tenant_id"]
            or evidence.get("company_id") != semantics["company_id"]
            or evidence.get("document_payload_hash") != payload_hash
        ):
            raise EosApprovedDocumentError(
                "EOS_APPROVED_DOCUMENT_PROOF_MISMATCH",
                "Scoped document evidence does not bind the exact envelope semantics",
                status_code=409,
            )
        existing = self._load_revision(
            session,
            tenant_id=semantics["tenant_id"],
            approved_document_id=semantics["approved_document_id"],
            document_revision=semantics["document_revision"],
        )
        if existing is not None:
            if (
                existing["payload_hash"] != payload_hash
                or str(existing["scoped_document_evidence_id"] or "") != evidence_id
                or existing["business_approval_proof_id"] is not None
            ):
                raise _conflict(
                    "Approved document revision has different immutable semantics "
                    "or scoped evidence identity"
                )
            return _projection(existing, now=self._now()), False

        company = self._load_company(session, semantics)
        self._require_project_scope(session, semantics=semantics, company=company)
        approved_at = _aware_datetime("approved_at", evidence["decided_at"])
        if semantics["valid_from"] < approved_at:
            raise _invalid("valid_from", "cannot precede final document approval")
        now = self._now()
        record = {
            **semantics,
            "business_approval_proof_id": None,
            "scoped_document_evidence_id": evidence_id,
            "business_proof_hash": _hash_ref("proof_hash", evidence["proof_hash"]),
            "approval_policy_id": _uuid("approval_policy_id", approval_policy["id"]),
            "approval_policy_version": _positive_int(
                "approval_policy_version", approval_policy["version"]
            ),
            "approval_policy_hash": _hash_ref(
                "approval_policy_hash", approval_policy["hash"]
            ),
            "state": "ACTIVE",
            "approved_at": approved_at,
            "approved_by_ref_type": "oa.user",
            "approved_by_id": _scoped_id(
                "approver_subject_id", evidence["approver_subject_id"], 128
            ),
            "source_work_item_ref": (
                "wc.approval-work-item:"
                f"{_uuid('wc_work_item_id', evidence['wc_work_item_id'])}"
            ),
            "payload_hash": payload_hash,
            "created_business_operation_id": _uuid(
                "created_business_operation_id", source_business_operation_id
            ),
            "created_at": now,
        }
        session.execute(EOS_APPROVED_DOCUMENT_TABLE.insert().values(**record))
        return _projection(record, now=now), True

    def get(self, *, tenant_id: str, envelope_id: str) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id, 128)
        envelope_id = _uuid("envelope_id", envelope_id)
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        select(EOS_APPROVED_DOCUMENT_TABLE).where(
                            EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id == tenant_id,
                            EOS_APPROVED_DOCUMENT_TABLE.c.envelope_id == envelope_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                consumed_amount = (
                    self._consumed_amount(
                        session,
                        tenant_id=tenant_id,
                        envelope_id=envelope_id,
                    )
                    if row is not None
                    else Decimal(0)
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return (
            _projection(row, now=self._now(), consumed_amount=consumed_amount)
            if row is not None
            else None
        )

    def get_in_session(
        self, session: Session, *, tenant_id: str, envelope_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id, 128)
        envelope_id = _uuid("envelope_id", envelope_id)
        row = (
            session.execute(
                select(EOS_APPROVED_DOCUMENT_TABLE).where(
                    EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVED_DOCUMENT_TABLE.c.envelope_id == envelope_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return _projection(
            row,
            now=self._now(),
            consumed_amount=self._consumed_amount(
                session, tenant_id=tenant_id, envelope_id=envelope_id
            ),
        )

    def _now(self) -> datetime:
        return _aware_datetime("clock", self._clock())

    @staticmethod
    def _consumed_amount(
        session: Session,
        *,
        tenant_id: str,
        envelope_id: str,
    ) -> Decimal:
        from .approved_document_consumption import (
            EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE,
        )

        value = session.execute(
            select(
                func.sum(EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.consumed_amount)
            ).where(
                EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.tenant_id == tenant_id,
                EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.envelope_id == envelope_id,
                EOS_APPROVED_DOCUMENT_CONSUMPTION_TABLE.c.state == "COMMITTED",
            )
        ).scalar_one()
        return Decimal(str(value or 0)).quantize(Decimal("0.0001"))

    @staticmethod
    def _load_revision(
        session: Session,
        *,
        tenant_id: str,
        approved_document_id: str,
        document_revision: int,
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_APPROVED_DOCUMENT_TABLE).where(
                    EOS_APPROVED_DOCUMENT_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVED_DOCUMENT_TABLE.c.approved_document_id
                    == approved_document_id,
                    EOS_APPROVED_DOCUMENT_TABLE.c.document_revision
                    == document_revision,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _load_company(
        session: Session, semantics: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        company = (
            session.execute(
                select(EOS_LEGAL_ENTITY_TABLE).where(
                    EOS_LEGAL_ENTITY_TABLE.c.tenant_id == semantics["tenant_id"],
                    EOS_LEGAL_ENTITY_TABLE.c.company_id == semantics["company_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise _not_found("LegalEntity was not found in tenant scope")
        if (
            company["status"] != "ACTIVE"
            or company["effective_from"] > semantics["valid_from"].date()
        ):
            raise _conflict("LegalEntity is not active for document validity")
        return company

    @staticmethod
    def _load_proof_bundle(
        session: Session, *, tenant_id: str, approval_proof_id: str
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        proof = (
            session.execute(
                select(EOS_APPROVAL_PROOF_TABLE).where(
                    EOS_APPROVAL_PROOF_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_PROOF_TABLE.c.approval_proof_id == approval_proof_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if proof is None:
            raise _conflict("Final BUSINESS_FORMAL approval proof was not found")
        instance = (
            session.execute(
                select(EOS_APPROVAL_INSTANCE_TABLE).where(
                    EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_INSTANCE_TABLE.c.approval_instance_id
                    == proof["approval_instance_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        decision = (
            session.execute(
                select(EOS_APPROVAL_DECISION_TABLE).where(
                    EOS_APPROVAL_DECISION_TABLE.c.tenant_id == tenant_id,
                    EOS_APPROVAL_DECISION_TABLE.c.wc_decision_id
                    == proof["final_wc_decision_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if instance is None or decision is None:
            raise _conflict("Approval proof lineage is incomplete")
        return proof, instance, decision

    @staticmethod
    def _require_project_scope(
        session: Session,
        *,
        semantics: Mapping[str, Any],
        company: Mapping[str, Any],
    ) -> None:
        del company
        project_ids = semantics["allowed_project_ids"]
        project_codes = semantics.get("allowed_project_codes", [])
        if not project_ids:
            return
        project_code_set = set(project_codes)
        for project_id in project_ids:
            project = (
                session.execute(
                    select(
                        EOS_PROJECT_TABLE.c.status,
                        EOS_PROJECT_TABLE.c.project_code,
                    ).where(
                        EOS_PROJECT_TABLE.c.tenant_id == semantics["tenant_id"],
                        EOS_PROJECT_TABLE.c.project_id == project_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            binding = session.execute(
                select(EOS_PROJECT_COMPANY_BINDING_TABLE.c.binding_id).where(
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.tenant_id
                    == semantics["tenant_id"],
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == project_id,
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.company_id
                    == semantics["company_id"],
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.state == "APPROVED",
                    EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_from
                    <= semantics["valid_from"].date(),
                    (
                        EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until.is_(None)
                        | (
                            EOS_PROJECT_COMPANY_BINDING_TABLE.c.valid_until
                            > semantics["valid_from"].date()
                        )
                    ),
                )
            ).scalar_one_or_none()
            if (
                project is None
                or project["status"] != "ACTIVE"
                or (project_codes and project["project_code"] not in project_code_set)
                or binding is None
            ):
                raise _conflict(
                    "Every approved Project ID and registration code must resolve to "
                    "one active Project bound to the company"
                )


class EosApprovedDocumentService:
    def __init__(
        self,
        repository: SqlAlchemyEosApprovedDocumentRepository,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source

    def get_approved_document(
        self,
        *,
        tenant_id: str,
        envelope_id: str,
        requester_subject_id: str,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id, 128)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id, 128
        )
        self._authorize(tenant_id=tenant_id, subject_id=requester_subject_id)
        found = self._repository.get(tenant_id=tenant_id, envelope_id=envelope_id)
        if found is None:
            raise _not_found("Approved document envelope was not found in tenant scope")
        return found

    def _authorize(self, *, tenant_id: str, subject_id: str) -> None:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied() from exc
        except Exception as exc:
            raise EosApprovedDocumentError(
                "EOS_APPROVED_DOCUMENT_AUTHORIZATION_UNAVAILABLE",
                "OA effective authorization is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        if not isinstance(value, Mapping):
            raise _denied()
        scopes = value.get("scopes")
        if (
            value.get("active") is not True
            or value.get("tenant_id") != tenant_id
            or value.get("subject_id") != subject_id
            or not isinstance(scopes, Sequence)
            or isinstance(scopes, (str, bytes))
            or FINANCE_DOCUMENT_READ_SCOPE not in scopes
        ):
            raise _denied()


def approved_document_payload_hash(value: ApprovedDocumentInput) -> str:
    return _payload_hash(_document_semantics(value))


def _payload_hash(semantics: Mapping[str, Any]) -> str:
    wire = dict(semantics)
    wire["approved_amount"] = _decimal_text(wire["approved_amount"])
    wire["valid_from"] = _timestamp(wire["valid_from"])
    wire["valid_until"] = (
        _timestamp(wire["valid_until"]) if wire["valid_until"] is not None else None
    )
    return semantic_sha256_hash_ref(
        {
            "schema_version": (
                "eos_approved_document_payload.v2"
                if wire.get("allowed_project_codes")
                else "eos_approved_document_payload.v1"
            ),
            **wire,
        }
    )


def _document_semantics(value: ApprovedDocumentInput) -> dict[str, Any]:
    if not isinstance(value, ApprovedDocumentInput):
        raise _invalid("value", "must be ApprovedDocumentInput")
    if not isinstance(value.valid_from, datetime) or value.valid_from.tzinfo is None:
        raise _invalid("valid_from", "must be a timezone-aware datetime")
    if value.valid_until is not None and (
        not isinstance(value.valid_until, datetime) or value.valid_until.tzinfo is None
    ):
        raise _invalid("valid_until", "must be a timezone-aware datetime")
    valid_from = _aware_datetime("valid_from", value.valid_from)
    valid_until = (
        _aware_datetime("valid_until", value.valid_until)
        if value.valid_until is not None
        else None
    )
    if valid_until is not None and valid_until <= valid_from:
        raise _invalid("valid_until", "must be later than valid_from")
    scope_type = _choice("scope_type", value.scope_type, APPROVED_DOCUMENT_SCOPE_TYPES)
    raw_project_ids = [
        _uuid("allowed_project_ids", item) for item in value.allowed_project_ids
    ]
    raw_project_codes = [
        _project_registration_code(item) for item in value.allowed_project_codes
    ]
    if raw_project_codes and len(raw_project_codes) != len(raw_project_ids):
        raise _invalid(
            "allowed_project_codes",
            "must contain one registration code for every Project ID",
        )
    project_ids = sorted(raw_project_ids)
    project_codes = sorted(raw_project_codes)
    if len(set(project_ids)) != len(raw_project_ids):
        raise _invalid("allowed_project_ids", "must be unique")
    if len(set(project_codes)) != len(project_codes):
        raise _invalid("allowed_project_codes", "must be unique")
    if scope_type == "COMPANY" and project_ids:
        raise _invalid("allowed_project_ids", "must be empty for COMPANY scope")
    if scope_type == "PROJECT" and len(project_ids) != 1:
        raise _invalid(
            "allowed_project_ids", "must contain one Project for PROJECT scope"
        )
    if scope_type == "PROJECT_SET" and len(project_ids) < 2:
        raise _invalid(
            "allowed_project_ids",
            "must contain at least two Projects for PROJECT_SET scope",
        )
    amount = _positive_decimal("approved_amount", value.approved_amount)
    semantics = {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id, 128),
        "envelope_id": _uuid("envelope_id", value.envelope_id),
        "company_id": _uuid("company_id", value.company_id),
        "approved_document_id": _scoped_id(
            "approved_document_id", value.approved_document_id, 128
        ),
        "document_revision": _positive_int(
            "document_revision", value.document_revision
        ),
        "document_type": _scoped_id("document_type", value.document_type, 64),
        "work_code": _work_code("work_code", value.work_code),
        "document_content_hash": _hash_ref(
            "document_content_hash", value.document_content_hash
        ),
        "attachment_manifest_hash": _hash_ref(
            "attachment_manifest_hash", value.attachment_manifest_hash
        ),
        "scope_type": scope_type,
        "project_set_hash": semantic_sha256_hash_ref(
            {
                "schema_version": "eos_approved_project_set.v2",
                "scope_type": scope_type,
                "allowed_project_ids": project_ids,
                "allowed_project_codes": project_codes,
            }
            if project_codes
            else {
                "schema_version": "eos_approved_project_set.v1",
                "scope_type": scope_type,
                "allowed_project_ids": project_ids,
            }
        ),
        "allowed_project_ids": project_ids,
        "approved_amount": amount,
        "approved_currency": _currency("approved_currency", value.approved_currency),
        "tolerance_policy_hash": (
            _hash_ref("tolerance_policy_hash", value.tolerance_policy_hash)
            if value.tolerance_policy_hash is not None
            else None
        ),
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    if project_codes:
        semantics["allowed_project_codes"] = project_codes
    return semantics


def _require_exact_proof(
    proof: Mapping[str, Any],
    instance: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    payload_hash: str,
) -> None:
    if (
        proof["approval_domain"] != "BUSINESS_FORMAL"
        or instance["state"] != "APPROVED"
        or decision["decision"] != "APPROVE"
        or decision["authorized_by_oa"] is not True
    ):
        raise _conflict("Approval proof is not a final authorized approval")
    if (
        proof["payload_hash"] != payload_hash
        or instance["payload_hash"] != payload_hash
        or instance["operation"] != APPROVED_DOCUMENT_PROTECTED_OPERATION
        or proof["policy_hash"] != instance["policy_hash"]
        or proof["business_operation_id"] != instance["business_operation_id"]
    ):
        raise EosApprovedDocumentError(
            "EOS_APPROVED_DOCUMENT_PROOF_MISMATCH",
            "Approval proof does not bind the exact document revision semantics",
            status_code=409,
        )


def _projection(
    value: Mapping[str, Any],
    *,
    now: datetime,
    consumed_amount: Decimal = Decimal(0),
) -> dict[str, Any]:
    valid_from = _aware_datetime("valid_from", value["valid_from"])
    valid_until = (
        _aware_datetime("valid_until", value["valid_until"])
        if value["valid_until"] is not None
        else None
    )
    state = value["state"]
    usable = (
        state == "ACTIVE"
        and valid_from <= now
        and (valid_until is None or now < valid_until)
    )
    effective_state = (
        "EXPIRED"
        if state == "ACTIVE" and valid_until is not None and now >= valid_until
        else state
    )
    approved = Decimal(str(value["approved_amount"])).quantize(Decimal("0.0001"))
    consumed = Decimal(str(consumed_amount)).quantize(Decimal("0.0001"))
    if consumed < 0 or consumed > approved:
        raise _unavailable()
    amount = _decimal_text(approved)
    return {
        "schema_version": (
            "eos_approved_document_envelope.v2"
            if value.get("allowed_project_codes")
            else "eos_approved_document_envelope.v1"
        ),
        "tenant_id": value["tenant_id"],
        "envelope_id": str(value["envelope_id"]),
        "company_id": str(value["company_id"]),
        "approved_document_id": value["approved_document_id"],
        "document_revision": value["document_revision"],
        "document_type": value["document_type"],
        "work_code": value["work_code"],
        "document_content_hash": value["document_content_hash"],
        "attachment_manifest_hash": value["attachment_manifest_hash"],
        "business_approval_proof_id": str(
            value["business_approval_proof_id"] or value["scoped_document_evidence_id"]
        ),
        "business_proof_hash": value["business_proof_hash"],
        "approval_policy_id": str(value["approval_policy_id"]),
        "approval_policy_version": value["approval_policy_version"],
        "approval_policy_hash": value["approval_policy_hash"],
        "scope_type": value["scope_type"],
        "project_set_hash": value["project_set_hash"],
        "allowed_project_ids": [str(item) for item in value["allowed_project_ids"]],
        **(
            {"allowed_project_codes": list(value["allowed_project_codes"])}
            if value.get("allowed_project_codes")
            else {}
        ),
        "approved_amount": amount,
        "approved_currency": value["approved_currency"],
        "remaining_amount": _decimal_text(approved - consumed),
        "tolerance_policy_hash": value["tolerance_policy_hash"],
        "valid_from": _timestamp(valid_from),
        "valid_until": _timestamp(valid_until) if valid_until is not None else None,
        "state": effective_state,
        "usable": usable,
        "approved_at": _timestamp(value["approved_at"]),
        "approved_by_principal_ref": {
            "type": value["approved_by_ref_type"],
            "id": value["approved_by_id"],
        },
        "source_work_item_ref": value["source_work_item_ref"],
        "payload_hash": value["payload_hash"],
        "created_business_operation_id": str(value["created_business_operation_id"]),
        "created_at": _timestamp(value["created_at"]),
    }


def _scoped_id(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or not _SCOPED_ID.fullmatch(value)
    ):
        raise _invalid(field, "must be a stable scoped identifier")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field, "must be a UUID") from exc


def _project_registration_code(value: object) -> str:
    normalized = str(value).strip().upper()
    if _PROJECT_REGISTRATION_CODE.fullmatch(normalized) is None:
        raise _invalid(
            "allowed_project_codes",
            "must contain approved 11-character Project registration codes",
        )
    return normalized


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field, "must be a positive integer")
    return value


def _positive_decimal(field: str, value: object) -> Decimal:
    try:
        admitted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid(field, "must be a decimal") from exc
    if not admitted.is_finite() or admitted <= 0 or admitted.as_tuple().exponent < -4:
        raise _invalid(field, "must be positive with at most four decimal places")
    return admitted.quantize(Decimal("0.0001"))


def _choice(field: str, value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _invalid(field, f"must be one of {sorted(choices)}")
    return value


def _work_code(field: str, value: object) -> str:
    if not isinstance(value, str) or not _WORK_CODE.fullmatch(value):
        raise _invalid(field, "must be an FL work code")
    return value


def _currency(field: str, value: object) -> str:
    if not isinstance(value, str) or not _CURRENCY.fullmatch(value):
        raise _invalid(field, "must be an uppercase ISO 4217 code")
    return value


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(field, "must be a sha256 hash reference") from exc


def _aware_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise _invalid(field, "must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp(value: object) -> str:
    return _aware_datetime("timestamp", value).isoformat().replace("+00:00", "Z")


def _decimal_text(value: object) -> str:
    return format(Decimal(str(value)).quantize(Decimal("0.0001")), "f")


def _invalid(field: str, detail: str) -> EosApprovedDocumentError:
    return EosApprovedDocumentError(
        "EOS_APPROVED_DOCUMENT_INVALID",
        f"{field}: {detail}",
        status_code=422,
    )


def _not_found(detail: str) -> EosApprovedDocumentError:
    return EosApprovedDocumentError(
        "EOS_APPROVED_DOCUMENT_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosApprovedDocumentError:
    return EosApprovedDocumentError(
        "EOS_APPROVED_DOCUMENT_CONFLICT", detail, status_code=409
    )


def _denied() -> EosApprovedDocumentError:
    return EosApprovedDocumentError(
        "EOS_APPROVED_DOCUMENT_AUTHORIZATION_DENIED",
        "Current finance:document:read authorization is required",
        status_code=403,
    )


def _unavailable() -> EosApprovedDocumentError:
    return EosApprovedDocumentError(
        "EOS_APPROVED_DOCUMENT_PERSISTENCE_UNAVAILABLE",
        "Approved document persistence is unavailable",
        status_code=503,
        retryable=True,
    )
