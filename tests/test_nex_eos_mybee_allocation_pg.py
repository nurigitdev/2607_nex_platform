from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import psycopg
import pytest
import test_nex_eos_mybee_cost_pool as source_fixture
from nex_eos import (
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_TABLE,
    EosAllocationReconciliationService,
    EosCostAllocationError,
    EosCostAllocationService,
    EosCostSourcePoolService,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosCostSourceFactsSource,
    SqlAlchemyEosCostSourcePoolRepository,
    cost_allocation_payload_hash,
    cost_allocations,
    parse_cost_allocation_run,
)
from nex_runtime import psycopg_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S6_03_POSTGRES_SMOKE") == "1"
PLAN_ID = "74000000-0000-4000-8000-000000000001"
BATCH_ID = "74000000-0000-4000-8000-000000000002"
OPERATION_ID = "74000000-0000-4000-8000-000000000003"
PROJECT_B = "74000000-0000-4000-8000-000000000004"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _allocation_payload(*, pool_id: str, period_id: str) -> dict:
    value = {
        "schema_version": "eos_cost_allocation_run.v1",
        "business_operation_id": OPERATION_ID,
        "idempotency_key": "w50-s6-03-concurrent-allocation",
        "payload_hash": "sha256:" + "0" * 64,
        "batch_id": BATCH_ID,
        "plan_id": PLAN_ID,
        "plan_revision": 1,
        "period_id": period_id,
        "functional_currency": "KRW",
        "currency_scale": 4,
        "sources": [
            {
                "pool_id": pool_id,
                "unallocated_amount_functional": "0.0000",
            }
        ],
    }
    command = parse_cost_allocation_run(
        tenant_id=source_fixture.posting_fixture.TENANT,
        company_id=source_fixture.posting_fixture.COMPANY_ID,
        payload=value,
    )
    value["payload_hash"] = cost_allocation_payload_hash(command)
    return value


