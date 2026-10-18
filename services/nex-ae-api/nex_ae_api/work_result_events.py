from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue

EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_name",
        "tenant_id",
        "work_item_id",
        "result_id",
        "revision_no",
        "result_type",
        "result_schema_ref",
        "technical_outcome",
        "business_outcome",
        "source_execution_ref",
        "claim_ref",
        "claim_generation",
        "assignment_ref",
        "submitted_by",
        "resume_match_ref",
        "correlation_id",
        "causation_id",
        "occurred_at",
    }
)
REQUIRED_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_name",
        "tenant_id",
        "work_item_id",
        "result_id",
        "revision_no",
        "result_type",
        "technical_outcome",
        "business_outcome",
        "submitted_by",
        "resume_match_ref",
        "correlation_id",
        "occurred_at",
    }
)
TERMINAL_EXECUTION_STATES = frozenset(
    {"SUCCEEDED", "FAILED", "BLOCKED", "ESCALATED", "CANCELLED"}
)


@dataclass
class WorkResultEventError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyWorkResultEventService:
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
        normalized = validate_work_result_event(event)
        return self._reconcile_event(normalized, persist=True)

    def reconcile_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 500
        ):
            raise _invalid("limit must be between 1 and 500.")
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(text(_PENDING_EVENTS_SQL), {"limit": limit})
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return [
            self._reconcile_event(_payload(row["event_payload"]), persist=False)
            for row in rows
        ]

    def _reconcile_event(
        self, event: Mapping[str, Any], *, persist: bool
    ) -> dict[str, Any]:
        now = _time(self._clock())
        event_hash = semantic_sha256_hash_ref(event)
        params = {
            "tenant_id": event["tenant_id"],
            "event_id": event["event_id"],
            "event_type": event["event_name"],
            "event_semantic_hash": event_hash,
            "external_ref": event["work_item_id"],
            "result_id": event["result_id"],
            "result_contract_ref": event.get("result_schema_ref"),
            "event_payload": json.dumps(event, sort_keys=True),
            "now": now,
        }
        try:
            with self._session_factory() as session:
                created = False
                if persist:
                    inserted = session.execute(text(_event_insert_sql(session)), params)
                    created = int(inserted.rowcount or 0) == 1
                inbox = _load_inbox(
                    session,
                    tenant_id=event["tenant_id"],
                    event_id=event["event_id"],
                    lock=True,
                )
                if inbox is None:
                    raise WorkResultEventError(
                        "ae.work_result_event_not_found",
                        "WorkResult event is not present in the external inbox.",
                        404,
                    )
                if inbox["event_semantic_hash"] != event_hash:
                    raise WorkResultEventError(
                        "ae.work_result_event_idempotency_conflict",
                        "WorkResult event identity was reused with different semantics.",
                    )
                if inbox["state"] != "RECEIVED":
                    matched_wait = _load_wait_by_event(session, event=event)
                    session.commit()
                    return _projection(
                        inbox,
                        created=False,
                        wait_state=(
                            None if matched_wait is None else matched_wait["state"]
                        ),
                        resume_runtime_job_id=(
                            None
                            if matched_wait is None
                            else matched_wait["resume_runtime_job_id"]
                        ),
                    )
                context = _load_wait_context(session, event=event, lock=True)
                if context is None:
                    session.commit()
                    return _projection(inbox, created=created)
                terminal_reason = _terminal_parent_reason(context)
                if terminal_reason is not None:
                    _cancel_wait_and_reject(
                        session,
                        event=event,
                        wait_id=context["wait_id"],
                        reason=terminal_reason,
                        now=now,
                    )
                    session.commit()
                    rejected = _load_inbox(
                        session,
                        tenant_id=event["tenant_id"],
                        event_id=event["event_id"],
                    )
                    return _projection(
                        rejected, created=created, wait_state="CANCELLED"
                    )
                rejection = _semantic_rejection(event, context)
                if rejection is not None:
                    _reject_inbox(session, event=event, reason=rejection, now=now)
                    session.commit()
                    rejected = _load_inbox(
                        session,
                        tenant_id=event["tenant_id"],
                        event_id=event["event_id"],
                    )
                    return _projection(
                        rejected, created=created, wait_state=context["wait_state"]
                    )
                if not _parent_ready(context):
                    session.commit()
                    return _projection(
                        inbox, created=created, wait_state=context["wait_state"]
                    )
                runtime_job_id = deterministic_resume_job_id(
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
                    dedup_key=_resume_dedup_key(
                        wait_id=context["wait_id"], event_id=event["event_id"]
                    ),
                    run_after=now,
                    correlation_id=event["correlation_id"],
                    now=now,
                    payload={
                        "wait_id": context["wait_id"],
                        "event_id": event["event_id"],
                        "result_id": event["result_id"],
                        "external_ref": event["work_item_id"],
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
                matched = _load_inbox(
                    session,
                    tenant_id=event["tenant_id"],
                    event_id=event["event_id"],
                )
                return _projection(
                    matched,
                    created=created,
                    wait_state="RESUME_QUEUED",
                    resume_runtime_job_id=job["runtime_job_id"],
                )
        except WorkResultEventError:
            raise
        except RuntimeJobError as exc:
            raise WorkResultEventError(
                exc.error_code, exc.detail, 503 if exc.retryable else 409, exc.retryable
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def validate_work_result_event(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("event must be an object.")
    event = copy.deepcopy(dict(value))
    unknown = set(event) - EVENT_FIELDS
    missing = REQUIRED_EVENT_FIELDS - set(event)
    if unknown:
        raise _invalid(f"unsupported event field: {min(unknown)}")
    if missing:
        raise _invalid(f"missing event field: {min(missing)}")
    if event["schema_version"] != "2.1":
        raise _invalid("event schema_version must be 2.1.")
    if event["event_name"] != "WORK_RESULT_SUBMITTED":
        raise _invalid("event_name must be WORK_RESULT_SUBMITTED.")
    for field, maximum in (
        ("event_id", 128),
        ("tenant_id", 128),
        ("result_id", 128),
        ("result_type", 120),
        ("correlation_id", 128),
    ):
        event[field] = _required(field, event[field], maximum)
    for field in (
        "work_item_id",
        "resume_match_ref",
        "source_execution_ref",
        "claim_ref",
        "assignment_ref",
    ):
        event[field] = _uuid(field, event.get(field))
    if event["resume_match_ref"] != event["work_item_id"]:
        raise _invalid("resume_match_ref must equal work_item_id.")
    event["revision_no"] = _positive_int("revision_no", event["revision_no"])
    event["claim_generation"] = _positive_int(
        "claim_generation", event.get("claim_generation")
    )
    event["result_schema_ref"] = _required(
        "result_schema_ref", event.get("result_schema_ref"), 512
    )
    if event["technical_outcome"] not in {"SUCCEEDED", "PARTIAL", "FAILED", "UNKNOWN"}:
        raise _invalid("technical_outcome is invalid.")
    if event["business_outcome"] not in {
        "VERIFIED",
        "REVISED",
        "REJECTED",
        "PENDING_VERIFICATION",
        "NOT_APPLICABLE",
    }:
        raise _invalid("business_outcome is invalid.")
    event["submitted_by"] = _entity_ref(event["submitted_by"])
    if event["submitted_by"]["entity_type"] != "AGENT":
        raise _invalid("Initial P7 result event submitter must be AGENT.")
    event["submitted_by"]["entity_id"] = _uuid(
        "submitted_by.entity_id", event["submitted_by"]["entity_id"]
    )
    if event.get("causation_id") is not None:
        event["causation_id"] = _required("causation_id", event["causation_id"], 128)
    event["occurred_at"] = _timestamp("occurred_at", event["occurred_at"])
    return event


def deterministic_resume_job_id(*, tenant_id: str, wait_id: str, event_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/ae/runtime-jobs/resume/"
            f"{tenant_id}/{wait_id}/{event_id}",
        )
    )


def _load_wait_context(
    session: Session, *, event: Mapping[str, Any], lock: bool
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF wait" if lock and _postgres(session) else ""
    row = (
        session.execute(
            text(
                "SELECT wait.wait_id, wait.agent_execution_id, "
                "wait.executable_step_id, wait.result_contract_ref, "
                "wait.state AS wait_state, wait.matched_event_id, "
                "wait.resume_runtime_job_id, parent.state AS parent_state, "
                "parent.correlation_id AS parent_correlation_id, "
                "step.state AS step_state, step.executor_kind, "
                "child.agent_execution_id AS child_execution_id, "
                "child.agent_id AS child_agent_id, child.source_type, "
                "child.work_item_ref, child.claim_ref, child.claim_generation, "
                "child.assignment_ref "
                "FROM ae_wait_registration AS wait "
                "JOIN ae_agent_execution AS parent "
                "ON parent.tenant_id = wait.tenant_id "
                "AND parent.agent_execution_id = wait.agent_execution_id "
                "JOIN ae_executable_step AS step "
                "ON step.tenant_id = wait.tenant_id "
                "AND step.executable_step_id = wait.executable_step_id "
                "LEFT JOIN ae_agent_execution AS child "
                "ON child.tenant_id = wait.tenant_id "
                "AND CAST(child.agent_execution_id AS TEXT) = :source_execution_ref "
                "WHERE wait.tenant_id = :tenant_id "
                "AND CAST(wait.external_ref AS TEXT) = :external_ref "
                "AND wait.wait_type = 'WORK_RESULT'" + suffix
            ),
            {
                "tenant_id": event["tenant_id"],
                "external_ref": event["work_item_id"],
                "source_execution_ref": event["source_execution_ref"],
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        key: (str(value) if key.endswith("_id") and value is not None else value)
        for key, value in row.items()
    }


def _load_wait_by_event(
    session: Session, *, event: Mapping[str, Any]
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT state, resume_runtime_job_id "
                "FROM ae_wait_registration WHERE tenant_id = :tenant_id "
                "AND matched_event_id = :event_id"
            ),
            {"tenant_id": event["tenant_id"], "event_id": event["event_id"]},
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def _semantic_rejection(
    event: Mapping[str, Any], context: Mapping[str, Any]
) -> str | None:
    if context["result_contract_ref"] != event["result_schema_ref"]:
        return "RESULT_CONTRACT_MISMATCH"
    if context["parent_correlation_id"] != event["correlation_id"]:
        return "CORRELATION_MISMATCH"
    if (
        context["child_execution_id"] is None
        or context["source_type"] != "CLAIMED_WORKITEM"
    ):
        return "SOURCE_EXECUTION_AUTHORITY_MISSING"
    authority = (
        str(context["work_item_ref"]),
        str(context["claim_ref"]),
        int(context["claim_generation"] or 0),
        str(context["assignment_ref"]),
        str(context["child_agent_id"]),
    )
    proposed = (
        event["work_item_id"],
        event["claim_ref"],
        event["claim_generation"],
        event["assignment_ref"],
        event["submitted_by"]["entity_id"],
    )
    if authority != proposed:
        return "CURRENT_AUTHORITY_MISMATCH"
    return None


def _parent_ready(context: Mapping[str, Any]) -> bool:
    return (
        context["wait_state"] == "PENDING"
        and context["parent_state"] == "WAITING_DEPENDENCY"
        and context["step_state"] == "WAITING"
        and context["executor_kind"] == "WC_DELEGATE_WORK"
    )


def _terminal_parent_reason(context: Mapping[str, Any]) -> str | None:
    if context["wait_state"] == "CANCELLED":
        return "WAIT_CANCELLED"
    if context["parent_state"] in TERMINAL_EXECUTION_STATES:
        return f"PARENT_{context['parent_state']}"
    if context["step_state"] in {"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"}:
        return f"STEP_{context['step_state']}"
    return None


def _mark_matched(
    session: Session,
    *,
    event: Mapping[str, Any],
    wait_id: str,
    runtime_job_id: str,
    now: str,
) -> None:
    updated = session.execute(
        text(
            "UPDATE ae_wait_registration SET state = 'RESUME_QUEUED', "
            "matched_event_id = :event_id, resume_runtime_job_id = :job_id, "
            "satisfied_at = COALESCE(satisfied_at, :now), updated_at = :now, "
            "version = version + 1 "
            "WHERE tenant_id = :tenant_id AND wait_id = :wait_id "
            "AND state = 'PENDING'"
        ),
        {
            "tenant_id": event["tenant_id"],
            "wait_id": wait_id,
            "event_id": event["event_id"],
            "job_id": runtime_job_id,
            "now": now,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise WorkResultEventError(
            "ae.work_result_wait_conflict",
            "WaitRegistration changed before resume scheduling.",
            409,
            True,
        )
    session.execute(
        text(
            "UPDATE ae_external_event_inbox SET state = 'MATCHED', "
            "processed_at = :now WHERE tenant_id = :tenant_id "
            "AND event_id = :event_id AND state = 'RECEIVED'"
        ),
        {"tenant_id": event["tenant_id"], "event_id": event["event_id"], "now": now},
    )


def _cancel_wait_and_reject(
    session: Session,
    *,
    event: Mapping[str, Any],
    wait_id: str,
    reason: str,
    now: str,
) -> None:
    session.execute(
        text(
            "UPDATE ae_wait_registration SET state = 'CANCELLED', "
            "updated_at = :now, version = version + 1 "
            "WHERE tenant_id = :tenant_id AND wait_id = :wait_id "
            "AND state = 'PENDING'"
        ),
        {"tenant_id": event["tenant_id"], "wait_id": wait_id, "now": now},
    )
    _reject_inbox(session, event=event, reason=reason, now=now)


def _reject_inbox(
    session: Session,
    *,
    event: Mapping[str, Any],
    reason: str,
    now: str,
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


def _load_inbox(
    session: Session, *, tenant_id: str, event_id: str, lock: bool = False
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock and _postgres(session) else ""
    row = (
        session.execute(
            text(
                "SELECT tenant_id, event_id, event_type, event_semantic_hash, "
                "external_ref, result_id, result_contract_ref, event_payload, "
                "state, rejection_reason, received_at, processed_at "
                "FROM ae_external_event_inbox WHERE tenant_id = :tenant_id "
                "AND event_id = :event_id" + suffix
            ),
            {"tenant_id": tenant_id, "event_id": event_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        **dict(row),
        "event_id": str(row["event_id"]),
        "external_ref": str(row["external_ref"]),
        "result_id": str(row["result_id"]),
        "event_payload": _payload(row["event_payload"]),
        "received_at": _time(row["received_at"]),
        "processed_at": (
            None if row["processed_at"] is None else _time(row["processed_at"])
        ),
    }


def _projection(
    inbox: Mapping[str, Any] | None,
    *,
    created: bool,
    wait_state: str | None = None,
    resume_runtime_job_id: str | None = None,
) -> dict[str, Any]:
    if inbox is None:
        raise WorkResultEventError(
            "ae.work_result_event_not_found",
            "WorkResult event projection is unavailable.",
            404,
        )
    return {
        "schema_version": "ae_work_result_event_acceptance.v1",
        "created": created,
        "event_id": inbox["event_id"],
        "inbox_state": inbox["state"],
        "wait_state": wait_state,
        "resume_runtime_job_id": resume_runtime_job_id,
        "rejection_reason": inbox["rejection_reason"],
    }


def _event_insert_sql(session: Session) -> str:
    payload = (
        "CAST(:event_payload AS JSONB)" if _postgres(session) else ":event_payload"
    )
    return _EVENT_INSERT_SQL.replace(":payload_expression", payload)


_EVENT_INSERT_SQL = """
    INSERT INTO ae_external_event_inbox (
        tenant_id, event_id, event_type, event_semantic_hash, external_ref,
        result_id, result_contract_ref, event_payload, state, received_at
    ) VALUES (
        :tenant_id, :event_id, :event_type, :event_semantic_hash, :external_ref,
        :result_id, :result_contract_ref, :payload_expression, 'RECEIVED', :now
    ) ON CONFLICT (tenant_id, event_id) DO NOTHING
"""

_PENDING_EVENTS_SQL = """
    SELECT event_payload FROM ae_external_event_inbox
    WHERE state = 'RECEIVED'
    ORDER BY received_at, event_id
    LIMIT :limit
"""


def _resume_dedup_key(*, wait_id: str, event_id: str) -> str:
    return f"p7:resume:{wait_id}:{event_id}"


def _entity_ref(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("submitted_by must be an entity reference.")
    result = copy.deepcopy(dict(value))
    if set(result) - {"entity_type", "entity_id", "version", "status"}:
        raise _invalid("submitted_by contains unsupported fields.")
    result["entity_type"] = _required(
        "submitted_by.entity_type", result.get("entity_type"), 80
    )
    result["entity_id"] = _required(
        "submitted_by.entity_id", result.get("entity_id"), 160
    )
    return result


def _payload(value: object) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise _invalid("stored event payload must be an object.")
    return dict(parsed)


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer.")
    return value


def _required(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _timestamp(field: str, value: object) -> str:
    normalized = _required(field, value, 64)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone.")
    return _time(parsed)


def _time(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value
    return normalized.isoformat().replace("+00:00", "Z")


def _postgres(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _invalid(detail: str) -> WorkResultEventError:
    return WorkResultEventError("ae.work_result_event_invalid", detail, 400)


def _unavailable() -> WorkResultEventError:
    return WorkResultEventError(
        "ae.work_result_event_store_unavailable",
        "AE WorkResult event persistence is unavailable.",
        503,
        True,
    )
