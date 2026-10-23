from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
from fastapi.testclient import TestClient
from nex_ae_api.approval_facade import (
    HttpWcApprovalClient,
    register_approval_facade_routes,
)
from nex_ae_api.auth_sessions import AUTH_SESSION_MODE_OA, register_auth_session_routes
from nex_ae_api.oa_session_client import HttpOaUserSessionClient
from nex_eos import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_ORG_UNIT_TABLE,
    EOS_POSITION_ASSIGNMENT_TABLE,
    EOS_POSITION_TABLE,
    EOS_PROJECT_TABLE,
    ApprovalInstanceInput,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    EosApproverResolutionService,
    EosBusinessFormalWcAdapter,
    NvtProjectInput,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    ProjectInput,
    SqlAlchemyEosApprovalInstanceRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from nex_oa.authorization_repository import build_authorization_repository_for_runtime
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.authorization_service import (
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.credentials import (
    build_credential_registry_for_runtime,
    register_local_credential_routes,
)
from nex_oa.memberships import (
    build_tenant_membership_registry_for_runtime,
    register_identity_membership_routes,
)
from nex_oa.sessions import (
    build_oa_session_registry_for_runtime,
    register_user_session_routes,
)
from nex_oa.subjects import (
    OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
    build_subject_registry_for_runtime,
    register_subject_registry_routes,
)
from nex_oa.user_login import OaUserLoginService, register_user_login_routes
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.approval_api import register_approval_routes
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalDetailService,
    ApprovalInboxService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from nex_wc.coordination_clients import HttpAuthorizationSource
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S74_POSTGRES_PLAYWRIGHT_SMOKE") == "1"
NODE_RUNNER = (
    ROOT
    / "apps"
    / "nex-ae-web"
    / "scripts"
    / "runBusinessFormalApprovalPlaywrightSmoke.mjs"
)
PASSWORD = "Nuri1004!"

pytestmark = pytest.mark.skipif(
    not EOS_DATABASE_URL
    or not WC_DATABASE_URL
    or not OA_DATABASE_URL
    or not SMOKE_ENABLED,
    reason="Protected P8-S74 EOS/WC/OA PostgreSQL Playwright smoke is disabled",
)

EOS_TABLES = (
    EOS_APPROVAL_PROOF_TABLE,
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_POSITION_ASSIGNMENT_TABLE,
    EOS_POSITION_TABLE,
    EOS_ORG_UNIT_TABLE,
)


class _RepositoryClient:
    def __init__(self, repository) -> None:
        self._service = ApprovalWorkItemService(repository)

    def create_or_get(self, work_item):
        return self._service.create_or_get(work_item)


def _stable_uuid(tenant_id: str, label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"nex-p8-s74:{tenant_id}:{label}"))


def _service_token(service_id: str, audience: str, *scopes: str) -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    ).access_token


def _identity_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + _service_token(
            "nex-ae-api",
            "nex-oa",
            OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
        ),
        "X-Service-ID": "nex-ae-api",
        "X-Request-ID": str(uuid4()),
    }


def _build_oa_app(database_url: str):
    spec = SERVICE_SPECS["nex-oa"]
    app = build_service_app(spec)
    runtime = attach_service_persistence_runtime(
        app,
        spec,
        environ={
            spec.database_env: database_url,
            "NEX_OA_PERSISTENCE_MODE": "postgres",
        },
    )
    subjects = build_subject_registry_for_runtime(runtime)
    memberships = build_tenant_membership_registry_for_runtime(
        runtime,
        subject_registry=subjects,
    )
    authorization_repository = build_authorization_repository_for_runtime(runtime)
    authorization_resolver = OaEffectiveAuthorizationResolver(
        repository=authorization_repository
    )
    sessions = build_oa_session_registry_for_runtime(
        runtime,
        membership_registry=memberships,
        authorization_resolver=authorization_resolver,
    )
    credentials = build_credential_registry_for_runtime(
        runtime,
        subject_registry=subjects,
    )
    authorization = OaAuthorizationService(
        repository=authorization_repository,
        resolver=authorization_resolver,
        membership_registry=memberships,
    )
    register_subject_registry_routes(app, registry=subjects)
    register_identity_membership_routes(app, registry=memberships)
    register_local_credential_routes(app, registry=credentials)
    register_user_session_routes(app, registry=sessions)
    register_user_login_routes(
        app,
        service=OaUserLoginService(
            credential_registry=credentials,
            session_registry=sessions,
        ),
    )
    register_authorization_routes(app, service=authorization)
    return app


