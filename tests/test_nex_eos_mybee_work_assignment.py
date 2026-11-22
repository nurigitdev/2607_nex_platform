from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from nex_eos import (
    D12_CATALOG_DIGEST,
    D12_CATALOG_ID,
    D12_CATALOG_VERSION,
    EOS_METADATA,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    EOS_PROJECT_WORK_ASSIGNMENT_TABLE,
    MANDATORY_D12_WORK_CODE_IDS,
    EosProjectWorkAssignmentError,
    EosProjectWorkAssignmentService,
    NvtProjectInput,
    ProjectInput,
    ProjectMembershipInput,
    ProjectWorkAssignmentInput,
    ProjectWorkCodeSetApproval,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosProjectWorkAssignmentRepository,
    SqlAlchemyEosProjectWorkCodeRepository,
    create_eos_app,
    project_work_assignment_payload_hash,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_eos.voucher_commands import EosServiceCaller
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, make_url, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT_ID = "tenant-a"
OTHER_TENANT_ID = "tenant-b"
NVT_ID = "c1000000-0000-4000-8000-000000000001"
PROJECT_ID = "c2000000-0000-4000-8000-000000000001"
WORK_SET_ID = "c3000000-0000-4000-8000-000000000001"
ASSIGNMENT_ID = "c4000000-0000-4000-8000-000000000001"
OWNER_ID = "owner-a"
WORKER_ID = "worker-a"
VIEWER_ID = "viewer-a"
PA_ID = "pa-project-a"
PROOF = "sha256:" + "a" * 64
GRADE_POLICY_HASH = "sha256:" + "b" * 64
PA_EVIDENCE = "sha256:" + "c" * 64
AUTH_REVISION = "d" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S1_06_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self) -> None:
        self.denied: set[str] = set()
        self.unavailable = False
        self.project_ids = [PROJECT_ID]
        self.revision_hash = AUTH_REVISION

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("private OA failure")
        if subject_id in self.denied:
            raise AuthorizationSubjectDenied("inactive")
        scopes = (
            [
                "project:work-assignment:manage",
                "project:work-assignment:read",
            ]
            if subject_id == OWNER_ID
            else ["project:work-assignment:perform"]
        )
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": scopes,
            "project_ids": self.project_ids,
            "revision_hash": self.revision_hash,
        }


class FixedAuthorizationSource:
    def __init__(self, value: object) -> None:
        self.value = value

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        return self.value


