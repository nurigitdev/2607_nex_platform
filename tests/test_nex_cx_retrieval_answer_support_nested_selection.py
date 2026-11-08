from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nex_cx.retrieval_answer_support_nested_selection as nested
import pytest
from nex_cx.retrieval_answer_support_collection import (
    collect_answer_support_calibration,
)
from nex_cx.retrieval_answer_support_nested_selection import (
    ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION,
    build_answer_support_nested_samples,
    select_nested_answer_support_profile,
    validate_answer_support_nested_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"
REVISION = "hf:" + "a" * 40
HASH = "sha256:" + "b" * 64


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _design() -> dict:
    return _load("s136_answer_support_nested_calibration_v1_design.json")


def _signal_design() -> dict:
    return _load("s136_answer_support_signal_v1_design.json")


def _request_profile() -> dict:
    return _load("s136_answer_support_generation_profile_v1.json")


def _case(case_id: str, *, ready: bool) -> dict:
    return {
        "case_id": case_id,
        "scenario_id": "scenario-1",
        "partition": "CALIBRATION",
        "language_profile": "KOREAN",
        "domain": "PROJECT",
        "expected_ready": ready,
        "query": f"query-{case_id}",
        "candidates": [
            {"candidate_id": "one", "text": "answer one"},
            {"candidate_id": "two", "text": "answer two"},
            {"candidate_id": "three", "text": "other three"},
            {"candidate_id": "four", "text": "other four"},
        ],
    }


def _collection(cases: list[dict]) -> dict:
    ready_by_id = {case["case_id"]: case["expected_ready"] for case in cases}

    def evaluator(payload, request_id, trace_id):
        del trace_id
        case_id = request_id.removeprefix("s20qpi-")
        ready = ready_by_id[case_id]
        user = json.loads(payload["messages"][1]["content"])
        items = []
        for index, candidate in enumerate(user["candidates"]):
            support = 0.9 if ready and index < 2 else 0.1
            items.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "classification": (
                        "DIRECT_ANSWER" if support > 0.5 else "TOPICAL_NON_ANSWER"
                    ),
                    "answer_support_score": support,
                    "contradiction_score": 0.0,
                }
            )
        return {
            "alias": "general-llm-default",
            "model_revision": REVISION,
            "deployment_id": "deployment-a",
            "provider_type": "vllm",
            "output": {"type": "text", "text": json.dumps({"items": items})},
            "finish_reason": "STOP",
        }

    return collect_answer_support_calibration(
        cases,
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        design=_signal_design(),
        profile=_request_profile(),
        artifact_revision=REVISION,
        artifact_evidence_hash=HASH,
        source_retrieval_evidence_hash="sha256:" + "c" * 64,
        evaluator=evaluator,
    )


def _sample(scenario: int, *, ready: bool, value: float) -> dict:
    features = {
        "direct_or_support_fraction": value,
        "second_answer_support_score": value,
        "top_two_answer_support_mean": value,
        "inverse_maximum_contradiction_score": value,
        "inverse_mean_contradiction_score": value,
        "normalized_support_contradiction_margin": value,
    }
    row = {
        "sample_schema_version": ANSWER_SUPPORT_NESTED_SAMPLE_SCHEMA_VERSION,
        "sample_id": f"scenario-{scenario}-{'ready' if ready else 'low'}",
        "scenario_id": f"scenario-{scenario}",
        "expected_ready": ready,
        "domain": "PROJECT",
        "language_profile": "KOREAN",
        "features": features,
        "source_feature_hash": semantic_sha256_hash_ref(
            {"scenario": scenario, "ready": ready, "kind": "feature"}
        ),
        "source_evidence_hash": semantic_sha256_hash_ref(
            {"scenario": scenario, "ready": ready, "kind": "evidence"}
        ),
    }
    row["sample_hash"] = semantic_sha256_hash_ref(row)
    return row


def _samples(*, separated: bool = True) -> list[dict]:
    return [
        _sample(
            scenario,
            ready=ready,
            value=(0.9 if ready else 0.1) if separated else 0.5,
        )
        for scenario in range(20)
        for ready in (False, True)
    ]


