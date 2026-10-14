from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response, trace_id_from_headers
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.route_auth import authorize_ae_operations_request

AE_RUNTIME_OPERATIONS_PATH = "/internal/v1/operations/agent-runtime"
AE_RUNTIME_OPERATIONS_SCHEMA_VERSION = "ae_agent_runtime_operations.v1"


@dataclass(frozen=True)
class AgentRuntimeOperationsError(Exception):
    error_code: str
    detail: str
    status_code: int = 503
    retryable: bool = True

    def __str__(self) -> str:
        return self.detail


class AgentRuntimeOperationsSource(Protocol):
    def snapshot(self, *, observed_at: str) -> Mapping[str, Any]: ...


class UnavailableAgentRuntimeOperationsSource:
    def snapshot(self, *, observed_at: str) -> Mapping[str, Any]:
        del observed_at
        raise AgentRuntimeOperationsError(
            "ae.agent_runtime_operations.persistence_unavailable",
            "AE Agent Runtime operations require PostgreSQL persistence.",
        )


class SqlAlchemyAgentRuntimeOperationsSource:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        queue_name: str = "ae-runtime",
        sample_limit: int = 256,
    ) -> None:
        self._session_factory = session_factory
        self._queue_name = _required_text(queue_name, "queue_name")
        if (
            isinstance(sample_limit, bool)
            or not isinstance(sample_limit, int)
            or not 1 <= sample_limit <= 1_000
        ):
            raise AgentRuntimeOperationsError(
                "ae.agent_runtime_operations.config_invalid",
                "sample_limit must be between 1 and 1000.",
                500,
                False,
            )
        self._sample_limit = sample_limit

    def snapshot(self, *, observed_at: str) -> Mapping[str, Any]:
        now = _timestamp(observed_at)
        try:
            with self._session_factory() as session:
                queue = _one(session, _QUEUE_COUNTS_SQL, {"now": now})
                attempts = _one(session, _ATTEMPT_COUNTS_SQL, {})
                issues = session.execute(text(_ISSUE_COUNTS_SQL)).mappings().all()
                leadership = _one(
                    session,
                    _LEADERSHIP_SQL,
                    {"queue_name": self._queue_name},
                )
                workers = (
                    session.execute(
                        text(_WORKER_COUNTS_SQL),
                        {
                            "service_id": "nex-ae-api",
                            "worker_type": "ae.agent_runtime.worker",
                        },
                    )
                    .mappings()
                    .all()
                )
                job_types = session.execute(text(_JOB_TYPE_COUNTS_SQL)).mappings().all()
                timing_rows = (
                    session.execute(
                        text(_TIMING_SAMPLE_SQL), {"limit": self._sample_limit}
                    )
                    .mappings()
                    .all()
                )
                step_rows = (
                    session.execute(
                        text(_STEP_TIMING_SAMPLE_SQL), {"limit": self._sample_limit}
                    )
                    .mappings()
                    .all()
                )
                execution_rows = (
                    session.execute(
                        text(_EXECUTION_TIMING_SAMPLE_SQL),
                        {"limit": self._sample_limit},
                    )
                    .mappings()
                    .all()
                )
                return _build_snapshot(
                    observed_at=now,
                    queue=queue,
                    attempts=attempts,
                    issues=issues,
                    leadership=leadership,
                    workers=workers,
                    job_types=job_types,
                    timing_rows=timing_rows,
                    step_rows=step_rows,
                    execution_rows=execution_rows,
                )
        except AgentRuntimeOperationsError:
            raise
        except SQLAlchemyError as exc:
            raise AgentRuntimeOperationsError(
                "ae.agent_runtime_operations.store_unavailable",
                "AE Agent Runtime operations projection is unavailable.",
            ) from exc