def _build_stack(*, worker_role: str = "MEMBER"):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    projects.create_nvt_project(NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S106", "NVT"))
    projects.create_project(
        ProjectInput(
            TENANT_ID,
            PROJECT_ID,
            "PROJECT-S106",
            "Project S1-06",
            nvt_project_id=NVT_ID,
        )
    )
    memberships = SqlAlchemyEosProjectMembershipRepository(factory)
    for subject_id, role in ((OWNER_ID, "OWNER"), (WORKER_ID, worker_role)):
        memberships.create_membership(
            ProjectMembershipInput(
                TENANT_ID,
                str(uuid.uuid4()),
                PROJECT_ID,
                subject_id,
                role,
                OWNER_ID,
                valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            )
        )
    SqlAlchemyEosProjectWorkCodeRepository(factory).approve(_work_set())
    return engine, factory


def _work_set() -> ProjectWorkCodeSetApproval:
    return ProjectWorkCodeSetApproval(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        work_set_id=WORK_SET_ID,
        revision=1,
        catalog_id=D12_CATALOG_ID,
        catalog_version=D12_CATALOG_VERSION,
        catalog_digest=D12_CATALOG_DIGEST,
        template_ref="mybee.d12.required-five",
        template_version="1.0.0",
        code_ids=MANDATORY_D12_WORK_CODE_IDS,
        approved_proof_hash=PROOF,
        approved_by_subject_id=OWNER_ID,
        pm_subject_id=OWNER_ID,
        pa_agent_id=PA_ID,
        pa_identity_evidence_hash=PA_EVIDENCE,
        effective_from=date(2026, 1, 1),
    )


def _value(
    *,
    assignment_id: str = ASSIGNMENT_ID,
    performer_kind: str = "HUMAN",
    subject_ref: str = WORKER_ID,
    performer_authority_hash: str = "sha256:" + AUTH_REVISION,
    valid_from: date = date(2026, 1, 1),
    valid_until: date | None = date(2026, 1, 31),
) -> ProjectWorkAssignmentInput:
    return ProjectWorkAssignmentInput(
        tenant_id=TENANT_ID,
        assignment_id=assignment_id,
        project_id=PROJECT_ID,
        work_set_id=WORK_SET_ID,
        work_set_revision=1,
        work_code_id=MANDATORY_D12_WORK_CODE_IDS[0],
        performer_kind=performer_kind,
        subject_ref=subject_ref,
        performer_authority_hash=performer_authority_hash,
        assignment_scope="EXECUTE",
        planned_man_days=Decimal("12.5000"),
        planned_grade_id="G4",
        grade_policy_ref="mybee.grade-policy:2026.1",
        grade_policy_hash=GRADE_POLICY_HASH,
        valid_from=valid_from,
        valid_until=valid_until,
        approved_proof_hash=PROOF,
        approved_by_subject_id=OWNER_ID,
    )


def _command(
    *,
    assignment_id: str = ASSIGNMENT_ID,
    performer_kind: str = "HUMAN",
    subject_ref: str = WORKER_ID,
    business_operation_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "business_operation_id": business_operation_id or str(uuid.uuid4()),
        "idempotency_key": f"s1-06:{uuid.uuid4()}",
        "requester_subject_id": OWNER_ID,
        "requested_operation": "PROJECT.WORK_ASSIGNMENT.ASSIGN",
        "project_id": PROJECT_ID,
        "assignment": {
            "assignment_id": assignment_id,
            "work_set_id": WORK_SET_ID,
            "work_set_revision": 1,
            "work_code_id": MANDATORY_D12_WORK_CODE_IDS[0],
            "performer_kind": performer_kind,
            "subject_ref": subject_ref,
            "assignment_scope": "EXECUTE",
            "planned_man_days": "12.5000",
            "planned_grade_id": "G4",
            "grade_policy_ref": "mybee.grade-policy:2026.1",
            "grade_policy_hash": GRADE_POLICY_HASH,
            "valid_from": "2026-01-01",
            "valid_until": "2026-01-31",
            "approved_proof_hash": PROOF,
        },
    }
    payload["payload_hash"] = project_work_assignment_payload_hash(payload)
    return payload


def _service(factory, source: object | None = None) -> EosProjectWorkAssignmentService:
    return EosProjectWorkAssignmentService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=source or AuthorizationSource(),
    )


CALLER = EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


def test_s1_06_migration_and_openapi_freeze_planning_privacy_boundary() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2525_eos_project_work_assignment"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_project_work_assignment" in compact
    assert "pg_advisory_xact_lock" in compact
    assert "eos_guard_project_assignment_overlap" in compact
    assert "eos_reject_project_assignment_mutation" in compact
    assert not {"salary", "payroll", "actual_day_rate"}.intersection(
        {column.name for column in EOS_PROJECT_WORK_ASSIGNMENT_TABLE.columns}
    )

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    paths = spec["paths"]
    assert (
        paths["/internal/v2/projects/{project_id}/work-assignments:assign"]["post"][
            "operationId"
        ]
        == "PROJECT.WORK_ASSIGNMENT.ASSIGN"
    )
    assert (
        paths["/internal/v2/projects/{project_id}/work-assignments"]["get"][
            "operationId"
        ]
        == "PROJECT.WORK_ASSIGNMENT.LIST"
    )
    schemas = spec["components"]["schemas"]
    output = schemas["ProjectWorkAssignment"]
    assert output["additionalProperties"] is False
    assert "planned_man_days" in output["properties"]
    assert not {"salary", "payroll_amount", "actual_payroll_cost"}.intersection(
        output["properties"]
    )


