from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_collection import (
    build_answer_support_generation_payload,
    collect_answer_support_calibration,
    normalize_answer_support_generation_result,
    validate_answer_support_calibration_collection,
    validate_answer_support_request_profile,
)
from nex_cx.retrieval_answer_support_signal import build_answer_support_request
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"
REVISION = "hf:" + "a" * 40
HASH = "sha256:" + "b" * 64


def _design() -> dict:
    return json.loads((DATA / "s136_answer_support_signal_v1_design.json").read_text())


def _profile() -> dict:
    return json.loads(
        (DATA / "s136_answer_support_generation_profile_v1.json").read_text()
    )


def _case(case_id: str = "case-1", *, partition: str = "CALIBRATION") -> dict:
    return {
        "case_id": case_id,
        "scenario_id": "scenario-1",
        "partition": partition,
        "expected_ready": True,
        "query": "What is the approval policy?",
        "candidates": [
            {
                "candidate_id": "primary",
                "text": "The direct policy answer.",
                "evidence_role": "PRIMARY_ANSWER",
                "expected_relevant": True,
            },
            {
                "candidate_id": "contradiction",
                "text": "A conflicting policy statement.",
                "evidence_role": "CONTRADICTORY_NON_ANSWER",
                "expected_relevant": False,
            },
        ],
    }


def _request() -> dict:
    case = _case()
    return build_answer_support_request(
        request_id="request-1",
        query_text=case["query"],
        candidates=[
            {"candidate_id": row["candidate_id"], "text": row["text"]}
            for row in case["candidates"]
        ],
        design=_design(),
        permission_filtered=True,
        owner_scope_enforced=True,
    )


def _generation_result(request_id: str = "request-1", *, revision: str = REVISION) -> dict:
    return {
        "mo_generation_id": "generation-1",
        "alias": "general-llm-default",
        "model_revision": revision,
        "deployment_id": "deployment-a",
        "provider_type": "vllm",
        "output": {
            "type": "text",
            "text": json.dumps(
                {
                    "items": [
                        {
                            "candidate_id": "primary",
                            "classification": "DIRECT_ANSWER",
                            "answer_support_score": 0.9,
                            "contradiction_score": 0.1,
                        },
                        {
                            "candidate_id": "contradiction",
                            "classification": "CONTRADICTORY_EVIDENCE",
                            "answer_support_score": 0.1,
                            "contradiction_score": 0.9,
                        },
                    ]
                }
            ),
        },
        "finish_reason": "STOP",
        "runtime_metadata": {"request_id": request_id},
    }


def _evaluator(payload, request_id, trace_id):
    assert payload["reasoning_mode"] == "disabled"
    assert trace_id.startswith("s20qpi-trace-")
    return _generation_result(request_id)


def _collection(cases=None, *, maximum_concurrency: int = 1) -> dict:
    return collect_answer_support_calibration(
        [_case()] if cases is None else cases,
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=_design(),
        profile=_profile(),
        artifact_revision=REVISION,
        artifact_evidence_hash=HASH,
        source_retrieval_evidence_hash="sha256:" + "c" * 64,
        evaluator=_evaluator,
        maximum_concurrency=maximum_concurrency,
    )


def _rehash(value: dict) -> dict:
    value.pop("collection_hash", None)
    value["collection_hash"] = semantic_sha256_hash_ref(value)
    return value


def test_request_profile_and_generation_payload_exclude_truth_labels() -> None:
    profile = validate_answer_support_request_profile(_profile())
    payload = build_answer_support_generation_payload(_request(), profile=_profile())
    serialized = json.dumps(payload)

    assert profile["profile_hash"].startswith("sha256:")
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0.0
    assert payload["reasoning_mode"] == "disabled"
    assert "expected_ready" not in serialized
    assert "expected_relevant" not in serialized
    assert "evidence_role" not in serialized


def test_generation_result_normalizes_to_text_free_p_h_evidence() -> None:
    evidence = normalize_answer_support_generation_result(
        request=_request(),
        result=_generation_result(),
        design=_design(),
        profile=_profile(),
        artifact_revision=REVISION,
    )

    assert evidence["provider_binding"]["model_revision"] == REVISION
    assert evidence["provider_binding"]["request_profile_id"] == (
        "s136-answer-support-generation-json-v1"
    )
    assert "The direct policy answer." not in json.dumps(evidence)
    assert evidence["candidate_evidence"][0]["candidate_text_sha256"]


def test_collection_is_deterministic_text_free_and_validated() -> None:
    collection = _collection(
        [_case("case-b"), _case("case-a")], maximum_concurrency=2
    )
    validated = validate_answer_support_calibration_collection(collection)
    serialized = json.dumps(collection)

    assert collection == validated
    assert [row["package_id"] for row in collection["package_evidence"]] == [
        "case-a",
        "case-b",
    ]
    assert collection["dataset"]["package_count"] == 2
    assert collection["dataset"]["candidate_count"] == 4
    assert collection["provider_binding"]["model_revision"] == REVISION
    assert "approval policy" not in serialized
    assert "expected_ready" not in serialized
    assert collection == _collection(
        [_case("case-b"), _case("case-a")], maximum_concurrency=2
    )


def test_collection_supports_slice_specific_request_namespace() -> None:
    observed = []

    def evaluator(payload, request_id, trace_id):
        observed.append((request_id, trace_id))
        return _generation_result(request_id)

    collection = collect_answer_support_calibration(
        [_case()],
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=_design(),
        profile=_profile(),
        artifact_revision=REVISION,
        artifact_evidence_hash=HASH,
        source_retrieval_evidence_hash="sha256:" + "c" * 64,
        evaluator=evaluator,
        request_namespace="s20qpn",
    )

    assert observed == [("s20qpn-case-1", "s20qpn-trace-case-1")]
    assert collection["package_evidence"][0]["request_id"] == "s20qpn-case-1"


