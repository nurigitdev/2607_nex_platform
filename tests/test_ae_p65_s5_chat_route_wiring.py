from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from nex_ae_api.chat import ChatInteractionStore, register_chat_routes
from nex_ae_api.semantic_candidate_admission import (
    SemanticCandidateAdmissionResult,
    SemanticStageProjection,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

from test_nex_ae_chat_runtime_policy import RecordingGenerationClient


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-p65-s5-route",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def _compiled_result(*, mode: str = "required") -> SemanticCandidateAdmissionResult:
    return SemanticCandidateAdmissionResult(
        mode=mode,
        status="COMPILED",
        directive="ACCEPT_RUNTIME_WORK",
        agent_execution_id="10000000-0000-4000-8000-000000000657",
        work_intent_id="20000000-0000-4000-8000-000000000657",
        agent_context_id="30000000-0000-4000-8000-000000000657",
        agent_plan_id="40000000-0000-4000-8000-000000000657",
        validation_result_id="50000000-0000-4000-8000-000000000657",
        validation_status="VALID",
        executable_plan_id="60000000-0000-4000-8000-000000000657",
        executable_plan_hash="sha256:" + "a" * 64,
        stages=(
            SemanticStageProjection(
                semantic_stage="INTENT",
                candidate_id="70000000-0000-4000-8000-000000000657",
                candidate_hash="sha256:" + "b" * 64,
                directive="CONTINUE",
                validation_outcome="ADMITTED",
                prompt_template_version_id="80000000-0000-4000-8000-000000000657",
                model_profile="general-llm-default",
                model_ref="model-revision-a",
                resumed=False,
            ),
        ),
    )


class Runtime:
    def __init__(self, mode="required", result=None, failure=None) -> None:
        self.mode = mode
        self.result = result or _compiled_result(mode=mode)
        self.failure = failure
        self.calls = []

    def admit_chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return self.result


def _client(runtime: Runtime):
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    app.state.ae_semantic_candidate_admission = runtime
    generation = RecordingGenerationClient()
    store = ChatInteractionStore()
    register_chat_routes(app, store=store, cx_client=generation)
    return TestClient(app), generation, store


def test_required_mode_returns_async_compiled_projection_without_direct_generation() -> None:
    runtime = Runtime()
    client, generation, store = _client(runtime)
    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "10000000-0000-4000-8000-000000000658",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": "private prompt",
        },
        headers=_headers(),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PENDING"
    planning = body["generation"]["semantic_planning"]
    assert planning["status"] == "COMPILED"
    assert planning["validation_status"] == "VALID"
    assert planning["raw_prompt_included"] is False
    assert "private prompt" not in str(planning)
    assert generation.calls == []
    assert len(runtime.calls) == 1
    assert store.get(body["interaction_id"]) == body


def test_required_block_is_problem_response_and_shadow_failure_falls_back() -> None:
    blocked = Runtime(
        result=SemanticCandidateAdmissionResult(
            mode="required",
            status="CANDIDATE_BLOCKED",
            directive="CLARIFICATION_REQUIRED",
            agent_execution_id="10000000-0000-4000-8000-000000000657",
        )
    )
    client, generation, _ = _client(blocked)
    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "20000000-0000-4000-8000-000000000658",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": "needs clarification",
        },
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "SEMANTIC_ADMISSION_BLOCKED"
    assert generation.calls == []

    shadow = Runtime(mode="shadow", failure=RuntimeError("private provider detail"))
    client, generation, _ = _client(shadow)
    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "30000000-0000-4000-8000-000000000658",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": "compatibility prompt",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert len(generation.calls) == 1


def test_required_unknown_failure_is_sanitized() -> None:
    runtime = Runtime(failure=RuntimeError("private stack detail"))
    client, _, _ = _client(runtime)
    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "40000000-0000-4000-8000-000000000658",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": "private prompt",
        },
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "SEMANTIC_ADMISSION_FAILED"
    assert "private stack detail" not in str(response.json())
