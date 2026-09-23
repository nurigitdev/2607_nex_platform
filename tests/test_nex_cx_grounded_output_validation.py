from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx.grounded_output_validation import (
    GROUNDED_OUTPUT_VALIDATION_SCHEMA_VERSION,
    GroundedOutputValidationError,
    normalize_generation_provider_response,
)


def provider_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "mo_generation_id": "mo-gen-001",
        "alias": "general-llm-default",
        "model_revision": "Qwen3.5-4B",
        "deployment_id": "dgx-generation-9111",
        "provider_type": "openai-compatible-generation",
        "output": {"type": "text", "text": "Grounded answer [1]."},
        "finish_reason": "stop",
        "usage": {
            "input_tokens": 12,
            "output_tokens": 4,
            "total_tokens": 16,
            "ignored": 99,
        },
        "runtime_metadata": {"provider_ms": 25},
    }
    response.update(overrides)
    return response


def retrieval_package() -> dict[str, object]:
    return {
        "retrieval_package_id": "cx-ret-001",
        "evidence_items": [
            {"evidence_id": "evidence-001", "citation_label": "[1]"},
            {"evidence_id": "evidence-002", "citation_label": "[2]"},
        ],
    }


def normalize(
    response: object | None = None,
    *,
    grounding_required: bool = True,
    package: object | None = None,
    selected: object = None,
) -> dict[str, object]:
    return normalize_generation_provider_response(
        provider_response() if response is None else response,
        grounding_required=grounding_required,
        retrieval_package=(retrieval_package() if package is None else package),
        selected_evidence_ids=selected,
    )


def test_normalize_grounded_provider_response_validates_selected_citations() -> None:
    response = provider_response(
        output={"type": "text", "text": "  Fact [1]. Repeated [1].  "},
    )

    normalized = normalize(response, selected=["evidence-001"])

    assert normalized["output"] == {"type": "text", "text": "Fact [1]. Repeated [1]."}
    assert normalized["finish_reason"] == "STOP"
    assert normalized["usage"] == {
        "input_tokens": 12,
        "output_tokens": 4,
        "total_tokens": 16,
    }
    assert normalized["runtime_metadata"] == {"provider_ms": 25}
    audit = normalized["grounded_output_validation"]
    assert audit["validation_schema_version"] == (
        GROUNDED_OUTPUT_VALIDATION_SCHEMA_VERSION
    )
    assert audit["status"] == "PASS"
    assert audit["grounding_required"] is True
    assert audit["output_char_count"] == 23
    assert audit["citation_labels"] == ["[1]"]
    assert audit["citation_count"] == 1
    assert audit["raw_output_included"] is False
    assert len(audit["output_sha256"]) == 64


def test_general_generation_allows_uncited_output_and_missing_optional_maps() -> None:
    normalized = normalize(
        provider_response(
            output={"type": "text", "text": "General answer."},
            usage=None,
            runtime_metadata=None,
        ),
        grounding_required=False,
        package=None,
    )

    assert normalized["usage"] == {}
    assert normalized["runtime_metadata"] == {}
    assert normalized["grounded_output_validation"]["citation_labels"] == []


@pytest.mark.parametrize(
    ("output_text", "selected", "expected_code"),
    [
        ("No citation.", ["evidence-001"], "cx.citation_required_missing"),
        ("Wrong selection [2].", ["evidence-001"], "cx.citation_validation_failed"),
        ("Unknown citation [3].", None, "cx.citation_validation_failed"),
    ],
)
def test_grounded_output_rejects_missing_or_unadmitted_citations(
    output_text: str,
    selected: list[str] | None,
    expected_code: str,
) -> None:
    with pytest.raises(GroundedOutputValidationError) as exc:
        normalize(
            provider_response(output={"type": "text", "text": output_text}),
            selected=selected,
        )

    assert exc.value.status_code == 502
    assert exc.value.error_code == expected_code
    assert exc.value.retryable is True
    assert str(exc.value) == exc.value.detail


@pytest.mark.parametrize(
    "response",
    [
        [],
        {**provider_response(), "output": None},
        {**provider_response(), "output": {"type": "json", "text": "answer"}},
        {**provider_response(), "output": {"type": "text", "text": ""}},
        {**provider_response(), "output": {"type": "text", "text": 17}},
    ],
)
def test_provider_output_rejects_invalid_response_shape(response: object) -> None:
    with pytest.raises(GroundedOutputValidationError) as exc:
        normalize(response)

    assert exc.value.error_code == "cx.provider_output_invalid"


@pytest.mark.parametrize("finish_reason", ["length", "CONTENT_FILTER", "tool_calls"])
def test_provider_output_rejects_incomplete_finish_reason(finish_reason: str) -> None:
    with pytest.raises(GroundedOutputValidationError) as exc:
        normalize(provider_response(finish_reason=finish_reason))

    assert exc.value.error_code == "cx.provider_output_incomplete"
    assert finish_reason.upper() in exc.value.detail


@pytest.mark.parametrize(
    "field",
    [
        "finish_reason",
        "mo_generation_id",
        "alias",
        "model_revision",
        "deployment_id",
        "provider_type",
    ],
)
def test_provider_output_requires_lineage_fields(field: str) -> None:
    response = provider_response()
    response[field] = ""

    with pytest.raises(GroundedOutputValidationError) as exc:
        normalize(response)

    assert exc.value.error_code == "cx.provider_output_invalid"


@pytest.mark.parametrize(
    "package",
    [
        False,
        {"evidence_items": "bad"},
        {"evidence_items": ["bad"]},
        {"evidence_items": []},
        {
            "evidence_items": [
                {"evidence_id": "same", "citation_label": "[1]"},
                {"evidence_id": "same", "citation_label": "[2]"},
            ]
        },
        {
            "evidence_items": [
                {"evidence_id": "one", "citation_label": "[1]"},
                {"evidence_id": "two", "citation_label": "[1]"},
            ]
        },
    ],
)
def test_grounded_output_rejects_invalid_retrieval_binding(package: object) -> None:
    with pytest.raises(GroundedOutputValidationError) as exc:
        normalize(package=package)

    assert exc.value.error_code == "cx.provider_output_invalid"


@pytest.mark.parametrize(
    "selected",
    ["evidence-001", ["evidence-001", "evidence-001"], ["missing"], [""]],
)
def test_grounded_output_rejects_invalid_selected_evidence(selected: object) -> None:
    with pytest.raises(GroundedOutputValidationError):
        normalize(selected=selected)


def test_normalization_copies_provider_maps_and_filters_invalid_usage() -> None:
    response = deepcopy(provider_response())
    response["usage"] = {
        "input_tokens": True,
        "output_tokens": -1,
        "total_tokens": 4,
    }
    runtime_metadata = {"provider_ms": 25}
    response["runtime_metadata"] = runtime_metadata

    normalized = normalize(response)
    runtime_metadata["provider_ms"] = 99

    assert normalized["usage"] == {"total_tokens": 4}
    assert normalized["runtime_metadata"] == {"provider_ms": 25}