def test_collection_rejects_empty_request_namespace() -> None:
    with pytest.raises(ValueError, match="request_namespace"):
        collect_answer_support_calibration(
            [_case()],
            dataset_id="dataset-v4",
            dataset_sha256="dataset-sha",
            design=_design(),
            profile=_profile(),
            artifact_revision=REVISION,
            artifact_evidence_hash=HASH,
            source_retrieval_evidence_hash="sha256:" + "c" * 64,
            evaluator=_evaluator,
            request_namespace=" ",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "ACTIVE", "identity"),
        ("reasoning_mode", "enabled", "identity"),
        ("max_output_tokens", 0, "token limit"),
        ("safety", {}, "safety"),
    ],
)
def test_request_profile_rejects_drift(field, value, message) -> None:
    profile = _profile()
    profile[field] = value
    with pytest.raises(ValueError, match=message):
        validate_answer_support_request_profile(profile)


def test_request_profile_and_payload_shape_guards() -> None:
    with pytest.raises(TypeError, match="profile"):
        validate_answer_support_request_profile([])
    profile = _profile()
    profile["extra"] = True
    with pytest.raises(ValueError, match="fields"):
        validate_answer_support_request_profile(profile)
    request = _request()
    request["candidates"] = []
    with pytest.raises(ValueError, match="empty"):
        build_answer_support_generation_payload(request, profile=_profile())
    request["candidates"] = "bad"
    with pytest.raises(TypeError, match="candidates"):
        build_answer_support_generation_payload(request, profile=_profile())


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda result: result.update(finish_reason="LENGTH"), "finish"),
        (lambda result: result.update(model_revision="hf:" + "d" * 40), "revision"),
        (lambda result: result["output"].update(type="image"), "output type"),
        (lambda result: result["output"].update(text="not-json"), "not JSON"),
        (
            lambda result: result["output"].update(text='{"items":[],"extra":true}'),
            "output fields",
        ),
    ],
)
def test_generation_result_fails_closed_on_provider_drift(mutator, message) -> None:
    result = _generation_result()
    mutator(result)
    with pytest.raises(ValueError, match=message):
        normalize_answer_support_generation_result(
            request=_request(),
            result=result,
            design=_design(),
            profile=_profile(),
            artifact_revision=REVISION,
        )


def test_collection_rejects_holdout_duplicates_and_binding_drift() -> None:
    with pytest.raises(ValueError, match="HOLDOUT"):
        _collection([_case(partition="HOLDOUT")])
    with pytest.raises(ValueError, match="duplicated"):
        _collection([_case(), _case()])

    calls = 0

    def drifting(payload, request_id, trace_id):
        nonlocal calls
        calls += 1
        result = _generation_result(request_id)
        if calls == 2:
            result["deployment_id"] = "deployment-b"
        return result

    with pytest.raises(ValueError, match="binding drifted"):
        collect_answer_support_calibration(
            [_case("a"), _case("b")],
            dataset_id="dataset-v4",
            dataset_sha256="dataset-sha",
            design=_design(),
            profile=_profile(),
            artifact_revision=REVISION,
            artifact_evidence_hash=HASH,
            source_retrieval_evidence_hash="sha256:" + "c" * 64,
            evaluator=drifting,
        )


def test_collection_input_and_integrity_guards() -> None:
    with pytest.raises(TypeError, match="cases"):
        _collection("bad")
    with pytest.raises(ValueError, match="empty"):
        _collection([])
    with pytest.raises(ValueError, match="concurrency"):
        _collection([_case()], maximum_concurrency=0)
    collection = _collection()
    collection["dataset"]["candidate_count"] = 99
    collection = _rehash(collection)
    with pytest.raises(ValueError, match="counts"):
        validate_answer_support_calibration_collection(collection)

    collection = _collection()
    collection["privacy"]["raw_query_persisted"] = True
    collection = _rehash(collection)
    with pytest.raises(ValueError, match="privacy"):
        validate_answer_support_calibration_collection(collection)

    collection = _collection()
    collection["safety"]["runtime_activation_permitted"] = True
    collection = _rehash(collection)
    with pytest.raises(ValueError, match="safety"):
        validate_answer_support_calibration_collection(collection)

    collection = deepcopy(_collection())
    collection["package_evidence"][0]["request_id"] = "tampered"
    with pytest.raises(ValueError, match="integrity"):
        validate_answer_support_calibration_collection(collection)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(status="ACTIVE"), "identity"),
        (
            lambda value: value["dataset"].update(partition="HOLDOUT"),
            "partition",
        ),
        (lambda value: value.update(package_evidence=[]), "package evidence"),
    ],
)
def test_collection_validator_rejects_semantic_drift(mutator, message) -> None:
    collection = _collection()
    mutator(collection)
    collection = _rehash(collection)

    with pytest.raises(ValueError, match=message):
        validate_answer_support_calibration_collection(collection)


def test_collection_rejects_malformed_candidate_shapes() -> None:
    malformed = _case()
    malformed["candidates"] = "bad"
    with pytest.raises(TypeError, match="calibration candidates"):
        _collection([malformed])

    malformed = _case()
    malformed["candidates"][0]["text"] = ""
    with pytest.raises(ValueError, match="candidate text"):
        _collection([malformed])
