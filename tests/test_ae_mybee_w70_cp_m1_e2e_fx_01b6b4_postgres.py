from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from nex_ae_api.agent_execution import SqlAlchemyAgentExecutionRepository
from nex_ae_api.agent_plans import SqlAlchemyAgentPlanRepository
from nex_ae_api.executable_plans import SqlAlchemyExecutablePlanRepository
from nex_ae_api.m1_plan_activation import InstalledM1PlanActivation
from nex_ae_api.m1_product_planning_coordinator import (
    build_m1_product_planning_coordinator_registration,
)
from nex_ae_api.m1_product_preparation_coordinator import (
    InstalledM1ProductPlanningCoordinator,
    M1ProductPreparationCoordinatorError,
)
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
from nex_ae_api.plan_validation import SqlAlchemyPlanValidationRepository
from nex_ae_api.planning_capabilities import SqlAlchemyCapabilitySnapshotRepository
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_planning_coordinators import ProductPlanningPolicy
from nex_ae_api.product_preparation_persistence import (
    ProductPreparationPersistenceError,
    SqlAlchemyGeneralizedWaitEventRepository,
    SqlAlchemyProductPreparationCheckpointRepository,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.runtime_resume import SqlAlchemyProductPreparationResumeService
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from test_ae_mybee_w70_cp_m1_e2e_fx_01b5_plan_materialization import (
    _agent_context,
    _preparation,
    _runtime,
    _snapshot,
    _work_intent,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b2_preparation_resume import (
    ENVELOPE_ID,
    EVIDENCE_ID,
    TENANT,
    _AuthoritySource,
    _PreparationAdapter,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b2_preparation_resume import (
    NOW as AUTHORITY_NOW,
)

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_AE_MYBEE_W70_CP_M1_01B6B4_POSTGRES_SMOKE") == "1"
NOW = datetime(2026, 11, 18, 1, 0, tzinfo=UTC)
NOW_TEXT = "2026-11-18T01:00:00Z"
AGENT_ID = "61000000-0000-4000-8000-000000000001"
TRIGGER_ID = "61000000-0000-4000-8000-000000000002"
LEGACY_INTERACTION_ID = "61000000-0000-4000-8000-000000000003"
WORKSPACE_ID = "61000000-0000-4000-8000-000000000004"
CONVERSATION_ID = "61000000-0000-4000-8000-000000000005"
DETERMINISTIC_PERSISTENCE_POLICY = ProductPlanningPolicy(
    mode="DETERMINISTIC_ONLY",
    proposal_schema_version="ae.product_planning_proposal.v1",
    prompt_binding_key="ae.plan_builder.project_delegation.v1",
    admission_policy_ref="ae.product_planning_proposal.strict.v1",
    deterministic_fallback_ref=None,
    proposal_consumers=(),
)


class _ProtectedPreparationAdapter(_PreparationAdapter):
    """Test owner double; durable orchestration remains the product runtime."""

    def __init__(self, work_intent: dict) -> None:
        super().__init__()
        self._work_intent = copy.deepcopy(work_intent)

    def continue_after_accounting_approval(self, **values):
        self.calls.append(("ACCOUNTING", values["accounting_approval_evidence_id"]))
        assert values["accounting_approval_evidence_id"] == EVIDENCE_ID
        return _preparation(self._work_intent)


def _registry():
    return load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json"
            )
        }
    )


def _components(sessions, *, work_intent, adapter=None, authority_source=None):
    selected_adapter = adapter or _ProtectedPreparationAdapter(work_intent)
    registration = build_m1_product_planning_coordinator_registration(
        product_capabilities=_registry(),
        preparation_registration=selected_adapter.registration,
        planning_policy=DETERMINISTIC_PERSISTENCE_POLICY,
    )
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    waits = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    coordinator = InstalledM1ProductPlanningCoordinator(
        registration=registration,
        transaction_preparation=SimpleNamespace(adapter=selected_adapter),
        authority_source=authority_source or _AuthoritySource(),
        checkpoints=checkpoints,
        wait_events=waits,
        clock=lambda: NOW,
    )
    jobs = SqlAlchemyRuntimeJobQueue(sessions)
    resume = SqlAlchemyProductPreparationResumeService(
        sessions,
        runtime_jobs=jobs,
        clock=lambda: NOW,
    )
    return SimpleNamespace(
        registration=registration,
        adapter=selected_adapter,
        coordinator=coordinator,
        checkpoints=checkpoints,
        waits=waits,
        jobs=jobs,
        resume=resume,
    )


