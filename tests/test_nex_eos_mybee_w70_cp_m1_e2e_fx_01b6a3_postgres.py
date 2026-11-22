from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
import pytest
import test_nex_eos_mybee_allocation_pg as allocation_fixture
import test_nex_eos_mybee_cost_pool as source_fixture
from fastapi.testclient import TestClient
from mybee_ax.integrations import (
    NexProjectPnlRefreshClient,
    ProjectPnlRefreshConsumerError,
    ProjectPnlRefreshProviderRequest,
)
from nex_eos import (
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_PNL_COMPONENT_TABLE,
    EOS_PROJECT_PNL_PROJECTION_TABLE,
    EosAllocationReconciliationService,
    EosCostAllocationService,
    EosCostSourcePoolService,
    ProjectPnlRebuildRequest,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosCostSourceFactsSource,
    SqlAlchemyEosCostSourcePoolRepository,
)
from nex_eos.app import create_eos_app
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import func, make_url, select, update

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = (
    os.getenv("NEX_EOS_MYBEE_W70_CP_M1_01B6A3_POSTGRES_SMOKE") == "1"
)


class _ProtectedApiTransport:
    def __init__(self, client: TestClient, token: str) -> None:
        self._client = client
        self._token = token

    def send(self, request: ProjectPnlRefreshProviderRequest) -> Mapping[str, Any]:
        response = self._client.request(
            request.method,
            request.path,
            headers={
                "Authorization": f"Bearer {self._token}",
                "X-NeX-Tenant-Id": request.tenant_id,
                "X-NeX-Company-Id": request.company_id,
                "X-NeX-Correlation-Id": request.correlation_id,
            },
        )
        value = response.json()
        if response.status_code >= 400:
            raise ProjectPnlRefreshConsumerError(
                str(value.get("error_code", "EOS_PROJECT_PNL_REFRESH_REJECTED")),
                str(value.get("detail", "EOS rejected allocation-to-P&L refresh")),
                status_code=response.status_code,
                retryable=bool(value.get("retryable", response.status_code >= 500)),
            )
        assert isinstance(value, dict)
        return value


def _runtime(scoped_url: str):
    app = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_VERSION": "w70-cp-m1-01b6a3",
            "NEX_BUILD_SHA": "protected-postgres",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            "NEX_EOS_DATABASE_URL": scoped_url,
            "NEX_EOS_TO_OA_SERVICE_TOKEN": "protected-smoke-oa-token",
        }
    )
    assert app.state.eos_project_pnl_refresh_service is not None
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    http = TestClient(app)
    consumer = NexProjectPnlRefreshClient(
        _ProtectedApiTransport(http, issued.access_token)
    )
    return app, http, consumer


def _seed_verified_allocation(app) -> tuple[Any, Mapping[str, Any]]:
    runtime = app.state.eos_database_runtime
    posting = source_fixture.posting_fixture
    _engine, sessions, candidates, command, _authorization = posting._runtime(
        engine=runtime.engine
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
    posting_service, posting_payload = posting._prepare_atomic_posting(
        sessions, candidates
    )
    committed = posting_service.execute(posting.CANDIDATE_ID, posting_payload)
    source_pool = EosCostSourcePoolService(
        source=SqlAlchemyEosCostSourceFactsSource(sessions),
        repository=SqlAlchemyEosCostSourcePoolRepository(sessions),
        clock=lambda: posting.NOW,
    ).admit(
        tenant_id=posting.TENANT,
        company_id=posting.COMPANY_ID,
        journal_id=committed["result"]["journal_id"],
        journal_line_no=1,
        payload=source_fixture._payload(
            source_kind="SERVICE", allocation_mode="MANAGEMENT_ALLOCATION"
        ),
    )
    allocation_fixture._seed_plan_and_second_project(sessions, source_kind="SERVICE")
    allocation_clock = datetime.fromisoformat(
        str(source_pool["recognized_at"]).replace("Z", "+00:00")
    ) + timedelta(minutes=1)
    allocation = EosCostAllocationService(
        session_factory=sessions,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            sessions,
            id_factory=lambda: str(uuid.uuid4()),
            clock=lambda: allocation_clock,
        ),
        clock=lambda: allocation_clock,
    ).run(
        tenant_id=posting.TENANT,
        company_id=posting.COMPANY_ID,
        payload=allocation_fixture._allocation_payload(
            pool_id=source_pool["pool_id"],
            period_id="32000000-0000-4000-8000-000000000021",
        ),
    )
    verification = EosAllocationReconciliationService(sessions).verify_batch(
        tenant_id=posting.TENANT,
        company_id=posting.COMPANY_ID,
        batch_id=allocation_fixture.BATCH_ID,
    )
    assert verification["verification_status"] == "VERIFIED"
    assert verification["batch"]["line_count"] == 2
    return sessions, allocation


def _refresh(consumer: NexProjectPnlRefreshClient, *, tenant=None, company=None):
    posting = source_fixture.posting_fixture
    return consumer.refresh(
        tenant_id=tenant or posting.TENANT,
        company_id=company or posting.COMPANY_ID,
        batch_id=allocation_fixture.BATCH_ID,
        correlation_id=f"protected-refresh:{uuid.uuid4()}",
    )


