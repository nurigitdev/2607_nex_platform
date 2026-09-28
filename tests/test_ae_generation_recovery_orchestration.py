from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_ae_api.async_generation import build_async_generation_projection
from nex_ae_api.chat import ChatInteractionStore, register_chat_routes, sha256_text
from nex_ae_api.generation_recovery import (
    AE_GENERATION_RETRY_ORCHESTRATION_SCHEMA_VERSION,
    AeGenerationRecoveryError,
    build_generation_retry_lineage,
    prepare_generation_retry,
)
from nex_ae_api.generated_response_lineage import attach_generated_response_lineage
from test_nex_ae_generated_response_lineage import sample_bundle, sample_record
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_user_token


def _job(status: str, *, retryable: bool = True) -> dict[str, Any]:
    error = None
    if status in {"FAILED", "CANCELLED"}:
        error = {
            "error_code": "cx.generation.failed",
            "retryable": retryable,
            "dead_lettered": not retryable,
        }
    return {
        "job_id": "job-recovery",
        "cx_generation_id": "generation-recovery",
        "status": status,
        "attempt_count": 1,
        "max_attempts": 3,
        "retryable": retryable,
        "links": {
            "generation": "/api/v1/generations/generation-recovery",
            "async_job": "/api/v1/generation-jobs/job-recovery",
        },
        "error": error,
    }


def _record(status: str = "FAILED", *, retryable: bool = True) -> dict[str, Any]:
    projection = build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": _job(status, retryable=retryable),
            "generation": None,
        }
    )
    return {
        "interaction_id": "parent-recovery",
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "owner_user_id": "user-a",
        "user_message_hash": sha256_text("same private question"),
        "status": "FAILED" if status != "QUEUED" else "PENDING",
        "generation": {"async_generation": projection},
    }


def _payload() -> dict[str, Any]:
    return {
        "interaction_id": "child-recovery",
        "user_message": "same private question",
        "generation": {"temperature": 0.1},
    }


def test_prepare_retry_returns_forced_async_child_and_lineage() -> None:
    payload = _payload()
    result = prepare_generation_retry(
        _record(),
        payload,
        submitted_input_hash=sha256_text("same private question"),
    )

    assert result["retry_orchestration_schema_version"] == (
        AE_GENERATION_RETRY_ORCHESTRATION_SCHEMA_VERSION
    )
    assert result["retry_payload"]["generation"] == {
        "temperature": 0.1,
        "execution_strategy": "ASYNCHRONOUS",
    }
    assert result["lineage"]["parent_interaction_id"] == "parent-recovery"
    assert result["lineage"]["parent_response_id"] is None
    assert result["recovery"]["action"] == "RETRY_AS_CHILD"
    assert result["raw_input_included"] is False
    assert payload["generation"] == {"temperature": 0.1}


def test_retry_lineage_links_existing_parent_response_when_available() -> None:
    parent = attach_generated_response_lineage(
        sample_record(), sample_bundle()["lineage"]
    )

    lineage = build_generation_retry_lineage(
        parent,
        {"job_id": "parent-job", "cx_generation_id": "parent-generation"},
    )

    assert lineage["parent_interaction_id"] == parent["interaction_id"]
    assert lineage["parent_response_id"] == (
        parent["generation"]["generated_response"]["response_id"]
    )


def test_retry_lineage_rejects_invalid_parent_response_and_projection() -> None:
    parent = attach_generated_response_lineage(
        sample_record(), sample_bundle()["lineage"]
    )
    parent["generation"]["generated_response"]["interaction_id"] = "different"

    with pytest.raises(AeGenerationRecoveryError, match="response lineage"):
        build_generation_retry_lineage(
            parent,
            {"job_id": "parent-job", "cx_generation_id": "parent-generation"},
        )
    with pytest.raises(AeGenerationRecoveryError, match="parent.job_id"):
        build_generation_retry_lineage(sample_record(), {"cx_generation_id": "cx"})


