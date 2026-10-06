from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nex_mo.providers import register_mock_provider_routes
from nex_mo.trace_projection import (
    MO_TRACE_OPERATIONS_PATH,
    MoTraceProjectionError,
    MoTraceProjectionSource,
    _opaque_identifier,
    _safe_text,
    _timestamp,
    build_mo_trace_projection,
    register_mo_trace_projection_routes,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventError,
    build_operational_event,
    issue_mock_service_token,
)

TRACE_ID = "76137613761376137613761376137613"
NOW = datetime(2026, 10, 6, 12, 30, tzinfo=UTC)


def _record(
    *, failed: bool = False, capability: str = "generation"
) -> dict[str, object]:
    return build_operational_event(
        service_id="nex-mo",
        event_type=(
            "mo.provider.request.failed" if failed else "mo.provider.request.succeeded"
        ),
        severity="ERROR" if failed else "INFO",
        message="provider result",
        trace_id=TRACE_ID,
        request_id="request-1376",
        details={
            "provider_capability": capability,
            "model_alias": "general-llm-default",
            "model_revision": "Qwen-revision",
            "deployment_id": "dgx-generation-9111",
            "provider_route_id": "route-general-llm-default",
            "provider_mode": "live",
            "provider_request_id": "provider-request-1376",
            "result_code": "FAILED" if failed else "SUCCEEDED",
            "retryable": failed,
            **({"failure_code": "UPSTREAM_TIMEOUT"} if failed else {}),
        },
        created_at="2026-10-06T12:00:00Z",
    )


def test_projection_preserves_model_agnostic_provider_identity() -> None:
    result = build_mo_trace_projection(TRACE_ID, [_record()], checked_at=NOW)

    assert result["service_id"] == "nex-mo"
    assert result["summary"] == {
        "stage_count": 1,
        "by_family": {"GENERATION": 1},
        "by_status": {"SUCCEEDED": 1},
        "private_payload_included": False,
    }
    stage = result["stages"][0]
    assert stage["correlation_refs"] == {"provider_request_id": "provider-request-1376"}
    assert stage["safe_attributes"]["model_revision"] == "Qwen-revision"
    assert stage["safe_attributes"]["deployment_id"] == "dgx-generation-9111"
    assert "provider_url" not in str(result)


def test_projection_maps_retrieval_failure_and_optional_fields() -> None:
    record = _record(failed=True, capability="reranking")
    details = record["details"]
    assert isinstance(details, dict)
    for field in (
        "model_alias",
        "model_revision",
        "deployment_id",
        "provider_route_id",
        "provider_mode",
        "provider_request_id",
    ):
        details.pop(field)

    result = build_mo_trace_projection(TRACE_ID, [record], checked_at=NOW)

    stage = result["stages"][0]
    assert stage["stage_family"] == "RETRIEVAL"
    assert stage["stage_status"] == "FAILED"
    assert stage["safe_attributes"]["failure_code"] == "UPSTREAM_TIMEOUT"
    assert stage["safe_attributes"]["retryable"] is True
    assert stage["correlation_refs"] == {}

    details.pop("retryable")
    record["created_at"] = datetime(2026, 10, 6, 12, 1, tzinfo=UTC)
    without_retryable = build_mo_trace_projection(
        TRACE_ID,
        [record],
        checked_at=NOW,
    )
    assert "retryable" not in without_retryable["stages"][0]["safe_attributes"]


def test_projection_rejects_invalid_records_and_clock() -> None:
    assert str(MoTraceProjectionError("code", "detail")) == "detail"
    assert _timestamp(datetime(2026, 10, 6, 12, 30)) == "2026-10-06T12:30:00Z"
    assert _opaque_identifier("prefix", "bad id").startswith("prefix-")
    assert _safe_text("x" * 129).startswith("sha256:")
    with pytest.raises(MoTraceProjectionError) as clock_error:
        build_mo_trace_projection(
            TRACE_ID,
            [],
            checked_at=datetime(2026, 10, 6, 12, 30),
        )
    assert clock_error.value.error_code == "mo.trace_clock_invalid"

    for update, code in (
        ({"trace_id": "f" * 32}, "mo.trace_record_mismatch"),
        ({"event_type": "mo.runtime.ready"}, "mo.trace_record_kind_invalid"),
        ({"event_type": None}, "mo.trace_record_invalid"),
        ({"details": {}}, "mo.trace_record_invalid"),
        ({"created_at": None}, "mo.trace_record_timestamp_invalid"),
    ):
        record = _record()
        record.update(update)
        with pytest.raises(MoTraceProjectionError) as exc_info:
            build_mo_trace_projection(TRACE_ID, [record], checked_at=NOW)
        assert exc_info.value.error_code == code


