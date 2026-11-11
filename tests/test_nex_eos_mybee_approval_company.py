from __future__ import annotations

import os
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from mybee_ax.integrations.nex_approval_client import (
    ScopedApprovalContractError,
    admit_scoped_approval_receipt,
    build_scoped_approval_request,
)
from nex_eos import (
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_METADATA,
    EOS_PROJECT_TABLE,
    EOS_SCOPED_APPROVAL_BINDING_TABLE,
    EOS_SCOPED_APPROVAL_CASE_TABLE,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    AuthorizationSubjectDenied,
    EosScopedApprovalError,
    EosScopedApprovalService,
    EosServiceCaller,
    LegalEntityInput,
    NvtProjectInput,
    ProjectCompanyBindingInput,
    ProjectInput,
    ScopedApprovalCaseInput,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosScopedApprovalRepository,
    create_eos_app,
    scoped_approval_payload_hash,
    scoped_approval_work_item,
)
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, delete, func, make_url, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
TENANT = "tenant-s2-02"
COMPANY_ID = "22000000-0000-4000-8000-000000000001"
OTHER_COMPANY_ID = "22000000-0000-4000-8000-000000000002"
NVT_ID = "22000000-0000-4000-8000-000000000003"
PROJECT_A = "22000000-0000-4000-8000-000000000004"
PROJECT_B = "22000000-0000-4000-8000-000000000005"
PROJECT_OTHER = "22000000-0000-4000-8000-000000000006"
POLICY_ID = "22000000-0000-4000-8000-000000000007"
CASE_ID = "22000000-0000-4000-8000-000000000008"
OPERATION_ID = "22000000-0000-4000-8000-000000000009"
SUBJECT_HASH = "sha256:" + "a" * 64
AUTH_REVISION = "b" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S2_02_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self) -> None:
        self.active = True
        self.denied = False
        self.unavailable = False
        self.tenant_id = TENANT
        self.subject_id = "employee-requester"
        self.scopes: object = ["finance:journal:request-approval"]
        self.company_ids: object | None = [COMPANY_ID]
        self.project_ids: object | None = [PROJECT_A, PROJECT_B]
        self.revision_hash: object = AUTH_REVISION
        self.decision_ref: object = "oa-authz:s2-02"

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.denied:
            raise AuthorizationSubjectDenied("inactive")
        if self.unavailable:
            raise RuntimeError("OA unavailable")
        return {
            "active": self.active,
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "scopes": self.scopes,
            "company_ids": self.company_ids,
            "project_ids": self.project_ids,
            "revision_hash": self.revision_hash,
            "decision_ref": self.decision_ref,
        }


class WcClient:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.fail = False
        self.malformed = False
        self.non_mapping = False
        self.drift = False

    def create_or_get(self, work_item):
        if self.fail:
            raise RuntimeError("WC unavailable")
        if self.malformed:
            return {"created": "yes"}
        if self.non_mapping:
            return []
        item = dict(work_item)
        existing = self.items.get(item["approval_work_item_id"])
        created = existing is None
        if existing is None:
            self.items[item["approval_work_item_id"]] = item
            existing = item
        result = dict(existing)
        if self.drift:
            result["approval_request_id"] = str(uuid.uuid4())
        return {"work_item": result, "created": created}