def _seed_approver(
    app: Any,
    *,
    tenant_id: str,
    subject_id: str,
    employee_id: str,
) -> None:
    with TestClient(app) as client:
        membership = client.post(
            "/internal/v1/identity/memberships/ensure",
            headers=_identity_headers(),
            json={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "tenant_display_name": "P8-S74 Formal Tenant",
                "subject_display_name": "P8-S74 Formal Approver",
                "status": "ACTIVE",
                "roles": ["employee"],
                "scopes": [
                    DEFAULT_USER_SCOPE,
                    "documents:upload",
                    "approval:read",
                    "approval:decide",
                ],
                "membership_metadata": {"smoke_marker": "p8-s74"},
            },
        )
        membership.raise_for_status()
        credential = client.post(
            "/internal/v1/auth/local-credentials/ensure",
            headers=_identity_headers(),
            json={
                "tenant_id": tenant_id,
                "employee_id": employee_id,
                "subject_id": subject_id,
                "password": PASSWORD,
                "credential_metadata": {"smoke_marker": "p8-s74"},
            },
        )
        credential.raise_for_status()


def _build_wc_app(database_url: str, *, oa_url: str):
    spec = SERVICE_SPECS["nex-wc"]
    app = build_service_app(spec)
    runtime = attach_service_persistence_runtime(
        app,
        spec,
        environ={
            spec.database_env: database_url,
            "NEX_WC_PERSISTENCE_MODE": "postgres",
        },
    )
    repository = SqlAlchemyApprovalWorkItemRepository(runtime.api_session_factory)
    authorization = HttpAuthorizationSource(
        base_url=oa_url,
        service_token=_service_token(
            "nex-wc",
            "nex-oa",
            OA_AUTHORIZATION_READ_SCOPE,
        ),
    )
    register_approval_routes(
        app,
        inbox_service=ApprovalInboxService(
            repository,
            authorization_source=authorization,
        ),
        detail_service=ApprovalDetailService(
            repository,
            authorization_source=authorization,
        ),
        decision_service=ApprovalDecisionService(
            repository,
            authorizer=ApprovalDecisionAuthorizer(authorization),
        ),
    )
    return app, repository


def _build_ae_app(*, oa_url: str, wc_url: str):
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    oa_client = HttpOaUserSessionClient(
        base_url=oa_url,
        service_token=_service_token("nex-ae-api", "nex-oa"),
    )
    register_auth_session_routes(
        app,
        oa_session_client=oa_client,
        session_mode=AUTH_SESSION_MODE_OA,
        cookie_secure=False,
    )
    register_approval_facade_routes(
        app,
        wc_client=HttpWcApprovalClient(
            base_url=wc_url,
            service_token=_service_token("nex-ae-api", "nex-wc"),
        ),
        oa_session_client=oa_client,
        session_mode=AUTH_SESSION_MODE_OA,
    )
    return app


def _nsl_work_item(
    *, tenant_id: str, subject_id: str, now: datetime
) -> dict[str, Any]:
    label = "nsl-write"
    return {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": tenant_id,
        "approval_work_item_id": _stable_uuid(tenant_id, label),
        "approval_domain": "NSL_WRITE",
        "source_ref": f"approval-request-{label}",
        "semantic_hash": "sha256:" + "7" * 64,
        "title": "P8-S74 NSL WRITE approval",
        "display_safe_summary": "Domain separation control item.",
        "approval_provider_type": "NSL",
        "approval_target_ref": f"approval-request-{label}",
        "target_approver_ref": subject_id,
        "target_role_ref": None,
        "target_org_scope_ref": None,
        "target_project_scope_ref": None,
        "agent_execution_id": f"agent-execution-{label}",
        "executable_step_id": f"step-{label}",
        "nsl_execution_id": f"nsl-execution-{label}",
        "business_operation_id": f"business-operation-{label}",
        "approval_request_id": f"approval-request-{label}",
        "protected_request_ref": f"ae-private:approval-{label}",
        "resume_target_ref": f"ae-wait:approval-{label}",
        "state": "PENDING",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "version": 1,
    }


