from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

import run_protected_live_rag_postgres_smoke as smoke
from test_cx_real_document_processing_pipeline_postgres_smoke import (
    _sqlite_cx_processing_pipeline_url,
)


def _live_env(database_url: str = "postgresql://user:secret@localhost/db") -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_CX_TEST_DATABASE_URL": database_url,
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "live-embedding-secret",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B",
        "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "Qwen3-Embedding-4B",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "live-reranker-secret",
        "NEX_MO_REMOTE_RERANKER_MODEL": "Qwen3-Reranker-0.6B",
        "NEX_MO_LIVE_EXPECTED_RERANKER_MODELS": "Qwen3-Reranker-0.6B",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": (
            "http://dgx.local:12000/v1/chat/completions"
        ),
        "NEX_MO_VLLM_API_KEY": "live-generation-secret",
        "NEX_MO_VLLM_MODEL": "Qwen3.5-122B-A10B-NVFP4",
        "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": "Qwen3.5-122B-A10B-NVFP4",
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "rerank",
    }


def _fake_remote_request(
    calls: list[dict[str, object]],
):
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        payload = kwargs["json"]
        if url.endswith("/v1/embeddings"):
            inputs = payload["input"]
            assert payload["model"] == "Qwen3-Embedding-4B"
            return httpx.Response(
                200,
                json={
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
                },
            )
        if url.endswith("/v1/rerank"):
            assert payload["model"] == "Qwen3-Reranker-0.6B"
            assert payload["top_n"] == 1
            return httpx.Response(
                200,
                json={
                    "results": [{"index": 0, "relevance_score": 0.94}],
                    "usage": {"prompt_tokens": 8, "total_tokens": 8},
                },
            )
        assert payload["model"] == "Qwen3.5-122B-A10B-NVFP4"
        assert payload["messages"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-live-rag-postgres-smoke",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Protected live RAG PostgreSQL answer.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 13,
                    "completion_tokens": 6,
                    "total_tokens": 19,
                },
            },
        )

    return requester


