from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from mybee_ax.integrations import (
    AllocationPlanConsumerError,
    AllocationPlanProviderRequest,
    NexAllocationPlanResolverClient,
)
from nex_eos import (
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_TABLE,
    allocation_plans,
)
from nex_eos.app import create_eos_app
from nex_runtime import issue_mock_service_token, psycopg_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import func, make_url, select

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = (
    os.getenv("NEX_EOS_MYBEE_W70_CP_M1_01B5A3_POSTGRES_SMOKE") == "1"
)

TENANT_ID = "G301"
CROSS_TENANT_ID = "G302"
COMPANY_ID = "83000000-0000-4000-8000-000000000001"
CROSS_COMPANY_ID = "83000000-0000-4000-8000-000000000002"
PROJECTS = (
    {
        "project_id": "83000000-0000-4000-8000-000000000011",
        "project_code": "G301D260001",
        "allocation_ratio": "0.200000000000",
    },
    {
        "project_id": "83000000-0000-4000-8000-000000000012",
        "project_code": "G301M260002",
        "allocation_ratio": "0.300000000000",
    },
    {
        "project_id": "83000000-0000-4000-8000-000000000013",
        "project_code": "G301S260003",
        "allocation_ratio": "0.500000000000",
    },
)
EFFECTIVE_ON = "2026-11-15"
NOW = datetime(2026, 11, 16, 3, 0, tzinfo=UTC)


class _ProtectedApiTransport:
    def __init__(self, client: TestClient, token: str) -> None:
        self._client = client
        self._token = token

    def send(self, request: AllocationPlanProviderRequest) -> Mapping[str, Any]:
        response = self._client.request(
            request.method,
            request.path,
            headers={
                "Authorization": f"Bearer {self._token}",
                "X-NeX-Tenant-Id": request.tenant_id,
                "X-NeX-Company-Id": request.company_id,
                "X-NeX-Correlation-Id": request.correlation_id,
            },
            json=dict(request.body),
        )
        value = response.json()
        if response.status_code >= 400:
            raise AllocationPlanConsumerError(
                str(value.get("error_code", "EOS_ALLOCATION_PLAN_REJECTED")),
                str(value.get("detail", "EOS rejected allocation-plan resolution")),
                status_code=response.status_code,
                retryable=bool(value.get("retryable", response.status_code >= 500)),
            )
        assert isinstance(value, dict)
        return value


def _runtime(scoped_url: str):
    app = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_VERSION": "w70-cp-m1-01b5a3",
            "NEX_BUILD_SHA": "protected-postgres",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            "NEX_EOS_DATABASE_URL": scoped_url,
            "NEX_EOS_TO_OA_SERVICE_TOKEN": "protected-smoke-oa-token",
        }
    )
    assert app.state.eos_allocation_plan_service is not None
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    client = TestClient(app)
    resolver = NexAllocationPlanResolverClient(
        _ProtectedApiTransport(client, issued.access_token)
    )
    return app, client, resolver


