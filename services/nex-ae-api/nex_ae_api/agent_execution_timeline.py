from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.nsl_read_backends import validate_nsl_backend_run
from nex_ae_api.nsl_step_executions import validate_nsl_step_execution_binding
from nex_ae_api.step_results import validate_step_result_contract

TIMELINE_SCHEMA_VERSION = "1.0"
TIMELINE_ORDERING_PROFILE = "p6.event-time-phase-source.v1"
_PHASE_ORDER = {
    "ADMISSION": 10,
    "PLANNING": 20,
    "STEP": 30,
    "JOB": 40,
    "BINDING": 50,
    "NSL": 60,
    "RESULT": 70,
    "PUBLICATION": 80,
}
_SOURCE_ORDER = {
    "AGENT_EXECUTION": 10,
    "EXECUTABLE_PLAN": 20,
    "EXECUTABLE_STEP": 30,
    "RUNTIME_JOB": 40,
    "RUNTIME_JOB_ATTEMPT": 50,
    "NSL_STEP_EXECUTION": 60,
    "NSL_PROGRESS": 70,
    "NSL_BACKEND_RUN": 80,
    "STEP_RESULT": 90,
    "AGENT_RESULT": 100,
    "RESULT_DELIVERY": 110,
}
_TIME_BASES = frozenset(
    {
        "SOURCE_TIMESTAMP",
        "CURRENT_SNAPSHOT",
        "PARENT_STARTED_AT",
        "PARENT_COMPLETED_AT",
    }
)
_FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "document_body",
        "hidden_reasoning",
        "password",
        "prompt",
        "raw_content",
        "raw_prompt",
        "reasoning_content",
        "result_payload",
        "runtime_result_envelope",
        "secret",
        "token",
    }
)


@dataclass(frozen=True)
class AgentExecutionTimelineError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyAgentExecutionTimeline:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def project(self, *, tenant_id: str, agent_execution_id: str) -> dict[str, Any]:
        tenant = _text("tenant_id", tenant_id, 128)
        execution_id = _uuid("agent_execution_id", agent_execution_id)
        try:
            with self._session_factory() as session:
                execution = _fetch_one(
                    session,
                    """
                    SELECT agent_execution_id, state, phase, version, source_type,
                           correlation_id, causation_id, received_at, created_at,
                           updated_at, completed_at
                    FROM ae_agent_execution
                    WHERE tenant_id = :tenant_id
                      AND agent_execution_id = :execution_id
                    """,
                    tenant,
                    execution_id,
                )
                if execution is None:
                    raise AgentExecutionTimelineError(
                        "ae.execution_timeline_not_found",
                        "AgentExecution timeline source was not found.",
                    )
                sources = _load_sources(session, tenant, execution_id)
                return build_agent_execution_timeline(
                    tenant_id=tenant,
                    execution=execution,
                    **sources,
                )
        except AgentExecutionTimelineError:
            raise
        except SQLAlchemyError as exc:
            raise AgentExecutionTimelineError(
                "ae.execution_timeline_unavailable",
                "AgentExecution timeline sources are unavailable.",
                True,
            ) from exc


