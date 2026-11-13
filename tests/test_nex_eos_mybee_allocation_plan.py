from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_TABLE,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE,
    EosAllocationPlanError,
    EosAllocationPlanService,
    SqlAlchemyEosAllocationPlanRepository,
    allocation_plans,
)
from nex_eos.allocation_plan_api import register_allocation_plan_routes
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import load_migrations
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "VO00"
COMPANY_ID = "72000000-0000-4000-8000-000000000001"
PLAN_ID = "72000000-0000-4000-8000-000000000002"
PROJECT_A = "72000000-0000-4000-8000-000000000003"
PROJECT_B = "72000000-0000-4000-8000-000000000004"
PROOF_ID = "72000000-0000-4000-8000-000000000005"
INSTANCE_ID = "72000000-0000-4000-8000-000000000006"
OPERATION_ID = "72000000-0000-4000-8000-000000000007"
DECISION_ID = "72000000-0000-4000-8000-000000000008"
APPROVER = "employee-alloc-2001"
NOW = datetime(2026, 11, 13, 4, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64


class AuthorizationSource:
    def __init__(self, *, scopes=None, active=True, fail=None) -> None:
        self.scopes = scopes or ["finance:cost-allocation-plan:approve"]
        self.active = active
        self.fail = fail
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
            "revision_hash": "f" * 64,
        }


