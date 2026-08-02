from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import nex_cx.generation as cx_generation
from nex_cx.generation import (
    GenerationExecutionStore,
    GenerationFacadeError,
    HttpMoGenerationClient,
    build_generation_execution_record,
    build_mo_generation_payload,
    compatibility_payload_from_generation_request,
    prompt_text_from_payload,
    register_generation_routes,
    retrieval_package_ref_from_payload,
    selected_evidence_ids_from_payload,
    validate_generation_request,
    validate_selected_evidence_ids,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


class FakeMoClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "payload": payload,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return {
            "mo_generation_id": "mo-gen-001",
            "alias": payload["alias"],
            "model_revision": "mock-llm-v1",
            "deployment_id": "mock-generation-local",
            "provider_type": "mock-generation",
            "output": {"type": "text", "text": "Mock CX response."},
            "finish_reason": "STOP",
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            "runtime_metadata": {
                "request_id": request_id,
                "trace_id": trace_id,
                "queue_ms": 0,
                "provider_ms": 12,
                "total_ms": 12,
                "route_id": "route-general-llm-default",
                "admission_decision": "ACCEPTED",
                "provider_request_id": "provider-001",
                "provider_url": "http://should-not-leak.local",
            },
        }


class FakeRetrievalPackageStore:
    def __init__(self, package: dict[str, Any] | None) -> None:
        self.package = package

    def get_retrieval_package(self, retrieval_package_id: str) -> dict[str, Any] | None:
        if self.package and self.package["retrieval_package_id"] == retrieval_package_id:
            return self.package
        return None


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def build_test_client() -> tuple[TestClient, FakeMoClient, GenerationExecutionStore]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = GenerationExecutionStore()
    mo_client = FakeMoClient()
    register_generation_routes(app, store=store, mo_client=mo_client)
    return TestClient(app), mo_client, store


def grounded_package(*, status: str = "READY", package_hash: str = "d" * 64) -> dict[str, Any]:
    return {
        "retrieval_package_id": "cx-ret-001",
        "package_hash": package_hash,
        "status": status,
        "evidence_items": [
            {"evidence_id": "evidence-001"},
            {"evidence_id": "evidence-002"},
        ],
    }


def grounded_payload(
    *,
    package_hash: str = "d" * 64,
    selected_evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": "Answer using evidence."}],
        "execution_mode": "GROUNDED_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "grounded-answer",
        "retrieval_package_ref": {
            "retrieval_package_id": "cx-ret-001",
            "package_hash": package_hash,
        },
    }
    if selected_evidence_ids is not None:
        payload["selected_evidence_ids"] = selected_evidence_ids
    return payload


def test_build_mo_generation_payload_hashes_prompt_metadata() -> None:
    payload = build_mo_generation_payload(
        {
            "prompt": "Summarize contract evidence.",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        },
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert payload["request_schema_version"] == "cx_mo_generation_request.v1"
    assert payload["alias"] == "general-llm-default"
    assert len(payload["provider_prompt_package_hash"]) == 64
    assert len(payload["metadata"]["generation_request_hash"]) == 64


def test_compatibility_payload_defaults_legacy_generation_to_general_answer() -> None:
    payload = compatibility_payload_from_generation_request({"prompt": "hello"})

    assert payload["execution_mode"] == "GENERAL_ANSWER"
    assert payload["generation_profile"] == "general-answer"
    assert compatibility_payload_from_generation_request(
        {"execution_mode": "GROUNDED_ANSWER"}
    ) == {"execution_mode": "GROUNDED_ANSWER"}


def test_prompt_text_from_payload_accepts_messages() -> None:
    assert (
        prompt_text_from_payload(
            {"messages": [{"role": "user", "content": "hello"}, {"content": "world"}]}
        )
        == "hello\nworld"
    )


def test_generation_endpoint_requires_service_claim() -> None:
    client, _, _ = build_test_client()

    response = client.post("/api/v1/generations", json={"prompt": "hello"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_generation_get_requires_service_claim() -> None:
    client, _, _ = build_test_client()

    response = client.get("/api/v1/generations/cx-gen-001")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_generation_endpoint_calls_mo_and_stores_safe_metadata() -> None:
    client, mo_client, store = build_test_client()

    response = client.post(
        "/api/v1/generations",
        json={
            "prompt": "Summarize private prompt text.",
            "alias": "general-llm-default",
            "provider_capability": "generation",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["mo_generation_id"] == "mo-gen-001"
    assert payload["mo_runtime_metadata"]["route_id"] == "route-general-llm-default"
    assert "provider_url" not in payload["mo_runtime_metadata"]
    assert "Summarize private prompt text." not in str(payload["request_metadata"])
    assert store.get(payload["cx_generation_id"]) == payload
    assert mo_client.calls[0]["payload"]["prompt"] == "Summarize private prompt text."
    assert payload["request_metadata"]["compatibility_rule_id"] == (
        "compat-general-answer-v1"
    )
    assert payload["request_metadata"]["grounding_required"] is False


def test_grounded_generation_endpoint_validates_retrieval_package_and_lineage() -> None:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = GenerationExecutionStore()
    mo_client = FakeMoClient()
    register_generation_routes(
        app,
        store=store,
        mo_client=mo_client,
        retrieval_store=FakeRetrievalPackageStore(grounded_package()),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/generations",
        json=grounded_payload(selected_evidence_ids=["evidence-001"]),
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_metadata"]["compatibility_rule_id"] == (
        "compat-grounded-answer-v1"
    )
    assert payload["request_metadata"]["retrieval_package_id"] == "cx-ret-001"
    assert payload["request_metadata"]["selected_evidence_count"] == 1
    assert store.get(payload["cx_generation_id"]) == payload


def test_generation_endpoint_returns_problem_for_missing_prompt() -> None:
    client, _, _ = build_test_client()

    response = client.post(
        "/api/v1/generations",
        json={"alias": "general-llm-default"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "cx.generation_request_invalid"


def test_grounded_generation_rejects_missing_retrieval_ref() -> None:
    client, _, _ = build_test_client()

    response = client.post(
        "/api/v1/generations",
        json={
            "prompt": "hello",
            "execution_mode": "GROUNDED_ANSWER",
            "generation_profile": "grounded-answer",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "cx.retrieval_package_ref_required"


def test_validate_generation_request_rejects_missing_store_hash_and_not_ready() -> None:
    with pytest.raises(GenerationFacadeError) as missing_store:
        validate_generation_request(grounded_payload(), retrieval_store=None)
    assert missing_store.value.error_code == "cx.retrieval_package_store_unavailable"
    assert missing_store.value.retryable is True

    with pytest.raises(GenerationFacadeError) as missing_package:
        validate_generation_request(
            grounded_payload(),
            retrieval_store=FakeRetrievalPackageStore(None),
        )
    assert missing_package.value.status_code == 404

    with pytest.raises(GenerationFacadeError) as hash_mismatch:
        validate_generation_request(
            grounded_payload(package_hash="e" * 64),
            retrieval_store=FakeRetrievalPackageStore(grounded_package()),
        )
    assert hash_mismatch.value.error_code == "cx.retrieval_package_hash_mismatch"

    with pytest.raises(GenerationFacadeError) as not_ready:
        validate_generation_request(
            grounded_payload(),
            retrieval_store=FakeRetrievalPackageStore(grounded_package(status="NO_ANSWER")),
        )
    assert not_ready.value.error_code == "cx.retrieval_package_not_ready"


def test_retrieval_package_ref_and_selected_evidence_validation() -> None:
    assert retrieval_package_ref_from_payload({}) is None
    assert retrieval_package_ref_from_payload(grounded_payload()) == {
        "retrieval_package_id": "cx-ret-001",
        "package_hash": "d" * 64,
    }
    assert selected_evidence_ids_from_payload({"selected_evidence_ids": None}) == []
    assert selected_evidence_ids_from_payload(
        {"selected_evidence_ids": [" evidence-001 "]}
    ) == ["evidence-001"]
    validate_selected_evidence_ids(
        {"selected_evidence_ids": ["evidence-001"]},
        grounded_package(),
    )

    invalid_refs = [
        {"retrieval_package_ref": []},
        {"retrieval_package_ref": {"retrieval_package_id": "", "package_hash": "d" * 64}},
        {"retrieval_package_ref": {"retrieval_package_id": "x", "package_hash": "bad"}},
    ]
    for payload in invalid_refs:
        try:
            retrieval_package_ref_from_payload(payload)
        except GenerationFacadeError as exc:
            assert exc.error_code == "cx.retrieval_package_ref_invalid"
        else:
            raise AssertionError("expected GenerationFacadeError")

    with pytest.raises(GenerationFacadeError) as invalid_ids:
        selected_evidence_ids_from_payload({"selected_evidence_ids": [""]})
    assert invalid_ids.value.error_code == "cx.selected_evidence_invalid"

    with pytest.raises(GenerationFacadeError) as missing_evidence:
        validate_selected_evidence_ids(
            {"selected_evidence_ids": ["missing"]},
            grounded_package(),
        )
    assert missing_evidence.value.error_code == "cx.selected_evidence_not_in_package"


def test_generation_record_can_be_read_back() -> None:
    client, _, _ = build_test_client()
    created = client.post(
        "/api/v1/generations",
        json={"prompt": "hello"},
        headers=auth_headers(),
    ).json()

    response = client.get(
        f"/api/v1/generations/{created['cx_generation_id']}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["cx_generation_id"] == created["cx_generation_id"]


def test_generation_read_returns_problem_for_unknown_record() -> None:
    client, _, _ = build_test_client()

    response = client.get(
        "/api/v1/generations/missing",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.generation_not_found"


def test_generation_endpoint_rejects_provider_private_fields() -> None:
    client, _, _ = build_test_client()

    response = client.post(
        "/api/v1/generations",
        json={"prompt": "hello", "provider_url": "http://internal"},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "cx.provider_field_forbidden"


def test_http_mo_generation_client_posts_with_mock_token(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return httpx.Response(
            200,
            json={
                "mo_generation_id": "mo-gen-001",
                "alias": "general-llm-default",
            },
        )

    monkeypatch.setattr(cx_generation.httpx, "post", fake_post)

    response = HttpMoGenerationClient(base_url="http://mo.test").create_generation(
        {"prompt": "hello"},
        request_id="req-1",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert response["mo_generation_id"] == "mo-gen-001"
    assert calls[0]["args"] == ("http://mo.test/api/v1/generations",)
    assert calls[0]["kwargs"]["headers"]["X-Service-ID"] == "nex-cx"
    assert calls[0]["kwargs"]["headers"]["Authorization"].startswith("Bearer ")


def test_http_mo_generation_client_maps_problem_response(
    monkeypatch,
) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(
            422,
            json={
                "error_code": "mo.capability_not_supported",
                "detail": "Unsupported capability.",
                "retryable": False,
            },
        )

    monkeypatch.setattr(cx_generation.httpx, "post", fake_post)

    try:
        HttpMoGenerationClient(base_url="http://mo.test").create_generation(
            {"prompt": "hello"},
            request_id="req-1",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )
    except GenerationFacadeError as exc:
        assert exc.status_code == 422
        assert exc.error_code == "mo.capability_not_supported"
    else:
        raise AssertionError("expected GenerationFacadeError")


def test_http_mo_generation_client_handles_non_object_problem_response(
    monkeypatch,
) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(503, json=["not", "an", "object"])

    monkeypatch.setattr(cx_generation.httpx, "post", fake_post)

    try:
        HttpMoGenerationClient(base_url="http://mo.test").create_generation(
            {"prompt": "hello"},
            request_id="req-1",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )
    except GenerationFacadeError as exc:
        assert exc.error_code == "mo.request_failed"
    else:
        raise AssertionError("expected GenerationFacadeError")


def test_build_generation_execution_record_keeps_safe_runtime_keys_only() -> None:
    record = build_generation_execution_record(
        source_payload={"prompt": "hello"},
        mo_payload={
            "cx_generation_id": "cx-gen-001",
            "provider_capability": "generation",
            "provider_prompt_package_hash": "a" * 64,
            "metadata": {"generation_request_hash": "b" * 64},
            "response_format": {"type": "text"},
        },
        mo_response={
            "mo_generation_id": "mo-gen-001",
            "alias": "general-llm-default",
            "output": {"text": "answer"},
            "finish_reason": "STOP",
            "runtime_metadata": {
                "request_id": "req",
                "trace_id": "trace",
                "route_id": "route",
                "provider_url": "http://internal",
            },
        },
        request_id="req",
        trace_id="trace",
    )

    assert record["response_metadata"]["output_preview"] == "answer"
    assert "provider_url" not in record["mo_runtime_metadata"]
