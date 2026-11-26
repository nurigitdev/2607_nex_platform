from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from test_ae_mybee_w70_cp_m1_e2e_fx_01b5_plan_materialization import (
    _agent_context,
    _runtime,
    _snapshot,
    _work_intent,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b2_preparation_resume import (
    CANDIDATE_ID,
    ENVELOPE_ID,
    EVIDENCE_ID,
    TENANT,
    _preparation,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b4_postgres import (
    _components,
    _ProtectedPreparationAdapter,
    _seed_lineage,
)

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_AE_MYBEE_W80_CA00G6A_POSTGRES_SMOKE") == "1"
NOW = datetime(2026, 11, 26, 2, 0, tzinfo=UTC)


class _ReviewPreparationAdapter(_ProtectedPreparationAdapter):
    def begin_proposal(self, **values):
        self.calls.append(("PROPOSAL_DRAFT", None))
        return _preparation(
            "WAITING_PROPOSAL_REVIEW",
            values["business_context_hash"],
            {
                "proposal_id": "proposal-ca00g6a",
                "proposal_review_ref": "eos.business-proposal:proposal-ca00g6a",
            },
        )

    def continue_after_proposal_review(self, **values):
        self.calls.append(("PROPOSAL_SUBMIT", None))
        return _preparation(
            "WAITING_BUSINESS_APPROVAL",
            values["business_context_hash"],
            {"business_approval_case_id": "business-case-ca00g6a"},
        )

    def continue_after_business_approval(self, **values):
        self.calls.append(("BUSINESS_APPROVED", values["envelope_id"]))
        return _preparation(
            "WAITING_VOUCHER_REVIEW",
            values["business_context_hash"],
            {
                "approved_document_envelope_id": values["envelope_id"],
                "candidate_id": CANDIDATE_ID,
                "voucher_review_ref": f"eos.voucher-candidate:{CANDIDATE_ID}",
            },
        )

    def continue_after_voucher_review(self, **values):
        self.calls.append(("VOUCHER_SUBMIT", values["candidate_id"]))
        return _preparation(
            "WAITING_ACCOUNTING_APPROVAL",
            values["business_context_hash"],
            {
                "candidate_id": values["candidate_id"],
                "accounting_approval_case_id": "accounting-case-ca00g6a",
            },
        )


def _advance(sessions, components, values, checkpoint, *, event_id, evidence_ref):
    accepted = components.coordinator.accept_approval_notification(
        tenant_id=TENANT,
        checkpoint_id=checkpoint["checkpoint_id"],
        event_id=event_id,
        notification_ref=f"review-event:{event_id}",
        authority_evidence_ref=evidence_ref,
        received_at=NOW.isoformat().replace("+00:00", "Z"),
    )
    replayed = components.coordinator.accept_approval_notification(
        tenant_id=TENANT,
        checkpoint_id=checkpoint["checkpoint_id"],
        event_id=event_id,
        notification_ref=f"review-event:{event_id}",
        authority_evidence_ref=evidence_ref,
        received_at=NOW.isoformat().replace("+00:00", "Z"),
    )
    assert replayed["event"] == accepted["event"]
    matched = components.resume.reconcile(tenant_id=TENANT, event_id=event_id)
    restarted = _components(
        sessions,
        work_intent=values["work_intent"],
        adapter=components.adapter,
    )
    assert restarted.resume.reconcile(tenant_id=TENANT, event_id=event_id) == matched
    advanced = restarted.coordinator.resume_approval(
        event_id=event_id,
        runtime_job_id=matched["resume_runtime_job_id"],
        **values,
    )
    ack_loss = restarted.coordinator.resume_approval(
        event_id=event_id,
        runtime_job_id=matched["resume_runtime_job_id"],
        **values,
    )
    assert ack_loss["replayed"] is True
    assert ack_loss["checkpoint"] == advanced["checkpoint"]
    return restarted, advanced


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W80 CA00G.6A AE PostgreSQL smoke is disabled",
)
def test_actual_postgres_four_wait_review_restart_replay_and_ack_loss() -> None:
    target = make_url(DATABASE_URL)
    assert (target.username, target.database) == ("nex_ae_user", "nex_ae_test")
    schema_name = f"mybee_w80_ca00g6a_{uuid.uuid4().hex}"
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
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        _seed_lineage(
            sessions,
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
        )
        adapter = _ReviewPreparationAdapter(work_intent)
        components = _components(sessions, work_intent=work_intent, adapter=adapter)

        proposal = components.coordinator.begin(**values)
        assert proposal["checkpoint"]["stage"] == "WAITING_PROPOSAL_REVIEW"
        components, business = _advance(
            sessions,
            components,
            values,
            proposal["checkpoint"],
            event_id="ca00g6a-proposal-submitted",
            evidence_ref="eos.business-proposal:proposal-ca00g6a",
        )
        assert business["checkpoint"]["stage"] == "WAITING_BUSINESS_APPROVAL"
        components, voucher = _advance(
            sessions,
            components,
            values,
            business["checkpoint"],
            event_id="ca00g6a-business-approved",
            evidence_ref=ENVELOPE_ID,
        )
        assert voucher["checkpoint"]["stage"] == "WAITING_VOUCHER_REVIEW"
        components, accounting = _advance(
            sessions,
            components,
            values,
            voucher["checkpoint"],
            event_id="ca00g6a-voucher-submitted",
            evidence_ref=f"eos.voucher-candidate:{CANDIDATE_ID}",
        )
        assert accounting["checkpoint"]["stage"] == "WAITING_ACCOUNTING_APPROVAL"
        _components_after, ready = _advance(
            sessions,
            components,
            values,
            accounting["checkpoint"],
            event_id="ca00g6a-accounting-approved",
            evidence_ref=EVIDENCE_ID,
        )
        assert ready["checkpoint"]["stage"] == "READY_FOR_D04"
        assert [name for name, _value in adapter.calls] == [
            "PROPOSAL_DRAFT",
            "PROPOSAL_SUBMIT",
            "BUSINESS_APPROVED",
            "VOUCHER_SUBMIT",
            "ACCOUNTING",
        ]
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(postgres_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
