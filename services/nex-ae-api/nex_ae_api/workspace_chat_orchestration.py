from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_ae_api.workspace import WorkspaceError, build_workspace_activity
from nex_ae_api.workspace_persistence import WorkspaceRepositoryError


@dataclass(frozen=True)
class WorkspaceChatOrchestrationError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


@dataclass(frozen=True)
class WorkspaceChatBinding:
    payload: dict[str, Any]
    workspace: dict[str, Any] | None
    interaction_id: str
    user_message_hash: str


def bind_workspace_chat_request(
    payload: dict[str, Any],
    *,
    trace_id: str,
    workspace_store: Any | None,
) -> WorkspaceChatBinding:
    normalized = dict(payload)
    user_message = _required_text(
        normalized.get("user_message"),
        error_code="ae.chat_request_invalid",
        detail="user_message is required.",
    )
    message_hash = hashlib.sha256(user_message.encode("utf-8")).hexdigest()
    interaction_id = _optional_text(normalized.get("interaction_id")) or str(
        uuid5(NAMESPACE_URL, f"ae-interaction:{trace_id}:{message_hash}")
    )
    normalized["interaction_id"] = interaction_id

    workspace_id = _optional_text(normalized.get("workspace_id"))
    if workspace_id is None:
        if "workspace_id" in normalized and normalized["workspace_id"] is not None:
            raise WorkspaceChatOrchestrationError(
                400,
                "ae.workspace_id_invalid",
                "workspace_id must be a non-empty string when supplied.",
            )
        normalized["chat_document_id"] = _optional_text(
            normalized.get("chat_document_id")
        ) or str(uuid5(NAMESPACE_URL, f"ae-chat-document:{trace_id}"))
        return WorkspaceChatBinding(normalized, None, interaction_id, message_hash)
    if workspace_store is None:
        raise WorkspaceChatOrchestrationError(
            503,
            "ae.workspace_store_unavailable",
            "AE workspace store is unavailable for workspace-bound chat.",
            True,
        )

    try:
        workspace = workspace_store.get_workspace(workspace_id)
    except WorkspaceRepositoryError as exc:
        raise WorkspaceChatOrchestrationError(
            503 if exc.retryable else 409,
            exc.error_code,
            exc.detail,
            exc.retryable,
        ) from exc
    if workspace is None or not _same_owner(normalized, workspace):
        raise WorkspaceChatOrchestrationError(
            404,
            "ae.workspace_not_found",
            f"Workspace was not found: {workspace_id}",
        )

    requested_document_id = _optional_text(normalized.get("chat_document_id"))
    workspace_document_id = str(workspace["chat_document_id"])
    if (
        requested_document_id is not None
        and requested_document_id != workspace_document_id
    ):
        raise WorkspaceChatOrchestrationError(
            409,
            "ae.workspace_chat_document_mismatch",
            "Chat document does not match the workspace binding.",
        )
    normalized["workspace_id"] = workspace_id
    normalized["chat_document_id"] = workspace_document_id
    return WorkspaceChatBinding(normalized, workspace, interaction_id, message_hash)


def idempotent_chat_record(
    binding: WorkspaceChatBinding,
    *,
    chat_store: Any,
) -> dict[str, Any] | None:
    record = chat_store.get_for_owner(
        binding.interaction_id,
        tenant_id=binding.payload.get("tenant_id", "local-tenant"),
        owner_user_id=binding.payload.get(
            "owner_user_id",
            binding.payload.get("user_id", "local-user"),
        ),
    )
    if record is None:
        return None
    if (
        record.get("workspace_id") != binding.payload.get("workspace_id")
        or record.get("chat_document_id") != binding.payload.get("chat_document_id")
        or record.get("user_message_hash") != binding.user_message_hash
    ):
        raise WorkspaceChatOrchestrationError(
            409,
            "ae.chat_interaction_conflict",
            "Interaction identifier is already bound to different chat input.",
        )
    return record


