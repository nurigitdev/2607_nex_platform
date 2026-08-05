from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from nex_ag.operations import (
    AG_OPERATIONS_SOURCE_MODE_ENV,
    AG_OPERATIONS_SOURCE_PROFILE_ENV,
    AG_OPERATIONS_SOURCE_SERVICES_ENV,
    OperationsQueryError,
    OperationsSourceConfigError,
    OperationsSource,
    OperationsSourceRegistry,
    RegistryOperationalEventStore,
    ReadOnlyJobQueue,
    ReadOnlyOperationalEventStore,
    ag_operations_source_database_env,
    attach_ag_operations_source_runtime,
    build_ag_operations_source_runtime,
    build_cross_service_trace_timeline_projection,
    build_job_operation_detail_projection,
    build_job_operations_projection,
    build_operation_query_options,
    build_operation_source_readiness_projection,
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
    build_operations_rollup_metrics_projection,
    build_operations_source_registry,
    build_operational_event_detail_projection,
    build_operational_event_taxonomy_projection,
    build_operational_event_projection,
    build_unified_operations_projection,
    normalize_operation_event_search_query,
    normalize_operation_cursor,
    normalize_operation_sort,
    normalize_operation_timestamp,
    normalize_ag_operations_source_mode,
    normalize_ag_operations_source_profile,
    normalize_dashboard_recent_limit,
    operations_issue_candidate_rules,
    register_job_operation_routes,
    register_operation_source_readiness_routes,
    register_operational_event_taxonomy_routes,
    register_operational_event_routes,
    register_unified_operation_routes,
    select_ag_operations_source_service_ids,
    summarize_operation_source_readiness,
    summarize_job_operations,
    summarize_operations_issue_candidates,
    summarize_operations_rollup_metrics,
    summarize_trace_timeline_items,
    _filter_records_by_operation_time,
    _operation_record_timestamp,
)
from nex_runtime import (
    CX_PROCESSING_EVENT_FAILED,
    CX_PROCESSING_EVENT_STARTED,
    FAILED,
    InMemoryOperationalEventStore,
    InMemoryJobQueue,
    JobQueueError,
    OperationalEventError,
    RUNNING,
    SERVICE_SPECS,
    SUCCEEDED,
    build_common_job,
    build_operational_event,
    build_service_app,
    build_subject_ref,
    issue_mock_service_token,
    normalize_job_limit,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
CONTRACT_ROOT = Path(__file__).parents[1] / "contracts"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {"Authorization": f"Bearer {issued.access_token}"}


def ag_operations_projection_schema() -> dict[str, object]:
    schema_path = (
        CONTRACT_ROOT
        / "schemas"
        / "service"
        / "nex_ag"
        / "operations_projection.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def assert_ag_operations_projection_contract(payload: dict[str, object]) -> None:
    Draft202012Validator(ag_operations_projection_schema()).validate(payload)


def build_store() -> InMemoryOperationalEventStore:
    store = InMemoryOperationalEventStore()
    store.append(
        build_operational_event(
            event_id="event-001",
            service_id="nex-cx",
            event_type="cx.processing.completed",
            severity="INFO",
            message="Document processing completed.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "cx.document", "id": "doc-001"},
            details={"pipeline_run_id": "run-001"},
            created_at="2026-08-05T00:00:00Z",
        )
    )
    store.append(
        build_operational_event(
            event_id="event-002",
            service_id="nex-mo",
            event_type="mo.provider.failed",
            severity="ERROR",
            message="Provider request failed.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            subject_ref={"type": "mo.provider", "id": "embedding"},
            details={"authorization": "Bearer private"},
            created_at="2026-08-05T00:00:01Z",
        )
    )
    return store


def sample_job(**overrides):
    return build_common_job(
        job_id=overrides.pop("job_id", "job-001"),
        job_type=overrides.pop("job_type", "cx.document_processing"),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        subject_ref=overrides.pop("subject_ref", build_subject_ref("cx.document", "doc-001")),
        idempotency_key=overrides.pop("idempotency_key", "idem-001"),
        created_at=overrides.pop("created_at", "2026-08-05T00:00:00Z"),
        max_attempts=overrides.pop("max_attempts", 2),
        status=overrides.pop("status", "QUEUED"),
        **overrides,
    )


def build_job_queues() -> dict[str, InMemoryJobQueue]:
    cx_queue = InMemoryJobQueue()
    cx_queue.enqueue(
        sample_job(
            job_id="job-cx-001",
            idempotency_key="idem-cx-001",
            created_at="2026-08-05T00:00:00Z",
        )
    )
    cx_running = cx_queue.start_job(
        "job-cx-001",
        updated_at="2026-08-05T00:00:03Z",
    )
    assert cx_running["status"] == RUNNING
    cx_queue.enqueue(
        sample_job(
            job_id="job-cx-002",
            idempotency_key="idem-cx-002",
            created_at="2026-08-05T00:00:01Z",
        )
    )
    cx_queue.fail_job(
        cx_queue.start_job("job-cx-002", updated_at="2026-08-05T00:00:04Z")["job_id"],
        updated_at="2026-08-05T00:00:05Z",
    )

    ae_queue = InMemoryJobQueue()
    ae_queue.enqueue(
        sample_job(
            job_id="job-ae-001",
            job_type="ae.artifact_render",
            subject_ref=build_subject_ref("ae.artifact", "artifact-001"),
            idempotency_key="idem-ae-001",
            created_at="2026-08-05T00:00:02Z",
        )
    )
    ae_queue.complete_job(
        ae_queue.start_job("job-ae-001", updated_at="2026-08-05T00:00:06Z")["job_id"],
        updated_at="2026-08-05T00:00:07Z",
    )
    return {
        "nex-cx": cx_queue,
        "nex-ae-api": ae_queue,
    }


class BrokenJobQueue:
    def list_jobs(self, *, job_type=None, status=None):
        raise JobQueueError(
            error_code="job.store_unavailable",
            detail="job queue store is unavailable",
            status_code=503,
        )

    def enqueue(self, job):
        raise AssertionError("not used")

    def get_job(self, job_id):
        raise AssertionError("not used")

    def start_job(self, job_id, *, updated_at=None):
        raise AssertionError("not used")

    def complete_job(self, job_id, *, updated_at=None):
        raise AssertionError("not used")

    def fail_job(self, job_id, *, updated_at=None):
        raise AssertionError("not used")

    def cancel_job(self, job_id, *, updated_at=None):
        raise AssertionError("not used")

    def claim_next_job(self, worker_id, *, job_type=None, updated_at=None):
        raise AssertionError("not used")


class UnavailableJobQueue(BrokenJobQueue):
    def get_job(self, job_id):
        raise JobQueueError(
            error_code="job.store_unavailable",
            detail="job queue store is unavailable",
            status_code=503,
        )


class BrokenOperationalEventStore:
    def append(self, event):
        raise AssertionError("not used")

    def get_event(self, event_id):
        raise AssertionError("not used")

    def list_events(self, **kwargs):
        raise OperationalEventError(
            error_code="operational_event.store_unavailable",
            detail="operational event store is unavailable",
            status_code=503,
        )


def build_event_stores() -> dict[str, InMemoryOperationalEventStore]:
    cx_store = InMemoryOperationalEventStore()
    cx_store.append(
        build_operational_event(
            event_id="event-cx-001",
            service_id="nex-cx",
            event_type="cx.processing.succeeded",
            severity="INFO",
            message="Document processing succeeded.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "cx.document", "id": "doc-001"},
            details={"pipeline_run_id": "run-001"},
            created_at="2026-08-05T00:00:00Z",
        )
    )
    mo_store = InMemoryOperationalEventStore()
    mo_store.append(
        build_operational_event(
            event_id="event-mo-001",
            service_id="nex-mo",
            event_type="mo.provider.failed",
            severity="ERROR",
            message="Provider request failed.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            subject_ref={"type": "mo.provider", "id": "reranker"},
            details={"service_token": "private"},
            created_at="2026-08-05T00:00:01Z",
        )
    )
    return {"nex-cx": cx_store, "nex-mo": mo_store}


def test_ag_operations_source_config_helpers_normalize_runtime_inputs() -> None:
    assert normalize_ag_operations_source_mode(None) == "memory"
    assert normalize_ag_operations_source_mode("postgresql") == "postgres"
    assert normalize_ag_operations_source_profile(None) == "dev"
    assert normalize_ag_operations_source_profile("TEST") == "test"
    assert ag_operations_source_database_env("nex-cx") == "NEX_CX_DATABASE_URL"
    assert (
        ag_operations_source_database_env("nex-cx", profile="test")
        == "NEX_CX_TEST_DATABASE_URL"
    )
    assert select_ag_operations_source_service_ids("nex-cx,nex-ae-api,nex-cx") == (
        "nex-ae-api",
        "nex-cx",
    )
    assert select_ag_operations_source_service_ids(None) == tuple(sorted(SERVICE_SPECS))


def test_operation_query_options_normalize_sort_cursor_and_timestamps() -> None:
    options = build_operation_query_options(
        limit=9999,
        since="2026-08-05T00:00:00+09:00",
        until="2026-08-05T00:00:01Z",
        sort="ASC",
        cursor="002",
    )

    assert options.limit == 500
    assert options.since == "2026-08-04T15:00:00Z"
    assert options.until == "2026-08-05T00:00:01Z"
    assert options.sort == "asc"
    assert options.cursor == "2"
    assert options.offset == 2
    assert options.to_filter_dict() == {
        "limit": 500,
        "since": "2026-08-04T15:00:00Z",
        "until": "2026-08-05T00:00:01Z",
        "sort": "asc",
        "cursor": "2",
    }
    assert options.pagination(total=4, returned=2)["next_cursor"] is None


@pytest.mark.parametrize(
    "operation, expected_code",
    [
        (lambda: normalize_operation_sort("latest"), "ag.operation_sort_invalid"),
        (lambda: normalize_operation_cursor("-1"), "ag.operation_cursor_invalid"),
        (lambda: normalize_operation_cursor("abc"), "ag.operation_cursor_invalid"),
        (
            lambda: normalize_operation_timestamp("not-a-date", field_name="since"),
            "ag.operation_timestamp_invalid",
        ),
        (
            lambda: build_operation_query_options(
                limit=10,
                since="2026-08-05T00:00:02Z",
                until="2026-08-05T00:00:01Z",
            ),
            "ag.operation_time_window_invalid",
        ),
    ],
)
def test_operation_query_options_reject_invalid_inputs(operation, expected_code) -> None:
    with pytest.raises(OperationsQueryError) as exc_info:
        operation()

    assert exc_info.value.error_code == expected_code


def test_operation_query_helpers_cover_timestamp_fallback_edges() -> None:
    options = build_operation_query_options(
        limit=10,
        since="2026-08-05T00:00:00",
        until="2026-08-05T00:00:01Z",
    )
    records = [
        {"record_id": "missing"},
        {"record_id": "fallback", "created_at": "2026-08-05T00:00:01Z"},
        {"record_id": "too-new", "updated_at": "2026-08-05T00:00:02Z"},
    ]

    assert options.since == "2026-08-05T00:00:00Z"
    assert _operation_record_timestamp(
        {"created_at": "2026-08-05T00:00:01Z"},
        timestamp_field="updated_at",
    ).isoformat().endswith("+00:00")
    assert _operation_record_timestamp({}, timestamp_field="updated_at").year == 1
    assert [
        record["record_id"]
        for record in _filter_records_by_operation_time(
            records,
            options,
            timestamp_field="updated_at",
        )
    ] == ["fallback"]


@pytest.mark.parametrize(
    "operation",
    [
        lambda queue, job: queue.enqueue(job),
        lambda queue, job: queue.start_job(job["job_id"]),
        lambda queue, job: queue.complete_job(job["job_id"]),
        lambda queue, job: queue.fail_job(job["job_id"]),
        lambda queue, job: queue.cancel_job(job["job_id"]),
        lambda queue, job: queue.claim_next_job("ag-reader"),
    ],
)
def test_read_only_job_queue_allows_reads_and_rejects_writes(operation) -> None:
    delegate = InMemoryJobQueue()
    job = delegate.enqueue(
        sample_job(
            job_id="job-read-only-001",
            idempotency_key="idem-read-only-001",
        )
    )
    queue = ReadOnlyJobQueue(delegate)

    assert queue.get_job("job-read-only-001") == job
    assert [stored["job_id"] for stored in queue.list_jobs()] == ["job-read-only-001"]
    with pytest.raises(JobQueueError, match="read-only"):
        operation(queue, job)


def test_read_only_operational_event_store_allows_reads_and_rejects_append() -> None:
    delegate = build_event_stores()["nex-cx"]
    store = ReadOnlyOperationalEventStore(delegate)

    event = store.get_event("event-cx-001")
    assert event is not None
    assert event["event_id"] == "event-cx-001"
    assert [stored["event_id"] for stored in store.list_events(service_id="nex-cx")] == [
        "event-cx-001"
    ]
    with pytest.raises(OperationalEventError, match="read-only"):
        store.append(event)


def test_ag_operations_source_runtime_defaults_to_memory_without_registry() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])

    runtime = attach_ag_operations_source_runtime(app, environ={})

    assert runtime.mode == "memory"
    assert runtime.profile == "dev"
    assert runtime.registry is None
    assert app.state.nex_ag_operations_source_runtime is runtime
    assert runtime.to_summary()["registry"] is None


