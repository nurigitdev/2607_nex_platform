from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
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

from .accounting_approval import (
    EOS_SCOPED_APPROVAL_DECISION_TABLE,
    EosAccountingApprovalError,
    _admit_delivery,
    _decision_record,
    _load_case_for_update,
    _load_decision_by_identity,
    _reject_conflicting_stage_decision,
    _require_wc_publication,
)
from .approval_policies import EOS_APPROVAL_POLICY_STAGE_TABLE
from .approved_documents import (
    ApprovedDocumentInput,
    SqlAlchemyEosApprovedDocumentRepository,
    approved_document_payload_hash,
)
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_formal_wc import WcApprovalWorkItemClient
from .business_transactions import EOS_METADATA
from .scoped_approvals import (
    EOS_SCOPED_APPROVAL_CASE_TABLE,
    scoped_approval_case_projection,
    scoped_approval_work_item,
)

DOCUMENT_SIGNOFF_APPROVAL_SCOPE = "approval:decide"
DOCUMENT_SIGNOFF_CONTEXT_SCHEMA = "eos_document_signoff_context.v1"
DOCUMENT_SIGNOFF_EVIDENCE_SCHEMA = "eos_document_signoff_evidence.v1"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE = Table(
    "eos_document_signoff_context",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("case_id", Uuid(as_uuid=False), primary_key=True),
    Column("envelope_id", Uuid(as_uuid=False), nullable=False),
    Column("approved_document_id", String(128), nullable=False),
    Column("document_revision", Integer, nullable=False),
    Column("document_type", String(64), nullable=False),
    Column("work_code", String(16), nullable=False),
    Column("document_content_hash", String(71), nullable=False),
    Column("attachment_manifest_hash", String(71), nullable=False),
    Column("approved_amount", Numeric(20, 4), nullable=False),
    Column("approved_currency", String(3), nullable=False),
    Column("tolerance_policy_hash", String(71), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=True),
    Column("subject_hash", String(71), nullable=False),
    Column("document_payload_hash", String(71), nullable=False),
    Column("context_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "case_id"),
        ("eos_scoped_approval_case.tenant_id", "eos_scoped_approval_case.case_id"),
        name="fk_eos_doc_signoff_context_case",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id", "envelope_id", name="ux_eos_doc_signoff_context_envelope"
    ),
    CheckConstraint("document_revision > 0", name="ck_eos_doc_signoff_revision"),
    CheckConstraint("approved_amount > 0", name="ck_eos_doc_signoff_amount"),
)

EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE = Table(
    "eos_document_signoff_evidence",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("case_id", Uuid(as_uuid=False), primary_key=True),
    Column("evidence_id", Uuid(as_uuid=False), nullable=False),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("envelope_id", Uuid(as_uuid=False), nullable=False),
    Column("context_hash", String(71), nullable=False),
    Column("document_payload_hash", String(71), nullable=False),
    Column("approver_subject_id", String(128), nullable=False),
    Column("approval_policy_hash", String(71), nullable=False),
    Column("wc_work_item_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_final_decision_id", Uuid(as_uuid=False), nullable=False),
    Column("oa_authorization_revision_hash", String(71), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("proof_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "case_id"),
        ("eos_scoped_approval_case.tenant_id", "eos_scoped_approval_case.case_id"),
        name="fk_eos_doc_signoff_evidence_case",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "evidence_id", name="ux_eos_doc_signoff_evidence"),
    UniqueConstraint("tenant_id", "envelope_id", name="ux_eos_doc_signoff_envelope"),
)


class EosDocumentSignoffError(RuntimeError):
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


class SqlAlchemyDocumentSignoffContextRepository:
    def __init__(self, session_factory: sessionmaker[Session], *, clock=None) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_in_session(
        self,
        session: Session,
        *,
        scoped_case: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        admitted = admit_document_signoff_context(context, scoped_case=scoped_case)
        now = _aware_datetime("clock", self._clock())
        record = {**admitted, "created_at": now}
        existing = _load_context(
            session,
            tenant_id=admitted["tenant_id"],
            case_id=admitted["case_id"],
        )
        if existing is not None:
            if existing["context_hash"] != admitted["context_hash"]:
                raise _conflict("Document signoff context replay changed semantics")
            return document_signoff_context_projection(existing)
        session.execute(EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE.insert().values(**record))
        return document_signoff_context_projection(record)


class EosDocumentSignoffService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        authorization_source: AuthorizationSource,
        wc_client: WcApprovalWorkItemClient,
        document_repository: SqlAlchemyEosApprovedDocumentRepository,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._authorization_source = authorization_source
        self._wc_client = wc_client
        self._document_repository = document_repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def ingest_wc_delivery(self, delivery: Mapping[str, Any]) -> dict[str, Any]:
        try:
            admitted = _admit_delivery(delivery)
        except EosAccountingApprovalError as exc:
            raise _from_accounting_error(exc) from exc
        authorization = self._authorize(admitted)
        replay = self._load_replay(admitted)
        if replay is not None:
            return self._receipt(admitted, replay, created=False)
        recorded_at = _aware_datetime("clock", self._clock())
        try:
            with self._session_factory.begin() as session:
                case, bindings = _load_case_for_update(
                    session,
                    tenant_id=admitted["tenant_id"],
                    case_id=admitted["case_id"],
                )
                if case is None:
                    raise _not_found("Scoped approval case was not found")
                context = _load_context(
                    session,
                    tenant_id=admitted["tenant_id"],
                    case_id=admitted["case_id"],
                )
                if context is None:
                    raise _conflict(
                        "Document signoff requires an immutable document context"
                    )
                _require_document_boundary(case, bindings, context, admitted)
                _require_current_authorization(
                    authorization, case=case, decided_by=admitted["decided_by"]
                )
                existing = _load_decision_by_identity(session, admitted)
                if existing is not None:
                    if existing["decision_hash"] != admitted["decision_hash"]:
                        raise _conflict(
                            "WC decision replay changed immutable semantics"
                        )
                    created = False
                else:
                    _reject_conflicting_stage_decision(session, case, admitted)
                    session.execute(
                        EOS_SCOPED_APPROVAL_DECISION_TABLE.insert().values(
                            **_decision_record(
                                admitted,
                                authorization=authorization,
                                recorded_at=recorded_at,
                            )
                        )
                    )
                    self._advance_case(
                        session,
                        case=case,
                        bindings=bindings,
                        context=context,
                        admitted=admitted,
                        authorization=authorization,
                        recorded_at=recorded_at,
                    )
                    created = True
        except EosDocumentSignoffError:
            raise
        except EosAccountingApprovalError as exc:
            raise _from_accounting_error(exc) from exc
        except IntegrityError as exc:
            raise _conflict("Document signoff decision changed concurrently") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return self._receipt(admitted, self._load_state(admitted), created=created)

    def _authorize(self, admitted: Mapping[str, Any]) -> dict[str, Any]:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=admitted["tenant_id"], subject_id=admitted["decided_by"]
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied("OA denied the document approver") from exc
        except Exception as exc:
            raise _unavailable("OA effective authorization is unavailable") from exc
        if not isinstance(value, Mapping):
            raise _denied("OA document authorization is malformed")
        return dict(value)

    def _load_replay(self, admitted: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                existing = _load_decision_by_identity(session, admitted)
                if existing is None:
                    return None
                if existing["decision_hash"] != admitted["decision_hash"]:
                    raise _conflict("WC decision replay changed immutable semantics")
        except EosDocumentSignoffError:
            raise
        except EosAccountingApprovalError as exc:
            raise _from_accounting_error(exc) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return self._load_state(admitted)

    def _load_state(self, admitted: Mapping[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                case, bindings = _load_case_for_update(
                    session,
                    tenant_id=admitted["tenant_id"],
                    case_id=admitted["case_id"],
                    for_update=False,
                )
                if case is None:
                    raise _not_found("Scoped approval case was not found")
                context = _load_context(
                    session,
                    tenant_id=admitted["tenant_id"],
                    case_id=admitted["case_id"],
                )
                evidence = _load_evidence(
                    session,
                    tenant_id=admitted["tenant_id"],
                    case_id=admitted["case_id"],
                )
                envelope = None
                if evidence is not None:
                    envelope = self._document_repository.get_in_session(
                        session,
                        tenant_id=admitted["tenant_id"],
                        envelope_id=str(evidence["envelope_id"]),
                    )
                return {
                    "case": scoped_approval_case_projection(case, bindings),
                    "context": document_signoff_context_projection(context),
                    "evidence": (
                        document_signoff_evidence_projection(evidence)
                        if evidence is not None
                        else None
                    ),
                    "envelope": envelope,
                }
        except EosDocumentSignoffError:
            raise
        except EosAccountingApprovalError as exc:
            raise _from_accounting_error(exc) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def _advance_case(
        self,
        session: Session,
        *,
        case: Mapping[str, Any],
        bindings: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any],
        admitted: Mapping[str, Any],
        authorization: Mapping[str, Any],
        recorded_at: datetime,
    ) -> None:
        if admitted["decision"] == "REJECT":
            values = _terminal_values(case, "REJECTED", admitted, recorded_at)
        elif admitted["stage_order"] < int(case["stage_count"]):
            next_order = admitted["stage_order"] + 1
            next_role = session.execute(
                select(EOS_APPROVAL_POLICY_STAGE_TABLE.c.position_type).where(
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == case["tenant_id"],
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id
                    == case["approval_policy_id"],
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order == next_order,
                )
            ).scalar_one_or_none()
            if next_role is None:
                raise _conflict("Document approval policy next stage is unavailable")
            values = {
                "active_stage_order": next_order,
                "target_role_ref": next_role,
                "version": int(case["version"]) + 1,
                "updated_at": recorded_at,
            }
        else:
            values = _terminal_values(case, "APPROVED", admitted, recorded_at)
            evidence = _insert_evidence(
                session,
                case=case,
                context=context,
                admitted=admitted,
                authorization=authorization,
                recorded_at=recorded_at,
            )
            self._document_repository.create_from_scoped_evidence_in_session(
                session,
                value=_approved_document_input(
                    case,
                    context,
                    evidence,
                    project_ids=tuple(
                        sorted(str(item["project_id"]) for item in bindings)
                    ),
                ),
                evidence=evidence,
                approval_policy={
                    "id": str(case["approval_policy_id"]),
                    "version": case["approval_policy_version"],
                    "hash": case["approval_policy_hash"],
                },
                source_business_operation_id=str(case["created_business_operation_id"]),
            )
        result = session.execute(
            update(EOS_SCOPED_APPROVAL_CASE_TABLE)
            .where(
                EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id == case["tenant_id"],
                EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == case["case_id"],
                EOS_SCOPED_APPROVAL_CASE_TABLE.c.version == case["version"],
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise _conflict("Document approval case changed concurrently")

    def _receipt(
        self,
        admitted: Mapping[str, Any],
        state: Mapping[str, Any],
        *,
        created: bool,
    ) -> dict[str, Any]:
        scoped_case = state["case"]
        publication = None
        if scoped_case["state"] == "PENDING":
            expected = scoped_approval_work_item(
                scoped_case, document_signoff_context=state["context"]
            )
            try:
                publication = self._wc_client.create_or_get(expected)
            except Exception as exc:
                raise _unavailable("WC next-stage publication is unavailable") from exc
            try:
                _require_wc_publication(publication, expected)
            except EosAccountingApprovalError as exc:
                raise _from_accounting_error(exc) from exc
        return {
            "schema_version": "eos_document_signoff_decision_receipt.v1",
            "created": created,
            "outbox_id": admitted["wc_outbox_id"],
            "event_id": admitted["wc_event_id"],
            "approval_domain": "BUSINESS_FORMAL",
            "purpose": "DOCUMENT_SIGNOFF",
            "case_id": admitted["case_id"],
            "case_state": scoped_case["state"],
            "next_stage_publication": publication,
            "document_signoff_evidence": state["evidence"],
            "approved_document_envelope": state["envelope"],
        }


class EosScopedApprovalDecisionRouter:
    """Resolve the persisted case purpose before invoking a domain finalizer."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        accounting_service,
        document_signoff_service: EosDocumentSignoffService,
    ) -> None:
        self._session_factory = session_factory
        self._accounting_service = accounting_service
        self._document_signoff_service = document_signoff_service

    def ingest_wc_delivery(self, delivery: Mapping[str, Any]) -> dict[str, Any]:
        try:
            admitted = _admit_delivery(delivery)
            with self._session_factory() as session:
                purpose = session.execute(
                    select(EOS_SCOPED_APPROVAL_CASE_TABLE.c.purpose).where(
                        EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id
                        == admitted["tenant_id"],
                        EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == admitted["case_id"],
                    )
                ).scalar_one_or_none()
        except EosAccountingApprovalError as exc:
            raise _from_accounting_error(exc) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        if purpose == "DOCUMENT_SIGNOFF":
            return self._document_signoff_service.ingest_wc_delivery(delivery)
        if purpose == "ACCOUNTING_POSTING":
            return self._accounting_service.ingest_wc_delivery(delivery)
        if purpose is None:
            raise _not_found("Scoped approval case was not found")
        raise _conflict("Scoped approval purpose has no admitted finalizer")


def admit_document_signoff_context(
    value: Mapping[str, Any], *, scoped_case: Mapping[str, Any]
) -> dict[str, Any]:
    fields = {
        "schema_version",
        "envelope_id",
        "approved_document_id",
        "document_revision",
        "document_type",
        "work_code",
        "document_content_hash",
        "attachment_manifest_hash",
        "approved_amount",
        "approved_currency",
        "tolerance_policy_hash",
        "valid_from",
        "valid_until",
        "subject_hash",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("document_signoff_context fields do not match the contract")
    if value.get("schema_version") != DOCUMENT_SIGNOFF_CONTEXT_SCHEMA:
        raise _invalid("document_signoff_context schema is invalid")
    if scoped_case.get("purpose") != "DOCUMENT_SIGNOFF":
        raise _invalid("document_signoff_context requires DOCUMENT_SIGNOFF")
    revision = _positive_int("document_revision", value.get("document_revision"))
    subject_hash = _hash_ref("subject_hash", value.get("subject_hash"))
    if revision != scoped_case.get("subject_revision"):
        raise _invalid("document revision does not match approval subject revision")
    if subject_hash != scoped_case.get("subject_hash"):
        raise _invalid("document context does not match approval subject hash")
    context = {
        "tenant_id": scoped_case["tenant_id"],
        "case_id": scoped_case["case_id"],
        "envelope_id": _uuid("envelope_id", value.get("envelope_id")),
        "approved_document_id": _scoped_id(
            "approved_document_id", value.get("approved_document_id"), 128
        ),
        "document_revision": revision,
        "document_type": _scoped_id("document_type", value.get("document_type"), 64),
        "work_code": _work_code(value.get("work_code")),
        "document_content_hash": _hash_ref(
            "document_content_hash", value.get("document_content_hash")
        ),
        "attachment_manifest_hash": _hash_ref(
            "attachment_manifest_hash", value.get("attachment_manifest_hash")
        ),
        "approved_amount": _positive_decimal(
            "approved_amount", value.get("approved_amount")
        ),
        "approved_currency": _currency(value.get("approved_currency")),
        "tolerance_policy_hash": (
            _hash_ref("tolerance_policy_hash", value.get("tolerance_policy_hash"))
            if value.get("tolerance_policy_hash") is not None
            else None
        ),
        "valid_from": _datetime("valid_from", value.get("valid_from")),
        "valid_until": (
            _datetime("valid_until", value.get("valid_until"))
            if value.get("valid_until") is not None
            else None
        ),
        "subject_hash": subject_hash,
    }
    if (
        context["valid_until"] is not None
        and context["valid_until"] <= context["valid_from"]
    ):
        raise _invalid("valid_until must be later than valid_from")
    document_input = _approved_document_input(
        scoped_case,
        context,
        None,
        project_ids=tuple(scoped_case["project_ids"]),
    )
    context["document_payload_hash"] = approved_document_payload_hash(document_input)
    context["context_hash"] = semantic_sha256_hash_ref(
        {
            "schema_version": "eos_document_signoff_context_semantics.v1",
            **_context_wire(context),
            "company_id": scoped_case["company_id"],
            "scope_type": scoped_case["scope_type"],
            "project_ids": scoped_case["project_ids"],
        }
    )
    return context


def document_signoff_context_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_SIGNOFF_CONTEXT_SCHEMA,
        **_context_wire(value),
    }


def document_signoff_evidence_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_SIGNOFF_EVIDENCE_SCHEMA,
        "tenant_id": value["tenant_id"],
        "case_id": str(value["case_id"]),
        "evidence_id": str(value["evidence_id"]),
        "company_id": str(value["company_id"]),
        "envelope_id": str(value["envelope_id"]),
        "context_hash": value["context_hash"],
        "document_payload_hash": value["document_payload_hash"],
        "approver_subject_id": value["approver_subject_id"],
        "approval_policy_hash": value["approval_policy_hash"],
        "wc_work_item_id": str(value["wc_work_item_id"]),
        "wc_final_decision_id": str(value["wc_final_decision_id"]),
        "oa_authorization_revision_hash": value["oa_authorization_revision_hash"],
        "decided_at": _timestamp(value["decided_at"]),
        "proof_hash": value["proof_hash"],
        "created_at": _timestamp(value["created_at"]),
    }


def _require_document_boundary(case, bindings, context, admitted) -> None:
    if case["purpose"] != "DOCUMENT_SIGNOFF":
        raise _conflict("ACCOUNTING_POSTING cannot satisfy document signoff")
    if case["requester_id"] == admitted["decided_by"]:
        raise _denied("Document requester cannot approve the same document")
    if (
        case["state"] != "PENDING"
        or case["active_stage_order"] != admitted["stage_order"]
    ):
        raise _conflict("WC decision is delayed, out of order, or case is terminal")
    if (
        case["expires_at"] is not None
        and _aware_datetime("expires_at", case["expires_at"]) <= admitted["decided_at"]
    ):
        raise _conflict("Document approval case expired before the decision")
    expected = scoped_approval_work_item(
        scoped_approval_case_projection(case, bindings),
        document_signoff_context=document_signoff_context_projection(context),
    )
    for field in (
        "tenant_id",
        "approval_work_item_id",
        "approval_domain",
        "source_ref",
        "semantic_hash",
        "approval_provider_type",
        "approval_target_ref",
        "target_role_ref",
        "target_org_scope_ref",
        "target_project_scope_ref",
        "business_operation_id",
        "approval_request_id",
        "protected_request_ref",
        "resume_target_ref",
    ):
        if admitted["work_item"].get(field) != expected.get(field):
            raise _conflict(f"WC work item {field} differs from the scoped case")
    if admitted["work_item"].get("version") != expected["version"] + 1:
        raise _conflict("WC work item terminal version is out of order")


def _require_current_authorization(value, *, case, decided_by) -> None:
    if value.get("active") is not True:
        raise _denied("Active OA Human authorization is required")
    if (
        value.get("tenant_id") != case["tenant_id"]
        or value.get("subject_id") != decided_by
    ):
        raise _denied("OA tenant and approver identity do not match")
    if DOCUMENT_SIGNOFF_APPROVAL_SCOPE not in _string_set(
        "scopes", value.get("scopes")
    ):
        raise _denied("Current approval:decide scope is required")
    roles = {item.lower() for item in _string_set("roles", value.get("roles"))}
    if str(case["target_role_ref"]).lower() not in roles:
        raise _denied("Current OA role does not match the document policy stage")
    company_ids = value.get("company_ids")
    if company_ids is not None and str(case["company_id"]) not in _string_set(
        "company_ids", company_ids
    ):
        raise _denied("OA company scope does not include the document company")
    revision = value.get("revision_hash")
    if (
        not isinstance(revision, str)
        or re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", revision) is None
    ):
        raise _denied("OA authorization revision is invalid")


def _insert_evidence(session, *, case, context, admitted, authorization, recorded_at):
    evidence_id = str(
        uuid5(
            NAMESPACE_URL,
            f"https://nex-platform.local/eos/document-signoff/{case['tenant_id']}/{case['case_id']}",
        )
    )
    revision = str(authorization["revision_hash"])
    revision_hash = _hash_ref(
        "revision_hash",
        revision if revision.startswith("sha256:") else f"sha256:{revision}",
    )
    semantics = {
        "schema_version": DOCUMENT_SIGNOFF_EVIDENCE_SCHEMA,
        "tenant_id": case["tenant_id"],
        "case_id": str(case["case_id"]),
        "evidence_id": evidence_id,
        "company_id": str(case["company_id"]),
        "envelope_id": str(context["envelope_id"]),
        "context_hash": context["context_hash"],
        "document_payload_hash": context["document_payload_hash"],
        "approver_subject_id": admitted["decided_by"],
        "approval_policy_hash": case["approval_policy_hash"],
        "wc_work_item_id": admitted["wc_work_item_id"],
        "wc_final_decision_id": admitted["wc_decision_id"],
        "oa_authorization_revision_hash": revision_hash,
        "decided_at": _timestamp(admitted["decided_at"]),
    }
    record = {
        **{key: value for key, value in semantics.items() if key != "schema_version"},
        "decided_at": admitted["decided_at"],
        "proof_hash": semantic_sha256_hash_ref(semantics),
        "created_at": recorded_at,
    }
    session.execute(EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE.insert().values(**record))
    return record


def _approved_document_input(
    case, context, evidence, *, project_ids: Sequence[str]
) -> ApprovedDocumentInput:
    evidence_id = (
        evidence["evidence_id"]
        if evidence is not None
        else str(
            uuid5(
                NAMESPACE_URL,
                f"https://nex-platform.local/eos/document-signoff/{case['tenant_id']}/{case['case_id']}",
            )
        )
    )
    return ApprovedDocumentInput(
        tenant_id=case["tenant_id"],
        envelope_id=str(context["envelope_id"]),
        company_id=str(case["company_id"]),
        approved_document_id=context["approved_document_id"],
        document_revision=context["document_revision"],
        document_type=context["document_type"],
        work_code=context["work_code"],
        document_content_hash=context["document_content_hash"],
        attachment_manifest_hash=context["attachment_manifest_hash"],
        business_approval_proof_id=str(evidence_id),
        scope_type=case["scope_type"],
        allowed_project_ids=tuple(project_ids),
        approved_amount=Decimal(context["approved_amount"]),
        approved_currency=context["approved_currency"],
        valid_from=_aware_datetime("valid_from", context["valid_from"]),
        valid_until=(
            _aware_datetime("valid_until", context["valid_until"])
            if context["valid_until"] is not None
            else None
        ),
        tolerance_policy_hash=context["tolerance_policy_hash"],
    )


def _context_wire(value):
    return {
        "tenant_id": value["tenant_id"],
        "case_id": str(value["case_id"]),
        "envelope_id": str(value["envelope_id"]),
        "approved_document_id": value["approved_document_id"],
        "document_revision": value["document_revision"],
        "document_type": value["document_type"],
        "work_code": value["work_code"],
        "document_content_hash": value["document_content_hash"],
        "attachment_manifest_hash": value["attachment_manifest_hash"],
        "approved_amount": _decimal_text(value["approved_amount"]),
        "approved_currency": value["approved_currency"],
        "tolerance_policy_hash": value["tolerance_policy_hash"],
        "valid_from": _timestamp(value["valid_from"]),
        "valid_until": (
            _timestamp(value["valid_until"])
            if value["valid_until"] is not None
            else None
        ),
        "subject_hash": value["subject_hash"],
        "document_payload_hash": value.get("document_payload_hash"),
        "context_hash": value.get("context_hash"),
    }


def _terminal_values(case, state, admitted, recorded_at):
    return {
        "state": state,
        "active_stage_order": None,
        "target_role_ref": None,
        "version": int(case["version"]) + 1,
        "updated_at": recorded_at,
        "decided_at": admitted["decided_at"],
    }


def _load_context(session, *, tenant_id, case_id):
    row = (
        session.execute(
            select(EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE).where(
                EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE.c.tenant_id == tenant_id,
                EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE.c.case_id == case_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _load_evidence(session, *, tenant_id, case_id):
    row = (
        session.execute(
            select(EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE).where(
                EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE.c.tenant_id == tenant_id,
                EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE.c.case_id == case_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _from_accounting_error(exc):
    return EosDocumentSignoffError(
        exc.error_code.replace("ACCOUNTING", "DOCUMENT_SIGNOFF"),
        exc.detail,
        status_code=exc.status_code,
        retryable=exc.retryable,
    )


def _uuid(field, value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _scoped_id(field, value, maximum):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or _SCOPED_ID.fullmatch(value) is None
    ):
        raise _invalid(f"{field} must be a stable scoped identifier")
    return value


def _hash_ref(field, value):
    try:
        admitted = validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a sha256 hash reference") from exc
    return admitted


def _positive_int(field, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be positive")
    return value


def _positive_decimal(field, value):
    try:
        admitted = Decimal(str(value))
    except Exception as exc:
        raise _invalid(f"{field} must be a decimal") from exc
    if not admitted.is_finite() or admitted <= 0 or admitted.as_tuple().exponent < -4:
        raise _invalid(f"{field} must be positive with at most four decimal places")
    return admitted.quantize(Decimal("0.0001"))


def _work_code(value):
    if not isinstance(value, str) or _WORK_CODE.fullmatch(value) is None:
        raise _invalid("work_code must be an FL work code")
    return value


def _currency(value):
    if not isinstance(value, str) or _CURRENCY.fullmatch(value) is None:
        raise _invalid("approved_currency must be uppercase ISO 4217")
    return value


def _datetime(field, value):
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an ISO timestamp")
    try:
        admitted = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an ISO timestamp") from exc
    if admitted.tzinfo is None:
        raise _invalid(f"{field} must include timezone")
    return admitted.astimezone(UTC)


def _aware_datetime(field, value):
    if not isinstance(value, datetime):
        raise _invalid(f"{field} must be a datetime")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _timestamp(value):
    return _aware_datetime("timestamp", value).isoformat().replace("+00:00", "Z")


def _decimal_text(value):
    return format(Decimal(str(value)).quantize(Decimal("0.0001")), "f")


def _string_set(field, value):
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _denied(f"OA {field} is invalid")
    admitted = set(value)
    if not admitted or any(not isinstance(item, str) or not item for item in admitted):
        raise _denied(f"OA {field} is invalid")
    return admitted


def _invalid(detail):
    return EosDocumentSignoffError(
        "EOS_DOCUMENT_SIGNOFF_INVALID", detail, status_code=422
    )


def _conflict(detail):
    return EosDocumentSignoffError(
        "EOS_DOCUMENT_SIGNOFF_CONFLICT", detail, status_code=409
    )


def _denied(detail):
    return EosDocumentSignoffError(
        "EOS_DOCUMENT_SIGNOFF_AUTHORIZATION_DENIED", detail, status_code=403
    )


def _not_found(detail):
    return EosDocumentSignoffError(
        "EOS_DOCUMENT_SIGNOFF_NOT_FOUND", detail, status_code=404
    )


def _unavailable(detail="Document signoff persistence is unavailable"):
    return EosDocumentSignoffError(
        "EOS_DOCUMENT_SIGNOFF_UNAVAILABLE", detail, status_code=503, retryable=True
    )


__all__ = (
    "DOCUMENT_SIGNOFF_APPROVAL_SCOPE",
    "EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE",
    "EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE",
    "EosDocumentSignoffError",
    "EosDocumentSignoffService",
    "EosScopedApprovalDecisionRouter",
    "SqlAlchemyDocumentSignoffContextRepository",
    "admit_document_signoff_context",
    "document_signoff_context_projection",
    "document_signoff_evidence_projection",
)
