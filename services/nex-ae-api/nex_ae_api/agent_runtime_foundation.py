from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    SqlAlchemyAgentExecutionRepository,
    agent_runtime_mode,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.agent_results import SqlAlchemyAgentResultRepository
from nex_ae_api.chat_application import ChatApplicationService
from nex_ae_api.executable_steps import (
    CompatibilityChatRuntime,
    SqlAlchemyExecutableStepRepository,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue


@dataclass(frozen=True)
class AgentRuntimeFoundationError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AgentRuntimeFoundation:
    mode: str
    available: bool
    admission: AgentExecutionAdmissionService | None
    jobs: SqlAlchemyRuntimeJobQueue | None
    steps: SqlAlchemyExecutableStepRepository | None
    compatibility: CompatibilityChatRuntime | None
    results: SqlAlchemyAgentResultRepository | None
    traces: SqlAlchemyAgentRuntimeTraceSource | None
    unavailable_reason: str | None = None


class SqlAlchemyAgentRuntimeTraceSource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(
        self, *, tenant_id: str, agent_execution_id: str
    ) -> dict[str, Any] | None:
        scope = {
            "tenant_id": _required("tenant_id", tenant_id),
            "agent_execution_id": _required(
                "agent_execution_id", agent_execution_id
            ),
        }
        try:
            with self._session_factory() as session:
                execution = _one(
                    session,
                    """
                    SELECT tenant_id, agent_execution_id, agent_id, trigger_id,
                           legacy_interaction_id, state, phase, result_id,
                           correlation_id, project_id
                    FROM ae_agent_execution
                    WHERE tenant_id = :tenant_id
                      AND agent_execution_id = :agent_execution_id
                    """,
                    scope,
                )
                if execution is None:
                    return None
                job = _one(
                    session,
                    """
                    SELECT runtime_job_id, job_type, state, attempt_no,
                           correlation_id
                    FROM ae_runtime_job
                    WHERE tenant_id = :tenant_id
                      AND execution_id = :agent_execution_id
                    ORDER BY created_at ASC, runtime_job_id ASC LIMIT 1
                    """,
                    scope,
                )
                step = _one(
                    session,
                    """
                    SELECT executable_step_id, state, retrieval_package_ref,
                           cx_generation_id, cx_job_id, generated_response_id,
                           correlation_id
                    FROM ae_executable_step
                    WHERE tenant_id = :tenant_id
                      AND agent_execution_id = :agent_execution_id
                      AND step_kind = 'P4_CHAT_RAG_COMPATIBILITY'
                    """,
                    scope,
                )
                result = _one(
                    session,
                    """
                    SELECT result_id, status, result_hash
                    FROM ae_agent_result
                    WHERE tenant_id = :tenant_id
                      AND agent_execution_id = :agent_execution_id
                    """,
                    scope,
                )
                delivery = None
                if result is not None:
                    delivery = _one(
                        session,
                        """
                        SELECT delivery_id, target_type, state, required,
                               correlation_id
                        FROM ae_result_delivery
                        WHERE tenant_id = :tenant_id AND result_id = :result_id
                          AND target_type = 'WORKSPACE_RESULT'
                        """,
                        {**scope, "result_id": result["result_id"]},
                    )
                attempt_counts = _one(
                    session,
                    """
                    SELECT count(*) AS total,
                           sum(CASE WHEN outcome = 'LEASE_EXPIRED' THEN 1 ELSE 0 END)
                               AS lease_expired
                    FROM ae_runtime_job_attempt
                    WHERE tenant_id = :tenant_id
                      AND runtime_job_id = :runtime_job_id
                    """,
                    {
                        **scope,
                        "runtime_job_id": None if job is None else job["runtime_job_id"],
                    },
                ) if job is not None else None
                return build_agent_runtime_trace(
                    execution=execution,
                    job=job,
                    step=step,
                    result=result,
                    delivery=delivery,
                    attempt_counts=attempt_counts,
                )
        except AgentRuntimeFoundationError:
            raise
        except SQLAlchemyError as exc:
            raise AgentRuntimeFoundationError(
                "ae.agent_runtime_trace_unavailable",
                "AE Agent Runtime trace store is unavailable.",
                True,
            ) from exc


def build_agent_runtime_trace(
    *,
    execution: Mapping[str, Any],
    job: Mapping[str, Any] | None,
    step: Mapping[str, Any] | None,
    result: Mapping[str, Any] | None,
    delivery: Mapping[str, Any] | None,
    attempt_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = _required("tenant_id", execution.get("tenant_id"))
    correlation_id = _required("correlation_id", execution.get("correlation_id"))
    for item in (job, step, delivery):
        if item is not None and item.get("correlation_id") != correlation_id:
            raise AgentRuntimeFoundationError(
                "ae.agent_runtime_trace_lineage_conflict",
                "Runtime trace correlation lineage is inconsistent.",
            )
    identities = {
        "interaction_id": _string(execution.get("legacy_interaction_id")),
        "execution_trigger_id": _string(execution.get("trigger_id")),
        "agent_id": _string(execution.get("agent_id")),
        "agent_execution_id": _string(execution.get("agent_execution_id")),
        "runtime_job_id": _string(None if job is None else job.get("runtime_job_id")),
        "executable_step_id": _string(
            None if step is None else step.get("executable_step_id")
        ),
        "retrieval_package_id": _string(
            None if step is None else step.get("retrieval_package_ref")
        ),
        "cx_generation_id": _string(
            None if step is None else step.get("cx_generation_id")
        ),
        "cx_job_id": _string(None if step is None else step.get("cx_job_id")),
        "generated_response_id": _string(
            None if step is None else step.get("generated_response_id")
        ),
        "agent_result_id": _string(
            None if result is None else result.get("result_id")
        ),
        "result_delivery_id": _string(
            None if delivery is None else delivery.get("delivery_id")
        ),
    }
    attempt_total = _count(attempt_counts, "total")
    lease_expired = _count(attempt_counts, "lease_expired")
    return {
        "runtime_trace_schema_version": "ae_agent_runtime_trace.v1",
        "tenant_id": tenant_id,
        "correlation_id": correlation_id,
        "identities": identities,
        "states": {
            "execution_state": execution.get("state"),
            "execution_phase": execution.get("phase"),
            "runtime_job_state": None if job is None else job.get("state"),
            "runtime_job_type": None if job is None else job.get("job_type"),
            "executable_step_state": None if step is None else step.get("state"),
            "agent_result_status": None if result is None else result.get("status"),
            "result_delivery_state": (
                None if delivery is None else delivery.get("state")
            ),
        },
        "lease_summary": {
            "attempt_count": attempt_total,
            "lease_expired_count": lease_expired,
        },
        "boundaries": {
            "project_resolved": execution.get("project_id") is not None,
            "workspace_delivery_required": (
                bool(delivery.get("required")) if delivery is not None else False
            ),
            "workspace_delivery_pending": (
                delivery is not None
                and delivery.get("target_type") == "WORKSPACE_RESULT"
                and delivery.get("state") == "PENDING"
            ),
            "succeeded_without_ack": (
                execution.get("state") == "SUCCEEDED"
                and delivery is not None
                and delivery.get("state") != "ACKNOWLEDGED"
            ),
        },
        "privacy": {
            "prompt_content_included": False,
            "response_content_included": False,
            "evidence_content_included": False,
            "secret_included": False,
            "provider_endpoint_included": False,
            "database_url_included": False,
        },
    }


def attach_agent_runtime_foundation(
    app: Any,
    persistence: Any,
    *,
    application: ChatApplicationService | None = None,
    environ: Mapping[str, str] | None = None,
) -> AgentRuntimeFoundation:
    mode = agent_runtime_mode(environ)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is None:
        if mode == "required":
            raise AgentRuntimeFoundationError(
                "ae.agent_runtime_persistence_required",
                "Required Agent Runtime mode needs AE PostgreSQL persistence.",
            )
        foundation = AgentRuntimeFoundation(
            mode=mode,
            available=False,
            admission=None,
            jobs=None,
            steps=None,
            compatibility=None,
            results=None,
            traces=None,
            unavailable_reason="persistence_not_configured",
        )
        app.state.ae_agent_runtime = foundation
        return foundation

    identities = SqlAlchemyAgentIdentityRegistry(session_factory)
    executions = SqlAlchemyAgentExecutionRepository(session_factory)
    jobs = SqlAlchemyRuntimeJobQueue(session_factory)
    steps = SqlAlchemyExecutableStepRepository(session_factory)
    foundation = AgentRuntimeFoundation(
        mode=mode,
        available=True,
        admission=AgentExecutionAdmissionService(
            identities=identities,
            executions=executions,
            mode=mode,
        ),
        jobs=jobs,
        steps=steps,
        compatibility=CompatibilityChatRuntime(
            steps=steps,
            jobs=jobs,
            application=application or ChatApplicationService(),
            mode=mode,
        ),
        results=SqlAlchemyAgentResultRepository(session_factory),
        traces=SqlAlchemyAgentRuntimeTraceSource(session_factory),
    )
    app.state.ae_agent_runtime = foundation
    return foundation


def _one(
    session: Session,
    statement: str,
    params: Mapping[str, Any],
) -> dict[str, Any] | None:
    row = session.execute(text(statement), params).mappings().first()
    if row is None:
        return None
    return {
        key: str(value) if key.endswith("_id") and value is not None else value
        for key, value in row.items()
    }


def _count(value: Mapping[str, Any] | None, key: str) -> int:
    if value is None or value.get(key) is None:
        return 0
    return int(value[key])


def _string(value: object) -> str | None:
    return None if value is None else str(value)


def _required(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentRuntimeFoundationError(
            "ae.agent_runtime_trace_invalid",
            f"{field} must be a non-empty string.",
        )
    return value.strip()
