from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_signal import (
    ANSWER_SUPPORT_CLASSES,
    ANSWER_SUPPORT_POLICY_ID,
    AnswerSupportSignalProvider,
    build_answer_support_package_features,
    build_answer_support_request,
    normalize_answer_support_response,
    validate_answer_support_signal_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_answer_support_signal_v1_design.json"
)


def _design() -> dict:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def _candidates() -> list[dict[str, str]]:
    return [
        {"candidate_id": "c1", "text": "The direct answer."},
        {"candidate_id": "c2", "text": "Supporting context."},
        {"candidate_id": "c3", "text": "Related but not an answer."},
        {"candidate_id": "c4", "text": "Contradictory evidence."},
    ]


def _binding() -> dict[str, str]:
    return {
        "provider_alias": "provider-a",
        "provider_type": "REMOTE_CLASSIFIER",
        "model_revision": "artifact:revision-a",
        "deployment_id": "deployment-a",
        "request_profile_id": "support-v1",
        "score_semantics_id": "ordinal-v1",
    }


def _request() -> dict:
    return build_answer_support_request(
        request_id="request-1",
        query_text="What is the policy?",
        candidates=_candidates(),
        design=_design(),
        permission_filtered=True,
        owner_scope_enforced=True,
    )


def _response() -> dict:
    return {
        "response_schema_version": "cx_answer_support_signal_response.v1",
        "request_id": "request-1",
        "provider_binding": _binding(),
        "items": [
            {
                "candidate_id": "c4",
                "classification": "CONTRADICTORY_EVIDENCE",
                "answer_support_score": 0.1,
                "contradiction_score": 0.9,
            },
            {
                "candidate_id": "c1",
                "classification": "DIRECT_ANSWER",
                "answer_support_score": 0.9,
                "contradiction_score": 0.1,
            },
            {
                "candidate_id": "c3",
                "classification": "TOPICAL_NON_ANSWER",
                "answer_support_score": 0.2,
                "contradiction_score": 0.1,
            },
            {
                "candidate_id": "c2",
                "classification": "SUPPORTING_EVIDENCE",
                "answer_support_score": 0.8,
                "contradiction_score": 0.1,
            },
        ],
    }


def _evidence() -> dict:
    return normalize_answer_support_response(
        request=_request(),
        response=_response(),
        expected_provider_binding=_binding(),
        design=_design(),
    )


def _rehash(value: dict, field: str) -> dict:
    value.pop(field, None)
    value[field] = semantic_sha256_hash_ref(value)
    return value


def test_design_request_evidence_and_package_projection_are_deterministic() -> None:
    design = validate_answer_support_signal_design(_design())
    request = _request()
    evidence = _evidence()
    features = build_answer_support_package_features(evidence)

    assert design["policy_id"] == ANSWER_SUPPORT_POLICY_ID
    assert request["query"]["text"] == "What is the policy?"
    assert request["admission"]["candidate_truth_included"] is False
    assert [row["candidate_id"] for row in evidence["candidate_evidence"]] == [
        "c1",
        "c2",
        "c3",
        "c4",
    ]
    assert "text" not in evidence["candidate_evidence"][0]
    assert features["candidate_count"] == 4
    assert features["classification_counts"]["DIRECT_ANSWER"] == 1
    assert features["features"] == {
        "direct_or_support_fraction": 0.5,
        "second_answer_support_score": 0.8,
        "top_two_answer_support_mean": 0.85,
        "maximum_contradiction_score": 0.9,
        "mean_contradiction_score": 0.3,
        "support_contradiction_margin": 0.2,
    }
    assert features["semantics"]["ready_threshold"] is None
    assert features == build_answer_support_package_features(evidence)


def test_provider_protocol_remains_implementation_neutral() -> None:
    class Stub:
        def evaluate(self, request):
            return {"request_id": request["request_id"]}

    provider: AnswerSupportSignalProvider = Stub()
    assert provider.evaluate({"request_id": "r"}) == {"request_id": "r"}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "ACTIVE", "identity"),
        ("classes", [], "classes"),
        ("score_fields", [], "score fields"),
        ("score_semantics", "PROBABILITY", "score semantics"),
        ("provider_binding_fields", [], "binding fields"),
        ("candidate_count", {"minimum": 0, "maximum": 1}, "candidate count"),
        ("raw_text_transport", "PERSISTED", "raw text"),
        ("package_feature_fields", [], "package feature"),
        ("safety", {}, "safety"),
    ],
)
def test_design_rejects_contract_drift(field, value, message) -> None:
    design = _design()
    design[field] = value
    with pytest.raises(ValueError, match=message):
        validate_answer_support_signal_design(design)