def build_agent_execution_timeline(
    *,
    tenant_id: str,
    execution: Mapping[str, Any],
    plans: Sequence[Mapping[str, Any]],
    steps: Sequence[Mapping[str, Any]],
    jobs: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]],
    bindings: Sequence[Mapping[str, Any]],
    backend_runs: Sequence[Mapping[str, Any]],
    step_results: Sequence[Mapping[str, Any]],
    agent_results: Sequence[Mapping[str, Any]],
    deliveries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    tenant = _text("tenant_id", tenant_id, 128)
    execution_id = _uuid("agent_execution_id", execution.get("agent_execution_id"))
    events: list[dict[str, Any]] = []
    gaps = [
        _gap(
            "EXECUTION_TRANSITION_HISTORY_UNAVAILABLE",
            f"AE:AGENT_EXECUTION:{execution_id}",
            "Only the current AgentExecution state and phase are retained.",
        )
    ]
    _append_event(
        events,
        event_time=execution["received_at"],
        phase="ADMISSION",
        source_type="AGENT_EXECUTION",
        source_id=f"AE:AGENT_EXECUTION:{execution_id}",
        event_type="EXECUTION_ADMITTED",
        state=None,
        details={
            "source_type": execution["source_type"],
            "correlation_id": execution["correlation_id"],
            "causation_id": execution.get("causation_id"),
        },
    )
    _append_event(
        events,
        event_time=execution["updated_at"],
        event_time_basis="CURRENT_SNAPSHOT",
        phase="ADMISSION",
        source_type="AGENT_EXECUTION",
        source_id=f"AE:AGENT_EXECUTION:{execution_id}:CURRENT",
        event_type="EXECUTION_CURRENT",
        state=execution["state"],
        details={"phase": execution["phase"], "version": execution["version"]},
    )
    for plan in plans:
        plan_id = str(plan["executable_plan_id"])
        _append_event(
            events,
            event_time=plan["compiled_at"],
            phase="PLANNING",
            source_type="EXECUTABLE_PLAN",
            source_id=f"AE:EXECUTABLE_PLAN:{plan_id}",
            event_type="PLAN_COMPILED",
            state=None,
            details={
                "version": plan["executable_plan_version"],
                "plan_hash": plan["plan_hash"],
            },
        )
    if steps:
        gaps.append(
            _gap(
                "STEP_TRANSITION_HISTORY_UNAVAILABLE",
                f"AE:AGENT_EXECUTION:{execution_id}:STEPS",
                "Only persisted and current ExecutableStep snapshots are retained.",
            )
        )
    for step in steps:
        step_id = str(step["executable_step_id"])
        _append_event(
            events,
            event_time=step["created_at"],
            phase="STEP",
            source_type="EXECUTABLE_STEP",
            source_id=f"AE:EXECUTABLE_STEP:{step_id}:PERSISTED",
            event_type="STEP_PERSISTED",
            state=None,
            details={
                "compiled_step_key": step["compiled_step_key"],
                "logical_step_ref": step["logical_step_id"],
                "executor_kind": step["executor_kind"],
            },
        )
        _append_event(
            events,
            event_time=step["updated_at"],
            event_time_basis="CURRENT_SNAPSHOT",
            phase="STEP",
            source_type="EXECUTABLE_STEP",
            source_id=f"AE:EXECUTABLE_STEP:{step_id}:CURRENT",
            event_type="STEP_CURRENT",
            state=step["state"],
            details={
                "compiled_step_key": step["compiled_step_key"],
                "version": step["version"],
                "result_ref": step.get("result_ref"),
                "error_ref": step.get("error_ref"),
            },
        )
    for job in jobs:
        job_id = str(job["runtime_job_id"])
        _append_event(
            events,
            event_time=job["created_at"],
            phase="JOB",
            source_type="RUNTIME_JOB",
            source_id=f"AE:RUNTIME_JOB:{job_id}:QUEUED",
            event_type="JOB_QUEUED",
            state="QUEUED",
            details={
                "job_type": job["job_type"],
                "executable_step_id": job.get("executable_step_id"),
            },
        )
        _append_event(
            events,
            event_time=job["updated_at"],
            event_time_basis="CURRENT_SNAPSHOT",
            phase="JOB",
            source_type="RUNTIME_JOB",
            source_id=f"AE:RUNTIME_JOB:{job_id}:CURRENT",
            event_type="JOB_CURRENT",
            state=job["state"],
            details={"attempt_no": job["attempt_no"]},
        )
    for attempt in attempts:
        attempt_id = str(attempt["attempt_id"])
        _append_event(
            events,
            event_time=attempt["started_at"],
            phase="JOB",
            source_type="RUNTIME_JOB_ATTEMPT",
            source_id=f"AE:RUNTIME_JOB_ATTEMPT:{attempt_id}:STARTED",
            event_type="JOB_ATTEMPT_STARTED",
            state="RUNNING",
            details={
                "runtime_job_id": attempt["runtime_job_id"],
                "attempt_no": attempt["attempt_no"],
                "worker_id": attempt["worker_id"],
            },
        )
        if attempt.get("ended_at") is not None:
            _append_event(
                events,
                event_time=attempt["ended_at"],
                phase="JOB",
                source_type="RUNTIME_JOB_ATTEMPT",
                source_id=f"AE:RUNTIME_JOB_ATTEMPT:{attempt_id}:ENDED",
                event_type="JOB_ATTEMPT_ENDED",
                state=attempt["outcome"],
                details={
                    "runtime_job_id": attempt["runtime_job_id"],
                    "attempt_no": attempt["attempt_no"],
                    "error_ref": attempt.get("error_ref"),
                },
            )
    for stored in bindings:
        binding = validate_nsl_step_execution_binding(
            _json_object(stored["binding_json"])
        )
        binding_ref = f"AE:NSL_BINDING:{binding['nsl_execution_id']}"
        for event_type, field in (
            ("NSL_BINDING_ALLOCATED", "allocated_at"),
            ("NSL_REQUEST_BOUND", "request_bound_at"),
            ("NSL_INVOCATION_STARTED", "invocation_started_at"),
        ):
            if binding[field] is not None:
                _append_event(
                    events,
                    event_time=binding[field],
                    phase="BINDING",
                    source_type="NSL_STEP_EXECUTION",
                    source_id=f"{binding_ref}:{event_type}",
                    event_type=event_type,
                    state=None,
                    details={
                        "executable_step_id": binding["executable_step_id"],
                        "nsl_execution_id": binding["nsl_execution_id"],
                        "business_operation_id": binding["business_operation_id"],
                    },
                )
        if binding["completed_at"] is not None:
            _append_event(
                events,
                event_time=binding["completed_at"],
                phase="RESULT",
                source_type="NSL_STEP_EXECUTION",
                source_id=f"{binding_ref}:SUMMARY",
                event_type="NSL_RESULT_SUMMARY_RECORDED",
                state=binding["state"],
                details={
                    "result_summary_ref": binding["result_summary_ref"],
                    "result_summary_hash": binding["result_summary_hash"],
                },
            )
    for stored in backend_runs:
        run = validate_nsl_backend_run(_json_object(stored["record_json"]))
        run_ref = f"AE:NSL_BACKEND_RUN:{run['nsl_execution_id']}:{run['attempt_no']}"
        if run["progress_events"]:
            gaps.append(
                _gap(
                    "NSL_PROGRESS_TIMESTAMPS_UNAVAILABLE",
                    run_ref,
                    "v0.1 progress ordering is retained but per-event time is absent.",
                )
            )
        for progress in run["progress_events"]:
            is_terminal = progress["state"] in {"COMPLETED", "FAILED"}
            _append_event(
                events,
                event_time=(run["completed_at"] if is_terminal else run["started_at"]),
                event_time_basis=(
                    "PARENT_COMPLETED_AT" if is_terminal else "PARENT_STARTED_AT"
                ),
                phase="NSL",
                source_type="NSL_PROGRESS",
                source_id=f"{run_ref}:PROGRESS:{progress['sequence']:04d}",
                event_type=f"NSL_PROGRESS_{progress['state']}",
                state=progress["runtime_status"],
                details={"progress_sequence": progress["sequence"]},
            )
        _append_event(
            events,
            event_time=run["completed_at"],
            phase="NSL",
            source_type="NSL_BACKEND_RUN",
            source_id=run_ref,
            event_type="NSL_BACKEND_ATTEMPT_COMPLETED",
            state=run["runtime_status"] or run["isolation_status"],
            details={
                "attempt_no": run["attempt_no"],
                "isolation_status": run["isolation_status"],
                "error_code": run["error_code"],
                "retryable": run["retryable"],
            },
            evidence_refs=run["evidence_refs"],
        )
    for stored in step_results:
        result = validate_step_result_contract(_json_object(stored["result_json"]))
        _append_event(
            events,
            event_time=result["completed_at"],
            phase="RESULT",
            source_type="STEP_RESULT",
            source_id=f"AE:STEP_RESULT:{result['step_result_id']}",
            event_type="STEP_RESULT_RECORDED",
            state=result["status"],
            details={
                "executable_step_id": result["executable_step_id"],
                "compiled_step_key": result["compiled_step_key"],
                "schema_version": result["schema_version"],
                "result_hash": result["result_hash"],
                "business_operation_id": result["business_operation_id"],
            },
            evidence_refs=result["evidence_refs"],
        )
    for result in agent_results:
        _append_event(
            events,
            event_time=result["created_at"],
            phase="RESULT",
            source_type="AGENT_RESULT",
            source_id=f"AE:AGENT_RESULT:{result['result_id']}",
            event_type="AGENT_RESULT_RECORDED",
            state=result["status"],
            details={"result_hash": result["result_hash"]},
        )
    for delivery in deliveries:
        delivery_id = str(delivery["delivery_id"])
        _append_event(
            events,
            event_time=delivery["created_at"],
            phase="PUBLICATION",
            source_type="RESULT_DELIVERY",
            source_id=f"AE:RESULT_DELIVERY:{delivery_id}:CREATED",
            event_type="RESULT_DELIVERY_CREATED",
            state="PENDING",
            details={
                "target_type": delivery["target_type"],
                "required": delivery["required"],
            },
        )
        _append_event(
            events,
            event_time=delivery["updated_at"],
            event_time_basis="CURRENT_SNAPSHOT",
            phase="PUBLICATION",
            source_type="RESULT_DELIVERY",
            source_id=f"AE:RESULT_DELIVERY:{delivery_id}:CURRENT",
            event_type="RESULT_DELIVERY_CURRENT",
            state=delivery["state"],
            details={
                "attempt_no": delivery["attempt_no"],
                "acknowledged_at": delivery.get("acknowledged_at"),
            },
        )
    ordered = sorted(
        events,
        key=lambda event: (
            event["event_time"],
            _PHASE_ORDER[event["phase"]],
            _SOURCE_ORDER[event["source_type"]],
            event["source_id"],
        ),
    )
    for sequence, event in enumerate(ordered, start=1):
        event["sequence"] = sequence
    projection = {
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "tenant_id": tenant,
        "agent_execution_id": execution_id,
        "ordering_profile": TIMELINE_ORDERING_PROFILE,
        "events": ordered,
        "projection_gaps": sorted(
            {canonical_json(gap): gap for gap in gaps}.values(),
            key=lambda gap: (gap["gap_code"], gap["scope_ref"]),
        ),
        "source_counts": {
            "agent_execution": 1,
            "agent_results": len(agent_results),
            "backend_runs": len(backend_runs),
            "bindings": len(bindings),
            "deliveries": len(deliveries),
            "jobs": len(jobs),
            "plans": len(plans),
            "runtime_attempts": len(attempts),
            "step_results": len(step_results),
            "steps": len(steps),
        },
    }
    projection["projection_hash"] = semantic_sha256_hash_ref(projection)
    return validate_agent_execution_timeline(projection)


