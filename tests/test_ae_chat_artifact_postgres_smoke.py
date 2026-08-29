from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import run_ae_chat_artifact_postgres_smoke as smoke
from run_migrations import MigrationError


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0408@127.0.0.1:5432/nex_ae_test"
        ),
    }


def good_observations() -> dict[str, Any]:
    return {
        "tables_present": sorted(smoke.EXPECTED_TABLES),
        "migration_recorded": True,
        "row_counts": {"interactions": 1, "artifact_refs": 1},
        "jsonb_columns": smoke.EXPECTED_JSONB_TYPES,
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
        "owner_scope": {
            "tenant_id": "tenant-chat-artifact-smoke-fixed",
            "user_id": "user-chat-artifact-smoke-fixed",
        },
    }


def sqlite_chat_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_chat_interactions (
                    chat_interaction_id TEXT PRIMARY KEY,
                    interaction_schema_version TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    user_message_hash TEXT NOT NULL,
                    user_message_preview TEXT NOT NULL,
                    cx_retrieval_package_id TEXT,
                    cx_retrieval_package_hash TEXT,
                    cx_generation_id TEXT,
                    cx_generation_status TEXT,
                    retrieval_summary TEXT NOT NULL,
                    generation_summary TEXT NOT NULL,
                    failure_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_chat_artifact_refs (
                    chat_artifact_ref_id TEXT PRIMARY KEY,
                    chat_interaction_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    artifact_version_id TEXT NOT NULL,
                    display_title TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    artifact_status TEXT NOT NULL,
                    primary_format TEXT NOT NULL,
                    available_formats TEXT NOT NULL,
                    preview_route TEXT,
                    download_routes TEXT NOT NULL,
                    source_generation_id TEXT NOT NULL,
                    source_content_hash TEXT NOT NULL,
                    quality_summary TEXT NOT NULL,
                    actions TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (chat_interaction_id, artifact_id, artifact_version_id)
                )
                """
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class FakeResult:
    def __init__(
        self,
        *,
        scalar_value: Any = None,
        mapping_value: dict[str, Any] | None = None,
        scalar_values: list[str] | None = None,
        rowcount: int = 1,
    ) -> None:
        self._scalar_value = scalar_value
        self._mapping_value = mapping_value
        self._scalar_values = scalar_values or []
        self.rowcount = rowcount

    def scalar(self) -> Any:
        return self._scalar_value

    def mappings(self) -> FakeResult:
        return self

    def first(self) -> dict[str, Any] | None:
        return self._mapping_value

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[str]:
        return self._scalar_values


class FakeConnection:
    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, statement: Any, params: dict[str, str] | None = None) -> FakeResult:
        query = str(statement).lower()
        if "to_regclass" in query:
            table_name = query.split("public.", 1)[1].split("'", 1)[0]
            return FakeResult(
                scalar_value=table_name if table_name in smoke.EXPECTED_TABLES else None
            )
        if "schema_migrations" in query:
            return FakeResult(scalar_value=True)
        if "count(*)" in query and "from ae_chat_artifact_refs" in query:
            return FakeResult(scalar_value=1)
        if "count(*)" in query and "from ae_chat_interactions" in query:
            return FakeResult(scalar_value=1)
        if "pg_typeof" in query:
            return FakeResult(mapping_value=smoke.EXPECTED_JSONB_TYPES)
        if "pg_indexes" in query:
            return FakeResult(scalar_values=sorted(smoke.EXPECTED_INDEXES))
        if "select tenant_id, user_id" in query:
            return FakeResult(
                mapping_value={
                    "tenant_id": "tenant-chat-artifact-smoke-fixed",
                    "user_id": "user-chat-artifact-smoke-fixed",
                }
            )
        if "delete from ae_chat_artifact_refs" in query:
            return FakeResult(rowcount=1)
        if "delete from ae_chat_interactions" in query:
            return FakeResult(rowcount=1)
        return FakeResult()


class FakeEngine:
    def connect(self) -> FakeConnection:
        return FakeConnection()

    def begin(self) -> FakeConnection:
        return FakeConnection()

    def dispose(self) -> None:
        return None


class BrokenBeginEngine(FakeEngine):
    def begin(self) -> FakeConnection:
        raise SQLAlchemyError("cleanup failed")


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload


def test_ae_chat_artifact_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_chat_artifact_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        f"ae_chat_artifact_postgres_smoke=skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_chat_artifact_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_chat_artifact_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_ae_chat_artifact_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_chat_artifact_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_chat_artifact_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_chat_artifact_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0408" not in evidence["detail"]


def test_ae_chat_artifact_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_chat_artifact_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("route failed")),
    )

    evidence = smoke.run_ae_chat_artifact_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert smoke.summary_line(evidence) == (
        "ae_chat_artifact_postgres_smoke=fail "
        "service=nex-ae-api reason=execution_failed"
    )


def test_ae_chat_artifact_postgres_smoke_passes_route_flow_with_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_chat_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=(smoke.MIGRATION_VERSION,),
            applied=(),
            skipped=(smoke.MIGRATION_VERSION,),
        ),
    )

    def observations(engine: Any, *, interaction_id: str) -> dict[str, Any]:
        result = good_observations()
        with engine.connect() as connection:
            tenant_id = connection.execute(
                text(
                    """
                    SELECT tenant_id FROM ae_chat_interactions
                    WHERE chat_interaction_id = :interaction_id
                    """
                ),
                {"interaction_id": interaction_id},
            ).scalar()
        suffix = tenant_id.replace("tenant-chat-artifact-smoke-", "")
        result["owner_scope"] = {
            "tenant_id": tenant_id,
            "user_id": f"user-chat-artifact-smoke-{suffix}",
        }
        return result

    monkeypatch.setattr(smoke, "_db_observations", observations)

    evidence = smoke.run_ae_chat_artifact_postgres_smoke(smoke_env())
    serialized = json.dumps(evidence, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["checks"]["artifact_link_idempotent"] is True
    assert evidence["checks"]["cleanup_deleted"] is True
    assert evidence["cleanup"] == {"interactions": 1, "artifact_refs": 1}
    assert evidence["cx_client_call_count"] == 1
    assert "secret-0408" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ae_chat_artifact_postgres_smoke=pass"
    )


def test_ae_chat_artifact_postgres_smoke_execute_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_chat_session_factory().kw["bind"]
    bad = good_observations()
    bad["row_counts"] = {"interactions": 1, "artifact_refs": 0}
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: bad)

    with pytest.raises(RuntimeError, match="row_counts"):
        smoke._execute_chat_artifact_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_chat_artifact_postgres_smoke_execute_route_failure_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def set_common_route_fakes() -> None:
        monkeypatch.setattr(smoke, "build_engine", lambda _database_url: FakeEngine())
        monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
        monkeypatch.setattr(
            smoke,
            "build_service_app",
            lambda _spec: SimpleNamespace(state=SimpleNamespace()),
        )
        monkeypatch.setattr(smoke, "register_chat_routes", lambda *args, **kwargs: None)

    set_common_route_fakes()

    class CreateFailsClient:
        def __init__(self, app: Any) -> None:
            self.app = app

        def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse(500)

    monkeypatch.setattr(smoke, "TestClient", CreateFailsClient)
    with pytest.raises(RuntimeError, match="interaction create"):
        smoke._execute_chat_artifact_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    class AttachFailsClient:
        def __init__(self, app: Any) -> None:
            self.app = app
            self.post_count = 0

        def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            self.post_count += 1
            if self.post_count == 1:
                return FakeResponse(200, {"interaction_id": "interaction"})
            return FakeResponse(500)

    monkeypatch.setattr(smoke, "TestClient", AttachFailsClient)
    with pytest.raises(RuntimeError, match="artifact link attach"):
        smoke._execute_chat_artifact_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_chat_artifact_postgres_smoke_execute_wraps_sqlalchemy_and_value_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: FakeEngine())
    monkeypatch.setattr(
        smoke,
        "build_session_factory",
        lambda _engine: (_ for _ in ()).throw(ValueError("bad session factory")),
    )

    with pytest.raises(RuntimeError, match="bad session factory"):
        smoke._execute_chat_artifact_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_chat_artifact_postgres_smoke_db_observations_shape() -> None:
    observations = smoke._db_observations(
        FakeEngine(),
        interaction_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
    )

    assert observations == good_observations()
    assert smoke._scalar_count(
        FakeConnection(),
        "SELECT count(*) FROM ae_chat_artifact_refs WHERE chat_interaction_id = :id",
        {"id": "interaction"},
    ) == 1


def test_ae_chat_artifact_postgres_smoke_cleanup_handles_empty_and_errors() -> None:
    assert smoke._cleanup_chat_rows(
        FakeEngine(),
        interaction_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
    ) == {"interactions": 1, "artifact_refs": 1}
    assert smoke._cleanup_chat_rows(FakeEngine(), interaction_id=None) == {
        "interactions": 0,
        "artifact_refs": 0,
    }
    assert smoke._cleanup_chat_rows(
        BrokenBeginEngine(),
        interaction_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
    ) == {"interactions": 0, "artifact_refs": 0}


def test_ae_chat_artifact_postgres_smoke_redaction_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()

    assert "secret-0408" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="database URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=nuri1004", {})
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/private", {})
    assert smoke._redaction_safe({"ok": True}, forbidden_fragments=["secret"])

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_chat_artifact_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_chat_artifact_postgres_smoke=skipped" in capsys.readouterr().out