def append_workspace_chat_activity(
    binding: WorkspaceChatBinding,
    *,
    workspace_store: Any | None,
    activity_type: str,
    status: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any] | None:
    if binding.workspace is None:
        return None
    if workspace_store is None:
        raise WorkspaceChatOrchestrationError(
            503,
            "ae.workspace_store_unavailable",
            "AE workspace store is unavailable for workspace activity.",
            True,
        )
    activity = build_workspace_activity(
        workspace_id=binding.workspace["workspace_id"],
        activity_type=activity_type,
        request_id=request_id,
        trace_id=trace_id,
        summary=f"Chat interaction {status.lower()}.",
        metadata={
            "interaction_id": binding.interaction_id,
            "status": status,
            "user_message_hash": binding.user_message_hash,
        },
    )
    try:
        saved = workspace_store.append_activity_record(activity)
    except WorkspaceRepositoryError as exc:
        raise WorkspaceChatOrchestrationError(
            503 if exc.retryable else 409,
            exc.error_code,
            exc.detail,
            exc.retryable,
        ) from exc
    if saved is None:
        raise WorkspaceChatOrchestrationError(
            404,
            "ae.workspace_not_found",
            f"Workspace was not found: {binding.workspace['workspace_id']}",
        )
    return saved


def append_persisted_workspace_chat_activity(
    record: dict[str, Any],
    *,
    workspace_store: Any | None,
    activity_type: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any] | None:
    workspace_id = _optional_text(record.get("workspace_id"))
    if workspace_id is None:
        return None
    if workspace_store is None:
        raise WorkspaceChatOrchestrationError(
            503,
            "ae.workspace_store_unavailable",
            "AE workspace store is unavailable for workspace activity.",
            True,
        )
    generation = record.get("generation")
    generation = generation if isinstance(generation, dict) else {}
    async_generation = generation.get("async_generation")
    async_generation = (
        async_generation if isinstance(async_generation, dict) else {}
    )
    activity = build_workspace_activity(
        workspace_id=workspace_id,
        activity_type=activity_type,
        request_id=request_id,
        trace_id=trace_id,
        summary=f"Asynchronous chat interaction {record.get('status', 'updated').lower()}.",
        metadata={
            "interaction_id": record.get("interaction_id"),
            "status": record.get("status"),
            "cx_status": record.get("cx_status"),
            "async_lifecycle_status": async_generation.get("lifecycle_status"),
            "async_job_status": async_generation.get("cx_job_status"),
            "handoff_status": async_generation.get("handoff_status"),
            "attempt_count": async_generation.get("attempt_count"),
            "retryable": async_generation.get("retryable") is True,
            "private_content_included": False,
        },
    )
    try:
        saved = workspace_store.append_activity_record(activity)
    except WorkspaceRepositoryError as exc:
        raise WorkspaceChatOrchestrationError(
            503 if exc.retryable else 409,
            exc.error_code,
            exc.detail,
            exc.retryable,
        ) from exc
    except WorkspaceError as exc:
        raise WorkspaceChatOrchestrationError(
            exc.status_code,
            exc.error_code,
            exc.detail,
            exc.retryable,
        ) from exc
    if saved is None:
        raise WorkspaceChatOrchestrationError(
            404,
            "ae.workspace_not_found",
            f"Workspace was not found: {workspace_id}",
        )
    return saved


def _same_owner(payload: dict[str, Any], workspace: dict[str, Any]) -> bool:
    tenant_id = _optional_text(payload.get("tenant_id")) or "local-tenant"
    owner_user_id = _optional_text(payload.get("owner_user_id")) or _optional_text(
        payload.get("user_id")
    ) or "local-user"
    return (
        workspace.get("tenant_id") == tenant_id
        and workspace.get("owner_user_id") == owner_user_id
    )


def _required_text(value: Any, *, error_code: str, detail: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise WorkspaceChatOrchestrationError(400, error_code, detail)
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