@pytest.mark.parametrize(
    "parent,payload,input_hash,status,error_code",
    [
        (_record("QUEUED"), _payload(), sha256_text("same private question"), 409, "ae.async_generation.not_retryable"),
        (_record("FAILED", retryable=False), _payload(), sha256_text("same private question"), 409, "ae.async_generation.not_retryable"),
        (_record(), {**_payload(), "interaction_id": "parent-recovery"}, sha256_text("same private question"), 400, "ae.async_generation.retry_interaction_id_invalid"),
        (_record(), _payload(), sha256_text("different"), 409, "ae.async_generation.retry_input_mismatch"),
        (_record(), {**_payload(), "generation": "bad"}, sha256_text("same private question"), 400, "ae.async_generation.retry_request_invalid"),
    ],
)
def test_prepare_retry_rejects_ineligible_or_invalid_requests(
    parent, payload, input_hash, status, error_code
) -> None:
    with pytest.raises(AeGenerationRecoveryError) as exc_info:
        prepare_generation_retry(parent, payload, submitted_input_hash=input_hash)
    assert exc_info.value.status_code == status
    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize("parent,payload,input_hash", [([], _payload(), "x"), (_record(), [], "x"), ({}, _payload(), "x"), (_record(), {"interaction_id": ""}, "x")])
def test_prepare_retry_rejects_invalid_shapes(parent, payload, input_hash) -> None:
    with pytest.raises(AeGenerationRecoveryError) as exc_info:
        prepare_generation_retry(parent, payload, submitted_input_hash=input_hash)
    assert exc_info.value.status_code == 400


def test_prepare_retry_rejects_invalid_parent_generation_metadata() -> None:
    with pytest.raises(AeGenerationRecoveryError) as exc_info:
        prepare_generation_retry(
            {"interaction_id": "parent", "generation": None},
            _payload(),
            submitted_input_hash="hash",
        )

    assert str(exc_info.value) == (
        "Parent interaction has invalid generation metadata."
    )


class RecoveryClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_job(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("job")
        return _job("FAILED")

    def get_handoff(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("handoff")
        return {
            "handoff_schema_version": "cx_generation_handoff.v1",
            "handoff_status": "BLOCKED",
            "next_action": "RETRY_OR_REPAIR_GENERATION",
            "job": _job("FAILED"),
            "generation": None,
            "content": None,
            "owner_scope_enforced": True,
        }


class _UnusedClient:
    def create_generation(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("not expected")

    def create_retrieval_context(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("not expected")


def _headers(user_id: str = "user-a") -> dict[str, str]:
    token = issue_mock_user_token(tenant_id="tenant-a", user_id=user_id)
    return {"Authorization": f"Bearer {token.access_token}"}


def test_recovery_route_reconciles_and_returns_plan_only() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    store.save(_record("QUEUED"))
    async_client = RecoveryClient()
    register_chat_routes(
        app,
        store=store,
        cx_client=_UnusedClient(),
        cx_async_client=async_client,
        retrieval_client=_UnusedClient(),
    )

    response = TestClient(app).get(
        "/api/v1/chat/interactions/parent-recovery/recovery",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["action"] == "RETRY_AS_CHILD"
    assert set(response.json()) == {
        "recovery_plan_schema_version",
        "action",
        "eligible",
        "reason_code",
        "new_interaction_required",
        "parent_lineage_required",
        "input_hash_required",
    }
    assert store.get("parent-recovery")["status"] == "FAILED"
    assert async_client.calls == ["job", "handoff"]


def test_recovery_route_is_owner_scoped_and_requires_async_interaction() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    store.save(_record("QUEUED"))
    register_chat_routes(
        app,
        store=store,
        cx_client=_UnusedClient(),
        cx_async_client=RecoveryClient(),
        retrieval_client=_UnusedClient(),
    )
    client = TestClient(app)

    hidden = client.get(
        "/api/v1/chat/interactions/parent-recovery/recovery",
        headers=_headers("user-b"),
    )
    unauthorized = client.get(
        "/api/v1/chat/interactions/parent-recovery/recovery"
    )

    assert hidden.status_code == 404
    assert unauthorized.status_code == 401
