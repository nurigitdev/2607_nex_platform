from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from mybee_ax.domain.documents import (
    ApprovedDocumentContractError,
    admit_approved_document_envelope,
    build_approved_document_request,
)
from nex_eos import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVED_DOCUMENT_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_METADATA,
    ApprovalInstanceInput,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    ApprovalStageDecisionInput,
    ApprovedDocumentInput,
    AuthorizationSubjectDenied,
    EosApprovedDocumentError,
    EosApprovedDocumentService,
    LegalEntityInput,
    NvtProjectInput,
    OrgUnitInput,
    ProjectCompanyBindingInput,
    ProjectInput,
    SqlAlchemyEosApprovalInstanceRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosApprovalTransitionRepository,
    SqlAlchemyEosApprovedDocumentRepository,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
    approved_document_payload_hash,
    create_eos_app,
    deterministic_business_formal_work_item_id,
)
from nex_runtime import issue_mock_service_token, psycopg_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, delete, make_url, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)
TENANT = "tenant-s2-01"
COMPANY_ID = "21000000-0000-4000-8000-000000000001"
NVT_ID = "21000000-0000-4000-8000-000000000002"
PROJECT_ID = "21000000-0000-4000-8000-000000000003"
ORG_ID = "21000000-0000-4000-8000-000000000004"
POLICY_ID = "21000000-0000-4000-8000-000000000005"
OPERATION_ID = "21000000-0000-4000-8000-000000000006"
INSTANCE_ID = "21000000-0000-4000-8000-000000000007"
ENVELOPE_ID = "21000000-0000-4000-8000-000000000008"
PROOF_ID = str(uuid.uuid5(uuid.UUID(INSTANCE_ID), "eos.approval-proof:v1"))
DECISION_ID = "21000000-0000-4000-8000-000000000009"
WORK_ITEM_ID = "21000000-0000-4000-8000-000000000010"
CONTENT_HASH = "sha256:" + "a" * 64
ATTACHMENT_HASH = "sha256:" + "b" * 64
INTENT_HASH = "sha256:" + "c" * 64
AUTH_REVISION = "d" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S2_01_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self, *, scopes=("finance:document:read",)) -> None:
        self.scopes = scopes
        self.denied = False
        self.unavailable = False

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.denied:
            raise AuthorizationSubjectDenied("inactive subject")
        if self.unavailable:
            raise RuntimeError("OA unavailable")
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": list(self.scopes),
            "revision_hash": AUTH_REVISION,
        }


def _value(**overrides) -> ApprovedDocumentInput:
    values = {
        "tenant_id": TENANT,
        "envelope_id": ENVELOPE_ID,
        "company_id": COMPANY_ID,
        "approved_document_id": "proposal-2026-0001",
        "document_revision": 1,
        "document_type": "BUSINESS_PROPOSAL",
        "work_code": "FL0004011",
        "document_content_hash": CONTENT_HASH,
        "attachment_manifest_hash": ATTACHMENT_HASH,
        "business_approval_proof_id": PROOF_ID,
        "scope_type": "PROJECT",
        "allowed_project_ids": (PROJECT_ID,),
        "approved_amount": Decimal("1250000.0000"),
        "approved_currency": "KRW",
        "valid_from": NOW + timedelta(hours=1),
        "valid_until": NOW + timedelta(days=30),
        "tolerance_policy_hash": None,
    }
    values.update(overrides)
    return ApprovedDocumentInput(**values)


