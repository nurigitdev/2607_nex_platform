from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import run_ae_artifact_postgres_smoke as smoke
from run_migrations import MigrationError


def good_observations() -> dict[str, Any]:
    return {
        "tables_present": sorted(smoke.EXPECTED_TABLES),
        "migration_recorded": True,
        "row_counts": {
            "handoffs": 1,
            "artifacts": 1,
            "source_refs": 1,
            "versions": 1,
            "render_jobs": 1,
            "files": 1,
            "links": 2,
        },
        "jsonb_columns": smoke.EXPECTED_JSONB_TYPES,
        "handoff_correlation_columns": list(
            smoke.EXPECTED_HANDOFF_CORRELATION_COLUMNS
        ),
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
        "storage_ref": "ae://artifacts/artifact/version/file.md",
    }


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0406@127.0.0.1:5432/nex_ae_test"
        ),
    }


def sqlite_artifact_session_factory():
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
                CREATE TABLE ae_artifact_handoffs (
                    artifact_handoff_id TEXT PRIMARY KEY,
                    handoff_schema_version TEXT NOT NULL,
                    artifact_request_id TEXT NOT NULL UNIQUE,
                    handoff_status TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    cx_generation_id TEXT NOT NULL,
                    structured_draft_id TEXT NOT NULL,
                    draft_schema_version TEXT NOT NULL,
                    structured_draft_content_hash TEXT NOT NULL,
                    citation_claims_hash TEXT NOT NULL,
                    validation_result_hash TEXT NOT NULL,
                    template_id TEXT,
                    template_version TEXT,
                    rendering_template_id TEXT,
                    artifact_intent TEXT NOT NULL,
                    target_formats TEXT NOT NULL,
                    artifact_title TEXT NOT NULL,
                    language TEXT NOT NULL,
                    retention_policy_ref TEXT NOT NULL,
                    actor_claims_ref TEXT NOT NULL,
                    workspace_ref TEXT NOT NULL,
                    quality_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    artifact_schema_version TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    artifact_status TEXT NOT NULL,
                    current_version_id TEXT,
                    artifact_handoff_id TEXT NOT NULL,
                    artifact_request_id TEXT NOT NULL UNIQUE,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    display_title TEXT NOT NULL,
                    language TEXT NOT NULL,
                    artifact_intent TEXT NOT NULL,
                    target_formats TEXT NOT NULL,
                    retention_policy_ref TEXT NOT NULL,
                    owner_actor_ref TEXT NOT NULL,
                    workspace_ref TEXT NOT NULL,
                    template_ref TEXT NOT NULL,
                    handoff_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_source_refs (
                    source_ref_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    cx_generation_id TEXT NOT NULL,
                    structured_draft_id TEXT NOT NULL,
                    draft_schema_version TEXT NOT NULL,
                    structured_draft_content_hash TEXT NOT NULL,
                    citation_claims_hash TEXT NOT NULL,
                    validation_result_hash TEXT NOT NULL,
                    retrieval_package_id TEXT,
                    retrieval_package_hash TEXT,
                    evidence_ref_count INTEGER NOT NULL,
                    source_anchor_count INTEGER NOT NULL,
                    quality_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_versions (
                    artifact_version_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    version_reason TEXT NOT NULL,
                    source_generation_id TEXT NOT NULL,
                    source_structured_draft_id TEXT NOT NULL,
                    source_content_hash TEXT NOT NULL,
                    source_citation_claims_hash TEXT NOT NULL,
                    render_policy_hash TEXT NOT NULL,
                    artifact_content_hash TEXT NOT NULL,
                    rendered_formats TEXT NOT NULL,
                    validation_snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_render_jobs (
                    render_job_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    artifact_version_id TEXT,
                    job_status TEXT NOT NULL,
                    current_stage TEXT NOT NULL,
                    progress_mode TEXT NOT NULL,
                    progress_percent INTEGER NOT NULL,
                    retryable INTEGER NOT NULL,
                    failure_code TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_files (
                    artifact_file_id TEXT PRIMARY KEY,
                    artifact_version_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    format TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    storage_ref TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    file_hash TEXT NOT NULL,
                    source_version_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_artifact_links (
                    artifact_link_id TEXT PRIMARY KEY,
                    artifact_file_id TEXT NOT NULL,
                    link_type TEXT NOT NULL,
                    access_policy TEXT NOT NULL,
                    link_route TEXT NOT NULL,
                    expires_at TEXT,
                    created_by_actor_ref TEXT NOT NULL,
                    download_count INTEGER NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL
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
        scalar_one_value: Any = None,
        mapping_value: dict[str, Any] | None = None,
        scalar_values: list[str] | None = None,
        rowcount: int = 1,
    ) -> None:
        self._scalar_value = scalar_value
        self._scalar_one_value = scalar_one_value
        self._mapping_value = mapping_value
        self._scalar_values = scalar_values or []
        self.rowcount = rowcount

    def scalar(self) -> Any:
        return self._scalar_value

    def scalar_one(self) -> Any:
        return self._scalar_one_value

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
        if "pg_typeof" in query:
            return FakeResult(mapping_value=smoke.EXPECTED_JSONB_TYPES)
        if "information_schema.columns" in query:
            return FakeResult(
                scalar_values=list(smoke.EXPECTED_HANDOFF_CORRELATION_COLUMNS)
            )
        if "pg_indexes" in query:
            return FakeResult(scalar_values=sorted(smoke.EXPECTED_INDEXES))
        if "select storage_ref" in query:
            return FakeResult(
                scalar_one_value="ae://artifacts/artifact/version/file.md"
            )
        if "count(*)" in query:
            count = 2 if "from ae_artifact_links" in query else 1
            return FakeResult(scalar_value=count)
        if "delete from ae_artifacts" in query:
            return FakeResult(rowcount=1)
        if "delete from ae_artifact_handoffs" in query:
            return FakeResult(rowcount=1)
        return FakeResult()


class FakeEngine:
    def connect(self) -> FakeConnection:
        return FakeConnection()

    def begin(self) -> FakeConnection:
        return FakeConnection()


class BrokenBeginEngine(FakeEngine):
    def begin(self) -> FakeConnection:
        raise SQLAlchemyError("cleanup failed")


def test_ae_artifact_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        f"ae_artifact_postgres_smoke=skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_artifact_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_artifact_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0406" not in evidence["detail"]


def test_ae_artifact_postgres_smoke_passes_route_flow_with_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: good_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=(smoke.MIGRATION_VERSION,),
            applied=(),
            skipped=(smoke.MIGRATION_VERSION,),
        ),
    )

    evidence = smoke.run_ae_artifact_postgres_smoke(smoke_env())
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["checks"]["local_payload_written"] is True
    assert evidence["checks"]["row_counts"] is True
    assert evidence["cleanup"] == {"artifacts": 1, "handoffs": 1}
    assert smoke.summary_line(evidence).startswith(
        "ae_artifact_postgres_smoke=pass service=nex-ae-api"
    )
    assert "secret-0406" not in serialized
    assert "/data/nex-platform" not in serialized


def test_ae_artifact_postgres_smoke_execute_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    bad = good_observations()
    bad["row_counts"] = {**bad["row_counts"], "links": 1}
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: bad)

    with pytest.raises(RuntimeError, match="row_counts"):
        smoke._execute_ae_artifact_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_postgres_smoke_db_observations_read_expected_shape() -> None:
    observations = smoke._db_observations(
        FakeEngine(),
        artifact_handoff_id="handoff-001",
        artifact_id="artifact-001",
        artifact_version_id="version-001",
        render_job_id="render-job-001",
        artifact_file_id="file-001",
    )

    assert observations == good_observations()
    assert smoke._scalar_count(
        FakeConnection(),
        "SELECT count(*) FROM ae_artifact_files WHERE artifact_file_id = :id",
        {"id": "file-001"},
    ) == 1


def test_ae_artifact_postgres_smoke_cleanup_handles_ids_empty_and_errors() -> None:
    assert smoke._cleanup_smoke_rows(
        FakeEngine(),
        artifact_id="artifact-001",
        artifact_handoff_id="handoff-001",
    ) == {"artifacts": 1, "handoffs": 1}
    assert smoke._cleanup_smoke_rows(
        FakeEngine(),
        artifact_id=None,
        artifact_handoff_id=None,
    ) == {"artifacts": 0, "handoffs": 0}
    assert smoke._cleanup_smoke_rows(
        BrokenBeginEngine(),
        artifact_id="artifact-001",
        artifact_handoff_id="handoff-001",
    ) == {"artifacts": 0, "handoffs": 0}


def test_ae_artifact_postgres_smoke_temporary_env_restores_previous_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_AE_ARTIFACT_STORAGE_ROOT", "before")

    with smoke._temporary_env("NEX_AE_ARTIFACT_STORAGE_ROOT", "during"):
        assert smoke.os.environ["NEX_AE_ARTIFACT_STORAGE_ROOT"] == "during"

    assert smoke.os.environ["NEX_AE_ARTIFACT_STORAGE_ROOT"] == "before"


def test_ae_artifact_postgres_smoke_redaction_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert "secret-0406" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=nuri1004", {})
    assert smoke._redaction_safe({"ok": True}, forbidden_fragments=["secret"])

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_artifact_postgres_smoke=skipped" in capsys.readouterr().out
