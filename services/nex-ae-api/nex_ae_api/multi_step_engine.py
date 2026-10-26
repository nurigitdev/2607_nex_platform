from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.runtime_jobs import RuntimeJobClaim, SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_results import (
    StepResultError,
    build_step_result,
    load_step_result_by_step,
    load_step_results_for_plan,
    persist_step_result_in_session,
    step_result_semantic_projection,
)

TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"})
ACTIVE_STATES = frozenset({"READY", "RUNNING", "WAITING"})


@dataclass
class MultiStepEngineError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class StepExecutionContext:
    job: dict[str, Any]
    attempt: dict[str, Any]
    step: dict[str, Any]
    dependency_results: tuple[dict[str, Any], ...]
    existing_result: dict[str, Any] | None

    @property
    def already_terminal(self) -> bool:
        return self.existing_result is not None


@dataclass(frozen=True)
class StepTerminalOutcome:
    status: Literal["SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"]
    result_contract_ref: str
    result_payload: Mapping[str, Any]
    started_at: str
    completed_at: str
    external_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    error_ref: str | None = None
    executor_kind: str | None = None
    business_operation_id: str | None = None


@dataclass(frozen=True)
class StepWaitingOutcome:
    retrieval_package_ref: str | None = None
    retrieval_package_hash: str | None = None
    cx_generation_id: str | None = None
    cx_job_id: str | None = None
    wait_id: str | None = None
    external_ref: str | None = None
    result_contract_ref: str | None = None


class SqlAlchemyMultiStepEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        runtime_jobs: SqlAlchemyRuntimeJobQueue,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._runtime_jobs = runtime_jobs
        self._id_factory = id_factory or (lambda: str(uuid4()))

    def schedule_next(
        self, *, tenant_id: str, execution_id: str, now: str
    ) -> dict[str, Any] | None:
        tenant = _required_text("tenant_id", tenant_id, 128)
        execution = _required_uuid("execution_id", execution_id)
        try:
            with self._session_factory() as session:
                runtime = _load_runtime(session, tenant, execution, lock=True)
                if runtime is None:
                    raise MultiStepEngineError(
                        "ae.multi_step_execution_not_found",
                        "Multi-step scheduling requires an AgentExecution.",
                    )
                plan = _load_plan(session, tenant, execution)
                if plan is None:
                    raise MultiStepEngineError(
                        "ae.multi_step_plan_not_found",
                        "Multi-step scheduling requires an ExecutablePlan.",
                    )
                steps = _load_steps(session, tenant, plan["executable_plan_id"])
                _require_plan_steps(steps)
                results = load_step_results_for_plan(
                    session, tenant, plan["executable_plan_id"]
                )
                if _all_terminal(steps):
                    _move_to_result_verify(session, runtime, now)
                    session.commit()
                    return None
                _require_runtime_authority(runtime)
                active = [step for step in steps if step["state"] in ACTIVE_STATES]
                if len(active) > 1:
                    raise MultiStepEngineError(
                        "ae.multi_step_parallelism_violation",
                        "P5 permits only one active ExecutableStep.",
                    )
                if active and active[0]["state"] in {"RUNNING", "WAITING"}:
                    session.commit()
                    return None
                if not active:
                    promoted = _promote_next_ready(session, steps, results, now)
                    if promoted is None:
                        raise MultiStepEngineError(
                            "ae.multi_step_dependency_deadlock",
                            "No deterministic ready step can be scheduled.",
                        )
                    active = [promoted]
                step = active[0]
                session.commit()
            completed_count = len(results)
            return self._runtime_jobs.enqueue_unique(
                tenant_id=tenant,
                runtime_job_id=_required_uuid("runtime_job_id", self._id_factory()),
                job_type=(
                    "START_EXECUTION" if completed_count == 0 else "CONTINUE_EXECUTION"
                ),
                execution_id=execution,
                executable_step_id=step["executable_step_id"],
                dedup_key=(
                    f"p5:step:{plan['executable_plan_id']}:{step['compiled_step_key']}"
                ),
                run_after=now,
                payload={
                    "executable_plan_id": plan["executable_plan_id"],
                    "compiled_step_key": step["compiled_step_key"],
                    "step_contract_hash": step["step_contract_hash"],
                },
                correlation_id=runtime["correlation_id"],
                causation_id=runtime["causation_id"],
                now=now,
            )
        except MultiStepEngineError:
            raise
        except StepResultError as exc:
            raise _from_step_result_error(exc) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def begin_claim(
        self, *, tenant_id: str, claim: RuntimeJobClaim, now: str
    ) -> StepExecutionContext:
        tenant = _required_text("tenant_id", tenant_id, 128)
        job, attempt = _validate_claim(claim, tenant)
        step_id = _required_uuid("executable_step_id", job["executable_step_id"])
        try:
            with self._session_factory() as session:
                _require_claim_authority(session, tenant, job, attempt, now)
                step = _load_step(session, tenant, step_id, lock=True)
                if step is None:
                    raise MultiStepEngineError(
                        "ae.multi_step_step_not_found",
                        "Claimed RuntimeJob has no ExecutableStep.",
                    )
                if step["agent_execution_id"] != job["execution_id"]:
                    raise MultiStepEngineError(
                        "ae.multi_step_claim_mismatch",
                        "RuntimeJob and ExecutableStep execution lineage differ.",
                    )
                existing = load_step_result_by_step(session, tenant, step_id)
                if existing is not None:
                    session.commit()
                    return StepExecutionContext(
                        job=job,
                        attempt=attempt,
                        step=step,
                        dependency_results=(),
                        existing_result=existing,
                    )
                if step["state"] not in {"READY", "RUNNING", "WAITING"}:
                    raise MultiStepEngineError(
                        "ae.multi_step_step_not_runnable",
                        "Claimed ExecutableStep is not runnable.",
                    )
                dependencies = _dependency_results(session, tenant, step)
                if any(item["status"] != "SUCCEEDED" for item in dependencies):
                    raise MultiStepEngineError(
                        "ae.multi_step_dependency_not_satisfied",
                        "ExecutableStep dependencies are not successful.",
                    )
                if step["state"] == "WAITING" and not (
                    (
                        job["job_type"] == "CONTINUE_EXECUTION"
                        and step["executor_kind"] == "P4_CHAT_RAG_COMPATIBILITY"
                    )
                    or (
                        job["job_type"] == "RESUME_EXECUTION"
                        and step["executor_kind"] in {"WC_DELEGATE_WORK", "LOCAL_SKILL"}
                    )
                ):
                    raise MultiStepEngineError(
                        "ae.multi_step_continuation_required",
                        "A waiting ExecutableStep requires its exact continuation job type.",
                    )
                if step["state"] == "READY":
                    updated = session.execute(
                        text(
                            "UPDATE ae_executable_step SET state = 'RUNNING', "
                            "version = version + 1, invocation_started_at = :now, "
                            "updated_at = :now WHERE tenant_id = :tenant_id "
                            "AND executable_step_id = :step_id AND state = 'READY' "
                            "AND version = :version"
                        ),
                        {
                            "tenant_id": tenant,
                            "step_id": step_id,
                            "version": step["version"],
                            "now": now,
                        },
                    )
                    if int(updated.rowcount or 0) != 1:
                        raise MultiStepEngineError(
                            "ae.multi_step_claim_conflict",
                            "ExecutableStep changed while beginning its claim.",
                            True,
                        )
                    step = _load_step(session, tenant, step_id, lock=False)
                runtime = _load_runtime(session, tenant, job["execution_id"], lock=True)
                if runtime is None:
                    raise MultiStepEngineError(
                        "ae.multi_step_execution_not_found",
                        "Claimed step lost its AgentExecution.",
                    )
                if job["job_type"] == "RESUME_EXECUTION":
                    _enter_external_resume(session, runtime, step or {}, job, now)
                else:
                    _enter_step_execution(session, runtime, now)
                session.commit()
                return StepExecutionContext(
                    job=job,
                    attempt=attempt,
                    step=step or {},
                    dependency_results=tuple(dependencies),
                    existing_result=None,
                )
        except MultiStepEngineError:
            raise
        except StepResultError as exc:
            raise _from_step_result_error(exc) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def record_outcome(
        self,
        *,
        tenant_id: str,
        claim: RuntimeJobClaim,
        outcome: StepTerminalOutcome,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        tenant = _required_text("tenant_id", tenant_id, 128)
        job, attempt = _validate_claim(claim, tenant)
        step_id = _required_uuid("executable_step_id", job["executable_step_id"])
        result = None
        try:
            with self._session_factory() as session:
                _require_claim_authority(
                    session,
                    tenant,
                    job,
                    attempt,
                    outcome.completed_at if observed_at is None else observed_at,
                )
                step = _load_step(session, tenant, step_id, lock=True)
                if step is None:
                    raise MultiStepEngineError(
                        "ae.multi_step_step_not_found",
                        "Terminal outcome has no ExecutableStep.",
                    )
                if step["agent_execution_id"] != job["execution_id"]:
                    raise MultiStepEngineError(
                        "ae.multi_step_claim_mismatch",
                        "Terminal outcome execution lineage differs.",
                    )
                proposed = build_step_result(
                    step_result_id=_required_uuid("step_result_id", self._id_factory()),
                    execution_id=step["agent_execution_id"],
                    executable_plan_id=step["executable_plan_id"],
                    executable_step_id=step["executable_step_id"],
                    compiled_step_key=step["compiled_step_key"],
                    logical_step_ref=step["logical_step_id"],
                    attempt_no=int(attempt["attempt_no"]),
                    status=outcome.status,
                    result_contract_ref=outcome.result_contract_ref,
                    result_payload=outcome.result_payload,
                    external_refs=outcome.external_refs,
                    artifact_refs=outcome.artifact_refs,
                    evidence_refs=outcome.evidence_refs,
                    error_ref=outcome.error_ref,
                    executor_kind=outcome.executor_kind,
                    business_operation_id=outcome.business_operation_id,
                    started_at=outcome.started_at,
                    completed_at=outcome.completed_at,
                )
                existing = load_step_result_by_step(session, tenant, step_id)
                if existing is not None:
                    if semantic_sha256_hash_ref(
                        step_result_semantic_projection(existing)
                    ) != semantic_sha256_hash_ref(
                        step_result_semantic_projection(proposed)
                    ):
                        raise MultiStepEngineError(
                            "ae.multi_step_terminal_conflict",
                            "ExecutableStep already has a different terminal outcome.",
                        )
                    session.commit()
                    return existing
                if step["state"] not in {"RUNNING", "WAITING"}:
                    raise MultiStepEngineError(
                        "ae.multi_step_step_not_running",
                        "Only a running ExecutableStep can terminalize.",
                    )
                updated = session.execute(
                    text(
                        "UPDATE ae_executable_step SET state = :state, "
                        "version = version + 1, result_ref = :result_ref, "
                        "error_ref = :error_ref, completed_at = :completed_at, "
                        "updated_at = :completed_at WHERE tenant_id = :tenant_id "
                        "AND executable_step_id = :step_id AND state = :expected_state "
                        "AND version = :version"
                    ),
                    {
                        "tenant_id": tenant,
                        "step_id": step_id,
                        "version": step["version"],
                        "state": outcome.status,
                        "expected_state": step["state"],
                        "result_ref": f"AE:STEP_RESULT:{proposed['step_result_id']}",
                        "error_ref": outcome.error_ref,
                        "completed_at": proposed["completed_at"],
                    },
                )
                if int(updated.rowcount or 0) != 1:
                    raise MultiStepEngineError(
                        "ae.multi_step_terminal_conflict",
                        "ExecutableStep changed while recording its outcome.",
                        True,
                    )
                result = persist_step_result_in_session(session, tenant, proposed)
                if job["job_type"] == "RESUME_EXECUTION":
                    _consume_external_wait(
                        session,
                        tenant_id=tenant,
                        job=job,
                        step=step,
                        completed_at=proposed["completed_at"],
                    )
                _advance_plan_after_result(
                    session,
                    tenant_id=tenant,
                    execution_id=step["agent_execution_id"],
                    executable_plan_id=step["executable_plan_id"],
                    completed_at=proposed["completed_at"],
                    id_factory=self._id_factory,
                )
                session.commit()
                return result
        except MultiStepEngineError:
            raise
        except StepResultError as exc:
            raise _from_step_result_error(exc) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def record_waiting(
        self,
        *,
        tenant_id: str,
        claim: RuntimeJobClaim,
        outcome: StepWaitingOutcome,
        now: str,
    ) -> dict[str, Any]:
        tenant = _required_text("tenant_id", tenant_id, 128)
        job, attempt = _validate_claim(claim, tenant)
        step_id = _required_uuid("executable_step_id", job["executable_step_id"])
        try:
            with self._session_factory() as session:
                _require_claim_authority(session, tenant, job, attempt, now)
                step = _load_step(session, tenant, step_id, lock=True)
                if step is None:
                    raise MultiStepEngineError(
                        "ae.multi_step_step_not_found",
                        "Waiting outcome has no ExecutableStep.",
                    )
                if (
                    step["agent_execution_id"] != job["execution_id"]
                    or step["state"] != "RUNNING"
                    or step["executor_kind"]
                    not in {
                        "P4_CHAT_RAG_COMPATIBILITY",
                        "WC_DELEGATE_WORK",
                        "LOCAL_SKILL",
                    }
                ):
                    raise MultiStepEngineError(
                        "ae.multi_step_waiting_mismatch",
                        "Only an eligible running step can enter WAITING.",
                    )
                if step["executor_kind"] == "P4_CHAT_RAG_COMPATIBILITY":
                    params = {
                        "tenant_id": tenant,
                        "step_id": step_id,
                        "version": step["version"],
                        "retrieval_package_ref": _optional_text(
                            "retrieval_package_ref",
                            outcome.retrieval_package_ref,
                            256,
                        ),
                        "retrieval_package_hash": _optional_text(
                            "retrieval_package_hash",
                            outcome.retrieval_package_hash,
                            256,
                        ),
                        "cx_generation_id": _optional_text(
                            "cx_generation_id", outcome.cx_generation_id, 256
                        ),
                        "cx_job_id": _required_text(
                            "cx_job_id", outcome.cx_job_id, 256
                        ),
                        "now": now,
                    }
                    updated = session.execute(
                        text(
                            "UPDATE ae_executable_step SET state = 'WAITING', "
                            "version = version + 1, "
                            "retrieval_package_ref = :retrieval_package_ref, "
                            "retrieval_package_hash = :retrieval_package_hash, "
                            "cx_generation_id = :cx_generation_id, "
                            "cx_job_id = :cx_job_id, updated_at = :now "
                            "WHERE tenant_id = :tenant_id "
                            "AND executable_step_id = :step_id "
                            "AND state = 'RUNNING' AND version = :version"
                        ),
                        params,
                    )
                elif step["executor_kind"] == "WC_DELEGATE_WORK":
                    params = {
                        "tenant_id": tenant,
                        "execution_id": step["agent_execution_id"],
                        "step_id": step_id,
                        "version": step["version"],
                        "wait_id": _required_uuid("wait_id", outcome.wait_id),
                        "external_ref": _required_uuid(
                            "external_ref", outcome.external_ref
                        ),
                        "result_contract_ref": _required_text(
                            "result_contract_ref",
                            outcome.result_contract_ref,
                            256,
                        ),
                        "now": now,
                    }
                    _require_delegate_wait(session, params)
                    runtime = _load_runtime(
                        session, tenant, step["agent_execution_id"], lock=True
                    )
                    if runtime is None:
                        raise MultiStepEngineError(
                            "ae.multi_step_execution_not_found",
                            "Delegated step lost its AgentExecution.",
                        )
                    updated = session.execute(
                        text(
                            "UPDATE ae_executable_step SET state = 'WAITING', "
                            "version = version + 1, updated_at = :now "
                            "WHERE tenant_id = :tenant_id "
                            "AND executable_step_id = :step_id "
                            "AND state = 'RUNNING' AND version = :version"
                        ),
                        params,
                    )
                    _move_to_dependency_wait(session, runtime, now)
                else:
                    params = {
                        "tenant_id": tenant,
                        "execution_id": step["agent_execution_id"],
                        "step_id": step_id,
                        "version": step["version"],
                        "wait_id": _required_uuid("wait_id", outcome.wait_id),
                        "external_ref": _required_text(
                            "external_ref", outcome.external_ref, 256
                        ),
                        "result_contract_ref": _required_text(
                            "result_contract_ref",
                            outcome.result_contract_ref,
                            256,
                        ),
                        "now": now,
                    }
                    _require_nsl_approval_wait(session, params)
                    runtime = _load_runtime(
                        session, tenant, step["agent_execution_id"], lock=True
                    )
                    if runtime is None:
                        raise MultiStepEngineError(
                            "ae.multi_step_execution_not_found",
                            "NSL approval step lost its AgentExecution.",
                        )
                    updated = session.execute(
                        text(
                            "UPDATE ae_executable_step SET state = 'WAITING', "
                            "version = version + 1, updated_at = :now "
                            "WHERE tenant_id = :tenant_id "
                            "AND executable_step_id = :step_id "
                            "AND state = 'RUNNING' AND version = :version"
                        ),
                        params,
                    )
                    _move_to_approval_wait(session, runtime, now)
                if int(updated.rowcount or 0) != 1:
                    raise MultiStepEngineError(
                        "ae.multi_step_waiting_conflict",
                        "ExecutableStep changed before entering WAITING.",
                        True,
                    )
                saved = _load_step(session, tenant, step_id, lock=False)
                if saved is None:
                    raise MultiStepEngineError(
                        "ae.multi_step_step_not_found",
                        "Waiting ExecutableStep disappeared after transition.",
                        True,
                    )
                session.commit()
                return saved
        except MultiStepEngineError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def enqueue_waiting_continuation(
        self,
        *,
        tenant_id: str,
        execution_id: str,
        executable_step_id: str,
        continuation_refs: Mapping[str, str | None],
        now: str,
    ) -> dict[str, Any]:
        tenant = _required_text("tenant_id", tenant_id, 128)
        execution = _required_uuid("execution_id", execution_id)
        step_id = _required_uuid("executable_step_id", executable_step_id)
        refs = _continuation_refs(continuation_refs)
        try:
            with self._session_factory() as session:
                step = _load_step(session, tenant, step_id, lock=False)
                runtime = _load_runtime(session, tenant, execution, lock=False)
                if (
                    step is None
                    or runtime is None
                    or step["agent_execution_id"] != execution
                    or step["state"] != "WAITING"
                    or step["executor_kind"] != "P4_CHAT_RAG_COMPATIBILITY"
                ):
                    raise MultiStepEngineError(
                        "ae.multi_step_continuation_mismatch",
                        "Continuation requires its waiting compatibility step.",
                    )
                if step["cx_job_id"] != refs.get("cx_job_ref"):
                    raise MultiStepEngineError(
                        "ae.multi_step_continuation_lineage_mismatch",
                        "Continuation CX job lineage differs from the waiting step.",
                    )
                session.commit()
            continuation_hash = semantic_sha256_hash_ref(refs).removeprefix("sha256:")
            return self._runtime_jobs.enqueue_unique(
                tenant_id=tenant,
                runtime_job_id=_required_uuid("runtime_job_id", self._id_factory()),
                job_type="CONTINUE_EXECUTION",
                execution_id=execution,
                executable_step_id=step_id,
                dedup_key=f"p5:resume:{step_id}:{continuation_hash}",
                run_after=now,
                payload={"continuation_refs": refs},
                correlation_id=runtime["correlation_id"],
                causation_id=step_id,
                now=now,
            )
        except MultiStepEngineError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def _advance_plan_after_result(
    session: Session,
    *,
    tenant_id: str,
    execution_id: str,
    executable_plan_id: str,
    completed_at: str,
    id_factory: Callable[[], str],
) -> None:
    while True:
        steps = _load_steps(session, tenant_id, executable_plan_id)
        results = load_step_results_for_plan(session, tenant_id, executable_plan_id)
        by_key = {item["compiled_step_key"]: item for item in results}
        changed = False
        for step in steps:
            if step["state"] != "PENDING":
                continue
            blockers = [
                key
                for key in step["dependencies"]
                if key in by_key and by_key[key]["status"] != "SUCCEEDED"
            ]
            if not blockers:
                continue
            _materialize_dependency_block(
                session,
                tenant_id=tenant_id,
                step=step,
                blockers=blockers,
                completed_at=completed_at,
                id_factory=id_factory,
            )
            changed = True
        if not changed:
            break
    steps = _load_steps(session, tenant_id, executable_plan_id)
    results = load_step_results_for_plan(session, tenant_id, executable_plan_id)
    if _all_terminal(steps):
        runtime = _load_runtime(session, tenant_id, execution_id, lock=True)
        if runtime is None:
            raise MultiStepEngineError(
                "ae.multi_step_execution_not_found",
                "Terminal plan lost its AgentExecution.",
            )
        _move_to_result_verify(session, runtime, completed_at)
        return
    if any(step["state"] in ACTIVE_STATES for step in steps):
        return
    if _promote_next_ready(session, steps, results, completed_at) is None:
        raise MultiStepEngineError(
            "ae.multi_step_dependency_deadlock",
            "Plan cannot advance from persisted dependency state.",
        )


def _materialize_dependency_block(
    session: Session,
    *,
    tenant_id: str,
    step: Mapping[str, Any],
    blockers: Sequence[str],
    completed_at: str,
    id_factory: Callable[[], str],
) -> None:
    updated = session.execute(
        text(
            "UPDATE ae_executable_step SET state = 'BLOCKED', version = version + 1, "
            "error_ref = :error_ref, completed_at = :now, updated_at = :now "
            "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id "
            "AND state = 'PENDING' AND version = :version"
        ),
        {
            "tenant_id": tenant_id,
            "step_id": step["executable_step_id"],
            "version": step["version"],
            "error_ref": "dependency://terminal-non-success",
            "now": completed_at,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise MultiStepEngineError(
            "ae.multi_step_dependency_conflict",
            "Dependent step changed while propagating terminal state.",
            True,
        )
    result = build_step_result(
        step_result_id=_required_uuid("step_result_id", id_factory()),
        execution_id=step["agent_execution_id"],
        executable_plan_id=step["executable_plan_id"],
        executable_step_id=step["executable_step_id"],
        compiled_step_key=step["compiled_step_key"],
        logical_step_ref=step["logical_step_id"],
        attempt_no=1,
        status="BLOCKED",
        result_contract_ref=step["output_contract_ref"],
        result_payload={
            "reason": "DEPENDENCY_TERMINAL_NON_SUCCESS",
            "blocked_by_compiled_step_keys": sorted(blockers),
        },
        error_ref="dependency://terminal-non-success",
        started_at=completed_at,
        completed_at=completed_at,
        evidence_refs=tuple(f"AE:COMPILED_STEP:{key}" for key in sorted(blockers)),
    )
    persist_step_result_in_session(session, tenant_id, result)


def _promote_next_ready(
    session: Session,
    steps: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    now: str,
) -> dict[str, Any] | None:
    succeeded = {
        item["compiled_step_key"] for item in results if item["status"] == "SUCCEEDED"
    }
    for step in steps:
        if step["state"] != "PENDING" or not set(step["dependencies"]).issubset(
            succeeded
        ):
            continue
        updated = session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'READY', version = version + 1, "
                "updated_at = :now WHERE tenant_id = :tenant_id "
                "AND executable_step_id = :step_id AND state = 'PENDING' "
                "AND version = :version"
            ),
            {
                "tenant_id": step["tenant_id"],
                "step_id": step["executable_step_id"],
                "version": step["version"],
                "now": now,
            },
        )
        if int(updated.rowcount or 0) != 1:
            raise MultiStepEngineError(
                "ae.multi_step_ready_conflict",
                "ExecutableStep changed while becoming ready.",
                True,
            )
        promoted = dict(step)
        promoted["state"] = "READY"
        promoted["version"] = int(step["version"]) + 1
        return promoted
    return None


def _dependency_results(
    session: Session, tenant_id: str, step: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if not step["dependencies"]:
        return []
    results = load_step_results_for_plan(session, tenant_id, step["executable_plan_id"])
    by_key = {item["compiled_step_key"]: item for item in results}
    missing = [key for key in step["dependencies"] if key not in by_key]
    if missing:
        raise MultiStepEngineError(
            "ae.multi_step_dependency_missing",
            "ExecutableStep dependency StepResult is missing.",
        )
    return [by_key[key] for key in step["dependencies"]]


def _validate_claim(
    claim: RuntimeJobClaim, tenant_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(claim, RuntimeJobClaim):
        raise _invalid("Multi-step execution requires a RuntimeJobClaim.")
    job = dict(claim.job)
    attempt = dict(claim.attempt)
    if (
        job.get("tenant_id") != tenant_id
        or job.get("job_type")
        not in {"START_EXECUTION", "CONTINUE_EXECUTION", "RESUME_EXECUTION"}
        or job.get("state") != "RUNNING"
        or not job.get("executable_step_id")
        or not job.get("lease_owner")
        or attempt.get("runtime_job_id") != job.get("runtime_job_id")
        or not attempt.get("attempt_id")
        or attempt.get("worker_id") != job.get("lease_owner")
        or attempt.get("outcome") != "RUNNING"
        or attempt.get("lease_token") != job.get("lease_token")
    ):
        raise _invalid("RuntimeJob claim is invalid for multi-step execution.")
    return job, attempt


def _enter_external_resume(
    session: Session,
    runtime: Mapping[str, Any],
    step: Mapping[str, Any],
    job: Mapping[str, Any],
    now: str,
) -> None:
    payload = job.get("payload")
    wait_type = (
        "WORK_RESULT"
        if step.get("executor_kind") == "WC_DELEGATE_WORK"
        else "NSL_APPROVAL"
        if step.get("executor_kind") == "LOCAL_SKILL"
        else None
    )
    if (
        step.get("state") != "WAITING"
        or wait_type is None
        or not isinstance(payload, Mapping)
        or not job.get("wait_id")
        or not payload.get("event_id")
    ):
        raise MultiStepEngineError(
            "ae.multi_step_resume_authority_invalid",
            "RESUME_EXECUTION lacks its exact delegated wait authority.",
        )
    wait = (
        session.execute(
            text(
                "SELECT state, matched_event_id, resume_runtime_job_id "
                "FROM ae_wait_registration WHERE tenant_id = :tenant_id "
                "AND wait_id = :wait_id AND agent_execution_id = :execution_id "
                "AND executable_step_id = :step_id AND wait_type = :wait_type"
            ),
            {
                "tenant_id": runtime["tenant_id"],
                "wait_id": job["wait_id"],
                "execution_id": runtime["agent_execution_id"],
                "step_id": step["executable_step_id"],
                "wait_type": wait_type,
            },
        )
        .mappings()
        .first()
    )
    if wait is None or (
        wait["state"],
        str(wait["matched_event_id"]),
        str(wait["resume_runtime_job_id"]),
    ) != (
        "RESUME_QUEUED",
        str(payload["event_id"]),
        str(job["runtime_job_id"]),
    ):
        raise MultiStepEngineError(
            "ae.multi_step_resume_authority_mismatch",
            "RESUME_EXECUTION differs from its matched durable wait.",
        )
    if runtime["state"] == "RUNNING" and runtime["phase"] == "STEP_EXECUTION":
        return
    expected_parent_state = (
        "WAITING_DEPENDENCY" if wait_type == "WORK_RESULT" else "WAITING_APPROVAL"
    )
    if (
        runtime["state"] != expected_parent_state
        or runtime["phase"] != "STEP_EXECUTION"
    ):
        raise MultiStepEngineError(
            "ae.multi_step_resume_parent_unavailable",
            "Parent AgentExecution is not eligible for delegated resume.",
        )
    updated = session.execute(
        text(
            "UPDATE ae_agent_execution SET state = 'RUNNING', "
            "version = version + 1, updated_at = :now "
            "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id "
            "AND state = :expected_state AND phase = 'STEP_EXECUTION' "
            "AND version = :version"
        ),
        {
            "tenant_id": runtime["tenant_id"],
            "execution_id": runtime["agent_execution_id"],
            "version": runtime["version"],
            "expected_state": expected_parent_state,
            "now": now,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise MultiStepEngineError(
            "ae.multi_step_resume_parent_conflict",
            "Parent AgentExecution changed while resuming.",
            True,
        )


def _consume_external_wait(
    session: Session,
    *,
    tenant_id: str,
    job: Mapping[str, Any],
    step: Mapping[str, Any],
    completed_at: str,
) -> None:
    payload = job.get("payload")
    if not isinstance(payload, Mapping):
        raise MultiStepEngineError(
            "ae.multi_step_resume_authority_invalid",
            "RESUME_EXECUTION payload is unavailable.",
        )
    updated = session.execute(
        text(
            "UPDATE ae_wait_registration SET state = 'CONSUMED', "
            "updated_at = :now, version = version + 1 "
            "WHERE tenant_id = :tenant_id AND wait_id = :wait_id "
            "AND agent_execution_id = :execution_id "
            "AND executable_step_id = :step_id AND state = 'RESUME_QUEUED' "
            "AND matched_event_id = :event_id "
            "AND resume_runtime_job_id = :runtime_job_id"
        ),
        {
            "tenant_id": tenant_id,
            "wait_id": job["wait_id"],
            "execution_id": step["agent_execution_id"],
            "step_id": step["executable_step_id"],
            "event_id": payload.get("event_id"),
            "runtime_job_id": job["runtime_job_id"],
            "now": completed_at,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise MultiStepEngineError(
            "ae.multi_step_resume_consume_conflict",
            "Delegated wait changed before StepResult commit.",
            True,
        )


def _require_claim_authority(
    session: Session,
    tenant_id: str,
    job: Mapping[str, Any],
    attempt: Mapping[str, Any],
    observed_at: str,
) -> None:
    now = _required_text("observed_at", observed_at, 64)
    suffix = " FOR UPDATE OF job" if _dialect_name(session) == "postgresql" else ""
    row = session.execute(
        text(
            "SELECT job.runtime_job_id FROM ae_runtime_job AS job "
            "JOIN ae_runtime_job_attempt AS attempt "
            "ON attempt.tenant_id = job.tenant_id "
            "AND attempt.runtime_job_id = job.runtime_job_id "
            "AND attempt.attempt_no = job.attempt_no "
            "WHERE job.tenant_id = :tenant_id "
            "AND job.runtime_job_id = :runtime_job_id "
            "AND job.state = 'RUNNING' "
            "AND job.attempt_no = :attempt_no "
            "AND job.lease_owner = :worker_id "
            "AND job.lease_token = :lease_token "
            "AND job.lease_until > :observed_at "
            "AND attempt.attempt_id = :attempt_id "
            "AND attempt.worker_id = :worker_id "
            "AND attempt.lease_token = :lease_token "
            "AND attempt.outcome = 'RUNNING'" + suffix
        ),
        {
            "tenant_id": tenant_id,
            "runtime_job_id": job["runtime_job_id"],
            "attempt_no": int(attempt["attempt_no"]),
            "attempt_id": attempt["attempt_id"],
            "worker_id": job["lease_owner"],
            "lease_token": job["lease_token"],
            "observed_at": now,
        },
    ).first()
    if row is None:
        raise MultiStepEngineError(
            "ae.multi_step_stale_runtime_job_lease",
            "Step mutation requires the current unexpired RuntimeJob lease.",
            True,
        )


def _load_runtime(
    session: Session, tenant_id: str, execution_id: str, *, lock: bool
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock and _dialect_name(session) == "postgresql" else ""
    row = (
        session.execute(
            text(
                "SELECT tenant_id, agent_execution_id, state, phase, version, correlation_id, "
                "causation_id FROM ae_agent_execution WHERE tenant_id = :tenant_id "
                "AND agent_execution_id = :execution_id" + suffix
            ),
            {"tenant_id": tenant_id, "execution_id": execution_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _row(row)


def _load_plan(
    session: Session, tenant_id: str, execution_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT executable_plan_id, executable_plan_version, plan_hash "
                "FROM ae_executable_plan WHERE tenant_id = :tenant_id "
                "AND agent_execution_id = :execution_id "
                "ORDER BY executable_plan_version DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "execution_id": execution_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _row(row)


def _load_steps(
    session: Session, tenant_id: str, executable_plan_id: str
) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                "SELECT tenant_id, executable_step_id, agent_execution_id, "
                "executable_plan_id, logical_step_id, compiled_step_key, step_index, "
                "step_type, executor_kind, state, version, legacy_interaction_id, "
                "retrieval_package_ref, retrieval_package_hash, cx_generation_id, "
                "cx_job_id, generated_response_id, result_ref, error_ref, "
                "dependency_json, input_binding_json, skill_binding_json, "
                "output_contract_ref, step_contract_hash, "
                "invocation_started_at, completed_at FROM ae_executable_step "
                "WHERE tenant_id = :tenant_id AND executable_plan_id = :plan_id "
                "ORDER BY step_index"
            ),
            {"tenant_id": tenant_id, "plan_id": executable_plan_id},
        )
        .mappings()
        .all()
    )
    return [_step_from_row(row) for row in rows]


def _load_step(
    session: Session, tenant_id: str, executable_step_id: str, *, lock: bool
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock and _dialect_name(session) == "postgresql" else ""
    row = (
        session.execute(
            text(
                "SELECT tenant_id, executable_step_id, agent_execution_id, "
                "executable_plan_id, logical_step_id, compiled_step_key, step_index, "
                "step_type, executor_kind, state, version, legacy_interaction_id, "
                "retrieval_package_ref, retrieval_package_hash, cx_generation_id, "
                "cx_job_id, generated_response_id, result_ref, error_ref, "
                "dependency_json, input_binding_json, skill_binding_json, "
                "output_contract_ref, step_contract_hash, "
                "invocation_started_at, completed_at FROM ae_executable_step "
                "WHERE tenant_id = :tenant_id AND executable_step_id = :step_id"
                + suffix
            ),
            {"tenant_id": tenant_id, "step_id": executable_step_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _step_from_row(row)


def _step_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    value = _row(row)
    value["version"] = int(value["version"])
    value["step_index"] = int(value["step_index"])
    value["dependencies"] = _json_list(value.pop("dependency_json"))
    value["compiled_input_bindings"] = _json_list(value.pop("input_binding_json"))
    skill_binding = value.pop("skill_binding_json")
    value["skill_binding"] = (
        None
        if skill_binding is None
        else dict(
            json.loads(skill_binding)
            if isinstance(skill_binding, str)
            else skill_binding
        )
    )
    for field in (
        "executable_step_id",
        "agent_execution_id",
        "executable_plan_id",
    ):
        value[field] = str(value[field])
    return value


def _require_runtime_authority(runtime: Mapping[str, Any]) -> None:
    if runtime["state"] != "RUNNING" or runtime["phase"] not in {
        "PLAN_COMPILE",
        "STEP_EXECUTION",
    }:
        raise MultiStepEngineError(
            "ae.multi_step_authority_missing",
            "Multi-step engine requires RUNNING planning/execution authority.",
        )


def _require_plan_steps(steps: Sequence[Mapping[str, Any]]) -> None:
    if not steps:
        raise MultiStepEngineError(
            "ae.multi_step_empty_plan",
            "ExecutablePlan has no materialized steps.",
        )
    if [step["step_index"] for step in steps] != list(range(len(steps))):
        raise MultiStepEngineError(
            "ae.multi_step_order_invalid",
            "ExecutableStep order is not contiguous.",
        )


def _enter_step_execution(
    session: Session, runtime: Mapping[str, Any], now: str
) -> None:
    _require_runtime_authority(runtime)
    if runtime["phase"] == "STEP_EXECUTION":
        return
    updated = session.execute(
        text(
            "UPDATE ae_agent_execution SET phase = 'STEP_EXECUTION', "
            "version = version + 1, updated_at = :now "
            "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id "
            "AND state = 'RUNNING' "
            "AND phase = 'PLAN_COMPILE' AND version = :version"
        ),
        {
            "tenant_id": runtime["tenant_id"],
            "execution_id": runtime["agent_execution_id"],
            "version": runtime["version"],
            "now": now,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise MultiStepEngineError(
            "ae.multi_step_execution_conflict",
            "AgentExecution changed before step execution.",
            True,
        )


def _require_delegate_wait(session: Session, params: Mapping[str, Any]) -> None:
    row = session.execute(
        text(
            "SELECT wait_id FROM ae_wait_registration "
            "WHERE tenant_id = :tenant_id "
            "AND wait_id = :wait_id "
            "AND agent_execution_id = :execution_id "
            "AND executable_step_id = :step_id "
            "AND wait_type = 'WORK_RESULT' "
            "AND external_ref = :external_ref "
            "AND result_contract_ref = :result_contract_ref "
            "AND state = 'PENDING'"
        ),
        params,
    ).first()
    if row is None:
        raise MultiStepEngineError(
            "ae.multi_step_wait_registration_mismatch",
            "DELEGATE_WORK requires its exact pending WaitRegistration.",
        )


def _require_nsl_approval_wait(session: Session, params: Mapping[str, Any]) -> None:
    row = session.execute(
        text(
            "SELECT wait_id FROM ae_wait_registration "
            "WHERE tenant_id = :tenant_id "
            "AND wait_id = :wait_id "
            "AND agent_execution_id = :execution_id "
            "AND executable_step_id = :step_id "
            "AND wait_type = 'NSL_APPROVAL' "
            "AND external_ref = :external_ref "
            "AND result_contract_ref = :result_contract_ref "
            "AND state = 'PENDING'"
        ),
        params,
    ).first()
    if row is None:
        raise MultiStepEngineError(
            "ae.multi_step_wait_registration_mismatch",
            "LOCAL_SKILL approval requires its exact pending WaitRegistration.",
        )


def _move_to_dependency_wait(
    session: Session, runtime: Mapping[str, Any], now: str
) -> None:
    if runtime["state"] != "RUNNING" or runtime["phase"] != "STEP_EXECUTION":
        raise MultiStepEngineError(
            "ae.multi_step_dependency_wait_mismatch",
            "DELEGATE_WORK requires active step execution authority.",
        )
    updated = session.execute(
        text(
            "UPDATE ae_agent_execution SET state = 'WAITING_DEPENDENCY', "
            "version = version + 1, updated_at = :now "
            "WHERE tenant_id = :tenant_id "
            "AND agent_execution_id = :execution_id "
            "AND state = 'RUNNING' AND phase = 'STEP_EXECUTION' "
            "AND version = :version"
        ),
        {
            "tenant_id": runtime["tenant_id"],
            "execution_id": runtime["agent_execution_id"],
            "version": runtime["version"],
            "now": now,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise MultiStepEngineError(
            "ae.multi_step_dependency_wait_conflict",
            "AgentExecution changed before dependency wait.",
            True,
        )


def _move_to_approval_wait(
    session: Session, runtime: Mapping[str, Any], now: str
) -> None:
    if runtime["state"] != "RUNNING" or runtime["phase"] != "STEP_EXECUTION":
        raise MultiStepEngineError(
            "ae.multi_step_approval_wait_mismatch",
            "NSL approval requires active step execution authority.",
        )
    updated = session.execute(
        text(
            "UPDATE ae_agent_execution SET state = 'WAITING_APPROVAL', "
            "version = version + 1, updated_at = :now "
            "WHERE tenant_id = :tenant_id "
            "AND agent_execution_id = :execution_id "
            "AND state = 'RUNNING' AND phase = 'STEP_EXECUTION' "
            "AND version = :version"
        ),
        {
            "tenant_id": runtime["tenant_id"],
            "execution_id": runtime["agent_execution_id"],
            "version": runtime["version"],
            "now": now,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise MultiStepEngineError(
            "ae.multi_step_approval_wait_conflict",
            "AgentExecution changed before approval wait.",
            True,
        )


def _move_to_result_verify(
    session: Session, runtime: Mapping[str, Any], now: str
) -> None:
    if runtime["phase"] == "RESULT_VERIFY":
        return
    if runtime["state"] != "RUNNING" or runtime["phase"] not in {
        "PLAN_COMPILE",
        "STEP_EXECUTION",
    }:
        raise MultiStepEngineError(
            "ae.multi_step_result_verify_conflict",
            "AgentExecution cannot enter result verification.",
        )
    updated = session.execute(
        text(
            "UPDATE ae_agent_execution SET phase = 'RESULT_VERIFY', "
            "version = version + 1, updated_at = :now "
            "WHERE tenant_id = :tenant_id AND agent_execution_id = :execution_id "
            "AND state = 'RUNNING' "
            "AND phase = :phase AND version = :version"
        ),
        {
            "tenant_id": runtime["tenant_id"],
            "execution_id": runtime["agent_execution_id"],
            "phase": runtime["phase"],
            "version": runtime["version"],
            "now": now,
        },
    )
    if int(updated.rowcount or 0) != 1:
        raise MultiStepEngineError(
            "ae.multi_step_execution_conflict",
            "AgentExecution changed before result verification.",
            True,
        )


def _all_terminal(steps: Sequence[Mapping[str, Any]]) -> bool:
    return bool(steps) and all(step["state"] in TERMINAL_STATES for step in steps)


def _required_uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID string.")
    try:
        UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID string.") from exc
    return value


def _required_text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _optional_text(field: str, value: object, maximum: int) -> str | None:
    return None if value is None else _required_text(field, value, maximum)


def _continuation_refs(value: Mapping[str, str | None]) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise _invalid("continuation_refs must be an object.")
    allowed = {
        "cx_job_ref",
        "cx_generation_ref",
        "generated_response_ref",
        "status",
    }
    if not value or not set(value).issubset(allowed):
        raise _invalid("continuation_refs fields are invalid.")
    refs = {
        str(key): _optional_text(str(key), item, 256) for key, item in value.items()
    }
    if refs.get("cx_job_ref") is None:
        raise _invalid("continuation_refs requires cx_job_ref.")
    return refs


def _json_list(value: Any) -> list[Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        raise MultiStepEngineError(
            "ae.multi_step_corrupt",
            "Stored ExecutableStep collection is not an array.",
        )
    return decoded


def _row(row: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(row)
    for field in (
        "agent_execution_id",
        "executable_plan_id",
    ):
        if field in value and value[field] is not None:
            value[field] = str(value[field])
    if "version" in value:
        value["version"] = int(value["version"])
    return value


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> MultiStepEngineError:
    return MultiStepEngineError("ae.multi_step_invalid", detail)


def _from_step_result_error(error: StepResultError) -> MultiStepEngineError:
    return MultiStepEngineError(error.error_code, error.detail, error.retryable)


def _unavailable() -> MultiStepEngineError:
    return MultiStepEngineError(
        "ae.multi_step_store_unavailable",
        "AE multi-step engine store is unavailable.",
        True,
    )