def _build_runtime(*, engine=None, transaction_type="ACCOUNTING_POSTING"):
    engine = engine or create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    entities = SqlAlchemyEosLegalEntityRepository(sessions)
    for company_id, code in (
        (COMPANY_ID, "NURI"),
        (OTHER_COMPANY_ID, "OTHER"),
    ):
        entities.create_legal_entity(
            LegalEntityInput(
                TENANT,
                company_id,
                code,
                f"{code} Company",
                "KRW",
                "KRW",
                "Asia/Seoul",
                date(2026, 1, 1),
            )
        )
    projects = SqlAlchemyEosProjectRepository(sessions)
    projects.create_nvt_project(NvtProjectInput(TENANT, NVT_ID, "NVT-S202", "NVT"))
    for project_id, code in (
        (PROJECT_A, "PROJECT-A"),
        (PROJECT_B, "PROJECT-B"),
        (PROJECT_OTHER, "PROJECT-X"),
    ):
        projects.create_project(
            ProjectInput(
                TENANT,
                project_id,
                code,
                code,
                nvt_project_id=NVT_ID,
            )
        )
    for project_id, company_id in (
        (PROJECT_A, COMPANY_ID),
        (PROJECT_B, COMPANY_ID),
        (PROJECT_OTHER, OTHER_COMPANY_ID),
    ):
        entities.create_project_company_binding(
            ProjectCompanyBindingInput(
                TENANT,
                str(uuid.uuid4()),
                project_id,
                company_id,
                date(2026, 1, 1),
                "sha256:" + "c" * 64,
            )
        )
    SqlAlchemyEosApprovalPolicyRepository(sessions).create_policy(
        ApprovalPolicyInput(
            tenant_id=TENANT,
            approval_policy_id=POLICY_ID,
            policy_key="mybee.accounting.s2-02",
            name="MyBee accounting approval",
            approval_domain="BUSINESS_FORMAL",
            effective_from=NOW - timedelta(days=1),
            transaction_type=transaction_type,
            stages=(
                ApprovalPolicyStageInput("TEAM_LEAD"),
                ApprovalPolicyStageInput("CEO"),
            ),
        )
    )
    authorization = AuthorizationSource()
    wc = WcClient()
    service = EosScopedApprovalService(
        repository=SqlAlchemyEosScopedApprovalRepository(sessions, clock=lambda: NOW),
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            sessions, clock=lambda: NOW
        ),
        authorization_source=authorization,
        wc_client=wc,
        clock=lambda: NOW,
    )
    return engine, sessions, service, authorization, wc


def _request(**overrides):
    values = {
        "tenant_id": TENANT,
        "business_operation_id": OPERATION_ID,
        "idempotency_key": "s2-02-project-set",
        "case_id": CASE_ID,
        "company_id": COMPANY_ID,
        "purpose": "ACCOUNTING_POSTING",
        "scope_type": "PROJECT_SET",
        "project_ids": [PROJECT_A, PROJECT_B],
        "subject_ref": "mybee.voucher:voucher-2026-0001",
        "subject_revision": 1,
        "subject_hash": SUBJECT_HASH,
        "requester_subject_id": "employee-requester",
        "approval_policy_id": POLICY_ID,
        "correlation_id": "s2-02-correlation",
        "causation_id": "s2-02-causation",
        "expires_at": NOW + timedelta(days=2),
    }
    values.update(overrides)
    return build_scoped_approval_request(**values)


def _caller() -> EosServiceCaller:
    return EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


def _direct_value(**overrides) -> ScopedApprovalCaseInput:
    values = {
        "tenant_id": TENANT,
        "case_id": str(uuid.uuid4()),
        "idempotency_key": f"direct-{uuid.uuid4()}",
        "company_id": COMPANY_ID,
        "purpose": "ACCOUNTING_POSTING",
        "scope_type": "PROJECT_SET",
        "project_ids": (PROJECT_A, PROJECT_B),
        "subject_ref": f"mybee.direct:{uuid.uuid4()}",
        "subject_revision": 1,
        "subject_hash": SUBJECT_HASH,
        "requester_subject_id": "employee-requester",
        "approval_policy_id": POLICY_ID,
        "oa_decision_ref": "oa-authz:s2-02",
        "authorization_revision_hash": "sha256:" + AUTH_REVISION,
        "authorization_checked_at": NOW,
        "created_business_operation_id": str(uuid.uuid4()),
        "correlation_id": "direct-correlation",
        "causation_id": "direct-causation",
        "expires_at": NOW + timedelta(days=1),
    }
    values.update(overrides)
    return ScopedApprovalCaseInput(**values)


