from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
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
    EosBusinessApprovalTransitionService,
    EosBusinessFormalWcAdapter,
    NvtProjectInput,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    ProjectInput,
    SqlAlchemyEosApprovalInstanceRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosApprovalTransitionRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
)
from nex_oa.authorization_repository import (
    build_authorization_repository_for_runtime,
)
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.authorization_service import OaAuthorizationService
from nex_oa.memberships import build_tenant_membership_registry_for_runtime
from nex_oa.subjects import build_subject_registry_for_runtime
from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S73_POSTGRES_SMOKE") == "1"
TENANT = "p8-s73-pg"
INSTANCE_ID = "76000000-0000-4000-8000-000000000001"
POLICY_ID = "76000000-0000-4000-8000-000000000002"
OPERATION_ID = "76000000-0000-4000-8000-000000000003"
ORG_ID = "76000000-0000-4000-8000-000000000004"
NVT_ID = "76000000-0000-4000-8000-000000000005"
PROJECT_ID = "76000000-0000-4000-8000-000000000006"
TEAM_POSITION_ID = "76000000-0000-4000-8000-000000000007"
GROUP_POSITION_ID = "76000000-0000-4000-8000-000000000008"
TEAM_ASSIGNMENT_ID = "76000000-0000-4000-8000-000000000009"
GROUP_ASSIGNMENT_ID = "76000000-0000-4000-8000-000000000010"
NOW = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)
PAYLOAD_HASH = semantic_sha256_hash_ref({"amount": "7300.00"})
INTENT_HASH = semantic_sha256_hash_ref({"write": "p8-s73-pg-voucher"})

pytestmark = pytest.mark.skipif(
    not EOS_DATABASE_URL
    or not WC_DATABASE_URL
    or not OA_DATABASE_URL
    or not SMOKE_ENABLED,
    reason="Protected P8-S73 EOS/WC/OA PostgreSQL smoke is disabled",
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


class RepositoryClient:
    def __init__(self, repository):
        self._service = ApprovalWorkItemService(repository)

    def create_or_get(self, work_item):
        return self._service.create_or_get(work_item)


class AuthorizationSource:
    def __init__(self, service: OaAuthorizationService) -> None:
        self._service = service
        self.calls: list[tuple[str, str]] = []

    def effective_authorization(self, *, tenant_id, subject_id):
        response = self._service.effective_authorization(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        authorization = response.get("authorization")
        if not isinstance(authorization, dict):
            raise TypeError("OA authorization response is invalid")
        self.calls.append((tenant_id, subject_id))
        return {**authorization, "active": True}


def _cleanup_eos(runtime) -> dict[str, int]:
    with runtime.engine.begin() as connection:
        for table in EOS_TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == TENANT))
    with runtime.engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == TENANT)
            ).scalar_one()
            for table in EOS_TABLES
        }


