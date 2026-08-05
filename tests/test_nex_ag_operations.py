from __future__ import annotations

from fastapi.testclient import TestClient

from nex_ag.operations import build_operational_event_projection, register_operational_event_routes
from nex_runtime import (
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_operational_event,
    build_service_app,
    issue_mock_service_token,
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
