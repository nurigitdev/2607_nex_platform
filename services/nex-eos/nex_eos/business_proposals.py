from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

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
    Text,
    UniqueConstraint,
    Uuid,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_METADATA

BUSINESS_PROPOSAL_STATES = frozenset(
    {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "WITHDRAWN"}
)
BUSINESS_PROPOSAL_SCOPE_TYPES = frozenset({"COMPANY", "PROJECT", "PROJECT_SET"})

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_MONEY_QUANTUM = Decimal("0.0001")
_MAX_MONEY = Decimal("9999999999999999.9999")


EOS_BUSINESS_PROPOSAL_TABLE = Table(
    "eos_business_proposal",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("proposal_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("requester_subject_id", String(128), nullable=False),
    Column("state", String(16), nullable=False),
    Column("current_revision_no", Integer, nullable=False),
    Column("version", Integer, nullable=False),
    Column("submitted_revision_no", Integer, nullable=True),
    Column("approval_policy_id", Uuid(as_uuid=False), nullable=True),
    Column("approval_policy_hash", String(71), nullable=True),
    Column("approval_preview_hash", String(71), nullable=True),
    Column("candidate_evidence_hash", String(71), nullable=True),
    Column("approval_line_hash", String(71), nullable=True),
    Column("normalized_amount", Numeric(20, 4), nullable=True),
    Column("functional_currency", String(3), nullable=True),
    Column("normalization_hash", String(71), nullable=True),
    Column("approval_case_id", Uuid(as_uuid=False), nullable=True),
    Column("approved_envelope_id", Uuid(as_uuid=False), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=True),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    Column("withdrawn_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_business_proposal_company",
    ),
    CheckConstraint(
        "state IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'WITHDRAWN')",
        name="ck_eos_business_proposal_state",
    ),
    CheckConstraint(
        "current_revision_no > 0 AND version > 0",
        name="ck_eos_business_proposal_versions",
    ),
)
Index(
    "ix_eos_business_proposal_owner",
    EOS_BUSINESS_PROPOSAL_TABLE.c.tenant_id,
    EOS_BUSINESS_PROPOSAL_TABLE.c.requester_subject_id,
    EOS_BUSINESS_PROPOSAL_TABLE.c.state,
    EOS_BUSINESS_PROPOSAL_TABLE.c.updated_at,
)


EOS_BUSINESS_PROPOSAL_REVISION_TABLE = Table(
    "eos_business_proposal_revision",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("proposal_id", Uuid(as_uuid=False), primary_key=True),
    Column("revision_no", Integer, primary_key=True),
    Column("revision_id", Uuid(as_uuid=False), nullable=False),
    Column("predecessor_revision_no", Integer, nullable=True),
    Column("document_type", String(64), nullable=False),
    Column("work_code", String(16), nullable=False),
    Column("title", String(300), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("business_justification", Text, nullable=False),
    Column("transaction_type", String(64), nullable=False),
    Column("requested_amount", Numeric(20, 4), nullable=False),
    Column("original_currency", String(3), nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    Column("scope_type", String(16), nullable=False),
    Column("project_ids", JSON, nullable=False),
    Column("project_codes", JSON, nullable=False),
    Column("attachment_manifest", JSON, nullable=False),
    Column("content_hash", String(71), nullable=False),
    Column("attachment_manifest_hash", String(71), nullable=False),
    Column("policy_selection_input_hash", String(71), nullable=False),
    Column("created_by_subject_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id", "revision_id", name="ux_eos_business_proposal_revision_id"
    ),
    UniqueConstraint(
        "tenant_id",
        "proposal_id",
        "content_hash",
        name="ux_eos_business_proposal_content",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "proposal_id"),
        ("eos_business_proposal.tenant_id", "eos_business_proposal.proposal_id"),
        name="fk_eos_business_proposal_revision",
        ondelete="RESTRICT",
    ),
    CheckConstraint("revision_no > 0", name="ck_eos_business_proposal_revision"),
    CheckConstraint(
        "predecessor_revision_no IS NULL OR predecessor_revision_no > 0",
        name="ck_eos_business_proposal_predecessor",
    ),
    CheckConstraint("requested_amount > 0", name="ck_eos_business_proposal_amount"),
    CheckConstraint(
        "scope_type IN ('COMPANY', 'PROJECT', 'PROJECT_SET')",
        name="ck_eos_business_proposal_scope",
    ),
)


class EosBusinessProposalError(RuntimeError):
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
class BusinessProposalRevisionInput:
    tenant_id: str
    proposal_id: str
    revision_id: str
    company_id: str
    requester_subject_id: str
    document_type: str
    work_code: str
    title: str
    purpose: str
    business_justification: str
    transaction_type: str
    requested_amount: Decimal
    original_currency: str
    valid_from: datetime
    scope_type: str
    project_ids: Sequence[str]
    project_codes: Sequence[str]
    attachment_manifest: Sequence[Mapping[str, Any]] = ()
    valid_until: datetime | None = None


@dataclass(frozen=True)
class BusinessProposalSubmissionInput:
    tenant_id: str
    proposal_id: str
    requester_subject_id: str
    expected_version: int
    expected_revision: int
    content_hash: str
    approval_policy_id: str
    approval_policy_hash: str
    approval_preview_hash: str
    candidate_evidence_hash: str
    approval_line_hash: str
    normalized_amount: Decimal
    functional_currency: str
    normalization_hash: str


class SqlAlchemyEosBusinessProposalRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_draft(
        self,
        value: BusinessProposalRevisionInput,
        *,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        payload = _revision_payload(value)
        now = _instant(created_at)
        try:
            with self._session_factory.begin() as session:
                existing = self._proposal(
                    session,
                    tenant_id=payload["tenant_id"],
                    proposal_id=payload["proposal_id"],
                    for_update=True,
                )
                if existing is not None:
                    projection = self._projection(session, existing)
                    if (
                        projection["current_revision"]["content_hash"]
                        == payload["content_hash"]
                        and projection["requester_subject_id"]
                        == payload["requester_subject_id"]
                    ):
                        return projection
                    raise _conflict(
                        "Business proposal identity has different semantics"
                    )
                aggregate = {
                    "tenant_id": payload["tenant_id"],
                    "proposal_id": payload["proposal_id"],
                    "company_id": payload["company_id"],
                    "requester_subject_id": payload["requester_subject_id"],
                    "state": "DRAFT",
                    "current_revision_no": 1,
                    "version": 1,
                    "submitted_revision_no": None,
                    "approval_policy_id": None,
                    "approval_policy_hash": None,
                    "approval_preview_hash": None,
                    "candidate_evidence_hash": None,
                    "approval_line_hash": None,
                    "normalized_amount": None,
                    "functional_currency": None,
                    "normalization_hash": None,
                    "approval_case_id": None,
                    "approved_envelope_id": None,
                    "created_at": now,
                    "updated_at": now,
                    "submitted_at": None,
                    "decided_at": None,
                    "withdrawn_at": None,
                }
                session.execute(
                    EOS_BUSINESS_PROPOSAL_TABLE.insert().values(**aggregate)
                )
                self._insert_revision(
                    session,
                    aggregate=aggregate,
                    payload=payload,
                    revision_no=1,
                    predecessor_revision_no=None,
                    created_at=now,
                )
                return self._projection(session, aggregate)
        except EosBusinessProposalError:
            raise
        except IntegrityError as exc:
            raise _conflict("Business proposal identity or revision conflicts") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def revise_draft(
        self,
        value: BusinessProposalRevisionInput,
        *,
        expected_version: int,
        expected_revision: int,
        actor_subject_id: str,
    ) -> dict[str, Any]:
        payload = _revision_payload(value)
        expected_version = _positive_int("expected_version", expected_version)
        expected_revision = _positive_int("expected_revision", expected_revision)
        actor = _scoped_id("actor_subject_id", actor_subject_id)
        try:
            with self._session_factory.begin() as session:
                current = self._required_proposal(
                    session,
                    tenant_id=payload["tenant_id"],
                    proposal_id=payload["proposal_id"],
                    for_update=True,
                )
                self._require_owner(current, actor)
                current_projection = self._projection(session, current)
                if (
                    current_projection["current_revision"]["content_hash"]
                    == payload["content_hash"]
                    and int(current["version"]) == expected_version
                ):
                    return current_projection
                if current["state"] not in {"DRAFT", "REJECTED"}:
                    raise _conflict("Only a DRAFT or REJECTED proposal can be revised")
                if (
                    int(current["version"]) != expected_version
                    or int(current["current_revision_no"]) != expected_revision
                ):
                    raise _version_conflict()
                if (
                    str(current["company_id"]) != payload["company_id"]
                    or current["requester_subject_id"]
                    != payload["requester_subject_id"]
                ):
                    raise _conflict("Proposal company and requester are immutable")
                now = datetime.now(UTC)
                next_revision = expected_revision + 1
                changed = {
                    "state": "DRAFT",
                    "current_revision_no": next_revision,
                    "version": expected_version + 1,
                    "submitted_revision_no": None,
                    "approval_policy_id": None,
                    "approval_policy_hash": None,
                    "approval_preview_hash": None,
                    "candidate_evidence_hash": None,
                    "approval_line_hash": None,
                    "normalized_amount": None,
                    "functional_currency": None,
                    "normalization_hash": None,
                    "approval_case_id": None,
                    "approved_envelope_id": None,
                    "updated_at": now,
                    "submitted_at": None,
                    "decided_at": None,
                    "withdrawn_at": None,
                }
                result = session.execute(
                    update(EOS_BUSINESS_PROPOSAL_TABLE)
                    .where(
                        EOS_BUSINESS_PROPOSAL_TABLE.c.tenant_id == payload["tenant_id"],
                        EOS_BUSINESS_PROPOSAL_TABLE.c.proposal_id
                        == payload["proposal_id"],
                        EOS_BUSINESS_PROPOSAL_TABLE.c.version == expected_version,
                        EOS_BUSINESS_PROPOSAL_TABLE.c.current_revision_no
                        == expected_revision,
                    )
                    .values(**changed)
                )
                if result.rowcount != 1:
                    raise _version_conflict()
                updated = {**dict(current), **changed}
                self._insert_revision(
                    session,
                    aggregate=updated,
                    payload=payload,
                    revision_no=next_revision,
                    predecessor_revision_no=expected_revision,
                    created_at=now,
                )
                return self._projection(session, updated)
        except EosBusinessProposalError:
            raise
        except IntegrityError as exc:
            raise _conflict("Business proposal revision conflicts") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def submit(
        self,
        value: BusinessProposalSubmissionInput,
        *,
        submitted_at: datetime | None = None,
    ) -> dict[str, Any]:
        submission = _submission(value)
        now = _instant(submitted_at)
        try:
            with self._session_factory.begin() as session:
                aggregate = self._required_proposal(
                    session,
                    tenant_id=submission["tenant_id"],
                    proposal_id=submission["proposal_id"],
                    for_update=True,
                )
                self._require_owner(aggregate, submission["requester_subject_id"])
                if aggregate["state"] == "SUBMITTED":
                    if _same_submission(aggregate, submission):
                        return self._projection(session, aggregate)
                    raise _conflict("Business proposal was submitted differently")
                if aggregate["state"] != "DRAFT":
                    raise _conflict("Only a DRAFT business proposal can be submitted")
                if (
                    int(aggregate["version"]) != submission["expected_version"]
                    or int(aggregate["current_revision_no"])
                    != submission["expected_revision"]
                ):
                    raise _stale("Business proposal submit version is stale")
                revision = session.execute(
                    select(EOS_BUSINESS_PROPOSAL_REVISION_TABLE).where(
                        EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.tenant_id
                        == submission["tenant_id"],
                        EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.proposal_id
                        == submission["proposal_id"],
                        EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.revision_no
                        == submission["expected_revision"],
                    )
                ).mappings().one()
                if revision["content_hash"] != submission["content_hash"]:
                    raise _stale("Business proposal content hash is stale")
                values = {
                    "state": "SUBMITTED",
                    "version": int(aggregate["version"]) + 1,
                    "submitted_revision_no": submission["expected_revision"],
                    "approval_policy_id": submission["approval_policy_id"],
                    "approval_policy_hash": submission["approval_policy_hash"],
                    "approval_preview_hash": submission["approval_preview_hash"],
                    "candidate_evidence_hash": submission["candidate_evidence_hash"],
                    "approval_line_hash": submission["approval_line_hash"],
                    "normalized_amount": submission["normalized_amount"],
                    "functional_currency": submission["functional_currency"],
                    "normalization_hash": submission["normalization_hash"],
                    "submitted_at": now,
                    "updated_at": now,
                }
                session.execute(
                    update(EOS_BUSINESS_PROPOSAL_TABLE)
                    .where(
                        EOS_BUSINESS_PROPOSAL_TABLE.c.tenant_id
                        == submission["tenant_id"],
                        EOS_BUSINESS_PROPOSAL_TABLE.c.proposal_id
                        == submission["proposal_id"],
                    )
                    .values(**values)
                )
                return self._projection(session, {**aggregate, **values})
        except EosBusinessProposalError:
            raise
        except IntegrityError as exc:
            raise _conflict("Business proposal submission conflicts") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(
        self,
        *,
        tenant_id: str,
        proposal_id: str,
        requester_subject_id: str | None = None,
    ) -> dict[str, Any] | None:
        tenant = _scoped_id("tenant_id", tenant_id)
        proposal = _uuid("proposal_id", proposal_id)
        requester = (
            _scoped_id("requester_subject_id", requester_subject_id)
            if requester_subject_id is not None
            else None
        )
        try:
            with self._session_factory() as session:
                row = self._proposal(session, tenant_id=tenant, proposal_id=proposal)
                if row is None or (
                    requester is not None and row["requester_subject_id"] != requester
                ):
                    return None
                return self._projection(session, row)
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_owner(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        states: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        tenant = _scoped_id("tenant_id", tenant_id)
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        selected_states = tuple(_state(value) for value in states)
        try:
            with self._session_factory() as session:
                statement = select(EOS_BUSINESS_PROPOSAL_TABLE).where(
                    EOS_BUSINESS_PROPOSAL_TABLE.c.tenant_id == tenant,
                    EOS_BUSINESS_PROPOSAL_TABLE.c.requester_subject_id == requester,
                )
                if selected_states:
                    statement = statement.where(
                        EOS_BUSINESS_PROPOSAL_TABLE.c.state.in_(selected_states)
                    )
                rows = session.execute(
                    statement.order_by(
                        EOS_BUSINESS_PROPOSAL_TABLE.c.updated_at.desc(),
                        EOS_BUSINESS_PROPOSAL_TABLE.c.proposal_id,
                    )
                ).mappings()
                return [self._projection(session, row) for row in rows]
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    @staticmethod
    def _insert_revision(
        session: Session,
        *,
        aggregate: Mapping[str, Any],
        payload: Mapping[str, Any],
        revision_no: int,
        predecessor_revision_no: int | None,
        created_at: datetime,
    ) -> None:
        session.execute(
            EOS_BUSINESS_PROPOSAL_REVISION_TABLE.insert().values(
                tenant_id=aggregate["tenant_id"],
                proposal_id=aggregate["proposal_id"],
                revision_no=revision_no,
                revision_id=payload["revision_id"],
                predecessor_revision_no=predecessor_revision_no,
                document_type=payload["document_type"],
                work_code=payload["work_code"],
                title=payload["title"],
                purpose=payload["purpose"],
                business_justification=payload["business_justification"],
                transaction_type=payload["transaction_type"],
                requested_amount=payload["requested_amount"],
                original_currency=payload["original_currency"],
                valid_from=payload["valid_from"],
                valid_until=payload["valid_until"],
                scope_type=payload["scope_type"],
                project_ids=payload["project_ids"],
                project_codes=payload["project_codes"],
                attachment_manifest=payload["attachment_manifest"],
                content_hash=payload["content_hash"],
                attachment_manifest_hash=payload["attachment_manifest_hash"],
                policy_selection_input_hash=payload["policy_selection_input_hash"],
                created_by_subject_id=payload["requester_subject_id"],
                created_at=created_at,
            )
        )

    @staticmethod
    def _proposal(
        session: Session,
        *,
        tenant_id: str,
        proposal_id: str,
        for_update: bool = False,
    ) -> Mapping[str, Any] | None:
        statement = select(EOS_BUSINESS_PROPOSAL_TABLE).where(
            EOS_BUSINESS_PROPOSAL_TABLE.c.tenant_id == tenant_id,
            EOS_BUSINESS_PROPOSAL_TABLE.c.proposal_id == proposal_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return session.execute(statement).mappings().one_or_none()

    def _required_proposal(
        self,
        session: Session,
        *,
        tenant_id: str,
        proposal_id: str,
        for_update: bool = False,
    ) -> Mapping[str, Any]:
        row = self._proposal(
            session,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            for_update=for_update,
        )
        if row is None:
            raise EosBusinessProposalError(
                "BUSINESS_PROPOSAL_NOT_FOUND",
                "Business proposal was not found in tenant scope",
                status_code=404,
            )
        return row

    @staticmethod
    def _require_owner(row: Mapping[str, Any], actor_subject_id: str) -> None:
        if row["requester_subject_id"] != actor_subject_id:
            raise EosBusinessProposalError(
                "BUSINESS_PROPOSAL_FORBIDDEN",
                "Only the proposal requester can revise the draft",
                status_code=403,
            )

    @staticmethod
    def _projection(session: Session, aggregate: Mapping[str, Any]) -> dict[str, Any]:
        revision = (
            session.execute(
                select(EOS_BUSINESS_PROPOSAL_REVISION_TABLE).where(
                    EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.tenant_id
                    == aggregate["tenant_id"],
                    EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.proposal_id
                    == aggregate["proposal_id"],
                    EOS_BUSINESS_PROPOSAL_REVISION_TABLE.c.revision_no
                    == aggregate["current_revision_no"],
                )
            )
            .mappings()
            .one()
        )
        return {
            **_wire_aggregate(aggregate),
            "current_revision": _wire_revision(revision),
        }


def _revision_payload(value: BusinessProposalRevisionInput) -> dict[str, Any]:
    if not isinstance(value, BusinessProposalRevisionInput):
        raise _invalid("value must be BusinessProposalRevisionInput")
    tenant_id = _scoped_id("tenant_id", value.tenant_id)
    proposal_id = _uuid("proposal_id", value.proposal_id)
    revision_id = _uuid("revision_id", value.revision_id)
    company_id = _uuid("company_id", value.company_id)
    requester = _scoped_id("requester_subject_id", value.requester_subject_id)
    document_type = _bounded("document_type", value.document_type, 64)
    work_code = str(value.work_code).strip().upper()
    if not _WORK_CODE.fullmatch(work_code):
        raise _invalid("work_code must use the FL0000000 format")
    title = _bounded("title", value.title, 300)
    purpose = _bounded("purpose", value.purpose, 4000)
    justification = _bounded(
        "business_justification", value.business_justification, 12000
    )
    transaction_type = _bounded("transaction_type", value.transaction_type, 64)
    amount = _money(value.requested_amount)
    currency = str(value.original_currency).strip().upper()
    if not _CURRENCY.fullmatch(currency):
        raise _invalid("original_currency must be an ISO currency code")
    valid_from = _instant(value.valid_from)
    valid_until = _optional_instant(value.valid_until)
    if valid_until is not None and valid_until <= valid_from:
        raise _invalid("valid_until must be later than valid_from")
    scope_type = str(value.scope_type).strip().upper()
    if scope_type not in BUSINESS_PROPOSAL_SCOPE_TYPES:
        raise _invalid("scope_type is unsupported")
    project_ids = sorted({_uuid("project_id", item) for item in value.project_ids})
    project_codes = sorted({_project_code(item) for item in value.project_codes})
    _require_scope(scope_type, project_ids, project_codes)
    attachment_manifest = _attachment_manifest(value.attachment_manifest)
    attachment_hash = semantic_sha256_hash_ref(attachment_manifest)
    policy_input = {
        "tenant_id": tenant_id,
        "company_id": company_id,
        "transaction_type": transaction_type,
        "requested_amount": format(amount, "f"),
        "original_currency": currency,
        "scope_type": scope_type,
        "project_ids": project_ids,
        "project_codes": project_codes,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until else None,
    }
    semantics = {
        "schema_version": "eos_business_proposal_revision.v1",
        "tenant_id": tenant_id,
        "proposal_id": proposal_id,
        "company_id": company_id,
        "requester_subject_id": requester,
        "document_type": document_type,
        "work_code": work_code,
        "title": title,
        "purpose": purpose,
        "business_justification": justification,
        "transaction_type": transaction_type,
        "requested_amount": format(amount, "f"),
        "original_currency": currency,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until else None,
        "scope_type": scope_type,
        "project_ids": project_ids,
        "project_codes": project_codes,
        "attachment_manifest": attachment_manifest,
        "attachment_manifest_hash": attachment_hash,
        "policy_selection_input_hash": semantic_sha256_hash_ref(policy_input),
    }
    return {
        **semantics,
        "revision_id": revision_id,
        "requested_amount": amount,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "content_hash": semantic_sha256_hash_ref(semantics),
    }


def _submission(value: BusinessProposalSubmissionInput) -> dict[str, Any]:
    if not isinstance(value, BusinessProposalSubmissionInput):
        raise _invalid("value must be BusinessProposalSubmissionInput")
    currency = str(value.functional_currency).strip().upper()
    if not _CURRENCY.fullmatch(currency):
        raise _invalid("functional_currency must be an ISO currency code")
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "proposal_id": _uuid("proposal_id", value.proposal_id),
        "requester_subject_id": _scoped_id(
            "requester_subject_id", value.requester_subject_id
        ),
        "expected_version": _positive_int("expected_version", value.expected_version),
        "expected_revision": _positive_int(
            "expected_revision", value.expected_revision
        ),
        "content_hash": _hash_ref("content_hash", value.content_hash),
        "approval_policy_id": _uuid(
            "approval_policy_id", value.approval_policy_id
        ),
        "approval_policy_hash": _hash_ref(
            "approval_policy_hash", value.approval_policy_hash
        ),
        "approval_preview_hash": _hash_ref(
            "approval_preview_hash", value.approval_preview_hash
        ),
        "candidate_evidence_hash": _hash_ref(
            "candidate_evidence_hash", value.candidate_evidence_hash
        ),
        "approval_line_hash": _hash_ref(
            "approval_line_hash", value.approval_line_hash
        ),
        "normalized_amount": _money(value.normalized_amount),
        "functional_currency": currency,
        "normalization_hash": _hash_ref(
            "normalization_hash", value.normalization_hash
        ),
    }


def _same_submission(
    aggregate: Mapping[str, Any], submission: Mapping[str, Any]
) -> bool:
    return all(
        str(aggregate[field]) == str(submission[field])
        for field in (
            "approval_policy_id",
            "approval_policy_hash",
            "approval_preview_hash",
            "candidate_evidence_hash",
            "approval_line_hash",
            "functional_currency",
            "normalization_hash",
        )
    ) and Decimal(str(aggregate["normalized_amount"])) == submission[
        "normalized_amount"
    ]


def _attachment_manifest(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise _invalid("attachment_manifest entries must be objects")
        object_ref = _bounded("attachment.object_ref", value.get("object_ref"), 512)
        if object_ref in seen:
            raise _invalid("attachment object_ref values must be unique")
        seen.add(object_ref)
        size = _non_negative_int("attachment.size", value.get("size"))
        media_type = _bounded("attachment.media_type", value.get("media_type"), 128)
        try:
            content_hash = validate_hash_ref(value.get("content_hash"))
        except ValueError as exc:
            raise _invalid("attachment.content_hash is invalid") from exc
        manifest.append(
            {
                "object_ref": object_ref,
                "size": size,
                "media_type": media_type,
                "content_hash": content_hash,
            }
        )
    return sorted(manifest, key=lambda item: item["object_ref"])


def _require_scope(
    scope_type: str, project_ids: Sequence[str], project_codes: Sequence[str]
) -> None:
    if len(project_ids) != len(project_codes):
        raise _invalid("project_ids and project_codes must have matching counts")
    expected = {"COMPANY": 0, "PROJECT": 1}
    if scope_type in expected and len(project_ids) != expected[scope_type]:
        raise _invalid(f"{scope_type} scope has an invalid Project count")
    if scope_type == "PROJECT_SET" and len(project_ids) < 2:
        raise _invalid("PROJECT_SET scope requires at least two Projects")


def _wire_aggregate(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: (
            (item if item.tzinfo is not None else item.replace(tzinfo=UTC))
            .astimezone(UTC)
            .isoformat()
            if isinstance(item, datetime)
            else str(item)
            if isinstance(item, uuid.UUID)
            else format(item, "f")
            if isinstance(item, Decimal)
            else item
        )
        for key, item in dict(value).items()
    }


def _wire_revision(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _wire_aggregate(value)
    result["requested_amount"] = format(Decimal(str(value["requested_amount"])), "f")
    result["project_ids"] = list(value["project_ids"])
    result["project_codes"] = list(value["project_codes"])
    result["attachment_manifest"] = list(value["attachment_manifest"])
    return result


def _scoped_id(field: str, value: object) -> str:
    result = str(value or "").strip()
    if not _SCOPED_ID.fullmatch(result):
        raise _invalid(f"{field} is invalid")
    return result


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _bounded(field: str, value: object, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise _invalid(f"{field} is invalid")
    return result


def _project_code(value: object) -> str:
    result = str(value or "").strip().upper()
    if not _PROJECT_CODE.fullmatch(result):
        raise _invalid("project_code is invalid")
    return result


def _money(value: object) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(_MONEY_QUANTUM)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _invalid("requested_amount is invalid") from exc
    if result <= 0 or result > _MAX_MONEY:
        raise _invalid("requested_amount is out of range")
    return result


def _instant(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise _invalid("datetime values must be timezone-aware")
    return result.astimezone(UTC)


def _optional_instant(value: datetime | None) -> datetime | None:
    return _instant(value) if value is not None else None


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{field} must be positive")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be positive") from exc
    if result <= 0:
        raise _invalid(f"{field} must be positive")
    return result


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} is invalid") from exc


def _non_negative_int(field: str, value: object) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{field} must be non-negative")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be non-negative") from exc
    if result < 0:
        raise _invalid(f"{field} must be non-negative")
    return result


def _state(value: object) -> str:
    result = str(value or "").strip().upper()
    if result not in BUSINESS_PROPOSAL_STATES:
        raise _invalid("proposal state is unsupported")
    return result


def _invalid(detail: str) -> EosBusinessProposalError:
    return EosBusinessProposalError(
        "BUSINESS_PROPOSAL_INVALID", detail, status_code=422
    )


def _conflict(detail: str) -> EosBusinessProposalError:
    return EosBusinessProposalError(
        "BUSINESS_PROPOSAL_CONFLICT", detail, status_code=409
    )


def _stale(detail: str) -> EosBusinessProposalError:
    return EosBusinessProposalError(
        "BUSINESS_PROPOSAL_STALE", detail, status_code=409
    )


def _version_conflict() -> EosBusinessProposalError:
    return EosBusinessProposalError(
        "BUSINESS_PROPOSAL_VERSION_CONFLICT",
        "Business proposal revision or version changed",
        status_code=409,
    )


def _unavailable() -> EosBusinessProposalError:
    return EosBusinessProposalError(
        "BUSINESS_PROPOSAL_PERSISTENCE_UNAVAILABLE",
        "Business proposal persistence is unavailable",
        status_code=503,
        retryable=True,
    )
