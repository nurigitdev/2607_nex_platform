from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_METADATA
from .voucher_candidates import (
    EOS_VOUCHER_CANDIDATE_TABLE,
    EosVoucherCandidateError,
)

ACCOUNTING_REVIEW_CONTEXT_V3 = "eos_accounting_review_context.v3"
CANDIDATE_REVIEW_PROJECTION_VERSION = "eos_candidate_review.v1"
INVALIDATE_CANDIDATE_REVIEW_OPERATION = "FINANCE.VOUCHER_CANDIDATE.INVALIDATE_REVIEW"

EOS_CANDIDATE_REVIEW_EVENT_TABLE = Table(
    "eos_candidate_review_event",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("event_id", Uuid(as_uuid=False), primary_key=True),
    Column("candidate_id", Uuid(as_uuid=False), nullable=False),
    Column("candidate_revision", Integer, nullable=False),
    Column("candidate_hash", String(71), nullable=False),
    Column("approval_case_id", Uuid(as_uuid=False), nullable=False),
    Column("transition_kind", String(16), nullable=False),
    Column("from_state", String(32), nullable=False),
    Column("to_state", String(32), nullable=False),
    Column("expected_version", Integer, nullable=False),
    Column("resulting_version", Integer, nullable=False),
    Column("actor_subject_id", String(128), nullable=False),
    Column("reason", String(2000), nullable=True),
    Column("validation_hash", String(71), nullable=True),
    Column("review_hash", String(71), nullable=False),
    Column("event_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "candidate_id",
        "resulting_version",
        name="ux_eos_candidate_review_version",
    ),
    UniqueConstraint(
        "tenant_id",
        "approval_case_id",
        "transition_kind",
        name="ux_eos_candidate_review_transition",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "candidate_id"),
        (
            "eos_voucher_candidate.tenant_id",
            "eos_voucher_candidate.candidate_id",
        ),
        name="fk_eos_candidate_review_candidate",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "approval_case_id"),
        ("eos_scoped_approval_case.tenant_id", "eos_scoped_approval_case.case_id"),
        name="fk_eos_candidate_review_case",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "transition_kind IN ('SUBMIT', 'RETURN', 'INVALIDATE')",
        name="ck_eos_candidate_review_kind",
    ),
)
Index(
    "ix_eos_candidate_review_candidate",
    EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.tenant_id,
    EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.candidate_id,
    EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.resulting_version.desc(),
)


class EosCandidateReviewError(RuntimeError):
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