def test_repository_persists_grade_man_day_plan_and_replays_same_identity() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkAssignmentRepository(factory)
    created = repository.assign(_value())
    replay = repository.assign(_value())
    assert created["planned_man_days"] == "12.5000"
    assert created["planned_grade_id"] == "G4"
    assert replay["assignment_hash"] == created["assignment_hash"]
    assert not {"salary", "actual_payroll_cost"}.intersection(created)
    assert repository.list_for_project(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        effective_on=date(2026, 1, 15),
        work_code_id=MANDATORY_D12_WORK_CODE_IDS[0],
    ) == [created]
    assert (
        repository.list_for_project(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            effective_on=date(2027, 1, 1),
        )
        == []
    )


def test_repository_accepts_admitted_pa_and_rejects_wrong_agent_or_viewer() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkAssignmentRepository(factory)
    agent = repository.assign(
        _value(
            performer_kind="AGENT",
            subject_ref=PA_ID,
            performer_authority_hash=PA_EVIDENCE,
        )
    )
    assert agent["performer_kind"] == "AGENT"

    with pytest.raises(EosProjectWorkAssignmentError) as wrong_agent:
        repository.assign(
            _value(
                assignment_id=str(uuid.uuid4()),
                performer_kind="AGENT",
                subject_ref="pa-other",
                performer_authority_hash=PA_EVIDENCE,
            )
        )
    assert wrong_agent.value.status_code == 403

    _engine, factory = _build_stack(worker_role="VIEWER")
    with pytest.raises(EosProjectWorkAssignmentError) as viewer:
        SqlAlchemyEosProjectWorkAssignmentRepository(factory).assign(_value())
    assert viewer.value.status_code == 403


def test_repository_rejects_overlap_identity_drift_and_invalid_contracts() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkAssignmentRepository(factory)
    repository.assign(_value())
    with pytest.raises(EosProjectWorkAssignmentError) as overlap:
        repository.assign(
            _value(
                assignment_id=str(uuid.uuid4()),
                valid_from=date(2026, 1, 31),
                valid_until=date(2026, 2, 28),
            )
        )
    assert overlap.value.status_code == 409
    with pytest.raises(EosProjectWorkAssignmentError) as drift:
        repository.assign(replace(_value(), planned_grade_id="G5"))
    assert drift.value.status_code == 409

    invalid = (
        replace(_value(assignment_id=str(uuid.uuid4())), planned_man_days=1.5),
        replace(_value(assignment_id=str(uuid.uuid4())), planned_man_days="bad"),
        replace(_value(assignment_id=str(uuid.uuid4())), planned_man_days=Decimal(0)),
        replace(
            _value(assignment_id=str(uuid.uuid4())),
            planned_man_days=Decimal("1.00001"),
        ),
        replace(_value(assignment_id=str(uuid.uuid4())), work_set_revision=True),
        replace(_value(assignment_id=str(uuid.uuid4())), work_code_id="BAD"),
        replace(_value(assignment_id=str(uuid.uuid4())), assignment_scope="BAD"),
        replace(_value(assignment_id=str(uuid.uuid4())), grade_policy_hash="bad"),
        replace(
            _value(assignment_id=str(uuid.uuid4())),
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        replace(
            _value(assignment_id=str(uuid.uuid4())),
            valid_from=date(2026, 3, 1),
            valid_until=date(2026, 2, 1),
        ),
    )
    for value in invalid:
        with pytest.raises(EosProjectWorkAssignmentError) as rejected:
            repository.assign(value)
        assert rejected.value.status_code == 422


def test_repository_requires_project_work_set_code_and_effective_membership() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkAssignmentRepository(factory)
    variants = (
        replace(_value(), project_id=str(uuid.uuid4())),
        replace(_value(), work_set_id=str(uuid.uuid4())),
        replace(_value(), work_code_id="FL9999999"),
        replace(_value(), subject_ref="missing-member"),
    )
    for value in variants:
        with pytest.raises(EosProjectWorkAssignmentError):
            repository.assign(value)

    with factory.begin() as session:
        session.execute(
            update(EOS_PROJECT_TABLE)
            .where(EOS_PROJECT_TABLE.c.tenant_id == TENANT_ID)
            .values(status="INACTIVE")
        )
    with pytest.raises(EosProjectWorkAssignmentError) as inactive:
        repository.assign(_value())
    assert inactive.value.status_code == 409


def test_repository_rejects_future_membership_and_non_typed_input() -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkAssignmentRepository(factory)
    with factory.begin() as session:
        session.execute(
            update(EOS_PROJECT_MEMBER_TABLE)
            .where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT_ID,
                EOS_PROJECT_MEMBER_TABLE.c.subject_id == WORKER_ID,
            )
            .values(valid_from=datetime(2027, 1, 1, tzinfo=UTC))
        )
    with pytest.raises(EosProjectWorkAssignmentError) as future:
        repository.assign(_value())
    assert future.value.status_code == 403
    with pytest.raises(EosProjectWorkAssignmentError) as untyped:
        repository.assign("not-an-assignment")
    assert untyped.value.status_code == 422