def _runtime(*, auth=None):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        EOS_LEGAL_ENTITY_TABLE,
        EOS_PROJECT_TABLE,
        EOS_PROJECT_COMPANY_BINDING_TABLE,
        EOS_PROJECT_WORK_ASSIGNMENT_TABLE,
        EOS_APPROVAL_INSTANCE_TABLE,
        EOS_APPROVAL_DECISION_TABLE,
        EOS_APPROVAL_PROOF_TABLE,
        EOS_COST_ALLOCATION_PLAN_TABLE,
        EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as session:
        session.execute(
            EOS_LEGAL_ENTITY_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                company_code="NURI",
                name="Nuri Company",
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
        for project_id, code in (
            (PROJECT_A, "VO00D260001"),
            (PROJECT_B, "VO00D260002"),
        ):
            session.execute(
                EOS_PROJECT_TABLE.insert().values(
                    tenant_id=TENANT,
                    project_id=project_id,
                    project_code=code,
                    project_request_code=None,
                    purpose_type="D",
                    origin="LEGACY_DIRECT",
                    approval_evidence_ref=None,
                    approval_evidence_hash=None,
                    project_owner_subject_id=None,
                    project_manager_subject_id=None,
                    agent_sync_state="IN_SYNC",
                    authorization_sync_state="IN_SYNC",
                    authorization_version=1,
                    name=code,
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
                    project_id=project_id,
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
    repository = SqlAlchemyEosAllocationPlanRepository(sessions, clock=lambda: NOW)
    source = auth or AuthorizationSource()
    return (
        engine,
        sessions,
        source,
        EosAllocationPlanService(
            repository=repository,
            authorization_source=source,
        ),
    )


def _payload(*, basis_kind="ACTUAL_WORK", revision=1, proof_id=PROOF_ID):
    return {
        "schema_version": "eos_cost_allocation_plan_release.v1",
        "approval_proof_id": proof_id,
        "plan": {
            "plan_id": PLAN_ID,
            "plan_revision": revision,
            "source_kind": "SHARED_EXPENSE",
            "scope_type": "PROJECT_SET",
            "basis_kind": basis_kind,
            "rule_release_hash": HASH_A,
            "basis_source_ref": "eos.evidence:allocation-basis:2026-11",
            "basis_source_hash": HASH_B,
            "effective_start": "2026-11-01",
            "effective_end": "2026-11-30",
            "lines": [
                {
                    "line_no": 1,
                    "project_id": PROJECT_A,
                    "project_code": "VO00D260001",
                    "work_code": None,
                    "basis_units": "6.00000000",
                    "allocation_ratio": "0.600000000000",
                    "eligibility_hash": HASH_C,
                    "confidentiality_class": "INTERNAL",
                },
                {
                    "line_no": 2,
                    "project_id": PROJECT_B,
                    "project_code": "VO00D260002",
                    "work_code": None,
                    "basis_units": "4.00000000",
                    "allocation_ratio": "0.400000000000",
                    "eligibility_hash": HASH_D,
                    "confidentiality_class": "CONFIDENTIAL",
                },
            ],
        },
    }


def _seed_proof(sessions, payload, *, proof_id=PROOF_ID, suffix=0, **overrides):
    _, candidate = allocation_plans._admit_release(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
    )
    instance_id = str(uuid.UUID(int=uuid.UUID(INSTANCE_ID).int + suffix))
    operation_id = str(uuid.UUID(int=uuid.UUID(OPERATION_ID).int + suffix))
    decision_id = str(uuid.UUID(int=uuid.UUID(DECISION_ID).int + suffix))
    values = {
        "payload_hash": candidate["plan_hash"],
        "operation": "FINANCE.COST_ALLOCATION_PLAN.RELEASE",
        "protected_operation_ref": (
            f"eos.cost-allocation-plan:{candidate['plan_id']}:"
            f"revision:{candidate['plan_revision']}"
        ),
        "instance_state": "APPROVED",
        "decision": "APPROVE",
        "authorized_by_oa": True,
    }
    values.update(overrides)
    with sessions.begin() as session:
        session.execute(
            EOS_APPROVAL_INSTANCE_TABLE.insert().values(
                tenant_id=TENANT,
                approval_instance_id=instance_id,
                idempotency_key=f"allocation-plan-{suffix}",
                approval_policy_id=str(uuid.uuid4()),
                policy_version=1,
                policy_hash=HASH_E,
                approval_domain="BUSINESS_FORMAL",
                business_operation_id=operation_id,
                operation=values["operation"],
                protected_operation_ref=values["protected_operation_ref"],
                payload_hash=values["payload_hash"],
                write_intent_hash=HASH_A,
                requester_ref_type="oa.user",
                requester_id="employee-requester",
                org_unit_id=str(uuid.uuid4()),
                project_id=PROJECT_A,
                state=values["instance_state"],
                active_stage_order=None,
                stage_count=1,
                version=2,
                expires_at=None,
                correlation_id=f"allocation-correlation-{suffix}",
                causation_id=f"allocation-causation-{suffix}",
                binding_hash=semantic_sha256_hash_ref({"instance": instance_id}),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_APPROVAL_DECISION_TABLE.insert().values(
                tenant_id=TENANT,
                approval_decision_id=str(uuid.uuid4()),
                approval_instance_id=instance_id,
                approval_stage_id=str(uuid.uuid4()),
                wc_approval_work_item_id=str(uuid.uuid4()),
                wc_decision_id=decision_id,
                decision=values["decision"],
                decision_version=1,
                decided_by_ref_type="oa.user",
                decided_by_id=APPROVER,
                decision_comment="Allocation plan approved",
                authorized_by_oa=values["authorized_by_oa"],
                oa_decision_ref=f"oa.decision:{decision_id}",
                authorization_revision_hash=HASH_D,
                authorization_checked_at=NOW,
                decided_at=NOW,
                decision_hash=semantic_sha256_hash_ref({"decision": decision_id}),
                recorded_at=NOW,
            )
        )
        session.execute(
            EOS_APPROVAL_PROOF_TABLE.insert().values(
                tenant_id=TENANT,
                approval_proof_id=proof_id,
                approval_instance_id=instance_id,
                business_operation_id=operation_id,
                final_approval_stage_id=str(uuid.uuid4()),
                final_wc_decision_id=decision_id,
                approval_domain="BUSINESS_FORMAL",
                protected_operation_ref=values["protected_operation_ref"],
                payload_hash=values["payload_hash"],
                write_intent_hash=HASH_A,
                policy_hash=HASH_E,
                instance_binding_hash=semantic_sha256_hash_ref(
                    {"binding": instance_id}
                ),
                decision_chain_hash=semantic_sha256_hash_ref({"chain": decision_id}),
                final_decision_hash=semantic_sha256_hash_ref({"final": decision_id}),
                proof_version=1,
                proof_hash=semantic_sha256_hash_ref({"proof": proof_id}),
                issued_at=NOW,
            )
        )
    return candidate


def test_s6_02_contracts_and_existing_migration_are_canonical() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2541_eos_cost_source_allocation"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_cost_allocation_plan" in compact
    assert "justified_percentage" in compact
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for table in (
            EOS_COST_ALLOCATION_PLAN_TABLE,
            EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
        )
        for constraint in table.constraints
    )
    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    route = spec["paths"]["/internal/v2/finance/cost-allocation-plans/releases"]["post"]
    assert route["operationId"] == "FINANCE.COST_ALLOCATION_PLAN.RELEASE"
    assert route["x-nex-business-scope"] == "finance:cost-allocation-plan:approve"


def test_release_replay_and_read_preserve_immutable_plan() -> None:
    engine, sessions, auth, service = _runtime()
    payload = _payload()
    candidate = _seed_proof(sessions, payload)

    created = service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    replay = service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    loaded = service.get(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        plan_id=PLAN_ID,
        plan_revision=1,
    )

    assert created["idempotency_disposition"] == "CREATED"
    assert replay["idempotency_disposition"] == "EXACT_REPLAY"
    assert loaded["operation"] == "FINANCE.COST_ALLOCATION_PLAN.GET"
    assert created["plan_hash"] == candidate["plan_hash"]
    assert created["approved_by"] == APPROVER
    assert created["approved_proof"] == f"eos.approval-proof:{PROOF_ID}"
    assert created["basis_priority"] == 1
    assert created["release_authorization_revision_hash"] == "f" * 64
    assert loaded["release_authorization_revision_hash"] is None
    assert len(auth.calls) == 2
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_COST_ALLOCATION_PLAN_TABLE)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_COST_ALLOCATION_PLAN_LINE_TABLE)
            )
            == 2
        )
    engine.dispose()


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        ({"payload_hash": HASH_C}, "EOS_COST_ALLOCATION_PLAN_PROOF_MISMATCH"),
        (
            {"operation": "FINANCE.OTHER.RELEASE"},
            "EOS_COST_ALLOCATION_PLAN_PROOF_MISMATCH",
        ),
        (
            {"protected_operation_ref": "eos.cost-allocation-plan:wrong"},
            "EOS_COST_ALLOCATION_PLAN_PROOF_MISMATCH",
        ),
        ({"instance_state": "PENDING"}, "EOS_COST_ALLOCATION_PLAN_CONFLICT"),
        ({"decision": "REJECT"}, "EOS_COST_ALLOCATION_PLAN_CONFLICT"),
    ],
)
def test_exact_business_formal_proof_is_fail_closed(override, error_code) -> None:
    engine, sessions, _auth, service = _runtime()
    payload = _payload()
    _seed_proof(sessions, payload, **override)
    with pytest.raises(EosAllocationPlanError) as error:
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert error.value.error_code == error_code
    engine.dispose()


