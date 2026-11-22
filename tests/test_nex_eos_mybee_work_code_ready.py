from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from mybee_ax.domain.work_codes import load_work_code_catalog
from nex_eos import (
    D12_CATALOG_DIGEST,
    D12_CATALOG_ID,
    D12_CATALOG_VERSION,
    EOS_METADATA,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    EOS_PROJECT_WORK_CODE_ENTRY_TABLE,
    EOS_PROJECT_WORK_CODE_SET_TABLE,
    MANDATORY_D12_CODES_HASH,
    MANDATORY_D12_WORK_CODE_IDS,
    EosProjectBusinessService,
    EosProjectWorkCodeError,
    LegalEntityInput,
    NvtProjectInput,
    ProjectCompanyBindingInput,
    ProjectInput,
    ProjectMembershipInput,
    ProjectWorkCodeSetApproval,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosProjectWorkCodeRepository,
    build_eos_database_runtime,
    create_eos_app,
    project_work_code_set_payload_hash,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_eos.voucher_commands import EosServiceCaller
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT_ID = "tenant-a"
OTHER_TENANT_ID = "tenant-b"
NVT_ID = "b1000000-0000-4000-8000-000000000001"
PROJECT_ID = "b2000000-0000-4000-8000-000000000001"
COMPANY_ID = "b3000000-0000-4000-8000-000000000001"
BINDING_ID = "b4000000-0000-4000-8000-000000000001"
WORK_SET_ID = "b5000000-0000-4000-8000-000000000001"
OWNER_ID = "owner-a"
PM_ID = "pm-a"
PA_ID = "pa-project-a"
PROOF = "sha256:" + "a" * 64
PA_EVIDENCE = "sha256:" + "b" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S1_05_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self) -> None:
        self.denied = False
        self.unavailable = False
        self.scopes = {
            "project:work-code:approve",
            "project:work-code:read",
        }

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("private OA detail")
        if self.denied:
            raise AuthorizationSubjectDenied("inactive")
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": sorted(self.scopes),
            "project_ids": [PROJECT_ID],
            "revision_hash": "c" * 64,
        }


class FixedAuthorizationSource:
    def __init__(self, value=None, *, error: Exception | None = None) -> None:
        self.value = value
        self.error = error

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.error is not None:
            raise self.error
        return self.value


def _build_stack(*, manager: bool = True, company: bool = True):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    projects.create_nvt_project(
        NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S105", "NVT S1-05")
    )
    projects.create_project(
        ProjectInput(
            TENANT_ID,
            PROJECT_ID,
            "PROJECT-S105",
            "Project S1-05",
            nvt_project_id=NVT_ID,
        )
    )
    memberships = SqlAlchemyEosProjectMembershipRepository(factory)
    memberships.create_membership(
        ProjectMembershipInput(
            TENANT_ID,
            str(uuid.uuid4()),
            PROJECT_ID,
            OWNER_ID,
            "OWNER",
            OWNER_ID,
        )
    )
    if manager:
        memberships.create_membership(
            ProjectMembershipInput(
                TENANT_ID,
                str(uuid.uuid4()),
                PROJECT_ID,
                PM_ID,
                "MANAGER",
                OWNER_ID,
            )
        )
    if company:
        legal = SqlAlchemyEosLegalEntityRepository(factory)
        legal.create_legal_entity(
            LegalEntityInput(
                TENANT_ID,
                COMPANY_ID,
                "NEX-KR",
                "NeX Korea",
                "KRW",
                "KRW",
                "Asia/Seoul",
                date(2026, 1, 1),
            )
        )
        legal.create_project_company_binding(
            ProjectCompanyBindingInput(
                TENANT_ID,
                BINDING_ID,
                PROJECT_ID,
                COMPANY_ID,
                date(2026, 1, 1),
                PROOF,
            )
        )
    return engine, factory


