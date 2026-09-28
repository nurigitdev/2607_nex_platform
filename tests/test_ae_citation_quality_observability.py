from __future__ import annotations

import json
from typing import Any

import pytest

from nex_ae_api.citation_quality_observability import (
    AE_CITATION_QUALITY_OBSERVABILITY_SCHEMA_VERSION,
    AE_CITATION_QUALITY_WORKFLOW_EVENT,
    observe_citation_quality_workflow,
)
from nex_ae_api.citation_quality_workflow import build_citation_quality_workflow
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter


def _workflow(status: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "grounding_required": status != "NOT_REQUIRED",
        "draft_validation_status": (
            "INVALID" if status == "ATTENTION_REQUIRED" else "VALIDATED"
        ),
        "grounded_response_quality_status": (
            "FAIL" if status == "ATTENTION_REQUIRED" else "PASS"
        ),
        "grounded_response_quality_issue_count": (
            2 if status == "ATTENTION_REQUIRED" else 0
        ),
    }
    if status == "REPAIRED":
        metadata["citation_repair"] = {
            "repair_schema_version": "cx_citation_repair.v1",
            "attempted": True,
            "attempt_count": 1,
            "max_attempts": 1,
            "trigger_error_code": "cx.citation_required_missing",
            "same_retrieval_package": True,
            "original_provider_prompt_package_hash": "a" * 64,
            "effective_provider_prompt_package_hash": "b" * 64,
            "invalid_output_included": False,
        }
    return build_citation_quality_workflow(
        {
            "cx_generation_id": "generation-observe",
            "request_metadata": metadata,
        },
        interaction_id="interaction-observe",
    )


@pytest.mark.parametrize(
    ("status", "outcome", "severity"),
    [
        ("NOT_REQUIRED", "CITATION_NOT_REQUIRED", "INFO"),
        ("VALIDATED", "CITATION_VALIDATED", "INFO"),
        ("REPAIRED", "BOUNDED_REPAIR_SUCCEEDED", "INFO"),
        ("ATTENTION_REQUIRED", "ATTENTION_REQUIRED", "WARNING"),
    ],
)
def test_citation_observability_emits_metadata_only_outcomes(
    status: str,
    outcome: str,
    severity: str,
) -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)

    result = observe_citation_quality_workflow(
        emitter,
        _workflow(status),
        request_id=" request-observe ",
        trace_id="a" * 32,
    )

    assert result.ok is True
    event = result.event
    assert event["event_type"] == AE_CITATION_QUALITY_WORKFLOW_EVENT
    assert event["severity"] == severity
    assert event["request_id"] == "request-observe"
    assert event["details"]["observability_schema_version"] == (
        AE_CITATION_QUALITY_OBSERVABILITY_SCHEMA_VERSION
    )
    assert event["details"]["outcome"] == outcome
    assert event["details"]["workflow_status"] == status
    assert event["details"]["response_content_included"] is False
    assert event["details"]["owner_identity_included"] is False
    serialized = json.dumps(event)
    assert "prompt text" not in serialized
    assert "response text" not in serialized
    assert "evidence text" not in serialized


def test_citation_observability_is_idempotent_and_rejects_invalid_workflow() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)
    workflow = _workflow("REPAIRED")

    first = observe_citation_quality_workflow(
        emitter,
        workflow,
        request_id=None,
        trace_id=" ",
    )
    second = observe_citation_quality_workflow(
        emitter,
        workflow,
        request_id=None,
        trace_id=" ",
    )

    assert first.event["event_id"] == second.event["event_id"]
    assert len(store.events) == 1
    with pytest.raises(ValueError):
        observe_citation_quality_workflow(
            emitter,
            {},
            request_id=None,
            trace_id=None,
        )


def test_citation_observability_store_failure_is_non_blocking() -> None:
    class BrokenStore:
        def append(self, event):
            raise RuntimeError("private persistence detail")

    result = observe_citation_quality_workflow(
        OperationalEventEmitter(service_id="nex-ae-api", store=BrokenStore()),
        _workflow("VALIDATED"),
        request_id=None,
        trace_id=None,
    )

    assert result.ok is False
    assert result.error_code == "operational_event.emit_failed"
    assert "private persistence detail" not in str(result)
