from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nex_ag.cross_service_trace import (
    AG_TRACE_REQUIRED_SCOPES,
    AgTraceSourceError,
    CrossServiceTraceAggregator,
    HttpCrossServiceTraceSourceClient,
    _safe_error_code,
    register_cross_service_trace_routes,
    build_default_cross_service_trace_aggregator,
)
from nex_runtime import (
    CrossServiceTraceError,
    InMemoryOperationalEventStore,
    OperationalEventError,
    SERVICE_SPECS,
    build_service_app,
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
    validate_mock_service_token,
    issue_mock_service_token,
)

TRACE_ID = "13771377137713771377137713771377"
REQUEST_TRACE_ID = "77137713771377137713771377137713"


def _source(
    service_id: str,
    *,
    stage_family: str = "OPERATIONS",
    stage_status: str = "SUCCEEDED",
    timestamp: str = "2026-10-06T13:00:00Z",
) -> dict[str, Any]:
    stage = build_cross_service_trace_stage(
        stage_id=f"stage-{service_id}-1377",
        trace_id=TRACE_ID,
        request_id=f"request-{service_id}-1377",
        service_id=service_id,
        stage_family=stage_family,
        stage_status=stage_status,
        operation_timestamp=timestamp,
        safe_attributes={"result_code": stage_status},
    )
    return build_cross_service_trace_source_projection(
        service_id=service_id,
        trace_id=TRACE_ID,
        stages=[stage],
        source_status="READY",
        checked_at="2026-10-06T13:01:00Z",
    )


