from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.product_planning_runtime import (
    InstalledProductCoordinatorAssignmentHandler,
    InstalledProductCoordinatorRuntime,
    SqlAlchemyProductPlanningLineageSource,
)
from nex_ae_api.runtime_resume import SqlAlchemyResumeRouteSource
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from test_ae_mybee_w70_cp_m1_e2e_fx_01b5_plan_materialization import (
    _agent_context,
    _runtime,
    _snapshot,
    _work_intent,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b2_preparation_resume import (
    ENVELOPE_ID,
    EVIDENCE_ID,
    TENANT,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b4_postgres import (
    NOW,
    NOW_TEXT,
    _activation,
    _components,
    _notify,
    _seed_lineage,
)

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = (
    os.getenv("NEX_AE_MYBEE_W70_CP_M1_01B7H_POSTGRES_SMOKE") == "1"
)


class _SingleRuntimeRegistry:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def resolve_route(self, route):
        assert route.resume_target_kind == "PRODUCT_COORDINATOR"
        return self.runtime


def _handler(*, sessions, components, work_intent, observed_at):
    registration = components.registration
    runtime = InstalledProductCoordinatorRuntime(
        registration=registration,
        coordinator=components.coordinator,
        activation=_activation(
            sessions,
            coordinator=components.coordinator,
            registration=registration,
        ),
    )
    return InstalledProductCoordinatorAssignmentHandler(
        route_source=SqlAlchemyResumeRouteSource(sessions),
        lineage_source=SqlAlchemyProductPlanningLineageSource(sessions),
        runtimes=_SingleRuntimeRegistry(runtime),
        runtime_jobs=components.jobs,
        clock=lambda: observed_at,
    )


def _claim_product_job(components, *, observed_at):
    claim = components.jobs.claim(
        tenant_id=TENANT,
        worker_id="ae-product-worker-01b7h",
        lease_seconds=600,
        now=observed_at.isoformat().replace("+00:00", "Z"),
    )
    assert claim is not None
    return AgentRuntimeAssignment(
        tenant_id=TENANT,
        executor_kind=None,
        backend_profile=None,
        assignment_kind="PRODUCT_COORDINATOR",
        claim=replace(claim, assignment_kind="PRODUCT_COORDINATOR"),
    )


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W70 CP-M1 01B.7H AE PostgreSQL smoke is disabled",
)
def test_actual_postgres_product_resume_jobs_settle_before_plan_execution():
    target = make_url(DATABASE_URL)
    assert (target.username, target.database) == ("nex_ae_user", "nex_ae_test")
    schema_name = f"mybee_w70_01b7h_{uuid.uuid4().hex}"
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
    engine = None
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=scoped_url, profile="test"
        )
        assert migration.applied[-1] == load_migrations("nex-ae-api")[-1].version
        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        work_intent = _work_intent()
        agent_context = _agent_context(work_intent)
        capability_snapshot = _snapshot(_runtime())
        _seed_lineage(
            sessions,
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
        )
        with sessions.begin() as session:
            session.execute(
                text(
                    "UPDATE ae_agent_context SET context_json = CAST(:context_json AS JSONB) "
                    "WHERE tenant_id = :tenant_id AND context_id = :context_id"
                ),
                {
                    "tenant_id": TENANT,
                    "context_id": agent_context["context_id"],
                    "context_json": json.dumps(agent_context, sort_keys=True),
                },
            )
        components = _components(sessions, work_intent=work_intent)
        values = {
            "work_intent": work_intent,
            "agent_context": agent_context,
            "capability_snapshot": capability_snapshot,
            "execution": {"execution_id": work_intent["execution_id"]},
        }

        business = components.coordinator.begin(**values)
        business_event = "cp-m1-01b7h-business-approved"
        _notify(
            components,
            business["checkpoint"],
            event_id=business_event,
            evidence_ref=ENVELOPE_ID,
        )
        business_match = components.resume.reconcile(
            tenant_id=TENANT, event_id=business_event
        )
        business_assignment = _claim_product_job(components, observed_at=NOW)
        business_result = _handler(
            sessions=sessions,
            components=components,
            work_intent=work_intent,
            observed_at=NOW + timedelta(minutes=1),
        )(business_assignment)
        assert business_result["stage"] == "WAITING_ACCOUNTING_APPROVAL"
        assert business_result["runtime_job_state"] == "DONE"
        business_job_id = business_match["resume_runtime_job_id"]
        assert components.jobs.get(TENANT, business_job_id)["state"] == "DONE"
        assert components.jobs.list_attempts(TENANT, business_job_id)[0][
            "outcome"
        ] == "DONE"

        accounting_event = "cp-m1-01b7h-accounting-approved"
        _notify(
            components,
            {"checkpoint_id": business_result["checkpoint_id"]},
            event_id=accounting_event,
            evidence_ref=EVIDENCE_ID,
        )
        accounting_match = components.resume.reconcile(
            tenant_id=TENANT, event_id=accounting_event
        )
        accounting_assignment = _claim_product_job(
            components, observed_at=NOW + timedelta(minutes=2)
        )
        accounting_result = _handler(
            sessions=sessions,
            components=components,
            work_intent=work_intent,
            observed_at=NOW + timedelta(minutes=3),
        )(accounting_assignment)
        assert accounting_result["stage"] == "READY_FOR_D04"
        assert accounting_result["runtime_job_state"] == "DONE"
        accounting_job_id = accounting_match["resume_runtime_job_id"]
        assert components.jobs.get(TENANT, accounting_job_id)["state"] == "DONE"
        assert components.jobs.list_attempts(TENANT, accounting_job_id)[0][
            "outcome"
        ] == "DONE"
        assert accounting_result["activation"]["runtime_job"]["state"] == "QUEUED"
    finally:
        if engine is not None:
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


def test_01b7h_uses_timezone_aware_runtime_settlement_clock() -> None:
    assert NOW == datetime(2026, 11, 18, 1, 0, tzinfo=UTC)
    assert NOW_TEXT == "2026-11-18T01:00:00Z"
