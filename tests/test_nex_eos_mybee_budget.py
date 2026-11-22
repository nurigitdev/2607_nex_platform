from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos import (
    D12_CATALOG_DIGEST,
    EOS_ACCOUNT_TABLE,
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
    EOS_BUDGET_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_BUDGET_BINDING_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_TABLE,
    EOS_PROJECT_WORK_CODE_SET_TABLE,
    MANDATORY_D12_CODES_HASH,
    EosBudgetError,
    EosBudgetService,
    EosProjectBudgetBindingError,
    EosProjectBudgetBindingService,
    SqlAlchemyEosBudgetRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectBudgetBindingRepository,
    budget_api,
    budget_payload_hash,
    parse_budget_commit,
    parse_project_budget_binding_commit,
    project_budget_binding_payload_hash,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_eos.budget_api import register_budget_routes
from run_migrations import load_migrations
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "VO00"
COMPANY_ID = "74000000-0000-4000-8000-000000000001"
ACCOUNT_ID = "74000000-0000-4000-8000-000000000002"
BUDGET_ID = "74000000-0000-4000-8000-000000000003"
PROJECT_ID = "74000000-0000-4000-8000-000000000004"
BINDING_ID = "74000000-0000-4000-8000-000000000005"
WORK_SET_ID = "74000000-0000-4000-8000-000000000006"
BUDGET_PROOF = "74000000-0000-4000-8000-000000000007"
BINDING_PROOF = "74000000-0000-4000-8000-000000000008"
BUDGET_APPROVAL_OPERATION = "74000000-0000-4000-8000-000000000009"
BINDING_APPROVAL_OPERATION = "74000000-0000-4000-8000-000000000010"
BUDGET_OPERATION = "74000000-0000-4000-8000-000000000011"
BINDING_OPERATION = "74000000-0000-4000-8000-000000000012"
APPROVER = "employee-budget-2001"
NOW = datetime(2026, 11, 13, 8, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


class AuthorizationSource:
    def __init__(self, *, scopes=None, active=True, fail=None, revision="f" * 64):
        self.scopes = scopes or [
            "finance:budget:approve",
            "finance:budget:bind",
        ]
        self.active = active
        self.fail = fail
        self.revision = revision
        self.calls = []

    def effective_authorization(self, *, tenant_id, subject_id):
        self.calls.append((tenant_id, subject_id))
        if self.fail is not None:
            raise self.fail
        return {
            "active": self.active,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": self.scopes,
            "revision_hash": self.revision,
        }


def _budget_payload(*, version=1, operation=BUDGET_OPERATION, amount="1000.0000"):
    value = {
        "schema_version": "eos_budget_commit.v1",
        "business_operation_id": operation,
        "idempotency_key": f"budget-{version}",
        "payload_hash": HASH_A,
        "approval_proof_id": BUDGET_PROOF,
        "budget": {
            "budget_id": BUDGET_ID,
            "budget_version": version,
            "fiscal_year": 2026,
            "account_id": ACCOUNT_ID,
            "budget_category": "PROJECT_OPERATING_EXPENSE",
            "approved_currency": "KRW",
            "approved_functional_amount": amount,
            "source_ref": "approved-document:budget-2026",
            "source_hash": HASH_B,
        },
    }
    command = parse_budget_commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=value
    )
    value["payload_hash"] = budget_payload_hash(command)
    return value


def _binding_payload(
    *,
    version=1,
    operation=BINDING_OPERATION,
    mode="LIMIT_AMOUNT",
    amount="600.0000",
    percent=None,
):
    value = {
        "schema_version": "eos_project_budget_binding_commit.v1",
        "business_operation_id": operation,
        "idempotency_key": f"project-budget-{version}",
        "payload_hash": HASH_A,
        "approval_proof_id": BINDING_PROOF,
        "binding": {
            "binding_id": BINDING_ID,
            "binding_version": version,
            "project_id": PROJECT_ID,
            "project_code": "VO00D260001",
            "budget_id": BUDGET_ID,
            "budget_version": 1,
            "allocation_mode": mode,
            "allocation_limit_amount": amount,
            "allocation_percent": percent,
            "approved_work_set_revision": 1,
            "valid_from": "2026-01-01",
            "valid_until": None,
        },
    }
    command = parse_project_budget_binding_commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=value
    )
    value["payload_hash"] = project_budget_binding_payload_hash(command)
    return value