def _sqlite_live_rag_url(tmp_path: Path) -> str:
    database_url = _sqlite_cx_processing_pipeline_url(tmp_path)
    engine = smoke.build_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_retrieval_packages (
                    retrieval_package_id TEXT PRIMARY KEY,
                    retrieval_package_schema_version TEXT NOT NULL DEFAULT 'cx_retrieval_context_package.v1',
                    package_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    query_text_sha256 TEXT NOT NULL,
                    query_text_preview TEXT,
                    query_embedding_provided BOOLEAN NOT NULL DEFAULT 0,
                    query_embedding_sha256 TEXT,
                    query_embedding_dimension INTEGER NOT NULL DEFAULT 0,
                    purpose TEXT NOT NULL,
                    retrieval_policy_id TEXT NOT NULL,
                    retrieval_policy_version TEXT,
                    retrieval_policy_hash TEXT,
                    retrieval_policy_source TEXT NOT NULL,
                    ranker_mix TEXT NOT NULL,
                    rerank_state TEXT NOT NULL,
                    permission_snapshot_hash TEXT NOT NULL,
                    source_summary TEXT NOT NULL DEFAULT '{}',
                    score_summary TEXT NOT NULL DEFAULT '{}',
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    no_answer_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_retrieval_evidence_items (
                    retrieval_package_id TEXT NOT NULL REFERENCES cx_retrieval_packages(retrieval_package_id),
                    evidence_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    content_version_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL REFERENCES cx_chunks(chunk_id),
                    chunk_policy_id TEXT NOT NULL,
                    source_anchor TEXT NOT NULL DEFAULT '{}',
                    citation_label TEXT NOT NULL,
                    evidence_text_sha256 TEXT NOT NULL,
                    evidence_text_preview TEXT NOT NULL,
                    final_score REAL NOT NULL DEFAULT 0,
                    scores TEXT NOT NULL DEFAULT '{}',
                    matched_terms TEXT NOT NULL DEFAULT '[]',
                    permission_result TEXT NOT NULL DEFAULT '{}',
                    neighbor_context TEXT NOT NULL DEFAULT '[]',
                    quality_flags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (retrieval_package_id, evidence_id),
                    UNIQUE (retrieval_package_id, rank)
                )
                """
            )
        )
    return database_url


def _count_rows(database_url: str, table: str) -> int:
    engine = smoke.build_engine(database_url)
    with engine.begin() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_protected_live_rag_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_protected_live_rag_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "protected_live_rag_postgres_smoke=skipped "
        "reason=NEX_PROTECTED_LIVE_RAG_POSTGRES_SMOKE"
    )


def test_protected_live_rag_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_protected_live_rag_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SMOKE_PROFILE_ENV: "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "protected_live_rag_postgres_smoke=fail "
        "service=nex-cx profile=dev reason=profile_not_allowed stage=unknown"
    )


def test_protected_live_rag_postgres_smoke_reports_configuration_issues() -> None:
    evidence = smoke.run_protected_live_rag_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "nex_pcx_embeddings_v1",
            "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "nex_pcx_rerank_v1",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert {
        issue["error_code"] for issue in evidence["issues"]
    } >= {
        "provider_endpoint_missing",
        "embedding_request_shape_not_compatible",
        "reranker_request_shape_not_compatible",
    }


def test_protected_live_rag_postgres_smoke_high_level_success_redacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "service_database_env",
        lambda service_id, profile: "NEX_CX_TEST_DATABASE_URL",
    )
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda service_id, profile, environ: environ["NEX_CX_TEST_DATABASE_URL"],
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: SimpleNamespace(
            service_id=service_id,
            profile=profile,
            planned=("001",),
            applied=(),
            skipped=("001",),
            dry_run=False,
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_protected_live_rag_postgres_smoke",
        lambda **kwargs: {
            "rag_evidence": {
                "retrieval": {"status": "READY", "rerank_state": "APPLIED"},
                "generation": {"status": "COMPLETED"},
            },
            "db_observations": {"chunk_embedding_max_dimension": 6},
            "checks": {"ok": True},
        },
    )

    evidence = smoke.run_protected_live_rag_postgres_smoke(_live_env())
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert evidence["migration"]["planned_count"] == 1
    assert "secret" not in serialized
    assert "dgx.local" not in serialized
    assert "live-generation-secret" not in serialized
    assert smoke.summary_line(evidence) == (
        "protected_live_rag_postgres_smoke=pass "
        "service=nex-cx profile=test db_env=NEX_CX_TEST_DATABASE_URL "
        "retrieval=READY rerank=APPLIED generation=COMPLETED embedding_dim=6"
    )


def test_protected_live_rag_postgres_smoke_reports_migration_and_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "service_database_env",
        lambda service_id, profile: "NEX_CX_TEST_DATABASE_URL",
    )

    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise smoke.MigrationError("missing database")

    monkeypatch.setattr(smoke, "service_database_url", raise_migration_error)
    migration_failure = smoke.run_protected_live_rag_postgres_smoke(_live_env())

    assert migration_failure["status"] == "FAIL"
    assert migration_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda service_id, profile, environ: environ["NEX_CX_TEST_DATABASE_URL"],
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: SimpleNamespace(),
    )

    def raise_runtime_error(**kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        smoke,
        "_execute_protected_live_rag_postgres_smoke",
        raise_runtime_error,
    )
    execution_failure = smoke.run_protected_live_rag_postgres_smoke(_live_env())

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"

    def raise_stage_error(**kwargs: object) -> None:
        raise smoke.LiveRagSmokeStageError(
            stage="generation",
            error_code="cx.retrieval_package_not_ready",
            detail="Retrieval package status is LOW_CONFIDENCE.",
            status_code=409,
            retryable=False,
            stage_status={"generation": "FAIL"},
        )

    monkeypatch.setattr(
        smoke,
        "_execute_protected_live_rag_postgres_smoke",
        raise_stage_error,
    )
    stage_failure = smoke.run_protected_live_rag_postgres_smoke(_live_env())

    assert stage_failure["status"] == "FAIL"
    assert stage_failure["failure_code"] == "execution_failed"
    assert stage_failure["detail"] == "cx.retrieval_package_not_ready"
    assert stage_failure["diagnostics"] == {
        "stage": "generation",
        "error_code": "cx.retrieval_package_not_ready",
        "detail": "Retrieval package status is LOW_CONFIDENCE.",
        "stage_status": {"generation": "FAIL"},
        "status_code": 409,
        "retryable": False,
    }
    assert smoke.summary_line(stage_failure) == (
        "protected_live_rag_postgres_smoke=fail "
        "service=nex-cx profile=test reason=execution_failed stage=generation"
    )


def test_protected_live_rag_postgres_smoke_sqlite_route_path(tmp_path: Path) -> None:
    database_url = _sqlite_live_rag_url(tmp_path)
    calls: list[dict[str, object]] = []

    result = smoke._execute_protected_live_rag_postgres_smoke(
        database_env="NEX_CX_TEST_DATABASE_URL",
        database_url=database_url,
        runtime_environ={
            **_live_env(database_url),
            "NEX_CX_TEST_DATABASE_URL": database_url,
        },
        requester=_fake_remote_request(calls),
    )
    serialized = json.dumps(result, ensure_ascii=False, default=str)

    assert all(result["checks"].values())
    assert result["stage_status"]["upload"] == "PASS"
    assert result["stage_status"]["score_calibration"] == "PASS"
    assert result["stage_status"]["generation"] == "PASS"
    assert result["stage_status"]["cleanup"] == "PASS"
    assert result["rag_evidence"]["retrieval"]["status"] == "READY"
    assert result["rag_evidence"]["retrieval"]["rerank_state"] == "APPLIED"
    assert result["rag_evidence"]["generation"]["status"] == "COMPLETED"
    assert result["score_calibration"]["checkpoint_schema_version"] == (
        smoke.SCORE_CALIBRATION_SCHEMA_VERSION
    )
    assert result["score_calibration"]["best_score"] == 0.94
    assert result["score_calibration"]["observed_low_confidence_threshold"] == 0.0
    assert result["score_calibration"]["default_low_confidence_threshold"] == 0.2
    assert result["score_calibration"]["threshold_override_used"] is True
    assert result["score_calibration"]["threshold_override_direction"] == "lowered"
    assert result["score_calibration"]["would_pass_default_threshold"] is True
    assert result["score_calibration"]["calibration_action"] == (
        "default_threshold_accepts_score"
    )
    assert result["db_observations"]["content_object_count"] == 1
    assert result["db_observations"]["source_file_count"] == 1
    assert result["db_observations"]["chunk_embedding_max_dimension"] == 6
    assert result["db_observations"]["retrieval_evidence_count"] == 1
    assert result["checks"]["score_calibration_recorded"] is True
    assert result["cleanup_observations"]["before"]["content_object_rows"] == 1
    assert result["cleanup_observations"]["after"]["content_object_rows"] == 0
    assert _count_rows(database_url, "cx_retrieval_packages") == 0
    assert _count_rows(database_url, "cx_retrieval_evidence_items") == 0
    assert _count_rows(database_url, "cx_content_objects") == 0
    assert _count_rows(database_url, "cx_source_files") == 0
    assert [call["url"] for call in calls] == [
        "http://dgx.local:9112/v1/embeddings",
        "http://dgx.local:9113/v1/rerank",
        "http://dgx.local:12000/v1/chat/completions",
    ]
    assert calls[0]["headers"]["Authorization"] == "Bearer live-embedding-secret"
    assert calls[1]["headers"]["Authorization"] == "Bearer live-reranker-secret"
    assert calls[2]["headers"]["Authorization"] == "Bearer live-generation-secret"
    assert "dgx.local" not in serialized
    assert "live-embedding-secret" not in serialized
    assert "live-reranker-secret" not in serialized
    assert "live-generation-secret" not in serialized
    assert smoke.SMOKE_TEXT not in serialized
    smoke.assert_protected_live_rag_postgres_evidence_redacted(
        result,
        _live_env(database_url),
    )


def test_protected_live_rag_postgres_smoke_generation_http_failure_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_live_rag_url(tmp_path)

    def fail_generation(*args: object, **kwargs: object) -> None:
        request = httpx.Request("POST", "http://testserver/api/v1/generations")
        response = httpx.Response(
            409,
            request=request,
            json={
                "error_code": "cx.retrieval_package_not_ready",
                "detail": "Retrieval package status is LOW_CONFIDENCE.",
                "retryable": False,
            },
        )
        raise httpx.HTTPStatusError(
            "Client error '409 Conflict'",
            request=request,
            response=response,
        )

    monkeypatch.setattr(smoke, "create_grounded_generation", fail_generation)

    with pytest.raises(smoke.LiveRagSmokeStageError) as exc_info:
        smoke._execute_protected_live_rag_postgres_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                **_live_env(database_url),
                "NEX_CX_TEST_DATABASE_URL": database_url,
            },
            requester=_fake_remote_request([]),
        )

    diagnostics = exc_info.value.to_safe_diagnostics()
    assert diagnostics["stage"] == "generation"
    assert diagnostics["error_code"] == "cx.retrieval_package_not_ready"
    assert diagnostics["status_code"] == 409
    assert diagnostics["retryable"] is False
    assert diagnostics["detail"] == "Retrieval package status is LOW_CONFIDENCE."
    assert diagnostics["stage_status"]["upload"] == "PASS"
    assert diagnostics["stage_status"]["generation"] == "FAIL"
    assert diagnostics["stage_status"]["cleanup"] == "PASS"
    assert _count_rows(database_url, "cx_retrieval_packages") == 0
    assert _count_rows(database_url, "cx_content_objects") == 0
    assert "dgx.local" not in json.dumps(diagnostics, ensure_ascii=False)


def test_protected_live_rag_postgres_smoke_check_failure_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_live_rag_url(tmp_path)

    monkeypatch.setattr(
        smoke,
        "_read_live_rag_db_observations",
        lambda *args, **kwargs: {
            "source_file_count": 0,
            "content_object_count": 0,
            "extraction_artifact_count": 0,
            "chunk_set_count": 0,
            "chunk_count": 0,
            "lexical_term_count": 0,
            "lexical_posting_count": 0,
            "chunk_embedding_count": 0,
            "chunk_embedding_min_dimension": 0,
            "chunk_embedding_max_dimension": 0,
            "retrieval_package_count": 0,
            "retrieval_status": "LOW_CONFIDENCE",
            "retrieval_rerank_state": "NOT_APPLIED",
            "retrieval_evidence_count": 0,
            "retrieval_stored_evidence_count": 0,
            "retrieval_max_final_score": 0.0,
        },
    )

    with pytest.raises(smoke.LiveRagSmokeStageError) as exc_info:
        smoke._execute_protected_live_rag_postgres_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                **_live_env(database_url),
                "NEX_CX_TEST_DATABASE_URL": database_url,
            },
            requester=_fake_remote_request([]),
        )

    assert exc_info.value.stage == "checks"
    assert exc_info.value.error_code == "protected_live_rag_postgres_checks_failed"
    assert _count_rows(database_url, "cx_content_objects") == 0
    assert _count_rows(database_url, "cx_source_files") == 0


def test_protected_live_rag_score_calibration_checkpoint_boundaries() -> None:
    checkpoint = smoke.build_score_calibration_checkpoint(
        {
            "status": "READY",
            "evidence_items": [{"evidence_id": "evidence-1"}],
            "score_summary": {
                "best_score": 0.11,
                "confidence_bucket": "READY",
                "low_confidence_threshold": 0.0,
                "quality_policy_id": "retrieval_quality_v1",
                "ranker_mix": "bm25_embedding_with_rerank",
                "rerank_state": "APPLIED",
            },
        }
    )

    assert checkpoint == {
        "checkpoint_schema_version": smoke.SCORE_CALIBRATION_SCHEMA_VERSION,
        "quality_policy_id": "retrieval_quality_v1",
        "ranker_mix": "bm25_embedding_with_rerank",
        "rerank_state": "APPLIED",
        "observed_status": "READY",
        "observed_confidence_bucket": "READY",
        "default_confidence_bucket": "LOW_CONFIDENCE",
        "best_score": 0.11,
        "evidence_count": 1,
        "observed_low_confidence_threshold": 0.0,
        "default_low_confidence_threshold": 0.2,
        "threshold_override_used": True,
        "threshold_override_direction": "lowered",
        "would_pass_default_threshold": False,
        "score_margin_to_observed_threshold": 0.11,
        "score_margin_to_default_threshold": -0.09,
        "calibration_action": "review_live_threshold_before_canonical_policy",
    }

    no_answer = smoke.build_score_calibration_checkpoint(
        {
            "status": "NO_ANSWER",
            "evidence_items": [],
            "score_summary": {
                "best_score": 0.0,
                "low_confidence_threshold": 0.2,
            },
        }
    )
    assert no_answer["default_confidence_bucket"] == "NO_ANSWER"
    assert no_answer["threshold_override_used"] is False
    assert no_answer["threshold_override_direction"] == "none"
    assert no_answer["calibration_action"] == "inspect_no_answer_retrieval"

    strict = smoke.build_score_calibration_checkpoint(
        {
            "status": "LOW_CONFIDENCE",
            "evidence_items": [{"evidence_id": "evidence-1"}],
            "score_summary": {
                "best_score": 0.3,
                "low_confidence_threshold": 0.5,
            },
        }
    )
    assert strict["threshold_override_direction"] == "raised"
    assert strict["calibration_action"] == "compare_observed_and_default_confidence"


def test_protected_live_rag_postgres_smoke_helpers_cover_edges(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_live_rag_url(tmp_path)
    engine = smoke.build_engine(database_url)

    with pytest.raises(RuntimeError, match="lineage is incomplete"):
        smoke._read_live_rag_db_observations(
            engine,
            document_id=None,
            source_file_id=None,
            retrieval_package_id=None,
        )

    with pytest.raises(RuntimeError, match="retrieval package"):
        smoke._read_live_rag_db_observations(
            engine,
            document_id="missing-document",
            source_file_id="missing-source-file",
            retrieval_package_id="missing-retrieval",
        )

    assert smoke._database_password(None) is None
    assert smoke._database_password("sqlite+pysqlite:///tmp/test.sqlite") is None
    assert smoke._database_password("postgresql://user@localhost/db") is None
    assert (
        smoke._database_password("postgresql+psycopg://user:secret@localhost/db")
        == "secret"
    )
    assert smoke._database_secret_leaked(
        '{"password":"secret"}',
        "postgresql+psycopg://user:secret@localhost/db",
    )
    assert not smoke._database_secret_leaked(
        '{"redacted_database_url":"postgresql://user:***@localhost/db"}',
        "postgresql+psycopg://user:secret@localhost/db",
    )

    with pytest.raises(ValueError, match="database secret"):
        smoke.assert_protected_live_rag_postgres_evidence_redacted(
            {"database": "secret"},
            {"NEX_CX_TEST_DATABASE_URL": "postgresql://user:secret@localhost/db"},
        )
    with pytest.raises(ValueError, match="raw source text"):
        smoke.assert_protected_live_rag_postgres_evidence_redacted(
            {"source": smoke.SMOKE_TEXT},
            {},
        )

    assert smoke._summary_failure_stage({"status": "FAIL"}) == "unknown"
    assert smoke._bounded_detail("x" * 300).endswith("...")
    request = httpx.Request("POST", "http://testserver/api/v1/embedding")
    response = httpx.Response(503, request=request, content=b"not-json")
    error = smoke._stage_failure_from_exception(
        "embedding_index",
        httpx.HTTPStatusError("failed", request=request, response=response),
        stage_status={"embedding_index": "FAIL"},
    )
    assert error.to_safe_diagnostics()["error_code"] == "http_status_503"
    assert smoke._safe_float(True, default=0.2) == 0.2
    assert smoke._safe_float("bad", default=0.3) == 0.3
    assert smoke._safe_string("", default="fallback") == "fallback"


def test_protected_live_rag_postgres_smoke_main_prints_summary_and_full_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_protected_live_rag_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "protected_live_rag_postgres_smoke=skipped" in capsys.readouterr().out

    output_path = tmp_path / "protected-live-rag-postgres.json"
    assert smoke.main(["--output", str(output_path)]) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "SKIPPED"
