from __future__ import annotations

import pytest

from nex_ae_api.workspace_chat_observability import observe_workspace_chat_state
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter


def _record(**overrides):
    return {
        "interaction_id": "interaction-1019",
        "workspace_id": "workspace-1019",
        "status": "PENDING",
        "cx_status": "PENDING",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-1019",
        "retrieval": None,
        "artifact_refs": [],
        **overrides,
    }


def test_observability_emits_private_content_free_state_events() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)

    pending = observe_workspace_chat_state(emitter, _record())
    failed = observe_workspace_chat_state(
        emitter,
        _record(
            status="FAILED",
            cx_status="FAILED",
            retrieval={"cx_retrieval_package_id": "private-package"},
            artifact_refs=[{"artifact_id": "artifact-1"}],
            failure={"error_code": "mo.provider_timeout", "retryable": True},
        ),
    )

    assert pending.ok is True
    assert failed.ok is True
    events = store.list_events(service_id="nex-ae-api", limit=10)
    assert {event["severity"] for event in events} == {"INFO", "ERROR"}
    failed_event = next(event for event in events if event["severity"] == "ERROR")
    assert failed_event["details"] == {
        "observability_schema_version": "ae_workspace_chat_observability.v2",
        "status": "FAILED",
        "cx_status": "FAILED",
        "workspace_bound": True,
        "retrieval_available": True,
        "artifact_ref_count": 1,
        "failure_code": "mo.provider_timeout",
        "retryable": True,
        "policy_available": False,
        "execution_mode": None,
        "compatibility_rule_id": None,
        "compatibility_rule_version": None,
        "policy_snapshot_hash": None,
        "prompt_binding_key": None,
        "prompt_version": None,
        "generation_policy_package_hash": None,
        "prompt_content_included": False,
        "response_content_included": False,
        "owner_identity_included": False,
        "provider_detail_included": False,
    }
    assert "private-package" not in str(failed_event)


def test_observability_projects_policy_lineage_without_private_content() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)
    private_prompt = "private policy prompt"
    result = observe_workspace_chat_state(
        emitter,
        _record(
            status="COMPLETED",
            cx_status="COMPLETED",
            generation={
                "output_preview": "private response",
                "policy": {
                    "runtime_policy_snapshot": {
                        "intent_decision": {"execution_mode": "DOCUMENT_SUMMARY"},
                        "compatibility_rule": {
                            "rule_id": "ae.document_summary.v1",
                            "rule_version": "v1",
                        },
                        "prompt_contract_ref": {
                            "prompt_binding_key": "ae.document_summary.default",
                            "prompt_version": "v1",
                        },
                        "policy_snapshot_hash": "a" * 64,
                    },
                    "generation_policy_package": {
                        "client_package_hash": "b" * 64,
                        "raw_prompt": private_prompt,
                    },
                },
            },
        ),
    )

    assert result.ok is True
    details = result.event["details"]
    assert details["policy_available"] is True
    assert details["execution_mode"] == "DOCUMENT_SUMMARY"
    assert details["compatibility_rule_id"] == "ae.document_summary.v1"
    assert details["compatibility_rule_version"] == "v1"
    assert details["policy_snapshot_hash"] == "a" * 64
    assert details["prompt_binding_key"] == "ae.document_summary.default"
    assert details["prompt_version"] == "v1"
    assert details["generation_policy_package_hash"] == "b" * 64
    assert private_prompt not in str(result.event)
    assert "private response" not in str(result.event)


def test_observability_is_idempotent_and_store_failure_is_non_blocking() -> None:
    store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=store)
    first = observe_workspace_chat_state(emitter, _record())
    second = observe_workspace_chat_state(emitter, _record())

    assert first.event["event_id"] == second.event["event_id"]
    assert len(store.events) == 1

    class BrokenStore:
        def append(self, event):
            raise RuntimeError("private database detail")

    failed = observe_workspace_chat_state(
        OperationalEventEmitter(service_id="nex-ae-api", store=BrokenStore()),
        _record(workspace_id=None, retrieval="invalid", artifact_refs="invalid"),
    )
    assert failed.ok is False
    assert failed.error_code == "operational_event.emit_failed"
    assert "private database detail" not in str(failed)


@pytest.mark.parametrize(
    "record",
    [
        _record(interaction_id=" "),
        _record(status=None),
    ],
)
def test_observability_rejects_missing_identity(record) -> None:
    emitter = OperationalEventEmitter(
        service_id="nex-ae-api",
        store=InMemoryOperationalEventStore(),
    )
    with pytest.raises(ValueError):
        observe_workspace_chat_state(emitter, record)