def validate_agent_execution_timeline(value: Mapping[str, Any]) -> dict[str, Any]:
    projection = _canonical_mapping("AgentExecutionTimeline", value)
    fields = {
        "schema_version",
        "tenant_id",
        "agent_execution_id",
        "ordering_profile",
        "events",
        "projection_gaps",
        "source_counts",
        "projection_hash",
    }
    if set(projection) != fields or projection.get("schema_version") != "1.0":
        raise _invalid("AgentExecutionTimeline fields or version are invalid.")
    _text("tenant_id", projection["tenant_id"], 128)
    _uuid("agent_execution_id", projection["agent_execution_id"])
    if projection["ordering_profile"] != TIMELINE_ORDERING_PROFILE:
        raise _invalid("AgentExecutionTimeline ordering profile is invalid.")
    events = projection["events"]
    if not isinstance(events, list) or len(events) > 10_000:
        raise _invalid("AgentExecutionTimeline events must be bounded.")
    ordering: list[tuple[str, int, int, str]] = []
    for index, event in enumerate(events, start=1):
        if not isinstance(event, Mapping) or set(event) != {
            "sequence",
            "event_time",
            "event_time_basis",
            "phase",
            "source_type",
            "source_id",
            "event_type",
            "state",
            "details",
            "evidence_refs",
        }:
            raise _invalid("AgentExecutionTimeline event fields are invalid.")
        if event["sequence"] != index:
            raise _invalid("AgentExecutionTimeline sequence is invalid.")
        event_time = _timestamp("event_time", event["event_time"])
        if event["event_time_basis"] not in _TIME_BASES:
            raise _invalid("AgentExecutionTimeline time basis is invalid.")
        phase = event["phase"]
        source_type = event["source_type"]
        if phase not in _PHASE_ORDER or source_type not in _SOURCE_ORDER:
            raise _invalid("AgentExecutionTimeline phase or source is invalid.")
        source_id = _ref("source_id", event["source_id"])
        _text("event_type", event["event_type"], 128)
        _optional_text("state", event["state"], 64)
        _safe_details(event["details"])
        refs = _refs(event["evidence_refs"], 128)
        if refs != event["evidence_refs"]:
            raise _invalid("Timeline evidence refs must be canonical.")
        ordering.append(
            (event_time, _PHASE_ORDER[phase], _SOURCE_ORDER[source_type], source_id)
        )
    if ordering != sorted(ordering):
        raise _invalid(
            "AgentExecutionTimeline events are not deterministically ordered."
        )
    gaps = projection["projection_gaps"]
    if not isinstance(gaps, list) or len(gaps) > 256:
        raise _invalid("AgentExecutionTimeline gaps must be bounded.")
    for gap in gaps:
        if not isinstance(gap, Mapping) or set(gap) != {
            "gap_code",
            "scope_ref",
            "detail",
        }:
            raise _invalid("AgentExecutionTimeline gap fields are invalid.")
        _text("gap_code", gap["gap_code"], 128)
        _ref("scope_ref", gap["scope_ref"])
        _text("detail", gap["detail"], 512)
    counts = projection["source_counts"]
    if not isinstance(counts, Mapping) or any(
        not isinstance(key, str) or type(count) is not int or count < 0
        for key, count in counts.items()
    ):
        raise _invalid("AgentExecutionTimeline source counts are invalid.")
    supplied_hash = _hash("projection_hash", projection["projection_hash"])
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in projection.items() if key != "projection_hash"}
    )
    if supplied_hash != expected_hash:
        raise _invalid("AgentExecutionTimeline hash does not match its content.")
    return projection