class SqlAlchemyEosCandidateReviewRepository:
    def __init__(self, session_factory: sessionmaker[Session], *, clock=None) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def submit_in_session(
        self,
        session: Session,
        *,
        scoped_case: Mapping[str, Any],
        review: Mapping[str, Any],
        validation: Mapping[str, Any],
    ) -> dict[str, Any]:
        if review.get("schema_version") != ACCOUNTING_REVIEW_CONTEXT_V3:
            raise _invalid("Authoritative candidate submission requires review v3.")
        tenant_id = str(scoped_case["tenant_id"])
        candidate_id = str(review["candidate_id"])
        event_id = _deterministic_event_id(
            tenant_id=tenant_id,
            approval_case_id=str(scoped_case["case_id"]),
            transition_kind="SUBMIT",
        )
        existing = self._event_by_id(session, tenant_id=tenant_id, event_id=event_id)
        if existing is not None:
            _require_submit_replay(existing, review=review, validation=validation)
            return _event_projection(existing)

        candidate = self._locked_candidate(
            session, tenant_id=tenant_id, candidate_id=candidate_id
        )
        _require_case_binding(scoped_case, candidate=candidate, review=review)
        _require_candidate_version(candidate, review)
        _require_validation_binding(
            validation,
            tenant_id=tenant_id,
            candidate=candidate,
            scoped_case=scoped_case,
            review=review,
        )
        if candidate["state"] not in {"DRAFT", "RETURNED_FOR_CORRECTION"}:
            raise _conflict("VoucherCandidate is not eligible for review submission.")
        created_at = _aware_datetime("clock", self._clock())
        record = _event_record(
            tenant_id=tenant_id,
            event_id=event_id,
            candidate=candidate,
            candidate_hash=str(review["candidate_hash"]),
            approval_case_id=str(scoped_case["case_id"]),
            transition_kind="SUBMIT",
            to_state="READY_FOR_REVIEW",
            actor_subject_id=str(scoped_case["requester_ref"]["id"]),
            reason=None,
            validation_hash=str(review["validation_hash"]),
            review_hash=_review_hash(review),
            created_at=created_at,
        )
        self._advance_candidate(session, candidate=candidate, record=record)
        self._insert_event(session, record)
        return _event_projection(record)

    def require_current_review_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        approval_case_id: str,
        review: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        submitted = self._event_by_case(
            session,
            tenant_id=tenant_id,
            approval_case_id=approval_case_id,
            transition_kind="SUBMIT",
        )
        if submitted is None:
            return None
        candidate = self._locked_candidate(
            session,
            tenant_id=tenant_id,
            candidate_id=str(submitted["candidate_id"]),
        )
        if candidate["state"] != "READY_FOR_REVIEW" or int(
            candidate["current_revision_no"]
        ) != int(review["candidate_revision"]):
            raise _conflict(
                "VoucherCandidate review is stale and cannot admit a WC decision."
            )
        if int(submitted["candidate_revision"]) != int(
            review["candidate_revision"]
        ) or str(submitted["candidate_hash"]) != str(review["candidate_hash"]):
            raise _conflict(
                "Accounting review no longer matches the submitted Candidate."
            )
        return {"candidate": candidate, "submitted_event": submitted}

    def return_from_rejection_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        approval_case_id: str,
        review: Mapping[str, Any],
        actor_subject_id: str,
        reason: object,
        decided_at: datetime,
    ) -> dict[str, Any] | None:
        event_id = _deterministic_event_id(
            tenant_id=tenant_id,
            approval_case_id=approval_case_id,
            transition_kind="RETURN",
        )
        existing = self._event_by_id(session, tenant_id=tenant_id, event_id=event_id)
        normalized_actor = _subject_id(actor_subject_id)
        normalized_reason = _reason(reason)
        if existing is not None:
            if (
                str(existing["actor_subject_id"]) != normalized_actor
                or str(existing["reason"]) != normalized_reason
                or str(existing["approval_case_id"]) != approval_case_id
            ):
                raise _conflict("Candidate return replay changed immutable semantics.")
            return _event_projection(existing)

        current = self.require_current_review_in_session(
            session,
            tenant_id=tenant_id,
            approval_case_id=approval_case_id,
            review=review,
        )
        if current is None:
            return None
        candidate = current["candidate"]
        record = _event_record(
            tenant_id=tenant_id,
            event_id=event_id,
            candidate=candidate,
            candidate_hash=str(current["submitted_event"]["candidate_hash"]),
            approval_case_id=approval_case_id,
            transition_kind="RETURN",
            to_state="RETURNED_FOR_CORRECTION",
            actor_subject_id=normalized_actor,
            reason=normalized_reason,
            validation_hash=None,
            review_hash=str(current["submitted_event"]["review_hash"]),
            created_at=_aware_datetime("decided_at", decided_at),
        )
        self._advance_candidate(session, candidate=candidate, record=record)
        self._insert_event(session, record)
        return _event_projection(record)

    def invalidate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = _invalidation_request(payload)
        try:
            with self._session_factory.begin() as session:
                existing = self._event_by_id(
                    session,
                    tenant_id=request["tenant_id"],
                    event_id=request["event_id"],
                )
                if existing is not None:
                    _require_invalidation_replay(existing, request)
                    event = _event_projection(existing)
                else:
                    submitted = self._event_by_case(
                        session,
                        tenant_id=request["tenant_id"],
                        approval_case_id=request["approval_case_id"],
                        transition_kind="SUBMIT",
                    )
                    if submitted is None:
                        raise _not_found("Submitted Candidate review was not found.")
                    candidate = self._locked_candidate(
                        session,
                        tenant_id=request["tenant_id"],
                        candidate_id=request["candidate_id"],
                    )
                    _require_invalidation_candidate(candidate, submitted, request)
                    record = _event_record(
                        tenant_id=request["tenant_id"],
                        event_id=request["event_id"],
                        candidate=candidate,
                        candidate_hash=request["expected_candidate_hash"],
                        approval_case_id=request["approval_case_id"],
                        transition_kind="INVALIDATE",
                        to_state="RETURNED_FOR_CORRECTION",
                        actor_subject_id=request["actor_subject_id"],
                        reason=request["reason"],
                        validation_hash=None,
                        review_hash=str(submitted["review_hash"]),
                        created_at=request["invalidated_at"],
                    )
                    self._advance_candidate(session, candidate=candidate, record=record)
                    self._insert_event(session, record)
                    event = _event_projection(record)
        except EosCandidateReviewError:
            raise
        except (IntegrityError, EosVoucherCandidateError) as exc:
            raise _conflict(
                "Candidate review invalidation changed concurrently."
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return event

    def get(self, *, tenant_id: str, candidate_id: str) -> dict[str, Any] | None:
        tenant_id = _tenant_id(tenant_id)
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
                events = (
                    session.execute(
                        select(EOS_CANDIDATE_REVIEW_EVENT_TABLE)
                        .where(
                            EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.tenant_id == tenant_id,
                            EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.candidate_id
                            == candidate_id,
                        )
                        .order_by(EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.resulting_version)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return {
            "schema_version": CANDIDATE_REVIEW_PROJECTION_VERSION,
            "tenant_id": tenant_id,
            "candidate_id": candidate_id,
            "state": candidate["state"],
            "candidate_version": candidate["version"],
            "current_revision_no": candidate["current_revision_no"],
            "events": [_event_projection(row) for row in events],
        }

    @staticmethod
    def _locked_candidate(
        session: Session, *, tenant_id: str, candidate_id: str
    ) -> Mapping[str, Any]:
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
            raise _not_found("VoucherCandidate was not found in tenant scope.")
        return candidate

    @staticmethod
    def _event_by_id(
        session: Session, *, tenant_id: str, event_id: str
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_CANDIDATE_REVIEW_EVENT_TABLE).where(
                    EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.tenant_id == tenant_id,
                    EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.event_id == event_id,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _event_by_case(
        session: Session,
        *,
        tenant_id: str,
        approval_case_id: str,
        transition_kind: str,
    ) -> Mapping[str, Any] | None:
        return (
            session.execute(
                select(EOS_CANDIDATE_REVIEW_EVENT_TABLE).where(
                    EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.tenant_id == tenant_id,
                    EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.approval_case_id
                    == approval_case_id,
                    EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.transition_kind
                    == transition_kind,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _advance_candidate(
        session: Session,
        *,
        candidate: Mapping[str, Any],
        record: Mapping[str, Any],
    ) -> None:
        result = session.execute(
            update(EOS_VOUCHER_CANDIDATE_TABLE)
            .where(
                EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == candidate["tenant_id"],
                EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == candidate["candidate_id"],
                EOS_VOUCHER_CANDIDATE_TABLE.c.state == candidate["state"],
                EOS_VOUCHER_CANDIDATE_TABLE.c.version == candidate["version"],
            )
            .values(
                state=record["to_state"],
                version=record["resulting_version"],
                updated_at=record["created_at"],
            )
        )
        if result.rowcount != 1:
            raise _conflict("VoucherCandidate review state changed concurrently.")

    @staticmethod
    def _insert_event(session: Session, record: Mapping[str, Any]) -> None:
        try:
            session.execute(EOS_CANDIDATE_REVIEW_EVENT_TABLE.insert().values(**record))
        except IntegrityError as exc:
            raise _conflict(
                "Candidate review transition conflicts with prior evidence."
            ) from exc


def _require_case_binding(
    scoped_case: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    review: Mapping[str, Any],
) -> None:
    candidate_id = str(candidate["candidate_id"])
    if (
        scoped_case["purpose"] != "ACCOUNTING_POSTING"
        or scoped_case["subject_ref"] != f"eos.voucher-candidate:{candidate_id}"
        or int(scoped_case["subject_revision"]) != int(review["candidate_revision"])
        or scoped_case["subject_hash"] != review["candidate_hash"]
        or str(scoped_case["company_id"]) != str(candidate["company_id"])
        or [str(item) for item in scoped_case["project_ids"]]
        != [str(candidate["project_id"])]
        or str(candidate["preparer_subject_id"])
        != str(review["candidate_preparer_subject_id"])
    ):
        raise _conflict("Accounting approval case does not match VoucherCandidate.")


def _require_candidate_version(
    candidate: Mapping[str, Any], review: Mapping[str, Any]
) -> None:
    if int(candidate["version"]) != int(review["candidate_version"]) or int(
        candidate["current_revision_no"]
    ) != int(review["candidate_revision"]):
        raise _conflict("VoucherCandidate version or revision changed before submit.")


def _require_validation_binding(
    validation: Mapping[str, Any],
    *,
    tenant_id: str,
    candidate: Mapping[str, Any],
    scoped_case: Mapping[str, Any],
    review: Mapping[str, Any],
) -> None:
    fx = validation.get("fx_evidence")
    totals = validation.get("totals")
    revision = validation.get("revision_ref")
    project = validation.get("project_ref")
    document = validation.get("document_ref")
    candidate_ref = validation.get("candidate_ref")
    if not all(
        isinstance(value, Mapping)
        for value in (fx, totals, revision, project, document, candidate_ref)
    ):
        raise _conflict("Candidate validation evidence is incomplete.")
    expected = (
        validation.get("schema_version") == "eos_voucher_candidate_validation.v1"
        and validation.get("status") == "PASS"
        and validation.get("tenant_id") == tenant_id
        and str(candidate_ref.get("id")) == str(candidate["candidate_id"])
        and int(validation.get("candidate_version")) == int(candidate["version"])
        and int(revision.get("revision_no")) == int(review["candidate_revision"])
        and str(revision.get("hash")) == str(review["candidate_hash"])
        and validation.get("company_id") == str(candidate["company_id"])
        and project.get("id") == str(candidate["project_id"])
        and document.get("id") == str(candidate["document_envelope_id"])
        and document.get("hash") == review["document_envelope_hash"]
        and str(validation.get("accounting_period_id"))
        == str(review["accounting_period_id"])
        and validation.get("posting_rule_release_hash") == review["rule_release_hash"]
        and validation.get("fx_rate_set_hash") == review["fx_rate_set_hash"]
        and validation.get("preparer_subject_id")
        == review["candidate_preparer_subject_id"]
        and validation.get("transaction_currency") == review["original_currency"]
        and validation.get("functional_currency") == review["functional_currency"]
        and validation.get("validation_hash") == review["validation_hash"]
        and validation.get("observed_at")
        == review["validation_observed_at"].isoformat()
        and str(scoped_case["requester_ref"]["id"])
        == str(review["candidate_preparer_subject_id"])
    )
    if not expected:
        raise _conflict("Candidate validation evidence differs from review context.")
    try:
        amounts_match = (
            Decimal(str(totals["debit_original"]))
            == Decimal(str(review["original_amount"]))
            and Decimal(str(totals["debit_functional"]))
            == Decimal(str(review["functional_amount"]))
            and Decimal(str(fx["normalized_rate"]))
            == Decimal(str(review["market_base_rate"]))
        )
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise _conflict("Candidate validation amount evidence is malformed.") from exc
    if not amounts_match:
        raise _conflict("Candidate validation amounts differ from review context.")


def _event_record(
    *,
    tenant_id: str,
    event_id: str,
    candidate: Mapping[str, Any],
    candidate_hash: str,
    approval_case_id: str,
    transition_kind: str,
    to_state: str,
    actor_subject_id: str,
    reason: str | None,
    validation_hash: str | None,
    review_hash: str,
    created_at: datetime,
) -> dict[str, Any]:
    semantics = {
        "schema_version": "eos_candidate_review_event.v1",
        "tenant_id": tenant_id,
        "event_id": event_id,
        "candidate_id": str(candidate["candidate_id"]),
        "candidate_revision": int(candidate["current_revision_no"]),
        "candidate_hash": validate_hash_ref(candidate_hash),
        "approval_case_id": approval_case_id,
        "transition_kind": transition_kind,
        "from_state": str(candidate["state"]),
        "to_state": to_state,
        "expected_version": int(candidate["version"]),
        "resulting_version": int(candidate["version"]) + 1,
        "actor_subject_id": actor_subject_id,
        "reason": reason,
        "validation_hash": validation_hash,
        "review_hash": review_hash,
        "created_at": created_at.isoformat(),
    }
    record = {key: value for key, value in semantics.items() if key != "schema_version"}
    record["created_at"] = created_at
    record["event_hash"] = semantic_sha256_hash_ref(semantics)
    return record


def _event_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "eos_candidate_review_event.v1",
        "event_id": str(value["event_id"]),
        "candidate_id": str(value["candidate_id"]),
        "candidate_revision": int(value["candidate_revision"]),
        "candidate_hash": value["candidate_hash"],
        "approval_case_id": str(value["approval_case_id"]),
        "transition_kind": value["transition_kind"],
        "from_state": value["from_state"],
        "to_state": value["to_state"],
        "expected_version": int(value["expected_version"]),
        "resulting_version": int(value["resulting_version"]),
        "actor_subject_id": value["actor_subject_id"],
        "reason": value["reason"],
        "validation_hash": value["validation_hash"],
        "review_hash": value["review_hash"],
        "event_hash": value["event_hash"],
        "created_at": _timestamp(value["created_at"]),
    }


def _invalidation_request(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version",
        "tenant_id",
        "event_id",
        "candidate_id",
        "approval_case_id",
        "expected_candidate_version",
        "expected_revision_no",
        "expected_candidate_hash",
        "actor_subject_id",
        "reason",
        "invalidated_at",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Candidate review invalidation fields do not match v1.")
    if value.get("schema_version") != "eos_candidate_review_invalidate.v1":
        raise _invalid("Candidate review invalidation schema_version is invalid.")
    return {
        "tenant_id": _tenant_id(value.get("tenant_id")),
        "event_id": _uuid("event_id", value.get("event_id")),
        "candidate_id": _uuid("candidate_id", value.get("candidate_id")),
        "approval_case_id": _uuid("approval_case_id", value.get("approval_case_id")),
        "expected_candidate_version": _positive_int(
            "expected_candidate_version", value.get("expected_candidate_version")
        ),
        "expected_revision_no": _positive_int(
            "expected_revision_no", value.get("expected_revision_no")
        ),
        "expected_candidate_hash": _hash_ref(
            "expected_candidate_hash", value.get("expected_candidate_hash")
        ),
        "actor_subject_id": _subject_id(value.get("actor_subject_id")),
        "reason": _reason(value.get("reason")),
        "invalidated_at": _datetime("invalidated_at", value.get("invalidated_at")),
    }


def _require_invalidation_candidate(
    candidate: Mapping[str, Any],
    submitted: Mapping[str, Any],
    request: Mapping[str, Any],
) -> None:
    if (
        candidate["state"] != "READY_FOR_REVIEW"
        or str(candidate["candidate_id"]) != request["candidate_id"]
        or int(candidate["version"]) != request["expected_candidate_version"]
        or int(candidate["current_revision_no"]) != request["expected_revision_no"]
        or int(submitted["candidate_revision"]) != request["expected_revision_no"]
        or submitted["candidate_hash"] != request["expected_candidate_hash"]
    ):
        raise _conflict("Candidate review invalidation CAS or lineage failed.")


def _require_submit_replay(
    existing: Mapping[str, Any],
    *,
    review: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> None:
    if (
        str(existing["candidate_id"]) != str(review["candidate_id"])
        or int(existing["candidate_revision"]) != int(review["candidate_revision"])
        or str(existing["candidate_hash"]) != str(review["candidate_hash"])
        or str(existing["validation_hash"]) != str(validation.get("validation_hash"))
        or str(existing["review_hash"]) != _review_hash(review)
    ):
        raise _conflict("Candidate submission replay changed immutable semantics.")


def _require_invalidation_replay(
    existing: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    if (
        existing["transition_kind"] != "INVALIDATE"
        or str(existing["candidate_id"]) != request["candidate_id"]
        or str(existing["approval_case_id"]) != request["approval_case_id"]
        or int(existing["candidate_revision"]) != request["expected_revision_no"]
        or str(existing["candidate_hash"]) != request["expected_candidate_hash"]
        or str(existing["actor_subject_id"]) != request["actor_subject_id"]
        or str(existing["reason"]) != request["reason"]
    ):
        raise _conflict("Candidate invalidation replay changed immutable semantics.")


def _deterministic_event_id(
    *, tenant_id: str, approval_case_id: str, transition_kind: str
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/eos/candidate-review/"
            f"{tenant_id}/{approval_case_id}/{transition_kind}",
        )
    )


def _review_hash(review: Mapping[str, Any]) -> str:
    semantics = dict(review)
    observed_at = semantics.get("validation_observed_at")
    if isinstance(observed_at, datetime):
        semantics["validation_observed_at"] = _aware_datetime(
            "validation_observed_at", observed_at
        ).isoformat()
    return semantic_sha256_hash_ref(semantics)


def _tenant_id(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > 128:
        raise _invalid("tenant_id must be a non-empty scoped identifier.")
    return normalized


def _subject_id(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > 128:
        raise _invalid("actor_subject_id must contain 1..128 characters.")
    return normalized


def _reason(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > 2000:
        raise _invalid("review transition reason must contain 1..2000 characters.")
    return normalized


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer.")
    return value


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(str(value))
    except ValueError as exc:
        raise _invalid(f"{field} must be a SHA-256 hash reference.") from exc


def _datetime(field: str, value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be an ISO 8601 date-time.") from exc
    return _aware_datetime(field, parsed)


def _aware_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must include a timezone.")
    return value.astimezone(UTC)


def _timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        raise _invalid("Stored candidate review timestamp is invalid.")
    normalized = (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    )
    return normalized.isoformat()


def _invalid(detail: str) -> EosCandidateReviewError:
    return EosCandidateReviewError(
        "EOS_CANDIDATE_REVIEW_INVALID", detail, status_code=422
    )


def _not_found(detail: str) -> EosCandidateReviewError:
    return EosCandidateReviewError(
        "EOS_CANDIDATE_REVIEW_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosCandidateReviewError:
    return EosCandidateReviewError(
        "EOS_CANDIDATE_REVIEW_CONFLICT", detail, status_code=409
    )


def _unavailable() -> EosCandidateReviewError:
    return EosCandidateReviewError(
        "EOS_CANDIDATE_REVIEW_PERSISTENCE_FAILED",
        "Candidate review persistence is unavailable.",
        status_code=503,
        retryable=True,
    )
