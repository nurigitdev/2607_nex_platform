from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_cx.generation import GenerationExecutionStore, register_generation_routes
from nex_cx.progress import (
    build_cx_generation_failure_progress_events,
    build_generation_progress_event,
    deterministic_event_id,
    safe_progress_details,
    safe_usage_summary,
    selected_evidence_count,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class ProgressMoClient:
    def __init__(self, output_text: str = "Grounded answer [1]") -> None:
        self.output_text = output_text

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {
            "mo_generation_id": "mo-gen-001",
            "alias": payload["alias"],
            "output": {"type": "text", "text": self.output_text},
            "finish_reason": "STOP",
            "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
            "runtime_metadata": {
                "request_id": request_id,
                "trace_id": trace_id,
                "provider_url": "http://should-not-leak.local",
            },
        }


class RetrievalStore:
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
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def retrieval_package() -> dict[str, Any]:
    return {
        "retrieval_package_id": "cx-ret-001",
        "package_hash": "d" * 64,
        "status": "READY",
        "evidence_items": [
            {
                "evidence_id": "evidence-001",
                "citation_label": "[1]",
            },
            {
                "evidence_id": "evidence-002",
                "citation_label": "[2]",
            },
        ],
    }


def grounded_payload() -> dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": "Answer with citation."}],
        "execution_mode": "GROUNDED_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "grounded-answer",
        "retrieval_package_ref": {
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "d" * 64,
        },
        "selected_evidence_ids": ["evidence-001"],
    }


def build_client(
    *,
    output_text: str = "Grounded answer [1]",
    package: dict[str, Any] | None = None,
) -> tuple[TestClient, GenerationExecutionStore]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = GenerationExecutionStore()
    register_generation_routes(
        app,
        store=store,
        mo_client=ProgressMoClient(output_text),
        retrieval_store=RetrievalStore(package),
    )
    return TestClient(app), store


def test_progress_event_builder_uses_stable_ids_and_redacted_details() -> None:
    event = build_generation_progress_event(
        event_type="generation.prompt.packaged",
        event_source_service="nex-cx",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        sequence_no=3,
        job_status="RUNNING",
        cx_generation_id="cx-gen-001",
        details={
            "provider_prompt_package_hash": "a" * 64,
            "raw_prompt": "private prompt",
            "nested": {"api_key": "secret", "safe_count": 2},
            "items": [{"raw_output": "private output", "ok": True}],
        },
        occurred_at="2026-08-02T00:00:00Z",
    )

    assert event["event_id"] == deterministic_event_id(
        event_source_service="nex-cx",
        cx_generation_id="cx-gen-001",
        job_id=None,
        event_type="generation.prompt.packaged",
        sequence_no=3,
    )
    assert event["current_stage"] == "PROMPT_ASSEMBLING"
    assert event["message_key"] == "generation.progress.prompt_packaged"
    assert event["details"] == {
        "provider_prompt_package_hash": "a" * 64,
        "nested": {"safe_count": 2},
        "items": [{"ok": True}],
    }


def test_progress_event_builder_rejects_invalid_shape_values() -> None:
    valid = {
        "event_source_service": "nex-cx",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "sequence_no": 1,
        "job_status": "RUNNING",
        "cx_generation_id": "cx-gen-001",
    }

    with pytest.raises(ValueError, match="event type"):
        build_generation_progress_event(event_type="unsupported", **valid)
    with pytest.raises(ValueError, match="job status"):
        build_generation_progress_event(
            event_type="generation.completed",
            job_status="SUCCEEDED",
            **{key: value for key, value in valid.items() if key != "job_status"},
        )
    with pytest.raises(ValueError, match="progress mode"):
        build_generation_progress_event(
            event_type="generation.completed",
            progress_mode="UNKNOWN",
            **valid,
        )
    with pytest.raises(ValueError, match="positive"):
        build_generation_progress_event(
            event_type="generation.completed",
            sequence_no=0,
            **{key: value for key, value in valid.items() if key != "sequence_no"},
        )
    with pytest.raises(ValueError, match="between"):
        build_generation_progress_event(
            event_type="generation.completed",
            progress_percent=101,
            **valid,
        )
    with pytest.raises(ValueError, match="COMPLETED"):
        build_generation_progress_event(
            event_type="generation.completed",
            current_stage="GENERATING",
            **valid,
        )
    with pytest.raises(ValueError, match="current_stage"):
        build_generation_progress_event(event_type="generation.failed", **valid)