def test_s2_02_migration_openapi_and_legacy_v1_boundary() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2527_eos_scoped_approval_case_v2"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_scoped_approval_case" in compact
    assert "create table if not exists eos_scoped_approval_subject_binding" in compact
    assert "where state in ('pending', 'approved')" in compact
    assert "alter table eos_approval_instance" not in compact
    assert "eos_guard_scoped_approval_case" in compact
    assert "eos_guard_scoped_approval_binding" in compact
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for table in (
            EOS_SCOPED_APPROVAL_CASE_TABLE,
            EOS_SCOPED_APPROVAL_BINDING_TABLE,
        )
        for constraint in table.constraints
    )
    assert EOS_APPROVAL_INSTANCE_TABLE.c.project_id.nullable is False

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    route = spec["paths"]["/internal/v2/finance/accounting-approval-cases"]["post"]
    assert route["operationId"] == "FINANCE.ACCOUNTING_APPROVAL.REQUEST"
    assert route["x-nex-route-class"] == "WRITE"
    assert route["x-nex-business-scope"] == "finance:journal:request-approval"


def test_project_set_case_commits_bindings_publishes_wc_and_replays() -> None:
    _engine, sessions, service, _authorization, wc = _build_runtime()
    request = _request()
    assert (
        scoped_approval_payload_hash(request.payload) == request.payload["payload_hash"]
    )
    receipt = service.request_case(request.payload, caller=_caller())
    assert receipt["created"] is True
    assert receipt["commit_state"] == "COMMITTED"
    scoped_case = receipt["scoped_approval_case"]
    assert scoped_case["scope_type"] == "PROJECT_SET"
    assert scoped_case["project_ids"] == [PROJECT_A, PROJECT_B]
    assert len(scoped_case["project_bindings"]) == 2
    assert scoped_case["active_stage_order"] == 1
    assert scoped_case["stage_count"] == 2
    assert scoped_case["target_role_ref"] == "TEAM_LEAD"
    work_item = receipt["wc_publication"]["work_item"]
    assert work_item["approval_domain"] == "BUSINESS_FORMAL"
    assert work_item["approval_request_id"] == CASE_ID
    assert work_item["target_project_scope_ref"] is None

    replay = service.request_case(request.payload, caller=_caller())
    assert replay["created"] is False
    assert replay["scoped_approval_case"] == scoped_case
    assert replay["wc_publication"]["created"] is False
    assert len(wc.items) == 1
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_SCOPED_APPROVAL_CASE_TABLE)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_SCOPED_APPROVAL_BINDING_TABLE)
            )
            == 2
        )


def test_company_scope_uses_no_fake_project_binding() -> None:
    _engine, sessions, service, authorization, _wc = _build_runtime()
    authorization.project_ids = None
    request = _request(
        business_operation_id=str(uuid.uuid4()),
        idempotency_key="s2-02-company",
        case_id=str(uuid.uuid4()),
        scope_type="COMPANY",
        project_ids=[],
        subject_ref="mybee.document:company-policy",
    )
    receipt = service.request_case(request.payload, caller=_caller())
    assert receipt["scoped_approval_case"]["project_ids"] == []
    assert receipt["scoped_approval_case"]["project_bindings"] == []
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_SCOPED_APPROVAL_BINDING_TABLE)
            )
            == 0
        )


