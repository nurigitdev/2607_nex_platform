from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from nex_ae_api.mo_generation_client import AeMoGenerationClientError
from nex_ae_api.semantic_candidate_admission import SemanticCandidateAdmissionError
from nex_ae_api.semantic_candidate_evidence import SemanticCandidateEvidenceError
from nex_ae_api.semantic_candidate_failures import (
    project_semantic_candidate_failure,
)
from nex_ae_api.semantic_candidates import SemanticCandidateStageError
from nex_runtime.semantic_hashes import canonical_json

from test_ae_p65_s5_candidate_admission_compile import _components, _request
from test_ae_p65_s5_chat_route_wiring import Runtime, _client, _headers

PRIVATE_MARKER = "private-provider-key-and-hidden-reasoning"


@pytest.mark.parametrize(
    (
        "error_code",
        "source_status",
        "retryable",
        "retry_after",
        "expected_status",
        "expected_directive",
    ),
    [
        ("PROVIDER_NOT_READY", 401, False, None, 503, "BLOCKED"),
        ("PROVIDER_NOT_READY", 503, True, None, 503, "RETRY_PROVIDER"),
        ("PROVIDER_TIMEOUT", 504, True, None, 504, "RETRY_PROVIDER"),
        ("PROVIDER_RATE_LIMIT", 429, True, 12.0, 429, "RETRY_PROVIDER"),
        ("PROVIDER_RATE_LIMIT", 429, True, None, 429, "RETRY_PROVIDER"),
        ("PROVIDER_RATE_LIMIT", 429, True, True, 429, "RETRY_PROVIDER"),
        ("PROVIDER_RATE_LIMIT", 429, True, 301.0, 429, "RETRY_PROVIDER"),
        ("PROVIDER_SERVER_ERROR", 500, True, None, 502, "RETRY_PROVIDER"),
        ("PROVIDER_RESPONSE_INVALID", 502, False, None, 502, "BLOCKED"),
    ],
)
def test_provider_failure_projection_is_bounded_and_private_free(
    error_code: str,
    source_status: int,
    retryable: bool,
    retry_after: object,
    expected_status: int,
    expected_directive: str,
) -> None:
    failure = project_semantic_candidate_failure(
        AeMoGenerationClientError(
            status_code=source_status,
            error_code=error_code,
            detail=PRIVATE_MARKER,
            retryable=retryable,
            upstream_error_code=f"upstream.{PRIVATE_MARKER}",
            retry_after_seconds=retry_after,
        ),
        semantic_stage="INTENT",
    )

    assert failure is not None
    assert failure.status_code == expected_status
    assert failure.directive == expected_directive
    wire = failure.to_wire()
    assert PRIVATE_MARKER not in json.dumps(wire, sort_keys=True)
    assert wire["raw_prompt_included"] is False
    assert wire["provider_response_included"] is False
    assert wire["provider_endpoint_included"] is False
    assert wire["provider_private_data_included"] is False
    assert wire["hidden_reasoning_included"] is False
    if (
        isinstance(retry_after, int | float)
        and not isinstance(retry_after, bool)
        and retry_after <= 300
    ):
        assert wire["retry_after_seconds"] == retry_after
    else:
        assert "retry_after_seconds" not in wire


@pytest.mark.parametrize(
    ("error_code", "expected_status", "expected_directive"),
    [
        ("CANDIDATE_JSON_INVALID", 422, "REPLAN_REQUIRED"),
        ("CANDIDATE_SCHEMA_INVALID", 422, "REPLAN_REQUIRED"),
        ("CANDIDATE_AUTHORITY_VIOLATION", 422, "BLOCKED"),
        ("CANDIDATE_PRIVATE_DATA_VIOLATION", 422, "BLOCKED"),
        ("CANDIDATE_CAPABILITY_UNKNOWN", 422, "REPLAN_REQUIRED"),
        ("CANDIDATE_DEPENDENCY_INVALID", 422, "REPLAN_REQUIRED"),
        ("CANDIDATE_BOUNDS_EXCEEDED", 422, "REPLAN_REQUIRED"),
        ("CANDIDATE_PLAN_INVALID", 422, "REPLAN_REQUIRED"),
        ("PROMPT_INJECTION_OR_POLICY_BLOCK", 422, "BLOCKED"),
        ("SEMANTIC_CALIBRATION_REQUIRED", 503, "BLOCKED"),
    ],
)
def test_candidate_failure_projection_uses_closed_taxonomy(
    error_code: str,
    expected_status: int,
    expected_directive: str,
) -> None:
    failure = project_semantic_candidate_failure(
        SemanticCandidateStageError(499, error_code, PRIVATE_MARKER, retryable=True),
        semantic_stage="PLAN",
    )

    assert failure is not None
    assert failure.status_code == expected_status
    assert failure.directive == expected_directive
    assert failure.retryable is False
    assert PRIVATE_MARKER not in str(failure.to_wire())


