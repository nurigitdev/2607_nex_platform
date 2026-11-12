from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
import yaml
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from nex_oa import project_entitlements
from nex_oa.authorization import OaAuthorizationError
from nex_oa.project_entitlements import (
    OA_PROJECT_DECISION_SCOPE,
    InMemoryOaProjectGrantRepository,
    OaProjectAuthorizationDecisionService,
    SqlAlchemyOaProjectGrantRepository,
    build_project_grant_repository_for_runtime,
    register_project_entitlement_routes,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    psycopg_database_url,
)
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
TENANT = "VO00"
SUBJECT = "employee-2003"
PROJECT_CODE = "VO00D260001"
PROJECT_ID = "c3000000-0000-4000-8000-000000000001"
EVENT_ID = "c3000000-0000-4000-8000-000000000002"
EVENT_HASH = "sha256:" + "b" * 64
DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_OA_MYBEE_W40_CA01_S03_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self, scopes=None) -> None:
        self.scopes = (
            ["finance:voucher-candidate:create"] if scopes is None else scopes
        )

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        return {
            "response_schema_version": "oa_authz_read_response.v1",
            "service_id": "nex-oa",
            "authorization": {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "scopes": list(self.scopes),
                "revision_hash": "c" * 64,
            },
        }


def _grant(**overrides):
    value = {
        "tenant_id": TENANT,
        "project_code": PROJECT_CODE,
        "subject_id": SUBJECT,
        "project_role": "MEMBER",
        "grant_status": "ACTIVE",
        "project_status": "ACTIVE",
        "source_project_id": PROJECT_ID,
        "source_version": 1,
        "source_event_id": EVENT_ID,
        "source_event_hash": EVENT_HASH,
        "occurred_at": NOW,
    }
    value.update(overrides)
    return value


def _decision(**overrides):
    value = {
        "tenant_id": TENANT,
        "subject_id": SUBJECT,
        "project_code": PROJECT_CODE,
        "action": "finance:voucher-candidate:create",
        "correlation_id": "w40-ca01-s03",
        "minimum_source_version": 1,
    }
    value.update(overrides)
    return value