def _counts(sessions) -> dict[str, int]:
    tables = {
        "pool": EOS_COST_SOURCE_POOL_TABLE,
        "batch": EOS_COST_ALLOCATION_BATCH_TABLE,
        "allocation_line": EOS_COST_ALLOCATION_LINE_TABLE,
        "projection": EOS_PROJECT_PNL_PROJECTION_TABLE,
        "component": EOS_PROJECT_PNL_COMPONENT_TABLE,
        "outbox": EOS_OUTBOX_TABLE,
    }
    with sessions() as session:
        return {
            name: int(session.scalar(select(func.count()).select_from(table)) or 0)
            for name, table in tables.items()
        }


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W70 CP-M1 P&L refresh PostgreSQL smoke is disabled",
)
def test_actual_postgres_strict_refresh_concurrency_restart_and_zero_mutation():
    target = make_url(DATABASE_URL)
    assert (target.username, target.database) == ("nex_eos_user", "nex_eos_test")
    schema_name = f"mybee_w70_01b6a3_{uuid.uuid4().hex}"
    postgres_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(postgres_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_eos_test", "nex_eos_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = (
        target.update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    apps = []
    clients = []
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert migration.applied[-1] == load_migrations("nex-eos")[-1].version

        app_one, http_one, consumer_one = _runtime(scoped_url)
        app_two, http_two, consumer_two = _runtime(scoped_url)
        apps.extend((app_one, app_two))
        clients.extend((http_one, http_two))
        sessions, allocation = _seed_verified_allocation(app_one)
        assert allocation["reconciliation_hash"].startswith("sha256:")
        authoritative_before = _counts(sessions)
        assert authoritative_before == {
            "pool": 1,
            "batch": 1,
            "allocation_line": 2,
            "projection": 0,
            "component": 0,
            "outbox": 3,
        }
        source = app_one.state.eos_project_pnl_refresh_source_resolver.resolve(
            tenant_id=source_fixture.posting_fixture.TENANT,
            company_id=source_fixture.posting_fixture.COMPANY_ID,
            batch_id=allocation_fixture.BATCH_ID,
        )
        for project in source.affected_projects:
            app_one.state.eos_project_pnl_projector.preview(
                ProjectPnlRebuildRequest(
                    tenant_id=source.tenant_id,
                    company_id=source.company_id,
                    project_id=project.project_id,
                    project_code=project.project_code,
                    period_id=source.period_id,
                    projection_version=1,
                    functional_currency=source.functional_currency,
                    as_of=source.committed_at,
                    evaluated_at=source.committed_at,
                )
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent = list(
                executor.map(
                    lambda consumer: _refresh(consumer),
                    (consumer_one, consumer_two),
                )
            )
        assert len({result["refresh_hash"] for result in concurrent}) == 1
        assert len(
            {
                tuple(item["projection_hash"] for item in result["projections"])
                for result in concurrent
            }
        ) == 1
        assert {result["disposition"] for result in concurrent} <= {
            "CREATED",
            "EXACT_REPLAY",
        }
        assert all(len(result["projections"]) == 2 for result in concurrent)

        replay = _refresh(consumer_one)
        assert replay["disposition"] == "EXACT_REPLAY"
        assert replay["refresh_hash"] == concurrent[0]["refresh_hash"]
        after_refresh = _counts(sessions)
        assert after_refresh["projection"] == 2
        assert after_refresh["component"] > 0
        for immutable in ("pool", "batch", "allocation_line", "outbox"):
            assert after_refresh[immutable] == authoritative_before[immutable]

        for tenant, company in (
            ("OTHER", source_fixture.posting_fixture.COMPANY_ID),
            (
                source_fixture.posting_fixture.TENANT,
                "71000000-0000-4000-8000-000000000099",
            ),
        ):
            with pytest.raises(ProjectPnlRefreshConsumerError) as denied:
                _refresh(consumer_one, tenant=tenant, company=company)
            assert denied.value.status_code == 404
            assert denied.value.error_code == "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_FOUND"
        assert _counts(sessions) == after_refresh

        for client in clients:
            client.close()
        clients.clear()
        for app in apps:
            app.state.eos_database_runtime.dispose()
        apps.clear()

        restarted_app, restarted_http, restarted_consumer = _runtime(scoped_url)
        apps.append(restarted_app)
        clients.append(restarted_http)
        restarted = _refresh(restarted_consumer)
        assert restarted["disposition"] == "EXACT_REPLAY"
        assert restarted["refresh_hash"] == replay["refresh_hash"]
        restarted_sessions = restarted_app.state.eos_database_runtime.session_factory
        assert _counts(restarted_sessions) == after_refresh

        with restarted_sessions.begin() as session:
            session.execute(
                update(EOS_COST_ALLOCATION_BATCH_TABLE)
                .where(
                    EOS_COST_ALLOCATION_BATCH_TABLE.c.tenant_id
                    == source_fixture.posting_fixture.TENANT,
                    EOS_COST_ALLOCATION_BATCH_TABLE.c.company_id
                    == source_fixture.posting_fixture.COMPANY_ID,
                    EOS_COST_ALLOCATION_BATCH_TABLE.c.batch_id
                    == allocation_fixture.BATCH_ID,
                )
                .values(state="REVERSED")
            )
        reversed_counts = _counts(restarted_sessions)
        with pytest.raises(ProjectPnlRefreshConsumerError) as reversed_batch:
            _refresh(restarted_consumer)
        assert reversed_batch.value.status_code == 409
        assert (
            reversed_batch.value.error_code
            == "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_VERIFIED"
        )
        assert _counts(restarted_sessions) == reversed_counts
    finally:
        for client in clients:
            client.close()
        for app in apps:
            app.state.eos_database_runtime.dispose()
        with psycopg.connect(postgres_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