def _fold_plan() -> dict:
    scenario_ids = [f"scenario-{value}" for value in range(20)]
    outer_folds = []
    for outer_index in range(5):
        validation = scenario_ids[outer_index * 4 : outer_index * 4 + 4]
        training = [value for value in scenario_ids if value not in validation]
        inner_folds = [
            {
                "fold_index": inner_index,
                "validation_scenario_ids": training[
                    inner_index * 4 : inner_index * 4 + 4
                ],
            }
            for inner_index in range(4)
        ]
        outer_folds.append(
            {
                "fold_index": outer_index,
                "validation_scenario_ids": validation,
                "inner_folds": inner_folds,
            }
        )
    return {
        "assignment": {"outer_fold_count": 5, "outer_folds": outer_folds}
    }


def _select(samples: list[dict]) -> dict:
    return select_nested_answer_support_profile(
        samples,
        dataset_id="dataset-v4",
        dataset_sha256="dataset-sha",
        collection_hash=HASH,
        provider_binding={
            "provider_alias": "general-llm-default",
            "provider_type": "vllm",
            "model_revision": REVISION,
            "deployment_id": "deployment-a",
            "request_profile_id": "request-profile-v1",
            "score_semantics_id": "ordinal-v1",
        },
        design=_design(),
        fold_plan=_fold_plan(),
    )


def test_build_samples_reconstructs_integrity_bound_text_free_features() -> None:
    cases = [_case("low", ready=False), _case("ready", ready=True)]
    samples = build_answer_support_nested_samples(_collection(cases), cases)

    assert len(samples) == 2
    assert samples[0]["features"]["second_answer_support_score"] == 0.1
    assert samples[1]["features"]["second_answer_support_score"] == 0.9
    assert "query-low" not in json.dumps(samples)
    assert "answer one" not in json.dumps(samples)


def test_nested_selection_admits_stable_perfect_profile_without_holdout() -> None:
    result = _select(_samples())

    assert result["status"] == "CALIBRATION_OOF_ADMITTED"
    assert result["selected"]["profile_id"] == "answer-support-second-v1"
    assert result["oof_evaluation"]["metrics"]["ready_recall"] == 1.0
    assert result["oof_evaluation"]["metrics"]["false_ready_rate"] == 0.0
    assert result["holdout"] == {
        "status": "SEALED_NOT_OPENED",
        "scenario_count": 20,
        "threshold_reselected": False,
    }
    assert result["runtime_activation_permitted"] is False


def test_nested_selection_fails_closed_when_profiles_do_not_separate() -> None:
    result = _select(_samples(separated=False))

    assert result["status"] == "NO_ADMISSIBLE_PROFILE"
    assert result["selected"] is None
    assert result["holdout_access_permitted"] is False


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(status="ACTIVE"), "identity"),
        (lambda value: value.update(profile_shortlist=[]), "profiles"),
        (lambda value: value.update(safety={}), "safety"),
        (
            lambda value: value["admission"].update(
                minimum_profile_selection_fold_count=0
            ),
            "fold_count",
        ),
    ],
)
def test_design_rejects_contract_drift(mutator, message) -> None:
    design = _design()
    mutator(design)
    with pytest.raises((TypeError, ValueError), match=message):
        validate_answer_support_nested_design(design)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(source_contract={}), "source contract"),
        (
            lambda value: value["feature_transforms"].update(source_fields=[]),
            "feature transforms",
        ),
        (
            lambda value: value["feature_transforms"].update(
                inverse_mean_contradiction_score="invalid"
            ),
            "feature transforms",
        ),
        (
            lambda value: value.update(
                profile_shortlist=value["profile_shortlist"][:3]
            ),
            "shortlist",
        ),
        (
            lambda value: value["selection_protocol"].update(mode="invalid"),
            "selection protocol",
        ),
        (
            lambda value: value["selection_protocol"].update(
                selection_tie_break=[]
            ),
            "tie break",
        ),
        (
            lambda value: value["admission"].update(
                point_constraints_remain_authoritative=False
            ),
            "admission",
        ),
    ],
)
def test_design_rejects_each_frozen_boundary(mutator, message) -> None:
    design = _design()
    mutator(design)
    with pytest.raises(ValueError, match=message):
        validate_answer_support_nested_design(design)