def test_repository_direct_create_get_replay_and_conflict_paths() -> None:
    _engine, sessions, _service, _authorization, _wc = _build_runtime()
    repository = SqlAlchemyEosScopedApprovalRepository(sessions, clock=lambda: NOW)
    value = _direct_value()
    projection, created = repository.create(value)
    assert created is True
    assert repository.get_case(tenant_id=TENANT, case_id=value.case_id) == projection
    replay, replay_created = repository.create(value)
    assert replay_created is False
    assert replay == projection
    assert repository.get_case(tenant_id=TENANT, case_id=str(uuid.uuid4())) is None

    with pytest.raises(EosScopedApprovalError) as semantic_conflict:
        repository.create(replace(value, subject_ref="mybee.direct:changed"))
    assert semantic_conflict.value.status_code == 409

    with pytest.raises(EosScopedApprovalError) as subject_conflict:
        repository.create(
            replace(
                value,
                case_id=str(uuid.uuid4()),
                idempotency_key=f"direct-{uuid.uuid4()}",
                created_business_operation_id=str(uuid.uuid4()),
            )
        )
    assert subject_conflict.value.status_code == 409


def test_policy_company_and_project_reference_guard_matrix() -> None:
    _engine, sessions, service, authorization, _wc = _build_runtime()
    authorization.company_ids = None
    authorization.project_ids = None
    missing_policy = _request(approval_policy_id=str(uuid.uuid4()))
    with pytest.raises(EosScopedApprovalError) as missing:
        service.request_case(missing_policy.payload, caller=_caller())
    assert missing.value.status_code == 404

    with sessions.begin() as session:
        session.execute(
            delete(EOS_APPROVAL_POLICY_STAGE_TABLE).where(
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == TENANT,
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id == POLICY_ID,
            )
        )
    with pytest.raises(EosScopedApprovalError) as no_stages:
        service.request_case(_request().payload, caller=_caller())
    assert no_stages.value.status_code == 409

    _engine, sessions, service, authorization, _wc = _build_runtime()
    authorization.company_ids = None
    authorization.project_ids = None
    with sessions.begin() as session:
        session.execute(
            update(EOS_LEGAL_ENTITY_TABLE)
            .where(
                EOS_LEGAL_ENTITY_TABLE.c.tenant_id == TENANT,
                EOS_LEGAL_ENTITY_TABLE.c.company_id == COMPANY_ID,
            )
            .values(status="INACTIVE")
        )
    with pytest.raises(EosScopedApprovalError) as inactive_company:
        service.request_case(_request().payload, caller=_caller())
    assert inactive_company.value.status_code == 409

    _engine, sessions, service, authorization, _wc = _build_runtime()
    authorization.company_ids = None
    authorization.project_ids = None
    with sessions.begin() as session:
        session.execute(
            update(EOS_APPROVAL_POLICY_TABLE)
            .where(
                EOS_APPROVAL_POLICY_TABLE.c.tenant_id == TENANT,
                EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id == POLICY_ID,
            )
            .values(project_id=PROJECT_A)
        )
    with pytest.raises(EosScopedApprovalError) as policy_scope:
        service.request_case(_request().payload, caller=_caller())
    assert policy_scope.value.status_code == 409

    _engine, sessions, service, authorization, _wc = _build_runtime()
    authorization.company_ids = None
    authorization.project_ids = None
    with sessions.begin() as session:
        session.execute(
            update(EOS_PROJECT_TABLE)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == TENANT,
                EOS_PROJECT_TABLE.c.project_id == PROJECT_A,
            )
            .values(status="INACTIVE")
        )
    with pytest.raises(EosScopedApprovalError) as inactive_project:
        service.request_case(_request().payload, caller=_caller())
    assert inactive_project.value.status_code == 409


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"scope_type": "COMPANY", "project_ids": [PROJECT_A]}, "scope shape"),
        ({"scope_type": "PROJECT", "project_ids": []}, "scope shape"),
        ({"scope_type": "PROJECT_SET", "project_ids": [PROJECT_A]}, "scope shape"),
        ({"project_ids": "not-an-array"}, "array"),
        ({"project_ids": [PROJECT_A, PROJECT_A]}, "unique"),
        ({"tenant_id": " bad"}, "invalid"),
        ({"case_id": "bad"}, "invalid"),
        ({"subject_revision": 0}, "invalid"),
        ({"subject_hash": "sha256:bad"}, "invalid"),
        ({"expires_at": NOW.replace(tzinfo=None)}, "timezone"),
    ),
)
def test_mybee_request_contract_rejects_invalid_scope_matrix(
    overrides, message
) -> None:
    with pytest.raises(ScopedApprovalContractError) as error:
        _request(**overrides)
    assert message.lower() in str(error.value).lower()