def _sqlite_repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE oa_project_grant ("
                "tenant_id TEXT, project_code TEXT, subject_id TEXT, "
                "project_role TEXT, grant_status TEXT, project_status TEXT, "
                "source_project_id TEXT, source_version INTEGER, "
                "source_event_id TEXT, source_event_hash TEXT, "
                "granted_at TEXT, revoked_at TEXT, updated_at TEXT, "
                "PRIMARY KEY (tenant_id, project_code, subject_id), "
                "UNIQUE (tenant_id, source_event_id))"
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory, SqlAlchemyOaProjectGrantRepository(factory)


def test_in_memory_grant_is_idempotent_versioned_and_tenant_isolated() -> None:
    repository = InMemoryOaProjectGrantRepository()
    created = repository.apply_grant(_grant())
    replay = repository.apply_grant(_grant())
    assert created["created"] is True
    assert replay["replayed"] is True

    updated = repository.apply_grant(
        _grant(
            project_role="VIEWER",
            source_version=2,
            source_event_id="c3000000-0000-4000-8000-000000000003",
            source_event_hash="sha256:" + "d" * 64,
        )
    )
    assert updated["record"]["project_role"] == "VIEWER"
    assert updated["record"]["granted_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert repository.get_grant(
        tenant_id=TENANT, project_code=PROJECT_CODE, subject_id=SUBJECT
    )["source_version"] == 2
    assert repository.get_grant(
        tenant_id="VO01", project_code="VO01D260001", subject_id=SUBJECT
    ) is None

    with pytest.raises(OaAuthorizationError, match="stale"):
        repository.apply_grant(
            _grant(
                source_event_id="c3000000-0000-4000-8000-000000000004",
                source_event_hash="sha256:" + "e" * 64,
            )
        )


def test_grant_replay_and_event_collision_fail_closed() -> None:
    repository = InMemoryOaProjectGrantRepository()
    repository.apply_grant(_grant())
    with pytest.raises(OaAuthorizationError, match="immutable semantics"):
        repository.apply_grant(_grant(project_role="OWNER"))
    with pytest.raises(OaAuthorizationError, match="another grant"):
        repository.apply_grant(
            _grant(project_code="VO00D260002", subject_id="employee-2004")
        )


@pytest.mark.parametrize(
    "payload",
    (
        {},
        _grant(tenant_id="bad tenant"),
        _grant(project_role="UNKNOWN"),
        _grant(source_project_id="not-a-uuid"),
        _grant(source_event_hash="not-a-hash"),
        _grant(source_version=True),
        _grant(source_version=[]),
        _grant(source_version=0),
        _grant(occurred_at="not-a-timestamp"),
        _grant(occurred_at=NOW.replace(tzinfo=None)),
    ),
)
def test_grant_payload_validation_rejects_malformed_fields(payload) -> None:
    with pytest.raises(OaAuthorizationError) as error:
        InMemoryOaProjectGrantRepository().apply_grant(payload)
    assert error.value.status_code == 400


@pytest.mark.parametrize(
    ("grant_overrides", "decision_overrides", "scopes", "reason"),
    (
        ({}, {}, [], "GLOBAL_SCOPE_MISSING"),
        ({"project_role": "VIEWER"}, {}, None, "PROJECT_ROLE_INSUFFICIENT"),
        ({"grant_status": "REVOKED"}, {}, None, "PROJECT_GRANT_REVOKED"),
        ({"project_status": "INACTIVE"}, {}, None, "PROJECT_INACTIVE"),
        ({"project_status": "CLOSED"}, {}, None, "PROJECT_CLOSED"),
        ({"project_status": "CLOSING"}, {}, None, "PROJECT_CLOSING_ACTION_DENIED"),
        ({}, {"minimum_source_version": 2}, None, "PROJECT_PROJECTION_STALE"),
        ({}, {"action": "unknown:action"}, None, "ACTION_UNKNOWN"),
    ),
)
def test_project_decision_denial_matrix(
    grant_overrides, decision_overrides, scopes, reason
) -> None:
    repository = InMemoryOaProjectGrantRepository()
    repository.apply_grant(_grant(**grant_overrides))
    service = OaProjectAuthorizationDecisionService(
        repository,
        AuthorizationSource(scopes),
        clock=lambda: NOW,
    )
    result = service.decide(_decision(**decision_overrides))
    assert result["allowed"] is False
    assert result["reason_code"] == reason


def test_project_decision_allows_exact_active_grant_and_closing_read() -> None:
    repository = InMemoryOaProjectGrantRepository()
    repository.apply_grant(_grant())
    service = OaProjectAuthorizationDecisionService(
        repository, AuthorizationSource(), clock=lambda: NOW
    )
    allowed = service.decide(_decision())
    assert allowed["allowed"] is True
    assert allowed["project_role"] == "MEMBER"
    assert allowed["applicable_global_scopes"] == [
        "finance:voucher-candidate:create"
    ]
    assert allowed["decision_ref"].startswith("sha256:")

    closing_repository = InMemoryOaProjectGrantRepository()
    closing_repository.apply_grant(_grant(project_status="CLOSING"))
    closing = OaProjectAuthorizationDecisionService(
        closing_repository,
        AuthorizationSource(["finance:report:read"]),
        clock=lambda: NOW,
    ).decide(_decision(action="finance:report:read"))
    assert closing["allowed"] is True


def test_missing_grant_denies_and_malformed_authorization_is_unavailable() -> None:
    repository = InMemoryOaProjectGrantRepository()
    service = OaProjectAuthorizationDecisionService(
        repository, AuthorizationSource(), clock=lambda: NOW
    )
    assert service.decide(_decision())["reason_code"] == "PROJECT_GRANT_NOT_FOUND"

    class MalformedAuthorization:
        def effective_authorization(self, **_kwargs):
            return {"authorization": {"tenant_id": TENANT, "subject_id": SUBJECT}}

    malformed = OaProjectAuthorizationDecisionService(
        repository, MalformedAuthorization(), clock=lambda: NOW
    )
    with pytest.raises(OaAuthorizationError) as error:
        malformed.decide(_decision())
    assert error.value.status_code == 503

    class NonMappingAuthorization:
        def effective_authorization(self, **_kwargs):
            return {"authorization": []}

    non_mapping = OaProjectAuthorizationDecisionService(
        repository, NonMappingAuthorization(), clock=lambda: NOW
    )
    with pytest.raises(OaAuthorizationError) as non_mapping_error:
        non_mapping.decide(_decision())
    assert non_mapping_error.value.status_code == 503


@pytest.mark.parametrize(
    "payload",
    (
        {},
        _decision(project_code="bad"),
        _decision(action="bad"),
        _decision(minimum_source_version=0),
        {**_decision(), "unexpected": True},
    ),
)
def test_project_decision_request_validation(payload) -> None:
    service = OaProjectAuthorizationDecisionService(
        InMemoryOaProjectGrantRepository(), AuthorizationSource(), clock=lambda: NOW
    )
    with pytest.raises(OaAuthorizationError) as error:
        service.decide(payload)
    assert error.value.status_code == 400


def test_sqlalchemy_grant_round_trip_restart_update_and_rollback(monkeypatch) -> None:
    engine, factory, repository = _sqlite_repository()
    repository.apply_grant(_grant())
    restarted = SqlAlchemyOaProjectGrantRepository(factory)
    assert restarted.get_grant(
        tenant_id=TENANT, project_code=PROJECT_CODE, subject_id=SUBJECT
    )["project_role"] == "MEMBER"
    updated = restarted.apply_grant(
        _grant(
            grant_status="REVOKED",
            source_version=2,
            source_event_id="c3000000-0000-4000-8000-000000000005",
            source_event_hash="sha256:" + "5" * 64,
        )
    )
    assert updated["record"]["revoked_at"] is not None

    monkeypatch.setattr(
        repository,
        "_session_factory",
        lambda: (_ for _ in ()).throw(SQLAlchemyError("offline")),
    )
    with pytest.raises(OaAuthorizationError) as unavailable:
        repository.get_grant(
            tenant_id=TENANT, project_code=PROJECT_CODE, subject_id=SUBJECT
        )
    assert unavailable.value.status_code == 503
    engine.dispose()


def test_sqlalchemy_grant_replay_event_collision_and_write_failures() -> None:
    engine, _factory, repository = _sqlite_repository()
    repository.apply_grant(_grant())
    replay = repository.apply_grant(_grant())
    assert replay["replayed"] is True

    with pytest.raises(OaAuthorizationError, match="another grant"):
        repository.apply_grant(
            _grant(project_code="VO00D260002", subject_id="employee-2004")
        )

    class FailingFactory:
        def __init__(self, error):
            self.error = error

        def begin(self):
            raise self.error

    repository._session_factory = FailingFactory(  # type: ignore[assignment]
        IntegrityError("insert", {}, RuntimeError("duplicate"))
    )
    with pytest.raises(OaAuthorizationError) as conflict:
        repository.apply_grant(_grant(source_event_id=str(uuid.uuid4())))
    assert conflict.value.status_code == 409

    repository._session_factory = FailingFactory(  # type: ignore[assignment]
        SQLAlchemyError("offline")
    )
    with pytest.raises(OaAuthorizationError) as unavailable:
        repository.apply_grant(_grant(source_event_id=str(uuid.uuid4())))
    assert unavailable.value.status_code == 503
    engine.dispose()


def test_sql_helpers_fail_closed_on_concurrent_update_and_lock_rows() -> None:
    record = project_entitlements._admit_grant(_grant())
    with pytest.raises(OaAuthorizationError, match="disappeared"):
        project_entitlements._update_grant(object(), record, expected=None)

    class Result:
        rowcount = 0

        def mappings(self):
            return self

        def one_or_none(self):
            return None

    class PostgresSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def __init__(self):
            self.statements = []

        def execute(self, statement, _params):
            self.statements.append(str(statement))
            return Result()

    session = PostgresSession()
    with pytest.raises(OaAuthorizationError, match="changed concurrently"):
        project_entitlements._update_grant(session, record, expected=record)
    assert project_entitlements._select_grant(
        session,
        {
            "tenant_id": TENANT,
            "project_code": PROJECT_CODE,
            "subject_id": SUBJECT,
        },
        for_update=True,
    ) is None
    assert session.statements[-1].endswith("FOR UPDATE")


def test_runtime_builder_selects_persistent_or_memory_repository() -> None:
    _engine_value, factory, _repository = _sqlite_repository()
    persistent = build_project_grant_repository_for_runtime(
        SimpleNamespace(
            mode=PERSISTENCE_MODE_POSTGRES,
            api_session_factory=factory,
        )
    )
    memory = build_project_grant_repository_for_runtime(
        SimpleNamespace(mode="memory", api_session_factory=None)
    )
    assert isinstance(persistent, SqlAlchemyOaProjectGrantRepository)
    assert isinstance(memory, InMemoryOaProjectGrantRepository)


def _headers(*scopes: str):
    token = issue_mock_service_token(
        service_id="nex-eos",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "w40-ca01-s03",
        "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
    }


def test_signed_project_decision_api_is_no_store_and_scope_protected() -> None:
    repository = InMemoryOaProjectGrantRepository()
    repository.apply_grant(_grant())
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_project_entitlement_routes(
        app,
        service=OaProjectAuthorizationDecisionService(
            repository, AuthorizationSource(), clock=lambda: NOW
        ),
    )
    client = TestClient(app)
    path = "/internal/v1/auth/project-decisions"
    assert client.post(path, json=_decision()).status_code == 401
    assert client.post(
        path, json=_decision(), headers=_headers("authorization:admin")
    ).status_code == 403
    response = client.post(
        path, json=_decision(), headers=_headers(OA_PROJECT_DECISION_SCOPE)
    )
    assert response.status_code == 200
    assert response.json()["decision"]["allowed"] is True
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert client.post(
        path,
        json=_decision(project_code="bad"),
        headers=_headers(OA_PROJECT_DECISION_SCOPE),
    ).status_code == 400


def test_project_decision_api_uses_configured_service_token_admission(
    monkeypatch,
) -> None:
    repository = InMemoryOaProjectGrantRepository()
    repository.apply_grant(_grant())
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    app.state.service_token_admission = object()
    register_project_entitlement_routes(
        app,
        service=OaProjectAuthorizationDecisionService(
            repository, AuthorizationSource(), clock=lambda: NOW
        ),
    )
    client = TestClient(app)
    path = "/internal/v1/auth/project-decisions"
    monkeypatch.setattr(
        project_entitlements,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: JSONResponse(
            status_code=401, content={"error_code": "SERVICE_CLAIM_INVALID"}
        ),
    )
    assert client.post(path, json=_decision()).status_code == 401

    monkeypatch.setattr(
        project_entitlements,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: object(),
    )
    assert client.post(path, json=_decision()).status_code == 200


def test_project_decision_schema_openapi_and_migration_contract() -> None:
    contract_root = Path("contracts")
    schema = json.loads(
        (
            contract_root
            / "schemas/service/nex_oa/project_authorization_decision_response.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    example = json.loads(
        (
            contract_root
            / "examples/auth/oa_project_authorization_decision.allow.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(example)
    openapi = yaml.safe_load(
        (contract_root / "openapi/nex-oa.openapi.yaml").read_text(encoding="utf-8")
    )
    operation = openapi["paths"]["/internal/v1/auth/project-decisions"]["post"]
    assert operation["x-nex-required-scopes"] == [
        "service:call",
        "authorization:read",
    ]
    migration = Path(
        "database/nex-oa/migrations/2518_oa_project_grant.sql"
    ).read_text(encoding="utf-8")
    assert "PRIMARY KEY (tenant_id, project_code, subject_id)" in migration
    assert "2518_oa_project_grant" in migration


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W40-CA01-S03 OA PostgreSQL smoke is disabled",
)
def test_actual_postgres_project_grant_restart_decision_and_zero_residue() -> None:
    schema_name = f"mybee_w40ca01s03_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_oa_test", "nex_oa_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    try:
        migrated = run_service_migrations(
            "nex-oa", database_url=scoped_url, profile="test"
        )
        assert "2518_oa_project_grant" in migrated.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO oa_tenants "
                    "(tenant_id, display_name) VALUES (:tenant_id, :display_name)"
                ),
                {"tenant_id": TENANT, "display_name": "W40 Tenant"},
            )
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        SqlAlchemyOaProjectGrantRepository(factory).apply_grant(_grant())
        restarted = SqlAlchemyOaProjectGrantRepository(factory)
        decision = OaProjectAuthorizationDecisionService(
            restarted, AuthorizationSource(), clock=lambda: NOW
        ).decide(_decision())
        assert decision["allowed"] is True
        with factory() as session:
            assert session.execute(
                text("SELECT count(*) FROM oa_project_grant")
            ).scalar_one() == 1
        engine.dispose()
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
            cursor.execute("SELECT to_regnamespace(%s)", (schema_name,))
            assert cursor.fetchone() == (None,)