def _load_sources(
    session: Session, tenant_id: str, execution_id: str
) -> dict[str, list[dict[str, Any]]]:
    params = {"tenant_id": tenant_id, "execution_id": execution_id}
    queries = {
        "plans": """
            SELECT executable_plan_id, executable_plan_version, plan_hash, compiled_at
            FROM ae_executable_plan WHERE tenant_id = :tenant_id
              AND agent_execution_id = :execution_id
            ORDER BY executable_plan_version
        """,
        "steps": """
            SELECT executable_step_id, logical_step_id, compiled_step_key,
                   executor_kind, state, version, result_ref, error_ref,
                   created_at, updated_at
            FROM ae_executable_step WHERE tenant_id = :tenant_id
              AND agent_execution_id = :execution_id
            ORDER BY step_index, executable_step_id
        """,
        "jobs": """
            SELECT runtime_job_id, job_type, executable_step_id, state, attempt_no,
                   created_at, updated_at
            FROM ae_runtime_job WHERE tenant_id = :tenant_id
              AND execution_id = :execution_id
            ORDER BY created_at, runtime_job_id
        """,
        "attempts": """
            SELECT a.attempt_id, a.runtime_job_id, a.attempt_no, a.worker_id,
                   a.started_at, a.ended_at, a.outcome, a.error_ref
            FROM ae_runtime_job_attempt a
            JOIN ae_runtime_job j ON j.tenant_id = a.tenant_id
                                 AND j.runtime_job_id = a.runtime_job_id
            WHERE a.tenant_id = :tenant_id AND j.execution_id = :execution_id
            ORDER BY a.started_at, a.attempt_id
        """,
        "bindings": """
            SELECT binding_json FROM ae_nsl_step_execution
            WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id
            ORDER BY allocated_at, executable_step_id
        """,
        "backend_runs": """
            SELECT r.record_json FROM ae_nsl_backend_run r
            JOIN ae_nsl_step_execution b
              ON b.tenant_id = r.tenant_id
             AND b.nsl_execution_id = r.nsl_execution_id
            WHERE r.tenant_id = :tenant_id AND b.agent_execution_id = :execution_id
            ORDER BY r.started_at, r.nsl_execution_id, r.attempt_no
        """,
        "step_results": """
            SELECT result_json FROM ae_step_result
            WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id
            ORDER BY completed_at, step_result_id
        """,
        "agent_results": """
            SELECT result_id, status, result_hash, created_at
            FROM ae_agent_result WHERE tenant_id = :tenant_id
              AND agent_execution_id = :execution_id
            ORDER BY created_at, result_id
        """,
        "deliveries": """
            SELECT delivery_id, target_type, required, state, attempt_no,
                   created_at, updated_at, acknowledged_at
            FROM ae_result_delivery WHERE tenant_id = :tenant_id
              AND agent_execution_id = :execution_id
            ORDER BY created_at, delivery_id
        """,
    }
    return {
        name: [
            _normalized_row(row)
            for row in session.execute(text(sql), params).mappings()
        ]
        for name, sql in queries.items()
    }


