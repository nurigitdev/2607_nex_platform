from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

P4_RUNTIME_JOB_TYPES = frozenset({"START_EXECUTION", "CONTINUE_EXECUTION"})
RUNTIME_JOB_TYPES = P4_RUNTIME_JOB_TYPES | {"RESUME_EXECUTION"}
RUNTIME_JOB_STATES = frozenset(
    {"QUEUED", "RUNNING", "DONE", "FAILED", "CANCELLED", "DEAD_LETTER"}
)
RUNTIME_ATTEMPT_OUTCOMES = frozenset(
    {"RUNNING", "DONE", "FAILED", "LEASE_EXPIRED", "CANCELLED"}
)
RUNTIME_ADMISSION_POLICIES = frozenset({"REJECT", "DELAY"})
_PRIVATE_PAYLOAD_KEYS = frozenset(
    {"content", "message_text", "prompt", "raw_content", "response"}
)


@dataclass(frozen=True)
class RuntimeJobError(Exception):
    error_code: str
    detail: str
    retryable: bool = False
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class RuntimeJobClaim:
    job: dict[str, Any]
    attempt: dict[str, Any]
    executor_kind: str | None = None
    backend_profile: str | None = None


class SqlAlchemyRuntimeJobQueue:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        id_factory: Callable[[], str] | None = None,
        max_runnable_depth: int | None = None,
        admission_policy: str = "DELAY",
        admission_delay_seconds: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._max_runnable_depth = _optional_positive_int(
            "max_runnable_depth", max_runnable_depth
        )
        self._admission_policy = _admission_policy(admission_policy)
        self._admission_delay_seconds = _positive_int(
            "admission_delay_seconds", admission_delay_seconds
        )

    def enqueue_unique(
        self,
        *,
        tenant_id: str,
        runtime_job_id: str,
        job_type: Literal["START_EXECUTION", "CONTINUE_EXECUTION", "RESUME_EXECUTION"],
        execution_id: str,
        dedup_key: str,
        run_after: str,
        correlation_id: str,
        now: str,
        executable_step_id: str | None = None,
        wait_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        causation_id: str | None = None,
    ) -> dict[str, Any]:
        if job_type not in RUNTIME_JOB_TYPES:
            raise _invalid(
                "RuntimeJob type must be START_EXECUTION, CONTINUE_EXECUTION, "
                "or RESUME_EXECUTION."
            )
        normalized_wait_id = _optional("wait_id", wait_id)
        if job_type == "RESUME_EXECUTION":
            if executable_step_id is None or normalized_wait_id is None:
                raise _invalid(
                    "RESUME_EXECUTION requires executable_step_id and wait_id."
                )
        elif normalized_wait_id is not None:
            raise _invalid("Only RESUME_EXECUTION may reference wait_id.")
        normalized_payload = _payload(payload)
        params = {
            "tenant_id": _required("tenant_id", tenant_id),
            "runtime_job_id": _required("runtime_job_id", runtime_job_id),
            "job_type": job_type,
            "execution_id": _required("execution_id", execution_id),
            "executable_step_id": _optional("executable_step_id", executable_step_id),
            "wait_id": normalized_wait_id,
            "dedup_key": _required("dedup_key", dedup_key),
            "run_after": _timestamp("run_after", run_after),
            "payload_json": json.dumps(
                normalized_payload, sort_keys=True, separators=(",", ":")
            ),
            "correlation_id": _required("correlation_id", correlation_id),
            "causation_id": _optional("causation_id", causation_id),
            "now": _timestamp("now", now),
        }
        try:
            with self._session_factory() as session:
                saved = self._enqueue_prepared(
                    session, params=params, payload=normalized_payload
                )
                session.commit()
                return saved
        except RuntimeJobError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def enqueue_resume_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        runtime_job_id: str,
        execution_id: str,
        executable_step_id: str,
        wait_id: str,
        dedup_key: str,
        run_after: str,
        correlation_id: str,
        now: str,
        payload: Mapping[str, Any],
        causation_id: str,
    ) -> dict[str, Any]:
        normalized_payload = _payload(payload)
        params = {
            "tenant_id": _required("tenant_id", tenant_id),
            "runtime_job_id": _required("runtime_job_id", runtime_job_id),
            "job_type": "RESUME_EXECUTION",
            "execution_id": _required("execution_id", execution_id),
            "executable_step_id": _required("executable_step_id", executable_step_id),
            "wait_id": _required("wait_id", wait_id),
            "dedup_key": _required("dedup_key", dedup_key),
            "run_after": _timestamp("run_after", run_after),
            "payload_json": json.dumps(
                normalized_payload, sort_keys=True, separators=(",", ":")
            ),
            "correlation_id": _required("correlation_id", correlation_id),
            "causation_id": _required("causation_id", causation_id),
            "now": _timestamp("now", now),
        }
        return self._enqueue_prepared(
            session, params=params, payload=normalized_payload
        )

    def _enqueue_prepared(
        self,
        session: Session,
        *,
        params: dict[str, Any],
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self._max_runnable_depth is not None:
            _lock_runtime_admission(session)
            existing = _load_by_dedup(session, params["tenant_id"], params["dedup_key"])
            if existing is not None:
                _require_same_job(existing, params, payload)
                return existing
            params["run_after"] = _apply_admission_policy(
                session,
                run_after=params["run_after"],
                now=params["now"],
                max_runnable_depth=self._max_runnable_depth,
                admission_policy=self._admission_policy,
                admission_delay_seconds=self._admission_delay_seconds,
            )
        if not _execution_exists(session, params["tenant_id"], params["execution_id"]):
            raise RuntimeJobError(
                "ae.runtime_job_execution_not_found",
                "RuntimeJob requires an existing AgentExecution in the same tenant.",
            )
        inserted = session.execute(text(_insert_sql(session)), params)
        saved = _load_by_dedup(session, params["tenant_id"], params["dedup_key"])
        if saved is None:
            raise RuntimeJobError(
                "ae.runtime_job_write_conflict",
                "RuntimeJob could not be reloaded after enqueue.",
                True,
            )
        if int(inserted.rowcount or 0) == 0:
            _require_same_job(saved, params, payload)
        return saved

    def get(self, tenant_id: str, runtime_job_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_job(
                    session,
                    _required("tenant_id", tenant_id),
                    _required("runtime_job_id", runtime_job_id),
                )
        except RuntimeJobError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def claim(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        lease_seconds: int,
        now: str,
    ) -> RuntimeJobClaim | None:
        tenant = _required("tenant_id", tenant_id)
        worker = _required("worker_id", worker_id)
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds < 1
        ):
            raise _invalid("lease_seconds must be a positive integer.")
        observed_at = _timestamp("now", now)
        lease_until = _format_timestamp(
            _parse_timestamp("now", observed_at) + timedelta(seconds=lease_seconds)
        )
        try:
            with self._session_factory() as session:
                candidate = _select_runnable(session, tenant, observed_at)
                if candidate is None:
                    return None
                if candidate["state"] == "RUNNING":
                    _expire_attempt(session, candidate, observed_at)
                attempt_no = int(candidate["attempt_no"]) + 1
                lease_token = _required("lease_token", self._id_factory())
                attempt_id = _required("attempt_id", self._id_factory())
                params = {
                    "tenant_id": tenant,
                    "runtime_job_id": str(candidate["runtime_job_id"]),
                    "expected_state": candidate["state"],
                    "expected_lease_token": candidate["lease_token"],
                    "worker_id": worker,
                    "lease_token": lease_token,
                    "lease_until": lease_until,
                    "attempt_no": attempt_no,
                    "attempt_id": attempt_id,
                    "now": observed_at,
                }
                updated = session.execute(text(_CLAIM_SQL), params)
                if int(updated.rowcount or 0) == 0:
                    session.rollback()
                    return None
                session.execute(text(_ATTEMPT_INSERT_SQL), params)
                job = _load_job(session, tenant, params["runtime_job_id"])
                attempt = _load_attempt(session, attempt_id)
                if job is None or attempt is None:
                    raise RuntimeJobError(
                        "ae.runtime_job_write_conflict",
                        "Claimed RuntimeJob could not be reloaded.",
                        True,
                    )
                session.commit()
                return RuntimeJobClaim(job=job, attempt=attempt)
        except RuntimeJobError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def claim_capability_aware(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        supported_executor_kinds: Sequence[str],
        supported_backend_profiles: Sequence[str] | None = None,
        lease_seconds: int,
        now: str,
        queue_name: str | None = None,
        dispatcher_id: str | None = None,
        fencing_token: int | None = None,
    ) -> RuntimeJobClaim | None:
        tenant = _required("tenant_id", tenant_id)
        worker = _required("worker_id", worker_id)
        executor_kinds = _executor_kinds(supported_executor_kinds)
        backend_profiles = (
            None
            if supported_backend_profiles is None
            else _backend_profiles(supported_backend_profiles)
        )
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or lease_seconds < 1
        ):
            raise _invalid("lease_seconds must be a positive integer.")
        leadership = _leadership_params(
            queue_name=queue_name,
            dispatcher_id=dispatcher_id,
            fencing_token=fencing_token,
        )
        observed_at = _timestamp("now", now)
        lease_until = _format_timestamp(
            _parse_timestamp("now", observed_at) + timedelta(seconds=lease_seconds)
        )
        try:
            with self._session_factory() as session:
                candidate = _select_capability_runnable(
                    session,
                    tenant_id=tenant,
                    executor_kinds=executor_kinds,
                    backend_profiles=backend_profiles,
                    now=observed_at,
                    leadership=leadership,
                )
                if candidate is None:
                    return None
                if candidate["state"] == "RUNNING":
                    _expire_attempt(session, candidate, observed_at)
                attempt_no = int(candidate["attempt_no"]) + 1
                lease_token = _required("lease_token", self._id_factory())
                attempt_id = _required("attempt_id", self._id_factory())
                params: dict[str, Any] = {
                    "tenant_id": tenant,
                    "runtime_job_id": str(candidate["runtime_job_id"]),
                    "expected_state": candidate["state"],
                    "expected_lease_token": candidate["lease_token"],
                    "worker_id": worker,
                    "lease_token": lease_token,
                    "lease_until": lease_until,
                    "attempt_no": attempt_no,
                    "attempt_id": attempt_id,
                    "now": observed_at,
                    "executor_kinds": list(executor_kinds),
                    **leadership,
                }
                statement = text(
                    _CAPABILITY_CLAIM_SQL
                    + (_LEADERSHIP_CLAIM_PREDICATE if leadership else "")
                ).bindparams(bindparam("executor_kinds", expanding=True))
                updated = session.execute(statement, params)
                if int(updated.rowcount or 0) == 0:
                    session.rollback()
                    return None
                session.execute(text(_ATTEMPT_INSERT_SQL), params)
                job = _load_job(session, tenant, params["runtime_job_id"])
                attempt = _load_attempt(session, attempt_id)
                if job is None or attempt is None:
                    raise RuntimeJobError(
                        "ae.runtime_job_write_conflict",
                        "Capability-aware RuntimeJob claim could not be reloaded.",
                        True,
                    )
                session.commit()
                return RuntimeJobClaim(
                    job=job,
                    attempt=attempt,
                    executor_kind=str(candidate["executor_kind"]),
                    backend_profile=(
                        None
                        if candidate["backend_profile"] is None
                        else str(candidate["backend_profile"])
                    ),
                )
        except RuntimeJobError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def complete(
        self,
        *,
        tenant_id: str,
        runtime_job_id: str,
        worker_id: str,
        lease_token: str,
        now: str,
    ) -> dict[str, Any]:
        return self._finish(
            tenant_id=tenant_id,
            runtime_job_id=runtime_job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            now=now,
            job_state="DONE",
            attempt_outcome="DONE",
            error_ref=None,
            retry_disposition_ref=None,
            run_after=None,
        )

    def fail(
        self,
        *,
        tenant_id: str,
        runtime_job_id: str,
        worker_id: str,
        lease_token: str,
        now: str,
        error_ref: str,
        retry_at: str | None = None,
        retry_disposition_ref: str | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise _invalid("max_attempts must be a positive integer.")
        current = self.get(tenant_id, runtime_job_id)
        if current is None:
            raise _not_found()
        retry_time = None if retry_at is None else _timestamp("retry_at", retry_at)
        if retry_time is None:
            state = "FAILED"
        elif int(current["attempt_no"]) >= max_attempts:
            state = "DEAD_LETTER"
        else:
            state = "QUEUED"
        return self._finish(
            tenant_id=tenant_id,
            runtime_job_id=runtime_job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            now=now,
            job_state=state,
            attempt_outcome="FAILED",
            error_ref=_required("error_ref", error_ref),
            retry_disposition_ref=_optional(
                "retry_disposition_ref", retry_disposition_ref
            ),
            run_after=retry_time,
        )

    def cancel(
        self,
        *,
        tenant_id: str,
        runtime_job_id: str,
        now: str,
        worker_id: str | None = None,
        lease_token: str | None = None,
    ) -> dict[str, Any]:
        tenant = _required("tenant_id", tenant_id)
        job_id = _required("runtime_job_id", runtime_job_id)
        observed_at = _timestamp("now", now)
        try:
            with self._session_factory() as session:
                job = _load_job_for_update(session, tenant, job_id)
                if job is None:
                    raise _not_found()
                if job["state"] == "CANCELLED":
                    return job
                if job["state"] == "RUNNING":
                    _require_current_lease(job, worker_id, lease_token, observed_at)
                    updated_attempt = session.execute(
                        text(_ATTEMPT_FINISH_SQL),
                        {
                            "tenant_id": tenant,
                            "runtime_job_id": job_id,
                            "attempt_no": job["attempt_no"],
                            "lease_token": lease_token,
                            "outcome": "CANCELLED",
                            "error_ref": None,
                            "retry_disposition_ref": None,
                            "now": observed_at,
                        },
                    )
                    if int(updated_attempt.rowcount or 0) != 1:
                        raise RuntimeJobError(
                            "ae.runtime_job_write_conflict",
                            "RuntimeJob cancellation has no matching running attempt.",
                            True,
                        )
                elif job["state"] != "QUEUED":
                    raise RuntimeJobError(
                        "ae.runtime_job_terminal",
                        "Terminal RuntimeJob cannot be cancelled.",
                    )
                session.execute(
                    text(_CANCEL_SQL),
                    {"tenant_id": tenant, "runtime_job_id": job_id, "now": observed_at},
                )
                saved = _load_job(session, tenant, job_id)
                if saved is None:
                    raise RuntimeJobError(
                        "ae.runtime_job_write_conflict",
                        "Cancelled RuntimeJob could not be reloaded.",
                        True,
                    )
                session.commit()
                return saved
        except RuntimeJobError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_attempts(
        self, tenant_id: str, runtime_job_id: str
    ) -> tuple[dict[str, Any], ...]:
        params = {
            "tenant_id": _required("tenant_id", tenant_id),
            "runtime_job_id": _required("runtime_job_id", runtime_job_id),
        }
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(text(_ATTEMPTS_SELECT_SQL), params).mappings().all()
                )
                return tuple(_attempt_from_row(row) for row in rows)
        except RuntimeJobError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def _finish(
        self,
        *,
        tenant_id: str,
        runtime_job_id: str,
        worker_id: str,
        lease_token: str,
        now: str,
        job_state: str,
        attempt_outcome: str,
        error_ref: str | None,
        retry_disposition_ref: str | None,
        run_after: str | None,
    ) -> dict[str, Any]:
        tenant = _required("tenant_id", tenant_id)
        job_id = _required("runtime_job_id", runtime_job_id)
        worker = _required("worker_id", worker_id)
        token = _required("lease_token", lease_token)
        observed_at = _timestamp("now", now)
        try:
            with self._session_factory() as session:
                job = _load_job_for_update(session, tenant, job_id)
                if job is None:
                    raise _not_found()
                _require_current_lease(job, worker, token, observed_at)
                params = {
                    "tenant_id": tenant,
                    "runtime_job_id": job_id,
                    "worker_id": worker,
                    "lease_token": token,
                    "attempt_no": job["attempt_no"],
                    "job_state": job_state,
                    "outcome": attempt_outcome,
                    "error_ref": error_ref,
                    "retry_disposition_ref": retry_disposition_ref,
                    "run_after": run_after or job["run_after"],
                    "now": observed_at,
                }
                updated_attempt = session.execute(text(_ATTEMPT_FINISH_SQL), params)
                updated_job = session.execute(text(_FINISH_SQL), params)
                if (
                    int(updated_attempt.rowcount or 0) != 1
                    or int(updated_job.rowcount or 0) != 1
                ):
                    raise RuntimeJobError(
                        "ae.runtime_job_write_conflict",
                        "RuntimeJob lease changed while recording its outcome.",
                        True,
                    )
                saved = _load_job(session, tenant, job_id)
                if saved is None:
                    raise RuntimeJobError(
                        "ae.runtime_job_write_conflict",
                        "Finished RuntimeJob could not be reloaded.",
                        True,
                    )
                session.commit()
                return saved
        except RuntimeJobError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def _insert_sql(session: Session) -> str:
    payload = (
        "CAST(:payload_json AS JSONB)"
        if session.get_bind().dialect.name == "postgresql"
        else ":payload_json"
    )
    return _INSERT_SQL.replace(":payload_expression", payload)