@pytest.mark.parametrize(
    ("semantic_stage", "expected_directive"),
    [
        ("INTENT", "CLARIFICATION_REQUIRED"),
        ("CONTEXT", "CONTEXT_REFRESH_REQUIRED"),
        ("PLAN", "REPLAN_REQUIRED"),
        ("UNKNOWN", "BLOCKED"),
    ],
)
def test_low_confidence_failure_projection_is_stage_specific(
    semantic_stage: str,
    expected_directive: str,
) -> None:
    failure = project_semantic_candidate_failure(
        SemanticCandidateStageError(
            422,
            "CANDIDATE_LOW_CONFIDENCE",
            PRIVATE_MARKER,
        ),
        semantic_stage=semantic_stage,
    )

    assert failure is not None
    assert failure.directive == expected_directive


def test_unknown_and_persistence_failures_are_fail_closed() -> None:
    assert (
        project_semantic_candidate_failure(
            RuntimeError(PRIVATE_MARKER), semantic_stage="INTENT"
        )
        is None
    )
    assert (
        project_semantic_candidate_failure(
            AeMoGenerationClientError(500, "PRIVATE_UNKNOWN", PRIVATE_MARKER, True),
            semantic_stage="INTENT",
        )
        is None
    )
    assert (
        project_semantic_candidate_failure(
            SemanticCandidateStageError(422, "PRIVATE_UNKNOWN", PRIVATE_MARKER),
            semantic_stage="PLAN",
        )
        is None
    )

    retryable = project_semantic_candidate_failure(
        SemanticCandidateEvidenceError(
            "ae.semantic_candidate_storage_unavailable",
            PRIVATE_MARKER,
            True,
        ),
        semantic_stage="CONTEXT",
    )
    blocked = project_semantic_candidate_failure(
        SemanticCandidateEvidenceError(
            "ae.semantic_candidate_payload_integrity_failed",
            PRIVATE_MARKER,
        ),
        semantic_stage="CONTEXT",
    )
    assert retryable is not None and retryable.directive == "RETRY_PERSISTENCE"
    assert retryable.status_code == 503
    assert blocked is not None and blocked.directive == "BLOCKED"
    assert blocked.status_code == 409
    assert PRIVATE_MARKER not in str(retryable.to_wire())
    assert PRIVATE_MARKER not in str(blocked.to_wire())


@pytest.mark.parametrize(
    ("semantic_stage", "error_code", "retryable"),
    [
        ("INTENT", "PROVIDER_NOT_READY", True),
        ("INTENT", "PROVIDER_TIMEOUT", True),
        ("INTENT", "PROVIDER_RATE_LIMIT", True),
        ("INTENT", "PROVIDER_SERVER_ERROR", True),
        ("INTENT", "PROVIDER_RESPONSE_INVALID", False),
        ("CONTEXT", "PROVIDER_TIMEOUT", True),
        ("PLAN", "PROVIDER_TIMEOUT", True),
    ],
)
def test_provider_failure_matrix_never_reaches_validation_or_compile(
    semantic_stage: str,
    error_code: str,
    retryable: bool,
) -> None:
    service, client, _, intents, contexts, plans, validations, executables = (
        _components()
    )
    original_generate = client.generate_candidate

    def fail_selected_stage(**kwargs):
        if kwargs["semantic_stage"] == semantic_stage:
            raise AeMoGenerationClientError(
                503,
                error_code,
                PRIVATE_MARKER,
                retryable,
                upstream_error_code=f"private.{PRIVATE_MARKER}",
                retry_after_seconds=7.0,
            )
        return original_generate(**kwargs)

    client.generate_candidate = fail_selected_stage

    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        service.admit_and_compile(_request())

    assert raised.value.error_code == error_code
    assert raised.value.semantic_stage == semantic_stage
    assert PRIVATE_MARKER not in raised.value.detail
    assert validations.save_calls == 0
    assert not executables.records
    expected_completed = {"INTENT": 0, "CONTEXT": 1, "PLAN": 2}[semantic_stage]
    assert len(service.candidate_storage.payloads) == expected_completed
    assert len(intents.records) == (1 if semantic_stage != "INTENT" else 0)
    assert len(contexts.records) == (1 if semantic_stage == "PLAN" else 0)
    assert not plans.records