def test_service_exactly_once_and_private_payroll_rejection() -> None:
    _engine, factory = _build_stack()
    service = _service(factory)
    payload = _command()
    created = service.assign(payload, caller=CALLER)
    replay = service.assign(payload, caller=CALLER)
    assert created["created"] is True
    assert replay["created"] is False
    assert created["result"]["work_assignment"]["planned_grade_id"] == "G4"
    listing = service.list_assignments(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        requester_subject_id=OWNER_ID,
    )
    assert listing["private_payroll_excluded"] is True
    assert listing["data_classification"] == "INTERNAL_PLANNING"

    private = _command(assignment_id=str(uuid.uuid4()))
    private["assignment"]["salary"] = "100000000"  # type: ignore[index]
    private["payload_hash"] = project_work_assignment_payload_hash(private)
    with pytest.raises(EosProjectWorkAssignmentError) as rejected:
        service.assign(private, caller=CALLER)
    assert rejected.value.error_code.endswith("PRIVATE_PAYROLL_FORBIDDEN")


def test_service_authorization_trust_hash_and_membership_fail_closed() -> None:
    _engine, factory = _build_stack()
    source = AuthorizationSource()
    service = _service(factory, source)
    payload = _command()
    payload["payload_hash"] = "sha256:" + "0" * 64
    with pytest.raises(EosProjectWorkAssignmentError) as bad_hash:
        service.assign(payload, caller=CALLER)
    assert bad_hash.value.status_code == 422
    with pytest.raises(EosProjectWorkAssignmentError) as trust:
        service.assign(
            _command(),
            caller=EosServiceCaller("nex-ae-api", "wrong", ("service:call",)),
        )
    assert trust.value.status_code == 403

    source.denied.add(WORKER_ID)
    with pytest.raises(EosProjectWorkAssignmentError) as inactive:
        service.assign(_command(), caller=CALLER)
    assert inactive.value.status_code == 403
    source.denied.clear()
    source.unavailable = True
    with pytest.raises(EosProjectWorkAssignmentError) as unavailable:
        service.assign(_command(), caller=CALLER)
    assert unavailable.value.status_code == 503