def test_ag_operations_source_runtime_builds_postgres_read_only_registry() -> None:
    engine_calls: list[dict[str, str]] = []
    session_calls: list[object] = []

    def fake_engine_factory(database_url: str, *, pool_settings: object) -> object:
        engine_calls.append(
            {
                "database_url": database_url,
                "service_id": pool_settings.service_id,
                "workload": pool_settings.workload,
            }
        )
        return SimpleNamespace(database_url=database_url, pool_settings=pool_settings)

    def fake_session_factory_builder(engine: object) -> object:
        session_calls.append(engine)
        return f"session:{engine.pool_settings.service_id}:{engine.pool_settings.workload}"

    runtime = build_ag_operations_source_runtime(
        environ={
            AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
            AG_OPERATIONS_SOURCE_PROFILE_ENV: "test",
            AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx,nex-ae-api,nex-cx",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
            "NEX_AE_TEST_DATABASE_URL": "postgresql://nex_ae_user:secret@localhost/nex_ae_test",
        },
        engine_factory=fake_engine_factory,
        session_factory_builder=fake_session_factory_builder,
    )

    assert runtime.mode == "postgres"
    assert runtime.profile == "test"
    assert runtime.selected_service_ids == ("nex-ae-api", "nex-cx")
    assert runtime.registry is not None
    assert [call["service_id"] for call in engine_calls] == [
        "nex-ae-api",
        "nex-ae-api",
        "nex-cx",
        "nex-cx",
    ]
    assert [call["workload"] for call in engine_calls] == [
        "api",
        "worker",
        "api",
        "worker",
    ]
    assert len(session_calls) == 4

    source = runtime.registry.get("nex-cx")
    assert source is not None
    assert source.source_kind == "postgres-read"
    assert source.database_env == "NEX_CX_TEST_DATABASE_URL"
    assert source.to_summary()["redacted_database_url"].endswith(
        "nex_cx_user:***@localhost/nex_cx_test"
    )
    assert isinstance(source.job_queue, ReadOnlyJobQueue)
    assert isinstance(source.operational_event_store, ReadOnlyOperationalEventStore)
    with pytest.raises(JobQueueError, match="read-only"):
        source.job_queue.enqueue(
            sample_job(
                job_id="job-runtime-read-only",
                idempotency_key="idem-runtime-read-only",
            )
        )


