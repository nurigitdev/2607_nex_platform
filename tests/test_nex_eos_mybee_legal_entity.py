from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_LEGAL_ENTITY_TABLE,
    EOS_METADATA,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EosLegalEntityError,
    EosLegalEntityService,
    LegalEntityInput,
    NvtProjectInput,
    ProjectCompanyBindingInput,
    ProjectInput,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
    create_eos_app,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, func, make_url, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT_ID = "tenant-a"
OTHER_TENANT_ID = "tenant-b"
COMPANY_A = "a1000000-0000-4000-8000-000000000001"
COMPANY_B = "a1000000-0000-4000-8000-000000000002"
NVT_ID = "a2000000-0000-4000-8000-000000000001"
PROJECT_ID = "a3000000-0000-4000-8000-000000000001"
BINDING_A = "a4000000-0000-4000-8000-000000000001"
BINDING_B = "a4000000-0000-4000-8000-000000000002"
PROOF_HASH = "sha256:" + "a" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S1_01_POSTGRES_SMOKE") == "1"
OPENAPI_PATH = "contracts/openapi/nex-eos.openapi.yaml"


class AuthorizationSource:
    def __init__(self) -> None:
        self.denied = False
        self.unavailable = False
        self.scopes = {
            "finance:company:read",
            "project:company-binding:read",
            "project:company-binding:manage",
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
            "revision_hash": "b" * 64,
        }


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    legal_entities = SqlAlchemyEosLegalEntityRepository(factory)
    projects = SqlAlchemyEosProjectRepository(factory)
    projects.create_nvt_project(
        NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S101", "NVT S1-01")
    )
    projects.create_project(
        ProjectInput(
            TENANT_ID,
            PROJECT_ID,
            "PROJECT-S101",
            "Project S1-01",
            nvt_project_id=NVT_ID,
        )
    )
    return engine, factory, legal_entities


def _entity(
    company_id: str = COMPANY_A,
    company_code: str = "NURI-KR",
    *,
    tenant_id: str = TENANT_ID,
    effective_from: date = date(2026, 1, 1),
    status: str = "ACTIVE",
    functional_currency: str = "KRW",
    version: int = 1,
) -> LegalEntityInput:
    return LegalEntityInput(
        tenant_id=tenant_id,
        company_id=company_id,
        company_code=company_code,
        name=f"{company_code} Legal Entity",
        functional_currency=functional_currency,
        presentation_currency="KRW",
        business_timezone="Asia/Seoul",
        effective_from=effective_from,
        status=status,
        version=version,
    )


def _binding(
    binding_id: str = BINDING_A,
    company_id: str = COMPANY_A,
    *,
    tenant_id: str = TENANT_ID,
    project_id: str = PROJECT_ID,
    valid_from: date = date(2026, 1, 1),
    valid_until: date | None = None,
    state: str = "APPROVED",
    version: int = 1,
) -> ProjectCompanyBindingInput:
    return ProjectCompanyBindingInput(
        tenant_id=tenant_id,
        binding_id=binding_id,
        project_id=project_id,
        company_id=company_id,
        valid_from=valid_from,
        valid_until=valid_until,
        approved_proof_hash=PROOF_HASH,
        state=state,
        version=version,
    )


def test_s1_01_migration_declares_tenant_qualified_master_and_range_guards() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2516_eos_legal_entity_project_binding"
    )
    compact = " ".join(migration.sql.lower().split())

    assert "create table if not exists eos_legal_entity" in compact
    assert "primary key (tenant_id, company_id)" in compact
    assert "unique (tenant_id, company_code)" in compact
    assert "create table if not exists eos_project_company_binding" in compact
    assert "foreign key (tenant_id, project_id)" in compact
    assert "foreign key (tenant_id, company_id)" in compact
    assert "valid_until is null or valid_until > valid_from" in compact
    assert "eos_reject_project_company_overlap" in compact
    assert "sha256:[0-9a-f]{64}" in compact


def test_s1_01_openapi_freezes_company_and_binding_contracts() -> None:
    with open(OPENAPI_PATH, encoding="utf-8") as stream:
        spec = yaml.safe_load(stream)

    paths = spec["paths"]
    legal_entity = paths["/internal/v2/finance/legal-entities/{company_id}"]["get"]
    binding_create = paths["/internal/v2/projects/{project_id}/company-bindings"][
        "post"
    ]
    binding_get = paths["/internal/v2/projects/{project_id}/company-binding"]["get"]

    assert legal_entity["operationId"] == "FINANCE.LEGAL_ENTITY.GET"
    assert legal_entity["x-nex-business-scope"] == "finance:company:read"
    assert binding_create["operationId"] == "PROJECT.COMPANY_BINDING.CREATE"
    assert binding_create["x-nex-route-class"] == "WRITE"
    assert binding_get["operationId"] == "PROJECT.COMPANY_BINDING.GET"
    assert binding_get["x-nex-side-effect-free"] is True
    assert set(
        spec["components"]["schemas"]["ProjectCompanyBindingCommand"]["required"]
    ) == {
        "binding_id",
        "company_id",
        "valid_from",
        "approved_proof_hash",
    }


