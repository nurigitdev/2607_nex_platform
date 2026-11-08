from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.nsl_approval_publication import NSL_APPROVAL_RESUME_CONTRACT_REF
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue

NSL_APPROVAL_EVENT_SCHEMA_VERSION = "ae_nsl_approval_decided_event.v1"
_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_name",
        "tenant_id",
        "approval_work_item_ref",
        "approval_request_id",
        "nsl_execution_id",
        "business_operation_id",
        "decision",
        "approval_evidence_ref",
        "evidence_integrity",
        "correlation_id",
        "causation_id",
        "occurred_at",
    }
)
_TERMINAL_EXECUTION_STATES = frozenset(
    {"SUCCEEDED", "FAILED", "BLOCKED", "ESCALATED", "CANCELLED"}
)


@dataclass(frozen=True)
class NslApprovalEventError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyNslApprovalEventService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        runtime_jobs: SqlAlchemyRuntimeJobQueue,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._runtime_jobs = runtime_jobs
        self._clock = clock or (lambda: datetime.now(UTC))

    def ingest(self, event: object) -> dict[str, Any]:
        return self._reconcile(validate_nsl_approval_event(event), persist=True)

    def reconcile_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise _invalid("limit must be between 1 and 500.")
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(text(_PENDING_SQL), {"limit": limit})
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return [
            self._reconcile(
                validate_nsl_approval_event(_payload(row["event_payload"])),
                persist=False,
            )
            for row in rows
        ]

    def _reconcile(
        self, event: Mapping[str, Any], *, persist: bool
    ) -> dict[str, Any]:
        now = _time(self._clock())
        event_hash = semantic_sha256_hash_ref(event)
        params = {
            **event,
            "event_semantic_hash": event_hash,
            "external_ref": event["approval_request_id"],
            "event_payload": json.dumps(event, sort_keys=True),
            "now": now,
        }
        try:
            with self._session_factory() as session:
                created = False
                if persist:
                    inserted = session.execute(text(_insert_sql(session)), params)
                    created = int(inserted.rowcount or 0) == 1
                inbox = _load_inbox(session, event=event, lock=True)
                if inbox is None:
                    raise NslApprovalEventError(
                        "ae.nsl_approval_event_not_found",
                        "NSL approval event is not present in the external inbox.",
                        404,
                    )
                if inbox["event_semantic_hash"] != event_hash:
                    raise NslApprovalEventError(
                        "ae.nsl_approval_event_idempotency_conflict",
                        "NSL approval event identity has different semantics.",
                    )
                if inbox["state"] != "RECEIVED":
                    wait = _load_wait_by_event(session, event)
                    session.commit()
                    return _projection(inbox, created=False, wait=wait)
                context = _load_context(session, event=event, lock=True)
                if context is None or context["evidence_integrity"] is None:
                    session.commit()
                    return _projection(inbox, created=created)
                terminal = _terminal_reason(context)
                if terminal is not None:
                    _cancel_and_reject(
                        session, event=event, wait_id=context["wait_id"], reason=terminal, now=now
                    )
                    session.commit()
                    return _projection(
                        _load_inbox(session, event=event),
                        created=created,
                        wait={"state": "CANCELLED", "resume_runtime_job_id": None},
                    )
                rejection = _semantic_rejection(event, context)
                if rejection is not None:
                    _reject(session, event=event, reason=rejection, now=now)
                    session.commit()
                    return _projection(
                        _load_inbox(session, event=event),
                        created=created,
                        wait={"state": context["wait_state"], "resume_runtime_job_id": None},
                    )
                if not _ready(context):
                    session.commit()
                    return _projection(
                        inbox,
                        created=created,
                        wait={"state": context["wait_state"], "resume_runtime_job_id": None},
                    )
                runtime_job_id = deterministic_nsl_approval_resume_job_id(
                    tenant_id=event["tenant_id"],
                    wait_id=context["wait_id"],
                    event_id=event["event_id"],
                )
                job = self._runtime_jobs.enqueue_resume_in_session(
                    session,
                    tenant_id=event["tenant_id"],
                    runtime_job_id=runtime_job_id,
                    execution_id=context["agent_execution_id"],
                    executable_step_id=context["executable_step_id"],
                    wait_id=context["wait_id"],
                    dedup_key=f"p8:nsl-approval-resume:{context['wait_id']}:{event['event_id']}",
                    run_after=now,
                    correlation_id=event["correlation_id"],
                    now=now,
                    payload={
                        "wait_id": context["wait_id"],
                        "event_id": event["event_id"],
                        "approval_request_id": event["approval_request_id"],
                        "approval_work_item_ref": event["approval_work_item_ref"],
                        "approval_evidence_ref": event["approval_evidence_ref"],
                        "resume_token_ref": _resume_token_ref(event),
                    },
                    causation_id=event["event_id"],
                )
                _mark_matched(
                    session,
                    event=event,
                    wait_id=context["wait_id"],
                    runtime_job_id=job["runtime_job_id"],
                    now=now,
                )
                session.commit()
                return _projection(
                    _load_inbox(session, event=event),
                    created=created,
                    wait={
                        "state": "RESUME_QUEUED",
                        "resume_runtime_job_id": job["runtime_job_id"],
                    },
                )
        except NslApprovalEventError:
            raise
        except RuntimeJobError as exc:
            raise NslApprovalEventError(
                exc.error_code, exc.detail, 503 if exc.retryable else 409, exc.retryable
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def validate_nsl_approval_event(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise _invalid("NSL approval event fields are invalid.")
    event = copy.deepcopy(dict(value))
    if event["schema_version"] != NSL_APPROVAL_EVENT_SCHEMA_VERSION:
        raise _invalid("NSL approval event schema_version is invalid.")
    if event["event_name"] != "NSL_APPROVAL_DECIDED":
        raise _invalid("event_name must be NSL_APPROVAL_DECIDED.")
    event["event_id"] = _uuid("event_id", event["event_id"])
    event["approval_work_item_ref"] = _uuid(
        "approval_work_item_ref", event["approval_work_item_ref"]
    )
    for field, maximum in (
        ("tenant_id", 128),
        ("approval_request_id", 256),
        ("nsl_execution_id", 256),
        ("business_operation_id", 256),
        ("approval_evidence_ref", 512),
        ("correlation_id", 128),
        ("causation_id", 128),
    ):
        event[field] = _required(field, event[field], maximum)
    if event["decision"] not in {"APPROVE", "REJECT"}:
        raise _invalid("decision must be APPROVE or REJECT.")
    try:
        event["evidence_integrity"] = validate_hash_ref(event["evidence_integrity"])
    except ValueError as exc:
        raise _invalid("evidence_integrity must be a SHA-256 reference.") from exc
    event["occurred_at"] = _timestamp(event["occurred_at"])
    return event


def deterministic_nsl_approval_resume_job_id(
    *, tenant_id: str, wait_id: str, event_id: str
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/ae/runtime-jobs/nsl-approval-resume/"
            f"{tenant_id}/{wait_id}/{event_id}",
        )
    )


def _load_context(
    session: Session, *, event: Mapping[str, Any], lock: bool
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF wait" if lock and _postgres(session) else ""
    row = (
        session.execute(
            text(_CONTEXT_SQL + suffix),
            {
                "tenant_id": event["tenant_id"],
                "approval_request_id": event["approval_request_id"],
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    context = {
        key: str(value) if key.endswith("_id") and value is not None else value
        for key, value in row.items()
    }
    if context["approval_work_item_ref"] is not None:
        context["approval_work_item_ref"] = str(context["approval_work_item_ref"])
    return context


def _semantic_rejection(event: Mapping[str, Any], context: Mapping[str, Any]) -> str | None:
    expected = {
        "approval_request_id": context["approval_request_id"],
        "nsl_execution_id": context["nsl_execution_id"],
        "business_operation_id": context["business_operation_id"],
        "approval_work_item_ref": context["approval_work_item_ref"],
        "evidence_integrity": context["evidence_integrity"],
        "decision": context["decision"],
    }
    if any(event[field] != value for field, value in expected.items()):
        return "APPROVAL_EVIDENCE_LINEAGE_MISMATCH"
    if event["approval_evidence_ref"] != _approval_evidence_ref(event):
        return "APPROVAL_EVIDENCE_REF_MISMATCH"
    if context["result_contract_ref"] != NSL_APPROVAL_RESUME_CONTRACT_REF:
        return "RESUME_CONTRACT_MISMATCH"
    return None


def _ready(context: Mapping[str, Any]) -> bool:
    return (
        context["wait_state"] == "PENDING"
        and context["parent_state"] == "WAITING_APPROVAL"
        and context["step_state"] == "WAITING"
        and context["executor_kind"] == "LOCAL_SKILL"
    )


def _terminal_reason(context: Mapping[str, Any]) -> str | None:
    if context["wait_state"] == "CANCELLED":
        return "WAIT_CANCELLED"
    if context["parent_state"] in _TERMINAL_EXECUTION_STATES:
        return f"PARENT_{context['parent_state']}"
    if context["step_state"] in {"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"}:
        return f"STEP_{context['step_state']}"
    return None


def _load_wait_by_event(
    session: Session, event: Mapping[str, Any]
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT state, resume_runtime_job_id FROM ae_wait_registration "
                "WHERE tenant_id = :tenant_id AND matched_event_id = :event_id"
            ),
            {"tenant_id": event["tenant_id"], "event_id": event["event_id"]},
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def _load_inbox(
    session: Session, *, event: Mapping[str, Any], lock: bool = False
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock and _postgres(session) else ""
    row = (
        session.execute(
            text(_INBOX_SQL + suffix),
            {"tenant_id": event["tenant_id"], "event_id": event["event_id"]},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        **dict(row),
        "event_id": str(row["event_id"]),
        "event_payload": _payload(row["event_payload"]),
        "received_at": _time(row["received_at"]),
        "processed_at": None if row["processed_at"] is None else _time(row["processed_at"]),
    }


def _mark_matched(
    session: Session,
    *,
    event: Mapping[str, Any],
    wait_id: str,
    runtime_job_id: str,
    now: str,
) -> None:
    updated = session.execute(
        text(_MATCH_WAIT_SQL),
        {
            "tenant_id": event["tenant_id"],
            "wait_id": wait_id,
            "event_id": event["event_id"],
            "job_id": runtime_job_id,
            "now": now,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise NslApprovalEventError(
            "ae.nsl_approval_wait_conflict",
            "NSL approval wait changed before resume scheduling.",
            retryable=True,
        )
    session.execute(
        text(_MATCH_INBOX_SQL),
        {"tenant_id": event["tenant_id"], "event_id": event["event_id"], "now": now},
    )


def _cancel_and_reject(
    session: Session,
    *,
    event: Mapping[str, Any],
    wait_id: str,
    reason: str,
    now: str,
) -> None:
    session.execute(
        text(
            "UPDATE ae_wait_registration SET state = 'CANCELLED', updated_at = :now, "
            "version = version + 1 WHERE tenant_id = :tenant_id AND wait_id = :wait_id "
            "AND state = 'PENDING'"
        ),
        {"tenant_id": event["tenant_id"], "wait_id": wait_id, "now": now},
    )
    _reject(session, event=event, reason=reason, now=now)


def _reject(
    session: Session, *, event: Mapping[str, Any], reason: str, now: str
) -> None:
    session.execute(
        text(
            "UPDATE ae_external_event_inbox SET state = 'REJECTED', "
            "rejection_reason = :reason, processed_at = :now "
            "WHERE tenant_id = :tenant_id AND event_id = :event_id "
            "AND state = 'RECEIVED'"
        ),
        {
            "tenant_id": event["tenant_id"],
            "event_id": event["event_id"],
            "reason": reason,
            "now": now,
        },
    )


def _projection(
    inbox: Mapping[str, Any] | None,
    *,
    created: bool,
    wait: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if inbox is None:
        raise NslApprovalEventError(
            "ae.nsl_approval_event_not_found",
            "NSL approval event projection is unavailable.",
            404,
        )
    return {
        "schema_version": "ae_nsl_approval_event_acceptance.v1",
        "created": created,
        "event_id": inbox["event_id"],
        "inbox_state": inbox["state"],
        "wait_state": None if wait is None else wait["state"],
        "resume_runtime_job_id": (
            None if wait is None else wait["resume_runtime_job_id"]
        ),
        "rejection_reason": inbox["rejection_reason"],
    }


def _approval_evidence_ref(event: Mapping[str, Any]) -> str:
    return f"ae-approval-evidence:{event['approval_request_id']}"


def _resume_token_ref(event: Mapping[str, Any]) -> str:
    return f"ae-nsl-resume:{event['evidence_integrity']}"


def _insert_sql(session: Session) -> str:
    payload = "CAST(:event_payload AS JSONB)" if _postgres(session) else ":event_payload"
    return _INSERT_SQL.replace(":payload_expression", payload)


def _payload(value: object) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise _invalid("stored NSL approval event payload must be an object.")
    return dict(parsed)


def _required(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _timestamp(value: object) -> str:
    text_value = _required("occurred_at", value, 64)
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("occurred_at must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid("occurred_at must include a timezone.")
    return _time(parsed)


def _time(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value
    return normalized.isoformat().replace("+00:00", "Z")


def _postgres(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _invalid(detail: str) -> NslApprovalEventError:
    return NslApprovalEventError("ae.nsl_approval_event_invalid", detail, 400)


def _unavailable() -> NslApprovalEventError:
    return NslApprovalEventError(
        "ae.nsl_approval_event_store_unavailable",
        "AE NSL approval event persistence is unavailable.",
        503,
        True,
    )


_INSERT_SQL = """
    INSERT INTO ae_external_event_inbox (
        tenant_id, event_id, event_type, event_semantic_hash, external_ref,
        result_id, result_contract_ref, event_payload, state, received_at,
        approval_request_id, approval_work_item_ref, approval_evidence_ref,
        evidence_integrity, nsl_execution_id, business_operation_id
    ) VALUES (
        :tenant_id, :event_id, :event_name, :event_semantic_hash, :external_ref,
        NULL, NULL, :payload_expression, 'RECEIVED', :now,
        :approval_request_id, :approval_work_item_ref, :approval_evidence_ref,
        :evidence_integrity, :nsl_execution_id, :business_operation_id
    ) ON CONFLICT (tenant_id, event_id) DO NOTHING
"""

_PENDING_SQL = """
    SELECT event_payload FROM ae_external_event_inbox
    WHERE state = 'RECEIVED' AND event_type = 'NSL_APPROVAL_DECIDED'
    ORDER BY received_at, event_id LIMIT :limit
"""

_CONTEXT_SQL = """
    SELECT wait.wait_id, wait.agent_execution_id, wait.executable_step_id,
           wait.result_contract_ref, wait.state AS wait_state,
           wait.approval_request_id, wait.nsl_execution_id,
           wait.business_operation_id, wait.checkpoint_version,
           parent.state AS parent_state, step.state AS step_state,
           step.executor_kind, evidence.approval_work_item_ref,
           evidence.evidence_integrity, evidence.decision
    FROM ae_wait_registration AS wait
    JOIN ae_agent_execution AS parent
      ON parent.tenant_id = wait.tenant_id
     AND parent.agent_execution_id = wait.agent_execution_id
    JOIN ae_executable_step AS step
      ON step.tenant_id = wait.tenant_id
     AND step.executable_step_id = wait.executable_step_id
    LEFT JOIN ae_approval_evidence AS evidence
      ON evidence.tenant_id = wait.tenant_id
     AND evidence.approval_request_id = wait.approval_request_id
    WHERE wait.tenant_id = :tenant_id
      AND wait.approval_request_id = :approval_request_id
      AND wait.wait_type = 'NSL_APPROVAL'
"""

_INBOX_SQL = """
    SELECT tenant_id, event_id, event_type, event_semantic_hash, external_ref,
           event_payload, state, rejection_reason, received_at, processed_at,
           approval_request_id, approval_work_item_ref, approval_evidence_ref,
           evidence_integrity, nsl_execution_id, business_operation_id
    FROM ae_external_event_inbox
    WHERE tenant_id = :tenant_id AND event_id = :event_id
"""

_MATCH_WAIT_SQL = """
    UPDATE ae_wait_registration SET state = 'RESUME_QUEUED',
        matched_event_id = :event_id, resume_runtime_job_id = :job_id,
        satisfied_at = COALESCE(satisfied_at, :now), updated_at = :now,
        version = version + 1
    WHERE tenant_id = :tenant_id AND wait_id = :wait_id AND state = 'PENDING'
"""

_MATCH_INBOX_SQL = """
    UPDATE ae_external_event_inbox SET state = 'MATCHED', processed_at = :now
    WHERE tenant_id = :tenant_id AND event_id = :event_id AND state = 'RECEIVED'
"""