def test_source_filters_non_provider_events() -> None:
    store = InMemoryOperationalEventStore()
    store.append(_record())
    store.append(
        build_operational_event(
            service_id="nex-mo",
            event_type="mo.runtime.ready",
            severity="INFO",
            message="ready",
            trace_id=TRACE_ID,
            created_at="2026-10-06T12:01:00Z",
        )
    )

    records = MoTraceProjectionSource(store).list_trace_records(TRACE_ID)

    assert len(records) == 1
    assert records[0]["event_type"] == "mo.provider.request.succeeded"


class FailingStore(InMemoryOperationalEventStore):
    def list_events(self, **kwargs):
        raise OperationalEventError(
            "operational_event.store_unavailable", "unavailable"
        )


def test_source_translates_store_failure() -> None:
    with pytest.raises(MoTraceProjectionError) as exc_info:
        MoTraceProjectionSource(FailingStore()).list_trace_records(TRACE_ID)
    assert exc_info.value.error_code == "mo.trace_source_unavailable"


def _authorization(
    audience: str = "nex-mo",
    service_id: str = "nex-ag",
    *,
    scope: bool = True,
) -> str:
    scopes = ["service:call"] + (["operations:read"] if scope else [])
    token = issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=scopes,
    )
    return f"Bearer {token.access_token}"


def _trace_client(source: MoTraceProjectionSource) -> TestClient:
    app = FastAPI()
    register_mo_trace_projection_routes(app, source=source, clock=lambda: NOW)
    return TestClient(app)


def test_route_requires_ag_operations_scope() -> None:
    client = _trace_client(MoTraceProjectionSource(InMemoryOperationalEventStore()))
    path = MO_TRACE_OPERATIONS_PATH.format(trace_id=TRACE_ID)

    assert client.get(path).status_code == 401
    assert (
        client.get(
            path, headers={"Authorization": _authorization(scope=False)}
        ).status_code
        == 401
    )
    forbidden = client.get(
        path, headers={"Authorization": _authorization(service_id="nex-cx")}
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "MO_OPERATIONS_CALLER_FORBIDDEN"
    assert (
        client.get(path, headers={"Authorization": _authorization()}).status_code == 200
    )


def test_route_translates_invalid_trace_and_source_failure() -> None:
    invalid = _trace_client(
        MoTraceProjectionSource(InMemoryOperationalEventStore())
    ).get(
        MO_TRACE_OPERATIONS_PATH.format(trace_id="invalid"),
        headers={"Authorization": _authorization()},
    )
    assert invalid.status_code == 422
    unavailable = _trace_client(MoTraceProjectionSource(FailingStore())).get(
        MO_TRACE_OPERATIONS_PATH.format(trace_id=TRACE_ID),
        headers={"Authorization": _authorization()},
    )
    assert unavailable.status_code == 503


def test_provider_routes_emit_success_and_failure_trace_events() -> None:
    store = InMemoryOperationalEventStore()
    app = FastAPI()
    app.state.nex_persistence = SimpleNamespace(operational_event_store=store)
    register_mock_provider_routes(app)
    client = TestClient(app)
    headers = {
        "Authorization": _authorization(service_id="nex-cx"),
        "X-Request-ID": "request-1376",
        "traceparent": f"00-{TRACE_ID}-0123456789abcdef-01",
    }

    success = client.post(
        "/api/v1/generations",
        headers=headers,
        json={"messages": [{"role": "user", "content": "safe prompt"}]},
    )
    failure = client.post(
        "/api/v1/embeddings",
        headers=headers,
        json={"inputs": []},
    )

    assert success.status_code == 200
    assert failure.status_code == 400
    events = store.list_events(service_id="nex-mo", trace_id=TRACE_ID, limit=10)
    assert {event["event_type"] for event in events} == {
        "mo.provider.request.succeeded",
        "mo.provider.request.failed",
    }
    succeeded = next(event for event in events if event["severity"] == "INFO")
    assert succeeded["details"]["provider_capability"] == "generation"
    assert succeeded["details"]["provider_request_id"]
    assert "safe prompt" not in str(events)
