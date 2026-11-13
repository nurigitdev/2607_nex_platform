from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_OUTBOX_TABLE,
)
from .journal_outbox_events import (
    EosJournalOutboxEventError,
    admit_journal_posted_event,
)
from .journal_posting import JOURNAL_POST_EVENT_TYPE, JOURNAL_POST_OPERATION
from .journals import (
    EOS_JOURNAL_HEADER_TABLE,
    EosJournalError,
    SqlAlchemyEosJournalRepository,
    admit_posted_journal,
)

JOURNAL_RECONCILE_OPERATION = "FINANCE.JOURNAL.RECONCILE"
JOURNAL_RECONCILIATION_SCHEMA = "eos_journal_reconciliation.v1"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class EosJournalOperationError(RuntimeError):
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


class EosJournalOperationService:
    """Authoritative READ-after-uncertain-commit projection for Journal Posting."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._journals = SqlAlchemyEosJournalRepository(session_factory)

    def reconcile(
        self, *, tenant_id: str, business_operation_id: str
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        business_operation_id = _uuid("business_operation_id", business_operation_id)
        try:
            with self._session_factory() as session:
                operation = _operation_row(
                    session,
                    tenant_id=tenant_id,
                    business_operation_id=business_operation_id,
                )
                if operation is None:
                    raise EosJournalOperationError(
                        "EOS_JOURNAL_OPERATION_NOT_FOUND",
                        "Journal Posting BusinessOperation was not found in tenant scope",
                        status_code=404,
                    )
                if operation["operation"] != JOURNAL_POST_OPERATION:
                    raise EosJournalOperationError(
                        "EOS_JOURNAL_OPERATION_TYPE_MISMATCH",
                        "BusinessOperation is not a Journal Posting operation",
                        status_code=409,
                    )
                if operation["commit_state"] == "PENDING":
                    return _unresolved_projection(operation)
                if operation["commit_state"] == "NOT_COMMITTED":
                    return _not_committed_projection(operation)
                if operation["commit_state"] != "COMMITTED":
                    raise EosJournalOperationError(
                        "EOS_JOURNAL_OPERATION_STATE_INVALID",
                        "Journal Posting BusinessOperation state is invalid",
                        status_code=503,
                    )
                return self._committed_projection(session, operation)
        except EosJournalOperationError:
            raise
        except SQLAlchemyError as exc:
            raise EosJournalOperationError(
                "EOS_JOURNAL_RECONCILIATION_UNAVAILABLE",
                "Journal Posting reconciliation persistence is unavailable",
                status_code=503,
                retryable=True,
            ) from exc

    def _committed_projection(
        self, session: Session, operation: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            idempotency = (
                session.execute(
                    select(EOS_IDEMPOTENCY_TABLE).where(
                        EOS_IDEMPOTENCY_TABLE.c.tenant_id == operation["tenant_id"],
                        EOS_IDEMPOTENCY_TABLE.c.business_operation_id
                        == operation["business_operation_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            outbox = (
                session.execute(
                    select(EOS_OUTBOX_TABLE).where(
                        EOS_OUTBOX_TABLE.c.tenant_id == operation["tenant_id"],
                        EOS_OUTBOX_TABLE.c.business_operation_id
                        == operation["business_operation_id"],
                        EOS_OUTBOX_TABLE.c.event_type == JOURNAL_POST_EVENT_TYPE,
                    )
                )
                .mappings()
                .one_or_none()
            )
            header = (
                session.execute(
                    select(EOS_JOURNAL_HEADER_TABLE).where(
                        EOS_JOURNAL_HEADER_TABLE.c.tenant_id == operation["tenant_id"],
                        EOS_JOURNAL_HEADER_TABLE.c.business_operation_id
                        == operation["business_operation_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            if idempotency is None or outbox is None or header is None:
                raise ValueError("Committed Posting lineage is incomplete")
            journal = self._journals.get_in_session(
                session,
                tenant_id=str(header["tenant_id"]),
                company_id=str(header["company_id"]),
                journal_id=str(header["journal_id"]),
            )
            if journal is None:
                raise ValueError("Committed PostedJournal is missing")
            admitted = admit_posted_journal(
                acceptance={
                    **journal["acceptance"],
                    "accepted_at": _database_time(journal["acceptance"]["accepted_at"]),
                },
                header={
                    **journal["header"],
                    "posted_at": _database_time(journal["header"]["posted_at"]),
                },
                lines=journal["lines"],
            )
            _require_lineage(operation, idempotency, outbox, admitted)
            event = admit_journal_posted_event(outbox["event_payload"])
            _require_event_lineage(operation, outbox, admitted, event)
            result = operation.get("result_json")
            if not isinstance(result, Mapping):
                raise TypeError("Committed Posting result is missing")
            _require_result_lineage(result, admitted)
        except (
            EosJournalError,
            EosJournalOutboxEventError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return _verification_failed_projection(operation)

        header = admitted["header"]
        acceptance = admitted["acceptance"]
        project_codes = sorted({line["project_code"] for line in admitted["lines"]})
        return {
            **_base_projection(
                operation,
                commit_state="COMMITTED",
                reconciliation_status="COMMITTED_CONFIRMED",
                verification_status="VERIFIED",
                retry_disposition="DO_NOT_REPOST",
            ),
            "journal": {
                "company_id": str(header["company_id"]),
                "journal_id": str(header["journal_id"]),
                "journal_no": str(header["journal_no"]),
                "journal_hash": str(header["journal_hash"]),
                "candidate_id": str(header["candidate_id"]),
                "candidate_revision": int(header["candidate_revision"]),
                "accounting_acceptance_id": str(header["accounting_acceptance_id"]),
                "accounting_acceptance_hash": str(acceptance["acceptance_hash"]),
                "accounting_period_id": str(header["period_id"]),
                "project_codes": project_codes,
                "line_count": int(header["line_count"]),
                "total_debit_functional": format(header["total_debit_functional"], "f"),
                "total_credit_functional": format(
                    header["total_credit_functional"], "f"
                ),
                "posted_at": _wire_time(header["posted_at"]),
            },
            "outbox": {
                "outbox_id": str(outbox["outbox_id"]),
                "event_id": str(outbox["event_id"]),
                "event_type": str(outbox["event_type"]),
                "event_payload_hash": str(outbox["event_payload_hash"]),
                "delivery_state": str(outbox["delivery_state"]),
                "attempt_count": int(outbox["attempt_count"]),
                "projector_state": (
                    "CURRENT" if outbox["delivery_state"] == "PUBLISHED" else "STALE"
                ),
            },
        }


def _operation_row(
    session: Session, *, tenant_id: str, business_operation_id: str
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_BUSINESS_OPERATION_TABLE).where(
                EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == tenant_id,
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                == business_operation_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_lineage(
    operation: Mapping[str, Any],
    idempotency: Mapping[str, Any],
    outbox: Mapping[str, Any],
    journal: Mapping[str, Any],
) -> None:
    header = journal["header"]
    expected = {
        "tenant_id": str(operation["tenant_id"]),
        "business_operation_id": str(operation["business_operation_id"]),
        "idempotency_key": str(operation["idempotency_key"]),
        "operation": str(operation["operation"]),
        "payload_hash": str(operation["payload_hash"]),
    }
    for field_name, expected_value in expected.items():
        if str(idempotency[field_name]) != expected_value:
            raise ValueError("Idempotency lineage drifted")
    if idempotency["idempotency_state"] != "COMPLETED":
        raise ValueError("Idempotency completion is missing")
    if (
        str(outbox["tenant_id"]) != expected["tenant_id"]
        or str(outbox["business_operation_id"]) != expected["business_operation_id"]
    ):
        raise ValueError("Outbox lineage drifted")
    if semantic_sha256_hash_ref(outbox["event_payload"]) != str(
        outbox["event_payload_hash"]
    ):
        raise ValueError("Outbox payload hash drifted")
    if (
        str(header["business_operation_id"]) != expected["business_operation_id"]
        or str(header["idempotency_key"]) != expected["idempotency_key"]
        or str(header["payload_hash"]) != expected["payload_hash"]
    ):
        raise ValueError("PostedJournal operation lineage drifted")


def _require_event_lineage(
    operation: Mapping[str, Any],
    outbox: Mapping[str, Any],
    journal: Mapping[str, Any],
    event: Mapping[str, Any],
) -> None:
    header = journal["header"]
    acceptance = journal["acceptance"]
    project_codes = sorted({line["project_code"] for line in journal["lines"]})
    expected = {
        "tenant_id": str(operation["tenant_id"]),
        "business_operation_id": str(operation["business_operation_id"]),
        "operation": JOURNAL_POST_OPERATION,
        "company_id": str(header["company_id"]),
        "journal_id": str(header["journal_id"]),
        "journal_no": str(header["journal_no"]),
        "journal_hash": str(header["journal_hash"]),
        "candidate_id": str(header["candidate_id"]),
        "candidate_revision": int(header["candidate_revision"]),
        "accounting_acceptance_id": str(acceptance["acceptance_id"]),
        "accounting_period_id": str(header["period_id"]),
        "project_codes": project_codes,
        "commit_state": "COMMITTED",
        "posted_at": _wire_time(header["posted_at"]),
    }
    if any(event[field] != value for field, value in expected.items()):
        raise ValueError("Journal Posted event lineage drifted")
    if outbox["delivery_state"] not in {"PENDING", "PUBLISHED"}:
        raise ValueError("Outbox delivery state is invalid")


def _require_result_lineage(
    result: Mapping[str, Any], journal: Mapping[str, Any]
) -> None:
    header = journal["header"]
    acceptance = journal["acceptance"]
    expected = {
        "journal_id": str(header["journal_id"]),
        "journal_no": str(header["journal_no"]),
        "journal_hash": str(header["journal_hash"]),
        "candidate_id": str(header["candidate_id"]),
        "candidate_revision": int(header["candidate_revision"]),
        "accounting_acceptance_id": str(acceptance["acceptance_id"]),
        "company_id": str(header["company_id"]),
        "accounting_period_id": str(header["period_id"]),
        "project_codes": sorted({line["project_code"] for line in journal["lines"]}),
    }
    if any(result.get(field) != value for field, value in expected.items()):
        raise ValueError("Journal Posting result lineage drifted")


def _base_projection(
    operation: Mapping[str, Any],
    *,
    commit_state: str,
    reconciliation_status: str,
    verification_status: str,
    retry_disposition: str,
) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_RECONCILIATION_SCHEMA,
        "operation": JOURNAL_RECONCILE_OPERATION,
        "tenant_id": str(operation["tenant_id"]),
        "business_operation_id": str(operation["business_operation_id"]),
        "posting_operation": str(operation["operation"]),
        "idempotency_key": str(operation["idempotency_key"]),
        "payload_hash": str(operation["payload_hash"]),
        "commit_state": commit_state,
        "reconciliation_status": reconciliation_status,
        "verification_status": verification_status,
        "retry_disposition": retry_disposition,
        "new_idempotency_key_allowed": False,
        "last_observed_at": _wire_time(
            operation.get("committed_at") or operation["created_at"]
        ),
    }


def _unresolved_projection(operation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_base_projection(
            operation,
            commit_state="UNKNOWN_COMMIT_STATE",
            reconciliation_status="RECONCILIATION_REQUIRED",
            verification_status="NOT_RUN",
            retry_disposition="DO_NOT_REPOST",
        ),
        "journal": None,
        "outbox": None,
    }


def _not_committed_projection(operation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_base_projection(
            operation,
            commit_state="NOT_COMMITTED",
            reconciliation_status="NOT_COMMITTED_CONFIRMED",
            verification_status="NOT_APPLICABLE",
            retry_disposition="RETRY_SAME_IDENTITY_ONLY",
        ),
        "journal": None,
        "outbox": None,
    }


def _verification_failed_projection(
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        **_base_projection(
            operation,
            commit_state="COMMITTED",
            reconciliation_status="COMMITTED_VERIFICATION_FAILED",
            verification_status="FAILED",
            retry_disposition="DO_NOT_REPOST",
        ),
        "journal": None,
        "outbox": None,
    }


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise EosJournalOperationError(
            "EOS_JOURNAL_RECONCILIATION_INVALID",
            f"{field_name} has an invalid format",
            status_code=422,
        )
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise EosJournalOperationError(
            "EOS_JOURNAL_RECONCILIATION_INVALID",
            f"{field_name} must be a UUID",
            status_code=422,
        ) from exc


def _wire_time(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("Persisted timestamp is invalid")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _database_time(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Persisted timestamp is invalid")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
