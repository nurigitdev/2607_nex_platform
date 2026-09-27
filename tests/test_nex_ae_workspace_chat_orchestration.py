from __future__ import annotations

import pytest

from nex_ae_api.chat import ChatInteractionStore
from nex_ae_api.workspace import WorkspaceStateStore
from nex_ae_api.workspace_chat_orchestration import (
    WorkspaceChatOrchestrationError,
    append_workspace_chat_activity,
    bind_workspace_chat_request,
    idempotent_chat_record,
)
from nex_ae_api.workspace_persistence import WorkspaceRepositoryError


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
CHAT_DOCUMENT_ID = "22222222-2222-4222-8222-222222222222"


def workspace_store() -> WorkspaceStateStore:
    store = WorkspaceStateStore()
    store.create_workspace(
        payload={
            "workspace_id": WORKSPACE_ID,
            "chat_document_id": CHAT_DOCUMENT_ID,
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        request_id="workspace-request",
        trace_id=TRACE_ID,
    )
    return store


def payload(**overrides):
    return {
        "workspace_id": WORKSPACE_ID,
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "owner_user_id": "user-a",
        "user_message": "Summarize the workspace.",
        **overrides,
    }


def test_binding_derives_identity_and_workspace_document() -> None:
    first = bind_workspace_chat_request(
        payload(), trace_id=TRACE_ID, workspace_store=workspace_store()
    )
    repeated = bind_workspace_chat_request(
        payload(), trace_id=TRACE_ID, workspace_store=workspace_store()
    )

    assert first.interaction_id == repeated.interaction_id
    assert first.user_message_hash == repeated.user_message_hash
    assert first.payload["chat_document_id"] == CHAT_DOCUMENT_ID
    assert first.workspace["workspace_id"] == WORKSPACE_ID


def test_legacy_binding_derives_document_without_workspace() -> None:
    binding = bind_workspace_chat_request(
        {"user_message": "hello"},
        trace_id=TRACE_ID,
        workspace_store=None,
    )

    assert binding.workspace is None
    assert binding.payload["chat_document_id"]
    assert binding.payload["interaction_id"] == binding.interaction_id


@pytest.mark.parametrize(
    ("request_payload", "store", "error_code", "status_code"),
    [
        ({"user_message": " "}, None, "ae.chat_request_invalid", 400),
        (
            {"user_message": "hello", "workspace_id": " "},
            None,
            "ae.workspace_id_invalid",
            400,
        ),
        (
            {"user_message": "hello", "workspace_id": WORKSPACE_ID},
            None,
            "ae.workspace_store_unavailable",
            503,
        ),
    ],
)
def test_binding_rejects_invalid_or_unavailable_inputs(
    request_payload,
    store,
    error_code,
    status_code,
) -> None:
    with pytest.raises(WorkspaceChatOrchestrationError) as exc:
        bind_workspace_chat_request(
            request_payload,
            trace_id=TRACE_ID,
            workspace_store=store,
        )

    assert exc.value.error_code == error_code
    assert exc.value.status_code == status_code


def test_binding_hides_missing_or_cross_owner_and_rejects_document_mismatch() -> None:
    store = workspace_store()
    cases = [
        (payload(workspace_id="missing"), "ae.workspace_not_found", 404),
        (payload(user_id="user-b", owner_user_id="user-b"), "ae.workspace_not_found", 404),
        (
            payload(chat_document_id="different-document"),
            "ae.workspace_chat_document_mismatch",
            409,
        ),
    ]

    for request_payload, error_code, status_code in cases:
        with pytest.raises(WorkspaceChatOrchestrationError) as exc:
            bind_workspace_chat_request(
                request_payload,
                trace_id=TRACE_ID,
                workspace_store=store,
            )
        assert exc.value.error_code == error_code
        assert exc.value.status_code == status_code


def test_binding_maps_workspace_repository_failure() -> None:
    class BrokenStore:
        def get_workspace(self, workspace_id):
            raise WorkspaceRepositoryError(
                "ae.workspace_store_unavailable",
                "Unavailable.",
                True,
            )

    with pytest.raises(WorkspaceChatOrchestrationError) as exc:
        bind_workspace_chat_request(
            payload(),
            trace_id=TRACE_ID,
            workspace_store=BrokenStore(),
        )

    assert exc.value.status_code == 503
    assert exc.value.retryable is True


def test_idempotent_record_accepts_exact_retry_and_rejects_conflict() -> None:
    binding = bind_workspace_chat_request(
        payload(interaction_id="interaction-a"),
        trace_id=TRACE_ID,
        workspace_store=workspace_store(),
    )
    store = ChatInteractionStore()
    record = {
        "interaction_id": "interaction-a",
        "workspace_id": WORKSPACE_ID,
        "chat_document_id": CHAT_DOCUMENT_ID,
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "user_message_hash": binding.user_message_hash,
    }
    store.save(record)

    assert idempotent_chat_record(binding, chat_store=store) == record
    store.records["interaction-a"] = {**record, "user_message_hash": "different"}
    with pytest.raises(WorkspaceChatOrchestrationError) as exc:
        idempotent_chat_record(binding, chat_store=store)
    assert exc.value.error_code == "ae.chat_interaction_conflict"


def test_activity_append_is_metadata_only_and_handles_legacy_and_missing() -> None:
    store = workspace_store()
    binding = bind_workspace_chat_request(
        payload(interaction_id="interaction-a"),
        trace_id=TRACE_ID,
        workspace_store=store,
    )
    activity = append_workspace_chat_activity(
        binding,
        workspace_store=store,
        activity_type="chat.interaction.started",
        status="PENDING",
        request_id="request-a",
        trace_id=TRACE_ID,
    )
    legacy = bind_workspace_chat_request(
        {"user_message": "hello"},
        trace_id=TRACE_ID,
        workspace_store=None,
    )

    assert activity["metadata"]["interaction_id"] == "interaction-a"
    assert activity["metadata"]["user_message_hash"] == binding.user_message_hash
    assert "Summarize the workspace." not in str(activity)
    assert append_workspace_chat_activity(
        legacy,
        workspace_store=None,
        activity_type="chat.interaction.started",
        status="PENDING",
        request_id="request-b",
        trace_id=TRACE_ID,
    ) is None

    with pytest.raises(WorkspaceChatOrchestrationError) as exc:
        append_workspace_chat_activity(
            binding,
            workspace_store=None,
            activity_type="chat.interaction.failed",
            status="FAILED",
            request_id="request-unavailable",
            trace_id=TRACE_ID,
        )
    assert exc.value.error_code == "ae.workspace_store_unavailable"
    assert exc.value.retryable is True

    class BrokenStore:
        def append_activity_record(self, activity):
            raise WorkspaceRepositoryError(
                "ae.workspace_store_unavailable",
                "Unavailable.",
                True,
            )

    with pytest.raises(WorkspaceChatOrchestrationError) as exc:
        append_workspace_chat_activity(
            binding,
            workspace_store=BrokenStore(),
            activity_type="chat.interaction.failed",
            status="FAILED",
            request_id="request-broken",
            trace_id=TRACE_ID,
        )
    assert exc.value.status_code == 503

    class MissingStore:
        def append_activity_record(self, activity):
            return None

    with pytest.raises(WorkspaceChatOrchestrationError) as exc:
        append_workspace_chat_activity(
            binding,
            workspace_store=MissingStore(),
            activity_type="chat.interaction.failed",
            status="FAILED",
            request_id="request-c",
            trace_id=TRACE_ID,
        )
    assert exc.value.error_code == "ae.workspace_not_found"