def _approval(
    *,
    revision: int = 1,
    work_set_id: str = WORK_SET_ID,
    code_ids: tuple[str, ...] = MANDATORY_D12_WORK_CODE_IDS,
    catalog_digest: str = D12_CATALOG_DIGEST,
    pm_subject_id: str = PM_ID,
    pa_agent_id: str = PA_ID,
) -> ProjectWorkCodeSetApproval:
    return ProjectWorkCodeSetApproval(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        work_set_id=work_set_id,
        revision=revision,
        catalog_id=D12_CATALOG_ID,
        catalog_version=D12_CATALOG_VERSION,
        catalog_digest=catalog_digest,
        template_ref="mybee.d12.required-five",
        template_version="1.0.0",
        code_ids=code_ids,
        approved_proof_hash=PROOF,
        approved_by_subject_id=OWNER_ID,
        pm_subject_id=pm_subject_id,
        pa_agent_id=pa_agent_id,
        pa_identity_evidence_hash=PA_EVIDENCE,
        effective_from=date(2026, 1, 1),
    )


def _command(*, operation_id: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "business_operation_id": operation_id or str(uuid.uuid4()),
        "idempotency_key": f"s1-05:{uuid.uuid4()}",
        "requester_subject_id": OWNER_ID,
        "requested_operation": "PROJECT.WORK_CODE_SET.APPROVE",
        "project_id": PROJECT_ID,
        "work_set": {
            "work_set_id": WORK_SET_ID,
            "revision": 1,
            "catalog_id": D12_CATALOG_ID,
            "catalog_version": D12_CATALOG_VERSION,
            "catalog_digest": D12_CATALOG_DIGEST,
            "template_ref": "mybee.d12.required-five",
            "template_version": "1.0.0",
            "code_ids": list(MANDATORY_D12_WORK_CODE_IDS),
            "approved_proof_hash": PROOF,
            "pm_subject_id": PM_ID,
            "pa_agent_id": PA_ID,
            "pa_identity_evidence_hash": PA_EVIDENCE,
            "effective_from": "2026-01-01",
        },
    }
    payload["payload_hash"] = project_work_code_set_payload_hash(payload)
    return payload


def test_s1_05_catalog_pin_and_migration_contract_are_source_backed() -> None:
    catalog = load_work_code_catalog()
    assert (catalog.catalog_id, catalog.catalog_version, catalog.mapping_digest) == (
        D12_CATALOG_ID,
        D12_CATALOG_VERSION,
        D12_CATALOG_DIGEST,
    )
    assert tuple(item.code_id for item in catalog.work_codes) == (
        MANDATORY_D12_WORK_CODE_IDS
    )

    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2524_eos_project_work_code_readiness"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_project_work_code_set" in compact
    assert "create table if not exists eos_project_work_code_entry" in compact
    assert "eos_guard_project_work_set_revision" in compact
    assert "deferrable initially deferred" in compact
    assert "eos_reject_project_work_set_mutation" in compact
    for code_id in MANDATORY_D12_WORK_CODE_IDS:
        assert code_id.lower() in compact


def test_s1_05_openapi_freezes_work_set_and_business_ready_boundaries() -> None:
    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    paths = spec["paths"]
    approval = paths["/internal/v2/projects/{project_id}/work-code-sets:approve"][
        "post"
    ]
    work_set = paths["/internal/v2/projects/{project_id}/work-code-set"]["get"]
    readiness = paths["/internal/v2/projects/{project_id}/business-readiness"]["get"]
    assert approval["operationId"] == "PROJECT.WORK_CODE_SET.APPROVE"
    assert approval["x-nex-business-scope"] == "project:work-code:approve"
    assert approval["x-nex-route-class"] == "WRITE"
    assert work_set["operationId"] == "PROJECT.WORK_CODE_SET.GET"
    assert readiness["operationId"] == "PROJECT.BUSINESS_READINESS.GET"
    assert work_set["x-nex-side-effect-free"] is True
    assert readiness["x-nex-side-effect-free"] is True


