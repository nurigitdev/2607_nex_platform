from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, date, datetime

import psycopg
import pytest
from nex_eos import (
    D12_CATALOG_DIGEST,
    EOS_ACCOUNT_TABLE,
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_BUDGET_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_ORG_UNIT_TABLE,
    EOS_PROJECT_BUDGET_BINDING_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_TABLE,
    EOS_PROJECT_WORK_CODE_ENTRY_TABLE,
    EOS_PROJECT_WORK_CODE_SET_TABLE,
    MANDATORY_D12_CODES_HASH,
    MANDATORY_D12_WORK_CODE_IDS,
    EosBudgetService,
    EosProjectBudgetBindingService,
    SqlAlchemyEosBudgetRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectBudgetBindingRepository,
    budget_payload_hash,
    build_eos_database_runtime,
    parse_budget_commit,
    parse_project_budget_binding_commit,
    project_budget_binding_payload_hash,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import func, make_url, select

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_MYBEE_S7_01_POSTGRES_SMOKE") == "1"
TENANT = "W501"
COMPANY_ID = "75000000-0000-4000-8000-000000000001"
ACCOUNT_ID = "75000000-0000-4000-8000-000000000002"
NVT_ID = "75000000-0000-4000-8000-000000000003"
PROJECT_ID = "75000000-0000-4000-8000-000000000004"
WORK_SET_ID = "75000000-0000-4000-8000-000000000005"
BUDGET_ID = "75000000-0000-4000-8000-000000000006"
BINDING_ID = "75000000-0000-4000-8000-000000000007"
POLICY_ID = "75000000-0000-4000-8000-000000000008"
ORG_ID = "75000000-0000-4000-8000-000000000009"
BUDGET_APPROVAL_OPERATION = "75000000-0000-4000-8000-000000000010"
BINDING_APPROVAL_OPERATION = "75000000-0000-4000-8000-000000000011"
BUDGET_OPERATION = "75000000-0000-4000-8000-000000000012"
BINDING_OPERATION = "75000000-0000-4000-8000-000000000013"
BUDGET_PROOF = "75000000-0000-4000-8000-000000000014"
BINDING_PROOF = "75000000-0000-4000-8000-000000000015"
APPROVER = "employee-budget-pg"
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected S7-01 nex_eos_test PostgreSQL smoke is disabled",
)


class AuthorizationSource:
    def effective_authorization(self, *, tenant_id, subject_id):
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": ["finance:budget:approve", "finance:budget:bind"],
            "revision_hash": "f" * 64,
        }


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _budget_payload():
    payload = {
        "schema_version": "eos_budget_commit.v1",
        "business_operation_id": BUDGET_OPERATION,
        "idempotency_key": "w50-budget-commit",
        "payload_hash": HASH_A,
        "approval_proof_id": BUDGET_PROOF,
        "budget": {
            "budget_id": BUDGET_ID,
            "budget_version": 1,
            "fiscal_year": 2026,
            "account_id": ACCOUNT_ID,
            "budget_category": "PROJECT_OPERATING_EXPENSE",
            "approved_currency": "KRW",
            "approved_functional_amount": "1000.0000",
            "source_ref": "approved-document:w50-budget",
            "source_hash": HASH_B,
        },
    }
    command = parse_budget_commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
    )
    payload["payload_hash"] = budget_payload_hash(command)
    return payload


def _binding_payload():
    payload = {
        "schema_version": "eos_project_budget_binding_commit.v1",
        "business_operation_id": BINDING_OPERATION,
        "idempotency_key": "w50-project-budget-bind",
        "payload_hash": HASH_A,
        "approval_proof_id": BINDING_PROOF,
        "binding": {
            "binding_id": BINDING_ID,
            "binding_version": 1,
            "project_id": PROJECT_ID,
            "project_code": "W501D260001",
            "budget_id": BUDGET_ID,
            "budget_version": 1,
            "allocation_mode": "LIMIT_AMOUNT",
            "allocation_limit_amount": "750.0000",
            "allocation_percent": None,
            "approved_work_set_revision": 1,
            "valid_from": "2026-01-01",
            "valid_until": None,
        },
    }
    command = parse_project_budget_binding_commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
    )
    payload["payload_hash"] = project_budget_binding_payload_hash(command)
    return payload