_INSERT_SQL = """
    INSERT INTO ae_runtime_job (
        tenant_id, runtime_job_id, job_type, execution_id, executable_step_id,
        wait_id,
        state, dedup_key, attempt_no, run_after, payload_json, correlation_id,
        causation_id, created_at, updated_at
    ) VALUES (
        :tenant_id, :runtime_job_id, :job_type, :execution_id,
        :executable_step_id, :wait_id, 'QUEUED', :dedup_key, 0, :run_after,
        :payload_expression, :correlation_id, :causation_id, :now, :now
    ) ON CONFLICT (tenant_id, dedup_key) DO NOTHING
"""

_CLAIM_SQL = """
    UPDATE ae_runtime_job
    SET state = 'RUNNING', lease_owner = :worker_id, lease_token = :lease_token,
        lease_until = :lease_until, attempt_no = :attempt_no, updated_at = :now
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
      AND state = :expected_state
      AND (lease_token = :expected_lease_token OR
           (lease_token IS NULL AND :expected_lease_token IS NULL))
      AND ((state = 'QUEUED' AND run_after <= :now)
           OR (state = 'RUNNING' AND lease_until <= :now))
"""

_CAPABILITY_CLAIM_SQL = """
    UPDATE ae_runtime_job
    SET state = 'RUNNING', lease_owner = :worker_id, lease_token = :lease_token,
        lease_until = :lease_until, attempt_no = :attempt_no, updated_at = :now
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
      AND state = :expected_state
      AND (lease_token = :expected_lease_token OR
           (lease_token IS NULL AND :expected_lease_token IS NULL))
      AND ((state = 'QUEUED' AND run_after <= :now)
           OR (state = 'RUNNING' AND lease_until <= :now))
      AND EXISTS (
          SELECT 1
          FROM ae_executable_step AS step
          WHERE step.tenant_id = ae_runtime_job.tenant_id
            AND step.executable_step_id = ae_runtime_job.executable_step_id
            AND step.executor_kind IN :executor_kinds
      )
"""

