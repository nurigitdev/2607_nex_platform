from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
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
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .approval_policies import EOS_APPROVAL_POLICY_STAGE_TABLE
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_formal_wc import WcApprovalWorkItemClient
from .business_transactions import EOS_METADATA
from .scoped_approvals import (
    EOS_SCOPED_APPROVAL_BINDING_TABLE,
    EOS_SCOPED_APPROVAL_CASE_TABLE,
    scoped_approval_case_projection,
    scoped_approval_work_item,
)

ACCOUNTING_APPROVAL_SCOPE = "finance:journal:approve"
ACCOUNTING_APPROVED_PENDING_POST = "ACCOUNTING_APPROVED_PENDING_POST"

_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_AGENT_PREFIXES = ("agent:", "job:", "service:", "nex-")
_REVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "candidate_revision",
        "candidate_hash",
        "document_envelope_hash",
        "fx_rate_set_hash",
        "rule_release_hash",
        "accounting_period_id",
        "candidate_preparer_subject_id",
        "business_approver_subject_ids",
        "original_currency",
        "original_amount",
        "market_base_rate",
        "rate_reference_date",
        "rate_publication",
        "functional_currency",
        "functional_amount",
        "fx_exception",
    }
)


EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE = Table(
    "eos_acct_approval_context",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("case_id", Uuid(as_uuid=False), primary_key=True),
    Column("candidate_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_revision", Integer, nullable=False),
    Column("candidate_hash", String(71), nullable=False),
    Column("document_envelope_hash", String(71), nullable=False),
    Column("fx_rate_set_hash", String(71), nullable=False),
    Column("rule_release_hash", String(71), nullable=False),
    Column("accounting_period_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_preparer_id", String(128), nullable=False),
    Column("business_approver_ids", JSON, nullable=False),
    Column("original_currency", String(3), nullable=False),
    Column("original_amount", Numeric(24, 6), nullable=False),
    Column("market_base_rate", Numeric(24, 10), nullable=False),
    Column("rate_reference_date", Date, nullable=False),
    Column("rate_publication", String(256), nullable=False),
    Column("functional_currency", String(3), nullable=False),
    Column("functional_amount", Numeric(24, 6), nullable=False),
    Column("fx_exception", String(512), nullable=True),
    Column("review_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "case_id"),
        ("eos_scoped_approval_case.tenant_id", "eos_scoped_approval_case.case_id"),
        name="fk_eos_acct_context_case",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id",
        "candidate_id",
        "candidate_revision",
        name="ux_eos_acct_context_candidate",
    ),
    CheckConstraint("candidate_revision > 0", name="ck_eos_acct_context_revision"),
    CheckConstraint(
        "original_amount > 0 AND market_base_rate > 0 AND functional_amount > 0",
        name="ck_eos_acct_context_amounts",
    ),
)