def _build_runtime(*, engine=None, value: ApprovedDocumentInput | None = None):
    engine = engine or create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    document = value or _value()
    entities = SqlAlchemyEosLegalEntityRepository(sessions)
    entities.create_legal_entity(
        LegalEntityInput(
            TENANT,
            COMPANY_ID,
            "NURI",
            "Nuri Company",
            "KRW",
            "KRW",
            "Asia/Seoul",
            date(2026, 1, 1),
        )
    )
    SqlAlchemyEosOrganizationRepository(sessions).create_org_unit(
        OrgUnitInput(
            TENANT,
            ORG_ID,
            "FINANCE-S201",
            "Finance S2-01",
            "TEAM",
            NOW - timedelta(days=1),
        )
    )
    projects = SqlAlchemyEosProjectRepository(sessions)
    projects.create_nvt_project(
        NvtProjectInput(TENANT, NVT_ID, "NVT-S201", "NVT S2-01")
    )
    projects.create_project(
        ProjectInput(
            TENANT,
            PROJECT_ID,
            "PROJECT-S201",
            "Project S2-01",
            nvt_project_id=NVT_ID,
        )
    )
    entities.create_project_company_binding(
        ProjectCompanyBindingInput(
            TENANT,
            str(uuid.uuid4()),
            PROJECT_ID,
            COMPANY_ID,
            date(2026, 1, 1),
            "sha256:" + "e" * 64,
        )
    )
    SqlAlchemyEosApprovalPolicyRepository(sessions).create_policy(
        ApprovalPolicyInput(
            tenant_id=TENANT,
            approval_policy_id=POLICY_ID,
            policy_key="mybee.document.s2-01",
            name="MyBee document approval",
            approval_domain="BUSINESS_FORMAL",
            effective_from=NOW - timedelta(days=1),
            stages=(ApprovalPolicyStageInput("TEAM_LEAD"),),
        )
    )
    payload_hash = approved_document_payload_hash(document)
    with sessions.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=OPERATION_ID,
                idempotency_key="s2-01-approved-document",
                operation="APPROVE_BUSINESS_DOCUMENT",
                payload_hash=payload_hash,
                commit_state="COMMITTED",
                result_json={"approved_document_id": document.approved_document_id},
                created_at=NOW - timedelta(minutes=2),
                committed_at=NOW - timedelta(minutes=1),
            )
        )
    instances = SqlAlchemyEosApprovalInstanceRepository(sessions, clock=lambda: NOW)
    instance, created = instances.create_or_get_instance(
        ApprovalInstanceInput(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
            idempotency_key="s2-01-approval-instance",
            approval_policy_id=POLICY_ID,
            business_operation_id=OPERATION_ID,
            protected_operation_ref="mybee.approved-document:proposal-2026-0001:1",
            payload_hash=payload_hash,
            write_intent_hash=INTENT_HASH,
            requester_ref={"type": "oa.user", "id": "employee-requester"},
            org_unit_id=ORG_ID,
            project_id=PROJECT_ID,
            correlation_id="s2-01-correlation",
            causation_id="s2-01-causation",
            expires_at=NOW + timedelta(days=2),
        )
    )
    assert created is True
    stage = instance["stages"][0]
    transition = SqlAlchemyEosApprovalTransitionRepository(
        sessions, clock=lambda: NOW + timedelta(minutes=1)
    )
    result = transition.apply_decision(
        ApprovalStageDecisionInput(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
            approval_stage_id=stage["approval_stage_id"],
            wc_approval_work_item_id=deterministic_business_formal_work_item_id(
                tenant_id=TENANT,
                approval_stage_id=stage["approval_stage_id"],
            ),
            wc_work_item_semantic_hash=semantic_sha256_hash_ref(
                {"work_item": WORK_ITEM_ID}
            ),
            wc_decision_id=DECISION_ID,
            wc_event_id=str(uuid.uuid4()),
            decision="APPROVE",
            decision_version=1,
            decided_by_ref={"type": "oa.user", "id": "employee-approver"},
            decision_comment="Approved",
            authorized_by_oa=True,
            oa_decision_ref="oa.authorization:s2-01",
            authorization_revision_hash="sha256:" + AUTH_REVISION,
            authorization_checked_at=NOW + timedelta(seconds=30),
            decided_at=NOW + timedelta(seconds=30),
            correlation_id="s2-01-decision-correlation",
            causation_id="s2-01-decision-causation",
        )
    )
    assert result["outcome"] == "FINAL_APPROVED"
    assert result["approval_proof"]["approval_proof_id"] == PROOF_ID
    return engine, sessions, document