_LEADERSHIP_CLAIM_PREDICATE = """
      AND EXISTS (
          SELECT 1
          FROM ae_rt_dispatch_lease AS leadership
          WHERE leadership.queue_name = :queue_name
            AND leadership.owner_id = :dispatcher_id
            AND leadership.fencing_token = :fencing_token
            AND leadership.released_at IS NULL
            AND leadership.lease_until > :now
      )
"""

_ATTEMPT_INSERT_SQL = """
    INSERT INTO ae_runtime_job_attempt (
        attempt_id, tenant_id, runtime_job_id, attempt_no, worker_id,
        lease_token, started_at, outcome
    ) VALUES (
        :attempt_id, :tenant_id, :runtime_job_id, :attempt_no, :worker_id,
        :lease_token, :now, 'RUNNING'
    )
"""

_ATTEMPT_FINISH_SQL = """
    UPDATE ae_runtime_job_attempt
    SET ended_at = :now, outcome = :outcome, error_ref = :error_ref,
        retry_disposition_ref = :retry_disposition_ref
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
      AND attempt_no = :attempt_no AND lease_token = :lease_token
      AND outcome = 'RUNNING'
"""

_FINISH_SQL = """
    UPDATE ae_runtime_job
    SET state = :job_state, run_after = :run_after, lease_owner = NULL,
        lease_token = NULL, lease_until = NULL, updated_at = :now
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
      AND state = 'RUNNING' AND lease_owner = :worker_id
      AND lease_token = :lease_token AND lease_until > :now
"""