def test_work_set_approval_replay_and_business_ready_projection() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)

    before = repository.evaluate_business_readiness(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        effective_on=date(2026, 1, 1),
    )
    assert before["state"] == "DRAFT_CONFIGURATION"
    assert before["business_ready"] is False
    assert before["technical_status"] == "ACTIVE"
    assert "WORK_CODE_SET_MISSING" in before["reason_codes"]

    created = repository.approve(_approval())
    replay = repository.approve(_approval())
    assert replay == created
    assert created["code_ids"] == list(MANDATORY_D12_WORK_CODE_IDS)
    assert created["mandatory_codes_hash"] == MANDATORY_D12_CODES_HASH

    ready = repository.evaluate_business_readiness(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        effective_on=date(2026, 1, 1),
    )
    assert ready["state"] == "BUSINESS_READY"
    assert ready["business_ready"] is True
    assert ready["required_codes_ok"] is True
    assert ready["project_company_bound"] is True
    assert ready["pm_assigned"] is True
    assert ready["pa_identity_bound"] is True
    assert ready["reason_codes"] == []
    assert ready["work_set"]["work_set_hash"] == created["work_set_hash"]


def test_business_ready_is_distinct_from_active_and_reacts_to_current_inputs() -> None:
    _engine, factory = _build_stack(manager=False, company=False)
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)
    repository.approve(_approval())

    not_ready = repository.evaluate_business_readiness(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        effective_on=date(2026, 1, 1),
    )
    assert not_ready["technical_status"] == "ACTIVE"
    assert not_ready["state"] == "WORK_SET_APPROVED"
    assert not_ready["business_ready"] is False
    assert set(not_ready["reason_codes"]) == {
        "PROJECT_COMPANY_BINDING_MISSING",
        "PM_MEMBERSHIP_MISSING",
    }

    with factory.begin() as session:
        session.execute(
            update(EOS_PROJECT_TABLE)
            .where(
                EOS_PROJECT_TABLE.c.tenant_id == TENANT_ID,
                EOS_PROJECT_TABLE.c.project_id == PROJECT_ID,
            )
            .values(status="INACTIVE")
        )
    blocked = repository.evaluate_business_readiness(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        effective_on=date(2026, 1, 1),
    )
    assert blocked["state"] == "BLOCKED"
    assert "PROJECT_INACTIVE" in blocked["reason_codes"]


def test_business_ready_intermediate_and_corrupt_source_states_fail_closed() -> None:
    _engine, factory = _build_stack(company=False)
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)
    repository.approve(_approval())
    member_ready = repository.evaluate_business_readiness(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        effective_on=date(2026, 1, 1),
    )
    assert member_ready["state"] == "MEMBER_READY"
    assert member_ready["reason_codes"] == ["PROJECT_COMPANY_BINDING_MISSING"]

    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)
    repository.approve(_approval())
    with factory.begin() as session:
        session.execute(
            delete(EOS_PROJECT_WORK_CODE_ENTRY_TABLE).where(
                EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.tenant_id == TENANT_ID,
                EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.project_id == PROJECT_ID,
                EOS_PROJECT_WORK_CODE_ENTRY_TABLE.c.work_code_id
                == MANDATORY_D12_WORK_CODE_IDS[0],
            )
        )
        session.execute(
            delete(EOS_PROJECT_MEMBER_TABLE).where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT_ID,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == PROJECT_ID,
            )
        )
        session.execute(
            update(EOS_PROJECT_WORK_CODE_SET_TABLE)
            .where(EOS_PROJECT_WORK_CODE_SET_TABLE.c.tenant_id == TENANT_ID)
            .values(pa_agent_id="")
        )
    blocked = repository.evaluate_business_readiness(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        effective_on=date(2026, 1, 1),
    )
    assert blocked["state"] == "BLOCKED"
    assert {
        "MANDATORY_WORK_CODES_INVALID",
        "PM_MEMBERSHIP_MISSING",
        "PROJECT_MEMBER_MISSING",
        "PA_IDENTITY_MISSING_OR_CONFLICTING",
    } <= set(blocked["reason_codes"])