def test_design_type_fields_and_required_identity_guards() -> None:
    with pytest.raises(TypeError, match="design"):
        validate_answer_support_signal_design([])
    design = _design()
    design["extra"] = True
    with pytest.raises(ValueError, match="fields"):
        validate_answer_support_signal_design(design)
    for field in ("design_id", "source_audit"):
        invalid = _design()
        invalid[field] = ""
        with pytest.raises(ValueError, match=field):
            validate_answer_support_signal_design(invalid)


def test_request_rejects_authorization_shape_size_and_integrity_failures() -> None:
    kwargs = {
        "request_id": "r",
        "query_text": "q",
        "candidates": [{"candidate_id": "c", "text": "t"}],
        "design": _design(),
        "permission_filtered": True,
        "owner_scope_enforced": True,
    }
    for field in ("permission_filtered", "owner_scope_enforced"):
        invalid = dict(kwargs)
        invalid[field] = False
        with pytest.raises(ValueError, match="authorization"):
            build_answer_support_request(**invalid)
    with pytest.raises(ValueError, match="candidate count"):
        build_answer_support_request(**{**kwargs, "candidates": []})
    with pytest.raises(ValueError, match="candidate count"):
        build_answer_support_request(
            **{**kwargs, "candidates": _candidates() * 6}
        )
    with pytest.raises(TypeError, match="candidates"):
        build_answer_support_request(**{**kwargs, "candidates": "bad"})
    with pytest.raises(ValueError, match="duplicated"):
        build_answer_support_request(
            **{
                **kwargs,
                "candidates": [
                    {"candidate_id": "c", "text": "one"},
                    {"candidate_id": "c", "text": "two"},
                ],
            }
        )
    with pytest.raises(ValueError, match="query_text is too long"):
        build_answer_support_request(**{**kwargs, "query_text": "q" * 16_001})
    with pytest.raises(ValueError, match="candidate_text is too long"):
        build_answer_support_request(
            **{
                **kwargs,
                "candidates": [{"candidate_id": "c", "text": "t" * 64_001}],
            }
        )
    with pytest.raises(ValueError, match="candidate.*fields"):
        build_answer_support_request(
            **{
                **kwargs,
                "candidates": [{"candidate_id": "c", "text": "t", "truth": True}],
            }
        )


def test_response_rejects_binding_identity_fields_and_candidate_coverage_drift() -> None:
    cases: list[tuple[dict, str]] = []
    response = _response()
    response["extra"] = True
    cases.append((response, "fields"))
    response = _response()
    response["response_schema_version"] = "v2"
    cases.append((response, "identity"))
    response = _response()
    response["request_id"] = "other"
    cases.append((response, "request binding"))
    response = _response()
    response["provider_binding"]["model_revision"] = "other"
    cases.append((response, "provider binding"))
    response = _response()
    response["items"][0]["rationale"] = "raw"
    cases.append((response, "item fields"))
    response = _response()
    response["items"][0]["candidate_id"] = "c1"
    cases.append((response, "candidate coverage"))
    for response, message in cases:
        with pytest.raises(ValueError, match=message):
            normalize_answer_support_response(
                request=_request(),
                response=response,
                expected_provider_binding=_binding(),
                design=_design(),
            )


def test_response_rejects_score_classification_and_type_failures() -> None:
    variants = [
        ("UNKNOWN", 0.5, 0.1, "classification is invalid"),
        ("DIRECT_ANSWER", 0.1, 0.2, "score ordering"),
        ("CONTRADICTORY_EVIDENCE", 0.8, 0.2, "score ordering"),
        ("TOPICAL_NON_ANSWER", True, 0.2, "answer_support_score"),
        ("TOPICAL_NON_ANSWER", 0.1, float("nan"), "contradiction_score"),
    ]
    for classification, support, contradiction, message in variants:
        response = _response()
        response["items"][0].update(
            classification=classification,
            answer_support_score=support,
            contradiction_score=contradiction,
        )
        with pytest.raises(ValueError, match=message):
            normalize_answer_support_response(
                request=_request(),
                response=response,
                expected_provider_binding=_binding(),
                design=_design(),
            )
    response = _response()
    response["items"] = "bad"
    with pytest.raises(TypeError, match="items"):
        normalize_answer_support_response(
            request=_request(),
            response=response,
            expected_provider_binding=_binding(),
            design=_design(),
        )


