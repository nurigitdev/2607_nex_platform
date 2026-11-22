from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from nex_eos import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_ORG_UNIT_TABLE,
    EOS_POSITION_ASSIGNMENT_TABLE,
    EOS_POSITION_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_TABLE,
    ApprovalInstanceInput,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    EosAllocationPlanError,
    EosAllocationPlanService,
    EosApproverResolutionService,
    EosBusinessApprovalTransitionService,
    EosBusinessFormalWcAdapter,
    NvtProjectInput,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    ProjectInput,
    SqlAlchemyEosAllocationPlanRepository,
    SqlAlchemyEosApprovalInstanceRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosApprovalTransitionRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
    allocation_plans,
    build_eos_database_runtime,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_oa.authorization import OaAuthorizationError
from nex_oa.authorization_repository import build_authorization_repository_for_runtime
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
SMOKE_ENABLED = os.getenv("NEX_EOS_MYBEE_S6_02_POSTGRES_SMOKE") == "1"

TENANT = "W502"
COMPANY_ID = "73000000-0000-4000-8000-000000000001"
NVT_ID = "73000000-0000-4000-8000-000000000002"
PROJECT_ID = "73000000-0000-4000-8000-000000000003"
PLAN_ID = "73000000-0000-4000-8000-000000000004"
ORG_ID = "73000000-0000-4000-8000-000000000005"
POSITION_ID = "73000000-0000-4000-8000-000000000006"
ASSIGNMENT_ID = "73000000-0000-4000-8000-000000000007"
POLICY_ID = "73000000-0000-4000-8000-000000000008"
OPERATION_ID = "73000000-0000-4000-8000-000000000009"
INSTANCE_ID = "73000000-0000-4000-8000-000000000010"
DECISION_ID = "73000000-0000-4000-8001-000000000001"
EVENT_ID = "73000000-0000-4000-8002-000000000001"
OUTBOX_ID = "73000000-0000-4000-8003-000000000001"
APPROVER = "employee-w50-allocation-approver"
NOW = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64

pytestmark = pytest.mark.skipif(
    not EOS_DATABASE_URL
    or not WC_DATABASE_URL
    or not OA_DATABASE_URL
    or not SMOKE_ENABLED,
    reason="Protected S6-02 EOS/WC/OA PostgreSQL smoke is disabled",
)


class RepositoryWcClient:
    def __init__(self, repository) -> None:
        self._service = ApprovalWorkItemService(repository)

    def create_or_get(self, work_item):
        return self._service.create_or_get(work_item)


class OaAuthorizationSource:
    def __init__(self, service: OaAuthorizationService) -> None:
        self._service = service
        self.calls: list[tuple[str, str]] = []

    def effective_authorization(self, *, tenant_id, subject_id):
        try:
            response = self._service.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except OaAuthorizationError as exc:
            if exc.error_code in {
                "oa.authorization_membership_inactive",
                "oa.authorization_membership_not_found",
            }:
                raise AuthorizationSubjectDenied(
                    "OA membership is inactive or absent",
                    error_code=exc.error_code,
                ) from exc
            raise
        authorization = response.get("authorization")
        if not isinstance(authorization, dict):
            raise AuthorizationSubjectDenied("OA membership is inactive or absent")
        self.calls.append((tenant_id, subject_id))
        return {**authorization, "active": True}


def _payload(proof_id: str) -> dict:
    return {
        "schema_version": "eos_cost_allocation_plan_release.v1",
        "approval_proof_id": proof_id,
        "plan": {
            "plan_id": PLAN_ID,
            "plan_revision": 1,
            "source_kind": "SHARED_EXPENSE",
            "scope_type": "PROJECT",
            "basis_kind": "JUSTIFIED_PERCENTAGE",
            "rule_release_hash": HASH_A,
            "basis_source_ref": "eos.approved-ratio:w50-smoke",
            "basis_source_hash": HASH_B,
            "effective_start": "2026-11-01",
            "effective_end": "2026-11-30",
            "lines": [
                {
                    "line_no": 1,
                    "project_id": PROJECT_ID,
                    "project_code": "W502D260001",
                    "work_code": None,
                    "basis_units": "1.00000000",
                    "allocation_ratio": "1.000000000000",
                    "eligibility_hash": HASH_C,
                    "confidentiality_class": "INTERNAL",
                }
            ],
        },
    }


