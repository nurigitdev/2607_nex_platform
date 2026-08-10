from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ag.operations import build_operation_query_options
from nex_ag.processing_operations import (
    AG_CX_PROCESSING_RUN_DETAIL_PROJECTION_SCHEMA_VERSION,
    AG_CX_PROCESSING_RUN_OPERATIONS_PROJECTION_SCHEMA_VERSION,
    CxProcessingRunOperationsError,
    InMemoryCxProcessingRunOperationsStore,
    SqlAlchemyCxProcessingRunOperationsStore,
    build_cx_processing_run_detail_projection,
    build_cx_processing_run_operation_stores,
    build_cx_processing_run_operations_projection,
    register_cx_processing_run_operation_routes,
)
import nex_ag.processing_operations as processing_operations
from nex_runtime import (
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
PIPELINE_RUN_ID = "22222222-2222-4222-8222-222222222222"
ERROR_HASH = "c" * 64
OUTPUT_HASH = "a" * 64


def processing_run(
    *,
    pipeline_run_id: str = PIPELINE_RUN_ID,
    document_id: str = DOCUMENT_ID,
    status: str = "FAILED",
    include_secret: bool = False,
) -> dict[str, Any]:
    run = {
        "pipeline_run_id": pipeline_run_id,
        "pipeline_schema_version": "cx_document_processing_pipeline.v1",
        "document_id": document_id,
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "job_id": "job-0190",
        "job_type": "cx.document_processing",
        "job_status": status,
        "job_attempt_count": 1,
        "job_max_attempts": 3,
        "job_retryable": True,
        "job_subject_ref": {"type": "document", "id": document_id},
        "job_links": {"processing": f"/api/v1/documents/{document_id}/processing"},
        "step_total": 2,
        "step_succeeded": 1,
        "step_skipped": 0,
        "step_failed": 1,
        "queued_at": "2026-08-10T00:00:00Z",
        "started_at": "2026-08-10T00:01:00Z",
        "completed_at": "2026-08-10T00:02:00Z",
        "updated_at": "2026-08-10T00:02:10Z",
        "steps": [
            {
                "pipeline_run_id": pipeline_run_id,
                "step_order": 1,
                "step_id": "extract_text",
                "status": "SUCCEEDED",
                "output_ref_type": "text_extraction",
                "output_ref_id": "text-extraction-0190",
                "output_ref_document_id": document_id,
                "output_ref_hash": OUTPUT_HASH,
                "error_code": None,
                "error_detail_sha256": None,
                "error_retryable": None,
                "created_at": "2026-08-10T00:01:30Z",
            },
            {
                "pipeline_run_id": pipeline_run_id,
                "step_order": 2,
                "step_id": "build_embedding_index",
                "status": "FAILED",
                "output_ref_type": None,
                "output_ref_id": None,
                "output_ref_document_id": document_id,
                "output_ref_hash": None,
                "error_code": "cx.embedding.provider_unavailable",
                "error_detail_sha256": ERROR_HASH,
                "error_retryable": True,
                "created_at": "2026-08-10T00:02:00Z",
            },
        ],
    }
    if include_secret:
        run["steps"][1]["error_detail"] = "SECRET_ERROR_DETAIL"
        run["source_text"] = "SECRET_SOURCE_TEXT"
    return run


def auth_headers(*, trace_id: str = TRACE_ID, request_id: str = REQUEST_ID) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def client_for_store(store: object) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_cx_processing_run_operation_routes(app, stores={"nex-cx": store})
    return TestClient(app)


def test_cx_processing_run_operations_projection_filters_and_summarizes() -> None:
    store = InMemoryCxProcessingRunOperationsStore(
        records=[
            processing_run(),
            processing_run(
                pipeline_run_id="33333333-3333-4333-8333-333333333333",
                document_id="44444444-4444-4444-8444-444444444444",
                status="SUCCEEDED",
            ),
        ]
    )

    projection = build_cx_processing_run_operations_projection(
        stores={"nex-cx": store},
        service_id="nex-cx",
        document_id=DOCUMENT_ID,
        status="FAILED",
        trace_id=TRACE_ID,
        include_steps=False,
        request_trace_id=TRACE_ID,
    )

    run = projection["processing_runs"][0]
    assert (
        projection["projection_schema_version"]
        == AG_CX_PROCESSING_RUN_OPERATIONS_PROJECTION_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY"
    assert projection["summary"] == {
        "total": 1,
        "by_status": {"FAILED": 1},
        "failed_count": 1,
        "running_count": 0,
        "retryable_failed_count": 1,
        "step_failed_count": 1,
    }
    assert projection["source_statuses"]["nex-cx"]["source_kind"] == "memory"
    assert projection["pagination"]["returned"] == 1
    assert run["steps_included"] is False
    assert run["steps"] == []


def test_in_memory_cx_processing_run_store_filters_all_optional_fields() -> None:
    store = InMemoryCxProcessingRunOperationsStore(records=[processing_run()])

    assert store.list_processing_runs(document_id="missing") == []
    assert store.list_processing_runs(status="SUCCEEDED") == []
    assert store.list_processing_runs(trace_id="0" * 32) == []
    assert store.list_processing_runs(request_id="missing-request") == []
    assert store.list_processing_runs(job_id="missing-job") == []
    matched = store.list_processing_runs(
        document_id=DOCUMENT_ID,
        status="FAILED",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        job_id="job-0190",
        include_steps=True,
        limit=1,
    )

    assert len(matched) == 1
    assert matched[0]["steps"][1]["step_id"] == "build_embedding_index"


def test_cx_processing_run_detail_projection_includes_safe_step_metadata_only() -> None:
    store = InMemoryCxProcessingRunOperationsStore(records=[processing_run(include_secret=True)])

    projection = build_cx_processing_run_detail_projection(
        service_id="nex-cx",
        store=store,
        run=store.get_processing_run(pipeline_run_id=PIPELINE_RUN_ID),
        request_trace_id=TRACE_ID,
    )

    serialized = str(projection)
    failed_step = projection["processing_run"]["steps"][1]
    assert (
        projection["projection_schema_version"]
        == AG_CX_PROCESSING_RUN_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert projection["summary"]["returned_step_count"] == 2
    assert projection["summary"]["error_hash_count"] == 1
    assert failed_step["error_detail_sha256"] == ERROR_HASH
    assert "error_detail" not in failed_step
    assert "SECRET_ERROR_DETAIL" not in serialized
    assert "SECRET_SOURCE_TEXT" not in serialized


def test_cx_processing_run_projection_handles_missing_and_unavailable_sources() -> None:
    projection = build_cx_processing_run_operations_projection(stores={})

    assert projection["projection_status"] == "DEGRADED"
    assert projection["source_statuses"]["nex-cx"]["status"] == "NOT_CONFIGURED"
    assert projection["summary"]["total"] == 0


def test_cx_processing_run_routes_require_auth_and_validate_filters() -> None:
    client = client_for_store(InMemoryCxProcessingRunOperationsStore(records=[processing_run()]))

    unauthorized = client.get("/admin/v1/operations/cx-processing-runs")
    invalid_service = client.get(
        "/admin/v1/operations/cx-processing-runs",
        params={"service_id": "nex-mo"},
        headers=auth_headers(),
    )
    invalid_status = client.get(
        "/admin/v1/operations/cx-processing-runs",
        params={"status": "BROKEN"},
        headers=auth_headers(),
    )
    invalid_cursor = client.get(
        "/admin/v1/operations/cx-processing-runs",
        params={"cursor": "-1"},
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_service.json()["error_code"] == "ag.cx_processing_run_service_invalid"
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error_code"] == "ag.cx_processing_run_status_invalid"
    assert invalid_cursor.status_code == 400


def test_cx_processing_run_routes_report_source_not_configured_and_dynamic_memory() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_cx_processing_run_operation_routes(app, stores={})
    configured_empty_client = TestClient(app)
    source_missing = configured_empty_client.get(
        f"/admin/v1/operations/cx-processing-runs/{PIPELINE_RUN_ID}",
        headers=auth_headers(),
    )

    dynamic_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_cx_processing_run_operation_routes(dynamic_app)
    dynamic_client = TestClient(dynamic_app)
    dynamic_list = dynamic_client.get(
        "/admin/v1/operations/cx-processing-runs",
        headers=auth_headers(),
    )
    dynamic_missing = dynamic_client.get(
        f"/admin/v1/operations/cx-processing-runs/{PIPELINE_RUN_ID}",
        headers=auth_headers(),
    )

    assert source_missing.status_code == 404
    assert source_missing.json()["error_code"] == (
        "ag.cx_processing_run_source_not_configured"
    )
    assert dynamic_list.status_code == 200
    assert dynamic_list.json()["projection_status"] == "READY"
    assert dynamic_missing.status_code == 404


def test_cx_processing_run_routes_return_list_detail_and_not_found() -> None:
    client = client_for_store(InMemoryCxProcessingRunOperationsStore(records=[processing_run()]))

    list_response = client.get(
        "/admin/v1/operations/cx-processing-runs",
        params={
            "service_id": "nex-cx",
            "document_id": DOCUMENT_ID,
            "status": "FAILED",
            "include_steps": "true",
            "limit": "5",
        },
        headers=auth_headers(),
    )
    detail_response = client.get(
        f"/admin/v1/operations/cx-processing-runs/{PIPELINE_RUN_ID}",
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing_response = client.get(
        "/admin/v1/operations/cx-processing-runs/missing-run",
        headers=auth_headers(),
    )

    list_body = list_response.json()
    detail_body = detail_response.json()
    assert list_response.status_code == 200
    assert list_body["processing_runs"][0]["steps_included"] is True
    assert list_body["processing_runs"][0]["steps"][1]["error_detail_sha256"] == ERROR_HASH
    assert detail_response.status_code == 200
    assert detail_body["processing_run"]["pipeline_run_id"] == PIPELINE_RUN_ID
    assert missing_response.status_code == 404
    assert missing_response.json()["error_code"] == "ag.cx_processing_run_not_found"


class BrokenProcessingStore:
    source_kind = "broken"
    database_env = "NEX_CX_TEST_DATABASE_URL"
    redacted_database_url = "postgresql://nex_cx_user:***@localhost/nex_cx_test"

    def list_processing_runs(self, **kwargs: object) -> list[dict[str, Any]]:
        raise CxProcessingRunOperationsError(
            error_code="ag.cx_processing_run_source_unavailable",
            detail="broken source",
        )

    def get_processing_run(self, *, pipeline_run_id: str) -> dict[str, Any] | None:
        raise CxProcessingRunOperationsError(
            error_code="ag.cx_processing_run_source_unavailable",
            detail="broken source",
        )


def test_cx_processing_run_source_errors_degrade_list_and_503_detail() -> None:
    store = BrokenProcessingStore()
    projection = build_cx_processing_run_operations_projection(stores={"nex-cx": store})
    client = client_for_store(store)
    detail_response = client.get(
        f"/admin/v1/operations/cx-processing-runs/{PIPELINE_RUN_ID}",
        headers=auth_headers(),
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert detail_response.status_code == 503
    assert detail_response.json()["error_code"] == "ag.cx_processing_run_source_unavailable"


def test_sqlalchemy_cx_processing_run_store_wraps_database_errors() -> None:
    class ExplodingSession:
        def __enter__(self) -> "ExplodingSession":
            raise SQLAlchemyError("database unavailable")

        def __exit__(self, *args: object) -> None:
            return None

    store = SqlAlchemyCxProcessingRunOperationsStore(lambda: ExplodingSession())

    with pytest.raises(CxProcessingRunOperationsError):
        store.list_processing_runs(document_id=DOCUMENT_ID)
    with pytest.raises(CxProcessingRunOperationsError):
        store.get_processing_run(pipeline_run_id=PIPELINE_RUN_ID)


def test_build_cx_processing_run_operation_stores_respects_memory_and_selected_services() -> None:
    memory = build_cx_processing_run_operation_stores(
        environ={
            "NEX_AG_OPERATIONS_SOURCE_MODE": "memory",
            "NEX_AG_OPERATIONS_SOURCE_SERVICES": "nex-cx",
        }
    )
    unselected = build_cx_processing_run_operation_stores(
        environ={
            "NEX_AG_OPERATIONS_SOURCE_MODE": "memory",
            "NEX_AG_OPERATIONS_SOURCE_SERVICES": "nex-mo",
        }
    )

    assert isinstance(memory["nex-cx"], InMemoryCxProcessingRunOperationsStore)
    assert unselected == {}


def test_build_cx_processing_run_operation_stores_builds_postgres_store() -> None:
    engine = object()
    seen: dict[str, object] = {}

    def fake_engine_factory(database_url: str, *, pool_settings: object) -> object:
        seen["database_url"] = database_url
        seen["pool_settings"] = pool_settings
        return engine

    def fake_session_factory_builder(received_engine: object) -> object:
        seen["engine"] = received_engine
        return lambda: None

    stores = build_cx_processing_run_operation_stores(
        environ={
            "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
            "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
            "NEX_AG_OPERATIONS_SOURCE_SERVICES": "nex-cx",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://user:secret@localhost/db",
        },
        engine_factory=fake_engine_factory,
        session_factory_builder=fake_session_factory_builder,
    )

    store = stores["nex-cx"]
    assert isinstance(store, SqlAlchemyCxProcessingRunOperationsStore)
    assert seen["database_url"] == "postgresql://user:secret@localhost/db"
    assert seen["engine"] is engine
    assert store.database_env == "NEX_CX_TEST_DATABASE_URL"
    assert store.redacted_database_url == "postgresql://user:***@localhost/db"


def test_sqlalchemy_cx_processing_run_operations_store_reads_sqlite_rows(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'ag-cx-processing.sqlite'}"
    engine = build_engine(database_url)
    create_sqlite_processing_tables(engine)
    seed_sqlite_processing_rows(engine)
    store = SqlAlchemyCxProcessingRunOperationsStore(
        build_session_factory(engine),
        database_env="NEX_CX_TEST_DATABASE_URL",
        redacted_database_url="sqlite:///***",
    )

    listed = store.list_processing_runs(
        document_id=DOCUMENT_ID,
        status="FAILED",
        trace_id=TRACE_ID,
        include_steps=True,
    )
    detail = store.get_processing_run(pipeline_run_id=PIPELINE_RUN_ID)
    missing = store.get_processing_run(pipeline_run_id="99999999-9999-4999-8999-999999999999")

    assert [run["pipeline_run_id"] for run in listed] == [PIPELINE_RUN_ID]
    assert listed[0]["steps"][1]["error_detail_sha256"] == ERROR_HASH
    assert listed[0]["job_subject_ref"] == {"type": "document", "id": DOCUMENT_ID}
    assert detail is not None
    assert detail["steps"][0]["output_ref_hash"] == OUTPUT_HASH
    assert missing is None


def test_processing_operations_helpers_cover_time_json_and_scalar_edges() -> None:
    records = [
        processing_run(
            pipeline_run_id="33333333-3333-4333-8333-333333333333",
            status="RUNNING",
        ),
        processing_run(),
    ]
    records[0]["updated_at"] = "2026-08-09T00:00:00Z"
    options = build_operation_query_options(
        since="2026-08-10T00:00:00Z",
        until="2026-08-10T00:03:00Z",
        sort="asc",
        limit=1,
    )

    filtered = processing_operations._filter_runs_by_time(records, options)
    page = processing_operations._apply_processing_run_query_options(filtered, options)

    assert [run["pipeline_run_id"] for run in filtered] == [PIPELINE_RUN_ID]
    assert page["pagination"]["returned"] == 1
    assert processing_operations._timestamp_to_wire_or_none(None) is None
    assert processing_operations._json_loads(None, default={"fallback": True}) == {
        "fallback": True
    }
    assert processing_operations._json_loads({"already": "mapping"}, default={}) == {
        "already": "mapping"
    }
    assert processing_operations._json_loads(b'{"from":"bytes"}', default={}) == {
        "from": "bytes"
    }
    assert processing_operations._json_loads(3, default={"fallback": True}) == {
        "fallback": True
    }
    assert processing_operations._mapping_value([]) == {}
    assert processing_operations._string_mapping({"a": 1}) == {"a": "1"}
    assert processing_operations._list_value(("not", "list")) == []
    assert processing_operations._int_value(True) == 0
    assert processing_operations._int_value("1") == 0
    assert processing_operations._nullable_bool(None) is None
    assert processing_operations._nullable_bool(0) is False
    assert processing_operations._nullable_bool("yes") is True
    assert processing_operations._nullable_bool([]) is False


def create_sqlite_processing_tables(engine: object) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_processing_runs (
                    pipeline_run_id TEXT PRIMARY KEY,
                    pipeline_schema_version TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    job_id TEXT,
                    job_type TEXT,
                    job_status TEXT,
                    job_attempt_count INTEGER NOT NULL,
                    job_max_attempts INTEGER NOT NULL,
                    job_retryable INTEGER,
                    job_subject_ref TEXT NOT NULL,
                    job_links TEXT NOT NULL,
                    step_total INTEGER NOT NULL,
                    step_succeeded INTEGER NOT NULL,
                    step_skipped INTEGER NOT NULL,
                    step_failed INTEGER NOT NULL,
                    queued_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_processing_steps (
                    pipeline_run_id TEXT NOT NULL,
                    step_order INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_ref_type TEXT,
                    output_ref_id TEXT,
                    output_ref_document_id TEXT,
                    output_ref_hash TEXT,
                    error_code TEXT,
                    error_detail_sha256 TEXT,
                    error_retryable INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
        )


def seed_sqlite_processing_rows(engine: object) -> None:
    run = processing_run()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO cx_document_processing_runs (
                    pipeline_run_id,
                    pipeline_schema_version,
                    document_id,
                    status,
                    trace_id,
                    request_id,
                    job_id,
                    job_type,
                    job_status,
                    job_attempt_count,
                    job_max_attempts,
                    job_retryable,
                    job_subject_ref,
                    job_links,
                    step_total,
                    step_succeeded,
                    step_skipped,
                    step_failed,
                    queued_at,
                    started_at,
                    completed_at,
                    updated_at
                )
                VALUES (
                    :pipeline_run_id,
                    :pipeline_schema_version,
                    :document_id,
                    :status,
                    :trace_id,
                    :request_id,
                    :job_id,
                    :job_type,
                    :job_status,
                    :job_attempt_count,
                    :job_max_attempts,
                    :job_retryable,
                    :job_subject_ref,
                    :job_links,
                    :step_total,
                    :step_succeeded,
                    :step_skipped,
                    :step_failed,
                    :queued_at,
                    :started_at,
                    :completed_at,
                    :updated_at
                )
                """
            ),
            {
                **{key: run[key] for key in run if key != "steps"},
                "job_retryable": 1,
                "job_subject_ref": '{"type":"document","id":"' + DOCUMENT_ID + '"}',
                "job_links": '{"processing":"/api/v1/documents/' + DOCUMENT_ID + '/processing"}',
            },
        )
        for step in run["steps"]:
            connection.execute(
                text(
                    """
                    INSERT INTO cx_document_processing_steps (
                        pipeline_run_id,
                        step_order,
                        step_id,
                        status,
                        output_ref_type,
                        output_ref_id,
                        output_ref_document_id,
                        output_ref_hash,
                        error_code,
                        error_detail_sha256,
                        error_retryable,
                        created_at
                    )
                    VALUES (
                        :pipeline_run_id,
                        :step_order,
                        :step_id,
                        :status,
                        :output_ref_type,
                        :output_ref_id,
                        :output_ref_document_id,
                        :output_ref_hash,
                        :error_code,
                        :error_detail_sha256,
                        :error_retryable,
                        :created_at
                    )
                    """
                ),
                {
                    **step,
                    "error_retryable": (
                        1 if step["error_retryable"] is True else step["error_retryable"]
                    ),
                },
            )