def test_cross_company_and_inactive_reference_are_rejected_before_wc() -> None:
    _engine, _sessions, service, authorization, wc = _build_runtime()
    authorization.project_ids = [PROJECT_A, PROJECT_OTHER]
    cross_company = _request(project_ids=[PROJECT_A, PROJECT_OTHER])
    with pytest.raises(EosScopedApprovalError) as error:
        service.request_case(cross_company.payload, caller=_caller())
    assert error.value.status_code == 409
    assert wc.items == {}

    missing = _request(company_id=str(uuid.uuid4()))
    authorization.company_ids = None
    authorization.project_ids = None
    with pytest.raises(EosScopedApprovalError) as error:
        service.request_case(missing.payload, caller=_caller())
    assert error.value.status_code == 404


def test_authorization_denial_unavailability_and_projection_drift() -> None:
    _engine, _sessions, service, authorization, _wc = _build_runtime()
    request = _request()
    authorization.denied = True
    with pytest.raises(EosScopedApprovalError) as denied:
        service.request_case(request.payload, caller=_caller())
    assert denied.value.status_code == 403

    authorization.denied = False
    authorization.unavailable = True
    with pytest.raises(EosScopedApprovalError) as unavailable:
        service.request_case(request.payload, caller=_caller())
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True

    authorization.unavailable = False
    mutations = (
        ("active", False),
        ("tenant_id", "other-tenant"),
        ("subject_id", "other-user"),
        ("scopes", []),
        ("scopes", "finance:journal:request-approval"),
        ("scopes", ["finance:journal:request-approval", ""]),
        ("company_ids", [OTHER_COMPANY_ID]),
        ("project_ids", [PROJECT_A]),
        ("revision_hash", "bad"),
    )
    for field, value in mutations:
        previous = getattr(authorization, field)
        setattr(authorization, field, value)
        with pytest.raises(EosScopedApprovalError) as error:
            service.request_case(request.payload, caller=_caller())
        assert error.value.status_code == 403
        setattr(authorization, field, previous)

    authorization.decision_ref = None
    authorization.revision_hash = "sha256:" + AUTH_REVISION
    receipt = service.request_case(request.payload, caller=_caller())
    assert receipt["scoped_approval_case"]["oa_decision_ref"].startswith("oa-authz:")


def test_service_request_shape_and_operation_admission_fail_closed() -> None:
    _engine, _sessions, service, authorization, _wc = _build_runtime()
    authorization.company_ids = None
    authorization.project_ids = None

    def with_hash(payload):
        payload["payload_hash"] = scoped_approval_payload_hash(payload)
        return payload

    request = _request()
    payload = dict(request.payload)
    payload["requested_operation"] = "UNKNOWN.OPERATION.REQUEST"
    with pytest.raises(EosScopedApprovalError):
        service.request_case(payload, caller=_caller())

    payload = dict(request.payload)
    payload["requested_operation"] = "PROJECT.PROJECT.GET"
    with pytest.raises(EosScopedApprovalError):
        service.request_case(payload, caller=_caller())

    payload = with_hash({**dict(request.payload), "case": 1})
    with pytest.raises(EosScopedApprovalError):
        service.request_case(payload, caller=_caller())

    for mutation in (
        lambda case: case.update(unexpected=True),
        lambda case: case.update(tenant_id="other-tenant"),
        lambda case: case.update(project_ids="not-an-array"),
        lambda case: case.update(project_ids=[PROJECT_A, PROJECT_A]),
        lambda case: case.update(expires_at=(NOW - timedelta(seconds=1)).isoformat()),
    ):
        payload = deepcopy(dict(request.payload))
        mutation(payload["case"])
        with_hash(payload)
        with pytest.raises(EosScopedApprovalError):
            service.request_case(payload, caller=_caller())

    with pytest.raises(EosScopedApprovalError):
        scoped_approval_payload_hash([])

    non_pending = service.request_case(request.payload, caller=_caller())[
        "scoped_approval_case"
    ]
    non_pending = {**non_pending, "state": "APPROVED", "active_stage_order": None}
    with pytest.raises(EosScopedApprovalError):
        scoped_approval_work_item(non_pending)