def _cleanup_eos(runtime) -> dict[str, int]:
    tables = (
        EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
        EOS_COST_ALLOCATION_PLAN_TABLE,
        EOS_APPROVAL_PROOF_TABLE,
        EOS_APPROVAL_DECISION_TABLE,
        EOS_APPROVAL_STAGE_TABLE,
        EOS_APPROVAL_INSTANCE_TABLE,
        EOS_APPROVAL_POLICY_STAGE_TABLE,
        EOS_APPROVAL_POLICY_TABLE,
        EOS_BUSINESS_OPERATION_TABLE,
        EOS_PROJECT_COMPANY_BINDING_TABLE,
        EOS_PROJECT_TABLE,
        EOS_NVT_PROJECT_TABLE,
        EOS_POSITION_ASSIGNMENT_TABLE,
        EOS_POSITION_TABLE,
        EOS_ORG_UNIT_TABLE,
        EOS_LEGAL_ENTITY_TABLE,
    )
    with runtime.engine.begin() as connection:
        for table in tables:
            connection.execute(table.delete().where(table.c.tenant_id == TENANT))
    with runtime.engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == TENANT)
            ).scalar_one()
            for table in tables
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


def _dispose_oa(runtime) -> None:
    if (
        runtime.worker_engine is not None
        and runtime.worker_engine is not runtime.api_engine
    ):
        runtime.worker_engine.dispose()
    if runtime.api_engine is not None:
        runtime.api_engine.dispose()


