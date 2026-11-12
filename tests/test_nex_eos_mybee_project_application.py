from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_METADATA,
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_APP_REVISION_TABLE,
    EOS_PROJECT_CODE_COUNTER_TABLE,
    EOS_PROJECT_TABLE,
    AuthorizationSubjectDenied,
    EosProjectApplicationError,
    EosProjectApplicationService,
    EosProjectError,
    NvtProjectInput,
    ProjectApplicationDraft,
    ProjectInput,
    SqlAlchemyEosProjectApplicationRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
    create_eos_app,
)
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, delete, make_url, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_W30_S00A_POSTGRES_SMOKE") == "1"

TENANT = "VO00"
APPLICANT = "employee-1004"
NVT_ID = "b1000000-0000-4000-8000-000000000001"
APPLICATION_ID = "b2000000-0000-4000-8000-000000000001"
PROJECT_ID = "b3000000-0000-4000-8000-000000000001"


class AuthorizationSource:
    def __init__(self) -> None:
        self.value: object = {
            "active": True,
            "tenant_id": TENANT,
            "subject_id": APPLICANT,
            "scopes": [
                "project:application:create",
                "project:application:read",
                "project:application:submit",
                "project:project:read",
            ],
            "revision_hash": "a" * 64,
        }

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    projects.create_nvt_project(
        NvtProjectInput(TENANT, NVT_ID, "NVT-W30", "W30 Portfolio")
    )
    applications = SqlAlchemyEosProjectApplicationRepository(factory)
    authorization = AuthorizationSource()
    service = EosProjectApplicationService(applications, authorization, projects)
    yield engine, factory, projects, applications, authorization, service
    engine.dispose()


def _draft(
    application_id: str = APPLICATION_ID,
    *,
    name: str = "NeX Project",
    purpose_type: str = "D",
) -> ProjectApplicationDraft:
    return ProjectApplicationDraft(
        tenant_id=TENANT,
        application_id=application_id,
        purpose_type=purpose_type,
        applicant_subject_id=APPLICANT,
        name=name,
        nvt_project_id=NVT_ID,
        currency="KRW",
    )


def test_application_code_revision_submission_and_exact_replay(runtime) -> None:
    _engine, factory, _projects, applications, _authorization, _service = runtime
    issued_at = datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
    created = applications.create_draft(_draft(), issued_at=issued_at)
    replay = applications.create_draft(_draft(), issued_at=issued_at)
    assert replay == created
    assert created["project_request_code"] == "VO00R270001"
    assert created["state"] == "DRAFT"
    assert created["current_revision"] == 1
    assert created["payload"]["name"] == "NeX Project"

    second = applications.create_draft(
        _draft(str(uuid.uuid4()), name="Second Project"),
        issued_at=issued_at,
    )
    assert second["project_request_code"] == "VO00R270002"
    with pytest.raises(EosProjectApplicationError, match="different semantics"):
        applications.create_draft(
            _draft(name="Changed under same identity"), issued_at=issued_at
        )

    revised = applications.revise_draft(
        replace(_draft(), name="Revised Project", purpose_type="M"),
        expected_version=1,
        actor_subject_id=APPLICANT,
    )
    assert revised["project_request_code"] == created["project_request_code"]
    assert revised["current_revision"] == 2
    assert revised["version"] == 2
    assert revised["payload"]["purpose_type"] == "M"
    exact_revision = applications.revise_draft(
        replace(_draft(), name="Revised Project", purpose_type="M"),
        expected_version=2,
        actor_subject_id=APPLICANT,
    )
    assert exact_revision == revised

    submitted = applications.submit(
        tenant_id=TENANT,
        project_request_code=created["project_request_code"],
        expected_version=2,
        actor_subject_id=APPLICANT,
    )
    assert submitted["state"] == "SUBMITTED"
    assert submitted["version"] == 3
    assert (
        applications.submit(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            expected_version=2,
            actor_subject_id=APPLICANT,
        )
        == submitted
    )
    with pytest.raises(EosProjectApplicationError, match="DRAFT"):
        applications.revise_draft(
            replace(_draft(), name="Too late"),
            expected_version=3,
            actor_subject_id=APPLICANT,
        )

    with factory() as session:
        revisions = (
            session.execute(
                select(EOS_PROJECT_APP_REVISION_TABLE.c.revision).where(
                    EOS_PROJECT_APP_REVISION_TABLE.c.application_id == APPLICATION_ID
                )
            )
            .scalars()
            .all()
        )
    assert revisions == [1, 2]