def test_s2_01_migration_openapi_and_no_public_approval_bypass() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2526_eos_approved_document_envelope"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_approved_document_envelope" in compact
    assert "foreign key ( tenant_id, business_approval_proof_id )" in compact
    assert "eos_guard_approved_doc_immutable" in compact
    assert "jsonb_typeof(allowed_project_ids) = 'array'" in compact
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for constraint in EOS_APPROVED_DOCUMENT_TABLE.constraints
    )

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    route = spec["paths"]["/internal/v2/finance/approved-documents/{envelope_id}"]
    assert set(route) == {"get"}
    assert route["get"]["operationId"] == "BUSINESS.DOCUMENT_APPROVED.GET"
    assert route["get"]["x-nex-business-scope"] == "finance:document:read"


def test_exact_final_proof_creates_immutable_projection_and_replays() -> None:
    _engine, sessions, document = _build_runtime()
    repository = SqlAlchemyEosApprovedDocumentRepository(
        sessions, clock=lambda: NOW + timedelta(hours=2)
    )
    projection, created = repository.create(document)
    assert created is True
    assert projection["business_approval_proof_id"] == PROOF_ID
    assert projection["business_proof_hash"].startswith("sha256:")
    assert projection["approved_by_principal_ref"] == {
        "type": "oa.user",
        "id": "employee-approver",
    }
    assert projection["allowed_project_ids"] == [PROJECT_ID]
    assert projection["remaining_amount"] == "1250000.0000"
    assert projection["usable"] is True

    replay, replay_created = repository.create(document)
    assert replay_created is False
    assert replay == projection
    assert repository.get(tenant_id=TENANT, envelope_id=ENVELOPE_ID) == projection


def test_proof_rejects_material_revision_drift_and_invalid_periods() -> None:
    _engine, sessions, document = _build_runtime()
    repository = SqlAlchemyEosApprovedDocumentRepository(sessions, clock=lambda: NOW)
    changed = replace(
        document,
        envelope_id=str(uuid.uuid4()),
        approved_document_id="proposal-2026-0002",
        attachment_manifest_hash="sha256:" + "f" * 64,
    )
    with pytest.raises(EosApprovedDocumentError) as mismatch:
        repository.create(changed)
    assert mismatch.value.error_code == "EOS_APPROVED_DOCUMENT_PROOF_MISMATCH"

    with sessions.begin() as session:
        session.execute(
            update(EOS_APPROVAL_INSTANCE_TABLE)
            .where(EOS_APPROVAL_INSTANCE_TABLE.c.tenant_id == TENANT)
            .values(operation="UNRELATED_APPROVAL")
        )
    with pytest.raises(EosApprovedDocumentError) as wrong_purpose:
        repository.create(document)
    assert wrong_purpose.value.error_code == "EOS_APPROVED_DOCUMENT_PROOF_MISMATCH"

    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(
            replace(document, valid_until=document.valid_from)
        )
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(
            replace(document, scope_type="COMPANY", allowed_project_ids=(PROJECT_ID,))
        )
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(
            replace(
                document, scope_type="PROJECT_SET", allowed_project_ids=(PROJECT_ID,)
            )
        )
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(replace(document, approved_amount=Decimal(0)))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("valid_from", NOW.replace(tzinfo=None)),
        ("valid_until", (NOW + timedelta(days=1)).replace(tzinfo=None)),
        ("scope_type", "PERSONAL"),
        ("allowed_project_ids", ()),
        ("tenant_id", " tenant"),
        ("envelope_id", "not-a-uuid"),
        ("document_revision", True),
        ("document_type", ""),
        ("work_code", "NOT-A-WORK-CODE"),
        ("document_content_hash", "sha256:bad"),
        ("approved_amount", Decimal("NaN")),
        ("approved_amount", object()),
        ("approved_amount", Decimal("1.00001")),
        ("approved_currency", "krw"),
        ("tolerance_policy_hash", "sha256:bad"),
    ),
)
def test_document_input_contract_rejects_malformed_values(field, value) -> None:
    document = _value()
    with pytest.raises(EosApprovedDocumentError) as error:
        approved_document_payload_hash(replace(document, **{field: value}))
    assert error.value.status_code == 422