def test_legal_entity_create_get_dedup_and_currency_is_immutable(
    repository,
) -> None:
    _engine, _factory, legal_entities = repository
    created = legal_entities.create_legal_entity(_entity())

    assert created["functional_currency"] == "KRW"
    assert (
        legal_entities.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_A,
            effective_on=date(2026, 1, 1),
            active_only=True,
        )["company_code"]
        == "NURI-KR"
    )
    assert (
        legal_entities.get_legal_entity(
            tenant_id=OTHER_TENANT_ID,
            company_id=COMPANY_A,
        )
        is None
    )
    assert (
        legal_entities.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_A,
            effective_on=date(2025, 12, 31),
        )
        is None
    )

    with pytest.raises(EosLegalEntityError) as duplicate:
        legal_entities.create_legal_entity(_entity(functional_currency="USD"))
    assert duplicate.value.error_code == "EOS_LEGAL_ENTITY_CONFLICT"


def test_adjacent_project_company_bindings_resolve_at_exact_boundary(
    repository,
) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    legal_entities.create_legal_entity(_entity(COMPANY_B, "NURI-US"))

    first = legal_entities.create_project_company_binding(
        _binding(valid_until=date(2026, 7, 1))
    )
    replay = legal_entities.create_project_company_binding(
        _binding(valid_until=date(2026, 7, 1))
    )
    second = legal_entities.create_project_company_binding(
        _binding(
            BINDING_B,
            COMPANY_B,
            valid_from=date(2026, 7, 1),
        )
    )

    assert replay["binding_id"] == first["binding_id"]
    assert second["company_id"] == COMPANY_B
    assert (
        legal_entities.get_effective_project_company_binding(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            effective_on=date(2026, 6, 30),
        )["company_id"]
        == COMPANY_A
    )
    assert (
        legal_entities.get_effective_project_company_binding(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            effective_on=date(2026, 7, 1),
        )["company_id"]
        == COMPANY_B
    )


def test_overlap_identity_drift_and_fake_project_are_rejected(repository) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    legal_entities.create_project_company_binding(
        _binding(valid_until=date(2026, 7, 1))
    )

    with pytest.raises(EosLegalEntityError) as overlap:
        legal_entities.create_project_company_binding(
            _binding(
                BINDING_B,
                valid_from=date(2026, 6, 1),
                valid_until=date(2026, 8, 1),
            )
        )
    assert overlap.value.error_code == "EOS_PROJECT_COMPANY_BINDING_CONFLICT"

    with pytest.raises(EosLegalEntityError) as identity_drift:
        legal_entities.create_project_company_binding(
            _binding(BINDING_A, valid_until=date(2026, 6, 1))
        )
    assert identity_drift.value.error_code == "EOS_PROJECT_COMPANY_BINDING_CONFLICT"

    with pytest.raises(EosLegalEntityError) as fake:
        legal_entities.create_project_company_binding(
            _binding(
                BINDING_B,
                project_id="a3000000-0000-4000-8000-000000000099",
                valid_from=date(2027, 1, 1),
            )
        )
    assert fake.value.error_code == "EOS_PROJECT_NOT_FOUND"


def test_company_must_be_same_tenant_active_and_effective(repository) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity(tenant_id=OTHER_TENANT_ID))
    with pytest.raises(EosLegalEntityError) as cross_tenant:
        legal_entities.create_project_company_binding(_binding())
    assert cross_tenant.value.error_code == "EOS_LEGAL_ENTITY_NOT_FOUND"

    legal_entities.create_legal_entity(
        _entity(
            COMPANY_B,
            "FUTURE",
            effective_from=date(2027, 1, 1),
        )
    )
    with pytest.raises(EosLegalEntityError) as future:
        legal_entities.create_project_company_binding(_binding(BINDING_B, COMPANY_B))
    assert future.value.error_code == "EOS_LEGAL_ENTITY_NOT_EFFECTIVE"

    legal_entities.create_legal_entity(
        _entity(
            "a1000000-0000-4000-8000-000000000003",
            "INACTIVE",
            status="INACTIVE",
        )
    )
    with pytest.raises(EosLegalEntityError) as inactive:
        legal_entities.create_project_company_binding(
            _binding(
                "a4000000-0000-4000-8000-000000000003",
                "a1000000-0000-4000-8000-000000000003",
            )
        )
    assert inactive.value.error_code == "EOS_LEGAL_ENTITY_NOT_EFFECTIVE"


