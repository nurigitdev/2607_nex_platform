from __future__ import annotations

import pytest

from nex_ae_api.generated_response_observability import (
    AE_GENERATED_RESPONSE_PERSISTED_EVENT,
    observe_generated_response_persisted,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter
from test_nex_ae_generated_response_lineage import sample_bundle


def test_observability_emits_idempotent_metadata_only_response_event() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)
    lineage = sample_bundle(retry=True, repaired=True)["lineage"]

    first = observe_generated_response_persisted(
        emitter,
        lineage,
        request_id=" request-1068 ",
        trace_id="trace-1068",
    )
    second = observe_generated_response_persisted(
        emitter,
        lineage,
        request_id="request-1068",
        trace_id="trace-1068",
    )

    assert first.ok is second.ok is True
    assert first.event["event_id"] == second.event["event_id"]
    assert len(store.events) == 1
    event = store.list_events(event_type=AE_GENERATED_RESPONSE_PERSISTED_EVENT)[0]
    assert event["details"] == {
        "observability_schema_version": "ae_generated_response_observability.v1",
        "outcome": "PERSISTED",
        "lineage_type": "RETRY_CHILD",
        "content_type": "text/markdown; charset=utf-8",
        "content_size_bytes": 34,
        "content_available": True,
        "retrieval_package_linked": True,
        "structured_draft_linked": True,
        "citation_workflow_status": "REPAIRED",
        "bounded_repair_applied": True,
        "parent_response_linked": True,
        "prompt_content_included": False,
        "response_content_included": False,
        "storage_ref_included": False,
        "owner_identity_included": False,
        "provider_detail_included": False,
        "lineage_identifiers_included": False,
    }
    private_values = (
        lineage["response_id"],
        lineage["cx_generation_id"],
        lineage["retrieval_package_id"],
        lineage["content_sha256"],
        lineage["parent_response_id"],
        "Grounded answer with citation [1].",
        "ae://chat-responses/",
    )
    assert all(value not in str(event) for value in private_values)


def test_observability_normalizes_optional_context_and_store_failure() -> None:
    lineage = sample_bundle()["lineage"]
    emitted = observe_generated_response_persisted(
        OperationalEventEmitter(
            service_id="nex-ae-api", store=InMemoryOperationalEventStore()
        ),
        lineage,
        request_id=" ",
        trace_id=None,
    )
    assert emitted.event["request_id"] is None
    assert emitted.event["trace_id"] is None

    class BrokenStore:
        def append(self, event):
            raise RuntimeError("private storage detail")

    failed = observe_generated_response_persisted(
        OperationalEventEmitter(service_id="nex-ae-api", store=BrokenStore()),
        lineage,
        request_id=None,
        trace_id=None,
    )
    assert failed.ok is False
    assert failed.error_code == "operational_event.emit_failed"
    assert "private storage detail" not in str(failed)


def test_observability_rejects_invalid_response_lineage() -> None:
    lineage = sample_bundle()["lineage"]
    lineage["raw_content_included"] = True

    with pytest.raises(ValueError):
        observe_generated_response_persisted(
            OperationalEventEmitter(
                service_id="nex-ae-api", store=InMemoryOperationalEventStore()
            ),
            lineage,
            request_id=None,
            trace_id=None,
        )
