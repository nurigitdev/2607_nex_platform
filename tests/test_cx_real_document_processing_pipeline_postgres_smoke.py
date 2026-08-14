from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import run_cx_real_document_processing_pipeline_postgres_smoke as smoke
from nex_runtime import build_engine
from run_migrations import MigrationError
from test_cx_uploaded_source_extraction_postgres_smoke import (
    _sqlite_cx_repository_url,
)


def _sqlite_cx_processing_pipeline_url(tmp_path: Path) -> str:
    database_url = _sqlite_cx_repository_url(tmp_path)
    engine = build_engine(database_url)
    with engine.begin() as connection:
        for statement in _sqlite_pipeline_schema_statements():
            connection.execute(text(statement))
    return database_url


def _sqlite_pipeline_schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE cx_chunk_sets (
            chunk_set_id TEXT PRIMARY KEY,
            content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
            extraction_artifact_id TEXT NOT NULL REFERENCES cx_extraction_artifacts(extraction_artifact_id),
            chunk_policy_id TEXT NOT NULL,
            chunk_size INTEGER NOT NULL,
            chunk_overlap INTEGER NOT NULL,
            source_markdown_sha256 TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            created_trace_id TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (
                content_object_id,
                extraction_artifact_id,
                chunk_policy_id,
                source_markdown_sha256
            )
        )
        """,
        """
        CREATE TABLE cx_chunks (
            chunk_id TEXT PRIMARY KEY,
            chunk_set_id TEXT NOT NULL REFERENCES cx_chunk_sets(chunk_set_id),
            content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
            ordinal INTEGER NOT NULL,
            start_offset INTEGER NOT NULL,
            end_offset INTEGER NOT NULL,
            char_count INTEGER NOT NULL,
            text_sha256 TEXT NOT NULL,
            text_preview TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (chunk_set_id, ordinal),
            UNIQUE (chunk_set_id, text_sha256)
        )
        """,
        """
        CREATE TABLE cx_lexical_terms (
            lexical_term_id TEXT PRIMARY KEY,
            chunk_set_id TEXT NOT NULL REFERENCES cx_chunk_sets(chunk_set_id),
            tokenizer_requested TEXT NOT NULL,
            tokenizer_used TEXT NOT NULL,
            tokenizer_fallback TEXT NOT NULL,
            fallback_used BOOLEAN NOT NULL DEFAULT 0,
            term TEXT NOT NULL,
            document_frequency INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (chunk_set_id, tokenizer_used, term)
        )
        """,
        """
        CREATE TABLE cx_lexical_postings (
            lexical_posting_id TEXT PRIMARY KEY,
            lexical_term_id TEXT NOT NULL REFERENCES cx_lexical_terms(lexical_term_id),
            chunk_id TEXT NOT NULL REFERENCES cx_chunks(chunk_id),
            occurrence_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (lexical_term_id, chunk_id)
        )
        """,
        """
        CREATE TABLE cx_chunk_embeddings (
            chunk_embedding_id TEXT PRIMARY KEY,
            chunk_id TEXT NOT NULL REFERENCES cx_chunks(chunk_id),
            provider_alias TEXT NOT NULL,
            model_profile_id TEXT NOT NULL,
            model_revision TEXT NOT NULL,
            deployment_id TEXT NOT NULL,
            vector_dimension INTEGER NOT NULL,
            embedding_sha256 TEXT NOT NULL,
            embedding_storage_uri TEXT,
            status TEXT NOT NULL DEFAULT 'READY',
            created_trace_id TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (chunk_id, model_profile_id, model_revision)
        )
        """,
        """
        CREATE TABLE cx_document_summaries (
            document_summary_id TEXT PRIMARY KEY,
            content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
            extraction_artifact_id TEXT NOT NULL REFERENCES cx_extraction_artifacts(extraction_artifact_id),
            prompt_template_version_id TEXT,
            summary_chunk_policy_id TEXT NOT NULL DEFAULT 'summary_1000_0',
            summary_text_sha256 TEXT NOT NULL,
            summary_storage_uri TEXT NOT NULL,
            summary_char_count INTEGER NOT NULL,
            summary_max_chars INTEGER NOT NULL DEFAULT 900,
            summary_hard_limit_chars INTEGER NOT NULL DEFAULT 1000,
            status TEXT NOT NULL DEFAULT 'READY',
            language_code TEXT,
            model_profile_id TEXT,
            model_revision TEXT,
            created_trace_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (content_object_id, extraction_artifact_id, summary_text_sha256)
        )
        """,
        """
        CREATE TABLE cx_document_summary_embeddings (
            summary_embedding_id TEXT PRIMARY KEY,
            document_summary_id TEXT NOT NULL REFERENCES cx_document_summaries(document_summary_id),
            provider_alias TEXT NOT NULL,
            model_profile_id TEXT NOT NULL,
            model_revision TEXT NOT NULL,
            deployment_id TEXT NOT NULL,
            vector_dimension INTEGER NOT NULL,
            embedding_sha256 TEXT NOT NULL,
            embedding_storage_uri TEXT,
            status TEXT NOT NULL DEFAULT 'READY',
            created_trace_id TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (document_summary_id, model_profile_id, model_revision)
        )
        """,
        """
        CREATE TABLE cx_document_processing_runs (
            pipeline_run_id TEXT PRIMARY KEY,
            pipeline_schema_version TEXT NOT NULL DEFAULT 'cx_document_processing_pipeline.v1',
            document_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
            status TEXT NOT NULL,
            trace_id TEXT,
            request_id TEXT NOT NULL,
            job_id TEXT,
            job_type TEXT,
            job_status TEXT,
            job_attempt_count INTEGER NOT NULL DEFAULT 0,
            job_max_attempts INTEGER NOT NULL DEFAULT 0,
            job_retryable BOOLEAN,
            job_subject_ref TEXT NOT NULL DEFAULT '{}',
            job_links TEXT NOT NULL DEFAULT '{}',
            step_total INTEGER NOT NULL DEFAULT 0,
            step_succeeded INTEGER NOT NULL DEFAULT 0,
            step_skipped INTEGER NOT NULL DEFAULT 0,
            step_failed INTEGER NOT NULL DEFAULT 0,
            queued_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE cx_document_processing_steps (
            pipeline_run_id TEXT NOT NULL REFERENCES cx_document_processing_runs(pipeline_run_id),
            step_order INTEGER NOT NULL,
            step_id TEXT NOT NULL,
            status TEXT NOT NULL,
            output_ref_type TEXT,
            output_ref_id TEXT,
            output_ref_document_id TEXT REFERENCES cx_content_objects(content_object_id),
            output_ref_hash TEXT,
            error_code TEXT,
            error_detail_sha256 TEXT,
            error_retryable BOOLEAN,
            created_at TEXT NOT NULL,
            PRIMARY KEY (pipeline_run_id, step_order),
            UNIQUE (pipeline_run_id, step_id)
        )
        """,
        """
        CREATE TABLE service_jobs (
            job_id TEXT PRIMARY KEY,
            job_schema_version TEXT NOT NULL DEFAULT 'common_job.v1',
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            retryable INTEGER NOT NULL DEFAULT 1,
            links TEXT NOT NULL DEFAULT '{}',
            payload TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            replay_lineage TEXT,
            available_at TEXT NOT NULL,
            locked_at TEXT,
            locked_by TEXT,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (job_type, idempotency_key)
        )
        """,
    )


def test_real_document_processing_pipeline_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_cx_real_document_processing_pipeline_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert smoke.summary_line(evidence).startswith(
        "cx_real_document_processing_pipeline_postgres_smoke=skipped"
    )


def test_real_document_processing_pipeline_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_cx_real_document_processing_pipeline_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SMOKE_PROFILE_ENV: "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert "reason=profile_not_allowed" in smoke.summary_line(evidence)


def test_real_document_processing_pipeline_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise MigrationError("boom")

    monkeypatch.setattr(smoke, "run_service_migrations", raise_migration_error)

    evidence = smoke.run_cx_real_document_processing_pipeline_postgres_smoke(
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


def test_real_document_processing_pipeline_postgres_smoke_high_level_success(
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
        "format_count": 4,
        "formats": [{"source_format": "pdf", "chunk_count": 1}],
        "db_observations": {
            "processing_run_count": 4,
            "chunk_count": 4,
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

    monkeypatch.setattr(
        smoke,
        "_execute_real_document_processing_pipeline_smoke",
        fake_execute,
    )

    evidence = smoke.run_cx_real_document_processing_pipeline_postgres_smoke(
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
    assert "formats=4 embedding_mode=unknown pipeline_runs=4 chunks=4" in (
        smoke.summary_line(evidence)
    )


def test_real_document_processing_pipeline_postgres_smoke_reports_execution_failure(
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
        "_execute_real_document_processing_pipeline_smoke",
        raise_runtime_error,
    )

    evidence = smoke.run_cx_real_document_processing_pipeline_postgres_smoke(
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


def test_real_document_processing_pipeline_postgres_smoke_requires_session_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_cx_processing_pipeline_url(tmp_path)
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(mode="postgres", api_session_factory=None),
    )

    with pytest.raises(RuntimeError, match="session factory is unavailable"):
        smoke._execute_real_document_processing_pipeline_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_TEST_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )


def test_real_document_processing_pipeline_postgres_smoke_sqlite_route_path(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_cx_processing_pipeline_url(tmp_path)

    result = smoke._execute_real_document_processing_pipeline_smoke(
        database_env="NEX_CX_TEST_DATABASE_URL",
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_TEST_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )

    assert all(result["checks"].values())
    assert result["format_count"] == 4
    assert {item["source_format"] for item in result["formats"]} == {
        "pdf",
        "docx",
        "pptx",
        "xlsx",
    }
    assert result["db_observations"]["extraction_artifact_count"] == 4
    assert result["db_observations"]["chunk_set_count"] == 4
    assert result["db_observations"]["processing_run_count"] == 4
    assert result["db_observations"]["processing_step_count"] == 24
    assert result["db_observations"]["summary_embedding_count"] == 4
    assert result["db_observations"]["service_job_count"] == 4
    assert result["embedding_provider"]["mode"] == "static"
    assert result["embedding_provider"]["request_count"] == 8
    assert result["expected_embedding_dimension"] == 4
    assert result["db_observations"]["chunk_embedding_min_dimension"] == 4
    assert result["db_observations"]["chunk_embedding_max_dimension"] == 4
    assert result["db_observations"]["summary_embedding_min_dimension"] == 4
    assert result["db_observations"]["summary_embedding_max_dimension"] == 4
    assert all(
        item["before"]["processing_run_rows"] == 1
        and item["before"]["processing_step_rows"] == 6
        and item["before"]["service_job_rows"] == 1
        and item["after"]["processing_run_rows"] == 0
        and item["after"]["content_object_rows"] == 0
        and item["after"]["source_file_rows"] == 0
        for item in result["cleanup_observations"]
    )
    smoke.assert_evidence_redacted(result)
    assert smoke.SECRET_MARKER_PREFIX not in json.dumps(result, ensure_ascii=False)


def test_real_document_processing_pipeline_postgres_smoke_remote_embedding_fake_route_path(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_cx_processing_pipeline_url(tmp_path)
    calls: list[dict[str, object]] = []

    def fake_request(method: str, url: str, **kwargs: object) -> object:
        calls.append({"method": method, "url": url, **kwargs})
        request_json = kwargs["json"]
        inputs = request_json["input"]
        return _FakeProviderResponse(
            {
                "object": "list",
                "data": [
                    {
                        "object": "embedding",
                        "index": index,
                        "embedding": [float(index + 1)] * 6,
                    }
                    for index, _ in enumerate(inputs)
                ],
                "usage": {
                    "prompt_tokens": len(inputs),
                    "total_tokens": len(inputs),
                },
            }
        )

    result = smoke._execute_real_document_processing_pipeline_smoke(
        database_env="NEX_CX_TEST_DATABASE_URL",
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_TEST_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
            smoke.REMOTE_EMBEDDING_ENV: "1",
            smoke.REMOTE_EMBEDDING_EXPECTED_DIMENSION_ENV: "6",
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.internal:9112/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_API_KEY": "secret-key",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B",
            "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "Qwen3-Embedding-4B",
        },
        embedding_requester=fake_request,
    )

    assert all(result["checks"].values())
    assert result["embedding_provider"]["mode"] == "remote_openai_compatible"
    assert result["embedding_provider"]["request_count"] == 8
    assert result["embedding_provider"]["input_count"] >= 8
    assert result["embedding_provider"]["last_vector_dimension"] == 6
    assert result["embedding_provider"]["config"]["configured"] is True
    assert result["embedding_provider"]["config"]["authorization_configured"] is True
    assert result["expected_embedding_dimension"] == 6
    assert result["db_observations"]["chunk_embedding_min_dimension"] == 6
    assert result["db_observations"]["summary_embedding_max_dimension"] == 6
    assert len(calls) == 8
    assert {call["method"] for call in calls} == {"POST"}
    assert all(
        call["headers"]["Authorization"] == "Bearer secret-key" for call in calls
    )
    serialized = json.dumps(result, ensure_ascii=False)
    assert "dgx.internal" not in serialized
    assert "secret-key" not in serialized
    smoke.assert_evidence_redacted(result)


def test_real_document_processing_pipeline_postgres_smoke_remote_embedding_config_guard(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_cx_processing_pipeline_url(tmp_path)

    with pytest.raises(ValueError, match="remote_embedding_endpoint_not_configured"):
        smoke._execute_real_document_processing_pipeline_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_TEST_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
                smoke.REMOTE_EMBEDDING_ENV: "1",
            },
        )

    assert smoke.remote_embedding_config_issues(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://embedding.local/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "wrong-model",
            "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "Qwen3-Embedding-4B",
        }
    ) == [
        {
            "capability": "embedding",
            "error_code": "remote_embedding_expected_model_mismatch",
            "model_name": "wrong-model",
            "expected_models": ["Qwen3-Embedding-4B"],
        }
    ]
    assert smoke.remote_embedding_config_issues(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://embedding.local/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "nex_pcx_embeddings_v1",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B",
        }
    ) == [
        {
            "capability": "embedding",
            "error_code": "remote_embedding_request_shape_mismatch",
            "request_shape": "nex_pcx_embeddings_v1",
            "expected_shape": "openai_embeddings",
        }
    ]
    assert smoke.remote_embedding_config_issues(
        {"NEX_MO_LIVE_TIMEOUT_SECONDS": "0"}
    )[0]["error_code"] == "remote_embedding_timeout_invalid"


def test_remote_mo_embedding_client_maps_provider_errors() -> None:
    def failing_request(*args: object, **kwargs: object) -> object:
        return _FakeProviderResponse({}, status_code=503)

    client = smoke.RemoteMoEmbeddingClient(
        environ={
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://embedding.local/v1/embeddings",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B",
        },
        requester=failing_request,
    )

    with pytest.raises(smoke.EmbeddingIndexError) as exc_info:
        client.create_embeddings(
            ["hello"],
            alias="alias",
            request_id="request",
            trace_id="trace",
        )

    assert exc_info.value.error_code == "mo.remote_embedding_http_error"
    assert exc_info.value.detail == "Remote embedding provider request failed."
    assert client.request_count == 0


def test_real_document_processing_pipeline_postgres_smoke_check_failure_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_cx_processing_pipeline_url(tmp_path)
    monkeypatch.setattr(smoke, "_redaction_safe", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="smoke checks failed"):
        smoke._execute_real_document_processing_pipeline_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_TEST_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    engine = build_engine(database_url)
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM service_jobs")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM cx_content_objects")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM cx_source_files")).scalar_one() == 0


def test_real_document_processing_pipeline_postgres_smoke_helpers_cover_edges(
    tmp_path: Path,
) -> None:
    static_client = smoke.StaticMoEmbeddingClient()
    assert static_client.create_embeddings(
        ["one", "two"],
        alias="alias",
        request_id="request",
        trace_id="trace",
    )["usage"]["total_tokens"] == 2
    assert static_client.safe_summary()["request_count"] == 1
    assert smoke.expected_processing_embedding_dimension({}, mode="static") == 4
    assert (
        smoke.expected_processing_embedding_dimension(
            {},
            mode="remote_openai_compatible",
        )
        == 2560
    )
    assert (
        smoke.expected_processing_embedding_dimension(
            {smoke.REMOTE_EMBEDDING_EXPECTED_DIMENSION_ENV: "6"},
            mode="remote_openai_compatible",
        )
        == 6
    )
    with pytest.raises(ValueError, match="must be an integer"):
        smoke.expected_processing_embedding_dimension(
            {smoke.REMOTE_EMBEDDING_EXPECTED_DIMENSION_ENV: "six"},
            mode="remote_openai_compatible",
        )
    with pytest.raises(ValueError, match="must be positive"):
        smoke.expected_processing_embedding_dimension(
            {smoke.REMOTE_EMBEDDING_EXPECTED_DIMENSION_ENV: "0"},
            mode="remote_openai_compatible",
        )
    assert smoke._embedding_response_dimension({}) == 0
    assert smoke._embedding_response_dimension({"data": ["bad"]}) == 0
    assert smoke._embedding_response_dimension({"data": [{"embedding": "bad"}]}) == 0
    assert smoke.NoopOperationalEventEmitter().safe_emit().ok is True
    assert smoke.NoopWorkerHeartbeatEmitter().safe_emit().ok is True

    database_url = _sqlite_cx_processing_pipeline_url(tmp_path)
    engine = build_engine(database_url)
    with engine.begin() as connection:
        assert smoke._optional_count(
            connection,
            "service_jobs",
            "job_id = :job_id",
            {"job_id": "missing"},
            enabled=False,
        ) == 0
        assert smoke._aggregate_db_observations(
            [
                {
                    "db_observations": {
                        "extraction_artifact_count": 1,
                        "chunk_set_count": 1,
                        "chunk_count": 2,
                        "lexical_term_count": 3,
                        "lexical_posting_count": 4,
                        "chunk_embedding_count": 2,
                        "chunk_embedding_min_dimension": 4,
                        "chunk_embedding_max_dimension": 4,
                        "document_summary_count": 1,
                        "summary_embedding_count": 1,
                        "summary_embedding_min_dimension": 4,
                        "summary_embedding_max_dimension": 4,
                        "processing_run_count": 1,
                        "processing_step_count": 6,
                        "service_job_count": 1,
                    }
                }
            ]
        )["processing_step_count"] == 6
    assert smoke._delete_real_document_processing_rows(
        engine,
        document_id=None,
        source_file_id=None,
        pipeline_run_id=None,
        job_id=None,
    ) == {
        "before": {
            "processing_run_rows": 0,
            "processing_step_rows": 0,
            "service_job_rows": 0,
            "extraction_artifact_rows": 0,
            "chunk_set_rows": 0,
            "chunk_rows": 0,
            "summary_rows": 0,
            "content_object_rows": 0,
            "source_file_rows": 0,
        },
        "after": {
            "processing_run_rows": 0,
            "processing_step_rows": 0,
            "service_job_rows": 0,
            "extraction_artifact_rows": 0,
            "chunk_set_rows": 0,
            "chunk_rows": 0,
            "summary_rows": 0,
            "content_object_rows": 0,
            "source_file_rows": 0,
        },
    }


def test_real_document_processing_pipeline_postgres_smoke_redaction_guard() -> None:
    smoke.assert_evidence_redacted({"safe": "ok"})

    for forbidden in [
        smoke.SECRET_MARKER_PREFIX,
        "source_storage_path",
        "extracted_markdown_path",
        "nex-cx-real-document-processing-smoke-",
        "/data/nex-platform",
    ]:
        with pytest.raises(ValueError, match="not redacted"):
            smoke.assert_evidence_redacted({"leak": forbidden})


def test_real_document_processing_pipeline_postgres_smoke_main_writes_output(
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
        "run_cx_real_document_processing_pipeline_postgres_smoke",
        lambda: evidence,
    )

    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == evidence
    assert (
        "cx_real_document_processing_pipeline_postgres_smoke=skipped"
        in capsys.readouterr().out
    )


def test_real_document_processing_pipeline_postgres_smoke_main_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = smoke._failure("execution_failed", "RuntimeError", profile="test")

    monkeypatch.setattr(
        smoke,
        "run_cx_real_document_processing_pipeline_postgres_smoke",
        lambda: evidence,
    )

    assert smoke.main([]) == 1
    assert '"failure_code": "execution_failed"' in capsys.readouterr().out


def test_real_document_processing_pipeline_postgres_smoke_quality_gate_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0290_cx_real_document_processing_pipeline_postgresql_smoke.md"
    )
    remote_embedding_slice_doc = (
        root
        / "docs"
        / "slices"
        / "0293_cx_processing_pipeline_remote_embedding_postgresql_smoke.md"
    )

    assert (
        "run_cx_real_document_processing_pipeline_postgres_smoke.py --summary"
        in quality_gate
    )
    assert "0290_cx_real_document_processing_pipeline_postgresql_smoke.md" in docs_index
    assert (
        "0293_cx_processing_pipeline_remote_embedding_postgresql_smoke.md"
        in docs_index
    )
    assert slice_doc.exists()
    assert remote_embedding_slice_doc.exists()


class _FakeProviderResponse:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        status_code: int = 200,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.is_error = status_code >= 400

    def json(self) -> dict[str, object]:
        return self._payload