def test_document_input_requires_typed_value_and_valid_project_shapes() -> None:
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(None)  # type: ignore[arg-type]
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(_value(allowed_project_ids=("not-a-uuid",)))
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(
            _value(allowed_project_ids=(PROJECT_ID, PROJECT_ID))
        )
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(
            _value(allowed_project_codes=("ABCDD260001", "ABCDD260002"))
        )
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(
            _value(
                scope_type="PROJECT_SET",
                allowed_project_ids=(PROJECT_ID, str(uuid.uuid4())),
                allowed_project_codes=("ABCDD260001", "ABCDD260001"),
            )
        )
    with pytest.raises(EosApprovedDocumentError):
        approved_document_payload_hash(_value(allowed_project_codes=("ABCDR260001",)))

    versioned = _value(allowed_project_codes=("ABCDD260001",))
    assert approved_document_payload_hash(versioned) != approved_document_payload_hash(
        _value()
    )


def test_repository_rejects_stale_company_missing_proof_and_broken_lineage() -> None:
    _engine, sessions, document = _build_runtime()
    with sessions.begin() as session:
        session.execute(
            update(EOS_LEGAL_ENTITY_TABLE)
            .where(EOS_LEGAL_ENTITY_TABLE.c.tenant_id == TENANT)
            .values(status="INACTIVE")
        )
    with pytest.raises(EosApprovedDocumentError) as inactive:
        SqlAlchemyEosApprovedDocumentRepository(sessions).create(document)
    assert inactive.value.status_code == 409

    _engine, sessions, document = _build_runtime()
    with sessions.begin() as session:
        session.execute(delete(EOS_LEGAL_ENTITY_TABLE))
    with pytest.raises(EosApprovedDocumentError) as missing_company:
        SqlAlchemyEosApprovedDocumentRepository(sessions).create(document)
    assert missing_company.value.status_code == 404

    _engine, sessions, document = _build_runtime()
    missing_proof = replace(document, business_approval_proof_id=str(uuid.uuid4()))
    with pytest.raises(EosApprovedDocumentError) as proof:
        SqlAlchemyEosApprovedDocumentRepository(sessions).create(missing_proof)
    assert proof.value.status_code == 409

    _engine, sessions, document = _build_runtime()
    with sessions.begin() as session:
        session.execute(delete(EOS_APPROVAL_DECISION_TABLE))
    with pytest.raises(EosApprovedDocumentError) as lineage:
        SqlAlchemyEosApprovedDocumentRepository(sessions).create(document)
    assert lineage.value.status_code == 409


def test_repository_rejects_nonfinal_proof_scope_drift_and_early_validity() -> None:
    _engine, sessions, document = _build_runtime()
    with sessions.begin() as session:
        session.execute(update(EOS_APPROVAL_INSTANCE_TABLE).values(state="REJECTED"))
    with pytest.raises(EosApprovedDocumentError) as nonfinal:
        SqlAlchemyEosApprovedDocumentRepository(sessions).create(document)
    assert nonfinal.value.status_code == 409

    unknown_project = "21000000-0000-4000-8000-000000000099"
    scoped_document = _value(allowed_project_ids=(unknown_project,))
    _engine, sessions, scoped_document = _build_runtime(value=scoped_document)
    with pytest.raises(EosApprovedDocumentError) as scope:
        SqlAlchemyEosApprovedDocumentRepository(sessions).create(scoped_document)
    assert scope.value.status_code == 409

    early_document = _value(valid_from=NOW + timedelta(seconds=45))
    _engine, sessions, early_document = _build_runtime(value=early_document)
    with pytest.raises(EosApprovedDocumentError) as validity:
        SqlAlchemyEosApprovedDocumentRepository(sessions).create(early_document)
    assert validity.value.status_code == 422


def test_company_scope_and_revision_conflict_are_deterministic() -> None:
    company_document = _value(scope_type="COMPANY", allowed_project_ids=())
    _engine, sessions, company_document = _build_runtime(value=company_document)
    repository = SqlAlchemyEosApprovedDocumentRepository(
        sessions, clock=lambda: NOW + timedelta(hours=2)
    )
    projection, created = repository.create(company_document)
    assert created is True
    assert projection["scope_type"] == "COMPANY"
    with pytest.raises(EosApprovedDocumentError) as proof_conflict:
        repository.create(
            replace(company_document, business_approval_proof_id=str(uuid.uuid4()))
        )
    assert proof_conflict.value.status_code == 409
    with sessions.begin() as session:
        session.execute(
            update(EOS_APPROVED_DOCUMENT_TABLE).values(
                payload_hash="sha256:" + "9" * 64
            )
        )
    with pytest.raises(EosApprovedDocumentError) as conflict:
        repository.create(company_document)
    assert conflict.value.status_code == 409