EOS_SCOPED_APPROVAL_DECISION_TABLE = Table(
    "eos_scoped_approval_decision",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("case_id", Uuid(as_uuid=False), primary_key=True),
    Column("stage_order", Integer, primary_key=True),
    Column("wc_work_item_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_decision_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_event_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_outbox_id", Uuid(as_uuid=False), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("decision_version", Integer, nullable=False),
    Column("decided_by", String(128), nullable=False),
    Column("decision_comment", String(2000), nullable=True),
    Column("wc_oa_decision_ref", String(128), nullable=False),
    Column("wc_authorization_revision_hash", String(71), nullable=False),
    Column("oa_decision_ref", String(128), nullable=False),
    Column("authorization_revision_hash", String(71), nullable=False),
    Column("authorization_checked_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("decision_hash", String(71), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "case_id"),
        ("eos_scoped_approval_case.tenant_id", "eos_scoped_approval_case.case_id"),
        name="fk_eos_scoped_decision_case",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id", "wc_work_item_id", name="ux_eos_scoped_decision_work_item"
    ),
    UniqueConstraint(
        "tenant_id", "wc_decision_id", name="ux_eos_scoped_decision_decision"
    ),
    UniqueConstraint("tenant_id", "wc_event_id", name="ux_eos_scoped_decision_event"),
    CheckConstraint(
        "decision IN ('APPROVE', 'REJECT')", name="ck_eos_scoped_decision_value"
    ),
    CheckConstraint("stage_order > 0", name="ck_eos_scoped_decision_stage"),
    CheckConstraint("decision_version = 1", name="ck_eos_scoped_decision_version"),
)

EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE = Table(
    "eos_accounting_approval_evidence",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("case_id", Uuid(as_uuid=False), primary_key=True),
    Column("evidence_id", Uuid(as_uuid=False), nullable=False),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_revision", Integer, nullable=False),
    Column("candidate_hash", String(71), nullable=False),
    Column("document_envelope_hash", String(71), nullable=False),
    Column("fx_rate_set_hash", String(71), nullable=False),
    Column("rule_release_hash", String(71), nullable=False),
    Column("accounting_period_id", Uuid(as_uuid=False), nullable=False),
    Column("approver_subject_id", String(128), nullable=False),
    Column("approval_policy_hash", String(71), nullable=False),
    Column("wc_final_decision_id", Uuid(as_uuid=False), nullable=False),
    Column("oa_authorization_revision_hash", String(71), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("proof_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "case_id"),
        ("eos_scoped_approval_case.tenant_id", "eos_scoped_approval_case.case_id"),
        name="fk_eos_acct_evidence_case",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "evidence_id", name="ux_eos_acct_evidence_id"),
    UniqueConstraint(
        "tenant_id",
        "candidate_id",
        "candidate_revision",
        name="ux_eos_acct_evidence_candidate",
    ),
)


class EosAccountingApprovalError(RuntimeError):
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


class SqlAlchemyAccountingReviewContextRepository:
    def __init__(self, session_factory: sessionmaker[Session], *, clock=None) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_in_session(
        self,
        session: Session,
        *,
        scoped_case: Mapping[str, Any],
        review: Mapping[str, Any],
    ) -> dict[str, Any]:
        admitted = admit_accounting_review(review)
        _require_review_case_binding(scoped_case, admitted)
        record = _review_record(
            tenant_id=str(scoped_case["tenant_id"]),
            case_id=str(scoped_case["case_id"]),
            review=admitted,
            created_at=_aware_datetime("clock", self._clock()),
        )
        existing = _load_review(
            session,
            tenant_id=record["tenant_id"],
            case_id=record["case_id"],
        )
        if existing is not None:
            if existing["review_hash"] != record["review_hash"]:
                raise _conflict("Accounting review replay changed immutable semantics")
            return _review_projection(existing)
        try:
            session.execute(
                EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.insert().values(**record)
            )
        except IntegrityError as exc:
            raise _conflict(
                "Accounting review identity or candidate revision conflicts"
            ) from exc
        return _review_projection(record)


class EosAccountingApprovalService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        authorization_source: AuthorizationSource,
        wc_client: WcApprovalWorkItemClient,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._authorization_source = authorization_source
        self._wc_client = wc_client
        self._clock = clock or (lambda: datetime.now(UTC))

    def ingest_wc_delivery(self, delivery: Mapping[str, Any]) -> dict[str, Any]:
        admitted = _admit_delivery(delivery)
        replay = self._load_replay(admitted)
        if replay is not None:
            return self._receipt(admitted, replay, created=False)

        authorization = self._authorize(admitted)
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
                review = _load_review(
                    session,
                    tenant_id=admitted["tenant_id"],
                    case_id=admitted["case_id"],
                )
                if review is None:
                    raise _conflict(
                        "Accounting approval requires an immutable review context"
                    )
                _require_case_decision_boundary(case, bindings, review, admitted)
                _require_separation_of_duties(case, review, admitted["decided_by"])
                _require_current_authorization(
                    authorization,
                    case=case,
                    decided_by=admitted["decided_by"],
                )
                existing = _load_decision_by_identity(session, admitted)
                if existing is not None:
                    if existing["decision_hash"] != admitted["decision_hash"]:
                        raise _conflict(
                            "WC decision replay changed immutable accounting semantics"
                        )
                    created = False
                else:
                    _reject_conflicting_stage_decision(session, case, admitted)
                    decision_record = _decision_record(
                        admitted,
                        authorization=authorization,
                        recorded_at=recorded_at,
                    )
                    session.execute(
                        EOS_SCOPED_APPROVAL_DECISION_TABLE.insert().values(
                            **decision_record
                        )
                    )
                    _advance_case(
                        session,
                        case=case,
                        admitted=admitted,
                        review=review,
                        authorization=authorization,
                        recorded_at=recorded_at,
                    )
                    created = True
        except EosAccountingApprovalError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Accounting approval decision changed concurrently"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

        state = self._load_state(admitted)
        return self._receipt(admitted, state, created=created)

    def _authorize(self, admitted: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=admitted["tenant_id"],
                subject_id=admitted["decided_by"],
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied("OA denied the accounting approver") from exc
        except Exception as exc:
            raise _unavailable("OA effective authorization is unavailable") from exc
        if not isinstance(value, Mapping):
            raise _denied("OA accounting authorization is malformed")
        return dict(value)

    def _load_replay(self, admitted: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                existing = _load_decision_by_identity(session, admitted)
                if existing is None:
                    return None
                if existing["decision_hash"] != admitted["decision_hash"]:
                    raise _conflict(
                        "WC decision replay changed immutable accounting semantics"
                    )
        except EosAccountingApprovalError:
            raise
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
                evidence = _load_evidence(
                    session,
                    tenant_id=admitted["tenant_id"],
                    case_id=admitted["case_id"],
                )
                review = _load_review(
                    session,
                    tenant_id=admitted["tenant_id"],
                    case_id=admitted["case_id"],
                )
                if review is None:
                    raise _conflict(
                        "Accounting approval requires an immutable review context"
                    )
                return {
                    "case": scoped_approval_case_projection(case, bindings),
                    "review": _review_projection(review),
                    "evidence": (
                        _evidence_projection(evidence) if evidence is not None else None
                    ),
                }
        except EosAccountingApprovalError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

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
                scoped_case,
                accounting_review=state["review"],
            )
            try:
                publication = self._wc_client.create_or_get(expected)
            except Exception as exc:
                raise _unavailable("WC next-stage publication is unavailable") from exc
            _require_wc_publication(publication, expected)
        return {
            "schema_version": "eos_accounting_approval_decision_receipt.v2",
            "created": created,
            "outbox_id": admitted["wc_outbox_id"],
            "event_id": admitted["wc_event_id"],
            "approval_domain": "BUSINESS_FORMAL",
            "purpose": "ACCOUNTING_POSTING",
            "case_id": admitted["case_id"],
            "case_state": scoped_case["state"],
            "observation_state": (
                ACCOUNTING_APPROVED_PENDING_POST
                if scoped_case["state"] == "APPROVED"
                else scoped_case["state"]
            ),
            "next_stage_publication": publication,
            "accounting_approval_evidence": state["evidence"],
        }


def admit_accounting_review(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REVIEW_FIELDS:
        raise _invalid("accounting_review fields do not match the admitted contract")
    if value.get("schema_version") != "eos_accounting_review_context.v2":
        raise _invalid("accounting_review schema_version is invalid")
    business_approvers = _subject_ids(
        "business_approver_subject_ids", value.get("business_approver_subject_ids")
    )
    original_currency = _currency("original_currency", value.get("original_currency"))
    functional_currency = _currency(
        "functional_currency", value.get("functional_currency")
    )
    market_rate = _positive_decimal("market_base_rate", value.get("market_base_rate"))
    original_amount = _positive_decimal("original_amount", value.get("original_amount"))
    functional_amount = _positive_decimal(
        "functional_amount", value.get("functional_amount")
    )
    reference_date = _date("rate_reference_date", value.get("rate_reference_date"))
    return {
        "schema_version": "eos_accounting_review_context.v2",
        "candidate_id": _uuid("candidate_id", value.get("candidate_id")),
        "candidate_revision": _positive_int(
            "candidate_revision", value.get("candidate_revision")
        ),
        "candidate_hash": _hash_ref("candidate_hash", value.get("candidate_hash")),
        "document_envelope_hash": _hash_ref(
            "document_envelope_hash", value.get("document_envelope_hash")
        ),
        "fx_rate_set_hash": _hash_ref(
            "fx_rate_set_hash", value.get("fx_rate_set_hash")
        ),
        "rule_release_hash": _hash_ref(
            "rule_release_hash", value.get("rule_release_hash")
        ),
        "accounting_period_id": _uuid(
            "accounting_period_id", value.get("accounting_period_id")
        ),
        "candidate_preparer_subject_id": _scoped_id(
            "candidate_preparer_subject_id",
            value.get("candidate_preparer_subject_id"),
            128,
        ),
        "business_approver_subject_ids": business_approvers,
        "original_currency": original_currency,
        "original_amount": _decimal_text(original_amount),
        "market_base_rate": _decimal_text(market_rate),
        "rate_reference_date": reference_date.isoformat(),
        "rate_publication": _text(
            "rate_publication", value.get("rate_publication"), 256
        ),
        "functional_currency": functional_currency,
        "functional_amount": _decimal_text(functional_amount),
        "fx_exception": _optional_text("fx_exception", value.get("fx_exception"), 512),
    }


def accounting_review_hash(review: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(admit_accounting_review(review))


def _review_record(
    *,
    tenant_id: str,
    case_id: str,
    review: Mapping[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "case_id": case_id,
        "candidate_id": review["candidate_id"],
        "candidate_revision": review["candidate_revision"],
        "candidate_hash": review["candidate_hash"],
        "document_envelope_hash": review["document_envelope_hash"],
        "fx_rate_set_hash": review["fx_rate_set_hash"],
        "rule_release_hash": review["rule_release_hash"],
        "accounting_period_id": review["accounting_period_id"],
        "candidate_preparer_id": review["candidate_preparer_subject_id"],
        "business_approver_ids": review["business_approver_subject_ids"],
        "original_currency": review["original_currency"],
        "original_amount": Decimal(review["original_amount"]),
        "market_base_rate": Decimal(review["market_base_rate"]),
        "rate_reference_date": date.fromisoformat(review["rate_reference_date"]),
        "rate_publication": review["rate_publication"],
        "functional_currency": review["functional_currency"],
        "functional_amount": Decimal(review["functional_amount"]),
        "fx_exception": review["fx_exception"],
        "review_hash": semantic_sha256_hash_ref(review),
        "created_at": created_at,
    }


def _review_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "eos_accounting_review_context.v2",
        "tenant_id": value["tenant_id"],
        "case_id": str(value["case_id"]),
        "candidate_id": str(value["candidate_id"]),
        "candidate_revision": value["candidate_revision"],
        "candidate_hash": value["candidate_hash"],
        "document_envelope_hash": value["document_envelope_hash"],
        "fx_rate_set_hash": value["fx_rate_set_hash"],
        "rule_release_hash": value["rule_release_hash"],
        "accounting_period_id": str(value["accounting_period_id"]),
        "candidate_preparer_subject_id": value["candidate_preparer_id"],
        "business_approver_subject_ids": list(value["business_approver_ids"]),
        "original_currency": value["original_currency"],
        "original_amount": _decimal_text(Decimal(value["original_amount"])),
        "market_base_rate": _decimal_text(Decimal(value["market_base_rate"])),
        "rate_reference_date": value["rate_reference_date"].isoformat(),
        "rate_publication": value["rate_publication"],
        "functional_currency": value["functional_currency"],
        "functional_amount": _decimal_text(Decimal(value["functional_amount"])),
        "fx_exception": value["fx_exception"],
        "review_hash": value["review_hash"],
    }


def _admit_delivery(value: Mapping[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != "wc_approval_delivery.v1"
    ):
        raise _invalid("WC approval delivery schema is invalid")
    outbox_id = _uuid("outbox_id", value.get("outbox_id"))
    work_item = _mapping("work_item", value.get("work_item"))
    decision = _mapping("decision", value.get("decision"))
    event = _mapping("event", value.get("event"))
    resume_target = _text("resume_target_ref", work_item.get("resume_target_ref"), 256)
    prefix = "eos.scoped-approval-case:"
    if not resume_target.startswith(prefix) or ":stage:" not in resume_target:
        raise _invalid("WC delivery does not target a scoped approval case")
    identity, _, stage_text = resume_target.removeprefix(prefix).partition(":stage:")
    case_id = _uuid("case_id", identity)
    stage_order = _positive_int("stage_order", stage_text)
    tenant_id = _scoped_id("tenant_id", event.get("tenant_id"), 128)
    work_item_id = _uuid("approval_work_item_id", event.get("approval_work_item_id"))
    decision_id = _uuid("decision_id", event.get("decision_id"))
    expected_event_type = "BUSINESS_FORMAL_APPROVAL_DECIDED"
    expected = {
        "work_item.tenant_id": (work_item.get("tenant_id"), tenant_id),
        "decision.tenant_id": (decision.get("tenant_id"), tenant_id),
        "work_item.approval_domain": (
            work_item.get("approval_domain"),
            "BUSINESS_FORMAL",
        ),
        "event.approval_domain": (event.get("approval_domain"), "BUSINESS_FORMAL"),
        "event.event_type": (event.get("event_type"), expected_event_type),
        "work_item.approval_work_item_id": (
            work_item.get("approval_work_item_id"),
            work_item_id,
        ),
        "decision.approval_work_item_id": (
            decision.get("approval_work_item_id"),
            work_item_id,
        ),
        "decision.decision_id": (decision.get("decision_id"), decision_id),
    }
    for field, (actual, bound) in expected.items():
        if actual != bound:
            raise _invalid(f"{field} lineage differs")
    action = decision.get("decision")
    if action not in {"APPROVE", "REJECT"} or event.get("decision") != action:
        raise _invalid("WC decision action lineage differs")
    expected_state = "APPROVED" if action == "APPROVE" else "REJECTED"
    if work_item.get("state") != expected_state:
        raise _invalid("WC work-item terminal state differs from decision")
    if decision.get("schema_version") != "wc_approval_decision.v1":
        raise _invalid("WC decision schema is invalid")
    if event.get("schema_version") != "wc_approval_event.v1":
        raise _invalid("WC event schema is invalid")
    if decision.get("authorized_by_oa") is not True:
        raise _invalid("WC decision lacks OA authorization")
    decision_version = _positive_int(
        "decision_version", decision.get("decision_version")
    )
    if decision_version != 1:
        raise _invalid("WC decision version is unsupported")
    decided_by = _scoped_id("decided_by", decision.get("decided_by"), 128)
    if event.get("decided_by") != decided_by:
        raise _invalid("WC event decision principal differs")
    if decided_by.lower().startswith(_AGENT_PREFIXES):
        raise _denied("Agent, job, and service principals cannot approve accounting")
    admitted = {
        "tenant_id": tenant_id,
        "case_id": case_id,
        "stage_order": stage_order,
        "wc_work_item_id": work_item_id,
        "wc_decision_id": decision_id,
        "wc_event_id": _uuid("event_id", event.get("event_id")),
        "wc_outbox_id": outbox_id,
        "work_item": work_item,
        "decision": action,
        "decision_version": decision_version,
        "decided_by": decided_by,
        "decision_comment": _optional_text(
            "decision_comment", decision.get("decision_comment"), 2000
        ),
        "wc_oa_decision_ref": _scoped_id(
            "oa_decision_ref", decision.get("oa_decision_ref"), 128
        ),
        "wc_authorization_revision_hash": _hash_ref(
            "authorization_revision_hash",
            decision.get("authorization_revision_hash"),
        ),
        "wc_authorization_checked_at": _datetime(
            "authorization_checked_at", decision.get("authorization_checked_at")
        ),
        "decided_at": _datetime("decided_at", decision.get("decided_at")),
        "correlation_id": _scoped_id(
            "correlation_id", event.get("correlation_id"), 128
        ),
        "causation_id": _scoped_id("causation_id", event.get("causation_id"), 128),
    }
    if event.get("occurred_at") != decision.get("decided_at"):
        raise _invalid("WC decision and event timestamps differ")
    admitted["decision_hash"] = _delivery_decision_hash(admitted)
    return admitted


def _delivery_decision_hash(value: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {
            "schema_version": "eos_scoped_approval_decision_binding.v2",
            **{
                key: value[key]
                for key in (
                    "tenant_id",
                    "case_id",
                    "stage_order",
                    "wc_work_item_id",
                    "wc_decision_id",
                    "wc_event_id",
                    "wc_outbox_id",
                    "decision",
                    "decision_version",
                    "decided_by",
                    "decision_comment",
                    "wc_oa_decision_ref",
                    "wc_authorization_revision_hash",
                    "correlation_id",
                    "causation_id",
                )
            },
            "wc_work_item_semantic_hash": value["work_item"].get("semantic_hash"),
            "decided_at": value["decided_at"].isoformat(),
        }
    )


def _require_case_decision_boundary(
    case: Mapping[str, Any],
    bindings: Sequence[Mapping[str, Any]],
    review: Mapping[str, Any],
    admitted: Mapping[str, Any],
) -> None:
    if case["purpose"] != "ACCOUNTING_POSTING":
        raise _conflict("DOCUMENT_SIGNOFF cannot satisfy accounting approval")
    if (
        case["state"] != "PENDING"
        or case["active_stage_order"] != admitted["stage_order"]
    ):
        raise _conflict("WC decision is delayed, out of order, or case is terminal")
    if (
        case["expires_at"] is not None
        and _persisted_datetime(case["expires_at"]) <= admitted["decided_at"]
    ):
        raise _conflict("Accounting approval case expired before the decision")
    projection = scoped_approval_case_projection(case, bindings)
    expected = scoped_approval_work_item(
        projection,
        accounting_review=_review_projection(review),
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


def _require_review_case_binding(
    case: Mapping[str, Any], review: Mapping[str, Any]
) -> None:
    if case["purpose"] != "ACCOUNTING_POSTING":
        raise _invalid("accounting_review is valid only for ACCOUNTING_POSTING")
    if case["subject_revision"] != review["candidate_revision"]:
        raise _invalid("candidate revision does not match approval subject revision")
    if case["subject_hash"] != review["candidate_hash"]:
        raise _invalid("candidate hash does not match approval subject hash")


def _require_separation_of_duties(
    case: Mapping[str, Any], review: Mapping[str, Any], approver: str
) -> None:
    if case["requester_id"] == approver:
        raise _denied("Approval requester cannot approve the accounting case")
    if review["candidate_preparer_id"] == approver:
        raise _denied("Voucher candidate preparer cannot approve the accounting case")
    business_approvers = list(review["business_approver_ids"])
    if len(business_approvers) == 1 and business_approvers[0] == approver:
        raise _denied("Sole business approver cannot also be sole accounting approver")


def _require_current_authorization(
    value: Mapping[str, Any], *, case: Mapping[str, Any], decided_by: str
) -> None:
    if value.get("active") is not True:
        raise _denied("Active OA Human authorization is required")
    if (
        value.get("tenant_id") != case["tenant_id"]
        or value.get("subject_id") != decided_by
    ):
        raise _denied("OA tenant and approver identity do not match")
    scopes = _string_set("scopes", value.get("scopes"))
    if ACCOUNTING_APPROVAL_SCOPE not in scopes:
        raise _denied("Current finance:journal:approve scope is required")
    roles = {item.lower() for item in _string_set("roles", value.get("roles"))}
    if str(case["target_role_ref"]).lower() not in roles:
        raise _denied("Current OA role does not match the accounting policy stage")
    company_ids = value.get("company_ids")
    if company_ids is not None and str(case["company_id"]) not in _string_set(
        "company_ids", company_ids
    ):
        raise _denied("OA company scope does not include the accounting company")
    revision = value.get("revision_hash")
    if (
        not isinstance(revision, str)
        or re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", revision) is None
    ):
        raise _denied("OA authorization revision is invalid")


def _decision_record(
    admitted: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    recorded_at: datetime,
) -> dict[str, Any]:
    revision = str(authorization["revision_hash"])
    revision_hash = revision if revision.startswith("sha256:") else f"sha256:{revision}"
    decision_ref = authorization.get("decision_ref") or (
        f"oa-authz:{revision_hash.removeprefix('sha256:')}"
    )
    return {
        **{
            key: admitted[key]
            for key in (
                "tenant_id",
                "case_id",
                "stage_order",
                "wc_work_item_id",
                "wc_decision_id",
                "wc_event_id",
                "wc_outbox_id",
                "decision",
                "decision_version",
                "decided_by",
                "decision_comment",
                "wc_oa_decision_ref",
                "wc_authorization_revision_hash",
                "decided_at",
                "decision_hash",
            )
        },
        "oa_decision_ref": _scoped_id("oa_decision_ref", decision_ref, 128),
        "authorization_revision_hash": revision_hash,
        "authorization_checked_at": recorded_at,
        "recorded_at": recorded_at,
    }


def _advance_case(
    session: Session,
    *,
    case: Mapping[str, Any],
    admitted: Mapping[str, Any],
    review: Mapping[str, Any],
    authorization: Mapping[str, Any],
    recorded_at: datetime,
) -> None:
    if admitted["decision"] == "REJECT":
        values = {
            "state": "REJECTED",
            "active_stage_order": None,
            "target_role_ref": None,
            "version": int(case["version"]) + 1,
            "updated_at": recorded_at,
            "decided_at": admitted["decided_at"],
        }
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
            raise _conflict("Accounting approval policy next stage is unavailable")
        values = {
            "active_stage_order": next_order,
            "target_role_ref": next_role,
            "version": int(case["version"]) + 1,
            "updated_at": recorded_at,
        }
    else:
        values = {
            "state": "APPROVED",
            "active_stage_order": None,
            "target_role_ref": None,
            "version": int(case["version"]) + 1,
            "updated_at": recorded_at,
            "decided_at": admitted["decided_at"],
        }
        _insert_evidence(
            session,
            case=case,
            review=review,
            admitted=admitted,
            authorization=authorization,
            recorded_at=recorded_at,
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
        raise _conflict("Accounting approval case changed concurrently")


def _insert_evidence(
    session: Session,
    *,
    case: Mapping[str, Any],
    review: Mapping[str, Any],
    admitted: Mapping[str, Any],
    authorization: Mapping[str, Any],
    recorded_at: datetime,
) -> None:
    revision = str(authorization["revision_hash"])
    revision_hash = revision if revision.startswith("sha256:") else f"sha256:{revision}"
    evidence_id = str(
        uuid5(
            NAMESPACE_URL,
            f"https://nex-platform.local/eos/accounting-approval/{case['tenant_id']}/{case['case_id']}",
        )
    )
    proof_semantics = {
        "schema_version": "eos_accounting_approval_evidence.v2",
        "tenant_id": case["tenant_id"],
        "case_id": str(case["case_id"]),
        "company_id": str(case["company_id"]),
        "candidate_id": str(review["candidate_id"]),
        "candidate_revision": review["candidate_revision"],
        "candidate_hash": review["candidate_hash"],
        "document_envelope_hash": review["document_envelope_hash"],
        "fx_rate_set_hash": review["fx_rate_set_hash"],
        "rule_release_hash": review["rule_release_hash"],
        "accounting_period_id": str(review["accounting_period_id"]),
        "approver_subject_id": admitted["decided_by"],
        "approval_policy_hash": case["approval_policy_hash"],
        "wc_final_decision_id": admitted["wc_decision_id"],
        "oa_authorization_revision_hash": revision_hash,
        "decided_at": admitted["decided_at"].isoformat(),
    }
    session.execute(
        EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.insert().values(
            tenant_id=case["tenant_id"],
            case_id=case["case_id"],
            evidence_id=evidence_id,
            company_id=case["company_id"],
            candidate_id=review["candidate_id"],
            candidate_revision=review["candidate_revision"],
            candidate_hash=review["candidate_hash"],
            document_envelope_hash=review["document_envelope_hash"],
            fx_rate_set_hash=review["fx_rate_set_hash"],
            rule_release_hash=review["rule_release_hash"],
            accounting_period_id=review["accounting_period_id"],
            approver_subject_id=admitted["decided_by"],
            approval_policy_hash=case["approval_policy_hash"],
            wc_final_decision_id=admitted["wc_decision_id"],
            oa_authorization_revision_hash=revision_hash,
            decided_at=admitted["decided_at"],
            proof_hash=semantic_sha256_hash_ref(proof_semantics),
            created_at=recorded_at,
        )
    )


def _evidence_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "eos_accounting_approval_evidence.v2",
        "evidence_id": str(value["evidence_id"]),
        "case_id": str(value["case_id"]),
        "company_id": str(value["company_id"]),
        "candidate_id": str(value["candidate_id"]),
        "candidate_revision": value["candidate_revision"],
        "candidate_hash": value["candidate_hash"],
        "document_envelope_hash": value["document_envelope_hash"],
        "fx_rate_set_hash": value["fx_rate_set_hash"],
        "rule_release_hash": value["rule_release_hash"],
        "accounting_period_id": str(value["accounting_period_id"]),
        "approver_subject_id": value["approver_subject_id"],
        "approval_policy_hash": value["approval_policy_hash"],
        "wc_final_decision_id": str(value["wc_final_decision_id"]),
        "oa_authorization_revision_hash": value["oa_authorization_revision_hash"],
        "decided_at": _timestamp(value["decided_at"]),
        "proof_hash": value["proof_hash"],
        "observation_state": ACCOUNTING_APPROVED_PENDING_POST,
    }


def _load_case_for_update(
    session: Session,
    *,
    tenant_id: str,
    case_id: str,
    for_update: bool = True,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    statement = select(EOS_SCOPED_APPROVAL_CASE_TABLE).where(
        EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id == tenant_id,
        EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == case_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.execute(statement).mappings().one_or_none()
    if row is None:
        return None, []
    bindings = [
        dict(item)
        for item in session.execute(
            select(EOS_SCOPED_APPROVAL_BINDING_TABLE).where(
                EOS_SCOPED_APPROVAL_BINDING_TABLE.c.tenant_id == tenant_id,
                EOS_SCOPED_APPROVAL_BINDING_TABLE.c.case_id == case_id,
            )
        ).mappings()
    ]
    return dict(row), bindings


def _load_review(session: Session, *, tenant_id: str, case_id: str):
    row = (
        session.execute(
            select(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE).where(
                EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.c.tenant_id == tenant_id,
                EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.c.case_id == case_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _load_evidence(session: Session, *, tenant_id: str, case_id: str):
    row = (
        session.execute(
            select(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE).where(
                EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.tenant_id == tenant_id,
                EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.case_id == case_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _load_decision_by_identity(
    session: Session, admitted: Mapping[str, Any]
) -> dict[str, Any] | None:
    rows = (
        session.execute(
            select(EOS_SCOPED_APPROVAL_DECISION_TABLE).where(
                EOS_SCOPED_APPROVAL_DECISION_TABLE.c.tenant_id == admitted["tenant_id"],
                (
                    (
                        EOS_SCOPED_APPROVAL_DECISION_TABLE.c.wc_decision_id
                        == admitted["wc_decision_id"]
                    )
                    | (
                        EOS_SCOPED_APPROVAL_DECISION_TABLE.c.wc_event_id
                        == admitted["wc_event_id"]
                    )
                    | (
                        EOS_SCOPED_APPROVAL_DECISION_TABLE.c.wc_work_item_id
                        == admitted["wc_work_item_id"]
                    )
                ),
            )
        )
        .mappings()
        .all()
    )
    if len(rows) > 1:
        raise _conflict("WC decision identities resolve to conflicting records")
    return dict(rows[0]) if rows else None


def _reject_conflicting_stage_decision(
    session: Session, case: Mapping[str, Any], admitted: Mapping[str, Any]
) -> None:
    existing = session.execute(
        select(EOS_SCOPED_APPROVAL_DECISION_TABLE.c.wc_decision_id).where(
            EOS_SCOPED_APPROVAL_DECISION_TABLE.c.tenant_id == case["tenant_id"],
            EOS_SCOPED_APPROVAL_DECISION_TABLE.c.case_id == case["case_id"],
            EOS_SCOPED_APPROVAL_DECISION_TABLE.c.stage_order == admitted["stage_order"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise _conflict("Accounting approval stage already has a terminal decision")


def _require_wc_publication(value: object, expected: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or not isinstance(
        value.get("work_item"), Mapping
    ):
        raise _unavailable("WC next-stage publication response is invalid")
    actual = value["work_item"]
    for field in (
        "tenant_id",
        "approval_work_item_id",
        "source_ref",
        "semantic_hash",
        "resume_target_ref",
    ):
        if actual.get(field) != expected.get(field):
            raise _unavailable("WC next-stage publication lineage differs")


def _mapping(field: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object")
    return dict(value)


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _positive_int(field: str, value: object) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a positive integer") from exc
    if isinstance(value, bool) or result < 1 or str(result) != str(value):
        raise _invalid(f"{field} must be a positive integer")
    return result


def _scoped_id(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or not _SCOPED_ID.fullmatch(value)
    ):
        raise _invalid(f"{field} is invalid")
    return value


def _text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"{field} is invalid")
    return value.strip()


def _optional_text(field: str, value: object, maximum: int) -> str | None:
    return None if value is None else _text(field, value, maximum)


def _hash_ref(field: str, value: object) -> str:
    if not isinstance(value, str) or _HASH_REF.fullmatch(value) is None:
        raise _invalid(f"{field} must be a sha256 hash reference")
    return value


def _subject_ids(field: str, value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid(f"{field} must be an array")
    result = [_scoped_id(field, item, 128) for item in value]
    if not result or len(result) != len(set(result)):
        raise _invalid(f"{field} must contain unique Human subjects")
    return sorted(result)


def _string_set(field: str, value: object) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _denied(f"OA {field} projection is invalid")
    result = {item for item in value if isinstance(item, str) and item}
    if len(result) != len(value):
        raise _denied(f"OA {field} projection is invalid")
    return result


def _currency(field: str, value: object) -> str:
    if not isinstance(value, str) or _CURRENCY.fullmatch(value) is None:
        raise _invalid(f"{field} must be an uppercase ISO currency")
    return value


def _positive_decimal(field: str, value: object) -> Decimal:
    if isinstance(value, bool):
        raise _invalid(f"{field} must be a positive decimal string")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid(f"{field} must be a positive decimal string") from exc
    if not result.is_finite() or result <= 0:
        raise _invalid(f"{field} must be positive and finite")
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _date(field: str, value: object) -> date:
    try:
        result = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be an ISO date") from exc
    return result


def _datetime(field: str, value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an ISO timestamp") from exc
    return _aware_datetime(field, parsed)


def _aware_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _persisted_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise _invalid("persisted timestamp is invalid")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp(value: object) -> str:
    return _persisted_datetime(value).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> EosAccountingApprovalError:
    return EosAccountingApprovalError(
        "EOS_ACCOUNTING_APPROVAL_INVALID", detail, status_code=422
    )


def _conflict(detail: str) -> EosAccountingApprovalError:
    return EosAccountingApprovalError(
        "EOS_ACCOUNTING_APPROVAL_CONFLICT", detail, status_code=409
    )


def _denied(detail: str) -> EosAccountingApprovalError:
    return EosAccountingApprovalError(
        "EOS_ACCOUNTING_APPROVAL_DENIED", detail, status_code=403
    )


def _not_found(detail: str) -> EosAccountingApprovalError:
    return EosAccountingApprovalError(
        "EOS_ACCOUNTING_APPROVAL_NOT_FOUND", detail, status_code=404
    )


def _unavailable(
    detail: str = "Accounting approval persistence is unavailable",
) -> EosAccountingApprovalError:
    return EosAccountingApprovalError(
        "EOS_ACCOUNTING_APPROVAL_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )


__all__ = (
    "ACCOUNTING_APPROVAL_SCOPE",
    "ACCOUNTING_APPROVED_PENDING_POST",
    "EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE",
    "EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE",
    "EOS_SCOPED_APPROVAL_DECISION_TABLE",
    "EosAccountingApprovalError",
    "EosAccountingApprovalService",
    "SqlAlchemyAccountingReviewContextRepository",
    "accounting_review_hash",
    "admit_accounting_review",
)