def test_work_set_approval_rejects_missing_inactive_and_initial_revision_gap() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)

    with pytest.raises(EosProjectWorkCodeError) as missing:
        repository.approve(
            replace(_approval(), project_id="b2000000-0000-4000-8000-000000000099")
        )
    assert missing.value.error_code == "EOS_PROJECT_WORK_CODE_NOT_FOUND"

    with factory.begin() as session:
        session.execute(
            update(EOS_PROJECT_TABLE)
            .where(EOS_PROJECT_TABLE.c.tenant_id == TENANT_ID)
            .values(status="INACTIVE")
        )
    with pytest.raises(EosProjectWorkCodeError) as inactive:
        repository.approve(_approval())
    assert inactive.value.error_code == "EOS_PROJECT_WORK_CODE_CONFLICT"

    _engine, factory = _build_stack()
    with pytest.raises(EosProjectWorkCodeError) as gap:
        SqlAlchemyEosProjectWorkCodeRepository(factory).approve(_approval(revision=2))
    assert gap.value.error_code == "EOS_PROJECT_WORK_CODE_CONFLICT"


def test_revision_advances_immutably_and_rejects_identity_drift() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)
    first = repository.approve(_approval())
    second = repository.approve(_approval(revision=2))
    assert first["revision"] == 1
    assert second["revision"] == 2
    assert first["work_set_hash"] != second["work_set_hash"]
    assert (
        repository.get_current_set(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            effective_on=date(2026, 1, 1),
        )["revision"]
        == 2
    )

    with pytest.raises(EosProjectWorkCodeError) as gap:
        repository.approve(_approval(revision=4))
    assert gap.value.error_code == "EOS_PROJECT_WORK_CODE_CONFLICT"
    with pytest.raises(EosProjectWorkCodeError) as new_stream:
        repository.approve(_approval(revision=3, work_set_id=str(uuid.uuid4())))
    assert new_stream.value.error_code == "EOS_PROJECT_WORK_CODE_CONFLICT"
    with pytest.raises(EosProjectWorkCodeError) as drift:
        repository.approve(replace(_approval(revision=2), template_version="2.0.0"))
    assert drift.value.error_code == "EOS_PROJECT_WORK_CODE_CONFLICT"

    with factory() as session:
        assert len(session.execute(select(EOS_PROJECT_WORK_CODE_SET_TABLE)).all()) == 2
        assert (
            len(session.execute(select(EOS_PROJECT_WORK_CODE_ENTRY_TABLE)).all()) == 10
        )


@pytest.mark.parametrize(
    "approval",
    (
        replace(_approval(), code_ids=MANDATORY_D12_WORK_CODE_IDS[:-1]),
        replace(_approval(), catalog_digest="sha256:" + "0" * 64),
        replace(_approval(), pm_subject_id=PA_ID),
        replace(_approval(), revision=0),
        replace(_approval(), revision=True),
        replace(_approval(), code_ids="FL0012004"),
        replace(_approval(), code_ids=()),
        replace(
            _approval(),
            code_ids=(
                "FL0012004",
                "FL0012004",
                "FL0012005",
                "FL0012006",
                "FL0012013",
                "FL0012026",
            ),
        ),
        replace(_approval(), template_version="v1"),
        replace(_approval(), approved_proof_hash="not-a-hash"),
        replace(_approval(), effective_from=datetime.now(UTC)),
        replace(
            _approval(),
            code_ids=(
                "FL0012005",
                "FL0012004",
                "FL0012006",
                "FL0012013",
                "FL0012026",
            ),
        ),
    ),
)
def test_work_set_admission_fails_closed_for_invalid_contracts(approval) -> None:
    _engine, factory = _build_stack()
    with pytest.raises(EosProjectWorkCodeError):
        SqlAlchemyEosProjectWorkCodeRepository(factory).approve(approval)