def _runtime(*, auth=None):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        EOS_BUSINESS_OPERATION_TABLE,
        EOS_IDEMPOTENCY_TABLE,
        EOS_OUTBOX_TABLE,
        EOS_LEGAL_ENTITY_TABLE,
        EOS_ACCOUNT_TABLE,
        EOS_PROJECT_TABLE,
        EOS_PROJECT_COMPANY_BINDING_TABLE,
        EOS_PROJECT_WORK_CODE_SET_TABLE,
        EOS_APPROVAL_INSTANCE_TABLE,
        EOS_APPROVAL_DECISION_TABLE,
        EOS_APPROVAL_PROOF_TABLE,
        EOS_BUDGET_TABLE,
        EOS_PROJECT_BUDGET_BINDING_TABLE,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    source = auth or AuthorizationSource()
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions,
        id_factory=iter(
            str(uuid.UUID(int=value)) for value in range(100, 500)
        ).__next__,
        clock=lambda: NOW,
    )
    budget_repository = SqlAlchemyEosBudgetRepository(sessions)
    binding_repository = SqlAlchemyEosProjectBudgetBindingRepository(sessions)
    return SimpleNamespace(
        engine=engine,
        sessions=sessions,
        auth=source,
        budget_repository=budget_repository,
        binding_repository=binding_repository,
        budget=EosBudgetService(
            repository=budget_repository,
            coordinator=coordinator,
            authorization_source=source,
            clock=lambda: NOW,
        ),
        binding=EosProjectBudgetBindingService(
            repository=binding_repository,
            coordinator=coordinator,
            authorization_source=source,
            clock=lambda: NOW,
        ),
    )


def _seed_authority(runtime, *, payload_hash, proof_id, operation_id, operation, ref):
    instance_id = str(uuid.uuid5(uuid.NAMESPACE_URL, proof_id + "instance"))
    stage_id = str(uuid.uuid5(uuid.NAMESPACE_URL, proof_id + "stage"))
    decision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, proof_id + "decision"))

    def evidence_hash(suffix):
        return "sha256:" + hashlib.sha256((proof_id + suffix).encode()).hexdigest()

    policy_hash = evidence_hash("policy")
    with runtime.sessions.begin() as session:
        session.execute(
            EOS_APPROVAL_INSTANCE_TABLE.insert().values(
                tenant_id=TENANT,
                approval_instance_id=instance_id,
                idempotency_key=f"approval-{proof_id}",
                approval_policy_id=str(uuid.uuid4()),
                policy_version=1,
                policy_hash=policy_hash,
                approval_domain="BUSINESS_FORMAL",
                business_operation_id=operation_id,
                operation=operation,
                protected_operation_ref=ref,
                payload_hash=payload_hash,
                write_intent_hash=HASH_A,
                requester_ref_type="oa.user",
                requester_id="employee-requester",
                org_unit_id=str(uuid.uuid4()),
                project_id=PROJECT_ID,
                state="APPROVED",
                active_stage_order=None,
                stage_count=1,
                version=2,
                expires_at=None,
                correlation_id="budget-correlation",
                causation_id="budget-causation",
                binding_hash=evidence_hash("binding"),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
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
                authorization_revision_hash=HASH_A,
                authorization_checked_at=NOW,
                decided_at=NOW,
                decision_hash=evidence_hash("decision"),
                recorded_at=NOW,
            )
        )
        session.execute(
            EOS_APPROVAL_PROOF_TABLE.insert().values(
                tenant_id=TENANT,
                approval_proof_id=proof_id,
                approval_instance_id=instance_id,
                business_operation_id=operation_id,
                final_approval_stage_id=stage_id,
                final_wc_decision_id=decision_id,
                approval_domain="BUSINESS_FORMAL",
                protected_operation_ref=ref,
                payload_hash=payload_hash,
                write_intent_hash=HASH_A,
                policy_hash=policy_hash,
                instance_binding_hash=evidence_hash("instance"),
                decision_chain_hash=evidence_hash("chain"),
                final_decision_hash=evidence_hash("decision"),
                proof_version=1,
                proof_hash=evidence_hash("proof"),
                issued_at=NOW,
            )
        )