def test_repository_maps_invalid_clock_and_database_failure() -> None:
    engine, sessions, document = _build_runtime()
    with pytest.raises(EosApprovedDocumentError) as invalid_clock:
        SqlAlchemyEosApprovedDocumentRepository(
            sessions, clock=lambda: "not-a-time"
        ).create(document)
    assert invalid_clock.value.status_code == 422

    engine.dispose()
    with pytest.raises(EosApprovedDocumentError) as unavailable:
        SqlAlchemyEosApprovedDocumentRepository(sessions).create(document)
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


def test_expired_projection_is_never_usable() -> None:
    _engine, sessions, document = _build_runtime()
    SqlAlchemyEosApprovedDocumentRepository(
        sessions, clock=lambda: NOW + timedelta(hours=2)
    ).create(document)
    expired = SqlAlchemyEosApprovedDocumentRepository(
        sessions, clock=lambda: NOW + timedelta(days=31)
    ).get(tenant_id=TENANT, envelope_id=ENVELOPE_ID)
    assert expired is not None
    assert expired["state"] == "EXPIRED"
    assert expired["usable"] is False


def test_service_requires_fresh_document_read_authority_and_tenant_scope() -> None:
    _engine, sessions, document = _build_runtime()
    repository = SqlAlchemyEosApprovedDocumentRepository(
        sessions, clock=lambda: NOW + timedelta(hours=2)
    )
    repository.create(document)
    source = AuthorizationSource()
    service = EosApprovedDocumentService(repository, source)
    assert (
        service.get_approved_document(
            tenant_id=TENANT,
            envelope_id=ENVELOPE_ID,
            requester_subject_id="employee-reader",
        )["envelope_id"]
        == ENVELOPE_ID
    )

    source.scopes = ()
    with pytest.raises(EosApprovedDocumentError) as denied:
        service.get_approved_document(
            tenant_id=TENANT,
            envelope_id=ENVELOPE_ID,
            requester_subject_id="employee-reader",
        )
    assert denied.value.status_code == 403
    source.scopes = ("finance:document:read",)
    source.denied = True
    with pytest.raises(EosApprovedDocumentError) as inactive:
        service.get_approved_document(
            tenant_id=TENANT,
            envelope_id=ENVELOPE_ID,
            requester_subject_id="employee-reader",
        )
    assert inactive.value.status_code == 403
    source.denied = False
    source.unavailable = True
    with pytest.raises(EosApprovedDocumentError) as unavailable:
        service.get_approved_document(
            tenant_id=TENANT,
            envelope_id=ENVELOPE_ID,
            requester_subject_id="employee-reader",
        )
    assert unavailable.value.status_code == 503


@pytest.mark.parametrize(
    "authorization",
    (
        None,
        {},
        {
            "active": False,
            "tenant_id": TENANT,
            "subject_id": "employee-reader",
            "scopes": ["finance:document:read"],
        },
        {
            "active": True,
            "tenant_id": "other-tenant",
            "subject_id": "employee-reader",
            "scopes": ["finance:document:read"],
        },
        {
            "active": True,
            "tenant_id": TENANT,
            "subject_id": "employee-reader",
            "scopes": "finance:document:read",
        },
    ),
)
def test_service_rejects_malformed_authorization_projection(authorization) -> None:
    class StaticAuthorizationSource:
        def effective_authorization(self, **_kwargs):
            return authorization

    _engine, sessions, _document = _build_runtime()
    service = EosApprovedDocumentService(
        SqlAlchemyEosApprovedDocumentRepository(sessions),
        StaticAuthorizationSource(),
    )
    with pytest.raises(EosApprovedDocumentError) as denied:
        service.get_approved_document(
            tenant_id=TENANT,
            envelope_id=ENVELOPE_ID,
            requester_subject_id="employee-reader",
        )
    assert denied.value.status_code == 403