def test_request_and_evidence_integrity_guards_fail_closed() -> None:
    request = _request()
    request["query"]["text"] = "tampered"
    with pytest.raises(ValueError, match="request integrity"):
        normalize_answer_support_response(
            request=request,
            response=_response(),
            expected_provider_binding=_binding(),
            design=_design(),
        )

    evidence = _evidence()
    evidence["candidate_evidence"][0]["answer_support_score"] = 0.2
    with pytest.raises(ValueError, match="evidence integrity"):
        build_answer_support_package_features(evidence)

    evidence = deepcopy(_evidence())
    evidence["raw_text"] = "forbidden"
    evidence = _rehash(evidence, "evidence_hash")
    with pytest.raises(ValueError, match="fields"):
        build_answer_support_package_features(evidence)


def test_verified_request_and_evidence_deep_guards() -> None:
    request = _request()
    request["candidates"][0]["text_sha256"] = "0" * 64
    request = _rehash(request, "request_hash")
    with pytest.raises(ValueError, match="candidate integrity"):
        normalize_answer_support_response(
            request=request,
            response=_response(),
            expected_provider_binding=_binding(),
            design=_design(),
        )

    for path, value, message in [
        (("query_sha256",), "x" * 64, "query hash"),
        (("candidate_evidence", 0, "candidate_text_sha256"), "x" * 64, "text hash"),
        (("privacy", "raw_query_persisted"), True, "privacy"),
        (("safety", "threshold_selected"), True, "safety"),
    ]:
        evidence = deepcopy(_evidence())
        target = evidence
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        evidence = _rehash(evidence, "evidence_hash")
        with pytest.raises(ValueError, match=message):
            build_answer_support_package_features(evidence)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda request: request.update(request_schema_version="v2"),
            "request identity",
        ),
        (
            lambda request: request["query"].update(sha256="0" * 64),
            "query integrity",
        ),
        (
            lambda request: request["candidates"][0].update(candidate_id=" c1 "),
            "request candidates",
        ),
        (
            lambda request: request["admission"].update(permission_filtered=False),
            "request admission",
        ),
        (
            lambda request: request["response_contract"].update(
                free_form_rationale_permitted=True
            ),
            "response contract",
        ),
    ],
)
def test_rehashed_request_semantic_drift_is_still_rejected(mutator, message) -> None:
    request = _request()
    mutator(request)
    request = _rehash(request, "request_hash")
    with pytest.raises(ValueError, match=message):
        normalize_answer_support_response(
            request=request,
            response=_response(),
            expected_provider_binding=_binding(),
            design=_design(),
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda evidence: evidence.update(status="ACTIVE"),
            "evidence identity",
        ),
        (
            lambda evidence: evidence.update(candidate_evidence=[]),
            "candidate evidence",
        ),
        (
            lambda evidence: evidence["provider_binding"].pop("deployment_id"),
            "provider binding fields",
        ),
    ],
)
def test_rehashed_evidence_semantic_drift_is_still_rejected(mutator, message) -> None:
    evidence = _evidence()
    mutator(evidence)
    evidence = _rehash(evidence, "evidence_hash")
    with pytest.raises(ValueError, match=message):
        build_answer_support_package_features(evidence)


def test_single_candidate_projection_uses_first_score_as_second_statistic() -> None:
    request = build_answer_support_request(
        request_id="single",
        query_text="query",
        candidates=[{"candidate_id": "only", "text": "answer"}],
        design=_design(),
        permission_filtered=True,
        owner_scope_enforced=True,
    )
    response = {
        "response_schema_version": "cx_answer_support_signal_response.v1",
        "request_id": "single",
        "provider_binding": _binding(),
        "items": [
            {
                "candidate_id": "only",
                "classification": "INSUFFICIENT_CONTEXT",
                "answer_support_score": 0.3,
                "contradiction_score": 0.2,
            }
        ],
    }
    evidence = normalize_answer_support_response(
        request=request,
        response=response,
        expected_provider_binding=_binding(),
        design=_design(),
    )
    features = build_answer_support_package_features(evidence)
    assert features["features"]["second_answer_support_score"] == 0.3
    assert set(features["classification_counts"]) == set(ANSWER_SUPPORT_CLASSES)
