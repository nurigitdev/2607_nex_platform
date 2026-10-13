from __future__ import annotations

from types import SimpleNamespace

import pytest
from nex_ae_api.agent_runtime_foundation import (
    AgentRuntimeFoundationError,
    SqlAlchemyAgentRuntimeTraceSource,
    attach_agent_runtime_foundation,
    build_agent_runtime_trace,
)
from nex_ae_api.chat_application import ChatApplicationService
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TENANT = "tenant-a"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
RESULT_ID = "22222222-2222-4222-8222-222222222222"


def _factory(*, with_schema: bool = True):
    engine = create_engine("sqlite+pysqlite://", future=True)
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ae_agent_execution (
                    tenant_id TEXT, agent_execution_id TEXT, agent_id TEXT,
                    trigger_id TEXT, legacy_interaction_id TEXT, state TEXT,
                    phase TEXT, result_id TEXT, correlation_id TEXT,
                    project_id TEXT
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_runtime_job (
                    tenant_id TEXT, runtime_job_id TEXT, job_type TEXT,
                    execution_id TEXT, state TEXT, attempt_no INTEGER,
                    correlation_id TEXT, created_at TEXT
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_runtime_job_attempt (
                    tenant_id TEXT, runtime_job_id TEXT, outcome TEXT
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_executable_step (
                    tenant_id TEXT, executable_step_id TEXT,
                    agent_execution_id TEXT, step_kind TEXT, state TEXT,
                    retrieval_package_ref TEXT, cx_generation_id TEXT,
                    cx_job_id TEXT, generated_response_id TEXT,
                    correlation_id TEXT
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_agent_result (
                    tenant_id TEXT, result_id TEXT, agent_execution_id TEXT,
                    status TEXT, result_hash TEXT
                )
            """))
            connection.execute(text("""
                CREATE TABLE ae_result_delivery (
                    tenant_id TEXT, delivery_id TEXT, result_id TEXT,
                    target_type TEXT, state TEXT, required BOOLEAN,
                    correlation_id TEXT
                )
            """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed(factory, *, correlation: str = "correlation-a") -> None:
    with factory.begin() as session:
        session.execute(text("""
            INSERT INTO ae_agent_execution VALUES (
                :tenant, :execution, 'agent-a', 'trigger-a', 'interaction-a',
                'RUNNING', 'RESULT_PUBLISH', :result, :correlation, NULL
            )
        """), {"tenant": TENANT, "execution": EXECUTION_ID,
                "result": RESULT_ID, "correlation": correlation})
        session.execute(text("""
            INSERT INTO ae_runtime_job VALUES (
                :tenant, 'job-a', 'START_EXECUTION', :execution, 'DONE', 2,
                :correlation, '2026-10-13T05:00:00Z'
            )
        """), {"tenant": TENANT, "execution": EXECUTION_ID,
                "correlation": correlation})
        session.execute(text("""
            INSERT INTO ae_runtime_job_attempt VALUES
                (:tenant, 'job-a', 'LEASE_EXPIRED'),
                (:tenant, 'job-a', 'DONE')
        """), {"tenant": TENANT})
        session.execute(text("""
            INSERT INTO ae_executable_step VALUES (
                :tenant, 'step-a', :execution, 'P4_CHAT_RAG_COMPATIBILITY',
                'SUCCEEDED', 'retrieval-a', 'generation-a', 'cx-job-a',
                'response-a', :correlation
            )
        """), {"tenant": TENANT, "execution": EXECUTION_ID,
                "correlation": correlation})
        session.execute(text("""
            INSERT INTO ae_agent_result VALUES (
                :tenant, :result, :execution, 'SUCCEEDED', 'sha256:result'
            )
        """), {"tenant": TENANT, "result": RESULT_ID,
                "execution": EXECUTION_ID})
        session.execute(text("""
            INSERT INTO ae_result_delivery VALUES (
                :tenant, 'delivery-a', :result, 'WORKSPACE_RESULT', 'PENDING',
                1, :correlation
            )
        """), {"tenant": TENANT, "result": RESULT_ID,
                "correlation": correlation})


def test_trace_source_projects_full_content_free_identity_chain_after_restart() -> None:
    factory = _factory()
    _seed(factory)

    trace = SqlAlchemyAgentRuntimeTraceSource(factory).get(
        tenant_id=TENANT, agent_execution_id=EXECUTION_ID
    )

    assert trace is not None
    assert trace["identities"] == {
        "interaction_id": "interaction-a",
        "execution_trigger_id": "trigger-a",
        "agent_id": "agent-a",
        "agent_execution_id": EXECUTION_ID,
        "runtime_job_id": "job-a",
        "executable_step_id": "step-a",
        "retrieval_package_id": "retrieval-a",
        "cx_generation_id": "generation-a",
        "cx_job_id": "cx-job-a",
        "generated_response_id": "response-a",
        "agent_result_id": RESULT_ID,
        "result_delivery_id": "delivery-a",
    }
    assert trace["states"] == {
        "execution_state": "RUNNING",
        "execution_phase": "RESULT_PUBLISH",
        "runtime_job_state": "DONE",
        "runtime_job_type": "START_EXECUTION",
        "executable_step_state": "SUCCEEDED",
        "agent_result_status": "SUCCEEDED",
        "result_delivery_state": "PENDING",
    }
    assert trace["lease_summary"] == {
        "attempt_count": 2,
        "lease_expired_count": 1,
    }
    assert trace["boundaries"] == {
        "project_resolved": False,
        "workspace_delivery_required": True,
        "workspace_delivery_pending": True,
        "succeeded_without_ack": False,
    }
    assert set(trace["privacy"].values()) == {False}
    assert SqlAlchemyAgentRuntimeTraceSource(factory).get(
        tenant_id=TENANT, agent_execution_id="missing"
    ) is None


def test_partial_trace_uses_null_identities_and_zero_attempts() -> None:
    trace = build_agent_runtime_trace(
        execution={
            "tenant_id": TENANT,
            "correlation_id": "correlation-a",
            "agent_execution_id": EXECUTION_ID,
            "state": "QUEUED",
            "phase": "INTAKE",
            "project_id": None,
        },
        job=None,
        step=None,
        result=None,
        delivery=None,
    )
    assert trace["identities"]["runtime_job_id"] is None
    assert trace["lease_summary"] == {
        "attempt_count": 0,
        "lease_expired_count": 0,
    }
    assert trace["boundaries"]["workspace_delivery_pending"] is False


def test_trace_rejects_correlation_conflicts_and_succeeded_pending_delivery() -> None:
    execution = {
        "tenant_id": TENANT,
        "correlation_id": "correlation-a",
        "agent_execution_id": EXECUTION_ID,
        "state": "SUCCEEDED",
        "phase": "FINALIZE",
        "project_id": "project-a",
    }
    with pytest.raises(AgentRuntimeFoundationError) as conflict:
        build_agent_runtime_trace(
            execution=execution,
            job={"correlation_id": "other"},
            step=None,
            result=None,
            delivery=None,
        )
    assert conflict.value.error_code == "ae.agent_runtime_trace_lineage_conflict"

    trace = build_agent_runtime_trace(
        execution=execution,
        job=None,
        step=None,
        result={"result_id": RESULT_ID, "status": "SUCCEEDED"},
        delivery={
            "delivery_id": "delivery-a",
            "target_type": "WORKSPACE_RESULT",
            "state": "PENDING",
            "required": True,
            "correlation_id": "correlation-a",
        },
    )
    assert trace["boundaries"]["project_resolved"] is True
    assert trace["boundaries"]["succeeded_without_ack"] is True


def test_trace_source_maps_store_failure_and_invalid_scope() -> None:
    source = SqlAlchemyAgentRuntimeTraceSource(_factory(with_schema=False))
    with pytest.raises(AgentRuntimeFoundationError) as unavailable:
        source.get(tenant_id=TENANT, agent_execution_id=EXECUTION_ID)
    assert unavailable.value.error_code == "ae.agent_runtime_trace_unavailable"
    assert unavailable.value.retryable is True
    with pytest.raises(AgentRuntimeFoundationError) as invalid:
        source.get(tenant_id="", agent_execution_id=EXECUTION_ID)
    assert invalid.value.error_code == "ae.agent_runtime_trace_invalid"
    assert str(invalid.value) == invalid.value.detail


def test_trace_source_handles_pre_result_and_propagates_lineage_conflict() -> None:
    factory = _factory()
    _seed(factory)
    with factory.begin() as session:
        session.execute(text("DELETE FROM ae_result_delivery"))
        session.execute(text("DELETE FROM ae_agent_result"))
    trace = SqlAlchemyAgentRuntimeTraceSource(factory).get(
        tenant_id=TENANT, agent_execution_id=EXECUTION_ID
    )
    assert trace is not None
    assert trace["identities"]["agent_result_id"] is None

    with factory.begin() as session:
        session.execute(
            text("UPDATE ae_runtime_job SET correlation_id = 'other'")
        )
    with pytest.raises(AgentRuntimeFoundationError) as conflict:
        SqlAlchemyAgentRuntimeTraceSource(factory).get(
            tenant_id=TENANT, agent_execution_id=EXECUTION_ID
        )
    assert conflict.value.error_code == "ae.agent_runtime_trace_lineage_conflict"


def test_bootstrap_attaches_complete_foundation_for_configured_persistence() -> None:
    factory = _factory()
    app = SimpleNamespace(state=SimpleNamespace())
    application = ChatApplicationService()
    foundation = attach_agent_runtime_foundation(
        app,
        SimpleNamespace(api_session_factory=factory),
        application=application,
        environ={"NEX_AE_AGENT_RUNTIME_MODE": "shadow"},
    )
    assert foundation.available is True
    assert foundation.mode == "shadow"
    assert foundation.admission is not None
    assert foundation.jobs is not None
    assert foundation.steps is not None
    assert foundation.compatibility is not None
    assert foundation.results is not None
    assert foundation.traces is not None
    assert app.state.ae_agent_runtime is foundation


def test_bootstrap_disabled_without_persistence_and_required_fails_closed() -> None:
    app = SimpleNamespace(state=SimpleNamespace())
    foundation = attach_agent_runtime_foundation(
        app,
        SimpleNamespace(api_session_factory=None),
        environ={"NEX_AE_AGENT_RUNTIME_MODE": "disabled"},
    )
    assert foundation.available is False
    assert foundation.unavailable_reason == "persistence_not_configured"
    assert foundation.traces is None

    with pytest.raises(AgentRuntimeFoundationError) as required:
        attach_agent_runtime_foundation(
            app,
            SimpleNamespace(api_session_factory=None),
            environ={"NEX_AE_AGENT_RUNTIME_MODE": "required"},
        )
    assert required.value.error_code == "ae.agent_runtime_persistence_required"