def test_repository_input_validation_matrix() -> None:
    _engine, sessions, _service, _authorization, _wc = _build_runtime()
    repository = SqlAlchemyEosScopedApprovalRepository(sessions, clock=lambda: NOW)
    with pytest.raises(EosScopedApprovalError):
        repository.create("not-an-input")

    value = _direct_value()
    mutations = (
        {"scope_type": "COMPANY"},
        {"tenant_id": " bad"},
        {"case_id": "bad"},
        {"subject_revision": 0},
        {"idempotency_key": ""},
        {"purpose": "DELETE"},
        {"subject_hash": "sha256:bad"},
        {"authorization_checked_at": NOW.replace(tzinfo=None)},
        {"expires_at": "not-a-time"},
    )
    for mutation in mutations:
        with pytest.raises(EosScopedApprovalError):
            repository.create(replace(value, **mutation))

    without_expiry, created = repository.create(
        replace(
            value,
            case_id=str(uuid.uuid4()),
            idempotency_key=f"direct-{uuid.uuid4()}",
            subject_ref=f"mybee.direct:{uuid.uuid4()}",
            created_business_operation_id=str(uuid.uuid4()),
            expires_at=None,
        )
    )
    assert created is True and without_expiry["expires_at"] is None


def test_coordinator_requires_transaction_session() -> None:
    class NoneCoordinator:
        def execute(self, _request, mutation):
            return mutation(None)

    _engine, sessions, _service, authorization, wc = _build_runtime()
    service = EosScopedApprovalService(
        repository=SqlAlchemyEosScopedApprovalRepository(sessions, clock=lambda: NOW),
        coordinator=NoneCoordinator(),
        authorization_source=authorization,
        wc_client=wc,
        clock=lambda: NOW,
    )
    with pytest.raises(RuntimeError, match="database transaction"):
        service.request_case(_request().payload, caller=_caller())


def test_policy_payload_trust_and_wc_fail_closed_matrix() -> None:
    _engine, _sessions, service, _authorization, wc = _build_runtime(
        transaction_type="DOCUMENT_SIGNOFF"
    )
    request = _request()
    with pytest.raises(EosScopedApprovalError) as policy_error:
        service.request_case(request.payload, caller=_caller())
    assert policy_error.value.status_code == 409

    _engine, _sessions, service, _authorization, wc = _build_runtime()
    malformed_hash = dict(request.payload)
    malformed_hash["payload_hash"] = "sha256:" + "f" * 64
    with pytest.raises(EosScopedApprovalError) as hash_error:
        service.request_case(malformed_hash, caller=_caller())
    assert hash_error.value.error_code == "EOS_SCOPED_APPROVAL_PAYLOAD_HASH_MISMATCH"

    with pytest.raises(EosScopedApprovalError) as trust_error:
        service.request_case(
            _request().payload,
            caller=EosServiceCaller("nex-ae-api", "other", ("service:call",)),
        )
    assert trust_error.value.status_code == 403
    for caller in (None, EosServiceCaller("nex-ae-api", "nex-eos", ())):
        with pytest.raises(EosScopedApprovalError):
            service.request_case(_request().payload, caller=caller)

    wc.fail = True
    with pytest.raises(EosScopedApprovalError) as wc_error:
        service.request_case(_request().payload, caller=_caller())
    assert wc_error.value.status_code == 503
    assert wc_error.value.retryable is True
    wc.fail = False
    wc.malformed = True
    with pytest.raises(EosScopedApprovalError) as malformed:
        service.request_case(_request().payload, caller=_caller())
    assert malformed.value.status_code == 502
    wc.malformed = False
    wc.non_mapping = True
    with pytest.raises(EosScopedApprovalError) as non_mapping:
        service.request_case(_request().payload, caller=_caller())
    assert non_mapping.value.status_code == 502
    wc.non_mapping = False
    wc.drift = True
    with pytest.raises(EosScopedApprovalError) as drift:
        service.request_case(_request().payload, caller=_caller())
    assert drift.value.status_code == 502