def _seed_foundation(runtime):
    with runtime.engine.begin() as connection:
        connection.execute(
            EOS_NVT_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                nvt_project_id=NVT_ID,
                nvt_project_code="W501-NVT",
                name="W50 Budget NVT",
                status="ACTIVE",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            EOS_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code="W501D260001",
                project_request_code="W501R260001",
                purpose_type="D",
                origin="APPROVED_APPLICATION",
                approval_evidence_ref="eos.approval:project",
                approval_evidence_hash=HASH_A,
                project_owner_subject_id="employee-owner",
                project_manager_subject_id="employee-pm",
                agent_sync_state="IN_SYNC",
                authorization_sync_state="IN_SYNC",
                authorization_version=1,
                name="W50 Budget Project",
                parent_project_id=None,
                nvt_project_id=NVT_ID,
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
        connection.execute(
            EOS_LEGAL_ENTITY_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                company_code="W501",
                name="W50 Budget Company",
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
            EOS_ACCOUNT_TABLE.insert().values(
                tenant_id=TENANT,
                account_id=ACCOUNT_ID,
                account_code="510100",
                name="Project expense",
                category="EXPENSE",
                account_type="OPERATING_EXPENSE",
                status="ACTIVE",
                effective_from=date(2026, 1, 1),
                effective_until=None,
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
        connection.execute(
            EOS_PROJECT_WORK_CODE_SET_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                work_set_id=WORK_SET_ID,
                revision=1,
                catalog_id="mybee.fl.d12.project-governance",
                catalog_version="1.0.0",
                catalog_digest=D12_CATALOG_DIGEST,
                template_ref="mybee.template:d12",
                template_version="1.0.0",
                mandatory_codes_hash=MANDATORY_D12_CODES_HASH,
                approved_proof_hash=HASH_A,
                approved_by_subject_id=APPROVER,
                pm_subject_id="employee-pm",
                pa_agent_id="pa-budget-project",
                pa_identity_evidence_hash=HASH_B,
                state="APPROVED",
                effective_from=date(2026, 1, 1),
                work_set_hash=_hash("work-set"),
                created_at=NOW,
            )
        )
        connection.execute(
            EOS_PROJECT_WORK_CODE_ENTRY_TABLE.insert(),
            [
                {
                    "tenant_id": TENANT,
                    "project_id": PROJECT_ID,
                    "work_set_id": WORK_SET_ID,
                    "work_set_revision": 1,
                    "work_code_id": work_code_id,
                    "ordinal": ordinal,
                    "mandatory": True,
                }
                for ordinal, work_code_id in enumerate(
                    MANDATORY_D12_WORK_CODE_IDS, start=1
                )
            ],
        )
        connection.execute(
            EOS_ORG_UNIT_TABLE.insert().values(
                tenant_id=TENANT,
                org_unit_id=ORG_ID,
                org_unit_code="W501-FINANCE",
                name="W501 Finance",
                org_unit_type="TEAM",
                parent_org_unit_id=None,
                status="ACTIVE",
                effective_from=NOW,
                effective_until=None,
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            EOS_APPROVAL_POLICY_TABLE.insert().values(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="finance.budget.w50",
                version=1,
                name="W50 Budget approval",
                approval_domain="BUSINESS_FORMAL",
                risk_level=None,
                minimum_amount=None,
                maximum_amount=None,
                project_id=PROJECT_ID,
                account_id=ACCOUNT_ID,
                transaction_type="BUDGET",
                status="ACTIVE",
                effective_from=NOW,
                effective_until=None,
                policy_hash=_hash("policy"),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            EOS_APPROVAL_POLICY_STAGE_TABLE.insert().values(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                stage_order=1,
                position_type="TEAM_LEAD",
                quorum_count=1,
                separation_policy="REQUESTER_EXCLUDED",
            )
        )


def _seed_approval(
    runtime, *, proof_id, approval_operation_id, operation, ref, payload_hash
):
    instance_id = str(uuid.uuid5(uuid.NAMESPACE_URL, proof_id + "instance"))
    stage_id = str(uuid.uuid5(uuid.NAMESPACE_URL, proof_id + "stage"))
    decision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, proof_id + "decision"))
    policy_hash = _hash("policy")
    with runtime.engine.begin() as connection:
        connection.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=approval_operation_id,
                idempotency_key=f"approval-operation-{proof_id}",
                operation=operation,
                payload_hash=payload_hash,
                commit_state="COMMITTED",
                result_json={"approval": "requested"},
                created_at=NOW,
                committed_at=NOW,
            )
        )
        connection.execute(
            EOS_APPROVAL_INSTANCE_TABLE.insert().values(
                tenant_id=TENANT,
                approval_instance_id=instance_id,
                idempotency_key=f"approval-instance-{proof_id}",
                approval_policy_id=POLICY_ID,
                policy_version=1,
                policy_hash=policy_hash,
                approval_domain="BUSINESS_FORMAL",
                business_operation_id=approval_operation_id,
                operation=operation,
                protected_operation_ref=ref,
                payload_hash=payload_hash,
                write_intent_hash=_hash(proof_id + "intent"),
                requester_ref_type="oa.user",
                requester_id="employee-requester",
                org_unit_id=ORG_ID,
                project_id=PROJECT_ID,
                state="APPROVED",
                active_stage_order=None,
                stage_count=1,
                version=2,
                expires_at=None,
                correlation_id=f"correlation-{proof_id}",
                causation_id=f"causation-{proof_id}",
                binding_hash=_hash(proof_id + "binding"),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            EOS_APPROVAL_STAGE_TABLE.insert().values(
                tenant_id=TENANT,
                approval_stage_id=stage_id,
                approval_instance_id=instance_id,
                stage_order=1,
                policy_stage_order=1,
                position_type="TEAM_LEAD",
                quorum_count=1,
                separation_policy="REQUESTER_EXCLUDED",
                state="APPROVED",
                version=2,
                activated_at=NOW,
                decided_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            EOS_APPROVAL_DECISION_TABLE.insert().values(
                tenant_id=TENANT,
                approval_decision_id=str(uuid.uuid4()),
                approval_instance_id=instance_id,
                approval_stage_id=stage_id,
                wc_approval_work_item_id=str(uuid.uuid4()),
                wc_decision_id=decision_id,
                decision="APPROVE",
                decision_version=1,
                decided_by_ref_type="oa.user",
                decided_by_id=APPROVER,
                decision_comment="approved",
                authorized_by_oa=True,
                oa_decision_ref="oa:budget-approved",
                authorization_revision_hash=_hash(proof_id + "oa"),
                authorization_checked_at=NOW,
                decided_at=NOW,
                decision_hash=_hash(proof_id + "decision"),
                recorded_at=NOW,
            )
        )
        connection.execute(
            EOS_APPROVAL_PROOF_TABLE.insert().values(
                tenant_id=TENANT,
                approval_proof_id=proof_id,
                approval_instance_id=instance_id,
                business_operation_id=approval_operation_id,
                final_approval_stage_id=stage_id,
                final_wc_decision_id=decision_id,
                approval_domain="BUSINESS_FORMAL",
                protected_operation_ref=ref,
                payload_hash=payload_hash,
                write_intent_hash=_hash(proof_id + "intent"),
                policy_hash=policy_hash,
                instance_binding_hash=_hash(proof_id + "binding"),
                decision_chain_hash=_hash(proof_id + "chain"),
                final_decision_hash=_hash(proof_id + "decision"),
                proof_version=1,
                proof_hash=_hash(proof_id + "proof"),
                issued_at=NOW,
            )
        )


def test_actual_nex_eos_test_budget_and_project_binding_smoke() -> None:
    url = make_url(DATABASE_URL)
    assert (url.username, url.database) == ("nex_eos_user", "nex_eos_test")
    schema_name = f"s7_01_budget_{uuid.uuid4().hex[:12]}"
    with (
        psycopg.connect(
            psycopg_database_url(DATABASE_URL), autocommit=True
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = url.update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    ).render_as_string(hide_password=False)
    migration = run_service_migrations(
        "nex-eos", database_url=scoped_url, profile="test"
    )
    assert migration.applied[-1] == "2542_eos_budget_project_binding"
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    try:
        _seed_foundation(runtime)
        budget_payload = _budget_payload()
        _seed_approval(
            runtime,
            proof_id=BUDGET_PROOF,
            approval_operation_id=BUDGET_APPROVAL_OPERATION,
            operation="FINANCE.BUDGET.COMMIT",
            ref=f"eos.budget:{BUDGET_ID}:version:1",
            payload_hash=budget_payload["payload_hash"],
        )
        coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
            runtime.session_factory, clock=lambda: NOW
        )
        source = AuthorizationSource()
        budget_service = EosBudgetService(
            repository=SqlAlchemyEosBudgetRepository(runtime.session_factory),
            coordinator=coordinator,
            authorization_source=source,
            clock=lambda: NOW,
        )
        created_budget = budget_service.commit(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            payload=budget_payload,
        )
        binding_payload = _binding_payload()
        _seed_approval(
            runtime,
            proof_id=BINDING_PROOF,
            approval_operation_id=BINDING_APPROVAL_OPERATION,
            operation="PROJECT.BUDGET_BINDING.COMMIT",
            ref=f"eos.project-budget-binding:{BINDING_ID}:version:1",
            payload_hash=binding_payload["payload_hash"],
        )
        binding_service = EosProjectBudgetBindingService(
            repository=SqlAlchemyEosProjectBudgetBindingRepository(
                runtime.session_factory
            ),
            coordinator=coordinator,
            authorization_source=source,
            clock=lambda: NOW,
        )
        created_binding = binding_service.commit(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            payload=binding_payload,
        )
        replay = binding_service.commit(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            payload=binding_payload,
        )
        assert created_budget["idempotency_disposition"] == "CREATED"
        assert created_binding["idempotency_disposition"] == "CREATED"
        assert replay["idempotency_disposition"] == "REPLAYED"
        with runtime.engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(EOS_BUDGET_TABLE)
                    .where(EOS_BUDGET_TABLE.c.tenant_id == TENANT)
                )
                == 1
            )
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(EOS_PROJECT_BUDGET_BINDING_TABLE)
                    .where(EOS_PROJECT_BUDGET_BINDING_TABLE.c.tenant_id == TENANT)
                )
                == 1
            )
    finally:
        runtime.engine.dispose()
        with (
            psycopg.connect(
                psycopg_database_url(DATABASE_URL), autocommit=True
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            cursor.execute(
                "SELECT count(*) FROM pg_namespace WHERE nspname = %s",
                (schema_name,),
            )
            assert cursor.fetchone()[0] == 0