@pytest.mark.parametrize(
    "source",
    [
        AuthorizationSource(active=False),
        AuthorizationSource(scopes=["finance:cost-allocation:read"]),
    ],
)
def test_fresh_oa_authorization_denial_has_zero_mutation(source) -> None:
    engine, sessions, _auth, service = _runtime(auth=source)
    payload = _payload()
    _seed_proof(sessions, payload)
    with pytest.raises(EosAllocationPlanError) as error:
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert error.value.status_code == 403
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_COST_ALLOCATION_PLAN_TABLE)
            )
            == 0
        )
    engine.dispose()


def test_oa_unavailability_is_retryable_and_has_zero_mutation() -> None:
    engine, sessions, _auth, service = _runtime(
        auth=AuthorizationSource(fail=TimeoutError("OA unavailable"))
    )
    payload = _payload()
    _seed_proof(sessions, payload)
    with pytest.raises(EosAllocationPlanError) as error:
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert error.value.status_code == 503
    assert error.value.retryable is True
    engine.dispose()


def test_oa_explicit_subject_denial_and_malformed_response_are_denied() -> None:
    for source in (
        AuthorizationSource(fail=AuthorizationSubjectDenied("inactive")),
        AuthorizationSource(),
    ):
        engine, sessions, _auth, service = _runtime(auth=source)
        payload = _payload()
        _seed_proof(sessions, payload)
        if source.fail is None:
            source.effective_authorization = lambda **_kwargs: {  # type: ignore[method-assign]
                "active": True,
                "tenant_id": TENANT,
                "subject_id": APPROVER,
                "scopes": "not-a-sequence",
                "revision_hash": "f" * 64,
            }
        with pytest.raises(EosAllocationPlanError) as error:
            service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
        assert error.value.status_code == 403
        engine.dispose()


