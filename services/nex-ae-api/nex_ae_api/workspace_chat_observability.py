from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


WORKSPACE_CHAT_OBSERVABILITY_SCHEMA_VERSION = "ae_workspace_chat_observability.v2"
WORKSPACE_CHAT_STATE_EVENT = "ae.workspace_chat.state_changed"


def observe_workspace_chat_state(
    emitter: OperationalEventEmitter,
    record: Mapping[str, Any],
) -> OperationalEventEmitResult:
    interaction_id = _required(record.get("interaction_id"), "interaction_id")
    status = _required(record.get("status"), "status")
    request_id = _optional(record.get("request_id"))
    trace_id = _optional(record.get("trace_id"))
    failure = _mapping(record.get("failure"))
    retrieval = _mapping(record.get("retrieval"))
    generation = _mapping(record.get("generation"))
    policy = _mapping(generation.get("policy"))
    runtime_policy = _mapping(policy.get("runtime_policy_snapshot"))
    intent = _mapping(runtime_policy.get("intent_decision"))
    compatibility_rule = _mapping(runtime_policy.get("compatibility_rule"))
    prompt_contract = _mapping(runtime_policy.get("prompt_contract_ref"))
    policy_package = _mapping(policy.get("generation_policy_package"))
    artifacts = record.get("artifact_refs")
    artifact_count = len(artifacts) if isinstance(artifacts, list) else 0
    return emitter.safe_emit(
        event_type=WORKSPACE_CHAT_STATE_EVENT,
        severity="ERROR" if status == "FAILED" else "INFO",
        message="AE workspace chat state changed.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("ae.chat_interaction", interaction_id),
        details={
            "observability_schema_version": (
                WORKSPACE_CHAT_OBSERVABILITY_SCHEMA_VERSION
            ),
            "status": status,
            "cx_status": _optional(record.get("cx_status")),
            "workspace_bound": _optional(record.get("workspace_id")) is not None,
            "retrieval_available": bool(retrieval),
            "artifact_ref_count": artifact_count,
            "failure_code": _optional(failure.get("error_code")),
            "retryable": failure.get("retryable") is True,
            "policy_available": bool(policy),
            "execution_mode": _optional(intent.get("execution_mode")),
            "compatibility_rule_id": _optional(
                compatibility_rule.get("rule_id")
            ),
            "compatibility_rule_version": _optional(
                compatibility_rule.get("rule_version")
            ),
            "policy_snapshot_hash": _optional(
                runtime_policy.get("policy_snapshot_hash")
            ),
            "prompt_binding_key": _optional(
                prompt_contract.get("prompt_binding_key")
            ),
            "prompt_version": _optional(prompt_contract.get("prompt_version")),
            "generation_policy_package_hash": _optional(
                policy_package.get("client_package_hash")
            ),
            "prompt_content_included": False,
            "response_content_included": False,
            "owner_identity_included": False,
            "provider_detail_included": False,
        },
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                f"ae-workspace-chat-state:{interaction_id}:{status}",
            )
        ),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required(value: object, field: str) -> str:
    normalized = _optional(value)
    if normalized is None:
        raise ValueError(f"{field} must be a non-empty string")
    return normalized


def _optional(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