def test_service_returns_tenant_scoped_not_found() -> None:
    _engine, sessions, _document = _build_runtime()
    service = EosApprovedDocumentService(
        SqlAlchemyEosApprovedDocumentRepository(sessions), AuthorizationSource()
    )
    with pytest.raises(EosApprovedDocumentError) as missing:
        service.get_approved_document(
            tenant_id=TENANT,
            envelope_id=str(uuid.uuid4()),
            requester_subject_id="employee-reader",
        )
    assert missing.value.status_code == 404


class FakeApprovedDocumentService:
    def get_approved_document(self, **kwargs):
        if kwargs["envelope_id"] == ENVELOPE_ID:
            return {"envelope_id": ENVELOPE_ID, **kwargs}
        raise EosApprovedDocumentError("NOT_FOUND", "missing", status_code=404)


def test_get_route_requires_service_trust_and_maps_domain_errors() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s2-01",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_approved_document_service = FakeApprovedDocumentService()
    client = TestClient(app)
    path = f"/internal/v2/finance/approved-documents/{ENVELOPE_ID}"
    assert client.get(path).status_code == 422
    assert (
        client.get(
            path,
            headers={
                "X-NeX-Tenant-Id": TENANT,
                "X-NeX-Subject-Id": "employee-reader",
            },
        ).status_code
        == 401
    )
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Subject-Id": "employee-reader",
    }
    assert client.get(path, headers=headers).status_code == 200
    missing = path.replace(ENVELOPE_ID, str(uuid.uuid4()))
    assert client.get(missing, headers=headers).status_code == 404
    app.state.eos_approved_document_service = None
    assert client.get(path, headers=headers).status_code == 503


def test_mybee_consumer_contract_accepts_exact_projection_and_rejects_drift() -> None:
    _engine, sessions, document = _build_runtime()
    projection, _created = SqlAlchemyEosApprovedDocumentRepository(
        sessions, clock=lambda: NOW + timedelta(hours=2)
    ).create(document)
    request = build_approved_document_request(
        tenant_id=TENANT,
        envelope_id=ENVELOPE_ID,
        requester_subject_id="employee-reader",
    )
    assert request.method == "GET"
    assert request.operation_id == "BUSINESS.DOCUMENT_APPROVED.GET"
    admitted = admit_approved_document_envelope(
        projection, tenant_id=TENANT, envelope_id=ENVELOPE_ID
    )
    assert admitted["payload_hash"] == approved_document_payload_hash(document)

    malformed = dict(projection)
    malformed["allowed_project_ids"] = [PROJECT_ID, PROJECT_ID]
    with pytest.raises(ApprovedDocumentContractError):
        admit_approved_document_envelope(
            malformed, tenant_id=TENANT, envelope_id=ENVELOPE_ID
        )