def test_sample_and_fold_integrity_guards() -> None:
    samples = _samples()
    tampered = deepcopy(samples)
    tampered[0]["features"]["second_answer_support_score"] = 1.0
    with pytest.raises(ValueError, match="integrity"):
        _select(tampered)

    duplicated = [*samples, deepcopy(samples[0])]
    with pytest.raises(ValueError, match="duplicated"):
        _select(duplicated)

    folds = _fold_plan()
    folds["assignment"]["outer_folds"][0]["inner_folds"].pop()
    with pytest.raises(ValueError, match="inner fold coverage"):
        select_nested_answer_support_profile(
            samples,
            dataset_id="dataset-v4",
            dataset_sha256="dataset-sha",
            collection_hash=HASH,
            provider_binding={field: "value" for field in (
                "provider_alias",
                "provider_type",
                "model_revision",
                "deployment_id",
                "request_profile_id",
                "score_semantics_id",
            )},
            design=_design(),
            fold_plan=folds,
        )


def test_builder_rejects_package_coverage_and_holdout_is_ignored() -> None:
    cases = [_case("low", ready=False), _case("ready", ready=True)]
    collection = _collection(cases)
    with pytest.raises(ValueError, match="coverage"):
        build_answer_support_nested_samples(collection, cases[:-1])

    holdout = _case("holdout", ready=True)
    holdout["partition"] = "HOLDOUT"
    samples = build_answer_support_nested_samples(collection, [*cases, holdout])
    assert len(samples) == 2


def test_builder_rejects_invalid_and_duplicate_dataset_cases() -> None:
    cases = [_case("low", ready=False), _case("ready", ready=True)]
    collection = _collection(cases)
    with pytest.raises(TypeError, match="dataset cases"):
        build_answer_support_nested_samples(collection, "invalid")
    with pytest.raises(ValueError, match="duplicated"):
        build_answer_support_nested_samples(
            collection, [cases[0], cases[0], cases[1]]
        )


def _rehash(row: dict) -> None:
    unsigned = dict(row)
    unsigned.pop("sample_hash", None)
    row["sample_hash"] = semantic_sha256_hash_ref(unsigned)


def test_sample_contract_guards_cover_identity_fields_pairs_and_labels() -> None:
    with pytest.raises(TypeError, match="samples"):
        nested._normalize_samples("invalid")

    samples = _samples()
    invalid_identity = deepcopy(samples)
    invalid_identity[0]["sample_schema_version"] = "invalid"
    _rehash(invalid_identity[0])
    with pytest.raises(ValueError, match="identity"):
        nested._normalize_samples(invalid_identity)

    invalid_features = deepcopy(samples)
    invalid_features[0]["features"].pop("direct_or_support_fraction")
    _rehash(invalid_features[0])
    with pytest.raises(ValueError, match="feature fields"):
        nested._normalize_samples(invalid_features)

    with pytest.raises(ValueError, match="scenario pairs"):
        nested._normalize_samples(samples[:-1])

    invalid_labels = deepcopy(samples)
    invalid_labels[1]["expected_ready"] = False
    _rehash(invalid_labels[1])
    with pytest.raises(ValueError, match="scenario labels"):
        nested._normalize_samples(invalid_labels)