def test_revoked_binding_is_persisted_but_never_effective(repository) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    revoked = legal_entities.create_project_company_binding(_binding(state="REVOKED"))

    assert revoked["state"] == "REVOKED"
    assert (
        legal_entities.get_effective_project_company_binding(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            effective_on=date(2026, 1, 1),
        )
        is None
    )


def test_ambiguous_persisted_binding_fails_closed(repository) -> None:
    _engine, factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.execute(
            EOS_PROJECT_COMPANY_BINDING_TABLE.insert(),
            [
                {
                    "tenant_id": TENANT_ID,
                    "binding_id": BINDING_A,
                    "project_id": PROJECT_ID,
                    "company_id": COMPANY_A,
                    "valid_from": date(2026, 1, 1),
                    "valid_until": None,
                    "approved_proof_hash": PROOF_HASH,
                    "state": "APPROVED",
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "tenant_id": TENANT_ID,
                    "binding_id": BINDING_B,
                    "project_id": PROJECT_ID,
                    "company_id": COMPANY_A,
                    "valid_from": date(2026, 2, 1),
                    "valid_until": None,
                    "approved_proof_hash": PROOF_HASH,
                    "state": "APPROVED",
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )

    with pytest.raises(EosLegalEntityError) as ambiguous:
        legal_entities.get_effective_project_company_binding(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            effective_on=date(2026, 3, 1),
        )
    assert ambiguous.value.error_code == "EOS_PROJECT_COMPANY_BINDING_AMBIGUOUS"


@pytest.mark.parametrize(
    "value",
    (
        _entity(company_id="bad"),
        _entity(company_code="bad code"),
        _entity(tenant_id="bad tenant"),
        LegalEntityInput(
            TENANT_ID,
            COMPANY_A,
            "EMPTY-NAME",
            "",
            "KRW",
            "KRW",
            "Asia/Seoul",
            date(2026, 1, 1),
        ),
        _entity(functional_currency="KR"),
        _entity(version=True),
        _entity(version=2),
        LegalEntityInput(
            TENANT_ID,
            COMPANY_A,
            "BAD-TZ",
            "Bad timezone",
            "KRW",
            "KRW",
            "Not/AZone",
            date(2026, 1, 1),
        ),
    ),
)
def test_legal_entity_validation_fails_closed(repository, value) -> None:
    _engine, _factory, legal_entities = repository
    with pytest.raises(EosLegalEntityError) as invalid:
        legal_entities.create_legal_entity(value)
    assert invalid.value.error_code == "EOS_LEGAL_ENTITY_INVALID"


@pytest.mark.parametrize(
    "value",
    (
        _binding(binding_id="bad"),
        _binding(valid_until=date(2026, 1, 1)),
        ProjectCompanyBindingInput(
            TENANT_ID,
            BINDING_A,
            PROJECT_ID,
            COMPANY_A,
            date(2026, 1, 1),
            "bad-hash",
        ),
        _binding(state="DRAFT"),
        _binding(version=2),
    ),
)
def test_project_company_binding_validation_fails_closed(repository, value) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    with pytest.raises(EosLegalEntityError) as invalid:
        legal_entities.create_project_company_binding(value)
    assert invalid.value.error_code == "EOS_LEGAL_ENTITY_INVALID"


def test_service_enforces_fresh_oa_scopes_and_tenant_isolation(repository) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    source = AuthorizationSource()
    service = EosLegalEntityService(legal_entities, source)

    assert (
        service.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_A,
            requester_subject_id="finance-a",
        )["company_id"]
        == COMPANY_A
    )
    source.scopes.remove("finance:company:read")
    with pytest.raises(EosLegalEntityError) as denied:
        service.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_A,
            requester_subject_id="finance-a",
        )
    assert denied.value.error_code == "EOS_LEGAL_ENTITY_AUTHORIZATION_DENIED"

    source.scopes.add("finance:company:read")
    source.unavailable = True
    with pytest.raises(EosLegalEntityError) as unavailable:
        service.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_A,
            requester_subject_id="finance-a",
        )
    assert unavailable.value.error_code == "EOS_LEGAL_ENTITY_AUTHORIZATION_UNAVAILABLE"
    assert "private OA detail" not in unavailable.value.detail

    source.unavailable = False
    source.denied = True
    with pytest.raises(EosLegalEntityError) as inactive_subject:
        service.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_A,
            requester_subject_id="finance-a",
        )
    assert inactive_subject.value.error_code == "EOS_LEGAL_ENTITY_AUTHORIZATION_DENIED"