def test_code_kinds_year_boundaries_exhaustion_and_validation(runtime) -> None:
    _engine, factory, _projects, applications, _authorization, _service = runtime
    before = datetime(2026, 6, 1, tzinfo=UTC)
    after = datetime(2027, 6, 1, tzinfo=UTC)
    assert (
        applications.allocate_registration_code(
            tenant_id=TENANT, purpose_type="D", issued_at=before
        )
        == "VO00D260001"
    )
    assert (
        applications.allocate_registration_code(
            tenant_id=TENANT, purpose_type="D", issued_at=before
        )
        == "VO00D260002"
    )
    with factory.begin() as session:
        assert (
            applications.allocate_registration_code_in_session(
                session,
                tenant_id=TENANT,
                purpose_type="D",
                issued_at=before,
            )
            == "VO00D260003"
        )
    assert (
        applications.allocate_registration_code(
            tenant_id=TENANT, purpose_type="M", issued_at=before
        )
        == "VO00M260001"
    )
    assert (
        applications.allocate_registration_code(
            tenant_id=TENANT, purpose_type="D", issued_at=after
        )
        == "VO00D270001"
    )

    with factory.begin() as session:
        session.execute(
            update(EOS_PROJECT_CODE_COUNTER_TABLE)
            .where(
                EOS_PROJECT_CODE_COUNTER_TABLE.c.tenant_id == TENANT,
                EOS_PROJECT_CODE_COUNTER_TABLE.c.code_kind == "REGISTRATION",
                EOS_PROJECT_CODE_COUNTER_TABLE.c.purpose_type == "D",
                EOS_PROJECT_CODE_COUNTER_TABLE.c.code_year == 27,
            )
            .values(last_serial=9999)
        )
    with pytest.raises(EosProjectApplicationError) as exhausted:
        applications.allocate_registration_code(
            tenant_id=TENANT, purpose_type="D", issued_at=after
        )
    assert exhausted.value.error_code == "EOS_PROJECT_CODE_EXHAUSTED"

    invalid = [
        replace(_draft(), tenant_id="tenant-a"),
        replace(_draft(), purpose_type="X"),
        replace(_draft(), nvt_project_id=None),
        replace(_draft(), parent_project_id=PROJECT_ID),
    ]
    for value in invalid:
        with pytest.raises(EosProjectApplicationError):
            applications.create_draft(value)

    fallback_values = {
        "tenant_id": TENANT,
        "tenant_code": TENANT,
        "code_kind": "REGISTRATION",
        "purpose_type": "S",
        "code_year": 28,
        "last_serial": 1,
        "version": 1,
        "updated_at": datetime.now(UTC),
    }
    with factory.begin() as session:
        assert (
            applications._allocate_locked_fallback(session, fallback_values)
            == "VO00S280001"
        )
        assert (
            applications._allocate_locked_fallback(session, fallback_values)
            == "VO00S280002"
        )
        session.execute(
            update(EOS_PROJECT_CODE_COUNTER_TABLE)
            .where(
                EOS_PROJECT_CODE_COUNTER_TABLE.c.tenant_id == TENANT,
                EOS_PROJECT_CODE_COUNTER_TABLE.c.purpose_type == "S",
                EOS_PROJECT_CODE_COUNTER_TABLE.c.code_year == 28,
            )
            .values(last_serial=9999)
        )
        with pytest.raises(EosProjectApplicationError) as fallback_exhausted:
            applications._allocate_locked_fallback(session, fallback_values)
    assert fallback_exhausted.value.error_code == "EOS_PROJECT_CODE_EXHAUSTED"