def test_safe_progress_helpers_handle_nested_and_non_dict_values() -> None:
    class StableObject:
        def __str__(self) -> str:
            return "stable-object"

    assert safe_usage_summary({"input_tokens": 1, "output_tokens": -1, "ignored": 7}) == {
        "input_tokens": 1
    }
    assert safe_usage_summary(["not", "dict"]) == {}
    assert safe_progress_details(
        {
            "safe": StableObject(),
            "password_hint": "hidden",
            "provider_endpoint": "http://hidden.local",
        }
    ) == {"safe": "stable-object"}
    assert selected_evidence_count({"selected_evidence_ids": ["a", "", 7, "b"]}) == 2
    assert selected_evidence_count({"selected_evidence_ids": None}) == 0
    assert selected_evidence_count({"selected_evidence_ids": "not-list"}) == 0


def test_generation_events_route_returns_grounded_timeline() -> None:
    client, store = build_client(package=retrieval_package())

    created = client.post(
        "/api/v1/generations",
        json=grounded_payload(),
        headers=auth_headers(),
    )
    payload = created.json()
    response = client.get(
        f"/api/v1/generations/{payload['cx_generation_id']}/events",
        headers=auth_headers(),
    )

    assert created.status_code == 200
    assert response.status_code == 200
    timeline = response.json()
    events = timeline["events"]
    assert timeline["pagination"] == {"next_cursor": None, "event_count": 7}
    assert [event["sequence_no"] for event in events] == list(range(1, 8))
    assert [event["event_type"] for event in events] == [
        "generation.request.accepted",
        "generation.retrieval.ready",
        "generation.prompt.packaged",
        "generation.provider.completed",
        "generation.draft.validating",
        "generation.citation.validating",
        "generation.completed",
    ]
    assert events[1]["details"]["selected_evidence_count"] == 1
    assert events[3]["mo_generation_id"] == "mo-gen-001"
    assert events[-1]["job_status"] == "COMPLETED"
    assert "Answer with citation." not in str(events)
    assert "should-not-leak" not in str(events)
    assert store.get_progress_events(payload["cx_generation_id"]) == events


def test_generation_events_route_skips_retrieval_for_general_answer() -> None:
    client, _ = build_client(output_text="General answer.")

    created = client.post(
        "/api/v1/generations",
        json={"prompt": "private general prompt"},
        headers=auth_headers(),
    )
    payload = created.json()
    response = client.get(
        f"/api/v1/generations/{payload['cx_generation_id']}/events",
        headers=auth_headers(),
    )

    assert created.status_code == 200
    assert response.status_code == 200
    assert "generation.retrieval.ready" not in {
        event["event_type"] for event in response.json()["events"]
    }
    assert response.json()["pagination"]["event_count"] == 6


def test_failure_progress_events_include_policy_lineage_without_raw_prompt() -> None:
    mo_payload = {
        "cx_generation_id": "cx-gen-timeout-001",
        "provider_prompt_package_hash": "a" * 64,
        "metadata": {"generation_request_hash": "b" * 64},
        "response_format": {"type": "text"},
    }
    failure_record = {
        "failure": {
            "failure_code": "mo.provider_timeout",
            "failure_class": "provider_timeout",
            "owner_service": "nex-cx",
            "failed_stage": "GENERATING",
            "retryable": True,
            "recovery_policy_id": "recovery-mo-provider-timeout-retry-v1",
            "recovery_policy_hash": "e" * 64,
        },
        "recovery_lineage": {
            "default_recovery_action": "retry",
            "attempt_no": 2,
            "reuse_retrieval_package": True,
        },
    }

    events = build_cx_generation_failure_progress_events(
        source_payload=grounded_payload(),
        mo_payload=mo_payload,
        failure_record=failure_record,
        compatibility_rule={
            "execution_mode": "GROUNDED_ANSWER",
            "generation_profile": "grounded-answer",
            "compatibility_rule_id": "compat-grounded-answer-v1",
            "grounding_required": True,
        },
        retrieval_package=retrieval_package(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert [event["event_type"] for event in events] == [
        "generation.request.accepted",
        "generation.retrieval.ready",
        "generation.prompt.packaged",
        "generation.failed",
    ]
    assert events[-1]["job_status"] == "FAILED"
    assert events[-1]["current_stage"] == "GENERATING"
    assert events[-1]["details"]["attempt_no"] == 2
    assert events[-1]["details"]["reuse_retrieval_package"] is True
    assert "Answer with citation." not in str(events)


def test_generation_events_route_requires_auth_and_reports_missing_generation() -> None:
    client, _ = build_client()

    unauthorized = client.get("/api/v1/generations/cx-gen-001/events")
    missing = client.get(
        "/api/v1/generations/cx-gen-001/events",
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "cx.generation_not_found"
