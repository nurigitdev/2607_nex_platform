from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.chat_application import (
    ChatApplicationInvocation,
    ChatApplicationService,
)
from nex_ae_api.runtime_jobs import (
    RuntimeJobClaim,
    RuntimeJobError,
    SqlAlchemyRuntimeJobQueue,
)

P4_STEP_KIND = "P4_CHAT_RAG_COMPATIBILITY"
EXECUTABLE_STEP_STATES = frozenset(
    {
        "PENDING",
        "READY",
        "CLAIMED",
        "RUNNING",
        "WAITING",
        "RECONCILIATION_REQUIRED",
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "CANCELLED",
    }
)
TERMINAL_STEP_STATES = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"})
TERMINAL_CHAT_STATUSES = frozenset({"COMPLETED", "FAILED", "NO_ANSWER", "CANCELLED"})
ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class ExecutableStepError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class CompatibilityStepOutcome:
    state: Literal["WAITING", "SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"]
    legacy_interaction_id: str
    retrieval_package_ref: str | None = None
    retrieval_package_hash: str | None = None
    cx_generation_id: str | None = None
    cx_job_id: str | None = None
    generated_response_id: str | None = None
    result_ref: str | None = None
    error_ref: str | None = None


@dataclass(frozen=True)
class CompatibilityExecutionResult:
    result: Any
    step: dict[str, Any] | None
    canonical_error_code: str | None = None


class SqlAlchemyExecutableStepRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_or_get(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        agent_execution_id: str,
        legacy_interaction_id: str,
        correlation_id: str,
        causation_id: str | None,
        now: str,
    ) -> dict[str, Any]:
        params = {
            "tenant_id": _required("tenant_id", tenant_id),
            "executable_step_id": _required(
                "executable_step_id", executable_step_id
            ),
            "agent_execution_id": _required(
                "agent_execution_id", agent_execution_id
            ),
            "step_kind": P4_STEP_KIND,
            "legacy_interaction_id": _required(
                "legacy_interaction_id", legacy_interaction_id
            ),
            "correlation_id": _required("correlation_id", correlation_id),
            "causation_id": _optional("causation_id", causation_id),
            "now": _timestamp("now", now),
        }
        try:
            with self._session_factory() as session:
                _require_execution_scope(session, params)
                inserted = session.execute(text(_STEP_INSERT_SQL), params)
                saved = _load_by_execution(
                    session, params["tenant_id"], params["agent_execution_id"]
                )
                if saved is None:
                    raise ExecutableStepError(
                        "ae.executable_step_write_conflict",
                        "ExecutableStep could not be reloaded after creation.",
                        True,
                    )
                if int(inserted.rowcount or 0) == 0:
                    _require_same_step(saved, params)
                session.commit()
                return saved
        except ExecutableStepError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(
        self, tenant_id: str, executable_step_id: str
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_step(
                    session,
                    _required("tenant_id", tenant_id),
                    _required("executable_step_id", executable_step_id),
                )
        except ExecutableStepError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def begin_invocation(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        expected_version: int,
        now: str,
    ) -> dict[str, Any]:
        return self._transition(
            tenant_id=tenant_id,
            executable_step_id=executable_step_id,
            expected_version=expected_version,
            expected_state="READY",
            target_state="RUNNING",
            now=now,
            outcome=None,
        )

    def record_outcome(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        expected_version: int,
        expected_state: Literal["RUNNING", "WAITING"],
        outcome: CompatibilityStepOutcome,
        now: str,
    ) -> dict[str, Any]:
        allowed = (
            {"WAITING", *TERMINAL_STEP_STATES}
            if expected_state == "RUNNING"
            else set(TERMINAL_STEP_STATES)
        )
        if outcome.state not in allowed:
            raise _invalid("ExecutableStep outcome is invalid for its current state.")
        return self._transition(
            tenant_id=tenant_id,
            executable_step_id=executable_step_id,
            expected_version=expected_version,
            expected_state=expected_state,
            target_state=outcome.state,
            now=now,
            outcome=outcome,
        )

    def record_invocation_failure(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        expected_version: int,
        error_ref: str,
        now: str,
    ) -> dict[str, Any]:
        current = self.get(tenant_id, executable_step_id)
        if current is None:
            raise _not_found()
        outcome = CompatibilityStepOutcome(
            state="FAILED",
            legacy_interaction_id=current["legacy_interaction_id"],
            error_ref=_required("error_ref", error_ref),
        )
        return self.record_outcome(
            tenant_id=tenant_id,
            executable_step_id=executable_step_id,
            expected_version=expected_version,
            expected_state="RUNNING",
            outcome=outcome,
            now=now,
        )

    def _transition(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        expected_version: int,
        expected_state: str,
        target_state: str,
        now: str,
        outcome: CompatibilityStepOutcome | None,
    ) -> dict[str, Any]:
        if target_state not in EXECUTABLE_STEP_STATES:
            raise _invalid("ExecutableStep state is outside the Frozen vocabulary.")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
        ):
            raise _invalid("ExecutableStep expected_version is invalid.")
        params = {
            "tenant_id": _required("tenant_id", tenant_id),
            "executable_step_id": _required(
                "executable_step_id", executable_step_id
            ),
            "expected_version": expected_version,
            "expected_state": expected_state,
            "target_state": target_state,
            "retrieval_package_ref": None,
            "retrieval_package_hash": None,
            "cx_generation_id": None,
            "cx_job_id": None,
            "generated_response_id": None,
            "result_ref": None,
            "error_ref": None,
            "legacy_interaction_id": None,
            "now": _timestamp("now", now),
        }
        if outcome is not None:
            params["legacy_interaction_id"] = _required(
                "legacy_interaction_id", outcome.legacy_interaction_id
            )
            for field_name in (
                "retrieval_package_ref",
                "retrieval_package_hash",
                "cx_generation_id",
                "cx_job_id",
                "generated_response_id",
                "result_ref",
                "error_ref",
            ):
                params[field_name] = _optional(
                    field_name, getattr(outcome, field_name)
                )
        try:
            with self._session_factory() as session:
                dialect_name = session.get_bind().dialect.name
                updated = session.execute(
                    text(_transition_sql(outcome, dialect_name)), params
                )
                if int(updated.rowcount or 0) == 0:
                    existing = _load_step(
                        session, params["tenant_id"], params["executable_step_id"]
                    )
                    if existing is None:
                        raise _not_found()
                    raise ExecutableStepError(
                        "ae.executable_step_state_conflict",
                        "ExecutableStep state or version changed before transition.",
                        True,
                    )
                saved = _load_step(
                    session, params["tenant_id"], params["executable_step_id"]
                )
                if saved is None:
                    raise ExecutableStepError(
                        "ae.executable_step_write_conflict",
                        "ExecutableStep disappeared after transition.",
                        True,
                    )
                session.commit()
                return saved
        except ExecutableStepError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