@pytest.mark.parametrize("revision_hash", [None, "not-a-hash"])
def test_oa_revision_hash_is_fail_closed(revision_hash) -> None:
    source = AuthorizationSource()
    source.effective_authorization = lambda **_kwargs: {  # type: ignore[method-assign]
        "active": True,
        "tenant_id": TENANT,
        "subject_id": APPROVER,
        "scopes": ["finance:cost-allocation-plan:approve"],
        "revision_hash": revision_hash,
    }
    engine, sessions, _auth, service = _runtime(auth=source)
    payload = _payload()
    _seed_proof(sessions, payload)
    with pytest.raises(EosAllocationPlanError) as error:
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert error.value.status_code == 403
    engine.dispose()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(schema_version="wrong"),
        lambda value: value["plan"].update(scope_type="UNKNOWN"),
        lambda value: value["plan"].update(source_kind="CASH"),
        lambda value: value["plan"].update(effective_end="2026-10-31"),
        lambda value: value["plan"]["lines"][1].update(line_no=3),
        lambda value: value["plan"]["lines"][1].update(project_id=PROJECT_A),
        lambda value: value["plan"]["lines"][1].update(
            allocation_ratio="0.500000000000"
        ),
        lambda value: value["plan"]["lines"][0].update(work_code="NOT-A-WORK-CODE"),
    ],
)
def test_release_payload_rejects_noncanonical_semantics(mutator) -> None:
    payload = _payload()
    mutator(payload)
    with pytest.raises(EosAllocationPlanError) as error:
        allocation_plans._admit_release(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "schema_version": "eos_cost_allocation_plan_release.v1",
            "approval_proof_id": PROOF_ID,
            "plan": {},
        },
    ],
)
def test_release_envelope_shape_is_closed(payload) -> None:
    with pytest.raises(EosAllocationPlanError):
        allocation_plans._admit_release(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_code", "wrong"),
        ("basis_units", "NaN"),
        ("basis_units", "0"),
        ("allocation_ratio", "1.100000000000"),
        ("eligibility_hash", "bad"),
    ],
)
def test_line_scalar_validation_is_closed(field, value) -> None:
    payload = _payload()
    payload["plan"]["lines"][0][field] = value
    with pytest.raises(EosAllocationPlanError):
        allocation_plans._admit_release(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )


def test_project_scope_and_empty_lines_are_rejected() -> None:
    payload = _payload()
    payload["plan"]["scope_type"] = "PROJECT"
    with pytest.raises(EosAllocationPlanError, match="exactly one line"):
        allocation_plans._admit_release(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )
    payload = _payload()
    payload["plan"]["lines"] = []
    with pytest.raises(EosAllocationPlanError, match="non-empty sequence"):
        allocation_plans._admit_release(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
        )