def test_service_agent_authority_operation_admission_and_transaction_guards() -> None:
    _engine, factory = _build_stack()
    service = _service(factory)
    created = service.assign(
        _command(performer_kind="AGENT", subject_ref=PA_ID), caller=CALLER
    )
    assert created["result"]["work_assignment"]["performer_authority_hash"] == (
        PA_EVIDENCE
    )

    wrong_agent = _command(
        assignment_id=str(uuid.uuid4()),
        performer_kind="AGENT",
        subject_ref="pa-other",
    )
    with pytest.raises(EosProjectWorkAssignmentError) as denied:
        service.assign(wrong_agent, caller=CALLER)
    assert denied.value.status_code == 403

    for operation in ("NOT.ADMITTED", "PROJECT.PROJECT.CREATE"):
        payload = _command(assignment_id=str(uuid.uuid4()))
        payload["requested_operation"] = operation
        with pytest.raises(EosProjectWorkAssignmentError) as rejected:
            service.assign(payload, caller=CALLER)
        assert rejected.value.status_code == 422

    malformed = _command(assignment_id=str(uuid.uuid4()))
    malformed["assignment"].pop("planned_grade_id")  # type: ignore[union-attr]
    malformed["payload_hash"] = project_work_assignment_payload_hash(malformed)
    with pytest.raises(EosProjectWorkAssignmentError) as shape:
        service.assign(malformed, caller=CALLER)
    assert shape.value.status_code == 422

    for invalid_date in (20260101, "not-a-date"):
        payload = _command(assignment_id=str(uuid.uuid4()))
        payload["assignment"]["valid_from"] = invalid_date  # type: ignore[index]
        payload["payload_hash"] = project_work_assignment_payload_hash(payload)
        with pytest.raises(EosProjectWorkAssignmentError) as rejected_date:
            service.assign(payload, caller=CALLER)
        assert rejected_date.value.status_code == 422

    class NullSessionCoordinator:
        def execute(self, _request, mutation):
            return mutation(None)

    null_service = EosProjectWorkAssignmentService(
        session_factory=factory,
        coordinator=NullSessionCoordinator(),
        authorization_source=AuthorizationSource(),
    )
    with pytest.raises(RuntimeError, match="requires a database transaction"):
        null_service.assign(_command(assignment_id=str(uuid.uuid4())), caller=CALLER)


def test_service_role_and_read_membership_fail_closed_and_admin_bypasses() -> None:
    class SubjectAuthorizationSource(AuthorizationSource):
        def effective_authorization(self, *, tenant_id: str, subject_id: str):
            return {
                "active": True,
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "scopes": [
                    "project:work-assignment:manage",
                    "project:work-assignment:read",
                    "project:work-assignment:perform",
                ],
                "project_ids": [PROJECT_ID],
                "revision_hash": AUTH_REVISION,
            }

    _engine, factory = _build_stack()
    service = _service(factory, SubjectAuthorizationSource())
    payload = _command(assignment_id=str(uuid.uuid4()))
    payload["requester_subject_id"] = WORKER_ID
    payload["payload_hash"] = project_work_assignment_payload_hash(payload)
    with pytest.raises(EosProjectWorkAssignmentError) as role:
        service.assign(payload, caller=CALLER)
    assert role.value.status_code == 403

    with pytest.raises(EosProjectWorkAssignmentError) as read_membership:
        service.list_assignments(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="non-member",
        )
    assert read_membership.value.status_code == 403

    admin = FixedAuthorizationSource(
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": "platform-admin",
            "scopes": [
                "project:work-assignment:read",
                "project:project:admin",
            ],
            "revision_hash": AUTH_REVISION,
        }
    )
    assert (
        _service(factory, admin).list_assignments(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="platform-admin",
        )["count"]
        == 0
    )


def test_service_maps_read_and_agent_authority_database_failures(monkeypatch) -> None:
    _engine, factory = _build_stack()
    service = _service(factory)

    def database_error(*_args, **_kwargs):
        raise SQLAlchemyError("offline")

    monkeypatch.setattr(service._repository, "require_project_role", database_error)
    with pytest.raises(EosProjectWorkAssignmentError) as read_failure:
        service.list_assignments(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
        )
    assert read_failure.value.status_code == 503

    class BrokenFactory:
        def __call__(self):
            raise SQLAlchemyError("offline")

    agent_service = EosProjectWorkAssignmentService(
        session_factory=BrokenFactory(),
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=AuthorizationSource(),
    )
    with pytest.raises(EosProjectWorkAssignmentError) as agent_failure:
        agent_service.assign(
            _command(
                assignment_id=str(uuid.uuid4()),
                performer_kind="AGENT",
                subject_ref=PA_ID,
            ),
            caller=CALLER,
        )
    assert agent_failure.value.status_code == 503