def _activation(sessions, *, coordinator, registration):
    jobs = SqlAlchemyRuntimeJobQueue(sessions)
    scheduler = SqlAlchemyMultiStepEngine(sessions, jobs)
    return InstalledM1PlanActivation(
        registration=registration,
        ready_checkpoints=coordinator,
        materializer=_runtime(),
        agent_plans=SqlAlchemyAgentPlanRepository(sessions),
        validations=SqlAlchemyPlanValidationRepository(sessions),
        executable_plans=SqlAlchemyExecutablePlanRepository(sessions),
        executions=SqlAlchemyAgentExecutionRepository(sessions),
        scheduler=scheduler,
        clock=lambda: NOW,
    )


def _seed_lineage(sessions, *, work_intent, agent_context, capability_snapshot):
    with sessions.begin() as session:
        session.execute(
            text("""
                INSERT INTO ae_agent_identity (
                    tenant_id, agent_id, agent_type, profile_ref, status,
                    project_id, created_at, version
                ) VALUES (
                    :tenant_id, :agent_id, 'IA', :profile_ref, 'ACTIVE',
                    NULL, :now, 1
                )
                """),
            {
                "tenant_id": TENANT,
                "agent_id": AGENT_ID,
                "profile_ref": "agent-profile://nex-platform/ia/m1-protected-gate/v1",
                "now": NOW_TEXT,
            },
        )
        session.execute(
            text("""
                INSERT INTO ae_agent_execution (
                    tenant_id, agent_execution_id, agent_id, agent_type,
                    principal_id, trigger_id, source_type, source_ref,
                    legacy_interaction_id, state, phase, version,
                    correlation_id, received_at, created_at, updated_at
                ) VALUES (
                    :tenant_id, :execution_id, :agent_id, 'IA', :principal_id,
                    :trigger_id, 'PROMPT', :source_ref, :interaction_id,
                    'RUNNING', 'PLAN_BUILD', 1, :correlation_id,
                    :now, :now, :now
                )
                """),
            {
                "tenant_id": TENANT,
                "execution_id": work_intent["execution_id"],
                "agent_id": AGENT_ID,
                "principal_id": "employee-100",
                "trigger_id": TRIGGER_ID,
                "source_ref": work_intent["source"]["source_ref"],
                "interaction_id": LEGACY_INTERACTION_ID,
                "correlation_id": "cp-m1-01b6b4-protected",
                "now": NOW_TEXT,
            },
        )
        session.execute(
            text("""
                INSERT INTO ae_work_intent (
                    tenant_id, work_intent_id, intent_revision,
                    agent_execution_id, source_ref, actor_ref,
                    compatibility_execution_mode, work_class, intent_hash,
                    intent_json, created_at
                ) VALUES (
                    :tenant_id, :work_intent_id, :intent_revision,
                    :execution_id, :source_ref, :actor_ref,
                    :compatibility_execution_mode, :work_class, :intent_hash,
                    CAST(:intent_json AS JSONB), :now
                )
                """),
            {
                "tenant_id": TENANT,
                "work_intent_id": work_intent["work_intent_id"],
                "intent_revision": work_intent["intent_revision"],
                "execution_id": work_intent["execution_id"],
                "source_ref": work_intent["source"]["source_ref"],
                "actor_ref": work_intent["source"]["actor_ref"],
                "compatibility_execution_mode": work_intent[
                    "compatibility_execution_mode"
                ],
                "work_class": work_intent["work_class"],
                "intent_hash": work_intent["intent_hash"],
                "intent_json": json.dumps(work_intent, sort_keys=True),
                "now": NOW_TEXT,
            },
        )
        persisted_context = {"schema_version": "1.1", **agent_context}
        session.execute(
            text("""
                INSERT INTO ae_agent_context (
                    tenant_id, context_id, context_generation,
                    agent_execution_id, work_intent_id, work_intent_revision,
                    work_intent_hash, principal_id, agent_id,
                    workspace_id, conversation_id, interaction_id,
                    context_hash, context_json, built_at
                ) VALUES (
                    :tenant_id, :context_id, :context_generation,
                    :execution_id, :work_intent_id, :work_intent_revision,
                    :work_intent_hash, :principal_id, :agent_id,
                    :workspace_id, :conversation_id, :interaction_id, :context_hash,
                    CAST(:context_json AS JSONB), :now
                )
                """),
            {
                "tenant_id": TENANT,
                "context_id": agent_context["context_id"],
                "context_generation": agent_context["context_generation"],
                "execution_id": work_intent["execution_id"],
                "work_intent_id": work_intent["work_intent_id"],
                "work_intent_revision": work_intent["intent_revision"],
                "work_intent_hash": work_intent["intent_hash"],
                "principal_id": "employee-100",
                "agent_id": AGENT_ID,
                "workspace_id": WORKSPACE_ID,
                "conversation_id": CONVERSATION_ID,
                "interaction_id": LEGACY_INTERACTION_ID,
                "context_hash": agent_context["context_hash"],
                "context_json": json.dumps(persisted_context, sort_keys=True),
                "now": NOW_TEXT,
            },
        )
    SqlAlchemyCapabilitySnapshotRepository(sessions).save(capability_snapshot)