def test_operation_source_readiness_projection_reports_default_memory_runtime() -> None:
    runtime = build_ag_operations_source_runtime(environ={})

    projection = build_operation_source_readiness_projection(
        runtime=runtime,
        service_id="nex-cx",
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operation_source_readiness_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["runtime"]["mode"] == "memory"
    assert projection["sources"] == [
        {
            "service_id": "nex-cx",
            "readiness_status": "DEFAULT_MEMORY",
            "configured": False,
            "source_kind": "memory-default",
            "capabilities": {
                "jobs": True,
                "events": True,
            },
            "read_only": False,
            "job_queue": "InMemoryJobQueue",
            "operational_event_store": "InMemoryOperationalEventStore",
            "database_env": None,
            "redacted_database_url": None,
        }
    ]
    assert projection["summary"] == {
        "total": 1,
        "by_status": {"DEFAULT_MEMORY": 1},
        "by_source_kind": {"memory-default": 1},
        "read_only": 0,
    }


def test_operation_source_readiness_projection_reports_postgres_sources() -> None:
    runtime = build_ag_operations_source_runtime(
        environ={
            AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
            AG_OPERATIONS_SOURCE_PROFILE_ENV: "test",
            AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        },
        engine_factory=lambda database_url, *, pool_settings: SimpleNamespace(
            database_url=database_url,
            pool_settings=pool_settings,
        ),
        session_factory_builder=lambda engine: f"session:{engine.pool_settings.workload}",
    )

    projection = build_operation_source_readiness_projection(runtime=runtime)

    assert projection["runtime"]["profile"] == "test"
    assert projection["sources"][0]["service_id"] == "nex-cx"
    assert projection["sources"][0]["readiness_status"] == "READY"
    assert projection["sources"][0]["source_kind"] == "postgres-read"
    assert projection["sources"][0]["read_only"] is True
    assert projection["sources"][0]["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert projection["sources"][0]["redacted_database_url"].endswith(
        "nex_cx_user:***@localhost/nex_cx_test"
    )
    assert projection["summary"]["read_only"] == 1
    assert "secret" not in str(projection)


def test_operation_source_readiness_projection_reports_not_configured_registry_source() -> None:
    runtime = build_ag_operations_source_runtime(
        environ={
            AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
            AG_OPERATIONS_SOURCE_PROFILE_ENV: "test",
            AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        },
        engine_factory=lambda database_url, *, pool_settings: SimpleNamespace(
            database_url=database_url,
            pool_settings=pool_settings,
        ),
        session_factory_builder=lambda engine: f"session:{engine.pool_settings.workload}",
    )

    projection = build_operation_source_readiness_projection(
        runtime=runtime,
        service_id="nex-mo",
    )

    assert projection["sources"][0]["readiness_status"] == "NOT_CONFIGURED"
    assert projection["sources"][0]["read_only"] is None
    assert projection["summary"]["by_status"] == {"NOT_CONFIGURED": 1}


def test_summarize_operation_source_readiness_counts_empty_sources() -> None:
    assert summarize_operation_source_readiness([]) == {
        "total": 0,
        "by_status": {},
        "by_source_kind": {},
        "read_only": 0,
    }


@pytest.mark.parametrize(
    "environ, expected",
    [
        ({AG_OPERATIONS_SOURCE_MODE_ENV: "filesystem"}, "unsupported AG operations source mode"),
        ({AG_OPERATIONS_SOURCE_PROFILE_ENV: "prod"}, "unsupported AG operations source profile"),
        (
            {AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx,nex-unknown"},
            "unknown AG operations source services",
        ),
        (
            {AG_OPERATIONS_SOURCE_SERVICES_ENV: ", ,"},
            "selected no services",
        ),
        (
            {
                AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
                AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
            },
            "missing database URL env NEX_CX_DATABASE_URL",
        ),
        (
            {
                AG_OPERATIONS_SOURCE_MODE_ENV: "postgres",
                AG_OPERATIONS_SOURCE_SERVICES_ENV: "nex-cx",
                "NEX_CX_DATABASE_URL": "postgresql://nex_cx_user:<password>@localhost/nex_cx_dev",
            },
            "placeholder password",
        ),
    ],
)
def test_ag_operations_source_runtime_rejects_invalid_config(
    environ: dict[str, str],
    expected: str,
) -> None:
    with pytest.raises(OperationsSourceConfigError, match=expected):
        build_ag_operations_source_runtime(environ=environ)


def test_ag_operations_source_database_env_rejects_unknown_service() -> None:
    with pytest.raises(OperationsSourceConfigError, match="unknown AG operations source"):
        ag_operations_source_database_env("nex-unknown")


def test_operations_source_registry_registers_sources_and_reports_capabilities() -> None:
    job_queues = build_job_queues()
    event_stores = build_event_stores()
    registry = build_operations_source_registry(
        job_queues=job_queues,
        event_stores=event_stores,
        source_kind="memory-test",
    )

    assert registry.service_ids() == ["nex-ae-api", "nex-cx", "nex-mo"]
    assert registry.get("nex-cx").job_queue is job_queues["nex-cx"]
    assert registry.get("nex-cx").operational_event_store is event_stores["nex-cx"]
    assert sorted(registry.job_queues()) == ["nex-ae-api", "nex-cx"]
    assert sorted(registry.event_stores()) == ["nex-cx", "nex-mo"]
    assert registry.to_summary()["registry_schema_version"] == "ag_operations_source_registry.v1"
    assert registry.to_summary()["sources"]["nex-mo"]["capabilities"] == {
        "jobs": False,
        "events": True,
    }


def test_operations_source_registry_rejects_unknown_or_empty_source_shapes() -> None:
    registry = OperationsSourceRegistry()

    try:
        OperationsSource(service_id="nex-unknown")
    except ValueError as exc:
        assert "unsupported operations source service" in str(exc)
    else:
        raise AssertionError("expected unknown service failure")

    try:
        OperationsSource(service_id="nex-cx", source_kind="")
    except ValueError as exc:
        assert "source_kind" in str(exc)
    else:
        raise AssertionError("expected empty source kind failure")

    try:
        OperationsSource(service_id="nex-cx", database_env="")
    except ValueError as exc:
        assert "database_env" in str(exc)
    else:
        raise AssertionError("expected empty database env failure")

    try:
        OperationsSource(service_id="nex-cx", redacted_database_url="")
    except ValueError as exc:
        assert "redacted_database_url" in str(exc)
    else:
        raise AssertionError("expected empty redacted database url failure")

    try:
        registry.get("nex-unknown")
    except ValueError as exc:
        assert "unsupported operations source service" in str(exc)
    else:
        raise AssertionError("expected unknown registry lookup failure")


def test_registry_operational_event_store_aggregates_and_filters_events() -> None:
    registry = build_operations_source_registry(event_stores=build_event_stores())
    registry_store = RegistryOperationalEventStore(registry)

    events = registry_store.list_events(limit=10)
    cx_events = registry_store.list_events(service_id="nex-cx", limit=10)
    missing = registry_store.list_events(service_id="nex-ag", limit=10)
    mo_event = registry_store.get_event("event-mo-001")
    absent_event = registry_store.get_event("event-missing")

    assert [event["event_id"] for event in events] == ["event-mo-001", "event-cx-001"]
    assert [event["event_id"] for event in cx_events] == ["event-cx-001"]
    assert missing == []
    assert mo_event is not None
    assert mo_event["details"]["service_token"] == "<redacted>"
    assert absent_event is None
    assert "private" not in str(events)

    try:
        registry_store.append(build_store().list_events(limit=1)[0])
    except Exception as exc:
        assert getattr(exc, "error_code") == "ag.operations_registry.read_only"
    else:
        raise AssertionError("expected read-only registry append failure")


def test_operations_routes_accept_source_registry() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, registry=registry)
    register_job_operation_routes(app, registry=registry)
    client = TestClient(app)

    events_response = client.get(
        "/admin/v1/operations/events",
        params={"service_id": "nex-mo", "severity": "ERROR"},
        headers=auth_headers(),
    )
    jobs_response = client.get(
        "/admin/v1/operations/jobs",
        params={"service_id": "nex-ae-api"},
        headers=auth_headers(),
    )

    assert events_response.status_code == 200
    assert events_response.json()["events"][0]["event_id"] == "event-mo-001"
    assert jobs_response.status_code == 200
    assert jobs_response.json()["jobs"][0]["job_id"] == "job-ae-001"


def test_operation_source_readiness_route_requires_auth_and_filters_service() -> None:
    runtime = build_ag_operations_source_runtime(environ={})
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operation_source_readiness_routes(app, runtime=runtime)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/sources")
    response = client.get(
        "/admin/v1/operations/sources",
        params={"service_id": "nex-cx"},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"] == {"service_id": "nex-cx"}
    assert payload["sources"][0]["service_id"] == "nex-cx"
    assert payload["sources"][0]["readiness_status"] == "DEFAULT_MEMORY"


def test_operation_source_readiness_route_reads_runtime_from_app_state() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    runtime = attach_ag_operations_source_runtime(app, environ={})
    register_operation_source_readiness_routes(app)

    response = TestClient(app).get(
        "/admin/v1/operations/sources",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["runtime"] == runtime.to_summary()


def test_operation_source_readiness_route_rejects_bad_service() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operation_source_readiness_routes(app)

    response = TestClient(app).get(
        "/admin/v1/operations/sources",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ag.operation_source_service_invalid"


def test_build_unified_operations_projection_combines_jobs_events_and_registry_summary() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )

    projection = build_unified_operations_projection(
        registry=registry,
        service_id="nex-cx",
        job_status="running",
        event_severity="info",
        limit=9999,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == "ag_unified_operations_projection.v1"
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "job_status": RUNNING,
        "job_type": None,
        "event_severity": "INFO",
        "event_type": None,
        "trace_id": None,
        "limit": 500,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert [job["job_id"] for job in projection["jobs"]["jobs"]] == ["job-cx-001"]
    assert [event["event_id"] for event in projection["events"]["events"]] == [
        "event-cx-001"
    ]
    assert projection["summary"]["jobs"]["statuses"][RUNNING] == 1
    assert projection["summary"]["events"]["by_severity"]["INFO"] == 1
    assert projection["source_registry"]["service_count"] == 3
    assert projection["pagination"]["jobs"]["total_after_filters"] == 1
    assert projection["pagination"]["events"]["total_after_filters"] == 1


def test_build_unified_operations_projection_supports_direct_injection_and_degraded_jobs() -> None:
    projection = build_unified_operations_projection(
        job_queues={
            **build_job_queues(),
            "nex-mo": BrokenJobQueue(),
        },
        event_store=build_store(),
        limit=2,
    )

    assert projection["projection_status"] == "DEGRADED"
    assert [job["job_id"] for job in projection["jobs"]["jobs"]] == [
        "job-ae-001",
        "job-cx-002",
    ]
    assert [event["event_id"] for event in projection["events"]["events"]] == [
        "event-002",
        "event-001",
    ]
    assert "source_registry" not in projection


def test_unified_operations_projection_applies_time_window_sort_and_cursor() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    options = build_operation_query_options(
        limit=1,
        since="2026-08-05T00:00:01Z",
        sort="asc",
    )

    projection = build_unified_operations_projection(
        registry=registry,
        query_options=options,
    )

    assert projection["filters"]["since"] == "2026-08-05T00:00:01Z"
    assert projection["filters"]["sort"] == "asc"
    assert [job["job_id"] for job in projection["jobs"]["jobs"]] == ["job-cx-001"]
    assert projection["pagination"]["jobs"]["next_cursor"] == "1"
    assert [event["event_id"] for event in projection["events"]["events"]] == [
        "event-mo-001"
    ]
    assert projection["pagination"]["events"]["next_cursor"] is None


def test_unified_operations_route_requires_auth_and_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations")
    response = client.get(
        "/admin/v1/operations",
        params={
            "service_id": "nex-cx",
            "job_status": "RUNNING",
            "event_severity": "INFO",
        },
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["jobs"]["jobs"][0]["job_id"] == "job-cx-001"
    assert payload["events"]["events"][0]["event_id"] == "event-cx-001"


def test_build_operations_rollup_metrics_projection_summarizes_sources() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )

    projection = build_operations_rollup_metrics_projection(
        registry=registry,
        service_id="nex-cx",
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operations_rollup_metrics_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "since": None,
        "until": None,
    }
    assert projection["rollups"] == [
        {
            "service_id": "nex-cx",
            "jobs": {
                "total": 2,
                "active": 1,
                "terminal": 1,
                "statuses": {
                    "QUEUED": 0,
                    "RUNNING": 1,
                    "SUCCEEDED": 0,
                    "FAILED": 1,
                    "CANCELLED": 0,
                },
                "by_job_type": {"cx.document_processing": 2},
            },
            "events": {
                "total": 1,
                "by_severity": {
                    "DEBUG": 0,
                    "INFO": 1,
                    "WARNING": 0,
                    "ERROR": 0,
                    "CRITICAL": 0,
                },
                "by_event_type": {"cx.processing.succeeded": 1},
            },
            "source_status": {
                "jobs": "READY",
                "events": "READY",
            },
        }
    ]
    assert projection["summary"]["jobs"]["total"] == 2
    assert projection["summary"]["events"]["total"] == 1
    assert projection["summary"]["source_statuses"] == {
        "jobs": {"READY": 1},
        "events": {"READY": 1},
    }
    assert projection["job_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "job_count": 2,
    }
    assert projection["event_source_statuses"]["nex-cx"] == {
        "status": "READY",
        "event_count": 1,
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_rollup_metrics_projection_applies_time_window() -> None:
    projection = build_operations_rollup_metrics_projection(
        registry=build_operations_source_registry(
            job_queues=build_job_queues(),
            event_stores=build_event_stores(),
        ),
        service_id="nex-cx",
        query_options=build_operation_query_options(
            limit=500,
            since="2026-08-05T00:00:04Z",
        ),
    )

    assert projection["filters"]["since"] == "2026-08-05T00:00:04Z"
    assert projection["rollups"][0]["jobs"]["total"] == 1
    assert projection["rollups"][0]["jobs"]["statuses"][FAILED] == 1
    assert projection["rollups"][0]["events"]["total"] == 0
    assert projection["summary"]["jobs"]["by_service"] == {"nex-cx": 1}
    assert projection["summary"]["events"]["by_service"] == {"nex-cx": 0}


def test_operations_rollup_metrics_projection_reports_degraded_sources() -> None:
    not_configured = build_operations_rollup_metrics_projection(
        registry=build_operations_source_registry(event_stores=build_event_stores()),
        service_id="nex-mo",
    )
    missing_events = build_operations_rollup_metrics_projection(
        registry=build_operations_source_registry(job_queues=build_job_queues()),
        service_id="nex-ae-api",
    )
    unavailable = build_operations_rollup_metrics_projection(
        job_queues={"nex-cx": BrokenJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_id="nex-cx",
    )

    assert not_configured["projection_status"] == "DEGRADED"
    assert not_configured["job_source_statuses"]["nex-mo"] == {
        "status": "NOT_CONFIGURED",
        "job_count": 0,
    }
    assert not_configured["event_source_statuses"]["nex-mo"]["status"] == "READY"
    assert missing_events["projection_status"] == "DEGRADED"
    assert missing_events["job_source_statuses"]["nex-ae-api"]["status"] == "READY"
    assert missing_events["event_source_statuses"]["nex-ae-api"] == {
        "status": "NOT_CONFIGURED",
        "event_count": 0,
    }
    assert unavailable["projection_status"] == "DEGRADED"
    assert unavailable["rollups"][0]["jobs"]["total"] == 0
    assert unavailable["rollups"][0]["events"]["total"] == 0
    assert unavailable["job_source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert unavailable["event_source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert unavailable["summary"]["source_statuses"] == {
        "jobs": {"UNAVAILABLE": 1},
        "events": {"UNAVAILABLE": 1},
    }
    assert_ag_operations_projection_contract(unavailable)


def test_summarize_operations_rollup_metrics_counts_empty() -> None:
    assert summarize_operations_rollup_metrics([]) == {
        "service_count": 0,
        "jobs": {
            "total": 0,
            "active": 0,
            "terminal": 0,
            "statuses": {
                "QUEUED": 0,
                "RUNNING": 0,
                "SUCCEEDED": 0,
                "FAILED": 0,
                "CANCELLED": 0,
            },
            "by_service": {},
        },
        "events": {
            "total": 0,
            "by_severity": {
                "DEBUG": 0,
                "INFO": 0,
                "WARNING": 0,
                "ERROR": 0,
                "CRITICAL": 0,
            },
            "by_service": {},
        },
        "source_statuses": {
            "jobs": {},
            "events": {},
        },
    }


def test_operations_rollup_metrics_route_requires_auth_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/rollups")
    response = client.get(
        "/admin/v1/operations/rollups",
        params={"service_id": "nex-cx"},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["projection_status"] == "READY"
    assert payload["rollups"][0]["service_id"] == "nex-cx"
    assert payload["summary"]["jobs"]["total"] == 2


def test_operations_rollup_metrics_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/rollups",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_window = client.get(
        "/admin/v1/operations/rollups",
        params={
            "since": "2026-08-05T00:00:02Z",
            "until": "2026-08-05T00:00:01Z",
        },
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_window.status_code == 400
    assert bad_window.json()["error_code"] == "ag.operation_time_window_invalid"


def test_build_operations_dashboard_snapshot_projection_combines_sections() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    runtime = build_ag_operations_source_runtime(environ={})

    projection = build_operations_dashboard_snapshot_projection(
        registry=registry,
        runtime=runtime,
        service_id="nex-cx",
        recent_limit=1,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operations_dashboard_snapshot_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "since": None,
        "until": None,
        "recent_limit": 1,
    }
    assert projection["source_readiness_summary"]["total"] == 1
    assert projection["operation_sources"][0]["service_id"] == "nex-cx"
    assert projection["rollup_summary"]["jobs"]["total"] == 2
    assert projection["rollups"][0]["events"]["total"] == 1
    assert [job["job_id"] for job in projection["recent_failures"]["jobs"]] == [
        "job-cx-002"
    ]
    assert projection["recent_failures"]["events"] == []
    assert [job["job_id"] for job in projection["active_jobs"]] == ["job-cx-001"]
    assert projection["degraded_sources"] == []
    assert_ag_operations_projection_contract(projection)


def test_operations_dashboard_snapshot_reports_degraded_sources_and_failure_events() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )

    projection = build_operations_dashboard_snapshot_projection(
        registry=registry,
        recent_limit=2,
    )

    assert projection["projection_status"] == "DEGRADED"
    assert [event["event_id"] for event in projection["recent_failures"]["events"]] == [
        "event-mo-001"
    ]
    assert [job["job_id"] for job in projection["recent_failures"]["jobs"]] == [
        "job-cx-002"
    ]
    assert [job["job_id"] for job in projection["active_jobs"]] == ["job-cx-001"]
    assert {
        (source["source_type"], source["service_id"], source["status"])
        for source in projection["degraded_sources"]
    } >= {
        ("readiness", "nex-oa", "NOT_CONFIGURED"),
        ("jobs", "nex-mo", "NOT_CONFIGURED"),
        ("events", "nex-ae-api", "NOT_CONFIGURED"),
    }
    assert projection["rollup_summary"]["source_statuses"]["jobs"] == {
        "READY": 2,
        "NOT_CONFIGURED": 3,
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_dashboard_snapshot_handles_unavailable_candidate_sources() -> None:
    projection = build_operations_dashboard_snapshot_projection(
        job_queues={"nex-cx": BrokenJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_id="nex-cx",
        recent_limit=999,
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["filters"]["recent_limit"] == 20
    assert projection["recent_failures"] == {
        "jobs": [],
        "events": [],
    }
    assert projection["active_jobs"] == []
    assert {
        (source["source_type"], source["service_id"], source["status"])
        for source in projection["degraded_sources"]
    } == {
        ("jobs", "nex-cx", "UNAVAILABLE"),
        ("events", "nex-cx", "UNAVAILABLE"),
    }
    assert projection["degraded_sources"][0]["error_code"] == "job.store_unavailable"
    assert_ag_operations_projection_contract(projection)


def test_normalize_dashboard_recent_limit_clamps_bounds() -> None:
    assert normalize_dashboard_recent_limit(0) == 1
    assert normalize_dashboard_recent_limit(5) == 5
    assert normalize_dashboard_recent_limit(999) == 20


def test_operations_dashboard_snapshot_route_requires_auth_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    runtime = build_ag_operations_source_runtime(environ={})
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry, runtime=runtime)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/dashboard")
    response = client.get(
        "/admin/v1/operations/dashboard",
        params={"service_id": "nex-cx", "recent_limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["projection_status"] == "READY"
    assert payload["rollup_summary"]["jobs"]["total"] == 2
    assert payload["recent_failures"]["jobs"][0]["job_id"] == "job-cx-002"


def test_operations_dashboard_snapshot_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/dashboard",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_window = client.get(
        "/admin/v1/operations/dashboard",
        params={
            "since": "2026-08-05T00:00:02Z",
            "until": "2026-08-05T00:00:01Z",
        },
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_window.status_code == 400
    assert bad_window.json()["error_code"] == "ag.operation_time_window_invalid"


def test_build_operations_issue_candidate_projection_flags_service_scope() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )

    projection = build_operations_issue_candidate_projection(
        registry=registry,
        service_id="nex-cx",
        recent_limit=2,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operations_issue_candidate_projection.v1"
    )
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert [rule["rule_id"] for rule in projection["rules"]] == [
        "operations_source_unavailable.v1",
        "operations_source_not_configured.v1",
        "failed_jobs_present.v1",
        "error_events_present.v1",
        "critical_events_present.v1",
        "active_jobs_review.v1",
    ]
    assert [
        (candidate["rule_id"], candidate["service_id"], candidate["severity"])
        for candidate in projection["issue_candidates"]
    ] == [
        ("failed_jobs_present.v1", "nex-cx", "ERROR"),
        ("active_jobs_review.v1", "nex-cx", "INFO"),
    ]
    assert projection["summary"] == {
        "total": 2,
        "by_severity": {
            "DEBUG": 0,
            "INFO": 1,
            "WARNING": 0,
            "ERROR": 1,
            "CRITICAL": 0,
        },
        "by_service": {"nex-cx": 2},
        "by_rule": {
            "failed_jobs_present.v1": 1,
            "active_jobs_review.v1": 1,
        },
    }
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_flags_degraded_and_error_event_sources() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )

    projection = build_operations_issue_candidate_projection(
        registry=registry,
        recent_limit=2,
    )

    assert projection["projection_status"] == "DEGRADED"
    candidates = {
        (candidate["rule_id"], candidate["service_id"], candidate["severity"])
        for candidate in projection["issue_candidates"]
    }
    assert (
        "operations_source_not_configured.v1",
        "nex-mo",
        "WARNING",
    ) in candidates
    assert ("failed_jobs_present.v1", "nex-cx", "ERROR") in candidates
    assert ("error_events_present.v1", "nex-mo", "ERROR") in candidates
    assert ("active_jobs_review.v1", "nex-cx", "INFO") in candidates
    assert projection["summary"]["by_severity"]["WARNING"] >= 1
    assert projection["summary"]["by_rule"]["operations_source_not_configured.v1"] >= 1
    candidate_ids = [
        candidate["candidate_id"]
        for candidate in projection["issue_candidates"]
    ]
    assert len(candidate_ids) == len(set(candidate_ids))
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_projection_reports_unavailable_sources() -> None:
    projection = build_operations_issue_candidate_projection(
        job_queues={"nex-cx": BrokenJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert {
        (candidate["rule_id"], candidate["service_id"], candidate["severity"])
        for candidate in projection["issue_candidates"]
    } == {
        ("operations_source_unavailable.v1", "nex-cx", "ERROR"),
    }
    assert projection["summary"]["by_rule"] == {
        "operations_source_unavailable.v1": 2,
    }
    assert projection["summary"]["by_severity"]["ERROR"] == 2
    assert_ag_operations_projection_contract(projection)


def test_operations_issue_candidate_rules_and_empty_summary_are_stable() -> None:
    assert operations_issue_candidate_rules()[0] == {
        "rule_id": "operations_source_unavailable.v1",
        "severity": "ERROR",
        "title": "Operations source unavailable",
        "description": "A configured operations source could not be read.",
        "enabled": True,
        "signal_type": "source_status",
    }
    assert summarize_operations_issue_candidates([]) == {
        "total": 0,
        "by_severity": {
            "DEBUG": 0,
            "INFO": 0,
            "WARNING": 0,
            "ERROR": 0,
            "CRITICAL": 0,
        },
        "by_service": {},
        "by_rule": {},
    }


def test_operations_issue_candidate_route_requires_auth_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/issue-candidates")
    response = client.get(
        "/admin/v1/operations/issue-candidates",
        params={"service_id": "nex-cx", "recent_limit": 2},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["projection_status"] == "READY"
    assert payload["summary"]["by_rule"]["failed_jobs_present.v1"] == 1


def test_operations_issue_candidate_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/issue-candidates",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_window = client.get(
        "/admin/v1/operations/issue-candidates",
        params={
            "since": "2026-08-05T00:00:02Z",
            "until": "2026-08-05T00:00:01Z",
        },
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_window.status_code == 400
    assert bad_window.json()["error_code"] == "ag.operation_time_window_invalid"


def test_unified_operations_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_status = client.get(
        "/admin/v1/operations",
        params={"job_status": "BLOCKED"},
        headers=auth_headers(),
    )
    bad_service = client.get(
        "/admin/v1/operations",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_severity = client.get(
        "/admin/v1/operations",
        params={"event_severity": "NOTICE"},
        headers=auth_headers(),
    )
    bad_cursor = client.get(
        "/admin/v1/operations",
        params={"cursor": "before"},
        headers=auth_headers(),
    )
    bad_window = client.get(
        "/admin/v1/operations",
        params={
            "since": "2026-08-05T00:00:02Z",
            "until": "2026-08-05T00:00:01Z",
        },
        headers=auth_headers(),
    )

    assert bad_status.status_code == 400
    assert bad_status.json()["error_code"] == "ag.job_status_invalid"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_severity.status_code == 400
    assert bad_severity.json()["error_code"] == "ag.operational_event_severity_invalid"
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error_code"] == "ag.operation_cursor_invalid"
    assert bad_window.status_code == 400
    assert bad_window.json()["error_code"] == "ag.operation_time_window_invalid"


def test_build_cross_service_trace_timeline_projection_sorts_and_summarizes() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    projection = build_cross_service_trace_timeline_projection(
        trace_id=TRACE_ID,
        registry=registry,
        query_options=build_operation_query_options(limit=3, sort="asc"),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_cross_service_trace_timeline_projection.v1"
    )
    assert projection["projection_status"] == "DEGRADED"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "trace_id": TRACE_ID,
        "service_id": None,
        "limit": 3,
        "since": None,
        "until": None,
        "sort": "asc",
        "cursor": None,
    }
    assert [
        (item["timeline_item_type"], item["item_id"])
        for item in projection["timeline"]
    ] == [
        ("event", "event:event-cx-001"),
        ("job", "job:nex-cx:job-cx-001"),
        ("job", "job:nex-cx:job-cx-002"),
    ]
    assert projection["summary"] == {
        "total": 3,
        "by_item_type": {"event": 1, "job": 2},
        "by_service": {"nex-cx": 3},
    }
    assert projection["pagination"]["next_cursor"] == "3"
    assert projection["job_source_statuses"]["nex-oa"]["status"] == "NOT_CONFIGURED"
    assert projection["event_source_status"] == {
        "status": "READY",
        "event_count": 1,
    }


def test_cross_service_trace_timeline_projection_filters_service_and_window() -> None:
    projection = build_cross_service_trace_timeline_projection(
        trace_id=TRACE_ID,
        job_queues=build_job_queues(),
        event_store=build_store(),
        service_id="nex-cx",
        query_options=build_operation_query_options(
            limit=2,
            since="2026-08-05T00:00:01Z",
            sort="desc",
        ),
    )

    assert projection["projection_status"] == "READY"
    assert projection["filters"]["service_id"] == "nex-cx"
    assert [item["item_id"] for item in projection["timeline"]] == [
        "job:nex-cx:job-cx-002",
        "job:nex-cx:job-cx-001",
    ]
    assert projection["summary"]["by_item_type"] == {"job": 2}
    assert projection["pagination"]["next_cursor"] is None


def test_cross_service_trace_timeline_projection_reports_unavailable_sources() -> None:
    projection = build_cross_service_trace_timeline_projection(
        trace_id=TRACE_ID,
        job_queues={"nex-cx": BrokenJobQueue()},
        event_store=BrokenOperationalEventStore(),
        service_id="nex-cx",
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["timeline"] == []
    assert projection["summary"] == {
        "total": 0,
        "by_item_type": {},
        "by_service": {},
    }
    assert projection["job_source_statuses"]["nex-cx"]["status"] == "UNAVAILABLE"
    assert projection["event_source_status"] == {
        "status": "UNAVAILABLE",
        "event_count": 0,
        "error_code": "operational_event.store_unavailable",
        "detail": "operational event store is unavailable",
    }


def test_summarize_trace_timeline_items_counts_empty_and_unknown_services() -> None:
    assert summarize_trace_timeline_items([]) == {
        "total": 0,
        "by_item_type": {},
        "by_service": {},
    }
    assert summarize_trace_timeline_items(
        [
            {
                "timeline_item_type": "custom",
                "service_id": "nex-cx",
            }
        ]
    ) == {
        "total": 1,
        "by_item_type": {"custom": 1},
        "by_service": {"nex-cx": 1},
    }


def test_cross_service_trace_timeline_route_requires_auth_and_returns_projection() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get(f"/admin/v1/operations/traces/{TRACE_ID}")
    response = client.get(
        f"/admin/v1/operations/traces/{TRACE_ID}",
        params={"service_id": "nex-cx", "sort": "asc", "limit": 2},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"]["trace_id"] == TRACE_ID
    assert payload["filters"]["service_id"] == "nex-cx"
    assert [item["timeline_item_type"] for item in payload["timeline"]] == [
        "event",
        "job",
    ]


def test_cross_service_trace_timeline_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_unified_operation_routes(app)
    client = TestClient(app)

    bad_service = client.get(
        f"/admin/v1/operations/traces/{TRACE_ID}",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_cursor = client.get(
        f"/admin/v1/operations/traces/{TRACE_ID}",
        params={"cursor": "before"},
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error_code"] == "ag.operation_cursor_invalid"


def test_ag_operations_contract_schema_accepts_runtime_projection_family() -> None:
    job_queues = build_job_queues()
    event_stores = build_event_stores()
    registry = build_operations_source_registry(
        job_queues=job_queues,
        event_stores=event_stores,
    )
    runtime = build_ag_operations_source_runtime(environ={})
    job = job_queues["nex-cx"].get_job("job-cx-001")
    event = build_store().get_event("event-002")
    assert job is not None
    assert event is not None

    projections = [
        build_operation_source_readiness_projection(
            runtime=runtime,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_operational_event_projection(
            build_store(),
            service_id="nex-mo",
            severity="ERROR",
            request_trace_id=TRACE_ID,
        ),
        build_operational_event_detail_projection(
            event,
            request_trace_id=TRACE_ID,
        ),
        build_operational_event_taxonomy_projection(
            service_id="nex-cx",
            event_type=CX_PROCESSING_EVENT_STARTED,
            request_trace_id=TRACE_ID,
        ),
        build_job_operations_projection(
            job_queues,
            service_id="nex-cx",
            status=RUNNING,
            request_trace_id=TRACE_ID,
        ),
        build_job_operation_detail_projection(
            job,
            service_id="nex-cx",
            event_store=build_store(),
            request_trace_id=TRACE_ID,
        ),
        build_unified_operations_projection(
            registry=registry,
            service_id="nex-cx",
            job_status=RUNNING,
            event_severity="INFO",
            trace_id=TRACE_ID,
            request_trace_id=TRACE_ID,
        ),
        build_operations_rollup_metrics_projection(
            registry=registry,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_operations_dashboard_snapshot_projection(
            registry=registry,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_operations_issue_candidate_projection(
            registry=registry,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
        build_cross_service_trace_timeline_projection(
            trace_id=TRACE_ID,
            registry=registry,
            service_id="nex-cx",
            request_trace_id=TRACE_ID,
        ),
    ]

    for projection in projections:
        assert_ag_operations_projection_contract(projection)


def test_build_operational_event_projection_filters_and_summarizes() -> None:
    projection = build_operational_event_projection(
        build_store(),
        service_id="nex-mo",
        severity="error",
        limit=9999,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == "ag_operational_event_projection.v1"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-mo",
        "severity": "ERROR",
        "event_type": None,
        "trace_id": None,
        "q": None,
        "limit": 500,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert [event["event_id"] for event in projection["events"]] == ["event-002"]
    assert projection["summary"]["by_severity"]["ERROR"] == 1
    assert projection["pagination"]["returned"] == 1
    assert "Bearer private" not in str(projection)


def test_build_operational_event_projection_can_omit_request_trace_id() -> None:
    projection = build_operational_event_projection(build_store(), limit=1)

    assert "request_trace_id" not in projection
    assert projection["filters"]["limit"] == 1
    assert len(projection["events"]) == 1


def test_build_operational_event_projection_applies_text_query() -> None:
    by_message = build_operational_event_projection(build_store(), q="provider")
    by_subject = build_operational_event_projection(build_store(), q="doc-001")
    by_detail = build_operational_event_projection(build_store(), q="run-001")
    no_match = build_operational_event_projection(build_store(), q="not-observed")

    assert [event["event_id"] for event in by_message["events"]] == ["event-002"]
    assert by_message["filters"]["q"] == "provider"
    assert by_message["pagination"]["total_after_filters"] == 1
    assert [event["event_id"] for event in by_subject["events"]] == ["event-001"]
    assert [event["event_id"] for event in by_detail["events"]] == ["event-001"]
    assert no_match["events"] == []
    assert no_match["summary"]["total"] == 0


def test_normalize_operation_event_search_query_strips_and_rejects_long_values() -> None:
    assert normalize_operation_event_search_query("  Provider  ") == "Provider"
    assert normalize_operation_event_search_query("   ") is None

    with pytest.raises(OperationsQueryError) as exc_info:
        normalize_operation_event_search_query("x" * 129)

    assert exc_info.value.error_code == "ag.operation_event_query_invalid"


def test_build_operational_event_detail_projection_returns_safe_event_summary() -> None:
    event = build_store().get_event("event-002")
    assert event is not None

    projection = build_operational_event_detail_projection(
        event,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operational_event_detail_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["event"]["event_id"] == "event-002"
    assert projection["event"]["details"]["authorization"] == "<redacted>"
    assert projection["summary"] == {
        "event_id": "event-002",
        "service_id": "nex-mo",
        "event_type": "mo.provider.failed",
        "severity": "ERROR",
        "trace_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "subject_ref": {"type": "mo.provider", "id": "embedding"},
        "created_at": "2026-08-05T00:00:01Z",
    }
    assert "Bearer private" not in str(projection)


def test_build_operational_event_taxonomy_projection_filters_and_summarizes() -> None:
    projection = build_operational_event_taxonomy_projection(
        service_id="nex-cx",
        event_type=CX_PROCESSING_EVENT_STARTED,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_operational_event_taxonomy_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "event_type": CX_PROCESSING_EVENT_STARTED,
    }
    assert [item["event_type"] for item in projection["event_types"]] == [
        CX_PROCESSING_EVENT_STARTED
    ]
    assert projection["summary"]["by_service"] == {"nex-cx": 1}


def test_operational_event_taxonomy_route_requires_auth_returns_filtered_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_taxonomy_routes(app)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/event-taxonomy")
    response = client.get(
        "/admin/v1/operations/event-taxonomy",
        params={"event_type": CX_PROCESSING_EVENT_FAILED},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert missing_auth.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["event_types"][0]["event_type"] == CX_PROCESSING_EVENT_FAILED
    assert payload["event_types"][0]["default_severity"] == "ERROR"


def test_operational_event_taxonomy_route_rejects_bad_service() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_taxonomy_routes(app)

    response = TestClient(app).get(
        "/admin/v1/operations/event-taxonomy",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ag.event_taxonomy_service_invalid"


def test_operational_events_route_requires_auth() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())

    response = TestClient(app).get("/admin/v1/operations/events")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_operational_events_route_returns_filtered_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())

    response = TestClient(app).get(
        "/admin/v1/operations/events",
        params={"service_id": "nex-cx", "q": "doc-001", "limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"]["service_id"] == "nex-cx"
    assert payload["filters"]["q"] == "doc-001"
    assert payload["events"][0]["event_id"] == "event-001"
    assert payload["summary"]["total"] == 1


def test_operational_event_detail_route_requires_auth_returns_event_and_404() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/events/event-001")
    response = client.get(
        "/admin/v1/operations/events/event-001",
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    missing_event = client.get(
        "/admin/v1/operations/events/event-missing",
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["event"]["event_id"] == "event-001"
    assert payload["summary"]["subject_ref"] == {"type": "cx.document", "id": "doc-001"}
    assert missing_event.status_code == 404
    assert missing_event.json()["error_code"] == "ag.operational_event_not_found"


def test_operational_events_route_applies_sort_cursor_and_window() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())

    response = TestClient(app).get(
        "/admin/v1/operations/events",
        params={
            "since": "2026-08-05T00:00:00Z",
            "sort": "asc",
            "limit": 1,
            "cursor": "1",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["sort"] == "asc"
    assert payload["filters"]["cursor"] == "1"
    assert [event["event_id"] for event in payload["events"]] == ["event-002"]
    assert payload["pagination"]["returned"] == 1
    assert payload["pagination"]["next_cursor"] is None


def test_operational_events_route_rejects_bad_severity() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operational_event_routes(app, store=build_store())

    response = TestClient(app).get(
        "/admin/v1/operations/events",
        params={"severity": "NOTICE"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ag.operational_event_severity_invalid"

    bad_sort = TestClient(app).get(
        "/admin/v1/operations/events",
        params={"sort": "latest"},
        headers=auth_headers(),
    )
    assert bad_sort.status_code == 400
    assert bad_sort.json()["error_code"] == "ag.operation_sort_invalid"

    bad_query = TestClient(app).get(
        "/admin/v1/operations/events",
        params={"q": "x" * 129},
        headers=auth_headers(),
    )
    assert bad_query.status_code == 400
    assert bad_query.json()["error_code"] == "ag.operation_event_query_invalid"


def test_normalize_job_limit_clamps_bounds() -> None:
    assert normalize_job_limit(0) == 1
    assert normalize_job_limit(10) == 10
    assert normalize_job_limit(9999) == 500


def test_build_job_operations_projection_aggregates_filters_and_summarizes() -> None:
    projection = build_job_operations_projection(
        build_job_queues(),
        service_id="nex-cx",
        status="failed",
        limit=9999,
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == "ag_job_operations_projection.v1"
    assert projection["projection_status"] == "READY"
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["filters"] == {
        "service_id": "nex-cx",
        "status": FAILED,
        "job_type": None,
        "limit": 500,
        "since": None,
        "until": None,
        "sort": "desc",
        "cursor": None,
    }
    assert [job["job_id"] for job in projection["jobs"]] == ["job-cx-002"]
    assert projection["jobs"][0]["service_id"] == "nex-cx"
    assert projection["summary"]["statuses"][FAILED] == 1
    assert projection["summary"]["by_service"] == {"nex-cx": 1}
    assert projection["summary"]["by_job_type"] == {"cx.document_processing": 1}
    assert projection["source_statuses"]["nex-cx"] == {
        "status": "READY",
        "job_count": 1,
    }
    assert projection["pagination"] == {
        "limit": 500,
        "cursor": None,
        "returned": 1,
        "total_after_filters": 1,
        "next_cursor": None,
    }


def test_build_job_operations_projection_sorts_limits_and_reports_degraded_sources() -> None:
    projection = build_job_operations_projection(
        {
            **build_job_queues(),
            "nex-mo": BrokenJobQueue(),
        },
        limit=2,
    )

    assert projection["projection_status"] == "DEGRADED"
    assert [job["job_id"] for job in projection["jobs"]] == [
        "job-ae-001",
        "job-cx-002",
    ]
    assert projection["summary"]["total"] == 2
    assert projection["summary"]["by_service"] == {"nex-ae-api": 1, "nex-cx": 1}
    assert projection["source_statuses"]["nex-mo"]["status"] == "UNAVAILABLE"
    assert projection["source_statuses"]["nex-oa"] == {
        "status": "NOT_CONFIGURED",
        "job_count": 0,
    }


def test_build_job_operations_projection_applies_query_options_before_paging() -> None:
    projection = build_job_operations_projection(
        build_job_queues(),
        query_options=build_operation_query_options(
            limit=1,
            since="2026-08-05T00:00:04Z",
            until="2026-08-05T00:00:07Z",
            sort="asc",
        ),
    )

    assert [job["job_id"] for job in projection["jobs"]] == ["job-cx-002"]
    assert projection["source_statuses"]["nex-cx"]["job_count"] == 1
    assert projection["source_statuses"]["nex-ae-api"]["job_count"] == 1
    assert projection["pagination"] == {
        "limit": 1,
        "cursor": None,
        "returned": 1,
        "total_after_filters": 2,
        "next_cursor": "1",
    }


def test_build_job_operation_detail_projection_includes_lifecycle_timeline() -> None:
    job = build_job_queues()["nex-cx"].get_job("job-cx-001")
    assert job is not None

    projection = build_job_operation_detail_projection(
        job,
        service_id="nex-cx",
        event_store=build_store(),
        request_trace_id=TRACE_ID,
    )

    assert projection["projection_schema_version"] == (
        "ag_job_operation_detail_projection.v1"
    )
    assert projection["request_trace_id"] == TRACE_ID
    assert projection["job"]["service_id"] == "nex-cx"
    assert projection["job"]["job_id"] == "job-cx-001"
    assert projection["summary"]["timeline_status"] == "READY"
    assert projection["summary"]["timeline_event_count"] == 1
    timeline_event_ids = [
        event["event_id"]
        for event in projection["lifecycle_timeline"]["events"]
    ]
    assert timeline_event_ids == ["event-001"]


def test_build_job_operation_detail_projection_reports_timeline_source_states() -> None:
    job = build_job_queues()["nex-cx"].get_job("job-cx-001")
    assert job is not None

    not_configured = build_job_operation_detail_projection(
        job,
        service_id="nex-cx",
    )
    unavailable = build_job_operation_detail_projection(
        job,
        service_id="nex-cx",
        event_store=BrokenOperationalEventStore(),
    )

    assert not_configured["lifecycle_timeline"] == {
        "timeline_status": "NOT_CONFIGURED",
        "event_count": 0,
        "events": [],
        "source_error": None,
    }
    assert unavailable["lifecycle_timeline"]["timeline_status"] == "UNAVAILABLE"
    assert unavailable["lifecycle_timeline"]["source_error"] == {
        "error_code": "operational_event.store_unavailable",
        "detail": "operational event store is unavailable",
        "status_code": 503,
    }


def test_summarize_job_operations_counts_empty_and_unknown_shapes() -> None:
    assert summarize_job_operations([])["by_service"] == {}

    summary = summarize_job_operations(
        [
            {
                "status": SUCCEEDED,
                "service_id": "nex-cx",
                "job_type": "cx.document_processing",
            },
            {"status": "UNKNOWN"},
        ]
    )

    assert summary["total"] == 2
    assert summary["statuses"][SUCCEEDED] == 1
    assert summary["by_service"] == {"nex-cx": 1, "unknown": 1}
    assert summary["by_job_type"] == {"cx.document_processing": 1, "unknown": 1}


def test_job_operations_route_requires_auth() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, job_queues=build_job_queues())

    response = TestClient(app).get("/admin/v1/operations/jobs")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_job_operations_route_returns_filtered_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, job_queues=build_job_queues())

    response = TestClient(app).get(
        "/admin/v1/operations/jobs",
        params={"job_type": "ae.artifact_render", "limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"]["job_type"] == "ae.artifact_render"
    assert payload["jobs"][0]["job_id"] == "job-ae-001"
    assert payload["summary"]["statuses"][SUCCEEDED] == 1


def test_job_operation_detail_route_requires_auth_returns_job_and_404() -> None:
    registry = build_operations_source_registry(
        job_queues=build_job_queues(),
        event_stores=build_event_stores(),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, registry=registry)
    client = TestClient(app)

    missing_auth = client.get("/admin/v1/operations/jobs/nex-cx/job-cx-001")
    response = client.get(
        "/admin/v1/operations/jobs/nex-cx/job-cx-001",
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )
    missing_job = client.get(
        "/admin/v1/operations/jobs/nex-cx/job-missing",
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["job"]["job_id"] == "job-cx-001"
    assert payload["lifecycle_timeline"]["timeline_status"] == "READY"
    timeline_event_ids = [
        event["event_id"]
        for event in payload["lifecycle_timeline"]["events"]
    ]
    assert timeline_event_ids == ["event-cx-001"]
    assert missing_job.status_code == 404
    assert missing_job.json()["error_code"] == "ag.job_not_found"


def test_job_operation_detail_route_rejects_bad_or_unavailable_sources() -> None:
    registry = build_operations_source_registry(job_queues=build_job_queues())
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, registry=registry)
    client = TestClient(app)

    bad_service = client.get(
        "/admin/v1/operations/jobs/nex-unknown/job-001",
        headers=auth_headers(),
    )
    missing_source = client.get(
        "/admin/v1/operations/jobs/nex-mo/job-001",
        headers=auth_headers(),
    )

    unavailable_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(
        unavailable_app,
        job_queues={"nex-cx": UnavailableJobQueue()},
    )
    unavailable = TestClient(unavailable_app).get(
        "/admin/v1/operations/jobs/nex-cx/job-001",
        headers=auth_headers(),
    )

    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert missing_source.status_code == 404
    assert missing_source.json()["error_code"] == "ag.job_source_not_configured"
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "job.store_unavailable"


def test_job_operations_route_rejects_bad_filters() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(app, job_queues=build_job_queues())
    client = TestClient(app)

    bad_status = client.get(
        "/admin/v1/operations/jobs",
        params={"status": "BLOCKED"},
        headers=auth_headers(),
    )
    bad_service = client.get(
        "/admin/v1/operations/jobs",
        params={"service_id": "nex-unknown"},
        headers=auth_headers(),
    )
    bad_cursor = client.get(
        "/admin/v1/operations/jobs",
        params={"cursor": "-1"},
        headers=auth_headers(),
    )

    assert bad_status.status_code == 400
    assert bad_status.json()["error_code"] == "ag.job_status_invalid"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["error_code"] == "ag.operation_cursor_invalid"