def test_service_and_hash_helpers_reject_non_objects_and_bad_identifiers() -> None:
    with pytest.raises(EosProjectWorkAssignmentError):
        project_work_assignment_payload_hash("not-an-object")
    _engine, factory = _build_stack()
    service = _service(factory)
    malformed_values = (
        ("assignment", None),
        ("tenant_id", "bad tenant"),
        ("business_operation_id", "bad-uuid"),
        ("idempotency_key", ""),
    )
    for field, value in malformed_values:
        payload = _command(assignment_id=str(uuid.uuid4()))
        payload[field] = value
        payload["payload_hash"] = project_work_assignment_payload_hash(payload)
        with pytest.raises(EosProjectWorkAssignmentError) as rejected:
            service.assign(payload, caller=CALLER)
        assert rejected.value.status_code == 422


@pytest.mark.parametrize(
    "value",
    (
        None,
        {},
        {
            "active": False,
            "tenant_id": TENANT_ID,
            "subject_id": OWNER_ID,
            "scopes": ["project:work-assignment:read"],
            "revision_hash": AUTH_REVISION,
        },
        {
            "active": True,
            "tenant_id": OTHER_TENANT_ID,
            "subject_id": OWNER_ID,
            "scopes": ["project:work-assignment:read"],
            "revision_hash": AUTH_REVISION,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": OWNER_ID,
            "scopes": "project:work-assignment:read",
            "revision_hash": AUTH_REVISION,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": OWNER_ID,
            "scopes": [],
            "revision_hash": AUTH_REVISION,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": OWNER_ID,
            "scopes": ["project:work-assignment:read", 7],
            "revision_hash": AUTH_REVISION,
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": OWNER_ID,
            "scopes": ["project:work-assignment:read"],
            "revision_hash": "bad",
            "project_ids": ["other-project"],
        },
        {
            "active": True,
            "tenant_id": TENANT_ID,
            "subject_id": OWNER_ID,
            "scopes": ["project:work-assignment:read"],
            "revision_hash": AUTH_REVISION,
            "project_ids": ["other-project"],
        },
    ),
)
def test_service_read_authorization_projection_rejects_drift(value) -> None:
    _engine, factory = _build_stack()
    service = _service(factory, FixedAuthorizationSource(value))
    with pytest.raises(EosProjectWorkAssignmentError) as rejected:
        service.list_assignments(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id=OWNER_ID,
        )
    assert rejected.value.status_code == 403


def test_repository_maps_integrity_and_database_failures(monkeypatch) -> None:
    _engine, factory = _build_stack()
    repository = SqlAlchemyEosProjectWorkAssignmentRepository(factory)

    def raise_integrity(_session, _value):
        raise IntegrityError("insert", {}, RuntimeError("conflict"))

    monkeypatch.setattr(repository, "assign_in_session", raise_integrity)
    with pytest.raises(EosProjectWorkAssignmentError) as conflict:
        repository.assign(_value())
    assert conflict.value.status_code == 409

    class BrokenFactory:
        def begin(self):
            raise SQLAlchemyError("offline")

        def __call__(self):
            raise SQLAlchemyError("offline")

    broken = SqlAlchemyEosProjectWorkAssignmentRepository(BrokenFactory())
    with pytest.raises(EosProjectWorkAssignmentError) as assign_error:
        broken.assign(_value())
    with pytest.raises(EosProjectWorkAssignmentError) as list_error:
        broken.list_for_project(tenant_id=TENANT_ID, project_id=PROJECT_ID)
    assert {assign_error.value.status_code, list_error.value.status_code} == {503}


class FakeWorkAssignmentService:
    def assign(self, payload, *, caller):
        return {"created": payload.get("replay") is not True, "result": payload}

    def list_assignments(self, **kwargs):
        return {"items": [], "count": 0, **kwargs}