def test_repository_maps_integrity_and_database_failures(monkeypatch) -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)

    def raise_integrity(_session, _value):
        raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    monkeypatch.setattr(repository, "approve_in_session", raise_integrity)
    with pytest.raises(EosProjectWorkCodeError) as conflict:
        repository.approve(_approval())
    assert conflict.value.status_code == 409

    class BrokenFactory:
        def begin(self):
            raise SQLAlchemyError("database offline")

        def __call__(self):
            raise SQLAlchemyError("database offline")

    broken = SqlAlchemyEosProjectWorkCodeRepository(BrokenFactory())
    with pytest.raises(EosProjectWorkCodeError) as approve_unavailable:
        broken.approve(_approval())
    with pytest.raises(EosProjectWorkCodeError) as get_unavailable:
        broken.get_current_set(tenant_id=TENANT_ID, project_id=PROJECT_ID)
    with pytest.raises(EosProjectWorkCodeError) as ready_unavailable:
        broken.evaluate_business_readiness(tenant_id=TENANT_ID, project_id=PROJECT_ID)
    assert {
        approve_unavailable.value.status_code,
        get_unavailable.value.status_code,
        ready_unavailable.value.status_code,
    } == {503}


def test_repository_rejects_non_approval_value_and_invalid_identifiers() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)
    with pytest.raises(EosProjectWorkCodeError):
        repository.approve("not-an-approval")
    with pytest.raises(EosProjectWorkCodeError):
        repository.get_current_set(tenant_id="bad tenant", project_id=PROJECT_ID)
    with pytest.raises(EosProjectWorkCodeError):
        repository.evaluate_business_readiness(
            tenant_id=TENANT_ID, project_id="not-a-uuid"
        )


def test_tenant_scope_and_missing_project_fail_closed() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)
    repository.approve(_approval())
    assert (
        repository.get_current_set(
            tenant_id=OTHER_TENANT_ID,
            project_id=PROJECT_ID,
            effective_on=date(2026, 1, 1),
        )
        is None
    )
    with pytest.raises(EosProjectWorkCodeError) as missing:
        repository.evaluate_business_readiness(
            tenant_id=OTHER_TENANT_ID,
            project_id=PROJECT_ID,
            effective_on=date(2026, 1, 1),
        )
    assert missing.value.error_code == "EOS_PROJECT_WORK_CODE_NOT_FOUND"


def test_service_reuses_business_operation_and_fresh_oa_authority() -> None:
    _engine, factory = _build_stack()
    source = AuthorizationSource()
    service = EosProjectBusinessService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=source,
    )
    payload = _command()
    caller = EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))
    created = service.approve_work_code_set(payload, caller=caller)
    replay = service.approve_work_code_set(payload, caller=caller)
    assert created["created"] is True
    assert replay["created"] is False
    assert created["result"]["work_set"]["revision"] == 1
    assert (
        service.get_business_readiness(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
            effective_on=date(2026, 1, 1),
        )["business_ready"]
        is True
    )

    source.scopes.remove("project:work-code:read")
    with pytest.raises(EosProjectWorkCodeError) as denied:
        service.get_work_code_set(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
        )
    assert denied.value.error_code == "EOS_PROJECT_WORK_CODE_AUTHORIZATION_DENIED"
    source.unavailable = True
    with pytest.raises(EosProjectWorkCodeError) as unavailable:
        service.get_business_readiness(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
        )
    assert unavailable.value.status_code == 503


def test_service_rejects_bad_hash_trust_and_non_owner_approval() -> None:
    _engine, factory = _build_stack()
    service = EosProjectBusinessService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=AuthorizationSource(),
    )
    payload = _command()
    payload["payload_hash"] = "sha256:" + "0" * 64
    with pytest.raises(EosProjectWorkCodeError) as bad_hash:
        service.approve_work_code_set(
            payload,
            caller=EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",)),
        )
    assert bad_hash.value.error_code == "EOS_PROJECT_WORK_CODE_PAYLOAD_HASH_MISMATCH"

    with pytest.raises(EosProjectWorkCodeError) as trust:
        service.approve_work_code_set(
            _command(),
            caller=EosServiceCaller("nex-ae-api", "other", ("service:call",)),
        )
    assert trust.value.status_code == 403