def register_agent_runtime_operations_routes(
    app: FastAPI,
    *,
    source: AgentRuntimeOperationsSource,
    clock: Callable[[], datetime] | None = None,
) -> None:
    selected_clock = clock or (lambda: datetime.now(UTC))

    @app.get(AE_RUNTIME_OPERATIONS_PATH, response_model=None)
    def get_agent_runtime_operations(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_ae_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        observed = selected_clock()
        if observed.tzinfo is None:
            return _problem(
                request,
                AgentRuntimeOperationsError(
                    "ae.agent_runtime_operations.clock_invalid",
                    "AE Agent Runtime operations clock must be timezone-aware.",
                    500,
                    False,
                ),
            )
        try:
            snapshot = dict(source.snapshot(observed_at=_timestamp(observed)))
            return {
                **snapshot,
                "request_trace_id": trace_id_from_headers(request),
                "server_selected": True,
            }
        except AgentRuntimeOperationsError as exc:
            return _problem(request, exc)


def _build_snapshot(
    *,
    observed_at: str,
    queue: Mapping[str, Any],
    attempts: Mapping[str, Any],
    issues: list[Mapping[str, Any]],
    leadership: Mapping[str, Any],
    workers: list[Mapping[str, Any]],
    job_types: list[Mapping[str, Any]],
    timing_rows: list[Mapping[str, Any]],
    step_rows: list[Mapping[str, Any]],
    execution_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    oldest = queue.get("oldest_runnable_at")
    oldest_age = None
    if oldest is not None:
        oldest_age = max(
            0.0,
            (_parse_timestamp(observed_at) - _as_datetime(oldest)).total_seconds(),
        )
    lease_until = leadership.get("lease_until")
    released_at = leadership.get("released_at")
    leader_active = (
        lease_until is not None
        and released_at is None
        and _as_datetime(lease_until) > _parse_timestamp(observed_at)
    )
    return {
        "schema_version": AE_RUNTIME_OPERATIONS_SCHEMA_VERSION,
        "observed_at": observed_at,
        "queue": {
            "queued": _count(queue, "queued"),
            "running": _count(queue, "running"),
            "retrying": _count(queue, "retrying"),
            "delayed": _count(queue, "delayed"),
            "failed": _count(queue, "failed"),
            "dead_letter": _count(queue, "dead_letter"),
            "oldest_runnable_age_seconds": oldest_age,
        },
        "attempts": {
            "total": _count(attempts, "total"),
            "lease_expiry_count": _count(attempts, "lease_expired"),
            "reclaim_count": _count(attempts, "lease_expired"),
            "stale_completion_rejection_count": None,
            "stale_completion_evidence": "NOT_PERSISTED",
        },
        "latency_ms": {
            "claim": _average_duration_ms(
                timing_rows, start_key="created_at", end_key="started_at"
            ),
            "step": _average_duration_ms(
                step_rows,
                start_key="invocation_started_at",
                end_key="completed_at",
            ),
            "execution": _average_duration_ms(
                execution_rows, start_key="received_at", end_key="updated_at"
            ),
        },
        "leadership": {
            "queue_name": leadership.get("queue_name"),
            "active": leader_active,
            "fencing_token": (
                None
                if leadership.get("fencing_token") is None
                else int(leadership["fencing_token"])
            ),
            "lease_until": _datetime_or_none(lease_until),
        },
        "workers": {
            "status_counts": {
                str(row["status"]): int(row["worker_count"]) for row in workers
            },
            "heartbeat_count": sum(int(row["worker_count"]) for row in workers),
        },
        "issues": {
            "open_count": sum(int(row["issue_count"]) for row in issues),
            "reason_counts": {
                str(row["reason_code"]): int(row["issue_count"]) for row in issues
            },
        },
        "job_types": {
            str(row["job_type"]): {
                "total": int(row["total_count"]),
                "failed": int(row["failed_count"]),
            }
            for row in job_types
        },
        "privacy": {
            "tenant_ids_included": False,
            "principal_ids_included": False,
            "runtime_job_ids_included": False,
            "content_included": False,
            "credentials_included": False,
        },
        "mutation_authority": False,
    }


def _problem(request: Request, exc: AgentRuntimeOperationsError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="AE Agent Runtime operations unavailable",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/ae-agent-runtime-operations",
    )


def _one(session: Session, statement: str, params: Mapping[str, Any]) -> dict[str, Any]:
    row = session.execute(text(statement), params).mappings().first()
    return {} if row is None else dict(row)


def _average_duration_ms(
    rows: list[Mapping[str, Any]], *, start_key: str, end_key: str
) -> float | None:
    values = [
        max(
            0.0,
            (_as_datetime(row[end_key]) - _as_datetime(row[start_key])).total_seconds()
            * 1_000,
        )
        for row in rows
        if row.get(start_key) is not None and row.get(end_key) is not None
    ]
    return None if not values else round(sum(values) / len(values), 3)


def _count(value: Mapping[str, Any], key: str) -> int:
    return int(value.get(key) or 0)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentRuntimeOperationsError(
            "ae.agent_runtime_operations.config_invalid",
            f"{field_name} must be a non-empty string.",
            500,
            False,
        )
    return value.strip()


def _timestamp(value: object) -> str:
    parsed = _as_datetime(value)
    return parsed.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    return _as_datetime(value)


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise AgentRuntimeOperationsError(
                "ae.agent_runtime_operations.timestamp_invalid",
                "Operations source timestamp is invalid.",
                500,
                False,
            ) from exc
    else:
        raise AgentRuntimeOperationsError(
            "ae.agent_runtime_operations.timestamp_invalid",
            "Operations source timestamp is invalid.",
            500,
            False,
        )
    if parsed.tzinfo is None:
        raise AgentRuntimeOperationsError(
            "ae.agent_runtime_operations.timestamp_invalid",
            "Operations source timestamp must include a timezone.",
            500,
            False,
        )
    return parsed.astimezone(UTC)


def _datetime_or_none(value: object) -> str | None:
    return None if value is None else _timestamp(value)


_QUEUE_COUNTS_SQL = """
    SELECT
      sum(CASE WHEN state = 'QUEUED' AND run_after <= :now AND attempt_no = 0 THEN 1 ELSE 0 END) AS queued,
      sum(CASE WHEN state = 'RUNNING' AND lease_until > :now THEN 1 ELSE 0 END) AS running,
      sum(CASE WHEN state = 'QUEUED' AND run_after <= :now AND attempt_no > 0 THEN 1 ELSE 0 END) AS retrying,
      sum(CASE WHEN state = 'QUEUED' AND run_after > :now THEN 1 ELSE 0 END) AS delayed,
      sum(CASE WHEN state = 'FAILED' THEN 1 ELSE 0 END) AS failed,
      sum(CASE WHEN state = 'DEAD_LETTER' THEN 1 ELSE 0 END) AS dead_letter,
      min(CASE WHEN state = 'QUEUED' AND run_after <= :now THEN run_after ELSE NULL END) AS oldest_runnable_at
    FROM ae_runtime_job
"""

_ATTEMPT_COUNTS_SQL = """
    SELECT count(*) AS total,
           sum(CASE WHEN outcome = 'LEASE_EXPIRED' THEN 1 ELSE 0 END) AS lease_expired
    FROM ae_runtime_job_attempt
"""

_ISSUE_COUNTS_SQL = """
    SELECT reason_code, count(*) AS issue_count
    FROM ae_rt_job_issue
    WHERE issue_state = 'OPEN'
    GROUP BY reason_code
    ORDER BY reason_code
"""

_LEADERSHIP_SQL = """
    SELECT queue_name, fencing_token, lease_until, released_at
    FROM ae_rt_dispatch_lease
    WHERE queue_name = :queue_name
"""

_WORKER_COUNTS_SQL = """
    SELECT status, count(*) AS worker_count
    FROM service_worker_heartbeats
    WHERE service_id = :service_id AND worker_type = :worker_type
    GROUP BY status
    ORDER BY status
"""

_JOB_TYPE_COUNTS_SQL = """
    SELECT job_type, count(*) AS total_count,
           sum(CASE WHEN state IN ('FAILED', 'DEAD_LETTER') THEN 1 ELSE 0 END) AS failed_count
    FROM ae_runtime_job
    GROUP BY job_type
    ORDER BY job_type
"""

_TIMING_SAMPLE_SQL = """
    SELECT job.created_at, attempt.started_at
    FROM ae_runtime_job_attempt AS attempt
    JOIN ae_runtime_job AS job
      ON job.tenant_id = attempt.tenant_id
     AND job.runtime_job_id = attempt.runtime_job_id
    ORDER BY attempt.started_at DESC
    LIMIT :limit
"""

_STEP_TIMING_SAMPLE_SQL = """
    SELECT invocation_started_at, completed_at
    FROM ae_executable_step
    WHERE invocation_started_at IS NOT NULL AND completed_at IS NOT NULL
    ORDER BY completed_at DESC
    LIMIT :limit
"""

_EXECUTION_TIMING_SAMPLE_SQL = """
    SELECT received_at, updated_at
    FROM ae_agent_execution
    WHERE state IN ('SUCCEEDED', 'FAILED', 'CANCELLED')
    ORDER BY updated_at DESC
    LIMIT :limit
"""
