from __future__ import annotations

import json
from pathlib import Path

import pytest
from nex_cx.retrieval_calibration_design import (
    RetrievalCalibrationDesignError,
    admit_retrieval_calibration_v4_design,
)

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4_design.json"
)


def _payload() -> dict:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def test_admits_frozen_v4_design_and_exposes_bounded_manifest() -> None:
    admitted = admit_retrieval_calibration_v4_design(_payload())

    assert admitted.manifest == {
        "design_schema_version": "cx_retrieval_calibration_design.v1",
        "design_id": "s136-retrieval-package-confidence-v4-design",
        "design_hash": (
            "sha256:f467d2c7ba37e0b314add4961a573dad8a9f800db58762ba3644456352585a2a"
        ),
        "status": "FROZEN_NOT_AUTHORED",
        "target_dataset_schema_version": "model_calibration_dataset.v4",
        "target_dataset_id": "s136-retrieval-package-confidence-public-v4",
        "scenario_count": 100,
        "calibration_scenario_count": 80,
        "holdout_scenario_count": 20,
        "outer_fold_count": 5,
        "inner_fold_count": 4,
        "profile_ids": [
            "reranker-only-v1",
            "s20qh-three-signal-balanced-v1",
            "s20qk-three-signal-channel-v1",
            "s20qi-expanded-channel-v1",
        ],
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }
    assert admitted.design["dataset"]["package_count"] == 200
    assert admitted.design["dataset"]["candidate_count"] == 800
    assert admitted.design["selection_protocol"][
        "outer_validation_scenarios_per_fold"
    ] == 16
    assert admitted.design["selection_protocol"][
        "inner_validation_scenarios_per_fold"
    ] == 16


@pytest.mark.parametrize(
    "mutation,detail",
    [
        (lambda value: value.update(extra=True), "design fields"),
        (
            lambda value: value.update(design_schema_version="other"),
            "design_schema_version",
        ),
        (lambda value: value.update(design_id="other"), "design_id"),
        (lambda value: value.update(status="DRAFT"), "status"),
        (
            lambda value: value["predecessor"].update(dataset_id="other"),
            "predecessor",
        ),
        (
            lambda value: value["dataset"].update(scenario_count=99),
            "dataset counts",
        ),
        (
            lambda value: value["dataset"].update(extra=True),
            "dataset fields",
        ),
        (
            lambda value: value["dataset"].update(target_dataset_id="other"),
            "dataset identity",
        ),
        (
            lambda value: value["dataset"].update(package_count=199),
            "dataset counts",
        ),
        (
            lambda value: value["dataset"][
                "partition_language_scenario_counts"
            ]["CALIBRATION"].update(KOREAN=47),
            "partition language quotas",
        ),
        (
            lambda value: value["dataset"][
                "partition_domain_scenario_counts"
            ]["HOLDOUT"].update(PROJECT=5),
            "partition domain quotas",
        ),
        (
            lambda value: value["dataset"]["package_semantics"].update(
                package_score="MAXIMUM_CANDIDATE_SCORE"
            ),
            "package_semantics",
        ),
        (
            lambda value: value["dataset"]["authoring"].update(
                model_score_guided_authoring_permitted=True
            ),
            "authoring",
        ),
        (
            lambda value: value["selection_protocol"].update(
                mode="SINGLE_LEVEL_GROUP_CV"
            ),
            "mode",
        ),
        (
            lambda value: value["selection_protocol"].update(extra=True),
            "selection_protocol fields",
        ),
        (
            lambda value: value["selection_protocol"].update(outer_fold_count=4),
            "nested fold geometry",
        ),
        (
            lambda value: value["selection_protocol"].update(
                outer_validation_scenarios_per_fold=15
            ),
            "nested fold geometry",
        ),
        (
            lambda value: value["selection_protocol"].update(
                maximum_profile_count=4
            ),
            "profile shortlist size",
        ),
        (
            lambda value: value["admission"].update(
                maximum_false_ready_rate=0.15
            ),
            "admission",
        ),
        (
            lambda value: value["boundaries"].update(
                holdout_access_in_this_slice=True
            ),
            "boundaries",
        ),
    ],
)
def test_rejects_frozen_design_boundary_drift(mutation, detail: str) -> None:
    value = _payload()
    mutation(value)

    with pytest.raises(RetrievalCalibrationDesignError, match=detail):
        admit_retrieval_calibration_v4_design(value)


@pytest.mark.parametrize(
    "mutation,detail",
    [
        (
            lambda profile: profile.update(feature_fields=["unknown_signal"]),
            "feature field",
        ),
        (
            lambda profile: profile.update(feature_fields=[]),
            "feature_fields",
        ),
        (
            lambda profile: profile.update(weights={"reranker_score": 0.5}),
            "weight sum",
        ),
        (
            lambda profile: profile.update(weights={}),
            "weight fields",
        ),
        (
            lambda profile: profile.update(weights={"reranker_score": "bad"}),
            "weight",
        ),
        (
            lambda profile: profile.update(weights={"reranker_score": float("nan")}),
            "weight",
        ),
        (
            lambda profile: profile.update(evidence_source=""),
            "evidence_source",
        ),
        (
            lambda profile: profile.update(evidence_source="OTHER_SOURCE"),
            "profile shortlist drift",
        ),
    ],
)
def test_rejects_profile_shortlist_drift(mutation, detail: str) -> None:
    value = _payload()
    profile = value["selection_protocol"]["profile_shortlist"][0]
    mutation(profile)

    with pytest.raises(RetrievalCalibrationDesignError, match=detail):
        admit_retrieval_calibration_v4_design(value)


def test_rejects_duplicate_profile_and_malformed_containers() -> None:
    duplicated = _payload()
    duplicated["selection_protocol"]["profile_shortlist"][1]["profile_id"] = (
        "reranker-only-v1"
    )
    with pytest.raises(RetrievalCalibrationDesignError, match="duplicate profile_id"):
        admit_retrieval_calibration_v4_design(duplicated)

    with pytest.raises(RetrievalCalibrationDesignError, match="must be an object"):
        admit_retrieval_calibration_v4_design([])  # type: ignore[arg-type]

    malformed = _payload()
    malformed["selection_protocol"]["profile_shortlist"] = "bad"
    with pytest.raises(RetrievalCalibrationDesignError, match="must be an array"):
        admit_retrieval_calibration_v4_design(malformed)

    bad_fields = _payload()
    bad_fields["selection_protocol"]["profile_shortlist"][0]["extra"] = True
    with pytest.raises(RetrievalCalibrationDesignError, match="profile fields"):
        admit_retrieval_calibration_v4_design(bad_fields)

    bad_partition = _payload()
    del bad_partition["dataset"]["partition_language_scenario_counts"]["HOLDOUT"]
    with pytest.raises(
        RetrievalCalibrationDesignError, match="partition language quotas"
    ):
        admit_retrieval_calibration_v4_design(bad_partition)


@pytest.mark.parametrize("value", [True, 0, "100"])
def test_rejects_non_positive_integer_counts(value: object) -> None:
    payload = _payload()
    payload["dataset"]["scenario_count"] = value
    with pytest.raises(RetrievalCalibrationDesignError, match="positive integer"):
        admit_retrieval_calibration_v4_design(payload)


def test_admitted_design_is_detached_from_source_mutation() -> None:
    source = _payload()
    admitted = admit_retrieval_calibration_v4_design(source)
    source["dataset"]["authoring"]["minimum_distinct_reviewers"] = 99

    assert admitted.design["dataset"]["authoring"][
        "minimum_distinct_reviewers"
    ] == 2