def test_application_validation_hierarchy_and_corruption_guards(runtime) -> None:
    _engine, factory, projects, applications, _authorization, _service = runtime
    parent_id = str(uuid.uuid4())
    projects.create_project(
        ProjectInput(
            tenant_id=TENANT,
            project_id=parent_id,
            project_code="PARENT-W30",
            name="Parent Project",
            nvt_project_id=NVT_ID,
        )
    )
    child = applications.create_draft(
        replace(
            _draft(str(uuid.uuid4())),
            parent_project_id=parent_id,
            nvt_project_id=None,
            company_id=str(uuid.uuid4()),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
    )
    assert child["payload"]["start_date"] == "2026-01-01"
    assert child["payload"]["company_id"] is not None

    with factory.begin() as session:
        session.execute(
            update(EOS_NVT_PROJECT_TABLE)
            .where(EOS_NVT_PROJECT_TABLE.c.nvt_project_id == NVT_ID)
            .values(status="INACTIVE")
        )
    with pytest.raises(EosProjectApplicationError, match="NVTProject must be ACTIVE"):
        applications.create_draft(_draft(str(uuid.uuid4())))
    with factory.begin() as session:
        session.execute(
            update(EOS_NVT_PROJECT_TABLE)
            .where(EOS_NVT_PROJECT_TABLE.c.nvt_project_id == NVT_ID)
            .values(status="ACTIVE")
        )
        session.execute(
            update(EOS_PROJECT_TABLE)
            .where(EOS_PROJECT_TABLE.c.project_id == parent_id)
            .values(status="INACTIVE")
        )
    with pytest.raises(
        EosProjectApplicationError, match="Parent Project must be ACTIVE"
    ):
        applications.create_draft(
            replace(
                _draft(str(uuid.uuid4())),
                parent_project_id=parent_id,
                nvt_project_id=None,
            )
        )
    with pytest.raises(EosProjectApplicationError) as absent_parent:
        applications.create_draft(
            replace(
                _draft(str(uuid.uuid4())),
                parent_project_id=str(uuid.uuid4()),
                nvt_project_id=None,
            )
        )
    assert absent_parent.value.error_code == "EOS_PROJECT_PARENT_NOT_FOUND"

    invalid_values = [
        replace(_draft(str(uuid.uuid4())), application_id="not-a-uuid"),
        replace(_draft(str(uuid.uuid4())), name=""),
        replace(_draft(str(uuid.uuid4())), currency="KRWW"),
        replace(_draft(str(uuid.uuid4())), company_id="not-a-uuid"),
        replace(_draft(str(uuid.uuid4())), start_date=datetime.now(UTC)),
        replace(
            _draft(str(uuid.uuid4())),
            start_date=date(2026, 2, 1),
            end_date=date(2026, 1, 1),
        ),
    ]
    for value in invalid_values:
        with pytest.raises(EosProjectApplicationError):
            applications.create_draft(value)
    with pytest.raises(EosProjectApplicationError, match="timezone-aware"):
        applications.create_draft(
            _draft(str(uuid.uuid4())),
            issued_at=datetime(2026, 1, 1),  # noqa: DTZ001 - invalid-input case
        )

    corrupt = applications.create_draft(_draft(str(uuid.uuid4())))
    with factory.begin() as session:
        session.execute(
            delete(EOS_PROJECT_APP_REVISION_TABLE).where(
                EOS_PROJECT_APP_REVISION_TABLE.c.application_id
                == corrupt["application_id"]
            )
        )
    with pytest.raises(EosProjectApplicationError) as corruption:
        applications.get_by_request_code(
            tenant_id=TENANT,
            project_request_code=corrupt["project_request_code"],
        )
    assert corruption.value.error_code == "EOS_PROJECT_APPLICATION_CORRUPT"


def test_owner_scope_authorization_and_exact_request_resolver(runtime) -> None:
    _engine, _factory, _projects, applications, authorization, service = runtime
    created = service.create_draft(_draft(), requester_subject_id=APPLICANT)
    assert (
        service.get_application(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            requester_subject_id=APPLICANT,
        )["request_hash"]
        == created["request_hash"]
    )

    with pytest.raises(EosProjectApplicationError) as mismatch:
        service.create_draft(
            replace(_draft(), applicant_subject_id="another-user"),
            requester_subject_id=APPLICANT,
        )
    assert mismatch.value.status_code == 403
    authorization.value = {
        "active": True,
        "tenant_id": TENANT,
        "subject_id": APPLICANT,
        "scopes": ["project:application:read"],
        "revision_hash": "b" * 64,
    }
    with pytest.raises(EosProjectApplicationError) as denied:
        service.submit(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            expected_version=1,
            requester_subject_id=APPLICANT,
        )
    assert denied.value.error_code == "EOS_PROJECT_APPLICATION_AUTHORIZATION_DENIED"
    assert (
        applications.get_by_request_code(
            tenant_id=TENANT, project_request_code="VO00R269999"
        )
        is None
    )


def test_authorization_failure_and_cross_owner_read_matrix(runtime) -> None:
    _engine, _factory, _projects, applications, authorization, service = runtime
    created = applications.create_draft(_draft())
    with pytest.raises(EosProjectApplicationError) as owner_denied:
        applications.revise_draft(
            replace(_draft(), name="Denied"),
            expected_version=1,
            actor_subject_id="employee-2000",
        )
    assert owner_denied.value.error_code == "EOS_PROJECT_APPLICATION_OWNER_DENIED"
    with pytest.raises(EosProjectApplicationError) as version_conflict:
        applications.revise_draft(
            replace(_draft(), name="Wrong version"),
            expected_version=2,
            actor_subject_id=APPLICANT,
        )
    assert (
        version_conflict.value.error_code == "EOS_PROJECT_APPLICATION_VERSION_CONFLICT"
    )

    other = "employee-2000"
    authorization.value = {
        "active": True,
        "tenant_id": TENANT,
        "subject_id": other,
        "scopes": ["project:application:read"],
    }
    with pytest.raises(EosProjectApplicationError) as read_denied:
        service.get_application(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            requester_subject_id=other,
        )
    assert read_denied.value.error_code == "EOS_PROJECT_APPLICATION_READ_DENIED"
    authorization.value["scopes"].append("project:application:admin")
    assert (
        service.get_application(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            requester_subject_id=other,
        )["application_id"]
        == APPLICATION_ID
    )

    authorization.value = AuthorizationSubjectDenied("inactive")
    with pytest.raises(EosProjectApplicationError) as inactive:
        service.get_application(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            requester_subject_id=other,
        )
    assert inactive.value.status_code == 403
    authorization.value = RuntimeError("OA unavailable")
    with pytest.raises(EosProjectApplicationError) as unavailable:
        service.get_application(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            requester_subject_id=other,
        )
    assert unavailable.value.retryable is True
    authorization.value = "malformed"
    with pytest.raises(EosProjectApplicationError) as malformed:
        service.get_application(
            tenant_id=TENANT,
            project_request_code=created["project_request_code"],
            requester_subject_id=other,
        )
    assert malformed.value.status_code == 503

    authorization.value = {
        "active": False,
        "tenant_id": TENANT,
        "subject_id": other,
        "scopes": ["project:application:read"],
    }
    with pytest.raises(EosProjectApplicationError) as denied:
        service.get_application(
            tenant_id=TENANT,
            project_request_code="VO00R269999",
            requester_subject_id=other,
        )
    assert denied.value.status_code == 403


def test_project_code_resolver_and_lifecycle_matrix(runtime) -> None:
    _engine, _factory, projects, _applications, _authorization, service = runtime
    projects.create_project(
        ProjectInput(
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            project_code="LEGACY-W30",
            name="Legacy Project",
            nvt_project_id=NVT_ID,
        )
    )
    resolved = service.resolve_project(
        tenant_id=TENANT,
        project_code="LEGACY-W30",
        requester_subject_id=APPLICANT,
    )
    assert resolved["project_code"] == "LEGACY-W30"
    assert "project_id" not in resolved
    assert (
        projects.get_project_by_code(
            tenant_id=TENANT, project_code="LEGACY-W30", active_only=True
        )
        is not None
    )

    transitions = [
        ("CLOSING", 1),
        ("ACTIVE", 2),
        ("INACTIVE", 3),
        ("ACTIVE", 4),
        ("CLOSING", 5),
        ("CLOSED", 6),
    ]
    for target, version in transitions:
        changed = projects.transition_project_status(
            tenant_id=TENANT,
            project_code="LEGACY-W30",
            target_status=target,
            expected_version=version,
        )
        assert changed["status"] == target
        assert changed["version"] == version + 1
    with pytest.raises(EosProjectError) as terminal:
        projects.transition_project_status(
            tenant_id=TENANT,
            project_code="LEGACY-W30",
            target_status="ACTIVE",
            expected_version=7,
        )
    assert terminal.value.error_code == "EOS_PROJECT_TRANSITION_DENIED"

    with pytest.raises(EosProjectError, match="approved Project registration code"):
        projects.create_project(
            ProjectInput(
                tenant_id=TENANT,
                project_id=str(uuid.uuid4()),
                project_code="VO00D26X001",
                project_request_code="VO00R260001",
                purpose_type="D",
                origin="APPROVED_APPLICATION",
                approval_evidence_ref="approval://wc/case-1",
                approval_evidence_hash=f"sha256:{'a' * 64}",
                name="Malformed approved Project",
                nvt_project_id=NVT_ID,
            )
        )


def test_internal_application_api_signed_trust_and_validation(runtime) -> None:
    _engine, _factory, _projects, _applications, _authorization, service = runtime
    app = create_eos_app(environ={})
    app.state.eos_project_application_service = service
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Subject-Id": APPLICANT,
    }
    payload = {
        "application_id": APPLICATION_ID,
        "purpose_type": "D",
        "name": "API Project",
        "nvt_project_id": NVT_ID,
        "currency": "KRW",
    }
    assert (
        client.post(
            "/internal/v2/project-applications",
            json=payload,
            headers={
                "X-NeX-Tenant-Id": TENANT,
                "X-NeX-Subject-Id": APPLICANT,
            },
        ).status_code
        == 401
    )
    created = client.post(
        "/internal/v2/project-applications", json=payload, headers=headers
    )
    assert created.status_code == 201
    code = created.json()["project_request_code"]
    assert (
        client.get(
            f"/internal/v2/project-applications/{code}", headers=headers
        ).status_code
        == 200
    )
    malformed = client.post(
        f"/internal/v2/project-applications/{code}:submit",
        json={"expected_version": 0},
        headers=headers,
    )
    assert malformed.status_code == 422
    submitted = client.post(
        f"/internal/v2/project-applications/{code}:submit",
        json={"expected_version": 1},
        headers=headers,
    )
    assert submitted.status_code == 200
    assert submitted.json()["state"] == "SUBMITTED"