def test_service_rejects_non_owner_and_missing_current_set() -> None:
    _engine, factory = _build_stack()
    memberships = SqlAlchemyEosProjectMembershipRepository(factory)
    memberships.create_membership(
        ProjectMembershipInput(
            TENANT_ID,
            str(uuid.uuid4()),
            PROJECT_ID,
            "member-a",
            "MEMBER",
            OWNER_ID,
        )
    )
    service = EosProjectBusinessService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=AuthorizationSource(),
    )
    with pytest.raises(EosProjectWorkCodeError) as missing:
        service.get_work_code_set(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
        )
    assert missing.value.status_code == 404

    payload = _command()
    payload["requester_subject_id"] = "member-a"
    payload["payload_hash"] = project_work_code_set_payload_hash(payload)
    with pytest.raises(EosProjectWorkCodeError) as denied:
        service.approve_work_code_set(
            payload,
            caller=EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",)),
        )
    assert denied.value.status_code == 403


def test_service_pm_authorization_and_transaction_guards() -> None:
    class PmAuthorizationSource(AuthorizationSource):
        def __init__(self, error: Exception) -> None:
            super().__init__()
            self.error = error

        def effective_authorization(self, *, tenant_id: str, subject_id: str):
            if subject_id == PM_ID:
                raise self.error
            return super().effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )

    caller = EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))
    for error, expected_status in (
        (AuthorizationSubjectDenied("inactive"), 403),
        (RuntimeError("OA unavailable"), 503),
    ):
        _engine, factory = _build_stack()
        service = EosProjectBusinessService(
            session_factory=factory,
            coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
            authorization_source=PmAuthorizationSource(error),
        )
        with pytest.raises(EosProjectWorkCodeError) as rejected:
            service.approve_work_code_set(_command(), caller=caller)
        assert rejected.value.status_code == expected_status

    class NullSessionCoordinator:
        def execute(self, _request, mutation):
            return mutation(None)

    _engine, factory = _build_stack()
    service = EosProjectBusinessService(
        session_factory=factory,
        coordinator=NullSessionCoordinator(),
        authorization_source=AuthorizationSource(),
    )
    with pytest.raises(RuntimeError, match="requires a database transaction"):
        service.approve_work_code_set(_command(), caller=caller)


def test_service_authorization_projection_matrix_fails_closed() -> None:
    _engine, factory = _build_stack()
    base = {
        "active": True,
        "tenant_id": TENANT_ID,
        "subject_id": OWNER_ID,
        "scopes": ["project:work-code:read"],
        "project_ids": [PROJECT_ID],
        "revision_hash": "c" * 64,
    }
    variants = (
        {**base, "active": False},
        {**base, "tenant_id": OTHER_TENANT_ID},
        {**base, "scopes": "project:work-code:read"},
        {**base, "scopes": ["project:work-code:read", 7]},
        {**base, "revision_hash": "bad"},
        {**base, "project_ids": ["other-project"]},
    )
    for value in variants:
        service = EosProjectBusinessService(
            session_factory=factory,
            coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
            authorization_source=FixedAuthorizationSource(value),
        )
        with pytest.raises(EosProjectWorkCodeError) as rejected:
            service.get_business_readiness(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                requester_subject_id=OWNER_ID,
            )
        assert rejected.value.status_code == 403

    service = EosProjectBusinessService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=FixedAuthorizationSource(
            error=AuthorizationSubjectDenied("inactive")
        ),
    )
    with pytest.raises(EosProjectWorkCodeError) as inactive:
        service.get_business_readiness(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
        )
    assert inactive.value.status_code == 403


