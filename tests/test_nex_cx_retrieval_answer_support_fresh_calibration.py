from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nex_cx.retrieval_answer_support_fresh_calibration as subject
import pytest
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "smoke" / "data"
REPORT = ROOT / "reports" / "live"


def _design() -> dict:
    return json.loads(
        (DATA / "s136_answer_support_fresh_calibration_v1_design.json").read_text()
    )


def _freeze() -> dict:
    return json.loads(
        (REPORT / "gb2_ca00_s20qpl_canonical_profile_freeze.json").read_text()
    )["freeze"]


def _predecessor() -> list[dict]:
    return json.loads(
        (DATA / "s136_retrieval_package_calibration_v4.json").read_text()
    )["cases"]


def _rehash_freeze(value: dict) -> None:
    value.pop("freeze_hash", None)
    value["freeze_hash"] = semantic_sha256_hash_ref(value)


def test_build_and_admit_fresh_calibration_matrix() -> None:
    dataset = subject.build_fresh_calibration_dataset(
        _design(), p_l_freeze=_freeze()
    )
    admission = subject.admit_fresh_calibration_dataset(
        dataset,
        design=_design(),
        p_l_freeze=_freeze(),
        predecessor_cases=_predecessor(),
    )

    assert len(dataset["cases"]) == 200
    assert admission["status"] == "ADMITTED_FRESH_CALIBRATION_ONLY"
    assert admission["scenario_count"] == 100
    assert admission["language_scenario_counts"] == {
        "KOREAN": 60,
        "KOREAN_ENGLISH_MIXED": 20,
        "ENGLISH": 20,
    }
    assert admission["holdout_case_count"] == 0
    assert admission["provider_calls"] == 0


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(status="ACTIVE"), "identity"),
        (lambda value: value.update(source_binding={}), "source binding fields"),
        (lambda value: value.update(dataset={}), "dataset design"),
        (lambda value: value.update(package_semantics={}), "package semantics"),
        (lambda value: value.update(authoring={}), "authoring"),
        (lambda value: value.update(safety={}), "safety"),
    ],
)
def test_design_rejects_drift(mutator, message) -> None:
    design = _design()
    mutator(design)
    with pytest.raises((TypeError, ValueError), match=message):
        subject.validate_fresh_calibration_design(design)


def test_build_rejects_p_l_binding_drift() -> None:
    for mutator in (
        lambda value: value.update(design_hash="sha256:" + "0" * 64),
        lambda value: value["canonical_profile"].update(threshold=0.5),
        lambda value: value.update(runtime_activation_permitted=True),
    ):
        freeze = deepcopy(_freeze())
        mutator(freeze)
        _rehash_freeze(freeze)
        with pytest.raises(ValueError, match="P-L freeze binding"):
            subject.build_fresh_calibration_dataset(
                _design(), p_l_freeze=freeze
            )


def test_admission_rejects_materialization_and_predecessor_overlap() -> None:
    dataset = subject.build_fresh_calibration_dataset(
        _design(), p_l_freeze=_freeze()
    )
    changed = deepcopy(dataset)
    changed["cases"][0]["query"] += " changed"
    with pytest.raises(ValueError, match="materialization"):
        subject.admit_fresh_calibration_dataset(
            changed,
            design=_design(),
            p_l_freeze=_freeze(),
            predecessor_cases=_predecessor(),
        )

    overlap = [{"query": dataset["cases"][0]["query"], "candidates": []}]
    with pytest.raises(ValueError, match="overlaps"):
        subject.admit_fresh_calibration_dataset(
            dataset,
            design=_design(),
            p_l_freeze=_freeze(),
            predecessor_cases=overlap,
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["cases"].pop(), "package count"),
        (
            lambda value: value["cases"][0].update(scenario_id="new-scenario"),
            "scenario pairing",
        ),
        (
            lambda value: [
                row.update(language_profile="ENGLISH")
                for row in value["cases"]
                if row["scenario_id"] == "fresh-project-01"
            ],
            "stratification",
        ),
        (
            lambda value: value["cases"][0].update(partition="HOLDOUT"),
            "partition",
        ),
        (
            lambda value: value["cases"][0].update(language_profile="ENGLISH"),
            "metadata drifted",
        ),
    ],
)
def test_admission_rejects_structural_drift(mutator, message) -> None:
    dataset = subject.build_fresh_calibration_dataset(
        _design(), p_l_freeze=_freeze()
    )
    mutator(dataset)
    with pytest.raises(ValueError, match=message):
        subject.admit_fresh_calibration_dataset(
            dataset,
            design=_design(),
            p_l_freeze=_freeze(),
            predecessor_cases=_predecessor(),
        )


def test_helpers_cover_languages_and_fail_closed_guards() -> None:
    assert [subject._language_for_index(value) for value in (1, 13, 17)] == [
        "KOREAN",
        "KOREAN_ENGLISH_MIXED",
        "ENGLISH",
    ]
    assert subject._policy_fact("PROJECT", "ENGLISH", 1)[1] == "2 days"
    with pytest.raises(ValueError, match="duplicated"):
        subject._require_unique(["same", "same"], "value")
    with pytest.raises(TypeError, match="mapping"):
        subject._mapping([], "mapping")
    with pytest.raises(ValueError, match="fields"):
        subject._exact_mapping({}, {"required"}, "fields")
    with pytest.raises(ValueError, match="text"):
        subject._required_text("", "text")