_CANCEL_SQL = """
    UPDATE ae_runtime_job
    SET state = 'CANCELLED', lease_owner = NULL, lease_token = NULL,
        lease_until = NULL, updated_at = :now
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
"""

_JOB_SELECT = """
    SELECT tenant_id, runtime_job_id, job_type, execution_id,
           executable_step_id, wait_id, reconciliation_id,
           result_delivery_id, publication_reconciliation_id, state,
           dedup_key, attempt_no, run_after, lease_owner, lease_token,
           lease_until, payload_json, correlation_id, causation_id,
           created_at, updated_at
    FROM ae_runtime_job
"""

_ATTEMPTS_SELECT_SQL = """
    SELECT attempt_id, tenant_id, runtime_job_id, attempt_no, worker_id,
           lease_token, started_at, ended_at, outcome, error_ref,
           retry_disposition_ref
    FROM ae_runtime_job_attempt
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
    ORDER BY attempt_no
"""


def _execution_exists(session: Session, tenant_id: str, execution_id: str) -> bool:
    return (
        session.execute(
            text(
                "SELECT 1 FROM ae_agent_execution "
                "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id"
            ),
            {"tenant_id": tenant_id, "execution_id": execution_id},
        ).first()
        is not None
    )


def _load_by_dedup(
    session: Session, tenant_id: str, dedup_key: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                _JOB_SELECT + " WHERE tenant_id = :tenant_id AND dedup_key = :dedup_key"
            ),
            {"tenant_id": tenant_id, "dedup_key": dedup_key},
        )
        .mappings()
        .first()
    )
    return None if row is None else _job_from_row(row)