def test_internal_application_api_revision_resolver_and_failure_paths(runtime) -> None:
    _engine, _factory, projects, _applications, _authorization, service = runtime
    projects.create_project(
        ProjectInput(
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            project_code="API-RESOLVE",
            name="Resolvable Project",
            nvt_project_id=NVT_ID,
        )
    )
    app = create_eos_app(environ={})
    app.state.eos_project_application_service = service
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Subject-Id": APPLICANT,
    }
    created = client.post(
        "/internal/v2/project-applications",
        headers=headers,
        json={
            "application_id": APPLICATION_ID,
            "purpose_type": "D",
            "name": "API revision",
            "nvt_project_id": NVT_ID,
            "start_date": "2026-01-01",
        },
    )
    assert created.status_code == 201
    code = created.json()["project_request_code"]
    revised = client.patch(
        f"/internal/v2/project-applications/{code}",
        headers=headers,
        json={
            "expected_version": 1,
            "purpose_type": "M",
            "name": "API revised",
            "nvt_project_id": NVT_ID,
            "end_date": "2026-12-31",
        },
    )
    assert revised.status_code == 200
    assert revised.json()["current_revision"] == 2
    resolved = client.get(
        "/internal/v2/projects:resolve",
        params={"project_code": "API-RESOLVE", "active_only": True},
        headers=headers,
    )
    assert resolved.status_code == 200
    assert "project_id" not in resolved.json()
    assert (
        client.get(
            "/internal/v2/projects:resolve",
            params={"project_code": "MISSING"},
            headers=headers,
        ).status_code
        == 404
    )
    invalid_date = client.post(
        "/internal/v2/project-applications",
        headers=headers,
        json={
            "application_id": str(uuid.uuid4()),
            "purpose_type": "D",
            "name": "Invalid date",
            "nvt_project_id": NVT_ID,
            "start_date": 20260101,
        },
    )
    assert invalid_date.status_code == 422

    app.state.eos_project_application_service = None
    assert (
        client.get(
            f"/internal/v2/project-applications/{code}", headers=headers
        ).status_code
        == 503
    )