def _seed_plan_and_second_project(sessions, *, source_kind: str) -> None:
    posting = source_fixture.posting_fixture
    with sessions.begin() as session:
        existing = (
            session.execute(
                select(EOS_PROJECT_TABLE).where(
                    EOS_PROJECT_TABLE.c.tenant_id == posting.TENANT,
                    EOS_PROJECT_TABLE.c.project_id == posting.PROJECT_ID,
                )
            )
            .mappings()
            .one()
        )
        project = dict(existing)
        project.update(
            project_id=PROJECT_B,
            project_code="VO00D260002",
            project_request_code="VO00R260002",
            name="W50 Allocation Target",
        )
        session.execute(EOS_PROJECT_TABLE.insert().values(**project))
        session.execute(
            EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                tenant_id=posting.TENANT,
                binding_id=str(uuid.uuid4()),
                project_id=PROJECT_B,
                company_id=posting.COMPANY_ID,
                valid_from=date(2026, 1, 1),
                valid_until=None,
                approved_proof_hash=posting.PROOF_HASH,
                state="APPROVED",
                version=1,
                created_at=posting.NOW,
                updated_at=posting.NOW,
            )
        )
        session.execute(
            EOS_COST_ALLOCATION_PLAN_TABLE.insert().values(
                tenant_id=posting.TENANT,
                company_id=posting.COMPANY_ID,
                plan_id=PLAN_ID,
                plan_revision=1,
                source_kind=source_kind,
                scope_type="PROJECT_SET",
                basis_kind="ACTUAL_WORK",
                rule_release_hash=HASH_A,
                basis_source_ref="eos.evidence:w50:actual-work",
                basis_source_hash=HASH_B,
                effective_start=date(2026, 11, 1),
                effective_end=date(2026, 11, 30),
                approved_by="employee-allocation-controller",
                approved_proof="eos.approval:w50-s6-03",
                state="APPROVED",
                plan_hash=HASH_C,
                created_at=posting.NOW,
            )
        )
        for line_no, project_id, project_code, ratio in (
            (1, posting.PROJECT_ID, posting.PROJECT_CODE, "0.500000000000"),
            (2, PROJECT_B, "VO00D260002", "0.500000000000"),
        ):
            session.execute(
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.insert().values(
                    tenant_id=posting.TENANT,
                    company_id=posting.COMPANY_ID,
                    plan_id=PLAN_ID,
                    plan_revision=1,
                    line_no=line_no,
                    project_id=project_id,
                    project_code=project_code,
                    work_code=None,
                    basis_units=Decimal("1.00000000"),
                    allocation_ratio=Decimal(ratio),
                    eligibility_hash=HASH_A,
                    confidentiality_class="INTERNAL",
                    line_hash=semantic_sha256_hash_ref(
                        {"line_no": line_no, "project_id": project_id}
                    ),
                )
            )


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S6-03 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_atomic_rollback_and_twenty_way_exact_replay(monkeypatch):
    schema_name = f"mybee_s603_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_eos_test", "nex_eos_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    engine = None
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2541_eos_cost_source_allocation" in migration.applied
        engine = create_engine(scoped_url, pool_pre_ping=True, pool_size=24)
        posting = source_fixture.posting_fixture
        _engine, sessions, candidates, command, _authorization = posting._runtime(
            engine=engine
        )
        with sessions.begin() as session:
            session.execute(
                EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                    tenant_id=posting.TENANT,
                    binding_id=str(uuid.uuid4()),
                    project_id=posting.PROJECT_ID,
                    company_id=posting.COMPANY_ID,
                    valid_from=date(2026, 1, 1),
                    valid_until=None,
                    approved_proof_hash=posting.PROOF_HASH,
                    state="APPROVED",
                    version=1,
                    created_at=posting.NOW,
                    updated_at=posting.NOW,
                )
            )
        command.execute(posting._payload(), caller=posting.CALLER)
        posting_service, post_payload = posting._prepare_atomic_posting(
            sessions, candidates
        )
        committed = posting_service.execute(posting.CANDIDATE_ID, post_payload)
        source_service = EosCostSourcePoolService(
            source=SqlAlchemyEosCostSourceFactsSource(sessions),
            repository=SqlAlchemyEosCostSourcePoolRepository(sessions),
            clock=lambda: posting.NOW,
        )
        source_pool = source_service.admit(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            journal_id=committed["result"]["journal_id"],
            journal_line_no=1,
            payload=source_fixture._payload(
                source_kind="SERVICE",
                allocation_mode="MANAGEMENT_ALLOCATION",
            ),
        )
        _seed_plan_and_second_project(sessions, source_kind="SERVICE")
        coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
            sessions,
            id_factory=lambda: str(uuid.uuid4()),
            clock=lambda: posting.NOW,
        )
        allocation = EosCostAllocationService(
            session_factory=sessions,
            coordinator=coordinator,
            clock=lambda: posting.NOW,
        )
        payload = _allocation_payload(
            pool_id=source_pool["pool_id"],
            period_id="32000000-0000-4000-8000-000000000021",
        )

        original_line_record = cost_allocations._allocation_line_record

        def corrupt_second_line(**kwargs):
            record = original_line_record(**kwargs)
            if kwargs["line_no"] == 2:
                record["project_code"] = "PROJECT-CODE-TOO-LONG"
            return record

        monkeypatch.setattr(
            cost_allocations, "_allocation_line_record", corrupt_second_line
        )
        with pytest.raises(EosCostAllocationError) as rolled_back:
            allocation.run(
                tenant_id=posting.TENANT,
                company_id=posting.COMPANY_ID,
                payload=payload,
            )
        assert rolled_back.value.status_code == 500
        assert rolled_back.value.error_code == "EOS_BUSINESS_MUTATION_FAILED"
        with sessions() as session:
            for table in (
                EOS_COST_ALLOCATION_BATCH_TABLE,
                EOS_COST_ALLOCATION_LINE_TABLE,
            ):
                assert (
                    session.execute(
                        select(func.count()).select_from(table)
                    ).scalar_one()
                    == 0
                )
            assert (
                session.execute(
                    select(EOS_COST_SOURCE_POOL_TABLE.c.pool_state).where(
                        EOS_COST_SOURCE_POOL_TABLE.c.pool_id == source_pool["pool_id"]
                    )
                ).scalar_one()
                == "OPEN"
            )

        monkeypatch.setattr(
            cost_allocations, "_allocation_line_record", original_line_record
        )

        def execute_once(_index: int):
            return allocation.run(
                tenant_id=posting.TENANT,
                company_id=posting.COMPANY_ID,
                payload=payload,
            )

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(execute_once, range(20)))
        assert [item["idempotency_disposition"] for item in results].count(
            "CREATED"
        ) == 1
        assert [item["idempotency_disposition"] for item in results].count(
            "EXACT_REPLAY"
        ) == 19
        assert len({item["reconciliation_hash"] for item in results}) == 1
        verified = EosAllocationReconciliationService(sessions).verify_batch(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            batch_id=BATCH_ID,
        )
        assert verified["verification_status"] == "VERIFIED"
        assert verified["batch"]["line_count"] == 2
        assert verified["conservation"][0]["unallocated_amount_functional"] == (
            "0.0000"
        )
        with sessions() as session:
            assert (
                session.execute(
                    select(func.count()).select_from(EOS_COST_ALLOCATION_BATCH_TABLE)
                ).scalar_one()
                == 1
            )
            assert (
                session.execute(
                    select(func.count()).select_from(EOS_COST_ALLOCATION_LINE_TABLE)
                ).scalar_one()
                == 2
            )
            assert (
                session.execute(
                    select(func.count())
                    .select_from(EOS_OUTBOX_TABLE)
                    .where(
                        EOS_OUTBOX_TABLE.c.event_type
                        == "FINANCE.COST_ALLOCATION_COMMITTED.v1"
                    )
                ).scalar_one()
                == 1
            )
        engine.dispose()
        engine = None
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
