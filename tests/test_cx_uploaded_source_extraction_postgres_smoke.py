from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import run_cx_uploaded_source_extraction_postgres_smoke as smoke
from nex_runtime import build_engine
from run_migrations import MigrationError


def _sqlite_cx_repository_url(tmp_path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cx-uploaded-source-extraction.db'}"
    engine = build_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_source_files (
                    source_file_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    first_seen_trace_id TEXT,
                    storage_backend TEXT NOT NULL DEFAULT 'local_filesystem',
                    storage_key TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    stored_extension TEXT NOT NULL,
                    checksum_verified_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (storage_backend, storage_key)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_objects (
                    content_object_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    tenant_ref_type TEXT NOT NULL DEFAULT 'oa.tenant',
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    owner_subject_ref_id TEXT NOT NULL,
                    uploaded_by_subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    uploaded_by_subject_ref_id TEXT NOT NULL,
                    source_file_id TEXT NOT NULL REFERENCES cx_source_files(source_file_id),
                    source_sha256 TEXT NOT NULL,
                    upload_id TEXT NOT NULL UNIQUE,
                    original_filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    classification TEXT NOT NULL DEFAULT 'internal',
                    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
                    retrieval_policy TEXT NOT NULL DEFAULT '{}',
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX ux_cx_content_owner_source_active
                ON cx_content_objects (tenant_id, owner_user_id, source_sha256)
                WHERE lifecycle_status = 'ACTIVE'
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX ux_cx_content_owner_subject_source_active
                ON cx_content_objects (
                    tenant_ref_type,
                    tenant_ref_id,
                    owner_subject_ref_type,
                    owner_subject_ref_id,
                    source_sha256
                )
                WHERE lifecycle_status = 'ACTIVE'
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_acl_entries (
                    acl_entry_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    principal_type TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    principal_ref_type TEXT NOT NULL,
                    principal_ref_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    granted_by_user_id TEXT,
                    granted_by_subject_ref_type TEXT,
                    granted_by_subject_ref_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (content_object_id, principal_type, principal_id, permission)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX ux_cx_content_acl_subject_ref_permission
                ON cx_content_acl_entries (
                    content_object_id,
                    principal_ref_type,
                    principal_ref_id,
                    permission
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_extraction_artifacts (
                    extraction_artifact_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    source_file_id TEXT NOT NULL REFERENCES cx_source_files(source_file_id),
                    artifact_kind TEXT NOT NULL DEFAULT 'markdown',
                    status TEXT NOT NULL DEFAULT 'SUCCEEDED',
                    extractor_name TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    markdown_sha256 TEXT NOT NULL,
                    markdown_storage_uri TEXT NOT NULL,
                    markdown_char_count INTEGER NOT NULL,
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (content_object_id, extractor_name, extractor_version, markdown_sha256)
                )
                """
            )
        )
    return database_url


def test_uploaded_source_extraction_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_cx_uploaded_source_extraction_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert smoke.summary_line(evidence).startswith(
        "cx_uploaded_source_extraction_postgres_smoke=skipped"
    )


def test_uploaded_source_extraction_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_cx_uploaded_source_extraction_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SMOKE_PROFILE_ENV: "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert "reason=profile_not_allowed" in smoke.summary_line(evidence)


def test_uploaded_source_extraction_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise MigrationError("boom")

    monkeypatch.setattr(smoke, "run_service_migrations", raise_migration_error)

    evidence = smoke.run_cx_uploaded_source_extraction_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": (
                "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
            ),
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert evidence["detail"] == "boom"


def test_uploaded_source_extraction_postgres_smoke_high_level_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = SimpleNamespace(
        service_id="nex-cx",
        profile="test",
        planned=("001", "002", "003"),
        applied=(),
        skipped=("001", "002", "003"),
        dry_run=False,
    )
    execution = {
        "document_id": "doc-1",
        "source_file_id": "src-1",
        "extraction": {
            "status": "SUCCEEDED",
            "source_reader": "materialized_local_source_file",
            "fallback_used": True,
            "markdown_char_count": 12,
        },
        "db_observations": {
            "source_checksum_verified": True,
            "extraction_artifact_count": 1,
        },
        "checks": {"all_good": True},
    }
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: migration,
    )

    def fake_execute(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return execution

    monkeypatch.setattr(smoke, "_execute_uploaded_source_extraction_smoke", fake_execute)

    evidence = smoke.run_cx_uploaded_source_extraction_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": (
                "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
            ),
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["redacted_database_url"].endswith("@127.0.0.1/nex_cx_test")
    assert evidence["migration"]["skipped_count"] == 3
    assert seen["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert seen["runtime_environ"]["NEX_CX_PERSISTENCE_MODE"] == "postgres"
    assert smoke.summary_line(evidence).endswith(
        "source_reader=materialized_local_source_file artifact_count=1"
    )


def test_uploaded_source_extraction_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = SimpleNamespace(
        service_id="nex-cx",
        profile="test",
        planned=("001",),
        applied=(),
        skipped=("001",),
        dry_run=False,
    )

    monkeypatch.setattr(smoke, "run_service_migrations", lambda *args, **kwargs: migration)

    def raise_runtime_error(**kwargs: object) -> dict[str, object]:
        raise RuntimeError("unavailable")

    monkeypatch.setattr(
        smoke,
        "_execute_uploaded_source_extraction_smoke",
        raise_runtime_error,
    )

    evidence = smoke.run_cx_uploaded_source_extraction_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": (
                "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
            ),
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert evidence["detail"] == "RuntimeError"


def test_uploaded_source_extraction_postgres_smoke_requires_session_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_cx_repository_url(tmp_path)
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(mode="postgres", api_session_factory=None),
    )

    with pytest.raises(RuntimeError, match="session factory is unavailable"):
        smoke._execute_uploaded_source_extraction_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_TEST_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )


def test_uploaded_source_extraction_postgres_smoke_sqlite_route_path(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_cx_repository_url(tmp_path)

    result = smoke._execute_uploaded_source_extraction_smoke(
        database_env="NEX_CX_TEST_DATABASE_URL",
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_TEST_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )

    assert all(result["checks"].values())
    assert result["extraction"]["status"] == "SUCCEEDED"
    assert result["extraction"]["source_reader"] == "materialized_local_source_file"
    assert result["extraction"]["fallback_used"] is True
    assert result["extraction"]["markdown_char_count"] > len(smoke.SECRET_SOURCE_TEXT)
    assert result["db_observations"] == {
        "source_checksum_verified": True,
        "extraction_artifact_count": 1,
    }
    assert result["cleanup_observations"]["before"] == {
        "extraction_artifact_rows": 1,
        "content_object_rows": 1,
        "source_file_rows": 1,
    }
    assert result["cleanup_observations"]["after"] == {
        "extraction_artifact_rows": 0,
        "content_object_rows": 0,
        "source_file_rows": 0,
    }
    smoke.assert_evidence_redacted(result)
    assert smoke.SECRET_SOURCE_TEXT not in json.dumps(result, ensure_ascii=False)


def test_uploaded_source_extraction_postgres_smoke_check_failure_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_cx_repository_url(tmp_path)
    monkeypatch.setattr(smoke, "_redaction_safe", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="smoke checks failed"):
        smoke._execute_uploaded_source_extraction_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_TEST_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    engine = build_engine(database_url)
    assert smoke._cleanup_counts(
        engine,
        document_id=None,
        source_file_id=None,
    ) == {
        "extraction_artifact_rows": 0,
        "content_object_rows": 0,
        "source_file_rows": 0,
    }


def test_uploaded_source_extraction_postgres_smoke_observation_helpers_missing_rows(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_cx_repository_url(tmp_path)
    engine = build_engine(database_url)

    assert smoke._read_source_file_observation(engine, source_file_id=None) == {
        "checksum_verified": False,
        "storage_backend": None,
    }
    assert smoke._read_source_file_observation(engine, source_file_id="missing") == {
        "checksum_verified": False,
        "storage_backend": None,
    }
    assert smoke._read_extraction_artifact_observation(
        engine,
        document_id=None,
        source_file_id="src",
        markdown_sha256="sha",
    ) == {"artifact_count": 0, "markdown_sha256_matches": False}
    assert smoke._cleanup_counts(
        engine,
        document_id=None,
        source_file_id=None,
    ) == {
        "extraction_artifact_rows": 0,
        "content_object_rows": 0,
        "source_file_rows": 0,
    }
    assert smoke._delete_uploaded_source_extraction_rows(
        engine,
        document_id=None,
        source_file_id="missing-source",
    ) == {
        "before": {
            "extraction_artifact_rows": 0,
            "content_object_rows": 0,
            "source_file_rows": 0,
        },
        "after": {
            "extraction_artifact_rows": 0,
            "content_object_rows": 0,
            "source_file_rows": 0,
        },
    }
    assert smoke._delete_uploaded_source_extraction_rows(
        engine,
        document_id="missing-document",
        source_file_id=None,
    ) == {
        "before": {
            "extraction_artifact_rows": 0,
            "content_object_rows": 0,
            "source_file_rows": 0,
        },
        "after": {
            "extraction_artifact_rows": 0,
            "content_object_rows": 0,
            "source_file_rows": 0,
        },
    }


def test_uploaded_source_extraction_postgres_smoke_redaction_guard() -> None:
    smoke.assert_evidence_redacted({"safe": "ok"})

    for forbidden in [
        smoke.SECRET_SOURCE_TEXT,
        "source_storage_path",
        "nex-cx-uploaded-source-extraction-smoke-",
        "/data/nex-platform",
    ]:
        with pytest.raises(ValueError, match="not redacted"):
            smoke.assert_evidence_redacted({"leak": forbidden})


def test_uploaded_source_extraction_postgres_smoke_main_writes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    output_path = tmp_path / "nested" / "evidence.json"

    monkeypatch.setattr(
        smoke,
        "run_cx_uploaded_source_extraction_postgres_smoke",
        lambda: evidence,
    )

    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == evidence
    assert "cx_uploaded_source_extraction_postgres_smoke=skipped" in capsys.readouterr().out


def test_uploaded_source_extraction_postgres_smoke_main_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = smoke._failure("execution_failed", "RuntimeError", profile="test")

    monkeypatch.setattr(
        smoke,
        "run_cx_uploaded_source_extraction_postgres_smoke",
        lambda: evidence,
    )

    assert smoke.main([]) == 1
    assert '"failure_code": "execution_failed"' in capsys.readouterr().out