def _seed_business_foundation(runtime):
    with runtime.sessions.begin() as session:
        session.execute(
            EOS_LEGAL_ENTITY_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                company_code="VO00",
                name="MyBee Company",
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
        session.execute(
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
        session.execute(
            EOS_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code="VO00D260001",
                project_request_code="VO00R260001",
                purpose_type="D",
                origin="APPROVED_APPLICATION",
                approval_evidence_ref="eos.approval:project",
                approval_evidence_hash=HASH_A,
                project_owner_subject_id="employee-owner",
                project_manager_subject_id="employee-pm",
                agent_sync_state="IN_SYNC",
                authorization_sync_state="IN_SYNC",
                authorization_version=1,
                name="Budget Project",
                parent_project_id=None,
                nvt_project_id=str(uuid.uuid4()),
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
        session.execute(
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
                approved_proof_hash=HASH_C,
                approved_by_subject_id=APPROVER,
                pm_subject_id="employee-pm",
                pa_agent_id="pa-budget-project",
                pa_identity_evidence_hash=HASH_A,
                state="APPROVED",
                effective_from=date(2026, 1, 1),
                work_set_hash=HASH_C,
                created_at=NOW,
            )
        )


def _prepare_budget(runtime):
    payload = _budget_payload()
    _seed_authority(
        runtime,
        payload_hash=payload["payload_hash"],
        proof_id=BUDGET_PROOF,
        operation_id=BUDGET_APPROVAL_OPERATION,
        operation="FINANCE.BUDGET.COMMIT",
        ref=f"eos.budget:{BUDGET_ID}:version:1",
    )
    return runtime.budget.commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
    )


def test_s7_01_migration_and_openapi_contract_are_additive() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2542_eos_budget_project_binding"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_budget" in compact
    assert "create table if not exists eos_project_budget_binding" in compact
    assert "approved_functional_amount > 0" in compact
    assert "allocation_percent > 0" in compact
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for table in (EOS_BUDGET_TABLE, EOS_PROJECT_BUDGET_BINDING_TABLE)
        for constraint in table.constraints
    )
    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    assert (
        spec["paths"]["/internal/v2/finance/budgets"]["post"]["operationId"]
        == "FINANCE.BUDGET.COMMIT"
    )
    assert (
        spec["paths"]["/internal/v2/finance/project-budget-bindings"]["post"][
            "x-nex-business-scope"
        ]
        == "finance:budget:bind"
    )
    assert (
        spec["paths"]["/internal/v2/projects/{project_id}/budget-bindings"]["get"][
            "x-nex-side-effect-free"
        ]
        is True
    )


def test_budget_commit_replay_and_read_preserve_one_approved_sor() -> None:
    runtime = _runtime()
    _seed_business_foundation(runtime)
    created = _prepare_budget(runtime)
    replay = runtime.budget.commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=_budget_payload()
    )
    loaded = runtime.budget.get(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        budget_id=BUDGET_ID,
        budget_version=1,
    )
    assert created["idempotency_disposition"] == "CREATED"
    assert replay["idempotency_disposition"] == "REPLAYED"
    assert loaded["approved_functional_amount"] == "1000.0000"
    assert loaded["state"] == "APPROVED"
    with runtime.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EOS_BUDGET_TABLE)) == 1
        assert session.scalar(select(func.count()).select_from(EOS_OUTBOX_TABLE)) == 1
    runtime.engine.dispose()