class CompatibilityChatRuntime:
    def __init__(
        self,
        *,
        steps: SqlAlchemyExecutableStepRepository,
        jobs: SqlAlchemyRuntimeJobQueue,
        application: ChatApplicationService | None = None,
        mode: Literal["disabled", "shadow", "required"] = "disabled",
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if mode not in {"disabled", "shadow", "required"}:
            raise _invalid("Compatibility runtime mode is invalid.")
        self._steps = steps
        self._jobs = jobs
        self._application = application or ChatApplicationService()
        self._mode = mode
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def enqueue_start(
        self,
        *,
        execution: Mapping[str, Any],
        run_after: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._mode == "disabled":
            raise _invalid("Disabled compatibility runtime does not enqueue jobs.")
        now = self._now()
        tenant_id = _required("tenant_id", execution.get("tenant_id"))
        execution_id = _required(
            "agent_execution_id", execution.get("agent_execution_id")
        )
        interaction_id = _required(
            "legacy_interaction_id", execution.get("legacy_interaction_id")
        )
        step = self._steps.create_or_get(
            tenant_id=tenant_id,
            executable_step_id=self._id_factory(),
            agent_execution_id=execution_id,
            legacy_interaction_id=interaction_id,
            correlation_id=_required(
                "correlation_id", execution.get("correlation_id")
            ),
            causation_id=_optional("causation_id", execution.get("causation_id")),
            now=now,
        )
        job = self._jobs.enqueue_unique(
            tenant_id=tenant_id,
            runtime_job_id=self._id_factory(),
            job_type="START_EXECUTION",
            execution_id=execution_id,
            executable_step_id=step["executable_step_id"],
            dedup_key=f"p4:start:{execution_id}",
            run_after=run_after or now,
            correlation_id=step["correlation_id"],
            causation_id=step["causation_id"],
            payload={"legacy_interaction_ref": interaction_id},
            now=now,
        )
        return step, job

    def run_start(
        self,
        *,
        claim: RuntimeJobClaim | None,
        callback: Callable[[], ResultT],
    ) -> CompatibilityExecutionResult:
        invocation = self._application.new_invocation("create")
        if self._mode == "disabled":
            return CompatibilityExecutionResult(
                result=self._application.create(callback, invocation=invocation),
                step=None,
            )
        try:
            job = _require_claim(claim, "START_EXECUTION")
            step = self._steps.get(job["tenant_id"], job["executable_step_id"])
            if step is None or step["agent_execution_id"] != job["execution_id"]:
                raise ExecutableStepError(
                    "ae.executable_step_claim_mismatch",
                    "START_EXECUTION does not reference its canonical ExecutableStep.",
                )
            running = self._steps.begin_invocation(
                tenant_id=job["tenant_id"],
                executable_step_id=step["executable_step_id"],
                expected_version=step["version"],
                now=self._now(),
            )
        except (ExecutableStepError, RuntimeJobError) as exc:
            return self._fallback_or_raise(invocation, callback, exc)

        try:
            result = self._application.create(callback, invocation=invocation)
        except Exception as exc:
            self._record_callback_failure(job, running, exc)
            raise

        try:
            outcome = compatibility_outcome(
                result,
                expected_interaction_id=running["legacy_interaction_id"],
            )
            saved = self._steps.record_outcome(
                tenant_id=job["tenant_id"],
                executable_step_id=running["executable_step_id"],
                expected_version=running["version"],
                expected_state="RUNNING",
                outcome=outcome,
                now=self._now(),
            )
            self._jobs.complete(
                tenant_id=job["tenant_id"],
                runtime_job_id=job["runtime_job_id"],
                worker_id=job["lease_owner"],
                lease_token=job["lease_token"],
                now=self._now(),
            )
            return CompatibilityExecutionResult(result=result, step=saved)
        except (ExecutableStepError, RuntimeJobError) as exc:
            if self._mode == "shadow":
                return CompatibilityExecutionResult(
                    result=result,
                    step=None,
                    canonical_error_code=exc.error_code,
                )
            raise

    def enqueue_continuation(
        self,
        *,
        tenant_id: str,
        executable_step_id: str,
        terminal_result: Any,
        runtime_job_id: str | None = None,
    ) -> dict[str, Any]:
        if self._mode == "disabled":
            raise _invalid("Disabled compatibility runtime does not enqueue jobs.")
        step = self._steps.get(tenant_id, executable_step_id)
        if step is None:
            raise _not_found()
        outcome = compatibility_outcome(
            terminal_result,
            expected_interaction_id=step["legacy_interaction_id"],
        )
        if outcome.state == "WAITING":
            raise _invalid("CONTINUE_EXECUTION requires an authoritative terminal result.")
        _require_continuation_lineage(step, outcome)
        terminal_key = ":".join(
            value or "none"
            for value in (
                outcome.cx_job_id,
                outcome.cx_generation_id,
                outcome.generated_response_id,
                outcome.state,
            )
        )
        now = self._now()
        return self._jobs.enqueue_unique(
            tenant_id=step["tenant_id"],
            runtime_job_id=runtime_job_id or self._id_factory(),
            job_type="CONTINUE_EXECUTION",
            execution_id=step["agent_execution_id"],
            executable_step_id=step["executable_step_id"],
            dedup_key=f"p4:continue:{step['executable_step_id']}:{terminal_key}",
            run_after=now,
            correlation_id=step["correlation_id"],
            causation_id=step["executable_step_id"],
            payload={
                "legacy_interaction_ref": step["legacy_interaction_id"],
                "cx_job_ref": outcome.cx_job_id,
                "cx_generation_ref": outcome.cx_generation_id,
            },
            now=now,
        )

    def run_continue(
        self,
        *,
        claim: RuntimeJobClaim,
        terminal_result: Any,
    ) -> dict[str, Any]:
        job = _require_claim(claim, "CONTINUE_EXECUTION")
        step = self._steps.get(job["tenant_id"], job["executable_step_id"])
        if (
            step is None
            or step["agent_execution_id"] != job["execution_id"]
            or step["state"] != "WAITING"
        ):
            raise ExecutableStepError(
                "ae.executable_step_continuation_mismatch",
                "CONTINUE_EXECUTION requires its waiting canonical ExecutableStep.",
            )
        outcome = compatibility_outcome(
            terminal_result,
            expected_interaction_id=step["legacy_interaction_id"],
        )
        if outcome.state == "WAITING":
            raise _invalid("CONTINUE_EXECUTION result is not terminal.")
        _require_continuation_lineage(step, outcome)
        saved = self._steps.record_outcome(
            tenant_id=job["tenant_id"],
            executable_step_id=step["executable_step_id"],
            expected_version=step["version"],
            expected_state="WAITING",
            outcome=outcome,
            now=self._now(),
        )
        self._jobs.complete(
            tenant_id=job["tenant_id"],
            runtime_job_id=job["runtime_job_id"],
            worker_id=job["lease_owner"],
            lease_token=job["lease_token"],
            now=self._now(),
        )
        return saved

    def _fallback_or_raise(
        self,
        invocation: ChatApplicationInvocation,
        callback: Callable[[], ResultT],
        error: ExecutableStepError | RuntimeJobError,
    ) -> CompatibilityExecutionResult:
        if self._mode != "shadow" or invocation.state != "READY":
            raise error
        result = self._application.create(callback, invocation=invocation)
        return CompatibilityExecutionResult(
            result=result,
            step=None,
            canonical_error_code=error.error_code,
        )

    def _record_callback_failure(
        self,
        job: Mapping[str, Any],
        step: Mapping[str, Any],
        error: Exception,
    ) -> None:
        error_ref = f"python:{type(error).__name__}"
        try:
            self._steps.record_invocation_failure(
                tenant_id=job["tenant_id"],
                executable_step_id=step["executable_step_id"],
                expected_version=step["version"],
                error_ref=error_ref,
                now=self._now(),
            )
            self._jobs.fail(
                tenant_id=job["tenant_id"],
                runtime_job_id=job["runtime_job_id"],
                worker_id=job["lease_owner"],
                lease_token=job["lease_token"],
                now=self._now(),
                error_ref=error_ref,
            )
        except (ExecutableStepError, RuntimeJobError):
            return

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")


def compatibility_outcome(
    result: Any,
    *,
    expected_interaction_id: str,
) -> CompatibilityStepOutcome:
    record = _result_mapping(result)
    interaction_id = _required("interaction_id", record.get("interaction_id"))
    if interaction_id != _required("expected_interaction_id", expected_interaction_id):
        raise _invalid("Chat result interaction does not match ExecutableStep.")
    status = _required("status", record.get("status")).upper()
    state = {
        "PENDING": "WAITING",
        "COMPLETED": "SUCCEEDED",
        "FAILED": "FAILED",
        "NO_ANSWER": "BLOCKED",
        "CANCELLED": "CANCELLED",
    }.get(status)
    if state is None:
        raise _invalid("Chat result status is unsupported by the compatibility step.")
    retrieval = record.get("retrieval")
    retrieval = retrieval if isinstance(retrieval, Mapping) else {}
    generation = record.get("generation")
    generation = generation if isinstance(generation, Mapping) else {}
    async_generation = generation.get("async_generation")
    async_generation = (
        async_generation if isinstance(async_generation, Mapping) else {}
    )
    generated_response = generation.get("generated_response_ref")
    generated_response = (
        generated_response if isinstance(generated_response, Mapping) else {}
    )
    failure = record.get("failure")
    failure = failure if isinstance(failure, Mapping) else {}
    return CompatibilityStepOutcome(
        state=state,  # type: ignore[arg-type]
        legacy_interaction_id=interaction_id,
        retrieval_package_ref=_optional(
            "retrieval_package_ref", retrieval.get("cx_retrieval_package_id")
        ),
        retrieval_package_hash=_optional(
            "retrieval_package_hash", retrieval.get("cx_package_hash")
        ),
        cx_generation_id=_optional(
            "cx_generation_id", record.get("cx_generation_id")
        ),
        cx_job_id=_optional("cx_job_id", async_generation.get("job_id")),
        generated_response_id=_optional(
            "generated_response_id",
            generated_response.get("generated_response_id")
            or generation.get("generated_response_id"),
        ),
        result_ref=f"ae-chat://interaction/{interaction_id}",
        error_ref=_optional("error_ref", failure.get("error_code")),
    )


def _result_mapping(result: Any) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        return result
    body = getattr(result, "body", None)
    if isinstance(body, bytes):
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _invalid("Chat response body is not valid JSON.") from exc
        if isinstance(decoded, Mapping):
            return decoded
    raise _invalid("Chat application result is not a structured record.")


_STEP_INSERT_SQL = """
    INSERT INTO ae_executable_step (
        tenant_id, executable_step_id, agent_execution_id, step_kind, state,
        version, legacy_interaction_id, correlation_id, causation_id,
        created_at, updated_at
    ) VALUES (
        :tenant_id, :executable_step_id, :agent_execution_id, :step_kind,
        'READY', 1, :legacy_interaction_id, :correlation_id, :causation_id,
        :now, :now
    ) ON CONFLICT (tenant_id, agent_execution_id, step_kind) DO NOTHING
"""

_STEP_SELECT_SQL = """
    SELECT tenant_id, executable_step_id, agent_execution_id, step_kind, state,
           version, legacy_interaction_id, retrieval_package_ref,
           retrieval_package_hash, cx_generation_id, cx_job_id,
           generated_response_id, result_ref, error_ref, correlation_id,
           causation_id, invocation_started_at, completed_at, created_at,
           updated_at
    FROM ae_executable_step
"""


def _transition_sql(
    outcome: CompatibilityStepOutcome | None,
    dialect_name: str,
) -> str:
    if outcome is None:
        assignments = "invocation_started_at = :now"
    else:
        completed_at = (
            "CAST(:now AS TIMESTAMPTZ)" if dialect_name == "postgresql" else ":now"
        )
        assignments = f"""
            retrieval_package_ref = COALESCE(:retrieval_package_ref, retrieval_package_ref),
            retrieval_package_hash = COALESCE(:retrieval_package_hash, retrieval_package_hash),
            cx_generation_id = COALESCE(:cx_generation_id, cx_generation_id),
            cx_job_id = COALESCE(:cx_job_id, cx_job_id),
            generated_response_id = COALESCE(:generated_response_id, generated_response_id),
            result_ref = COALESCE(:result_ref, result_ref),
            error_ref = COALESCE(:error_ref, error_ref),
            completed_at = CASE WHEN :target_state = 'WAITING'
                                THEN NULL ELSE {completed_at} END
        """
    lineage_guard = (
        " AND legacy_interaction_id = :legacy_interaction_id"
        if outcome is not None
        else ""
    )
    return f"""
        UPDATE ae_executable_step
        SET state = :target_state, version = version + 1,
            {assignments}, updated_at = :now
        WHERE tenant_id = :tenant_id AND executable_step_id = :executable_step_id
          AND state = :expected_state AND version = :expected_version
          {lineage_guard}
    """


def _require_execution_scope(session: Session, params: Mapping[str, Any]) -> None:
    execution = session.execute(
        text(
            """
            SELECT legacy_interaction_id, correlation_id
            FROM ae_agent_execution
            WHERE tenant_id = :tenant_id
              AND agent_execution_id = :agent_execution_id
            """
        ),
        params,
    ).mappings().first()
    if execution is None:
        raise ExecutableStepError(
            "ae.executable_step_execution_not_found",
            "ExecutableStep requires an existing AgentExecution in the same tenant.",
        )
    if (
        str(execution["legacy_interaction_id"])
        != str(params["legacy_interaction_id"])
        or execution["correlation_id"] != params["correlation_id"]
    ):
        raise ExecutableStepError(
            "ae.executable_step_execution_mismatch",
            "ExecutableStep lineage does not match its AgentExecution.",
        )


def _load_by_execution(
    session: Session, tenant_id: str, agent_execution_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            _STEP_SELECT_SQL
            + " WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id"
            + " AND step_kind = :step_kind"
        ),
        {
            "tenant_id": tenant_id,
            "execution_id": agent_execution_id,
            "step_kind": P4_STEP_KIND,
        },
    ).mappings().first()
    return None if row is None else _step_from_row(row)


def _load_step(
    session: Session, tenant_id: str, executable_step_id: str
) -> dict[str, Any] | None:
    row = session.execute(
        text(
            _STEP_SELECT_SQL
            + " WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
        ),
        {"tenant_id": tenant_id, "step_id": executable_step_id},
    ).mappings().first()
    return None if row is None else _step_from_row(row)


def _step_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "executable_step_id": str(row["executable_step_id"]),
        "agent_execution_id": str(row["agent_execution_id"]),
        "step_kind": row["step_kind"],
        "state": row["state"],
        "version": int(row["version"]),
        "legacy_interaction_id": str(row["legacy_interaction_id"]),
        "retrieval_package_ref": row["retrieval_package_ref"],
        "retrieval_package_hash": row["retrieval_package_hash"],
        "cx_generation_id": row["cx_generation_id"],
        "cx_job_id": row["cx_job_id"],
        "generated_response_id": row["generated_response_id"],
        "result_ref": row["result_ref"],
        "error_ref": row["error_ref"],
        "correlation_id": row["correlation_id"],
        "causation_id": row["causation_id"],
        "invocation_started_at": _datetime_or_none(row["invocation_started_at"]),
        "completed_at": _datetime_or_none(row["completed_at"]),
        "created_at": _datetime_value(row["created_at"]),
        "updated_at": _datetime_value(row["updated_at"]),
    }