def test_actual_postgres_business_formal_release_and_fresh_oa_denial() -> None:
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
    for service_id, database_url in (
        ("nex-eos", EOS_DATABASE_URL),
        ("nex-wc", WC_DATABASE_URL),
        ("nex-oa", OA_DATABASE_URL),
    ):
        migration = run_service_migrations(
            service_id, database_url=database_url, profile="test"
        )
        assert len(migration.planned) == len(migration.applied) + len(migration.skipped)

    eos = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": EOS_DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    wc_engine = create_engine(WC_DATABASE_URL, pool_pre_ping=True)
    wc_sessions = sessionmaker(bind=wc_engine, autoflush=False, expire_on_commit=False)
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
        oa, subject_registry=subjects
    )
    authorization_repository = build_authorization_repository_for_runtime(oa)
    authorization_source = OaAuthorizationSource(
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
        memberships.ensure_membership(
            {
                "tenant_id": TENANT,
                "subject_id": APPROVER,
                "tenant_display_name": "W50 Allocation Smoke Tenant",
                "subject_display_name": APPROVER,
                "roles": ["finance-approver"],
                "scopes": [
                    "approval:decide",
                    "finance:cost-allocation-plan:approve",
                ],
                "membership_metadata": {"smoke_marker": "w50-s6-02"},
            }
        )
        organization = SqlAlchemyEosOrganizationRepository(eos.session_factory)
        organization.create_org_unit(
            OrgUnitInput(
                TENANT,
                ORG_ID,
                "W50-FINANCE",
                "W50 Finance",
                "TEAM",
                NOW - timedelta(days=1),
            )
        )
        organization.create_position(
            PositionInput(TENANT, POSITION_ID, "TEAM_LEAD", ORG_ID)
        )
        organization.assign_position(
            PositionAssignmentInput(
                TENANT,
                ASSIGNMENT_ID,
                POSITION_ID,
                {"type": "oa.user", "id": APPROVER},
                NOW - timedelta(hours=1),
            )
        )
        projects = SqlAlchemyEosProjectRepository(eos.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "W50-NVT", "W50 NVT")
        )
        projects.create_project(
            ProjectInput(
                TENANT,
                PROJECT_ID,
                "W502D260001",
                "W50 Allocation Project",
                nvt_project_id=NVT_ID,
            )
        )
        with eos.engine.begin() as connection:
            connection.execute(
                EOS_LEGAL_ENTITY_TABLE.insert().values(
                    tenant_id=TENANT,
                    company_id=COMPANY_ID,
                    company_code="W50-COMPANY",
                    name="W50 Company",
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
            connection.execute(
                EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                    tenant_id=TENANT,
                    binding_id=str(uuid.uuid4()),
                    project_id=PROJECT_ID,
                    company_id=COMPANY_ID,
                    valid_from=date(2026, 1, 1),
                    valid_until=None,
                    approved_proof_hash=HASH_A,
                    state="APPROVED",
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

        SqlAlchemyEosApprovalPolicyRepository(eos.session_factory).create_policy(
            ApprovalPolicyInput(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="finance.cost-allocation-plan.w50",
                name="W50 allocation plan release",
                approval_domain="BUSINESS_FORMAL",
                effective_from=NOW - timedelta(days=1),
                stages=(ApprovalPolicyStageInput("TEAM_LEAD"),),
            )
        )
        provisional = _payload(str(uuid.uuid4()))
        _, candidate = allocation_plans._admit_release(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=provisional
        )
        with eos.engine.begin() as connection:
            connection.execute(
                EOS_BUSINESS_OPERATION_TABLE.insert().values(
                    tenant_id=TENANT,
                    business_operation_id=OPERATION_ID,
                    idempotency_key="w50-allocation-plan-release",
                    operation="FINANCE.COST_ALLOCATION_PLAN.RELEASE",
                    payload_hash=candidate["plan_hash"],
                    commit_state="COMMITTED",
                    result_json={"plan_id": PLAN_ID, "plan_revision": 1},
                    created_at=NOW - timedelta(minutes=2),
                    committed_at=NOW - timedelta(minutes=1),
                )
            )
        instances = SqlAlchemyEosApprovalInstanceRepository(
            eos.session_factory, clock=lambda: NOW
        )
        instances.create_or_get_instance(
            ApprovalInstanceInput(
                tenant_id=TENANT,
                approval_instance_id=INSTANCE_ID,
                idempotency_key="w50-allocation-plan-approval",
                approval_policy_id=POLICY_ID,
                business_operation_id=OPERATION_ID,
                protected_operation_ref=(
                    f"eos.cost-allocation-plan:{PLAN_ID}:revision:1"
                ),
                payload_hash=candidate["plan_hash"],
                write_intent_hash=semantic_sha256_hash_ref(
                    {"write": "w50-allocation-plan-release"}
                ),
                requester_ref={"type": "oa.user", "id": "employee-requester"},
                org_unit_id=ORG_ID,
                project_id=PROJECT_ID,
                correlation_id="w50-allocation-correlation",
                causation_id="w50-allocation-causation",
                expires_at=NOW + timedelta(days=1),
            )
        )
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_sessions)
        adapter = EosBusinessFormalWcAdapter(
            approval_instances=instances,
            approver_resolution=EosApproverResolutionService(
                organization, clock=lambda: NOW
            ),
            wc_client=RepositoryWcClient(wc_repository),
            clock=lambda: NOW,
        )
        work_item = adapter.project_active_stage(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        )["work_item"]
        decision_service = ApprovalDecisionService(
            wc_repository,
            authorizer=ApprovalDecisionAuthorizer(
                authorization_source, clock=lambda: NOW + timedelta(minutes=1)
            ),
            id_factory=lambda: DECISION_ID,
            event_id_factory=lambda: EVENT_ID,
            outbox_id_factory=lambda: OUTBOX_ID,
            clock=lambda: NOW + timedelta(minutes=1),
        )
        decision_result = decision_service.decide(
            tenant_id=TENANT,
            approval_work_item_id=work_item["approval_work_item_id"],
            decision="APPROVE",
            decided_by=APPROVER,
            decision_comment="W50 allocation plan approved",
            correlation_id="w50-allocation-decision",
            causation_id="w50-allocation-work-item",
        )
        terminal_item = wc_repository.get(
            tenant_id=TENANT,
            approval_work_item_id=work_item["approval_work_item_id"],
        )
        event = next(
            row["event_payload"]
            for row in wc_repository.list_pending_approval_events(limit=10)
            if row["decision_id"] == DECISION_ID
        )
        final = EosBusinessApprovalTransitionService(
            approval_instances=instances,
            transitions=SqlAlchemyEosApprovalTransitionRepository(
                eos.session_factory, clock=lambda: NOW + timedelta(minutes=2)
            ),
        ).advance_from_wc_decision(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
            work_item=terminal_item,
            decision=decision_result["decision"],
            event=event,
        )
        assert final["outcome"] == "FINAL_APPROVED"
        proof_id = final["approval_proof"]["approval_proof_id"]
        payload = _payload(proof_id)
        service = EosAllocationPlanService(
            repository=SqlAlchemyEosAllocationPlanRepository(eos.session_factory),
            authorization_source=authorization_source,
        )
        created = service.release(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )
        replay = service.release(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )
        assert created["idempotency_disposition"] == "CREATED"
        assert replay["idempotency_disposition"] == "EXACT_REPLAY"
        assert created["basis_priority"] == 4

        with oa.api_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM oa_tenant_memberships "
                    "WHERE tenant_id = :tenant_id AND subject_id = :subject_id"
                ),
                {"tenant_id": TENANT, "subject_id": APPROVER},
            )
        with pytest.raises(EosAllocationPlanError) as denied:
            service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
        assert denied.value.status_code == 403
        with eos.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(EOS_COST_ALLOCATION_PLAN_TABLE)
                    .where(EOS_COST_ALLOCATION_PLAN_TABLE.c.tenant_id == TENANT)
                )
                == 1
            )
    finally:
        assert all(value == 0 for value in _cleanup_wc(wc_engine).values())
        assert all(value == 0 for value in _cleanup_eos(eos).values())
        assert all(value == 0 for value in _cleanup_oa(oa.api_engine).values())
        wc_engine.dispose()
        eos.dispose()
        _dispose_oa(oa)