def _load_job(
    session: Session, tenant_id: str, runtime_job_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                _JOB_SELECT
                + " WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id"
            ),
            {"tenant_id": tenant_id, "runtime_job_id": runtime_job_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _job_from_row(row)


def _load_job_for_update(
    session: Session, tenant_id: str, runtime_job_id: str
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if session.get_bind().dialect.name == "postgresql" else ""
    row = (
        session.execute(
            text(
                _JOB_SELECT
                + " WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id"
                + suffix
            ),
            {"tenant_id": tenant_id, "runtime_job_id": runtime_job_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _job_from_row(row)


def _select_runnable(
    session: Session, tenant_id: str, now: str
) -> Mapping[str, Any] | None:
    suffix = (
        " FOR UPDATE SKIP LOCKED"
        if session.get_bind().dialect.name == "postgresql"
        else ""
    )
    return (
        session.execute(
            text(
                _JOB_SELECT
                + """
            WHERE tenant_id = :tenant_id
              AND ((state = 'QUEUED' AND run_after <= :now)
                   OR (state = 'RUNNING' AND lease_until <= :now))
            ORDER BY CASE WHEN state = 'RUNNING' THEN 0 ELSE 1 END,
                     run_after, created_at, runtime_job_id
            LIMIT 1
            """
                + suffix
            ),
            {"tenant_id": tenant_id, "now": now},
        )
        .mappings()
        .first()
    )


def _select_capability_runnable(
    session: Session,
    *,
    tenant_id: str,
    executor_kinds: tuple[str, ...],
    backend_profiles: tuple[str, ...] | None,
    now: str,
    leadership: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    dialect = session.get_bind().dialect.name
    leadership_join = ""
    leadership_predicate = ""
    if leadership:
        leadership_join = (
            " JOIN ae_rt_dispatch_lease AS leadership"
            " ON leadership.queue_name = :queue_name"
        )
        leadership_predicate = (
            " AND leadership.owner_id = :dispatcher_id"
            " AND leadership.fencing_token = :fencing_token"
            " AND leadership.released_at IS NULL"
            " AND leadership.lease_until > :now"
        )
    lock_suffix = (
        " FOR UPDATE OF job, step SKIP LOCKED" if dialect == "postgresql" else ""
    )
    backend_expression = (
        "step.skill_binding_json ->> 'backend_profile'"
        if dialect == "postgresql"
        else "json_extract(step.skill_binding_json, '$.backend_profile')"
    )
    backend_selection = (
        f", {backend_expression} AS backend_profile"
        if backend_profiles is not None
        else ", NULL AS backend_profile"
    )
    backend_predicate = (
        " AND (step.executor_kind <> 'LOCAL_SKILL' "
        f"OR {backend_expression} IN :backend_profiles)"
        if backend_profiles is not None
        else ""
    )
    statement = text(
        """
        SELECT job.tenant_id, job.runtime_job_id, job.job_type,
               job.execution_id, job.executable_step_id, job.wait_id,
               job.reconciliation_id, job.result_delivery_id,
               job.publication_reconciliation_id, job.state, job.dedup_key,
               job.attempt_no, job.run_after, job.lease_owner,
               job.lease_token, job.lease_until, job.payload_json,
               job.correlation_id, job.causation_id, job.created_at,
               job.updated_at, step.executor_kind
        """
        + backend_selection
        + """
        FROM ae_runtime_job AS job
        JOIN ae_executable_step AS step
          ON step.tenant_id = job.tenant_id
         AND step.executable_step_id = job.executable_step_id
        """
        + leadership_join
        + """
        WHERE job.tenant_id = :tenant_id
          AND step.executor_kind IN :executor_kinds
        """
        + backend_predicate
        + """
          AND ((job.state = 'QUEUED' AND job.run_after <= :now)
               OR (job.state = 'RUNNING' AND job.lease_until <= :now))
        """
        + leadership_predicate
        + """
        ORDER BY CASE WHEN job.state = 'RUNNING' THEN 0 ELSE 1 END,
                 job.run_after, job.created_at, job.runtime_job_id
        LIMIT 1
        """
        + lock_suffix
    ).bindparams(bindparam("executor_kinds", expanding=True))
    if backend_profiles is not None:
        statement = statement.bindparams(bindparam("backend_profiles", expanding=True))
    return (
        session.execute(
            statement,
            {
                "tenant_id": tenant_id,
                "executor_kinds": list(executor_kinds),
                **(
                    {"backend_profiles": list(backend_profiles)}
                    if backend_profiles is not None
                    else {}
                ),
                "now": now,
                **leadership,
            },
        )
        .mappings()
        .first()
    )


def _expire_attempt(session: Session, candidate: Mapping[str, Any], now: str) -> None:
    updated = session.execute(
        text(
            """
            UPDATE ae_runtime_job_attempt
            SET outcome = 'LEASE_EXPIRED', ended_at = :now
            WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
              AND attempt_no = :attempt_no AND lease_token = :lease_token
              AND outcome = 'RUNNING'
            """
        ),
        {
            "tenant_id": candidate["tenant_id"],
            "runtime_job_id": candidate["runtime_job_id"],
            "attempt_no": candidate["attempt_no"],
            "lease_token": candidate["lease_token"],
            "now": now,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise RuntimeJobError(
            "ae.runtime_job_attempt_conflict",
            "Expired RuntimeJob has no matching running attempt.",
            True,
        )


def _load_attempt(session: Session, attempt_id: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
            SELECT attempt_id, tenant_id, runtime_job_id, attempt_no, worker_id,
                   lease_token, started_at, ended_at, outcome, error_ref,
                   retry_disposition_ref
            FROM ae_runtime_job_attempt WHERE attempt_id = :attempt_id
            """
            ),
            {"attempt_id": attempt_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _attempt_from_row(row)


def _job_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_payload = row["payload_json"]
    payload = (
        json.loads(raw_payload) if isinstance(raw_payload, str) else dict(raw_payload)
    )
    return {
        "schema_version": "2.1",
        "tenant_id": row["tenant_id"],
        "runtime_job_id": str(row["runtime_job_id"]),
        "job_type": row["job_type"],
        "execution_id": str(row["execution_id"]),
        "executable_step_id": _string_or_none(row["executable_step_id"]),
        "wait_id": _string_or_none(row["wait_id"]),
        "reconciliation_id": _string_or_none(row["reconciliation_id"]),
        "state": row["state"],
        "dedup_key": row["dedup_key"],
        "attempt_no": int(row["attempt_no"]),
        "run_after": _datetime_value(row["run_after"]),
        "lease_owner": row["lease_owner"],
        "lease_token": row["lease_token"],
        "lease_until": _datetime_or_none(row["lease_until"]),
        "payload": payload,
        "correlation_id": row["correlation_id"],
        "causation_id": row["causation_id"],
        "created_at": _datetime_value(row["created_at"]),
        "updated_at": _datetime_value(row["updated_at"]),
        "result_delivery_id": _string_or_none(row["result_delivery_id"]),
        "publication_reconciliation_id": _string_or_none(
            row["publication_reconciliation_id"]
        ),
    }


def _attempt_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "attempt_id": str(row["attempt_id"]),
        "tenant_id": row["tenant_id"],
        "runtime_job_id": str(row["runtime_job_id"]),
        "attempt_no": int(row["attempt_no"]),
        "worker_id": row["worker_id"],
        "lease_token": row["lease_token"],
        "started_at": _datetime_value(row["started_at"]),
        "ended_at": _datetime_or_none(row["ended_at"]),
        "outcome": row["outcome"],
        "error_ref": row["error_ref"],
        "retry_disposition_ref": row["retry_disposition_ref"],
    }


def _require_same_job(
    existing: Mapping[str, Any], params: Mapping[str, Any], payload: Mapping[str, Any]
) -> None:
    keys = (
        "job_type",
        "execution_id",
        "executable_step_id",
        "correlation_id",
        "causation_id",
    )
    if (
        any(_comparable(existing[key]) != _comparable(params[key]) for key in keys)
        or _comparable(existing.get("wait_id"))
        != _comparable(params.get("wait_id"))
        or _parse_timestamp("run_after", existing["run_after"])
        != _parse_timestamp("run_after", params["run_after"])
        or existing["payload"] != payload
    ):
        raise RuntimeJobError(
            "ae.runtime_job_dedup_conflict",
            "RuntimeJob dedup key was reused with different semantics.",
        )


def _require_current_lease(
    job: Mapping[str, Any], worker_id: object, lease_token: object, now: str
) -> None:
    worker = _required("worker_id", worker_id)
    token = _required("lease_token", lease_token)
    if (
        job["state"] != "RUNNING"
        or job["lease_owner"] != worker
        or job["lease_token"] != token
        or job["lease_until"] is None
        or _parse_timestamp("lease_until", job["lease_until"])
        <= _parse_timestamp("now", now)
    ):
        raise RuntimeJobError(
            "ae.runtime_job_stale_lease",
            "RuntimeJob completion requires its current unexpired worker lease.",
            True,
        )


def _payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = {} if value is None else dict(value)
    _reject_private_payload(payload)
    try:
        json.dumps(payload, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise _invalid("RuntimeJob payload must be JSON serializable.") from exc
    return payload


def _reject_private_payload(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).strip().lower() in _PRIVATE_PAYLOAD_KEYS:
                raise _invalid(
                    "RuntimeJob payload must contain references, not raw content."
                )
            _reject_private_payload(nested)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_private_payload(item)


def _timestamp(field: str, value: object) -> str:
    return _format_timestamp(_parse_timestamp(field, value))


def _parse_timestamp(field: str, value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be an RFC 3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string.")
    return value.strip()


def _optional(field: str, value: object) -> str | None:
    return None if value is None else _required(field, value)


def _datetime_value(value: Any) -> str:
    return (
        value.isoformat().replace("+00:00", "Z")
        if hasattr(value, "isoformat")
        else str(value)
    )


def _datetime_or_none(value: Any) -> str | None:
    return None if value is None else _datetime_value(value)


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _comparable(value: Any) -> Any:
    return None if value is None else str(value)


def _lock_runtime_admission(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('ae-runtime-admission'))")
        )


def _apply_admission_policy(
    session: Session,
    *,
    run_after: str,
    now: str,
    max_runnable_depth: int,
    admission_policy: str,
    admission_delay_seconds: int,
) -> str:
    if _parse_timestamp("run_after", run_after) > _parse_timestamp("now", now):
        return run_after
    depth = int(
        session.execute(
            text(
                "SELECT count(*) FROM ae_runtime_job "
                "WHERE state = 'QUEUED' AND run_after <= :now"
            ),
            {"now": now},
        ).scalar_one()
    )
    if depth < max_runnable_depth:
        return run_after
    if admission_policy == "DELAY":
        raise RuntimeJobError(
            "ae.runtime_job_backpressure_delayed",
            "RuntimeJob admission is delayed because runnable capacity is exhausted.",
            True,
            admission_delay_seconds,
        )
    raise RuntimeJobError(
        "ae.runtime_job_backpressure_rejected",
        "RuntimeJob admission is rejected because runnable capacity is exhausted.",
        True,
    )


def _executor_kinds(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("supported_executor_kinds must be an array of strings.")
    normalized = tuple(sorted({_required("executor_kind", value) for value in values}))
    if not normalized:
        raise _invalid("supported_executor_kinds must not be empty.")
    return normalized


def _backend_profiles(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("supported_backend_profiles must be an array of strings.")
    normalized = tuple(
        sorted({_required("backend_profile", value) for value in values})
    )
    if not normalized:
        raise _invalid("supported_backend_profiles must not be empty.")
    return normalized


def _leadership_params(
    *,
    queue_name: str | None,
    dispatcher_id: str | None,
    fencing_token: int | None,
) -> dict[str, Any]:
    values = (queue_name, dispatcher_id, fencing_token)
    if all(value is None for value in values):
        return {}
    if any(value is None for value in values):
        raise _invalid(
            "queue_name, dispatcher_id, and fencing_token must be provided together."
        )
    return {
        "queue_name": _required("queue_name", queue_name),
        "dispatcher_id": _required("dispatcher_id", dispatcher_id),
        "fencing_token": _positive_int("fencing_token", fencing_token),
    }


def _admission_policy(value: object) -> str:
    policy = _required("admission_policy", value).upper()
    if policy not in RUNTIME_ADMISSION_POLICIES:
        raise _invalid("admission_policy must be REJECT or DELAY.")
    return policy


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer.")
    return value


def _optional_positive_int(field: str, value: object) -> int | None:
    return None if value is None else _positive_int(field, value)


def _invalid(detail: str) -> RuntimeJobError:
    return RuntimeJobError("ae.runtime_job_invalid", detail)


def _not_found() -> RuntimeJobError:
    return RuntimeJobError("ae.runtime_job_not_found", "RuntimeJob was not found.")


def _unavailable() -> RuntimeJobError:
    return RuntimeJobError(
        "ae.runtime_job_store_unavailable",
        "AE RuntimeJob store is unavailable.",
        True,
    )
