from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import validate_contracts
from nex_cx.generation import (
    GenerationExecutionStore,
    GenerationFacadeError,
    register_generation_routes,
)
from nex_cx.generation_observability import (
    CX_GENERATION_COMPLETED_EVENT,
    CX_GENERATION_FAILED_EVENT,
    CX_GENERATION_READ_FAILED_EVENT,
    CX_GENERATION_REPLAYED_EVENT,
    _failure_event_id,
    _outcome_event_id,
    observe_generation_outcome,
    observe_generation_request_failure,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "96800000000000000000000000000001"
PRIVATE_PROMPT = "PRIVATE_GENERATION_PROMPT_0968"
PRIVATE_OUTPUT = "PRIVATE_GENERATION_OUTPUT_0968"
PRIVATE_OWNER = "PRIVATE_OWNER_0968"


class _GenerationClient:
    def __init__(self, failure: GenerationFacadeError | None = None) -> None:
        self.failure = failure

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        if self.failure is not None:
            raise self.failure
        return {
            "mo_generation_id": "mo-generation-0968",
            "alias": payload["alias"],
            "model_revision": "Qwen3.5-4B",
            "deployment_id": "dgx-generation",
            "provider_type": "mock-generation",
            "output": {"type": "text", "text": PRIVATE_OUTPUT},
            "finish_reason": "STOP",
            "usage": {"input_tokens": 9, "output_tokens": 7, "total_tokens": 16},
            "runtime_metadata": {"provider_ms": 12, "total_ms": 14},
        }


class _ExplodingEventStore:
    def append(self, _event: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("PRIVATE_EVENT_STORE_FAILURE")


def _record(*, status: str = "COMPLETED") -> dict[str, Any]:
    failed = status == "FAILED"
    return {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": "cx-generation-0968",
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": "request-0968",
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "tenant_ref_id": "PRIVATE_TENANT_0968",
        "owner_subject_ref_id": PRIVATE_OWNER,
        "request_metadata": {
            "compatibility_rule_id": "compat-general-answer-v1",
            "grounding_required": False,
            "selected_evidence_count": 0,
            "raw_prompt": PRIVATE_PROMPT,
        },
        "response_metadata": {
            "finish_reason": "ERROR" if failed else "STOP",
            "output_hash": None if failed else "c" * 64,
            "output_preview": PRIVATE_OUTPUT,
        },
        "private_output_metadata": {
            "output_sha256": "c" * 64,
            "output_size_bytes": 29,
            "output_storage_uri": "file:///private/output",
        },
        "usage": {} if failed else {"prompt_tokens": 9, "completion_tokens": 7},
        "failure": (
            {
                "failure_code": "mo.provider_timeout",
                "failed_stage": "GENERATING",
                "retryable": True,
                "safe_message": "must not be copied",
            }
            if failed
            else None
        ),
    }


def _emitter() -> tuple[OperationalEventEmitter, InMemoryOperationalEventStore]:
    store = InMemoryOperationalEventStore()
    return OperationalEventEmitter(service_id="nex-cx", store=store), store


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": "tenant-0968",
        "X-NEX-Subject-ID": PRIVATE_OWNER,
        "X-Request-ID": "request-0968",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def test_terminal_events_are_deterministic_and_metadata_only() -> None:
    emitter, events = _emitter()

    completed = observe_generation_outcome(emitter, _record())
    duplicate = observe_generation_outcome(emitter, _record())
    failed = observe_generation_outcome(emitter, _record(status="FAILED"))

    assert completed.ok is duplicate.ok is failed.ok is True
    assert duplicate.event == completed.event
    assert len(events.list_events()) == 2
    success = events.list_events(event_type=CX_GENERATION_COMPLETED_EVENT)[0]
    assert success["event_id"] == _outcome_event_id(
        generation_id="cx-generation-0968",
        status="COMPLETED",
        replayed=False,
    )
    assert success["details"]["output_sha256"] == "c" * 64
    assert success["details"]["output_size_bytes"] == 29
    assert success["details"]["input_unit_count"] == 9
    assert success["details"]["output_unit_count"] == 7
    failure = events.list_events(event_type=CX_GENERATION_FAILED_EVENT)[0]
    assert failure["severity"] == "ERROR"
    assert failure["details"]["error_code"] == "mo.provider_timeout"
    assert failure["details"]["retryable"] is True
    serialized = json.dumps(events.list_events())
    assert PRIVATE_PROMPT not in serialized
    assert PRIVATE_OUTPUT not in serialized
    assert PRIVATE_OWNER not in serialized
    assert "output_storage_uri" not in serialized


def test_replay_and_sparse_outcomes_normalize_safe_metadata() -> None:
    emitter, events = _emitter()

    replay = observe_generation_outcome(emitter, _record(), replayed=True)
    sparse = observe_generation_outcome(
        emitter,
        {
            "cx_generation_id": " ",
            "status": " ",
            "request_metadata": [],
            "response_metadata": None,
            "content_ref": {"size_bytes": True},
            "usage": {"total_tokens": True},
        },
    )

    assert replay.event is not None
    assert replay.event["event_type"] == CX_GENERATION_REPLAYED_EVENT
    assert replay.event["details"]["replayed"] is True
    assert sparse.event is not None
    assert sparse.event["subject_ref"]["id"] == "unknown"
    assert sparse.event["details"]["generation_status"] == "UNKNOWN"
    assert sparse.event["details"]["selected_evidence_count"] == 0
    assert sparse.event["details"]["output_size_bytes"] is None
    assert sparse.event["details"]["total_unit_count"] is None
    assert len(events.list_events()) == 2


def test_request_failure_events_distinguish_read_and_create_failures() -> None:
    emitter, events = _emitter()

    read = observe_generation_request_failure(
        emitter,
        operation="content_read",
        error_code="cx.generation_content_integrity_failed",
        status_code=409,
        retryable=False,
        trace_id=TRACE_ID,
        request_id="request-0968",
        cx_generation_id="cx-generation-0968",
    )
    create = observe_generation_request_failure(
        emitter,
        operation=" ",
        error_code=" ",
        status_code=503,
        retryable=True,
        trace_id=None,
        request_id=None,
    )

    assert read.event is not None
    assert read.event["event_type"] == CX_GENERATION_READ_FAILED_EVENT
    assert read.event["severity"] == "WARNING"
    assert read.event["event_id"] == _failure_event_id(
        operation="content_read",
        error_code="cx.generation_content_integrity_failed",
        cx_generation_id="cx-generation-0968",
        trace_id=TRACE_ID,
        request_id="request-0968",
    )
    assert create.event is not None
    assert create.event["event_type"] == CX_GENERATION_FAILED_EVENT
    assert create.event["severity"] == "ERROR"
    assert create.event["subject_ref"] is None
    assert create.event["details"]["operation"] == "unknown"
    assert create.event["details"]["error_code"] == "cx.generation_failed"
    assert len(events.list_events()) == 2


def test_event_store_failure_never_changes_generation_response() -> None:
    emitter = OperationalEventEmitter(
        service_id="nex-cx",
        store=_ExplodingEventStore(),  # type: ignore[arg-type]
    )
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(
        app,
        store=GenerationExecutionStore(),
        mo_client=_GenerationClient(),
        event_emitter=emitter,
    )

    response = TestClient(app).post(
        "/api/v1/generations",
        headers=_headers(),
        json={"prompt": PRIVATE_PROMPT},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


def test_generation_routes_emit_terminal_and_read_failure_events() -> None:
    emitter, events = _emitter()
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(
        app,
        store=GenerationExecutionStore(),
        mo_client=_GenerationClient(),
        event_emitter=emitter,
    )
    client = TestClient(app)

    completed = client.post(
        "/api/v1/generations",
        headers=_headers(),
        json={"prompt": PRIVATE_PROMPT},
    )
    metadata = client.get(
        f"/api/v1/generations/{completed.json()['cx_generation_id']}",
        headers=_headers(),
    )
    unavailable = client.get(
        "/api/v1/generations/cx-generation-0968/content",
        headers=_headers(),
    )
    unauthenticated = client.post(
        "/api/v1/generations",
        json={"prompt": PRIVATE_PROMPT},
    )

    assert completed.status_code == 200
    assert metadata.status_code == 200
    validate_contracts.validate_payload(
        validate_contracts.load_structured_file(
            ROOT
            / "contracts/schemas/generation/cx_generation_read_model.v1.schema.json"
        ),
        metadata.json(),
    )
    assert PRIVATE_OUTPUT not in metadata.text
    assert unavailable.status_code == 503
    assert unauthenticated.status_code == 401
    assert len(events.list_events(event_type=CX_GENERATION_COMPLETED_EVENT)) == 1
    read_failures = events.list_events(event_type=CX_GENERATION_READ_FAILED_EVENT)
    assert len(read_failures) == 1
    assert read_failures[0]["details"]["operation"] == "content_read"
    assert len(events.list_events()) == 2


def test_generation_routes_emit_provider_and_admission_failures() -> None:
    emitter, events = _emitter()
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_generation_routes(
        app,
        store=GenerationExecutionStore(),
        mo_client=_GenerationClient(
            GenerationFacadeError(
                status_code=504,
                error_code="mo.provider_timeout",
                detail="provider private failure",
                retryable=True,
            )
        ),
        event_emitter=emitter,
    )
    client = TestClient(app)

    provider_failure = client.post(
        "/api/v1/generations",
        headers=_headers(),
        json={"prompt": PRIVATE_PROMPT},
    )
    admission_failure = client.post(
        "/api/v1/generations",
        headers=_headers(),
        json={},
    )

    assert provider_failure.status_code == 504
    assert admission_failure.status_code == 400
    failures = events.list_events(event_type=CX_GENERATION_FAILED_EVENT)
    assert len(failures) == 2
    assert {event["details"].get("error_code") for event in failures} == {
        "mo.provider_timeout",
        "cx.generation_request_invalid",
    }
    assert PRIVATE_PROMPT not in json.dumps(failures)


def test_generation_read_contracts_and_openapi_bindings() -> None:
    for schema_name, example_name, negative_name in (
        (
            "cx_generation_read_model.v1.schema.json",
            "cx_generation_read_model.mock_success.json",
            "cx_generation_read_model.storage_uri_leak.json",
        ),
        (
            "cx_generation_content.v1.schema.json",
            "cx_generation_content.mock_success.json",
            "cx_generation_content.owner_scope_disabled.json",
        ),
    ):
        schema = validate_contracts.load_structured_file(
            ROOT / "contracts/schemas/generation" / schema_name
        )
        example = validate_contracts.load_structured_file(
            ROOT / "contracts/examples/generation" / example_name
        )
        negative = validate_contracts.load_structured_file(
            ROOT / "contracts/tests/negative/generation" / negative_name
        )
        validate_contracts.validate_payload(schema, example)
        try:
            validate_contracts.validate_payload(schema, negative)
        except validate_contracts.ValidationError:
            pass
        else:
            raise AssertionError(
                f"negative fixture unexpectedly passed: {negative_name}"
            )

    openapi = validate_contracts.load_structured_file(
        ROOT / "contracts/openapi/nex-cx.openapi.yaml"
    )
    metadata_response = openapi["paths"]["/api/v1/generations/{cx_generation_id}"][
        "get"
    ]["responses"]["200"]
    content_response = openapi["paths"][
        "/api/v1/generations/{cx_generation_id}/content"
    ]["get"]["responses"]["200"]
    assert metadata_response["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/CxGenerationReadModel"
    )
    assert content_response["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/CxGenerationContent"
    )