def test_service_admin_read_bypasses_membership_and_maps_database_failure(
    monkeypatch,
) -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)
    repository.approve(_approval())
    with factory.begin() as session:
        session.execute(
            delete(EOS_PROJECT_MEMBER_TABLE).where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT_ID,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == PROJECT_ID,
            )
        )
    source = AuthorizationSource()
    source.scopes.add("project:project:admin")
    service = EosProjectBusinessService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=source,
    )
    assert (
        service.get_work_code_set(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
        )["revision"]
        == 1
    )

    source.scopes.remove("project:project:admin")

    def fail_role(*_args, **_kwargs):
        raise SQLAlchemyError("membership database unavailable")

    monkeypatch.setattr(service._repository, "require_project_role", fail_role)
    with pytest.raises(EosProjectWorkCodeError) as unavailable:
        service.get_work_code_set(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
        )
    assert unavailable.value.status_code == 503


def test_command_shape_and_operation_validation_matrix() -> None:
    with pytest.raises(EosProjectWorkCodeError):
        project_work_code_set_payload_hash(None)

    _engine, factory = _build_stack()
    service = EosProjectBusinessService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=AuthorizationSource(),
    )
    caller = EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))

    payloads = []
    unknown = _command()
    unknown["requested_operation"] = "UNKNOWN.OPERATION.NAME"
    payloads.append(unknown)
    wrong = _command()
    wrong["requested_operation"] = "PROJECT.CREATE"
    payloads.append(wrong)
    bad_object = _command()
    bad_object["work_set"] = "not-an-object"
    payloads.append(bad_object)
    bad_project = _command()
    bad_project["project_id"] = "not-a-uuid"
    payloads.append(bad_project)
    bad_idempotency = _command()
    bad_idempotency["idempotency_key"] = ""
    payloads.append(bad_idempotency)
    bad_date_type = _command()
    bad_date_type["work_set"]["effective_from"] = 20260101
    payloads.append(bad_date_type)
    bad_date_value = _command()
    bad_date_value["work_set"]["effective_from"] = "not-a-date"
    payloads.append(bad_date_value)

    for payload in payloads:
        payload["payload_hash"] = project_work_code_set_payload_hash(payload)
        with pytest.raises(EosProjectWorkCodeError) as invalid:
            service.approve_work_code_set(payload, caller=caller)
        assert invalid.value.status_code == 422


class FakeProjectBusinessService:
    def approve_work_code_set(self, payload, *, caller):
        return {"created": True, "result": {"project_id": payload["project_id"]}}

    def get_work_code_set(self, **kwargs):
        return {"project_id": kwargs["project_id"], "revision": 1}

    def get_business_readiness(self, **kwargs):
        return {"project_id": kwargs["project_id"], "business_ready": True}


def test_v2_routes_require_service_trust_and_map_unavailable_service() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-05",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_project_business_service = FakeProjectBusinessService()
    client = TestClient(app)
    path = f"/internal/v2/projects/{PROJECT_ID}/business-readiness"
    approve_path = f"/internal/v2/projects/{PROJECT_ID}/work-code-sets:approve"
    headers = {"X-NeX-Tenant-Id": TENANT_ID, "X-NeX-Subject-Id": OWNER_ID}
    assert client.get(path, headers=headers).status_code == 401
    assert client.post(approve_path, json=_command()).status_code == 401
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers["Authorization"] = f"Bearer {token.access_token}"
    assert client.get(path, headers=headers).status_code == 200
    assert (
        client.get(
            f"/internal/v2/projects/{PROJECT_ID}/work-code-set", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/internal/v2/projects/{PROJECT_ID}/work-code-sets:approve",
            headers={"Authorization": headers["Authorization"]},
            json=_command(),
        ).status_code
        == 201
    )
    app.state.eos_project_business_service = None
    assert client.get(path, headers=headers).status_code == 503
    assert (
        client.post(
            approve_path,
            headers={"Authorization": headers["Authorization"]},
            json=_command(),
        ).status_code
        == 503
    )