def test_project_binding_is_read_only_link_and_exact_replay() -> None:
    runtime = _runtime()
    _seed_business_foundation(runtime)
    _prepare_budget(runtime)
    payload = _binding_payload()
    _seed_authority(
        runtime,
        payload_hash=payload["payload_hash"],
        proof_id=BINDING_PROOF,
        operation_id=BINDING_APPROVAL_OPERATION,
        operation="PROJECT.BUDGET_BINDING.COMMIT",
        ref=f"eos.project-budget-binding:{BINDING_ID}:version:1",
    )
    created = runtime.binding.commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
    )
    replay = runtime.binding.commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
    )
    listed = runtime.binding.list_for_project(
        tenant_id=TENANT, company_id=COMPANY_ID, project_id=PROJECT_ID
    )
    assert created["idempotency_disposition"] == "CREATED"
    assert replay["idempotency_disposition"] == "REPLAYED"
    assert listed["bindings"][0]["allocation_limit_amount"] == "600.0000"
    with runtime.sessions() as session:
        budget = session.execute(select(EOS_BUDGET_TABLE)).mappings().one()
        assert Decimal(budget["approved_functional_amount"]) == Decimal("1000.0000")
    runtime.engine.dispose()


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda value: value.update(extra="bad"), "payload"),
        (lambda value: value.update(schema_version="v0"), "schema_version"),
        (lambda value: value.update(budget={}), "budget"),
        (lambda value: value.update(payload_hash="bad"), "payload_hash"),
        (
            lambda value: value.update(business_operation_id=123),
            "business_operation_id",
        ),
        (lambda value: value.update(idempotency_key=" "), "idempotency_key"),
        (lambda value: value["budget"].update(budget_version=True), "budget_version"),
        (lambda value: value["budget"].update(account_id=123), "account_id"),
        (lambda value: value["budget"].update(fiscal_year=1999), "fiscal_year"),
        (
            lambda value: value["budget"].update(approved_functional_amount="0.0000"),
            "approved_functional_amount",
        ),
        (
            lambda value: value["budget"].update(approved_currency="krw"),
            "approved_currency",
        ),
    ],
)
def test_budget_command_fail_closed_matrix(mutate, error) -> None:
    payload = _budget_payload()
    mutate(payload)
    with pytest.raises(EosBudgetError, match=error):
        parse_budget_commit(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)


@pytest.mark.parametrize(
    "change",
    [
        {"extra": "bad"},
        {"schema_version": "bad"},
        {"binding": {}},
        {
            "allocation_mode": "PERCENTAGE",
            "allocation_limit_amount": "1.0000",
            "allocation_percent": None,
        },
        {"allocation_mode": "SHARE"},
        {"allocation_limit_amount": "bad"},
        {"allocation_limit_amount": "0.0000"},
        {"allocation_limit_amount": None, "allocation_percent": "1.100000000000"},
        {"valid_from": None},
        {"valid_from": "not-a-date"},
        {"valid_until": "2025-12-31"},
        {"binding_id": 123},
        {"project_code": "bad"},
        {"approved_work_set_revision": 0},
    ],
)
def test_binding_command_fail_closed_matrix(change) -> None:
    payload = _binding_payload()
    if "extra" in change:
        payload["extra"] = change["extra"]
    elif "schema_version" in change:
        payload["schema_version"] = change["schema_version"]
    elif "binding" in change:
        payload["binding"] = change["binding"]
    else:
        payload["binding"].update(change)
    with pytest.raises(EosProjectBudgetBindingError):
        parse_project_budget_binding_commit(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )


@pytest.mark.parametrize(
    "auth",
    [
        AuthorizationSource(active=False),
        AuthorizationSource(scopes=["finance:other"]),
        AuthorizationSource(revision="bad"),
        AuthorizationSource(fail=AuthorizationSubjectDenied("inactive")),
        AuthorizationSource(fail=RuntimeError("offline")),
    ],
)
def test_budget_authorization_denial_has_zero_mutation(auth) -> None:
    runtime = _runtime(auth=auth)
    _seed_business_foundation(runtime)
    payload = _budget_payload()
    _seed_authority(
        runtime,
        payload_hash=payload["payload_hash"],
        proof_id=BUDGET_PROOF,
        operation_id=BUDGET_APPROVAL_OPERATION,
        operation="FINANCE.BUDGET.COMMIT",
        ref=f"eos.budget:{BUDGET_ID}:version:1",
    )
    with pytest.raises(EosBudgetError) as exc:
        runtime.budget.commit(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert exc.value.status_code in {403, 503}
    with runtime.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EOS_BUDGET_TABLE)) == 0
    runtime.engine.dispose()