def _cleanup_wc(engine) -> dict[str, int]:
    tables = ("wc_approval_outbox", "wc_approval_decision", "wc_approval_work_item")
    with engine.begin() as connection:
        for table_name in tables:
            connection.execute(
                text(f"DELETE FROM {table_name} WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            )
    with engine.connect() as connection:
        return {
            table_name: connection.execute(
                text(f"SELECT count(*) FROM {table_name} WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
            for table_name in tables
        }


def _cleanup_oa(engine) -> dict[str, int]:
    tables = (
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
    with engine.begin() as connection:
        for table_name in tables:
            connection.execute(
                text(f"DELETE FROM {table_name} WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            )
    with engine.connect() as connection:
        return {
            table_name: connection.execute(
                text(f"SELECT count(*) FROM {table_name} WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
            for table_name in tables
        }


def _dispose_persistence_runtime(runtime) -> None:
    if runtime.worker_engine is not None and runtime.worker_engine is not runtime.api_engine:
        runtime.worker_engine.dispose()
    if runtime.api_engine is not None:
        runtime.api_engine.dispose()


def _decision_envelope(
    repository,
    item,
    *,
    authorization_source: AuthorizationSource,
    suffix: int,
    at: datetime,
):
    decision_id = f"76000000-0000-4000-8001-{suffix:012d}"
    event_id = f"76000000-0000-4000-8002-{suffix:012d}"
    outbox_id = f"76000000-0000-4000-8003-{suffix:012d}"
    service = ApprovalDecisionService(
        repository,
        authorizer=ApprovalDecisionAuthorizer(
            authorization_source,
            clock=lambda: at,
        ),
        id_factory=lambda: decision_id,
        event_id_factory=lambda: event_id,
        outbox_id_factory=lambda: outbox_id,
        clock=lambda: at,
    )
    result = service.decide(
        tenant_id=TENANT,
        approval_work_item_id=item["approval_work_item_id"],
        decision="APPROVE",
        decided_by=item["target_approver_ref"],
        decision_comment=f"P8-S73 stage {suffix} approved",
        correlation_id=f"p8-s73-pg-correlation-{suffix}",
        causation_id=f"p8-s73-pg-causation-{suffix}",
    )
    terminal_item = repository.get(
        tenant_id=TENANT,
        approval_work_item_id=item["approval_work_item_id"],
    )
    event = next(
        row["event_payload"]
        for row in repository.list_pending_approval_events(limit=10)
        if row["decision_id"] == result["decision"]["decision_id"]
    )
    return terminal_item, result["decision"], event


def test_s73_actual_wc_decision_advances_eos_and_survives_restart() -> None:
    assert (
        make_url(EOS_DATABASE_URL).username,
        make_url(EOS_DATABASE_URL).database,
    ) == (
        "nex_eos_user",
        "nex_eos_test",
    )
    assert (make_url(WC_DATABASE_URL).username, make_url(WC_DATABASE_URL).database) == (
        "nex_wc_user",
        "nex_wc_test",
    )
    assert (make_url(OA_DATABASE_URL).username, make_url(OA_DATABASE_URL).database) == (
        "nex_oa_user",
        "nex_oa_test",
    )
    migrations = {
        service_id: run_service_migrations(
            service_id,
            database_url=database_url,
            profile="test",
        )
        for service_id, database_url in (
            ("nex-eos", EOS_DATABASE_URL),
            ("nex-wc", WC_DATABASE_URL),
            ("nex-oa", OA_DATABASE_URL),
        )
    }
    assert all(
        len(result.planned) == len(result.applied) + len(result.skipped)
        for result in migrations.values()
    )
    eos = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": EOS_DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    wc_engine = create_engine(WC_DATABASE_URL, pool_pre_ping=True)
    wc_sessions = sessionmaker(
        bind=wc_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    oa_spec = SERVICE_SPECS["nex-oa"]
    oa_app = build_service_app(oa_spec)
    oa = attach_service_persistence_runtime(
        oa_app,
        oa_spec,
        environ={
            oa_spec.database_env: OA_DATABASE_URL,
            "NEX_OA_PERSISTENCE_MODE": "postgres",
        },
    )
    assert oa.api_engine is not None
    subjects = build_subject_registry_for_runtime(oa)
    memberships = build_tenant_membership_registry_for_runtime(
        oa,
        subject_registry=subjects,
    )
    authorization_repository = build_authorization_repository_for_runtime(oa)
    authorization_source = AuthorizationSource(
        OaAuthorizationService(
            repository=authorization_repository,
            resolver=OaEffectiveAuthorizationResolver(authorization_repository),
            membership_registry=memberships,
        )
    )
    assert all(value == 0 for value in _cleanup_eos(eos).values())
    assert all(value == 0 for value in _cleanup_wc(wc_engine).values())
    assert all(value == 0 for value in _cleanup_oa(oa.api_engine).values())
    try:
        with eos.engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_eos_test", "nex_eos_user")
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = '2512_eos_approval_proof_decision_fk'"
                    )
                ).scalar_one()
                == 1
            )
        with oa.api_engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_oa_test", "nex_oa_user")

        for subject_id in ("employee-p8-s73-team", "employee-p8-s73-group"):
            memberships.ensure_membership(
                {
                    "tenant_id": TENANT,
                    "subject_id": subject_id,
                    "tenant_display_name": "P8 S73 PostgreSQL Tenant",
                    "subject_display_name": subject_id,
                    "roles": ["employee"],
                    "scopes": ["approval:decide"],
                    "membership_metadata": {"smoke_marker": "p8-s73"},
                }
            )
        with wc_engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_wc_test", "nex_wc_user")
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = '1006_wc_approval_foundation'"
                    )
                ).scalar_one()
                == 1
            )

        organization = SqlAlchemyEosOrganizationRepository(eos.session_factory)
        organization.create_org_unit(
            OrgUnitInput(
                TENANT,
                ORG_ID,
                "P8-S73-PG-FINANCE",
                "P8 S73 PostgreSQL Finance",
                "TEAM",
                NOW - timedelta(days=1),
            )
        )
        for position_id, position_type, assignment_id, principal in (
            (
                TEAM_POSITION_ID,
                "TEAM_LEAD",
                TEAM_ASSIGNMENT_ID,
                "employee-p8-s73-team",
            ),
            (
                GROUP_POSITION_ID,
                "GROUP_LEAD",
                GROUP_ASSIGNMENT_ID,
                "employee-p8-s73-group",
            ),
        ):
            organization.create_position(
                PositionInput(TENANT, position_id, position_type, ORG_ID)
            )
            organization.assign_position(
                PositionAssignmentInput(
                    TENANT,
                    assignment_id,
                    position_id,
                    {"type": "oa.user", "id": principal},
                    NOW - timedelta(hours=1),
                )
            )
        projects = SqlAlchemyEosProjectRepository(eos.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "P8-S73-PG-NVT", "P8 S73 PG NVT")
        )
        projects.create_project(
            ProjectInput(
                TENANT,
                PROJECT_ID,
                "P8-S73-PG-PROJECT",
                "P8 S73 PG Project",
                nvt_project_id=NVT_ID,
            )
        )
        SqlAlchemyEosApprovalPolicyRepository(eos.session_factory).create_policy(
            ApprovalPolicyInput(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="finance.voucher.p8-s73-pg",
                name="P8 S73 PostgreSQL policy",
                approval_domain="BUSINESS_FORMAL",
                effective_from=NOW - timedelta(days=1),
                stages=(
                    ApprovalPolicyStageInput("TEAM_LEAD"),
                    ApprovalPolicyStageInput("GROUP_LEAD"),
                ),
            )
        )
        with eos.engine.begin() as connection:
            connection.execute(
                EOS_BUSINESS_OPERATION_TABLE.insert().values(
                    tenant_id=TENANT,
                    business_operation_id=OPERATION_ID,
                    idempotency_key="p8-s73-pg-operation",
                    operation="CREATE_VOUCHER_DRAFT",
                    payload_hash=PAYLOAD_HASH,
                    commit_state="COMMITTED",
                    result_json={"voucher_id": "p8-s73-pg-voucher"},
                    created_at=NOW - timedelta(minutes=1),
                    committed_at=NOW - timedelta(seconds=30),
                )
            )
        instances = SqlAlchemyEosApprovalInstanceRepository(
            eos.session_factory, clock=lambda: NOW
        )
        _instance, created = instances.create_or_get_instance(
            ApprovalInstanceInput(
                tenant_id=TENANT,
                approval_instance_id=INSTANCE_ID,
                idempotency_key="p8-s73-pg-instance",
                approval_policy_id=POLICY_ID,
                business_operation_id=OPERATION_ID,
                protected_operation_ref="eos:business-operation:p8-s73-pg",
                payload_hash=PAYLOAD_HASH,
                write_intent_hash=INTENT_HASH,
                requester_ref={"type": "oa.user", "id": "employee-p8-s73"},
                org_unit_id=ORG_ID,
                project_id=PROJECT_ID,
                correlation_id="p8-s73-pg-correlation",
                causation_id="p8-s73-pg-causation",
                expires_at=NOW + timedelta(days=7),
            )
        )
        assert created is True
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_sessions)
        adapter = EosBusinessFormalWcAdapter(
            approval_instances=instances,
            approver_resolution=EosApproverResolutionService(
                organization, clock=lambda: NOW
            ),
            wc_client=RepositoryClient(wc_repository),
            clock=lambda: NOW,
        )
        transition_repository = SqlAlchemyEosApprovalTransitionRepository(
            eos.session_factory, clock=lambda: NOW + timedelta(minutes=2)
        )
        transition_service = EosBusinessApprovalTransitionService(
            approval_instances=instances,
            transitions=transition_repository,
        )

        first_projection = adapter.project_active_stage(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        )
        first_envelope = _decision_envelope(
            wc_repository,
            first_projection["work_item"],
            authorization_source=authorization_source,
            suffix=1,
            at=NOW + timedelta(minutes=1),
        )
        first = transition_service.advance_from_wc_decision(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
            work_item=first_envelope[0],
            decision=first_envelope[1],
            event=first_envelope[2],
        )
        assert first["outcome"] == "NEXT_STAGE_ACTIVE"
        assert first["next_active_stage"]["position_type"] == "GROUP_LEAD"

        adapter = EosBusinessFormalWcAdapter(
            approval_instances=instances,
            approver_resolution=EosApproverResolutionService(
                organization, clock=lambda: NOW + timedelta(minutes=3)
            ),
            wc_client=RepositoryClient(wc_repository),
            clock=lambda: NOW + timedelta(minutes=3),
        )
        second_projection = adapter.project_active_stage(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        )
        second_envelope = _decision_envelope(
            wc_repository,
            second_projection["work_item"],
            authorization_source=authorization_source,
            suffix=2,
            at=NOW + timedelta(minutes=4),
        )
        restarted_transitions = SqlAlchemyEosApprovalTransitionRepository(
            eos.session_factory, clock=lambda: NOW + timedelta(minutes=5)
        )
        restarted_service = EosBusinessApprovalTransitionService(
            approval_instances=SqlAlchemyEosApprovalInstanceRepository(
                eos.session_factory
            ),
            transitions=restarted_transitions,
        )
        final = restarted_service.advance_from_wc_decision(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
            work_item=second_envelope[0],
            decision=second_envelope[1],
            event=second_envelope[2],
        )
        assert final["outcome"] == "FINAL_APPROVED"
        assert final["instance"]["state"] == "APPROVED"
        assert final["approval_proof"]["business_operation_id"] == OPERATION_ID
        proof = SqlAlchemyEosApprovalTransitionRepository(
            eos.session_factory
        ).get_final_proof(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
        assert proof == final["approval_proof"]

        replay = restarted_service.advance_from_wc_decision(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
            work_item=second_envelope[0],
            decision=second_envelope[1],
            event=second_envelope[2],
        )
        assert replay["created"] is False
        assert replay["approval_proof"] == proof
        assert authorization_source.calls == [
            (TENANT, "employee-p8-s73-team"),
            (TENANT, "employee-p8-s73-group"),
        ]
    finally:
        assert all(value == 0 for value in _cleanup_wc(wc_engine).values())
        assert all(value == 0 for value in _cleanup_eos(eos).values())
        assert all(value == 0 for value in _cleanup_oa(oa.api_engine).values())
        wc_engine.dispose()
        eos.dispose()
        _dispose_persistence_runtime(oa)