class StubClient:
    def __init__(self, service_id: str, result: object) -> None:
        self.service_id = service_id
        self.result = result
        self.calls: list[tuple[str, str, str]] = []

    def get_trace_projection(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append((trace_id, request_id, request_trace_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result  # type: ignore[return-value]


def test_http_client_uses_operations_scope_and_validates_response(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def requester(url: str, **kwargs: Any) -> httpx.Response:
        captured.update(url=url, **kwargs)
        return httpx.Response(
            200,
            json=_source("nex-cx"),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK")
    client = HttpCrossServiceTraceSourceClient(
        service_id="nex-cx",
        base_url="http://cx.local/",
        requester=requester,
    )

    assert (
        client.get_trace_projection(
            TRACE_ID,
            request_id="request-1377",
            request_trace_id=REQUEST_TRACE_ID,
        )["service_id"]
        == "nex-cx"
    )
    assert captured["url"] == (
        f"http://cx.local/internal/v1/operations/traces/{TRACE_ID}"
    )
    assert captured["headers"]["X-Service-ID"] == "nex-ag"
    token = captured["headers"]["Authorization"].removeprefix("Bearer ")
    admission = validate_mock_service_token(
        token,
        expected_audience="nex-cx",
        required_scopes=AG_TRACE_REQUIRED_SCOPES,
    )
    assert admission.ok is True


@pytest.mark.parametrize(
    ("status_code", "body", "source_status", "error_code", "retryable"),
    [
        (
            403,
            {"error_code": "cx.trace_forbidden"},
            "DEGRADED",
            "cx.trace_forbidden",
            False,
        ),
        (
            503,
            {"error_code": "private code", "retryable": True},
            "UNAVAILABLE",
            "ag.trace_source_request_failed",
            True,
        ),
    ],
)
def test_http_client_maps_safe_http_failures(
    monkeypatch,
    status_code: int,
    body: dict[str, Any],
    source_status: str,
    error_code: str,
    retryable: bool,
) -> None:
    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK")

    def requester(url: str, **_: Any) -> httpx.Response:
        return httpx.Response(
            status_code,
            json=body,
            request=httpx.Request("GET", url),
        )

    client = HttpCrossServiceTraceSourceClient(
        "nex-cx", "http://cx", requester=requester
    )
    with pytest.raises(AgTraceSourceError) as exc_info:
        client.get_trace_projection(
            TRACE_ID,
            request_id="request-1377",
            request_trace_id=REQUEST_TRACE_ID,
        )
    assert exc_info.value.source_status == source_status
    assert exc_info.value.error_code == error_code
    assert exc_info.value.retryable is retryable


def test_http_client_fails_closed_for_token_transport_and_contract(monkeypatch) -> None:
    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY")
    missing_token = HttpCrossServiceTraceSourceClient("nex-oa", "http://oa")
    with pytest.raises(AgTraceSourceError) as token_error:
        missing_token.get_trace_projection(
            TRACE_ID,
            request_id="request-1377",
            request_trace_id=REQUEST_TRACE_ID,
        )
    assert token_error.value.error_code == "ag.outbound_service_token_missing"
    assert token_error.value.retryable is False

    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK")

    def timeout(url: str, **_: Any) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=httpx.Request("GET", url))

    def transport(url: str, **_: Any) -> httpx.Response:
        raise httpx.ConnectError("failed", request=httpx.Request("GET", url))

    def invalid(url: str, **_: Any) -> httpx.Response:
        return httpx.Response(200, json=["invalid"], request=httpx.Request("GET", url))

    for requester, code, retryable in (
        (timeout, "ag.trace_source_timeout", True),
        (transport, "ag.trace_source_transport_failed", True),
        (invalid, "ag.trace_source_contract_invalid", False),
    ):
        client = HttpCrossServiceTraceSourceClient(
            "nex-oa", "http://oa", requester=requester
        )
        with pytest.raises(AgTraceSourceError) as exc_info:
            client.get_trace_projection(
                TRACE_ID,
                request_id="request-1377",
                request_trace_id=REQUEST_TRACE_ID,
            )
        assert exc_info.value.error_code == code
        assert exc_info.value.retryable is retryable

    def invalid_problem(url: str, **_: Any) -> httpx.Response:
        return httpx.Response(
            502,
            content=b"not-json",
            request=httpx.Request("GET", url),
        )

    invalid_problem_client = HttpCrossServiceTraceSourceClient(
        "nex-oa", "http://oa", requester=invalid_problem
    )
    with pytest.raises(AgTraceSourceError) as invalid_problem_error:
        invalid_problem_client.get_trace_projection(
            TRACE_ID,
            request_id="request-1377",
            request_trace_id=REQUEST_TRACE_ID,
        )
    assert str(invalid_problem_error.value) == "ag.trace_source_request_failed"


def test_aggregator_sorts_sources_and_records_partial_failure() -> None:
    oa = StubClient(
        "nex-oa",
        _source("nex-oa", stage_family="AUTH", timestamp="2026-10-06T12:00:00Z"),
    )
    cx = StubClient(
        "nex-cx",
        _source("nex-cx", stage_family="GENERATION", timestamp="2026-10-06T12:02:00Z"),
    )
    mo = StubClient(
        "nex-mo",
        AgTraceSourceError(
            "nex-mo",
            "ag.trace_source_timeout",
            "UNAVAILABLE",
            retryable=True,
        ),
    )
    aggregator = CrossServiceTraceAggregator(
        {"nex-oa": oa, "nex-cx": cx, "nex-mo": mo},
        clock=lambda: datetime(2026, 10, 6, 13, 0, tzinfo=UTC),
    )

    result = aggregator.aggregate(
        TRACE_ID,
        request_id="request-1377",
        request_trace_id=REQUEST_TRACE_ID,
    )

    assert result.projection["projection_status"] == "DEGRADED"
    assert [stage["service_id"] for stage in result.projection["timeline"]] == [
        "nex-oa",
        "nex-cx",
    ]
    assert result.projection["source_statuses"] == [
        {"service_id": "nex-ae-api", "source_status": "UNAVAILABLE"},
        {"service_id": "nex-cx", "source_status": "READY"},
        {"service_id": "nex-mo", "source_status": "UNAVAILABLE"},
        {"service_id": "nex-oa", "source_status": "READY"},
    ]
    assert result.diagnostics == (
        {
            "service_id": "nex-ae-api",
            "error_code": "ag.trace_source_not_configured",
            "retryable": False,
        },
        {
            "service_id": "nex-mo",
            "error_code": "ag.trace_source_timeout",
            "retryable": True,
            "status_code": 503,
        },
    )


def test_aggregator_rejects_bad_selection_contract_and_clock() -> None:
    invalid_source = _source("nex-oa")
    invalid_source["summary"]["stage_count"] = 99
    aggregator = CrossServiceTraceAggregator(
        {"nex-oa": StubClient("nex-oa", invalid_source)},
        clock=lambda: datetime(2026, 10, 6, 13, 0, tzinfo=UTC),
    )
    degraded = aggregator.aggregate(
        TRACE_ID,
        request_id="request-1377",
        request_trace_id=REQUEST_TRACE_ID,
        service_ids=["nex-oa"],
    )
    assert degraded.projection["projection_status"] == "DEGRADED"
    assert degraded.diagnostics[0]["error_code"] == "ag.trace_source_contract_invalid"

    for selected in ([], ["nex-oa", "nex-oa"], ["nex-ag"]):
        with pytest.raises(ValueError):
            aggregator.aggregate(
                TRACE_ID,
                request_id="request-1377",
                request_trace_id=REQUEST_TRACE_ID,
                service_ids=selected,
            )

    naive = CrossServiceTraceAggregator(
        {"nex-oa": StubClient("nex-oa", _source("nex-oa"))},
        clock=lambda: datetime(2026, 10, 6, 13, 0),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        naive.aggregate(
            TRACE_ID,
            request_id="request-1377",
            request_trace_id=REQUEST_TRACE_ID,
            service_ids=["nex-oa"],
        )


def test_default_aggregator_uses_service_environment_without_leaking_tokens() -> None:
    aggregator = build_default_cross_service_trace_aggregator(
        {
            "NEX_OA_BASE_URL": "http://oa.internal/",
            "NEX_AG_TO_OA_SERVICE_TOKEN": "signed-oa-token",
        }
    )

    assert tuple(aggregator.clients) == ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo")
    assert aggregator.clients["nex-oa"].base_url == "http://oa.internal/"
    assert aggregator.clients["nex-oa"].service_token == "signed-oa-token"
    assert aggregator.clients["nex-mo"].base_url == "http://127.0.0.1:8105"
    assert "signed-oa-token" not in repr(aggregator)

    for args in (
        ("nex-ag", "http://ag", 5.0),
        ("nex-oa", " bad ", 5.0),
        ("nex-oa", "http://oa", 0.0),
    ):
        with pytest.raises(ValueError):
            HttpCrossServiceTraceSourceClient(
                service_id=args[0], base_url=args[1], timeout_seconds=args[2]
            )
    with pytest.raises(ValueError):
        CrossServiceTraceAggregator({"nex-ag": StubClient("nex-ag", {})})

    assert _safe_error_code("oa.valid_code") == "oa.valid_code"
    assert _safe_error_code(None) == "ag.trace_source_request_failed"


def _route_aggregator() -> CrossServiceTraceAggregator:
    return CrossServiceTraceAggregator(
        {
            service_id: StubClient(service_id, _source(service_id))
            for service_id in ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo")
        },
        clock=lambda: datetime(2026, 10, 6, 13, 0, tzinfo=UTC),
    )


def _auth_headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-oa",
        audience="nex-ag",
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": "request-route-1378",
        "traceparent": f"00-{REQUEST_TRACE_ID}-00f067aa0ba902b7-01",
    }


def test_protected_route_persists_audit_and_appends_ag_stage() -> None:
    store = InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_cross_service_trace_routes(
        app,
        aggregator=_route_aggregator(),
        event_store=store,
    )
    client = TestClient(app)

    assert client.get(f"/admin/v1/operations/traces/{TRACE_ID}").status_code == 401
    response = client.get(
        f"/admin/v1/operations/traces/{TRACE_ID}", headers=_auth_headers()
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == "ag_cross_service_trace_e2e.v1"
    assert payload["summary"]["source_count"] == 5
    assert payload["summary"]["stage_count"] == 5
    ag_stages = [
        stage for stage in payload["timeline"] if stage["service_id"] == "nex-ag"
    ]
    assert len(ag_stages) == 1
    assert ag_stages[0]["stage_family"] == "OPERATIONS"
    events = store.list_events(trace_id=TRACE_ID)
    assert len(events) == 1
    assert events[0]["event_type"] == "ag.cross_service_trace.read.succeeded"
    assert events[0]["details"] == {
        "projection_status": "READY",
        "source_count": 4,
        "ready_source_count": 4,
        "degraded_source_count": 0,
        "unavailable_source_count": 0,
        "stage_count": 4,
        "diagnostic_count": 0,
        "diagnostic_error_codes": [],
        "private_payload_included": False,
    }


class BrokenEventStore(InMemoryOperationalEventStore):
    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        del event
        raise OperationalEventError(
            "operational_event.store_unavailable",
            "store unavailable",
            503,
        )


class BrokenAggregator:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def aggregate(self, *args: Any, **kwargs: Any):
        del args, kwargs
        raise self.error


def test_protected_route_fails_closed_for_audit_and_aggregation_errors() -> None:
    audit_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_cross_service_trace_routes(
        audit_app,
        aggregator=_route_aggregator(),
        event_store=BrokenEventStore(),
    )
    audit_response = TestClient(audit_app).get(
        f"/admin/v1/operations/traces/{TRACE_ID}", headers=_auth_headers()
    )
    assert audit_response.status_code == 503
    assert audit_response.json()["error_code"] == (
        "ag.cross_service_trace_audit_unavailable"
    )

    for error, status_code, error_code in (
        (
            ValueError("private"),
            503,
            "ag.cross_service_trace_aggregation_failed",
        ),
        (
            CrossServiceTraceError("trace.trace_id_invalid", "invalid trace"),
            422,
            "trace.trace_id_invalid",
        ),
    ):
        app = build_service_app(SERVICE_SPECS["nex-ag"])
        register_cross_service_trace_routes(
            app,
            aggregator=BrokenAggregator(error),  # type: ignore[arg-type]
        )
        response = TestClient(app).get(
            f"/admin/v1/operations/traces/{TRACE_ID}", headers=_auth_headers()
        )
        assert response.status_code == status_code
        assert response.json()["error_code"] == error_code