def _cleanup_eos(runtime, tenant_id: str) -> dict[str, int]:
    with runtime.engine.begin() as connection:
        for table in EOS_TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == tenant_id))
    with runtime.engine.connect() as connection:
        return {
            table.name: int(
                connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.tenant_id == tenant_id)
                ).scalar_one()
            )
            for table in EOS_TABLES
        }


def _cleanup_sql_tables(engine, tenant_id: str, tables: tuple[str, ...]):
    with engine.begin() as connection:
        for table in tables:
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in tables
        }


def _dispose_eos(runtime) -> None:
    runtime.engine.dispose()


def test_s74_actual_eos_wc_oa_postgres_business_formal_playwright() -> None:
    database_specs = (
        ("nex-eos", EOS_DATABASE_URL, "nex_eos_user", "nex_eos_test"),
        ("nex-wc", WC_DATABASE_URL, "nex_wc_user", "nex_wc_test"),
        ("nex-oa", OA_DATABASE_URL, "nex_oa_user", "nex_oa_test"),
    )
    for service_id, database_url, expected_user, expected_database in database_specs:
        result = run_service_migrations(
            service_id,
            database_url=database_url,
            profile="test",
        )
        assert len(result.planned) == len(result.applied) + len(result.skipped)
        assert (make_url(database_url).username, make_url(database_url).database) == (
            expected_user,
            expected_database,
        )
        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                assert tuple(
                    connection.execute(
                        text("SELECT current_user, current_database()")
                    ).one()
                ) == (expected_user, expected_database)
        finally:
            engine.dispose()

    suffix = uuid4().hex[:8]
    tenant_id = f"tenant-p8-s74-{suffix}"
    subject_id = f"approver-{suffix}"
    requester_id = f"requester-{suffix}"
    employee_id = f"EMP-P8-S74-{suffix}"
    now = datetime.now(UTC)
    ids = {
        label: _stable_uuid(tenant_id, label)
        for label in (
            "org",
            "nvt",
            "project",
            "team-position",
            "group-position",
            "team-assignment",
            "group-assignment",
            "policy",
            "operation",
            "instance",
        )
    }
    payload_hash = semantic_sha256_hash_ref({"amount": "7400.00"})
    intent_hash = semantic_sha256_hash_ref({"write": "p8-s74-voucher"})
    wc_tables = (
        "wc_approval_outbox",
        "wc_approval_decision",
        "wc_approval_work_item",
    )
    oa_tables = (
        "oa_authz_events",
        "oa_group_roles",
        "oa_group_members",
        "oa_roles",
        "oa_groups",
        "oa_user_sessions",
        "oa_local_credentials",
        "oa_tenant_memberships",
        "oa_subjects",
        "oa_tenants",
    )
    eos = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": EOS_DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    wc_engine = create_engine(WC_DATABASE_URL, pool_pre_ping=True)
    oa_engine = create_engine(OA_DATABASE_URL, pool_pre_ping=True)
    servers: list[Any] = []
    try:
        assert all(value == 0 for value in _cleanup_eos(eos, tenant_id).values())
        assert all(
            value == 0
            for value in _cleanup_sql_tables(wc_engine, tenant_id, wc_tables).values()
        )
        assert all(
            value == 0
            for value in _cleanup_sql_tables(oa_engine, tenant_id, oa_tables).values()
        )

        oa_app = _build_oa_app(OA_DATABASE_URL)
        _seed_approver(
            oa_app,
            tenant_id=tenant_id,
            subject_id=subject_id,
            employee_id=employee_id,
        )
        oa_server = browser_runtime.start_api_server(
            oa_app,
            browser_runtime.find_free_port(),
        )
        servers.append(oa_server)
        wc_app, wc_repository = _build_wc_app(
            WC_DATABASE_URL,
            oa_url=oa_server.url,
        )

        organization = SqlAlchemyEosOrganizationRepository(eos.session_factory)
        organization.create_org_unit(
            OrgUnitInput(
                tenant_id,
                ids["org"],
                f"FINANCE-{suffix}",
                "P8-S74 Finance",
                "TEAM",
                now - timedelta(days=1),
            )
        )
        for position_id, position_type, assignment_id in (
            (ids["team-position"], "TEAM_LEAD", ids["team-assignment"]),
            (ids["group-position"], "GROUP_LEAD", ids["group-assignment"]),
        ):
            organization.create_position(
                PositionInput(tenant_id, position_id, position_type, ids["org"])
            )
            organization.assign_position(
                PositionAssignmentInput(
                    tenant_id,
                    assignment_id,
                    position_id,
                    {"type": "oa.user", "id": subject_id},
                    now - timedelta(hours=1),
                )
            )
        projects = SqlAlchemyEosProjectRepository(eos.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(
                tenant_id,
                ids["nvt"],
                f"NVT-{suffix}",
                "P8-S74 NVT",
            )
        )
        projects.create_project(
            ProjectInput(
                tenant_id,
                ids["project"],
                f"PROJECT-{suffix}",
                "P8-S74 Project",
                nvt_project_id=ids["nvt"],
            )
        )
        SqlAlchemyEosApprovalPolicyRepository(eos.session_factory).create_policy(
            ApprovalPolicyInput(
                tenant_id=tenant_id,
                approval_policy_id=ids["policy"],
                policy_key=f"finance.voucher.p8-s74-{suffix}",
                name="P8-S74 formal approval policy",
                approval_domain="BUSINESS_FORMAL",
                effective_from=now - timedelta(days=1),
                stages=(
                    ApprovalPolicyStageInput("TEAM_LEAD"),
                    ApprovalPolicyStageInput("GROUP_LEAD"),
                ),
            )
        )
        with eos.engine.begin() as connection:
            connection.execute(
                EOS_BUSINESS_OPERATION_TABLE.insert().values(
                    tenant_id=tenant_id,
                    business_operation_id=ids["operation"],
                    idempotency_key=f"p8-s74-operation-{suffix}",
                    operation="CREATE_VOUCHER_DRAFT",
                    payload_hash=payload_hash,
                    commit_state="COMMITTED",
                    result_json={"voucher_id": f"p8-s74-voucher-{suffix}"},
                    created_at=now - timedelta(minutes=1),
                    committed_at=now - timedelta(seconds=30),
                )
            )
        instances = SqlAlchemyEosApprovalInstanceRepository(
            eos.session_factory,
            clock=lambda: now,
        )
        instance, created = instances.create_or_get_instance(
            ApprovalInstanceInput(
                tenant_id=tenant_id,
                approval_instance_id=ids["instance"],
                idempotency_key=f"p8-s74-instance-{suffix}",
                approval_policy_id=ids["policy"],
                business_operation_id=ids["operation"],
                protected_operation_ref=f"eos:business-operation:{ids['operation']}",
                payload_hash=payload_hash,
                write_intent_hash=intent_hash,
                requester_ref={"type": "oa.user", "id": requester_id},
                org_unit_id=ids["org"],
                project_id=ids["project"],
                correlation_id=f"p8-s74-correlation-{suffix}",
                causation_id=f"p8-s74-causation-{suffix}",
                expires_at=now + timedelta(days=7),
            )
        )
        assert created is True
        formal = EosBusinessFormalWcAdapter(
            approval_instances=instances,
            approver_resolution=EosApproverResolutionService(
                organization,
                clock=lambda: now,
            ),
            wc_client=_RepositoryClient(wc_repository),
            clock=lambda: now,
        ).project_active_stage(
            tenant_id=tenant_id,
            approval_instance_id=ids["instance"],
        )
        assert formal["created"] is True
        assert formal["work_item"]["target_role_ref"] == "TEAM_LEAD"
        nsl = _nsl_work_item(
            tenant_id=tenant_id,
            subject_id=subject_id,
            now=now,
        )
        assert ApprovalWorkItemService(wc_repository).create_or_get(nsl)["created"]
        direct_inbox = ApprovalInboxService(
            wc_repository,
            authorization_source=HttpAuthorizationSource(
                base_url=oa_server.url,
                service_token=_service_token(
                    "nex-wc",
                    "nex-oa",
                    OA_AUTHORIZATION_READ_SCOPE,
                ),
            ),
        ).list_pending(
            tenant_id=tenant_id,
            subject_id=subject_id,
            limit=50,
        )
        direct_formal = next(
            gate
            for gate in direct_inbox["gates"]
            if gate["approval_domain"] == "BUSINESS_FORMAL"
        )
        assert direct_formal["formal_approval"]["current_stage"] == 1
        assert direct_formal["formal_approval"]["stage_count"] == 2

        wc_server = browser_runtime.start_api_server(
            wc_app,
            browser_runtime.find_free_port(),
        )
        servers.append(wc_server)
        ae_server = browser_runtime.start_api_server(
            _build_ae_app(oa_url=oa_server.url, wc_url=wc_server.url),
            browser_runtime.find_free_port(),
        )
        servers.append(ae_server)
        web_server = browser_runtime.start_web_server(
            browser_runtime.find_free_port(),
            ae_server.url,
        )
        servers.append(web_server)

        completed = subprocess.run(
            ["node", str(NODE_RUNNER)],
            cwd=ROOT,
            env={
                **os.environ,
                "NEX_P8_S74_WEB_URL": web_server.url,
                "NEX_P8_S74_TENANT_ID": tenant_id,
                "NEX_P8_S74_EMPLOYEE_ID": employee_id,
                "NEX_P8_S74_PASSWORD": PASSWORD,
                "NEX_P8_S74_FORMAL_GATE_ID": formal["work_item"][
                    "approval_work_item_id"
                ],
                "NEX_P8_S74_NSL_GATE_ID": nsl["approval_work_item_id"],
                "NEX_P8_S74_EXPECTED_ROLE": "TEAM_LEAD",
                "NEX_P8_S74_EXPECTED_TARGET": formal["work_item"][
                    "approval_target_ref"
                ],
                "NEX_P8_S74_EXPECTED_STAGE": "1",
                "NEX_P8_S74_EXPECTED_STAGE_COUNT": "2",
            },
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout or completed.stderr
        evidence = json.loads(completed.stdout)
        assert evidence["status"] == "PASS", evidence
        assert all(evidence["checks"].values()), evidence
        assert evidence["runner"]["postgresql_used"] is True

        with wc_engine.connect() as connection:
            decision = connection.execute(
                text(
                    """
                    SELECT w.state, d.decision, count(o.outbox_id) AS outbox_count
                    FROM wc_approval_work_item w
                    JOIN wc_approval_decision d
                      ON d.tenant_id = w.tenant_id
                     AND d.approval_work_item_id = w.approval_work_item_id
                    LEFT JOIN wc_approval_outbox o
                      ON o.tenant_id = d.tenant_id
                     AND o.decision_id = d.decision_id
                    WHERE w.tenant_id = :tenant_id
                      AND w.approval_work_item_id = :work_item_id
                    GROUP BY w.state, d.decision
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "work_item_id": formal["work_item"]["approval_work_item_id"],
                },
            ).one()
        assert tuple(decision) == ("APPROVED", "APPROVE", 1)
        persisted_instance = instances.get_instance(
            tenant_id=tenant_id,
            approval_instance_id=ids["instance"],
        )
        assert persisted_instance is not None
        assert persisted_instance["state"] == instance["state"] == "PENDING"
        assert persisted_instance["stages"][0]["state"] == "ACTIVE"
    finally:
        for server in reversed(servers):
            server.stop()
        eos_residue = _cleanup_eos(eos, tenant_id)
        wc_residue = _cleanup_sql_tables(wc_engine, tenant_id, wc_tables)
        oa_residue = _cleanup_sql_tables(oa_engine, tenant_id, oa_tables)
        _dispose_eos(eos)
        wc_engine.dispose()
        oa_engine.dispose()

    assert all(value == 0 for value in eos_residue.values()), eos_residue
    assert all(value == 0 for value in wc_residue.values()), wc_residue
    assert all(value == 0 for value in oa_residue.values()), oa_residue