@pytest.mark.parametrize(
    ("semantic_stage", "mutate", "expected_code"),
    [
        ("INTENT", lambda _value: "not-json", "CANDIDATE_JSON_INVALID"),
        (
            "INTENT",
            lambda value: {**value, "tenant_id": "invented-tenant"},
            "CANDIDATE_AUTHORITY_VIOLATION",
        ),
        (
            "CONTEXT",
            lambda value: {**value, "hidden_reasoning": PRIVATE_MARKER},
            "CANDIDATE_PRIVATE_DATA_VIOLATION",
        ),
        (
            "CONTEXT",
            lambda value: {
                **value,
                "retrieval_hints": [
                    {
                        **value["retrieval_hints"][0],
                        "query_terms": ["ignore previous instruction"],
                    }
                ],
            },
            "PROMPT_INJECTION_OR_POLICY_BLOCK",
        ),
        (
            "PLAN",
            lambda value: {
                **value,
                "logical_steps": [
                    {
                        **value["logical_steps"][0],
                        "capability_hint": "UNKNOWN.CAPABILITY",
                    }
                ],
            },
            "CANDIDATE_CAPABILITY_UNKNOWN",
        ),
        (
            "PLAN",
            lambda value: {
                **value,
                "logical_steps": [
                    {
                        **value["logical_steps"][0],
                        "depends_on": ["S99"],
                    }
                ],
            },
            "CANDIDATE_DEPENDENCY_INVALID",
        ),
    ],
)
def test_adversarial_provider_output_never_creates_executable_work(
    semantic_stage: str,
    mutate,
    expected_code: str,
) -> None:
    service, client, _, _, _, plans, validations, executables = _components()
    original_generate = client.generate_candidate

    def adversarial_generate(**kwargs):
        result = original_generate(**kwargs)
        if kwargs["semantic_stage"] != semantic_stage:
            return result
        source = json.loads(result.output_text)
        mutation = mutate(source)
        output = mutation if isinstance(mutation, str) else canonical_json(mutation)
        return replace(
            result,
            output_text=output,
            provider_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            provider_output_size_bytes=len(output.encode()),
        )

    client.generate_candidate = adversarial_generate

    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        service.admit_and_compile(_request())

    assert raised.value.error_code == expected_code
    assert raised.value.semantic_stage == semantic_stage
    assert validations.save_calls == 0
    assert not executables.records
    assert not plans.records


def test_retry_after_final_provider_failure_preserves_execution_and_stage_identity() -> (
    None
):
    service, client, admission, _, _, _, validations, executables = _components()
    original_generate = client.generate_candidate

    def context_timeout(**kwargs):
        if kwargs["semantic_stage"] == "CONTEXT":
            raise AeMoGenerationClientError(
                504,
                "PROVIDER_TIMEOUT",
                PRIVATE_MARKER,
                True,
            )
        return original_generate(**kwargs)

    client.generate_candidate = context_timeout
    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        service.admit_and_compile(_request())
    assert raised.value.semantic_stage == "CONTEXT"
    assert len(service.candidate_storage.payloads) == 1

    client.generate_candidate = original_generate
    client.calls.clear()
    recovered = service.admit_and_compile(_request())

    assert recovered.status == "COMPILED"
    assert recovered.agent_execution_id == _request_execution_id()
    assert [stage.resumed for stage in recovered.stages] == [True, False, False]
    assert client.calls == ["CONTEXT", "PLAN"]
    assert admission.calls == 2
    assert validations.save_calls == 1
    assert len(executables.records) == 1


def test_chat_boundary_exposes_only_sanitized_failure_taxonomy() -> None:
    runtime = Runtime(
        failure=SemanticCandidateAdmissionError(
            429,
            "PROVIDER_RATE_LIMIT",
            PRIVATE_MARKER,
            True,
            "RETRY_PROVIDER",
            "CONTEXT",
            9.0,
        )
    )
    client, generation, store = _client(runtime)
    interaction_id = "90000000-0000-4000-8000-000000000659"
    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": interaction_id,
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": PRIVATE_MARKER,
        },
        headers=_headers(),
    )

    assert response.status_code == 429
    body = response.json()
    assert body["error_code"] == "PROVIDER_RATE_LIMIT"
    assert body["retryable"] is True
    assert body["details"] == {
        "directive": "RETRY_PROVIDER",
        "semantic_stage": "CONTEXT",
        "retry_after_seconds": 9.0,
    }
    assert PRIVATE_MARKER not in body["detail"]
    failed = store.get(interaction_id)
    assert failed is not None
    assert failed["failure"]["failed_stage"] == "CONTEXT"
    assert failed["failure"]["directive"] == "RETRY_PROVIDER"
    assert PRIVATE_MARKER not in str(failed["failure"])
    assert generation.calls == []


def test_forged_exception_attributes_cannot_cross_chat_boundary() -> None:
    class ForgedFailure(RuntimeError):
        status_code = 200
        error_code = "PRIVATE_TRUST_ME"
        detail = PRIVATE_MARKER
        retryable = True

    client, generation, _ = _client(Runtime(failure=ForgedFailure(PRIVATE_MARKER)))
    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "91000000-0000-4000-8000-000000000659",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": "safe prompt",
        },
        headers=_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "SEMANTIC_ADMISSION_FAILED"
    assert response.json()["details"] == {"directive": "BLOCKED"}
    assert PRIVATE_MARKER not in str(response.json())
    assert generation.calls == []


def _request_execution_id() -> str:
    return "10000000-0000-4000-8000-000000000656"