@pytest.mark.parametrize(
    ("authorization", "expected_code"),
    (
        (None, "EOS_LEGAL_ENTITY_AUTHORIZATION_UNAVAILABLE"),
        ({"active": False}, "EOS_LEGAL_ENTITY_AUTHORIZATION_DENIED"),
        (
            {
                "active": True,
                "tenant_id": OTHER_TENANT_ID,
                "subject_id": "finance-a",
                "scopes": ["finance:company:read"],
                "revision_hash": "b" * 64,
            },
            "EOS_LEGAL_ENTITY_AUTHORIZATION_DENIED",
        ),
        (
            {
                "active": True,
                "tenant_id": TENANT_ID,
                "subject_id": "finance-a",
                "scopes": "finance:company:read",
                "revision_hash": "b" * 64,
            },
            "EOS_LEGAL_ENTITY_AUTHORIZATION_UNAVAILABLE",
        ),
        (
            {
                "active": True,
                "tenant_id": TENANT_ID,
                "subject_id": "finance-a",
                "scopes": [""],
                "revision_hash": "b" * 64,
            },
            "EOS_LEGAL_ENTITY_AUTHORIZATION_UNAVAILABLE",
        ),
        (
            {
                "active": True,
                "tenant_id": TENANT_ID,
                "subject_id": "finance-a",
                "scopes": ["finance:company:read"],
                "revision_hash": "bad",
            },
            "EOS_LEGAL_ENTITY_AUTHORIZATION_UNAVAILABLE",
        ),
    ),
)
def test_service_rejects_malformed_or_drifted_oa_authorization(
    repository, authorization, expected_code
) -> None:
    class RawAuthorizationSource:
        def effective_authorization(self, **_kwargs):
            return authorization

    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    service = EosLegalEntityService(legal_entities, RawAuthorizationSource())

    with pytest.raises(EosLegalEntityError) as rejected:
        service.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_A,
            requester_subject_id="finance-a",
        )
    assert rejected.value.error_code == expected_code


def test_service_binding_command_query_and_missing_paths(repository) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    service = EosLegalEntityService(legal_entities, AuthorizationSource())

    created = service.bind_project(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        requester_subject_id="finance-a",
        payload={
            "binding_id": BINDING_A,
            "company_id": COMPANY_A,
            "valid_from": "2026-01-01",
            "approved_proof_hash": PROOF_HASH,
        },
    )
    assert created["valid_from"] == "2026-01-01"
    assert (
        service.get_project_company_binding(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="finance-a",
            effective_on=date(2026, 1, 1),
        )["binding_id"]
        == BINDING_A
    )

    with pytest.raises(EosLegalEntityError) as missing:
        service.get_project_company_binding(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="finance-a",
            effective_on=date(2025, 12, 31),
        )
    assert missing.value.error_code == "EOS_PROJECT_COMPANY_BINDING_NOT_FOUND"

    with pytest.raises(EosLegalEntityError) as missing_company:
        service.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_B,
            requester_subject_id="finance-a",
        )
    assert missing_company.value.error_code == "EOS_LEGAL_ENTITY_NOT_FOUND"


@pytest.mark.parametrize("valid_from", ("not-a-date", 100))
def test_service_rejects_malformed_binding_dates(repository, valid_from) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    service = EosLegalEntityService(legal_entities, AuthorizationSource())

    with pytest.raises(EosLegalEntityError) as invalid:
        service.bind_project(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="finance-a",
            payload={
                "binding_id": BINDING_A,
                "company_id": COMPANY_A,
                "valid_from": valid_from,
                "approved_proof_hash": PROOF_HASH,
            },
        )
    assert invalid.value.error_code == "EOS_LEGAL_ENTITY_INVALID"


def test_service_accepts_date_objects_and_finite_binding(repository) -> None:
    _engine, _factory, legal_entities = repository
    legal_entities.create_legal_entity(_entity())
    service = EosLegalEntityService(legal_entities, AuthorizationSource())

    created = service.bind_project(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        requester_subject_id="finance-a",
        payload={
            "binding_id": BINDING_A,
            "company_id": COMPANY_A,
            "valid_from": date(2026, 1, 1),
            "valid_until": date(2026, 12, 31),
            "approved_proof_hash": PROOF_HASH,
        },
    )
    assert created["valid_until"] == "2026-12-31"