def _fetch_one(
    session: Session,
    sql: str,
    tenant_id: str,
    execution_id: str,
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(sql), {"tenant_id": tenant_id, "execution_id": execution_id}
        )
        .mappings()
        .first()
    )
    return None if row is None else _normalized_row(row)


def _append_event(
    events: list[dict[str, Any]],
    *,
    event_time: object,
    phase: str,
    source_type: str,
    source_id: str,
    event_type: str,
    state: object,
    details: Mapping[str, Any],
    evidence_refs: Sequence[str] = (),
    event_time_basis: str = "SOURCE_TIMESTAMP",
) -> None:
    event = {
        "sequence": 0,
        "event_time": _timestamp("event_time", event_time),
        "event_time_basis": event_time_basis,
        "phase": phase,
        "source_type": source_type,
        "source_id": _ref("source_id", source_id),
        "event_type": _text("event_type", event_type, 128),
        "state": _optional_text("state", state, 64),
        "details": _safe_details(details),
        "evidence_refs": _refs(evidence_refs, 128),
    }
    events.append(event)


def _gap(code: str, scope_ref: str, detail: str) -> dict[str, str]:
    return {
        "gap_code": _text("gap_code", code, 128),
        "scope_ref": _ref("scope_ref", scope_ref),
        "detail": _text("detail", detail, 512),
    }