def test_budget_rejects_hash_proof_currency_account_and_revision_conflicts() -> None:
    runtime = _runtime()
    _seed_business_foundation(runtime)
    bad_hash = _budget_payload()
    bad_hash["payload_hash"] = HASH_A
    with pytest.raises(EosBudgetError, match="payload_hash"):
        runtime.budget.commit(tenant_id=TENANT, company_id=COMPANY_ID, payload=bad_hash)

    payload = _budget_payload()
    _seed_authority(
        runtime,
        payload_hash=HASH_A,
        proof_id=BUDGET_PROOF,
        operation_id=BUDGET_APPROVAL_OPERATION,
        operation="FINANCE.BUDGET.COMMIT",
        ref=f"eos.budget:{BUDGET_ID}:version:1",
    )
    with pytest.raises(EosBudgetError, match="exact governed payload"):
        runtime.budget.commit(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    with runtime.sessions.begin() as session:
        session.execute(EOS_APPROVAL_PROOF_TABLE.delete())
        session.execute(EOS_APPROVAL_DECISION_TABLE.delete())
        session.execute(EOS_APPROVAL_INSTANCE_TABLE.delete())
    _seed_authority(
        runtime,
        payload_hash=payload["payload_hash"],
        proof_id=BUDGET_PROOF,
        operation_id=BUDGET_APPROVAL_OPERATION,
        operation="FINANCE.BUDGET.COMMIT",
        ref=f"eos.budget:{BUDGET_ID}:version:1",
    )
    with runtime.sessions.begin() as session:
        session.execute(
            update(EOS_LEGAL_ENTITY_TABLE).values(functional_currency="USD")
        )
    with pytest.raises(EosBudgetError, match="functional currency"):
        runtime.budget.commit(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    runtime.engine.dispose()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda session: None, "LegalEntity was not found"),
        (
            lambda session: session.execute(
                update(EOS_LEGAL_ENTITY_TABLE).values(status="INACTIVE")
            ),
            "active LegalEntity",
        ),
        (
            lambda session: session.execute(EOS_ACCOUNT_TABLE.delete()),
            "account was not found",
        ),
        (
            lambda session: session.execute(
                update(EOS_ACCOUNT_TABLE).values(status="INACTIVE")
            ),
            "account must be active",
        ),
    ],
)
def test_budget_repository_rejects_missing_or_inactive_authorities(
    mutation, message
) -> None:
    runtime = _runtime()
    if "LegalEntity was not found" not in message:
        _seed_business_foundation(runtime)
    command = parse_budget_commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=_budget_payload()
    )
    with runtime.sessions.begin() as session:
        mutation(session)
        with pytest.raises(EosBudgetError, match=message):
            runtime.budget_repository.create_in_session(
                session,
                command,
                {
                    "decided_by_id": APPROVER,
                    "approval_proof_ref": f"eos.approval-proof:{BUDGET_PROOF}",
                },
                created_at=NOW,
            )
    runtime.engine.dispose()


def test_budget_and_binding_require_proof_and_next_revision() -> None:
    runtime = _runtime()
    _seed_business_foundation(runtime)
    with pytest.raises(EosBudgetError, match="approval proof was not found"):
        runtime.budget.commit(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=_budget_payload()
        )
    _prepare_budget(runtime)
    version_gap = parse_budget_commit(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        payload=_budget_payload(
            version=3, operation="74000000-0000-4000-8000-000000000099"
        ),
    )
    with (
        runtime.sessions.begin() as session,
        pytest.raises(EosBudgetError, match="next immutable revision 2"),
    ):
        runtime.budget_repository.create_in_session(
            session,
            version_gap,
            {
                "decided_by_id": APPROVER,
                "approval_proof_ref": f"eos.approval-proof:{BUDGET_PROOF}",
            },
            created_at=NOW,
        )
    with pytest.raises(
        EosProjectBudgetBindingError, match="approval proof was not found"
    ):
        runtime.binding.commit(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=_binding_payload()
        )
    bad_hash = _binding_payload()
    bad_hash["payload_hash"] = HASH_A
    with pytest.raises(EosProjectBudgetBindingError, match="payload_hash"):
        runtime.binding.commit(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=bad_hash
        )
    runtime.engine.dispose()


