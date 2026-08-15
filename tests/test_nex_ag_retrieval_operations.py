from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import text

from nex_ag.operations import (
    AG_OPERATIONS_SOURCE_MODE_ENV,
    AG_OPERATIONS_SOURCE_PROFILE_ENV,
    AG_OPERATIONS_SOURCE_SERVICES_ENV,
    AgOperationsSourceRuntime,
    build_operation_query_options,
)
from nex_ag.retrieval_operations import (
    AG_RETRIEVAL_PACKAGE_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_RETRIEVAL_PACKAGE_OPERATIONS_PROJECTION_SCHEMA_VERSION,
    AG_RETRIEVAL_SCORE_CALIBRATION_SCHEMA_VERSION,
    InMemoryRetrievalPackageOperationsStore,
    RetrievalPackageOperationsError,
    SqlAlchemyRetrievalPackageOperationsStore,
    build_retrieval_score_calibration_projection,
    build_retrieval_package_detail_projection,
    build_retrieval_package_operation_stores,
    build_retrieval_package_operations_projection,
    register_retrieval_package_operation_routes,
    summarize_retrieval_package_detail,
    summarize_retrieval_package_operations,
)
from nex_runtime import (
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    SERVICE_SPECS,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {"Authorization": f"Bearer {issued.access_token}"}


def retrieval_record(
    *,
    retrieval_package_id: str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    status: str = "READY",
    trace_id: str = TRACE_ID,
    request_id: str = REQUEST_ID,
    policy_id: str = "weighted_rrf_vector_bm25_v1",
    evidence_count: int = 2,
    created_at: str = "2026-08-09T00:00:00Z",
    no_answer_reason: str | None = None,
    score_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_score_summary = score_summary or {
        "best_score": 0.92,
        "ranker_mix": "weighted_rrf_vector_bm25_v1",
        "rerank_state": "NOT_APPLIED",
        "confidence_bucket": "READY",
        "quality_policy_id": "retrieval_quality_v1",
        "low_confidence_threshold": 0.2,
    }
    return {
        "retrieval_package_id": retrieval_package_id,
        "package_hash": "a" * 64,
        "status": status,
        "trace_id": trace_id,
        "request_id": request_id,
        "query_text_sha256": "b" * 64,
        "query_text_preview": "bounded retrieval query preview",
        "query_embedding_provided": True,
        "query_embedding_sha256": "c" * 64,
        "query_embedding_dimension": 3,
        "purpose": "grounded_answer",
        "retrieval_policy_id": policy_id,
        "retrieval_policy_version": "2026-08-09",
        "retrieval_policy_hash": "d" * 64,
        "retrieval_policy_source": "ag_registry_active",
        "ranker_mix": "weighted_rrf_vector_bm25_v1",
        "rerank_state": "NOT_APPLIED",
        "permission_snapshot_hash": "e" * 64,
        "source_summary": {
            "source_count": 1,
            "document_count": 1,
            "chunk_count": 2,
        },
        "score_summary": resolved_score_summary,
        "warning_count": 0,
        "evidence_count": evidence_count,
        "no_answer_reason": no_answer_reason,
        "created_at": created_at,
        "updated_at": created_at,
    }


def retrieval_evidence_record(
    *,
    evidence_id: str = "evidence-001",
    rank: int = 1,
    final_score: float = 0.92,
    permission_allowed: bool = True,
    quality_flags: list[str] | None = None,
) -> dict[str, object]:
    return {
        "retrieval_package_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "evidence_id": evidence_id,
        "rank": rank,
        "content_object_id": "11111111-1111-4111-8111-111111111111",
        "content_version_id": "version-001",
        "chunk_id": "22222222-2222-4222-8222-222222222222",
        "chunk_policy_id": "chunk_1000_100_v1",
        "source_anchor": {"page": 3, "section": "safe-anchor"},
        "citation_label": "[1]",
        "evidence_text_sha256": "f" * 64,
        "evidence_text_preview": "secret evidence text that must stay out of AG",
        "final_score": final_score,
        "scores": {"vector": final_score, "bm25": 0.41},
        "matched_terms": ["retrieval", "debug"],
        "permission_result": {
            "allowed": permission_allowed,
            "reason": "owner",
            "policy_id": "cx-permission-v1",
            "principal_type": "user",
            "permission": "read",
            "principal_id": "user-secret",
        },
        "neighbor_context": [{"chunk_id": "neighbor-001"}],
        "quality_flags": quality_flags or [],
        "created_at": "2026-08-09T00:00:00Z",
    }


def build_app(
    stores: dict[str, InMemoryRetrievalPackageOperationsStore] | None = None,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_retrieval_package_operation_routes(app, stores=stores or {})
    return TestClient(app)


def test_retrieval_package_operations_projection_filters_and_summarizes() -> None:
    store = InMemoryRetrievalPackageOperationsStore(
        records=[
            retrieval_record(created_at="2026-08-09T00:00:00Z"),
            retrieval_record(
                retrieval_package_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                status="NO_ANSWER",
                evidence_count=0,
                created_at="2026-08-09T00:01:00Z",
                no_answer_reason="no_terms_matched",
                score_summary={
                    "best_score": 0.0,
                    "ranker_mix": "weighted_rrf_vector_bm25_v1",
                    "rerank_state": "NOT_APPLIED",
                    "confidence_bucket": "NO_ANSWER",
                    "quality_policy_id": "retrieval_quality_v1",
                    "low_confidence_threshold": 0.2,
                },
            ),
            retrieval_record(
                retrieval_package_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                status="LOW_CONFIDENCE",
                trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                evidence_count=1,
                created_at="2026-08-09T00:02:00Z",
            ),
        ]
    )
    options = build_operation_query_options(
        limit=5,
        since="2026-08-08T23:59:00Z",
        sort="desc",
    )

    projection = build_retrieval_package_operations_projection(
        stores={"nex-cx": store},
        status="NO_ANSWER",
        query_options=options,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_RETRIEVAL_PACKAGE_OPERATIONS_PROJECTION_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"]["status"] == "NO_ANSWER"
    assert projection["source_statuses"]["nex-cx"]["package_count"] == 1
    assert projection["summary"] == {
        "total": 1,
        "by_status": {"NO_ANSWER": 1},
        "by_policy": {"weighted_rrf_vector_bm25_v1": 1},
        "low_confidence": 0,
        "no_answer": 1,
        "evidence_count": 0,
        "score_calibration": {
            "threshold_override_count": 0,
            "would_pass_default_threshold": 0,
            "default_ready": 0,
            "default_low_confidence": 0,
            "default_no_answer": 1,
            "action_counts": {"inspect_no_answer_retrieval": 1},
        },
    }
    package = projection["retrieval_packages"][0]
    assert package["operation_type"] == "retrieval_package"
    assert package["query_text_sha256"] == "b" * 64
    assert package["query_text_preview"] == "bounded retrieval query preview"
    assert package["best_score"] == 0.0
    assert package["score_calibration"]["calibration_schema_version"] == (
        AG_RETRIEVAL_SCORE_CALIBRATION_SCHEMA_VERSION
    )
    assert package["score_calibration"]["default_confidence_bucket"] == "NO_ANSWER"
    assert "evidence text" not in str(projection).lower()


def test_retrieval_package_operations_projection_reports_source_gaps_and_errors() -> None:
    class BrokenStore(InMemoryRetrievalPackageOperationsStore):
        def list_retrieval_packages(self, **kwargs: object) -> list[dict[str, object]]:
            raise RetrievalPackageOperationsError(
                error_code="ag.retrieval_package_source_unavailable",
                detail="source unavailable",
            )

    missing_projection = build_retrieval_package_operations_projection(
        stores={},
        service_id="nex-cx",
    )
    broken_projection = build_retrieval_package_operations_projection(
        stores={"nex-cx": BrokenStore()},
        service_id="nex-cx",
    )

    assert missing_projection["projection_status"] == "DEGRADED"
    assert missing_projection["source_statuses"]["nex-cx"]["status"] == (
        "NOT_CONFIGURED"
    )
    assert broken_projection["projection_status"] == "DEGRADED"
    assert broken_projection["source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert broken_projection["source_statuses"]["nex-cx"]["error_code"] == (
        "ag.retrieval_package_source_unavailable"
    )


def test_summarize_retrieval_package_operations_counts_empty_list() -> None:
    assert summarize_retrieval_package_operations([]) == {
        "total": 0,
        "by_status": {},
        "by_policy": {},
        "low_confidence": 0,
        "no_answer": 0,
        "evidence_count": 0,
        "score_calibration": {
            "threshold_override_count": 0,
            "would_pass_default_threshold": 0,
            "default_ready": 0,
            "default_low_confidence": 0,
            "default_no_answer": 0,
            "action_counts": {},
        },
    }


def test_retrieval_package_detail_projection_redacts_evidence_text() -> None:
    record = retrieval_record()
    record["evidence_items"] = [
        retrieval_evidence_record(),
        retrieval_evidence_record(
            evidence_id="evidence-002",
            rank=2,
            final_score=0.57,
            permission_allowed=False,
            quality_flags=["low_confidence"],
        ),
    ]
    store = InMemoryRetrievalPackageOperationsStore(records=[record])

    projection = build_retrieval_package_detail_projection(
        service_id="nex-cx",
        store=store,
        package=record,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        AG_RETRIEVAL_PACKAGE_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["retrieval_package"]["retrieval_package_id"] == (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )
    assert projection["summary"]["score_range"] == {"min": 0.57, "max": 0.92}
    assert projection["summary"]["permission_denied_count"] == 1
    assert projection["summary"]["quality_flag_count"] == 1
    assert projection["summary"]["score_calibration"]["calibration_action"] == (
        "default_threshold_accepts_score"
    )
    assert (
        projection["retrieval_package"]["score_calibration"][
            "would_pass_default_threshold"
        ]
        is True
    )
    first_evidence = projection["evidence_items"][0]
    assert first_evidence["evidence_text_preview_redacted"] is True
    assert first_evidence["evidence_text_sha256"] == "f" * 64
    assert first_evidence["matched_term_count"] == 2
    assert first_evidence["permission_result"] == {
        "allowed": True,
        "reason": "owner",
        "policy_id": "cx-permission-v1",
        "principal_type": "user",
        "permission": "read",
    }
    assert "secret evidence text" not in str(projection)
    assert "user-secret" not in str(projection)


def test_summarize_retrieval_package_detail_handles_missing_evidence() -> None:
    summary = summarize_retrieval_package_detail(retrieval_record(), [])

    assert summary["returned_evidence_items"] == 0
    assert summary["score_range"] is None
    assert summary["score_calibration"]["default_confidence_bucket"] == "READY"
    assert summary["evidence_text_preview_redacted"] is True


def test_retrieval_score_calibration_projection_reports_threshold_boundaries() -> None:
    lowered = build_retrieval_score_calibration_projection(
        retrieval_record(
            score_summary={
                "best_score": 0.159322,
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
                "rerank_state": "APPLIED",
                "confidence_bucket": "READY",
                "quality_policy_id": "retrieval_quality_v1",
                "low_confidence_threshold": 0.0,
            }
        ),
        default_low_confidence_threshold=0.2,
    )
    raised = build_retrieval_score_calibration_projection(
        retrieval_record(
            status="LOW_CONFIDENCE",
            score_summary={
                "best_score": 0.3,
                "confidence_bucket": "LOW_CONFIDENCE",
                "quality_policy_id": "retrieval_quality_v1",
                "low_confidence_threshold": 0.5,
            },
        ),
        default_low_confidence_threshold=0.2,
    )
    incomplete = build_retrieval_score_calibration_projection(
        retrieval_record(
            score_summary={
                "confidence_bucket": "not-supported",
                "quality_policy_id": "retrieval_quality_v1",
            }
        ),
        default_low_confidence_threshold=0.2,
    )

    assert lowered["observed_confidence_bucket"] == "READY"
    assert lowered["default_confidence_bucket"] == "LOW_CONFIDENCE"
    assert lowered["threshold_override_used"] is True
    assert lowered["threshold_override_direction"] == "lowered"
    assert lowered["score_margin_to_default_threshold"] == -0.040678
    assert lowered["calibration_action"] == (
        "review_live_threshold_before_canonical_policy"
    )
    assert raised["default_confidence_bucket"] == "READY"
    assert raised["threshold_override_direction"] == "raised"
    assert raised["calibration_action"] == (
        "compare_observed_and_default_confidence"
    )
    assert incomplete["observed_confidence_bucket"] == "UNKNOWN"
    assert incomplete["default_confidence_bucket"] == "UNKNOWN"
    assert incomplete["calibration_action"] == "calibration_data_incomplete"


def test_retrieval_package_operations_route_requires_auth_and_validates_filters() -> None:
    client = build_app(
        {
            "nex-cx": InMemoryRetrievalPackageOperationsStore(
                records=[retrieval_record()]
            )
        }
    )

    unauthorized = client.get("/admin/v1/operations/retrieval-packages")
    bad_service = client.get(
        "/admin/v1/operations/retrieval-packages",
        params={"service_id": "nex-mo"},
        headers=auth_headers(),
    )
    bad_status = client.get(
        "/admin/v1/operations/retrieval-packages",
        params={"status": "FAILED"},
        headers=auth_headers(),
    )
    bad_cursor = client.get(
        "/admin/v1/operations/retrieval-packages",
        params={"cursor": "-1"},
        headers=auth_headers(),
    )
    ok = client.get(
        "/admin/v1/operations/retrieval-packages",
        params={"status": "ready"},
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.retrieval_package_service_invalid"
    assert bad_status.status_code == 400
    assert bad_status.json()["error_code"] == "ag.retrieval_package_status_invalid"
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error_code"] == "ag.operation_cursor_invalid"
    assert ok.status_code == 200
    assert ok.json()["summary"]["total"] == 1


def test_retrieval_package_detail_route_returns_safe_package_debug_view() -> None:
    record = retrieval_record()
    record["evidence_items"] = [retrieval_evidence_record()]
    client = build_app(
        {"nex-cx": InMemoryRetrievalPackageOperationsStore(records=[record])}
    )

    response = client.get(
        "/admin/v1/operations/retrieval-packages/"
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        headers=auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operations/retrieval-packages/missing",
        headers=auth_headers(),
    )
    missing_source = build_app({}).get(
        "/admin/v1/operations/retrieval-packages/"
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        headers=auth_headers(),
    )
    invalid_service = client.get(
        "/admin/v1/operations/retrieval-packages/"
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa?service_id=nex-ae-api",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["projection_schema_version"] == (
        AG_RETRIEVAL_PACKAGE_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert body["summary"]["returned_evidence_items"] == 1
    assert "secret evidence text" not in str(body)
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ag.retrieval_package_not_found"
    assert missing_source.status_code == 404
    assert missing_source.json()["error_code"] == (
        "ag.retrieval_package_source_not_configured"
    )
    assert invalid_service.status_code == 400


def test_retrieval_package_operations_route_reads_runtime_from_app_state() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    app.state.nex_ag_operations_source_runtime = AgOperationsSourceRuntime(
        mode="memory",
        profile="dev",
        selected_service_ids=("nex-cx",),
        registry=None,
    )
    register_retrieval_package_operation_routes(app)
    client = TestClient(app)

    response = client.get(
        "/admin/v1/operations/retrieval-packages",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_status"] == "READY"
    assert payload["source_statuses"]["nex-cx"]["source_kind"] == "memory"


def test_retrieval_package_operation_stores_follow_operations_runtime_config() -> None:
    memory_runtime = AgOperationsSourceRuntime(
        mode="memory",
        profile="dev",
        selected_service_ids=("nex-cx", "nex-ag"),
        registry=None,
    )
    postgres_runtime = AgOperationsSourceRuntime(
        mode="postgres",
        profile="test",
        selected_service_ids=("nex-cx",),
        registry=None,
    )
    missing_cx_runtime = AgOperationsSourceRuntime(
        mode="postgres",
        profile="test",
        selected_service_ids=("nex-ag",),
        registry=None,
    )
    env = {
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql://nex_cx_user:secret@localhost/nex_cx_test"
        )
    }

    memory_stores = build_retrieval_package_operation_stores(runtime=memory_runtime)
    postgres_stores = build_retrieval_package_operation_stores(
        runtime=postgres_runtime,
        environ=env,
        engine_factory=lambda database_url, *, pool_settings: SimpleNamespace(
            database_url=database_url,
            pool_settings=pool_settings,
        ),
        session_factory_builder=lambda engine: f"session:{engine.pool_settings.workload}",
    )
    missing_stores = build_retrieval_package_operation_stores(
        runtime=missing_cx_runtime,
        environ=env,
    )

    assert memory_stores["nex-cx"].source_kind == "memory"
    assert postgres_stores["nex-cx"].source_kind == "postgres-read"
    assert postgres_stores["nex-cx"].database_env == "NEX_CX_TEST_DATABASE_URL"
    assert postgres_stores["nex-cx"].redacted_database_url.endswith(
        "nex_cx_user:***@localhost/nex_cx_test"
    )
    assert missing_stores == {}
    assert "secret" not in str(postgres_stores["nex-cx"].redacted_database_url)


def test_retrieval_package_operation_stores_can_read_environment_without_runtime() -> None:
    stores = build_retrieval_package_operation_stores(
        environ={
            AG_OPERATIONS_SOURCE_MODE_ENV: "memory",
            AG_OPERATIONS_SOURCE_PROFILE_ENV: "test",
            AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
        }
    )

    assert stores["nex-cx"].source_kind == "memory"


def test_sqlalchemy_retrieval_package_operations_store_reads_sqlite_rows(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'retrieval-packages.sqlite'}"
    engine = build_engine(database_url)
    _create_sqlite_retrieval_package_table(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO cx_retrieval_packages (
                    retrieval_package_id,
                    package_hash,
                    status,
                    trace_id,
                    request_id,
                    query_text_sha256,
                    query_text_preview,
                    query_embedding_provided,
                    query_embedding_sha256,
                    query_embedding_dimension,
                    purpose,
                    retrieval_policy_id,
                    retrieval_policy_version,
                    retrieval_policy_hash,
                    retrieval_policy_source,
                    ranker_mix,
                    rerank_state,
                    permission_snapshot_hash,
                    source_summary,
                    score_summary,
                    warning_count,
                    evidence_count,
                    no_answer_reason,
                    created_at,
                    updated_at
                )
                VALUES (
                    :retrieval_package_id,
                    :package_hash,
                    :status,
                    :trace_id,
                    :request_id,
                    :query_text_sha256,
                    :query_text_preview,
                    :query_embedding_provided,
                    :query_embedding_sha256,
                    :query_embedding_dimension,
                    :purpose,
                    :retrieval_policy_id,
                    :retrieval_policy_version,
                    :retrieval_policy_hash,
                    :retrieval_policy_source,
                    :ranker_mix,
                    :rerank_state,
                    :permission_snapshot_hash,
                    :source_summary,
                    :score_summary,
                    :warning_count,
                    :evidence_count,
                    :no_answer_reason,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                **retrieval_record(),
                "query_embedding_provided": 0,
                "source_summary": '{"source_count":1,"document_count":1,"chunk_count":2}',
                "score_summary": '{"best_score":0.92}',
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO cx_retrieval_evidence_items (
                    retrieval_package_id,
                    evidence_id,
                    rank,
                    content_object_id,
                    content_version_id,
                    chunk_id,
                    chunk_policy_id,
                    source_anchor,
                    citation_label,
                    evidence_text_sha256,
                    evidence_text_preview,
                    final_score,
                    scores,
                    matched_terms,
                    permission_result,
                    neighbor_context,
                    quality_flags,
                    created_at
                )
                VALUES (
                    :retrieval_package_id,
                    :evidence_id,
                    :rank,
                    :content_object_id,
                    :content_version_id,
                    :chunk_id,
                    :chunk_policy_id,
                    :source_anchor,
                    :citation_label,
                    :evidence_text_sha256,
                    :evidence_text_preview,
                    :final_score,
                    :scores,
                    :matched_terms,
                    :permission_result,
                    :neighbor_context,
                    :quality_flags,
                    :created_at
                )
                """
            ),
            {
                **retrieval_evidence_record(),
                "source_anchor": '{"page":3}',
                "scores": '{"vector":0.92,"bm25":0.41}',
                "matched_terms": '["retrieval","debug"]',
                "permission_result": '{"allowed":true,"reason":"owner"}',
                "neighbor_context": '[{"chunk_id":"neighbor-001"}]',
                "quality_flags": '["debug_checked"]',
            },
        )
    store = SqlAlchemyRetrievalPackageOperationsStore(build_session_factory(engine))

    rows = store.list_retrieval_packages(status="READY", trace_id=TRACE_ID)
    detail = store.get_retrieval_package(
        retrieval_package_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )

    assert len(rows) == 1
    assert rows[0]["retrieval_package_id"] == (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )
    assert rows[0]["query_embedding_provided"] is False
    assert rows[0]["source_summary"]["chunk_count"] == 2
    assert rows[0]["score_summary"]["best_score"] == 0.92
    assert detail is not None
    assert detail["evidence_items"][0]["evidence_text_sha256"] == "f" * 64
    assert detail["evidence_items"][0]["quality_flags"] == ["debug_checked"]
    assert store.get_retrieval_package(retrieval_package_id="missing") is None


def test_sqlalchemy_retrieval_package_operations_store_wraps_sql_errors(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'missing-table.sqlite'}"
    store = SqlAlchemyRetrievalPackageOperationsStore(
        build_session_factory(build_engine(database_url))
    )

    try:
        store.list_retrieval_packages()
    except RetrievalPackageOperationsError as exc:
        assert exc.error_code == "ag.retrieval_package_source_unavailable"
    else:
        raise AssertionError("expected retrieval package source failure")


def _create_sqlite_retrieval_package_table(engine: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_retrieval_packages (
                    retrieval_package_id TEXT PRIMARY KEY,
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
                    retrieval_package_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    content_object_id TEXT NOT NULL,
                    content_version_id TEXT,
                    chunk_id TEXT NOT NULL,
                    chunk_policy_id TEXT,
                    source_anchor TEXT NOT NULL DEFAULT '{}',
                    citation_label TEXT,
                    evidence_text_sha256 TEXT NOT NULL,
                    evidence_text_preview TEXT,
                    final_score REAL NOT NULL,
                    scores TEXT NOT NULL DEFAULT '{}',
                    matched_terms TEXT NOT NULL DEFAULT '[]',
                    permission_result TEXT NOT NULL DEFAULT '{}',
                    neighbor_context TEXT NOT NULL DEFAULT '[]',
                    quality_flags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (retrieval_package_id, evidence_id)
                )
                """
            )
        )
