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
    AG_RETRIEVAL_PACKAGE_OPERATIONS_PROJECTION_SCHEMA_VERSION,
    InMemoryRetrievalPackageOperationsStore,
    RetrievalPackageOperationsError,
    SqlAlchemyRetrievalPackageOperationsStore,
    build_retrieval_package_operation_stores,
    build_retrieval_package_operations_projection,
    register_retrieval_package_operation_routes,
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
) -> dict[str, object]:
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
        "score_summary": {
            "best_score": 0.92,
            "ranker_mix": "weighted_rrf_vector_bm25_v1",
        },
        "warning_count": 0,
        "evidence_count": evidence_count,
        "no_answer_reason": no_answer_reason,
        "created_at": created_at,
        "updated_at": created_at,
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
    }
    package = projection["retrieval_packages"][0]
    assert package["operation_type"] == "retrieval_package"
    assert package["query_text_sha256"] == "b" * 64
    assert package["query_text_preview"] == "bounded retrieval query preview"
    assert package["best_score"] == 0.92
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
    }


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
    store = SqlAlchemyRetrievalPackageOperationsStore(build_session_factory(engine))

    rows = store.list_retrieval_packages(status="READY", trace_id=TRACE_ID)

    assert len(rows) == 1
    assert rows[0]["retrieval_package_id"] == (
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )
    assert rows[0]["query_embedding_provided"] is False
    assert rows[0]["source_summary"]["chunk_count"] == 2
    assert rows[0]["score_summary"]["best_score"] == 0.92


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