def test_profile_admission_and_primitive_contract_guards() -> None:
    profile = deepcopy(_design()["profile_shortlist"][0])
    with pytest.raises(TypeError, match="profiles"):
        nested._profiles("invalid")

    invalid_fields = deepcopy(profile)
    invalid_fields["feature_fields"] = []
    invalid_fields["weights"] = {}
    with pytest.raises(ValueError, match="profile fields"):
        nested._profiles([invalid_fields])

    invalid_weight = deepcopy(profile)
    invalid_weight["weights"][invalid_weight["feature_fields"][0]] = 0.5
    with pytest.raises(ValueError, match="profile weights"):
        nested._profiles([invalid_weight])

    with pytest.raises(ValueError, match="duplicated"):
        nested._profiles([profile, profile])
    with pytest.raises(ValueError, match="admission fields"):
        nested._admission({})
    with pytest.raises(ValueError, match="AUC"):
        nested._auc([{"score": 1.0, "expected_ready": True}])
    with pytest.raises(ValueError, match="profile binding"):
        nested._find_profile([profile], "missing")
    assert nested._find_profile(
        [{"profile_id": "first"}, {"profile_id": "second"}], "second"
    )["profile_id"] == "second"
    with pytest.raises(ValueError, match="provider binding fields"):
        nested._provider_binding({})
    with pytest.raises(ValueError, match="fields"):
        nested._exact_mapping({}, {"required"}, "mapping")
    with pytest.raises(TypeError, match="mapping"):
        nested._mapping([], "mapping")
    with pytest.raises(ValueError, match="text"):
        nested._required_text(" ", "text")
    with pytest.raises(TypeError, match="flag"):
        nested._required_bool(1, "flag")
    for value in (True, "1", float("nan"), 2.0):
        with pytest.raises(ValueError, match="score"):
            nested._bounded(value, "score")
    for value in (True, "1", 0):
        with pytest.raises(ValueError, match="count"):
            nested._positive_int(value, "count")


def test_feature_and_fold_plan_guards() -> None:
    features = {
        field: 0.5 for field in nested.SOURCE_FEATURE_FIELDS
    }
    features["second_answer_support_score"] = -0.1
    with pytest.raises(ValueError, match="package feature"):
        nested._transformed_features(features)

    folds = _fold_plan()
    with pytest.raises(ValueError, match="outer fold count"):
        nested._validated_outer_folds(
            folds,
            scenario_ids={f"scenario-{value}" for value in range(20)},
            outer_count=4,
            inner_count=4,
        )

    folds = _fold_plan()
    folds["assignment"]["outer_folds"][0]["inner_folds"] = "invalid"
    with pytest.raises(TypeError, match="inner folds"):
        nested._validated_outer_folds(
            folds,
            scenario_ids={f"scenario-{value}" for value in range(20)},
            outer_count=5,
            inner_count=4,
        )


def test_nested_selection_handles_inner_threshold_and_refit_failures(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        nested,
        "evaluate_binary_score_calibration",
        lambda *_args, **_kwargs: {
            "status": "FAILED",
            "selected_threshold": None,
            "best_effort_metrics": {},
        },
    )
    result = _select(_samples())
    assert result["status"] == "NO_ADMISSIBLE_PROFILE"
    assert all(
        row["status"] == "NO_ADMISSIBLE_PROFILE"
        for row in result["outer_folds"]
    )


def test_nested_selection_handles_outer_refit_and_full_fit_failures(
    monkeypatch,
) -> None:
    original = nested.evaluate_binary_score_calibration

    def fail_refit(values, *, dataset_id, constraints):
        if ":refit" in dataset_id:
            return {"status": "FAILED", "selected_threshold": None}
        return original(values, dataset_id=dataset_id, constraints=constraints)

    monkeypatch.setattr(nested, "evaluate_binary_score_calibration", fail_refit)
    result = _select(_samples())
    assert all(row["status"] == "OUTER_REFIT_FAILED" for row in result["outer_folds"])

    def fail_full_fit(values, *, dataset_id, constraints):
        if dataset_id.endswith(":full-calibration"):
            return {"status": "FAILED"}
        return original(values, dataset_id=dataset_id, constraints=constraints)

    monkeypatch.setattr(nested, "evaluate_binary_score_calibration", fail_full_fit)
    result = _select(_samples())
    assert result["status"] == "NO_ADMISSIBLE_PROFILE"
    assert result["checks"]["full_calibration_threshold_fitted"] is False