def test_v2_routes_require_trust_map_replay_and_hide_unavailable_service() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-06",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_project_work_assignment_service = FakeWorkAssignmentService()
    client = TestClient(app)
    path = f"/internal/v2/projects/{PROJECT_ID}/work-assignments"
    assert client.get(path).status_code == 422
    assert client.post(f"{path}:assign", json={}).status_code == 401
    assert (
        client.get(
            path,
            headers={
                "X-NeX-Tenant-Id": TENANT_ID,
                "X-NeX-Subject-Id": OWNER_ID,
            },
        ).status_code
        == 401
    )
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": OWNER_ID,
    }
    assert client.get(path, headers=headers).status_code == 200
    command = _command()
    command.pop("project_id")
    assert (
        client.post(f"{path}:assign", headers=headers, json=command).status_code == 201
    )
    command["replay"] = True
    assert (
        client.post(f"{path}:assign", headers=headers, json=command).status_code == 200
    )
    app.state.eos_project_work_assignment_service = None
    assert client.get(path, headers=headers).status_code == 503
    assert (
        client.post(f"{path}:assign", headers=headers, json=command).status_code == 503
    )


def test_v2_routes_map_assignment_domain_failures() -> None:
    class FailingWorkAssignmentService(FakeWorkAssignmentService):
        def assign(self, payload, *, caller):
            raise EosProjectWorkAssignmentError(
                "EOS_PROJECT_WORK_ASSIGNMENT_CONFLICT",
                "conflict",
                status_code=409,
            )

        def list_assignments(self, **kwargs):
            raise EosProjectWorkAssignmentError(
                "EOS_PROJECT_WORK_ASSIGNMENT_AUTHORIZATION_DENIED",
                "denied",
                status_code=403,
            )

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-06",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_project_work_assignment_service = FailingWorkAssignmentService()
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": OWNER_ID,
    }
    path = f"/internal/v2/projects/{PROJECT_ID}/work-assignments"
    assert TestClient(app).get(path, headers=headers).status_code == 403
    command = _command()
    command.pop("project_id")
    response = TestClient(app).post(f"{path}:assign", headers=headers, json=command)
    assert response.status_code == 409


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S1-06 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_overlap_immutability_and_zero_residue() -> None:
    schema_name = f"mybee_s106_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        identity = connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone()
        assert identity == ("nex_eos_test", "nex_eos_user")
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
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    projects.create_nvt_project(NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S106", "NVT"))
    projects.create_project(
        ProjectInput(
            TENANT_ID,
            PROJECT_ID,
            "PROJECT-S106",
            "Project S1-06",
            nvt_project_id=NVT_ID,
        )
    )
    memberships = SqlAlchemyEosProjectMembershipRepository(factory)
    for subject_id, role in ((OWNER_ID, "OWNER"), (WORKER_ID, "MEMBER")):
        memberships.create_membership(
            ProjectMembershipInput(
                TENANT_ID,
                str(uuid.uuid4()),
                PROJECT_ID,
                subject_id,
                role,
                OWNER_ID,
                valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            )
        )
    SqlAlchemyEosProjectWorkCodeRepository(factory).approve(_work_set())
    barrier = Barrier(2)

    def assign(identifier: str) -> str:
        barrier.wait()
        try:
            SqlAlchemyEosProjectWorkAssignmentRepository(factory).assign(
                _value(assignment_id=identifier)
            )
            return "created"
        except EosProjectWorkAssignmentError as exc:
            return f"error:{exc.status_code}"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(assign, (ASSIGNMENT_ID, str(uuid.uuid4()))))
        assert sorted(outcomes) == ["created", "error:409"]
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.eos_project_work_assignment "
                        "SET planned_grade_id = 'G5'"
                    ).format(sql.Identifier(schema_name))
                )
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL("DELETE FROM {}.eos_project_work_assignment").format(
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
