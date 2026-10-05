from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx.citation_repair import (
    CX_CITATION_REPAIR_SCHEMA_VERSION,
    CitationRepairError,
    build_citation_repair_payload,
    generate_with_bounded_citation_repair,
    validate_citation_repair_projection,
)
from nex_cx.grounded_output_validation import GroundedOutputValidationError
from nex_cx.grounded_prompt import build_grounded_evidence_binding


def _retrieval_package() -> dict:
    return {
        "retrieval_package_id": "retrieval-0997",
        "package_hash": "b" * 64,
        "evidence_items": [
            {
                "evidence_id": "evidence-1",
                "citation_label": "[1]",
                "text": "First private evidence.",
            },
            {
                "evidence_id": "evidence-2",
                "citation_label": "[2]",
                "text": "Second private evidence.",
            },
        ],
    }


def _payload() -> dict:
    binding = build_grounded_evidence_binding(
        retrieval_package=_retrieval_package(),
        selected_evidence_ids=["evidence-1"],
    )
    return {
        "client_request_id": "client-0997",
        "cx_generation_id": "generation-0997",
        "provider_prompt_package_hash": "a" * 64,
        "messages": [
            {"role": "system", "content": "Use evidence."},
            {"role": "user", "content": "Private grounded envelope."},
        ],
        "prompt": None,
        "temperature": 0.3,
        "metadata": {
            "retrieval_package_id": "retrieval-0997",
            "retrieval_package_hash": "b" * 64,
            "evidence_binding_hash": binding["evidence_binding_hash"],
            "selected_evidence_count": 1,
            "generation_request_hash": "c" * 64,
        },
    }


def _response(text: str) -> dict:
    return {
        "mo_generation_id": "mo-0997",
        "alias": "general-llm-default",
        "model_revision": "mock-v1",
        "deployment_id": "mock-local",
        "provider_type": "mock-generation",
        "output": {"type": "text", "text": text},
        "finish_reason": "STOP",
        "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        "runtime_metadata": {},
    }


class SequenceClient:
    def __init__(self, *responses: dict) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create_generation(self, payload, *, request_id, trace_id):
        self.calls.append(deepcopy(payload))
        return self.responses.pop(0)


def _generate(client: SequenceClient, checkpoints: list[str]):
    return generate_with_bounded_citation_repair(
        generation_client=client,
        mo_payload=_payload(),
        request_id="request-0997",
        trace_id="trace-0997",
        grounding_required=True,
        retrieval_package=_retrieval_package(),
        selected_evidence_ids=["evidence-1"],
        cancellation_checkpoint=lambda: checkpoints.append("checkpoint"),
    )


def test_valid_first_response_skips_repair() -> None:
    client = SequenceClient(_response("Grounded answer [1]."))
    checkpoints: list[str] = []

    result = _generate(client, checkpoints)

    assert len(client.calls) == 1
    assert checkpoints == ["checkpoint"]
    assert result.repair == {
        "repair_schema_version": CX_CITATION_REPAIR_SCHEMA_VERSION,
        "attempted": False,
        "attempt_count": 0,
        "max_attempts": 1,
        "trigger_error_code": None,
        "same_retrieval_package": True,
        "original_provider_prompt_package_hash": "a" * 64,
        "effective_provider_prompt_package_hash": "a" * 64,
        "invalid_output_included": False,
    }


@pytest.mark.parametrize(
    ("invalid_text", "trigger"),
    [
        ("Missing citation.", "cx.citation_required_missing"),
        ("Wrong citation [2].", "cx.citation_validation_failed"),
    ],
)
def test_citation_failure_gets_one_repair_with_same_package(invalid_text, trigger) -> None:
    client = SequenceClient(
        _response(invalid_text),
        _response("Repaired grounded answer [1]."),
    )
    checkpoints: list[str] = []

    result = _generate(client, checkpoints)

    assert len(client.calls) == 2
    assert checkpoints == ["checkpoint", "checkpoint"]
    repair_payload = client.calls[1]
    assert repair_payload["metadata"]["retrieval_package_id"] == "retrieval-0997"
    assert repair_payload["metadata"]["retrieval_package_hash"] == "b" * 64
    assert repair_payload["metadata"]["evidence_binding_hash"] == (
        _payload()["metadata"]["evidence_binding_hash"]
    )
    assert repair_payload["temperature"] == 0.0
    assert "[1]" in repair_payload["messages"][-1]["content"]
    assert "Missing citation." not in str(repair_payload)
    assert result.repair["attempt_count"] == 1
    assert result.repair["trigger_error_code"] == trigger
    assert result.repair["invalid_output_included"] is False