def _safe_details(value: object) -> dict[str, Any]:
    details = _canonical_mapping("timeline details", value)

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key).lower() in _FORBIDDEN_DETAIL_KEYS:
                    raise _invalid("Timeline details contain private material.")
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(details)
    if len(canonical_json(details).encode("utf-8")) > 16_384:
        raise _invalid("Timeline details exceed the bounded projection size.")
    return details


def _normalized_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


def _json_value(value: object) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    return value


def _json_object(value: object) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise _invalid("Stored timeline source must be an object.")
    return dict(decoded)


def _canonical_mapping(name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{name} must be an object.")
    try:
        return json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be canonical JSON.") from exc


def _refs(value: object, maximum: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("Timeline evidence refs must be an array.")
    refs = [_ref("evidence_ref", item) for item in value]
    if len(refs) > maximum or len(set(refs)) != len(refs):
        raise _invalid("Timeline evidence refs must be bounded and unique.")
    return sorted(refs)


def _uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID.")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID.") from exc
    if str(parsed) != value:
        raise _invalid(f"{field} must be a canonical UUID.")
    return value


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a lowercase SHA-256 reference.") from exc


def _ref(field: str, value: object) -> str:
    return _text(field, value, 512)


def _text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _optional_text(field: str, value: object, maximum: int) -> str | None:
    return None if value is None else _text(field, value, maximum)


def _timestamp(field: str, value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an RFC3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> AgentExecutionTimelineError:
    return AgentExecutionTimelineError("ae.execution_timeline_invalid", detail)