def test_revision_sequence_and_identity_conflict_are_guarded() -> None:
    engine, sessions, _auth, service = _runtime()
    first = _payload()
    _seed_proof(sessions, first)
    service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=first)

    third = _payload(revision=3, proof_id=str(uuid.uuid4()))
    _seed_proof(
        sessions,
        third,
        proof_id=third["approval_proof_id"],
        suffix=1,
    )
    with pytest.raises(EosAllocationPlanError, match="next immutable revision 2"):
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=third)

    changed = _payload(proof_id=str(uuid.uuid4()))
    changed["plan"]["lines"][0]["basis_units"] = "7.00000000"
    _seed_proof(
        sessions,
        changed,
        proof_id=changed["approval_proof_id"],
        suffix=2,
    )
    with pytest.raises(EosAllocationPlanError, match="different immutable semantics"):
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=changed)
    engine.dispose()


@pytest.mark.parametrize("fault", ["project_code", "project_state", "binding"])
def test_project_company_scope_is_revalidated_at_release(fault) -> None:
    engine, sessions, _auth, service = _runtime()
    payload = _payload()
    _seed_proof(sessions, payload)
    with sessions.begin() as session:
        if fault == "project_code":
            session.execute(
                update(EOS_PROJECT_TABLE)
                .where(EOS_PROJECT_TABLE.c.project_id == PROJECT_A)
                .values(project_code="VO00D269999")
            )
        elif fault == "project_state":
            session.execute(
                update(EOS_PROJECT_TABLE)
                .where(EOS_PROJECT_TABLE.c.project_id == PROJECT_A)
                .values(status="CLOSED")
            )
        else:
            session.execute(
                update(EOS_PROJECT_COMPANY_BINDING_TABLE)
                .where(EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == PROJECT_A)
                .values(state="REVOKED")
            )
    with pytest.raises(EosAllocationPlanError) as error:
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert error.value.status_code == 409
    engine.dispose()


@pytest.mark.parametrize(
    "fault", ["company_missing", "company_inactive", "project_missing"]
)
def test_missing_or_inactive_scope_authority_is_fail_closed(fault) -> None:
    engine, sessions, _auth, service = _runtime()
    payload = _payload()
    _seed_proof(sessions, payload)
    with sessions.begin() as session:
        if fault == "company_missing":
            session.execute(EOS_LEGAL_ENTITY_TABLE.delete())
        elif fault == "company_inactive":
            session.execute(update(EOS_LEGAL_ENTITY_TABLE).values(status="INACTIVE"))
        else:
            session.execute(
                EOS_PROJECT_TABLE.delete().where(
                    EOS_PROJECT_TABLE.c.project_id == PROJECT_A
                )
            )
    with pytest.raises(EosAllocationPlanError) as error:
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert error.value.status_code in {404, 409}
    engine.dispose()


def _seed_work_assignments(sessions):
    hashes = [HASH_C, HASH_D]
    with sessions.begin() as session:
        for index, (project_id, units, assignment_hash) in enumerate(
            ((PROJECT_A, "6.0000", HASH_C), (PROJECT_B, "4.0000", HASH_D)),
            start=1,
        ):
            session.execute(
                EOS_PROJECT_WORK_ASSIGNMENT_TABLE.insert().values(
                    tenant_id=TENANT,
                    assignment_id=str(uuid.uuid4()),
                    project_id=project_id,
                    work_set_id=str(uuid.uuid4()),
                    work_set_revision=1,
                    work_code_id="FL0012009",
                    performer_kind="HUMAN",
                    subject_ref=f"employee-{index}",
                    performer_authority_hash=HASH_A,
                    assignment_scope="EXECUTE",
                    planned_man_days=units,
                    planned_grade_id="G1",
                    grade_policy_ref="eos.grade-policy:v1",
                    grade_policy_hash=HASH_B,
                    valid_from=date(2026, 1, 1),
                    valid_until=None,
                    approved_proof_hash=HASH_E,
                    approved_by_subject_id=APPROVER,
                    assignment_hash=assignment_hash,
                    created_at=NOW,
                )
            )
    return semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-APPROVED-PLAN-BASIS-V1",
            "assignment_hashes": sorted(hashes),
        }
    )


