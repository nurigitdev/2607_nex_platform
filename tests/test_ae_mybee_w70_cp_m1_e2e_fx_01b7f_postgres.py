from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from nex_ae_api.approval_decision_event_api import (
    ApprovalDecisionEventError,
    EosProductApprovalReceiptAdmission,
)
from nex_ae_api.product_planning_runtime import InstalledProductPlanningEventAdmission
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
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b4_postgres import (
    _components,
    _seed_lineage,
)

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_AE_MYBEE_W70_CP_M1_01B7F_POSTGRES_SMOKE") == "1"
TENANT = "VO00"
OUTBOX_ID = "7f000000-0000-4000-8000-000000000001"
EVENT_ID = "7f000000-0000-4000-8000-000000000002"
WORK_ITEM_ID = "7f000000-0000-4000-8000-000000000003"
DECISION_ID = "7f000000-0000-4000-8000-000000000004"
ENVELOPE_ID = "7f000000-0000-4000-8000-000000000005"
DECIDED_AT = "2026-11-19T02:00:00Z"


class _EosClient:
    def __init__(self, case_id: str) -> None:
        self._case_id = case_id

    def ingest(self, _delivery):
        return {
            "schema_version": "eos_document_signoff_decision_receipt.v1",
            "created": True,
            "outbox_id": OUTBOX_ID,
            "event_id": EVENT_ID,
            "approval_domain": "BUSINESS_FORMAL",
            "purpose": "DOCUMENT_SIGNOFF",
            "case_id": self._case_id,
            "case_state": "APPROVED",
            "next_stage_publication": None,
            "document_signoff_evidence": {
                "evidence_id": "7f000000-0000-4000-8000-000000000006"
            },
            "approved_document_envelope": {"envelope_id": ENVELOPE_ID},
        }


class _Runtimes:
    def __init__(self, components) -> None:
        self._components = components

    def resolve_identity(self, **values):
        registration = self._components.registration
        assert values == {
            "coordinator_id": registration.coordinator_id,
            "coordinator_version": registration.coordinator_version,
            "coordinator_registration_hash": registration.registration_hash,
        }
        return SimpleNamespace(
            registration=registration,
            coordinator=self._components.coordinator,
        )


def _delivery(case_id: str, *, tenant_id: str = TENANT):
    return {
        "schema_version": "wc_approval_delivery.v1",
        "outbox_id": OUTBOX_ID,
        "work_item": {
            "tenant_id": tenant_id,
            "approval_work_item_id": WORK_ITEM_ID,
            "approval_domain": "BUSINESS_FORMAL",
            "resume_target_ref": f"eos.scoped-approval-case:{case_id}:stage:1",
        },
        "decision": {
            "tenant_id": tenant_id,
            "approval_work_item_id": WORK_ITEM_ID,
            "decision_id": DECISION_ID,
            "decision": "APPROVE",
            "decided_at": DECIDED_AT,
        },
        "event": {
            "tenant_id": tenant_id,
            "event_id": EVENT_ID,
            "approval_work_item_id": WORK_ITEM_ID,
            "decision_id": DECISION_ID,
            "occurred_at": DECIDED_AT,
        },
    }


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W70 CP-M1 01B.7F AE PostgreSQL smoke is disabled",
)
def test_actual_postgres_receipt_replay_restart_and_cross_tenant_zero_mutation():
    target = make_url(DATABASE_URL)
    assert (target.username, target.database) == ("nex_ae_user", "nex_ae_test")
    schema_name = f"mybee_w70_01b7f_{uuid.uuid4().hex}"
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
        components = _components(sessions, work_intent=work_intent)
        waiting = components.coordinator.begin(**values)
        case_id = next(
            item["authority_ref"]
            for item in waiting["checkpoint"]["authority_refs"]
            if item.get("authority_kind") == "BUSINESS_FORMAL"
        )
        event_admission = InstalledProductPlanningEventAdmission(
            runtimes=_Runtimes(components),
            resume_service=components.resume,
        )
        admission = EosProductApprovalReceiptAdmission(
            eos_client=_EosClient(case_id),
            wait_contexts=components.waits,
            product_events=event_admission,
        )

        first = admission.ingest(_delivery(case_id))
        engine.dispose()
        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        restarted = _components(sessions, work_intent=work_intent)
        replay = EosProductApprovalReceiptAdmission(
            eos_client=_EosClient(case_id),
            wait_contexts=restarted.waits,
            product_events=InstalledProductPlanningEventAdmission(
                runtimes=_Runtimes(restarted),
                resume_service=restarted.resume,
            ),
        ).ingest(_delivery(case_id))

        assert replay == first
        with sessions() as session:
            assert session.execute(
                text(
                    "SELECT state, matched_event_id, resume_runtime_job_id "
                    "FROM ae_wait_registration WHERE tenant_id=:tenant_id"
                ),
                {"tenant_id": TENANT},
            ).one().state == "RESUME_QUEUED"
            assert session.execute(
                text(
                    "SELECT count(*) FROM ae_external_event_inbox "
                    "WHERE tenant_id=:tenant_id"
                ),
                {"tenant_id": TENANT},
            ).scalar_one() == 1
            assert session.execute(
                text(
                    "SELECT count(*) FROM ae_runtime_job "
                    "WHERE tenant_id=:tenant_id AND job_type='RESUME_EXECUTION'"
                ),
                {"tenant_id": TENANT},
            ).scalar_one() == 1
        before = first["product_resume"]
        with pytest.raises(ApprovalDecisionEventError, match="No Product wait"):
            EosProductApprovalReceiptAdmission(
                eos_client=_EosClient(case_id),
                wait_contexts=restarted.waits,
                product_events=InstalledProductPlanningEventAdmission(
                    runtimes=_Runtimes(restarted),
                    resume_service=restarted.resume,
                ),
            ).ingest(_delivery(case_id, tenant_id="OTHER"))
        assert replay["product_resume"] == before
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