def test_v2_route_redacts_domain_failure() -> None:
    class FailingService(FakeProjectBusinessService):
        def get_business_readiness(self, **_kwargs):
            raise EosProjectWorkCodeError(
                "EOS_PROJECT_WORK_CODE_NOT_FOUND",
                "Project was not found",
                status_code=404,
            )

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-05",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_project_business_service = FailingService()
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    response = TestClient(app).get(
        f"/internal/v2/projects/{PROJECT_ID}/business-readiness",
        headers={
            "Authorization": f"Bearer {token.access_token}",
            "X-NeX-Tenant-Id": TENANT_ID,
            "X-NeX-Subject-Id": OWNER_ID,
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "EOS_PROJECT_WORK_CODE_NOT_FOUND"


def test_v2_approval_route_maps_domain_failure_and_replay_status() -> None:
    class FailingService(FakeProjectBusinessService):
        def approve_work_code_set(self, _payload, *, caller):
            raise EosProjectWorkCodeError(
                "EOS_PROJECT_WORK_CODE_CONFLICT",
                "revision conflict",
                status_code=409,
            )

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-05",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    path = f"/internal/v2/projects/{PROJECT_ID}/work-code-sets:approve"
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    app.state.eos_project_business_service = FailingService()
    response = TestClient(app).post(path, headers=headers, json=_command())
    assert response.status_code == 409
    assert response.json()["error_code"] == "EOS_PROJECT_WORK_CODE_CONFLICT"

    class ReplayService(FakeProjectBusinessService):
        def approve_work_code_set(self, payload, *, caller):
            return {"created": False, "result": {"project_id": payload["project_id"]}}

    app.state.eos_project_business_service = ReplayService()
    assert (
        TestClient(app).post(path, headers=headers, json=_command()).status_code == 200
    )


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S1-05 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_work_set_revision_immutability_and_zero_residue() -> None:
    schema_name = f"mybee_s105_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == (
            "nex_eos_test",
            "nex_eos_user",
        )
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    from sqlalchemy import make_url

    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    try:
        result = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2524_eos_project_work_code_readiness" in result.applied
        db = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        projects = SqlAlchemyEosProjectRepository(db.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT_ID, NVT_ID, "NVT-PG", "NVT PG")
        )
        projects.create_project(
            ProjectInput(
                TENANT_ID,
                PROJECT_ID,
                "PROJECT-PG",
                "Project PG",
                nvt_project_id=NVT_ID,
            )
        )
        memberships = SqlAlchemyEosProjectMembershipRepository(db.session_factory)
        memberships.create_membership(
            ProjectMembershipInput(
                TENANT_ID,
                str(uuid.uuid4()),
                PROJECT_ID,
                PM_ID,
                "MANAGER",
                OWNER_ID,
            )
        )
        repository = SqlAlchemyEosProjectWorkCodeRepository(db.session_factory)
        repository.approve(_approval())
        repository.approve(_approval(revision=2))

        barrier = Barrier(2)

        def approve_revision(value: ProjectWorkCodeSetApproval) -> str:
            barrier.wait()
            try:
                repository.approve(value)
                return "COMMITTED"
            except EosProjectWorkCodeError as exc:
                return exc.error_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(
                pool.map(
                    approve_revision,
                    (
                        _approval(revision=3),
                        replace(_approval(revision=3), template_version="2.0.0"),
                    ),
                )
            )
        assert sorted(outcomes) == ["COMMITTED", "EOS_PROJECT_WORK_CODE_CONFLICT"]
        with db.session_factory() as session:
            assert (
                len(session.execute(select(EOS_PROJECT_WORK_CODE_SET_TABLE)).all()) == 3
            )
            assert (
                len(session.execute(select(EOS_PROJECT_WORK_CODE_ENTRY_TABLE)).all())
                == 15
            )
        with pytest.raises(
            SQLAlchemyError, match="immutable"
        ), db.session_factory.begin() as session:
            session.execute(
                update(EOS_PROJECT_WORK_CODE_SET_TABLE)
                .where(EOS_PROJECT_WORK_CODE_SET_TABLE.c.tenant_id == TENANT_ID)
                .values(state="APPROVED")
            )
        db.dispose()
    finally:
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM information_schema.schemata WHERE schema_name=%s",
                    (schema_name,),
                ).fetchone()[0]
                == 0
            )