def test_migration_contract_and_operation_registry() -> None:
    from nex_runtime import DEFAULT_OPERATION_REGISTRY

    migration = "database/nex-eos/migrations/2531_eos_project_application_lifecycle.sql"
    sql_text = Path(migration).read_text(encoding="utf-8")
    assert "eos_project_application" in sql_text
    assert "eos_project_app_revision" in sql_text
    assert "eos_project_code_counter" in sql_text
    assert "trg_eos_project_app_revision_immutable" in sql_text
    assert "trg_eos_project_business_identity" in sql_text
    assert "CLOSING" in sql_text and "CLOSED" in sql_text
    for operation in (
        "PROJECT.APPLICATION.CREATE",
        "PROJECT.APPLICATION.REVISE",
        "PROJECT.APPLICATION.SUBMIT",
        "PROJECT.APPLICATION.GET",
        "PROJECT.PROJECT.RESOLVE",
    ):
        assert (
            DEFAULT_OPERATION_REGISTRY.resolve(operation).canonical_operation
            == operation
        )


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W30-S00A EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_migration_concurrent_codes_and_zero_residue() -> None:
    schema_name = f"mybee_w30s00a_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    try:
        result = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2531_eos_project_application_lifecycle" in result.applied
        db = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        projects = SqlAlchemyEosProjectRepository(db.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT, NVT_ID, "NVT-W30-PG", "W30 PG Portfolio")
        )

        def create(index: int) -> str:
            repository = SqlAlchemyEosProjectApplicationRepository(db.session_factory)
            return repository.create_draft(
                _draft(
                    str(uuid.uuid4()),
                    name=f"Concurrent Project {index}",
                ),
                issued_at=datetime(2026, 6, 1, tzinfo=UTC),
            )["project_request_code"]

        with ThreadPoolExecutor(max_workers=8) as executor:
            codes = list(executor.map(create, range(32)))
        assert len(set(codes)) == 32
        assert min(codes) == "VO00R260001"
        assert max(codes) == "VO00R260032"

        repository = SqlAlchemyEosProjectApplicationRepository(db.session_factory)
        sample = repository.get_by_request_code(
            tenant_id=TENANT, project_request_code=codes[0]
        )
        assert sample is not None
        assert sample["payload"]["name"].startswith("Concurrent Project")
        with db.session_factory.begin() as session:
            row = (
                session.execute(
                    select(EOS_PROJECT_CODE_COUNTER_TABLE).where(
                        EOS_PROJECT_CODE_COUNTER_TABLE.c.tenant_id == TENANT,
                        EOS_PROJECT_CODE_COUNTER_TABLE.c.code_kind == "REQUEST",
                        EOS_PROJECT_CODE_COUNTER_TABLE.c.code_year == 26,
                    )
                )
                .mappings()
                .one()
            )
        assert row["last_serial"] == 32
        db.engine.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            cursor.execute(
                "SELECT to_regnamespace(%s)",
                (schema_name,),
            )
            assert cursor.fetchone() == (None,)