def test_repository_errors_are_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private database detail")

    repository = SqlAlchemyEosLegalEntityRepository(
        lambda: BrokenSession()  # type: ignore[arg-type]
    )
    with pytest.raises(EosLegalEntityError) as failed:
        repository.get_legal_entity(
            tenant_id=TENANT_ID,
            company_id=COMPANY_A,
        )
    assert failed.value.error_code == "EOS_LEGAL_ENTITY_PERSISTENCE_FAILED"
    assert "private database detail" not in failed.value.detail


class FakeLegalEntityService:
    def get_legal_entity(self, **kwargs):
        return {"company_id": kwargs["company_id"]}

    def bind_project(self, **kwargs):
        return {"project_id": kwargs["project_id"], **kwargs["payload"]}

    def get_project_company_binding(self, **kwargs):
        return {"project_id": kwargs["project_id"], "effective_on": "2026-01-01"}


def test_v2_routes_require_service_trust_and_expose_only_scoped_operations() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-01",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_legal_entity_service = FakeLegalEntityService()
    client = TestClient(app)
    company_path = f"/internal/v2/finance/legal-entities/{COMPANY_A}"
    headers = {
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": "finance-a",
    }
    assert client.get(company_path, headers=headers).status_code == 401

    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers["Authorization"] = f"Bearer {token.access_token}"
    assert client.get(company_path, headers=headers).status_code == 200
    bind_path = f"/internal/v2/projects/{PROJECT_ID}/company-bindings"
    assert (
        client.post(
            bind_path,
            headers=headers,
            json={
                "binding_id": BINDING_A,
                "company_id": COMPANY_A,
                "valid_from": "2026-01-01",
                "approved_proof_hash": PROOF_HASH,
            },
        ).status_code
        == 201
    )
    assert (
        client.get(
            f"/internal/v2/projects/{PROJECT_ID}/company-binding",
            headers=headers,
            params={"effective_on": "2026-01-01"},
        ).status_code
        == 200
    )

    app.state.eos_legal_entity_service = None
    assert client.get(company_path, headers=headers).status_code == 503


def test_v2_route_maps_domain_error_without_leaking_private_detail() -> None:
    class FailingService(FakeLegalEntityService):
        def get_legal_entity(self, **_kwargs):
            raise EosLegalEntityError(
                "EOS_LEGAL_ENTITY_NOT_FOUND",
                "LegalEntity was not found",
                status_code=404,
            )

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-01",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_legal_entity_service = FailingService()
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    response = TestClient(app).get(
        f"/internal/v2/finance/legal-entities/{COMPANY_A}",
        headers={
            "Authorization": f"Bearer {token.access_token}",
            "X-NeX-Tenant-Id": TENANT_ID,
            "X-NeX-Subject-Id": "finance-a",
        },
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "EOS_LEGAL_ENTITY_NOT_FOUND"


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S1-01 EOS PostgreSQL smoke is disabled",
)
def test_s1_01_actual_postgres_migration_fk_overlap_and_zero_residue() -> None:
    schema_name = f"mybee_s101_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))

    scoped_url = make_url(DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    )
    scoped_url = scoped_url.render_as_string(hide_password=False)
    try:
        result = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2516_eos_legal_entity_project_binding" in result.applied
        runtime = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        projects = SqlAlchemyEosProjectRepository(runtime.session_factory)
        legal_entities = SqlAlchemyEosLegalEntityRepository(runtime.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S101-PG", "NVT S1-01 PG")
        )
        projects.create_project(
            ProjectInput(
                TENANT_ID,
                PROJECT_ID,
                "PROJECT-S101-PG",
                "Project S1-01 PG",
                nvt_project_id=NVT_ID,
            )
        )
        legal_entities.create_legal_entity(_entity())
        legal_entities.create_project_company_binding(
            _binding(valid_until=date(2026, 7, 1))
        )
        with pytest.raises(EosLegalEntityError) as overlap:
            legal_entities.create_project_company_binding(
                _binding(
                    BINDING_B,
                    valid_from=date(2026, 6, 1),
                )
            )
        assert overlap.value.error_code == "EOS_PROJECT_COMPANY_BINDING_CONFLICT"
        with runtime.engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count()).select_from(EOS_LEGAL_ENTITY_TABLE)
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    select(func.count()).select_from(EOS_PROJECT_COMPANY_BINDING_TABLE)
                ).scalar_one()
                == 1
            )
        runtime.dispose()
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

    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.schemata WHERE schema_name = %s",
            (schema_name,),
        )
        assert cursor.fetchone() == (0,)