def test_mybee_consumer_admits_exact_receipt_and_rejects_lineage_drift() -> None:
    _engine, _sessions, service, _authorization, _wc = _build_runtime()
    request = _request()
    receipt = service.request_case(request.payload, caller=_caller())
    admitted = admit_scoped_approval_receipt(
        receipt,
        tenant_id=TENANT,
        business_operation_id=OPERATION_ID,
        case_id=CASE_ID,
    )
    assert admitted["scoped_approval_case"]["project_ids"] == [PROJECT_A, PROJECT_B]

    malformed = dict(receipt)
    malformed["tenant_id"] = "other-tenant"
    with pytest.raises(ScopedApprovalContractError):
        admit_scoped_approval_receipt(
            malformed,
            tenant_id=TENANT,
            business_operation_id=OPERATION_ID,
            case_id=CASE_ID,
        )


def test_mybee_consumer_rejects_case_and_receipt_drift_matrix() -> None:
    _engine, _sessions, service, _authorization, _wc = _build_runtime()
    receipt = service.request_case(_request().payload, caller=_caller())

    def reject(value):
        with pytest.raises(ScopedApprovalContractError):
            admit_scoped_approval_receipt(
                value,
                tenant_id=TENANT,
                business_operation_id=OPERATION_ID,
                case_id=CASE_ID,
            )

    reject(None)
    for field, value in (
        ("schema_version", "v1"),
        ("created", "true"),
        ("commit_state", "PENDING"),
        ("business_operation_id", str(uuid.uuid4())),
        ("wc_publication", []),
    ):
        malformed = deepcopy(receipt)
        malformed[field] = value
        reject(malformed)

    case_mutations = (
        ("schema_version", "v1"),
        ("case_id", str(uuid.uuid4())),
        ("company_id", "bad"),
        ("purpose", "DELETE"),
        ("scope_type", "COMPANY"),
        ("project_ids", [PROJECT_B, PROJECT_A]),
        ("project_set_hash", "sha256:bad"),
        ("subject_ref", " bad"),
        ("subject_revision", 0),
        ("state", "DELETED"),
        ("stage_count", 0),
        ("authorization_checked_at", "not-a-time"),
        ("created_at", "2026-11-11T03:00:00"),
        ("updated_at", 1),
        ("requester_ref", {"type": "oa.user"}),
        ("approval_policy_ref", {"id": POLICY_ID}),
        ("project_bindings", []),
    )
    for field, value in case_mutations:
        malformed = deepcopy(receipt)
        malformed["scoped_approval_case"][field] = value
        reject(malformed)

    malformed = deepcopy(receipt)
    malformed["scoped_approval_case"]["unexpected"] = True
    reject(malformed)
    malformed = deepcopy(receipt)
    malformed["scoped_approval_case"]["project_bindings"][0]["project_id"] = str(
        uuid.uuid4()
    )
    reject(malformed)
    malformed = deepcopy(receipt)
    malformed["scoped_approval_case"]["project_bindings"][0][
        "company_id"
    ] = OTHER_COMPANY_ID
    reject(malformed)

    from mybee_ax.integrations.nex_approval_client import scoped_approval_request_hash

    with pytest.raises(ScopedApprovalContractError):
        scoped_approval_request_hash([])
    with pytest.raises(ScopedApprovalContractError):
        _request(idempotency_key="")
    malformed = dict(receipt)
    malformed["wc_publication"] = {"created": True, "work_item": {}}
    with pytest.raises(ScopedApprovalContractError):
        admit_scoped_approval_receipt(
            malformed,
            tenant_id=TENANT,
            business_operation_id=OPERATION_ID,
            case_id=CASE_ID,
        )