def test_second_citation_failure_is_not_repaired_again() -> None:
    client = SequenceClient(
        _response("Missing citation."),
        _response("Still missing citation."),
    )

    with pytest.raises(GroundedOutputValidationError) as raised:
        _generate(client, [])

    assert raised.value.error_code == "cx.citation_required_missing"
    assert len(client.calls) == 2


def test_non_citation_validation_failure_is_not_repaired() -> None:
    client = SequenceClient({"output": {"type": "text", "text": ""}})

    with pytest.raises(GroundedOutputValidationError) as raised:
        _generate(client, [])

    assert raised.value.error_code == "cx.provider_output_invalid"
    assert len(client.calls) == 1


def test_citation_repair_projection_validation_fails_closed() -> None:
    valid = _generate(SequenceClient(_response("Grounded answer [1].")), []).repair
    assert validate_citation_repair_projection(valid) == valid

    mutations = (
        {**valid, "unexpected": True},
        {**valid, "repair_schema_version": "wrong"},
        {**valid, "attempted": True},
        {**valid, "max_attempts": 2},
        {**valid, "trigger_error_code": "cx.citation_required_missing"},
        {**valid, "effective_provider_prompt_package_hash": "b" * 64},
        {**valid, "same_retrieval_package": False},
        {**valid, "invalid_output_included": True},
    )
    for mutation in mutations:
        with pytest.raises(CitationRepairError):
            validate_citation_repair_projection(mutation)

    repaired = _generate(
        SequenceClient(
            _response("Missing citation."),
            _response("Grounded answer [1]."),
        ),
        [],
    ).repair
    assert validate_citation_repair_projection(repaired)["attempted"] is True


@pytest.mark.parametrize(
    ("payload_change", "package", "trigger"),
    [
        ({}, None, "cx.citation_required_missing"),
        ({"messages": []}, _retrieval_package(), "cx.citation_required_missing"),
        ({"client_request_id": ""}, _retrieval_package(), "cx.citation_required_missing"),
        (
            {"metadata": {"retrieval_package_id": "other"}},
            _retrieval_package(),
            "cx.citation_required_missing",
        ),
        (
            {
                "metadata": {
                    **_payload()["metadata"],
                    "evidence_binding_hash": "0" * 64,
                }
            },
            _retrieval_package(),
            "cx.citation_required_missing",
        ),
        ({}, _retrieval_package(), "cx.provider_output_invalid"),
    ],
)
def test_repair_payload_rejects_missing_or_changed_boundary(
    payload_change, package, trigger
) -> None:
    payload = {**_payload(), **payload_change}

    with pytest.raises(CitationRepairError):
        build_citation_repair_payload(
            payload,
            retrieval_package=package,
            selected_evidence_ids=["evidence-1"],
            trigger_error_code=trigger,
        )


def test_repair_payload_validates_labels_hashes_and_required_text() -> None:
    with pytest.raises(CitationRepairError):
        build_citation_repair_payload(
            {**_payload(), "provider_prompt_package_hash": "bad"},
            retrieval_package=_retrieval_package(),
            selected_evidence_ids=["evidence-1"],
            trigger_error_code="cx.citation_required_missing",
        )
    with pytest.raises(CitationRepairError):
        build_citation_repair_payload(
            _payload(),
            retrieval_package={**_retrieval_package(), "evidence_items": "bad"},
            selected_evidence_ids=None,
            trigger_error_code="cx.citation_required_missing",
        )
    with pytest.raises(CitationRepairError) as no_labels:
        build_citation_repair_payload(
            _payload(),
            retrieval_package=_retrieval_package(),
            selected_evidence_ids=["missing"],
            trigger_error_code="cx.citation_required_missing",
        )
    assert str(no_labels.value) == "Citation repair evidence binding is invalid."


def test_repair_payload_rejects_selected_evidence_count_drift() -> None:
    payload = _payload()
    payload["metadata"]["selected_evidence_count"] = 2

    with pytest.raises(CitationRepairError, match="count changed"):
        build_citation_repair_payload(
            payload,
            retrieval_package=_retrieval_package(),
            selected_evidence_ids=["evidence-1"],
            trigger_error_code="cx.citation_required_missing",
        )