def test_mybee_consumer_contract_rejects_malformed_envelope_matrix() -> None:
    _engine, sessions, document = _build_runtime()
    projection, _created = SqlAlchemyEosApprovedDocumentRepository(
        sessions, clock=lambda: NOW + timedelta(hours=2)
    ).create(document)

    mutations = (
        ("schema_version", "v2"),
        ("tenant_id", "other-tenant"),
        ("envelope_id", str(uuid.uuid4())),
        ("company_id", "not-a-uuid"),
        ("approved_document_id", " bad"),
        ("document_revision", 0),
        ("document_type", ""),
        ("work_code", "FLBAD"),
        ("document_content_hash", "sha256:bad"),
        ("tolerance_policy_hash", "sha256:bad"),
        ("approval_policy_version", True),
        ("scope_type", "PERSONAL"),
        ("allowed_project_ids", [PROJECT_ID, PROJECT_ID]),
        ("approved_amount", "not-a-number"),
        ("approved_amount", "1.00001"),
        ("remaining_amount", "-1.0000"),
        ("approved_currency", "krw"),
        ("state", "DELETED"),
        ("usable", "true"),
        ("valid_from", 1),
        ("valid_from", "not-a-time"),
        ("valid_from", "2026-11-11T01:00:00"),
        ("source_work_item_ref", ""),
    )
    for field, value in mutations:
        malformed = dict(projection)
        malformed[field] = value
        with pytest.raises(ApprovedDocumentContractError):
            admit_approved_document_envelope(
                malformed, tenant_id=TENANT, envelope_id=ENVELOPE_ID
            )

    extra = dict(projection)
    extra["unexpected"] = True
    with pytest.raises(ApprovedDocumentContractError):
        admit_approved_document_envelope(
            extra, tenant_id=TENANT, envelope_id=ENVELOPE_ID
        )

    malformed = dict(projection)
    malformed["state"] = "REVOKED"
    malformed["usable"] = True
    with pytest.raises(ApprovedDocumentContractError):
        admit_approved_document_envelope(
            malformed, tenant_id=TENANT, envelope_id=ENVELOPE_ID
        )

    malformed = dict(projection)
    malformed["scope_type"] = "COMPANY"
    with pytest.raises(ApprovedDocumentContractError):
        admit_approved_document_envelope(
            malformed, tenant_id=TENANT, envelope_id=ENVELOPE_ID
        )

    malformed = dict(projection)
    malformed["valid_until"] = malformed["valid_from"]
    with pytest.raises(ApprovedDocumentContractError):
        admit_approved_document_envelope(
            malformed, tenant_id=TENANT, envelope_id=ENVELOPE_ID
        )

    for principal in (None, {"type": "oa.user"}, {"type": " bad", "id": "user"}):
        malformed = dict(projection)
        malformed["approved_by_principal_ref"] = principal
        with pytest.raises(ApprovedDocumentContractError):
            admit_approved_document_envelope(
                malformed, tenant_id=TENANT, envelope_id=ENVELOPE_ID
            )

    with pytest.raises(ApprovedDocumentContractError):
        build_approved_document_request(
            tenant_id=" bad",
            envelope_id=ENVELOPE_ID,
            requester_subject_id="employee-reader",
        )
    with pytest.raises(ApprovedDocumentContractError):
        build_approved_document_request(
            tenant_id=TENANT,
            envelope_id="bad",
            requester_subject_id="employee-reader",
        )
    malformed = dict(projection)
    malformed["remaining_amount"] = "9999999.0000"
    with pytest.raises(ApprovedDocumentContractError):
        admit_approved_document_envelope(
            malformed, tenant_id=TENANT, envelope_id=ENVELOPE_ID
        )


def test_persistence_errors_are_typed() -> None:
    class BrokenSession:
        def __enter__(self):
            raise SQLAlchemyError("broken")

        def __exit__(self, *_args):
            return False

    class BrokenFactory:
        def __call__(self):
            return BrokenSession()

    repository = SqlAlchemyEosApprovedDocumentRepository(BrokenFactory())
    with pytest.raises(EosApprovedDocumentError) as error:
        repository.get(tenant_id=TENANT, envelope_id=ENVELOPE_ID)
    assert error.value.status_code == 503
    assert error.value.retryable is True


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S2-01 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_proof_binding_immutability_and_zero_residue() -> None:
    schema_name = f"mybee_s201_{uuid.uuid4().hex}"
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
    run_service_migrations("nex-eos", database_url=scoped_url, profile="test")
    engine = create_engine(scoped_url, pool_pre_ping=True)
    try:
        _runtime_engine, sessions, document = _build_runtime(engine=engine)
        projection, created = SqlAlchemyEosApprovedDocumentRepository(
            sessions, clock=lambda: NOW + timedelta(hours=2)
        ).create(document)
        assert created is True and projection["usable"] is True
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.eos_approved_document_envelope "
                        "SET approved_amount = 1"
                    ).format(sql.Identifier(schema_name))
                )
            connection.execute(
                sql.SQL(
                    "UPDATE {}.eos_approved_document_envelope SET state = 'REVOKED'"
                ).format(sql.Identifier(schema_name))
            )
            assert connection.execute(
                sql.SQL("SELECT state FROM {}.eos_approved_document_envelope").format(
                    sql.Identifier(schema_name)
                )
            ).fetchone() == ("REVOKED",)
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL("DELETE FROM {}.eos_approved_document_envelope").format(
                        sql.Identifier(schema_name)
                    )
                )
    finally:
        engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