@pytest.mark.parametrize(
    ("table", "message"),
    [
        (EOS_PROJECT_TABLE, "Project identity was not found"),
        (EOS_PROJECT_COMPANY_BINDING_TABLE, "company binding"),
        (EOS_BUDGET_TABLE, "Budget revision was not found"),
        (EOS_PROJECT_WORK_CODE_SET_TABLE, "WorkCodeSet revision was not found"),
    ],
)
def test_binding_repository_requires_all_authoritative_references(
    table, message
) -> None:
    runtime = _runtime()
    _seed_business_foundation(runtime)
    _prepare_budget(runtime)
    command = parse_project_budget_binding_commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=_binding_payload()
    )
    with runtime.sessions.begin() as session:
        session.execute(table.delete())
        with pytest.raises(EosProjectBudgetBindingError, match=message):
            runtime.binding_repository.create_in_session(
                session,
                command,
                {
                    "decided_by_id": APPROVER,
                    "approval_proof_ref": f"eos.approval-proof:{BINDING_PROOF}",
                },
                created_at=NOW,
            )
    runtime.engine.dispose()


def test_percentage_binding_projects_wire_values_and_enforces_total_capacity() -> None:
    runtime = _runtime()
    _seed_business_foundation(runtime)
    _prepare_budget(runtime)
    payload = _binding_payload(mode="PERCENTAGE", amount=None, percent="0.600000000000")
    payload["binding"]["valid_until"] = "2026-12-31"
    payload["payload_hash"] = project_budget_binding_payload_hash(
        parse_project_budget_binding_commit(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )
    )
    _seed_authority(
        runtime,
        payload_hash=payload["payload_hash"],
        proof_id=BINDING_PROOF,
        operation_id=BINDING_APPROVAL_OPERATION,
        operation="PROJECT.BUDGET_BINDING.COMMIT",
        ref=f"eos.project-budget-binding:{BINDING_ID}:version:1",
    )
    runtime.binding.commit(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    listed = runtime.binding.list_for_project(
        tenant_id=TENANT, company_id=COMPANY_ID, project_id=PROJECT_ID
    )
    assert listed["bindings"][0]["allocation_limit_amount"] is None
    assert listed["bindings"][0]["allocation_percent"] == "0.600000000000"
    assert listed["bindings"][0]["valid_until"] == "2026-12-31"

    second_id = "74000000-0000-4000-8000-000000000071"
    second_proof = "74000000-0000-4000-8000-000000000072"
    second_operation = "74000000-0000-4000-8000-000000000073"
    second_approval_operation = "74000000-0000-4000-8000-000000000074"
    second = _binding_payload(
        operation=second_operation,
        mode="PERCENTAGE",
        amount=None,
        percent="0.500000000000",
    )
    second["approval_proof_id"] = second_proof
    second["idempotency_key"] = "project-budget-percentage-second"
    second["binding"]["binding_id"] = second_id
    second["payload_hash"] = project_budget_binding_payload_hash(
        parse_project_budget_binding_commit(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=second
        )
    )
    _seed_authority(
        runtime,
        payload_hash=second["payload_hash"],
        proof_id=second_proof,
        operation_id=second_approval_operation,
        operation="PROJECT.BUDGET_BINDING.COMMIT",
        ref=f"eos.project-budget-binding:{second_id}:version:1",
    )
    with pytest.raises(EosProjectBudgetBindingError, match="percentages exceed one"):
        runtime.binding.commit(tenant_id=TENANT, company_id=COMPANY_ID, payload=second)
    runtime.engine.dispose()


def test_binding_rejects_capacity_mixed_mode_and_project_scope_conflicts() -> None:
    runtime = _runtime()
    _seed_business_foundation(runtime)
    _prepare_budget(runtime)
    payload = _binding_payload(amount="1100.0000")
    _seed_authority(
        runtime,
        payload_hash=payload["payload_hash"],
        proof_id=BINDING_PROOF,
        operation_id=BINDING_APPROVAL_OPERATION,
        operation="PROJECT.BUDGET_BINDING.COMMIT",
        ref=f"eos.project-budget-binding:{BINDING_ID}:version:1",
    )
    with pytest.raises(EosProjectBudgetBindingError, match="exceed"):
        runtime.binding.commit(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    with runtime.sessions.begin() as session:
        session.execute(
            update(EOS_PROJECT_TABLE)
            .where(EOS_PROJECT_TABLE.c.project_id == PROJECT_ID)
            .values(status="INACTIVE")
        )
    payload2 = _binding_payload(operation=str(uuid.uuid4()), amount="500.0000")
    with runtime.sessions.begin() as session:
        session.execute(EOS_APPROVAL_PROOF_TABLE.delete())
        session.execute(EOS_APPROVAL_DECISION_TABLE.delete())
        session.execute(EOS_APPROVAL_INSTANCE_TABLE.delete())
    _seed_authority(
        runtime,
        payload_hash=payload2["payload_hash"],
        proof_id=BINDING_PROOF,
        operation_id=str(uuid.uuid4()),
        operation="PROJECT.BUDGET_BINDING.COMMIT",
        ref=f"eos.project-budget-binding:{BINDING_ID}:version:1",
    )
    with pytest.raises(EosProjectBudgetBindingError, match="ACTIVE or CLOSING"):
        runtime.binding.commit(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload2
        )
    runtime.engine.dispose()


def test_missing_reads_and_repository_failures_are_typed(monkeypatch) -> None:
    runtime = _runtime()
    with pytest.raises(EosBudgetError) as budget_missing:
        runtime.budget.get(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            budget_id=BUDGET_ID,
            budget_version=1,
        )
    assert budget_missing.value.status_code == 404
    assert (
        runtime.binding.list_for_project(
            tenant_id=TENANT, company_id=COMPANY_ID, project_id=PROJECT_ID
        )["bindings"]
        == []
    )
    monkeypatch.setattr(
        runtime.budget_repository,
        "get",
        lambda **_kwargs: (_ for _ in ()).throw(
            EosBudgetError("x", "offline", status_code=503)
        ),
    )
    with pytest.raises(EosBudgetError, match="offline"):
        runtime.budget.get(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            budget_id=BUDGET_ID,
            budget_version=1,
        )
    runtime.engine.dispose()


def test_budget_api_routes_cover_success_replay_errors_and_unavailable(
    monkeypatch,
) -> None:
    app = FastAPI()
    app.state.eos_budget_service = SimpleNamespace(
        commit=lambda **_kwargs: {"idempotency_disposition": "CREATED"},
        get=lambda **kwargs: {"operation": "FINANCE.BUDGET.GET", **kwargs},
    )
    app.state.eos_project_budget_binding_service = SimpleNamespace(
        commit=lambda **_kwargs: {"idempotency_disposition": "REPLAYED"},
        list_for_project=lambda **kwargs: {"bindings": [], **kwargs},
    )
    monkeypatch.setattr(budget_api, "_admit", lambda *_args, **_kwargs: object())
    register_budget_routes(app)
    client = TestClient(app)
    headers = {"X-NeX-Tenant-Id": TENANT, "X-NeX-Company-Id": COMPANY_ID}
    assert (
        client.post(
            "/internal/v2/finance/budgets", json={}, headers=headers
        ).status_code
        == 201
    )
    assert (
        client.get(
            f"/internal/v2/finance/budgets/{BUDGET_ID}/versions/1", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/internal/v2/finance/project-budget-bindings", json={}, headers=headers
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/internal/v2/projects/{PROJECT_ID}/budget-bindings", headers=headers
        ).status_code
        == 200
    )
    app.state.eos_budget_service = None
    assert (
        client.post(
            "/internal/v2/finance/budgets", json={}, headers=headers
        ).status_code
        == 503
    )
    assert (
        client.get(
            f"/internal/v2/finance/budgets/{BUDGET_ID}/versions/1", headers=headers
        ).status_code
        == 503
    )
    app.state.eos_project_budget_binding_service = None
    assert (
        client.post(
            "/internal/v2/finance/project-budget-bindings", json={}, headers=headers
        ).status_code
        == 503
    )
    assert (
        client.get(
            f"/internal/v2/projects/{PROJECT_ID}/budget-bindings", headers=headers
        ).status_code
        == 503
    )


def test_budget_api_routes_cover_admission_and_typed_domain_errors(monkeypatch) -> None:
    app = FastAPI()
    app.state.eos_budget_service = SimpleNamespace(
        commit=lambda **_kwargs: (_ for _ in ()).throw(
            EosBudgetError("EOS_BUDGET_CONFLICT", "conflict", status_code=409)
        ),
        get=lambda **_kwargs: (_ for _ in ()).throw(
            EosBudgetError("EOS_BUDGET_NOT_FOUND", "missing", status_code=404)
        ),
    )
    app.state.eos_project_budget_binding_service = SimpleNamespace(
        commit=lambda **_kwargs: (_ for _ in ()).throw(
            EosProjectBudgetBindingError(
                "EOS_PROJECT_BUDGET_BINDING_CONFLICT",
                "conflict",
                status_code=409,
            )
        ),
        list_for_project=lambda **_kwargs: (_ for _ in ()).throw(
            EosProjectBudgetBindingError(
                "EOS_PROJECT_BUDGET_BINDING_UNAVAILABLE",
                "offline",
                status_code=503,
                retryable=True,
            )
        ),
    )
    monkeypatch.setattr(budget_api, "_admit", lambda *_args, **_kwargs: object())
    register_budget_routes(app)
    client = TestClient(app)
    headers = {"X-NeX-Tenant-Id": TENANT, "X-NeX-Company-Id": COMPANY_ID}
    assert (
        client.post(
            "/internal/v2/finance/budgets", json={}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.get(
            f"/internal/v2/finance/budgets/{BUDGET_ID}/versions/1", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/internal/v2/finance/project-budget-bindings", json={}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.get(
            f"/internal/v2/projects/{PROJECT_ID}/budget-bindings", headers=headers
        ).status_code
        == 503
    )

    denied = budget_api.JSONResponse({"detail": "denied"}, status_code=401)
    monkeypatch.setattr(budget_api, "_admit", lambda *_args, **_kwargs: denied)
    assert (
        client.post(
            "/internal/v2/finance/budgets", json={}, headers=headers
        ).status_code
        == 401
    )
    assert (
        client.get(
            f"/internal/v2/finance/budgets/{BUDGET_ID}/versions/1", headers=headers
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/internal/v2/finance/project-budget-bindings", json={}, headers=headers
        ).status_code
        == 401
    )
    assert (
        client.get(
            f"/internal/v2/projects/{PROJECT_ID}/budget-bindings", headers=headers
        ).status_code
        == 401
    )


def test_budget_api_admission_marks_only_commands_as_write(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(
        budget_api,
        "admit_service_token_from_request",
        lambda request, authorization, **kwargs: captured.append(kwargs) or object(),
    )
    request = SimpleNamespace()
    budget_api._admit(request, None)
    budget_api._admit(request, "Bearer token", write=True)
    assert "route_class" not in captured[0]
    assert captured[1]["route_class"] == "WRITE"


def test_hashes_are_deterministic_and_domain_separated() -> None:
    budget = parse_budget_commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=_budget_payload()
    )
    binding = parse_project_budget_binding_commit(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=_binding_payload()
    )
    assert budget_payload_hash(budget) == budget_payload_hash(budget)
    assert project_budget_binding_payload_hash(
        binding
    ) == project_budget_binding_payload_hash(binding)
    assert budget_payload_hash(budget) != project_budget_binding_payload_hash(binding)