def test_approved_plan_basis_reconciles_work_assignments() -> None:
    engine, sessions, _auth, service = _runtime()
    basis_hash = _seed_work_assignments(sessions)
    payload = _payload(basis_kind="APPROVED_PLAN")
    payload["plan"]["basis_source_hash"] = basis_hash
    for line in payload["plan"]["lines"]:
        line["work_code"] = "FL0012009"
    _seed_proof(sessions, payload)
    result = service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert result["basis_priority"] == 2
    engine.dispose()


@pytest.mark.parametrize("fault", ["missing_work_code", "units", "hash"])
def test_approved_plan_basis_mismatch_is_fail_closed(fault) -> None:
    engine, sessions, _auth, service = _runtime()
    basis_hash = _seed_work_assignments(sessions)
    payload = _payload(basis_kind="APPROVED_PLAN")
    payload["plan"]["basis_source_hash"] = basis_hash
    for line in payload["plan"]["lines"]:
        line["work_code"] = "FL0012009"
    if fault == "missing_work_code":
        payload["plan"]["lines"][0]["work_code"] = None
    elif fault == "units":
        payload["plan"]["lines"][0]["basis_units"] = "7.00000000"
    else:
        payload["plan"]["basis_source_hash"] = HASH_A
    _seed_proof(sessions, payload)
    with pytest.raises(EosAllocationPlanError) as error:
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert error.value.status_code == 409
    engine.dispose()


def test_approved_plan_requires_effective_assignment() -> None:
    engine, sessions, _auth, service = _runtime()
    payload = _payload(basis_kind="APPROVED_PLAN")
    for line in payload["plan"]["lines"]:
        line["work_code"] = "FL0012009"
    _seed_proof(sessions, payload)
    with pytest.raises(EosAllocationPlanError, match="lacks an effective"):
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    engine.dispose()


def test_missing_proof_and_missing_plan_are_explicit() -> None:
    engine, _sessions, _auth, service = _runtime()
    with pytest.raises(EosAllocationPlanError, match="proof was not found"):
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=_payload())
    with pytest.raises(EosAllocationPlanError) as missing:
        service.get(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            plan_id=PLAN_ID,
            plan_revision=1,
        )
    assert missing.value.status_code == 404
    engine.dispose()


def test_repository_validation_and_clock_guards_are_explicit() -> None:
    engine, sessions, _auth, _service = _runtime()
    repository = SqlAlchemyEosAllocationPlanRepository(sessions)
    with pytest.raises(EosAllocationPlanError):
        repository.load_approval_context(
            tenant_id="not valid tenant", approval_proof_id=PROOF_ID
        )
    payload = _payload()
    _, candidate = allocation_plans._admit_release(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=payload
    )
    with pytest.raises(EosAllocationPlanError, match="proof was not found"):
        repository.release(candidate, approval_proof_id=PROOF_ID)

    _seed_proof(sessions, payload)
    naive_repository = SqlAlchemyEosAllocationPlanRepository(
        sessions, clock=lambda: NOW.replace(tzinfo=None)
    )
    service = EosAllocationPlanService(
        repository=naive_repository, authorization_source=AuthorizationSource()
    )
    with pytest.raises(EosAllocationPlanError) as error:
        service.release(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)
    assert error.value.error_code == "EOS_COST_ALLOCATION_PLAN_CLOCK_INVALID"
    assert allocation_plans._wire_value(uuid.UUID(PLAN_ID)) == PLAN_ID
    engine.dispose()