def _require_same_step(
    existing: Mapping[str, Any], params: Mapping[str, Any]
) -> None:
    keys = (
        "agent_execution_id",
        "step_kind",
        "legacy_interaction_id",
        "correlation_id",
        "causation_id",
    )
    if any(_comparable(existing[key]) != _comparable(params[key]) for key in keys):
        raise ExecutableStepError(
            "ae.executable_step_identity_conflict",
            "AgentExecution compatibility step was reused with different semantics.",
        )


def _require_claim(
    claim: RuntimeJobClaim | None, expected_job_type: str
) -> Mapping[str, Any]:
    if claim is None:
        raise _invalid("Compatibility execution requires a claimed RuntimeJob.")
    job = claim.job
    if (
        job.get("job_type") != expected_job_type
        or job.get("state") != "RUNNING"
        or not job.get("lease_owner")
        or not job.get("lease_token")
        or not job.get("executable_step_id")
    ):
        raise _invalid("RuntimeJob claim is invalid for compatibility execution.")
    return job


def _require_continuation_lineage(
    step: Mapping[str, Any], outcome: CompatibilityStepOutcome
) -> None:
    for field_name in ("cx_job_id", "cx_generation_id"):
        expected = step.get(field_name)
        actual = getattr(outcome, field_name)
        if expected is not None and str(actual) != str(expected):
            raise ExecutableStepError(
                "ae.executable_step_continuation_lineage_mismatch",
                "Async terminal result does not match the waiting CX lineage.",
            )


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be an RFC 3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC 3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string.")
    return value.strip()


def _optional(field: str, value: object) -> str | None:
    return None if value is None else _required(field, value)


def _datetime_value(value: Any) -> str:
    return value.isoformat().replace("+00:00", "Z") if hasattr(value, "isoformat") else str(value)


def _datetime_or_none(value: Any) -> str | None:
    return None if value is None else _datetime_value(value)


def _comparable(value: Any) -> Any:
    return None if value is None else str(value)


def _invalid(detail: str) -> ExecutableStepError:
    return ExecutableStepError("ae.executable_step_invalid", detail)


def _not_found() -> ExecutableStepError:
    return ExecutableStepError(
        "ae.executable_step_not_found", "ExecutableStep was not found."
    )


def _unavailable() -> ExecutableStepError:
    return ExecutableStepError(
        "ae.executable_step_store_unavailable",
        "AE ExecutableStep store is unavailable.",
        True,
    )