class FakeScopedApprovalService:
    def request_case(self, payload, *, caller):
        if payload.get("fail"):
            raise EosScopedApprovalError("DENIED", "denied", status_code=403)
        return {"created": payload.get("created", True), "caller": caller.subject}


def test_route_requires_write_trust_maps_errors_and_service_unavailable() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s2-02",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_scoped_approval_service = FakeScopedApprovalService()
    client = TestClient(app)
    path = "/internal/v2/finance/accounting-approval-cases"
    assert client.post(path, json={}).status_code == 401
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    assert client.post(path, headers=headers, json={}).status_code == 201
    assert (
        client.post(path, headers=headers, json={"created": False}).status_code == 200
    )
    assert client.post(path, headers=headers, json={"fail": True}).status_code == 403
    app.state.eos_scoped_approval_service = None
    assert client.post(path, headers=headers, json={}).status_code == 503


def test_repository_persistence_failures_are_typed() -> None:
    class BrokenSession:
        def __enter__(self):
            raise SQLAlchemyError("broken")

        def __exit__(self, *_args):
            return False

    class BrokenFactory:
        def __call__(self):
            return BrokenSession()

        def begin(self):
            return BrokenSession()

    repository = SqlAlchemyEosScopedApprovalRepository(BrokenFactory())
    with pytest.raises(EosScopedApprovalError) as error:
        repository.get_case(tenant_id=TENANT, case_id=CASE_ID)
    assert error.value.status_code == 503
    assert error.value.retryable is True
    with pytest.raises(EosScopedApprovalError) as create_error:
        repository.create(_direct_value())
    assert create_error.value.status_code == 503


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S2-02 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_scoped_case_immutability_and_zero_residue() -> None:
    schema_name = f"mybee_s202_{uuid.uuid4().hex}"
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
        _runtime_engine, _sessions, service, _authorization, _wc = _build_runtime(
            engine=engine
        )
        receipt = service.request_case(_request().payload, caller=_caller())
        assert receipt["created"] is True
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            row = connection.execute(
                sql.SQL(
                    "SELECT scope_type, state, version FROM {}.eos_scoped_approval_case"
                ).format(sql.Identifier(schema_name))
            ).fetchone()
            assert row == ("PROJECT_SET", "PENDING", 1)
            assert connection.execute(
                sql.SQL(
                    "SELECT count(*) FROM {}.eos_scoped_approval_subject_binding"
                ).format(sql.Identifier(schema_name))
            ).fetchone() == (2,)
            assert connection.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = 'eos_approval_instance' "
                "AND column_name = 'project_id'",
                (schema_name,),
            ).fetchone() == ("NO",)
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.eos_scoped_approval_case SET subject_revision = 2"
                    ).format(sql.Identifier(schema_name))
                )
            connection.execute(
                sql.SQL(
                    "UPDATE {}.eos_scoped_approval_case "
                    "SET state = 'APPROVED', active_stage_order = NULL, "
                    "target_role_ref = NULL, version = 2, updated_at = now(), "
                    "decided_at = now()"
                ).format(sql.Identifier(schema_name))
            )
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL("DELETE FROM {}.eos_scoped_approval_case").format(
                        sql.Identifier(schema_name)
                    )
                )
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL(
                        "DELETE FROM {}.eos_scoped_approval_subject_binding"
                    ).format(sql.Identifier(schema_name))
                )
    finally:
        engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