@pytest.mark.parametrize(
    ("helper", "value"),
    [
        (lambda value: allocation_plans._uuid("id", value), "bad"),
        (lambda value: allocation_plans._text("ref", value, 3), "toolong"),
        (lambda value: allocation_plans._positive_int("revision", value), True),
        (
            lambda value: allocation_plans._positive_decimal(
                "amount", value, Decimal("0.1")
            ),
            "not-number",
        ),
        (lambda value: allocation_plans._date_value("date", value), None),
        (lambda value: allocation_plans._date_value("date", value), "not-a-date"),
    ],
)
def test_scalar_helper_guards(helper, value) -> None:
    with pytest.raises(EosAllocationPlanError):
        helper(value)


def test_allocation_plan_api_release_get_and_fail_closed(monkeypatch) -> None:
    engine, sessions, _auth, service = _runtime()
    payload = _payload()
    _seed_proof(sessions, payload)
    monkeypatch.setattr(
        "nex_eos.allocation_plan_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api", audience="nex-eos", scopes=("service:call",)
        ),
    )
    app = FastAPI()
    register_allocation_plan_routes(app)
    headers = {
        "Authorization": "Bearer signed-service-token",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Company-Id": COMPANY_ID,
    }
    with TestClient(app) as client:
        unavailable = client.post(
            "/internal/v2/finance/cost-allocation-plans/releases",
            headers=headers,
            json=payload,
        )
        app.state.eos_allocation_plan_service = service
        created = client.post(
            "/internal/v2/finance/cost-allocation-plans/releases",
            headers=headers,
            json=payload,
        )
        loaded = client.get(
            f"/internal/v2/finance/cost-allocation-plans/{PLAN_ID}/revisions/1",
            headers=headers,
        )
        missing = client.get(
            f"/internal/v2/finance/cost-allocation-plans/{uuid.uuid4()}/revisions/1",
            headers=headers,
        )
    assert unavailable.status_code == 503
    assert created.status_code == 201
    assert loaded.status_code == 200
    assert missing.status_code == 404
    engine.dispose()


def test_allocation_plan_api_propagates_token_and_domain_denials(monkeypatch) -> None:
    app = FastAPI()
    register_allocation_plan_routes(app)
    denied = JSONResponse({"error_code": "TOKEN_DENIED"}, status_code=401)
    monkeypatch.setattr(
        "nex_eos.allocation_plan_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: denied,
    )
    headers = {
        "Authorization": "Bearer invalid",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Company-Id": COMPANY_ID,
    }
    with TestClient(app) as client:
        write = client.post(
            "/internal/v2/finance/cost-allocation-plans/releases",
            headers=headers,
            json=_payload(),
        )
        read = client.get(
            f"/internal/v2/finance/cost-allocation-plans/{PLAN_ID}/revisions/1",
            headers=headers,
        )
    assert write.status_code == read.status_code == 401


def test_allocation_plan_api_maps_domain_error_and_read_unavailable(
    monkeypatch,
) -> None:
    engine, sessions, _auth, service = _runtime()
    payload = _payload()
    _seed_proof(sessions, payload)
    monkeypatch.setattr(
        "nex_eos.allocation_plan_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api", audience="nex-eos", scopes=("service:call",)
        ),
    )
    app = FastAPI()
    register_allocation_plan_routes(app)
    headers = {
        "Authorization": "Bearer signed-service-token",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Company-Id": COMPANY_ID,
    }
    with TestClient(app) as client:
        unavailable = client.get(
            f"/internal/v2/finance/cost-allocation-plans/{PLAN_ID}/revisions/1",
            headers=headers,
        )
        app.state.eos_allocation_plan_service = service
        invalid = client.post(
            "/internal/v2/finance/cost-allocation-plans/releases",
            headers=headers,
            json={"schema_version": "wrong"},
        )
    assert unavailable.status_code == 503
    assert invalid.status_code == 422
    engine.dispose()