def _notify(components, checkpoint, *, event_id, evidence_ref):
    return components.coordinator.accept_approval_notification(
        tenant_id=TENANT,
        checkpoint_id=checkpoint["checkpoint_id"],
        event_id=event_id,
        notification_ref=f"wc-event://{event_id}",
        authority_evidence_ref=evidence_ref,
        received_at=NOW_TEXT,
    )


def _counts(sessions) -> dict[str, int]:
    tables = {
        "checkpoints": "ae_product_prep_checkpoint",
        "waits": "ae_wait_registration",
        "events": "ae_external_event_inbox",
        "plans": "ae_agent_plan",
        "validations": "ae_plan_validation",
        "executable_plans": "ae_executable_plan",
        "steps": "ae_executable_step",
        "jobs": "ae_runtime_job",
    }
    with sessions() as session:
        return {
            name: int(
                session.execute(
                    text(
                        f"SELECT count(*) FROM {table} " "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": TENANT},
                ).scalar_one()
            )
            for name, table in tables.items()
        }


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W70 CP-M1 01B.6B.4 AE PostgreSQL smoke is disabled",
)
def test_actual_postgres_two_wait_restart_ack_loss_plan_replay_and_zero_residue():
    target = make_url(DATABASE_URL)
    assert (target.username, target.database) == ("nex_ae_user", "nex_ae_test")
    schema_name = f"mybee_w70_01b6b4_{uuid.uuid4().hex}"
    postgres_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(postgres_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_ae_test", "nex_ae_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = target.update_query_dict(
        {"options": f"-csearch_path={schema_name},public"}
    ).render_as_string(hide_password=False)
    engines = []
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=scoped_url, profile="test"
        )
        assert migration.applied[-1] == load_migrations("nex-ae-api")[-1].version

        work_intent = _work_intent()
        agent_context = _agent_context(work_intent)
        capability_snapshot = _snapshot(_runtime())
        values = {
            "work_intent": work_intent,
            "agent_context": agent_context,
            "capability_snapshot": capability_snapshot,
            "execution": {"execution_id": work_intent["execution_id"]},
        }

        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        _seed_lineage(
            sessions,
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
        )
        adapter = _ProtectedPreparationAdapter(work_intent)
        components = _components(sessions, work_intent=work_intent, adapter=adapter)

        business = components.coordinator.begin(**values)
        assert components.coordinator.begin(**values)["replayed"] is True
        before_cross_scope = _counts(sessions)
        with pytest.raises(M1ProductPreparationCoordinatorError):
            components.coordinator.accept_approval_notification(
                tenant_id="OTHER",
                checkpoint_id=business["checkpoint"]["checkpoint_id"],
                event_id="cross-scope-business",
                notification_ref="wc-event://cross-scope-business",
                authority_evidence_ref=ENVELOPE_ID,
                received_at=NOW_TEXT,
            )
        assert _counts(sessions) == before_cross_scope

        business_event = "cp-m1-01b6b4-business-approved"
        first_event = _notify(
            components,
            business["checkpoint"],
            event_id=business_event,
            evidence_ref=ENVELOPE_ID,
        )
        assert (
            _notify(
                components,
                business["checkpoint"],
                event_id=business_event,
                evidence_ref=ENVELOPE_ID,
            )
            == first_event
        )
        business_match = components.resume.reconcile(
            tenant_id=TENANT, event_id=business_event
        )
        restarted_match = _components(
            sessions, work_intent=work_intent, adapter=adapter
        ).resume.reconcile(tenant_id=TENANT, event_id=business_event)
        assert restarted_match == business_match

        restarted = _components(sessions, work_intent=work_intent, adapter=adapter)
        accounting = restarted.coordinator.resume_approval(
            event_id=business_event,
            runtime_job_id=business_match["resume_runtime_job_id"],
            **values,
        )
        business_ack_loss = restarted.coordinator.resume_approval(
            event_id=business_event,
            runtime_job_id=business_match["resume_runtime_job_id"],
            **values,
        )
        assert business_ack_loss["replayed"] is True
        assert business_ack_loss["checkpoint"] == accounting["checkpoint"]

        engine.dispose()
        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        restarted = _components(sessions, work_intent=work_intent, adapter=adapter)
        accounting_event = "cp-m1-01b6b4-accounting-approved"
        _notify(
            restarted,
            accounting["checkpoint"],
            event_id=accounting_event,
            evidence_ref=EVIDENCE_ID,
        )
        accounting_match = restarted.resume.reconcile(
            tenant_id=TENANT, event_id=accounting_event
        )
        assert (
            _components(
                sessions, work_intent=work_intent, adapter=adapter
            ).resume.reconcile(tenant_id=TENANT, event_id=accounting_event)
            == accounting_match
        )

        denied = _components(
            sessions,
            work_intent=work_intent,
            adapter=adapter,
            authority_source=_AuthoritySource(fail=True),
        )
        before_revocation = _counts(sessions)
        with pytest.raises(M1ProductPreparationCoordinatorError) as unavailable:
            denied.coordinator.resume_approval(
                event_id=accounting_event,
                runtime_job_id=accounting_match["resume_runtime_job_id"],
                **values,
            )
        assert unavailable.value.retryable is True
        assert _counts(sessions) == before_revocation

        restarted = _components(sessions, work_intent=work_intent, adapter=adapter)
        ready = restarted.coordinator.resume_approval(
            event_id=accounting_event,
            runtime_job_id=accounting_match["resume_runtime_job_id"],
            **values,
        )
        ready_ack_loss = restarted.coordinator.resume_approval(
            event_id=accounting_event,
            runtime_job_id=accounting_match["resume_runtime_job_id"],
            **values,
        )
        assert ready["ready"] is True
        assert ready_ack_loss["replayed"] is True
        assert ready_ack_loss["checkpoint"] == ready["checkpoint"]

        activation = _activation(
            sessions,
            coordinator=restarted.coordinator,
            registration=restarted.registration,
        )
        first_activation = activation.activate(**values)

        engine.dispose()
        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        final_components = _components(
            sessions, work_intent=work_intent, adapter=adapter
        )
        replayed_activation = _activation(
            sessions,
            coordinator=final_components.coordinator,
            registration=final_components.registration,
        ).activate(**values)
        assert (
            replayed_activation["activation_hash"]
            == first_activation["activation_hash"]
        )
        assert replayed_activation["runtime_job"] == first_activation["runtime_job"]
        assert replayed_activation["replayed"] == {
            "agent_plan": True,
            "validation": True,
            "executable_plan": True,
        }

        expected = {
            "checkpoints": 3,
            "waits": 2,
            "events": 2,
            "plans": 1,
            "validations": 1,
            "executable_plans": 1,
            "steps": 2,
            "jobs": 3,
        }
        assert _counts(sessions) == expected
        with sessions() as session:
            job_counts = dict(
                session.execute(
                    text(
                        "SELECT job_type, count(*) FROM ae_runtime_job "
                        "WHERE tenant_id = :tenant_id GROUP BY job_type"
                    ),
                    {"tenant_id": TENANT},
                ).all()
            )
        assert job_counts == {"RESUME_EXECUTION": 2, "START_EXECUTION": 1}

        with pytest.raises(M1ProductPreparationCoordinatorError, match="stale"):
            final_components.coordinator.resume_approval(
                event_id=business_event,
                runtime_job_id=business_match["resume_runtime_job_id"],
                **values,
            )
        with pytest.raises(ProductPreparationPersistenceError):
            _notify(
                final_components,
                accounting["checkpoint"],
                event_id=accounting_event,
                evidence_ref=ENVELOPE_ID,
            )
        assert _counts(sessions) == expected
    finally:
        for engine in engines:
            engine.dispose()
        with psycopg.connect(postgres_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)


def test_01b6b4_wall_clock_is_not_used_as_business_authority() -> None:
    assert AUTHORITY_NOW < NOW