def _seed_scope(session_factory) -> None:
    with session_factory.begin() as session:
        nvt_project_id = "83000000-0000-4000-8000-000000000010"
        session.execute(
            EOS_NVT_PROJECT_TABLE.insert().values(
                tenant_id=TENANT_ID,
                nvt_project_id=nvt_project_id,
                nvt_project_code="G301-NVT-PROTECTED",
                name="Protected Resolution NVT",
                status="ACTIVE",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_LEGAL_ENTITY_TABLE.insert().values(
                tenant_id=TENANT_ID,
                company_id=COMPANY_ID,
                company_code="G301",
                name="Protected Resolution Company",
                functional_currency="KRW",
                presentation_currency="KRW",
                business_timezone="Asia/Seoul",
                status="ACTIVE",
                effective_from=date(2026, 1, 1),
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for index, project in enumerate(PROJECTS, 1):
            session.execute(
                EOS_PROJECT_TABLE.insert().values(
                    tenant_id=TENANT_ID,
                    project_id=project["project_id"],
                    project_code=project["project_code"],
                    project_request_code=f"G301R26{index:04d}",
                    purpose_type=project["project_code"][4],
                    origin="APPROVED_APPLICATION",
                    approval_evidence_ref=f"eos.approval:project:{index}",
                    approval_evidence_hash=_hash(f"project-approval:{index}"),
                    project_owner_subject_id=f"employee-owner-{index}",
                    project_manager_subject_id=f"employee-pm-{index}",
                    agent_sync_state="IN_SYNC",
                    authorization_sync_state="IN_SYNC",
                    authorization_version=1,
                    name=f"Protected Project {index}",
                    parent_project_id=None,
                    nvt_project_id=nvt_project_id,
                    hierarchy_depth=1,
                    status="ACTIVE",
                    start_date=date(2026, 1, 1),
                    end_date=None,
                    currency="KRW",
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.execute(
                EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                    tenant_id=TENANT_ID,
                    binding_id=str(uuid.uuid4()),
                    project_id=project["project_id"],
                    company_id=COMPANY_ID,
                    valid_from=date(2026, 1, 1),
                    valid_until=None,
                    approved_proof_hash=_hash(f"binding:{index}"),
                    state="APPROVED",
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


def _seed_approved_plan(
    session_factory,
    *,
    plan_id: str,
    ratios: Sequence[str],
    effective_start: str,
    effective_end: str,
    created_at: datetime,
) -> dict[str, Any]:
    proof_id = str(uuid.uuid4())
    payload = {
        "schema_version": "eos_cost_allocation_plan_release.v1",
        "approval_proof_id": proof_id,
        "plan": {
            "plan_id": plan_id,
            "plan_revision": 1,
            "source_kind": "SERVICE",
            "scope_type": "PROJECT_SET",
            "basis_kind": "APPROVED_PLAN",
            "rule_release_hash": _hash(f"rule:{plan_id}"),
            "basis_source_ref": f"eos.evidence:protected:{plan_id}",
            "basis_source_hash": _hash(f"basis:{plan_id}"),
            "effective_start": effective_start,
            "effective_end": effective_end,
            "lines": [
                {
                    "line_no": index,
                    "project_id": project["project_id"],
                    "project_code": project["project_code"],
                    "work_code": None,
                    "basis_units": f"{index}.00000000",
                    "allocation_ratio": ratio,
                    "eligibility_hash": _hash(f"eligibility:{plan_id}:{index}"),
                    "confidentiality_class": "INTERNAL",
                }
                for index, (project, ratio) in enumerate(
                    zip(PROJECTS, ratios, strict=True), 1
                )
            ],
        },
    }
    _, candidate = allocation_plans._admit_release(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        payload=payload,
    )
    plan_record = {
        key: candidate[key]
        for key in (
            "tenant_id",
            "company_id",
            "plan_id",
            "plan_revision",
            "source_kind",
            "scope_type",
            "basis_kind",
            "rule_release_hash",
            "basis_source_ref",
            "basis_source_hash",
            "effective_start",
            "effective_end",
            "plan_hash",
        )
    }
    plan_record.update(
        approved_by="employee-protected-approver",
        approved_proof=f"eos.approval-proof:{proof_id}",
        state="APPROVED",
        created_at=created_at,
    )
    line_records = [
        {
            "tenant_id": TENANT_ID,
            "company_id": COMPANY_ID,
            "plan_id": plan_id,
            "plan_revision": 1,
            **line,
        }
        for line in candidate["lines"]
    ]
    with session_factory.begin() as session:
        session.execute(EOS_COST_ALLOCATION_PLAN_TABLE.insert().values(**plan_record))
        session.execute(EOS_COST_ALLOCATION_PLAN_LINE_TABLE.insert(), line_records)
    return candidate


def _counts(session_factory) -> tuple[int, int]:
    with session_factory() as session:
        return (
            int(
                session.scalar(
                    select(func.count()).select_from(EOS_COST_ALLOCATION_PLAN_TABLE)
                )
                or 0
            ),
            int(
                session.scalar(
                    select(func.count()).select_from(
                        EOS_COST_ALLOCATION_PLAN_LINE_TABLE
                    )
                )
                or 0
            ),
        )


def _resolve(
    resolver: NexAllocationPlanResolverClient,
    *,
    tenant_id: str = TENANT_ID,
    company_id: str = COMPANY_ID,
    effective_on: str = EFFECTIVE_ON,
    projects: Sequence[Mapping[str, Any]] = PROJECTS,
) -> Mapping[str, Any]:
    return resolver.resolve(
        tenant_id=tenant_id,
        company_id=company_id,
        source_kind="SERVICE",
        effective_on=effective_on,
        projects=projects,
        correlation_id=f"protected:{uuid.uuid4()}",
    )


def _assert_not_resolved(resolver: NexAllocationPlanResolverClient, **values) -> None:
    with pytest.raises(AllocationPlanConsumerError) as error:
        _resolve(resolver, **values)
    assert error.value.status_code == 404
    assert error.value.error_code == "EOS_COST_ALLOCATION_PLAN_NOT_RESOLVED"
    assert error.value.retryable is False


def _hash(value: str) -> str:
    return semantic_sha256_hash_ref({"protected_resolution_evidence": value})


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W70 CP-M1 allocation resolution PostgreSQL smoke is disabled",
)
def test_actual_postgres_protected_resolution_restart_and_isolation_gate() -> None:
    target = make_url(DATABASE_URL)
    assert (target.username, target.database) == ("nex_eos_user", "nex_eos_test")
    schema_name = f"mybee_w70_01b5a3_{uuid.uuid4().hex}"
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
    app_one = None
    app_two = None
    client_one = None
    client_two = None
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        migration_head = load_migrations("nex-eos")[-1].version
        assert migration.applied[-1] == migration_head

        app_one, client_one, resolver_one = _runtime(scoped_url)
        session_factory = app_one.state.eos_database_runtime.session_factory
        _seed_scope(session_factory)
        primary = _seed_approved_plan(
            session_factory,
            plan_id="83000000-0000-4000-8000-000000000101",
            ratios=("0.200000000000", "0.300000000000", "0.500000000000"),
            effective_start="2026-11-01",
            effective_end="2026-11-30",
            created_at=NOW,
        )
        _seed_approved_plan(
            session_factory,
            plan_id="83000000-0000-4000-8000-000000000102",
            ratios=("0.210000000000", "0.290000000000", "0.500000000000"),
            effective_start="2026-11-01",
            effective_end="2026-11-30",
            created_at=NOW + timedelta(hours=1),
        )
        _seed_approved_plan(
            session_factory,
            plan_id="83000000-0000-4000-8000-000000000103",
            ratios=("0.200000000000", "0.300000000000", "0.500000000000"),
            effective_start="2026-10-01",
            effective_end="2026-10-31",
            created_at=NOW + timedelta(hours=2),
        )
        seeded_counts = _counts(session_factory)
        assert seeded_counts == (3, 9)

        first = _resolve(resolver_one)
        replay = _resolve(resolver_one)
        assert first == replay
        assert first["plan_id"] == primary["plan_id"]
        assert first["plan_hash"] == primary["plan_hash"]
        assert _counts(session_factory) == seeded_counts

        _assert_not_resolved(resolver_one, effective_on="2026-09-30")
        _assert_not_resolved(resolver_one, effective_on="2026-12-01")
        _assert_not_resolved(resolver_one, tenant_id=CROSS_TENANT_ID)
        _assert_not_resolved(resolver_one, company_id=CROSS_COMPANY_ID)
        drifted = [dict(project) for project in PROJECTS]
        drifted[0]["allocation_ratio"] = "0.220000000000"
        drifted[1]["allocation_ratio"] = "0.280000000000"
        _assert_not_resolved(resolver_one, projects=drifted)
        mismatched = [dict(project) for project in PROJECTS]
        mismatched[0]["project_id"] = str(uuid.uuid4())
        _assert_not_resolved(resolver_one, projects=mismatched)
        assert _counts(session_factory) == seeded_counts

        client_one.close()
        client_one = None
        app_one.state.eos_database_runtime.dispose()
        app_one = None

        app_two, client_two, resolver_two = _runtime(scoped_url)
        restarted = _resolve(resolver_two)
        assert restarted == first
        assert restarted["resolution_hash"] == first["resolution_hash"]
        restarted_sessions = app_two.state.eos_database_runtime.session_factory
        assert _counts(restarted_sessions) == seeded_counts

        _seed_approved_plan(
            restarted_sessions,
            plan_id="83000000-0000-4000-8000-000000000104",
            ratios=("0.200000000000", "0.300000000000", "0.500000000000"),
            effective_start="2026-11-10",
            effective_end="2026-11-20",
            created_at=NOW + timedelta(hours=3),
        )
        ambiguous_counts = _counts(restarted_sessions)
        with pytest.raises(AllocationPlanConsumerError) as ambiguous:
            _resolve(resolver_two)
        assert ambiguous.value.status_code == 409
        assert ambiguous.value.error_code == "EOS_COST_ALLOCATION_PLAN_AMBIGUOUS"
        assert ambiguous.value.retryable is False
        assert _counts(restarted_sessions) == ambiguous_counts == (4, 12)
    finally:
        if client_one is not None:
            client_one.close()
        if client_two is not None:
            client_two.close()
        if app_one is not None:
            app_one.state.eos_database_runtime.dispose()
        if app_two is not None:
            app_two.state.eos_database_runtime.dispose()
        with psycopg.connect(postgres_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
