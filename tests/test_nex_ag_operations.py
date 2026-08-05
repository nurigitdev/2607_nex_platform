from __future__ import annotations

from fastapi.testclient import TestClient

from nex_ag.operations import (
    OperationsSource,
    OperationsSourceRegistry,
    RegistryOperationalEventStore,
    build_job_operations_projection,
    build_operations_source_registry,
    build_operational_event_projection,
    register_job_operation_routes,
    register_operational_event_routes,
    summarize_job_operations,
)
from nex_runtime import (
    FAILED,
    InMemoryOperationalEventStore,
    InMemoryJobQueue,
    JobQueueError,
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


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {"Authorization": f"Bearer {issued.access_token}"}


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

    assert [event["event_id"] for event in events] == ["event-mo-001", "event-cx-001"]
    assert [event["event_id"] for event in cx_events] == ["event-cx-001"]
    assert missing == []
    assert mo_event is not None
    assert mo_event["details"]["service_token"] == "<redacted>"
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
        "limit": 500,
    }
    assert [event["event_id"] for event in projection["events"]] == ["event-002"]
    assert projection["summary"]["by_severity"]["ERROR"] == 1
    assert "Bearer private" not in str(projection)


def test_build_operational_event_projection_can_omit_request_trace_id() -> None:
    projection = build_operational_event_projection(build_store(), limit=1)

    assert "request_trace_id" not in projection
    assert projection["filters"]["limit"] == 1
    assert len(projection["events"]) == 1


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
        params={"service_id": "nex-cx", "limit": 1},
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_trace_id"] == TRACE_ID
    assert payload["filters"]["service_id"] == "nex-cx"
    assert payload["events"][0]["event_id"] == "event-001"
    assert payload["summary"]["total"] == 1


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

    assert bad_status.status_code == 400
    assert bad_status.json()["error_code"] == "ag.job_status_invalid"
    assert bad_service.status_code == 400
    assert bad_service.json()["error_code"] == "ag.job_service_invalid"
