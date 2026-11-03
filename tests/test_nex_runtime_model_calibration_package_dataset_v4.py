from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from nex_runtime import (
    CANDIDATE_ROLE_EXPECTED_RELEVANT,
    CANDIDATE_ROLE_IDS,
    LOW_CONFIDENCE_CANDIDATE_ROLES,
    MODEL_CALIBRATION_PACKAGE_DATASET_V4_ID,
    MODEL_CALIBRATION_PACKAGE_DATASET_V4_SCHEMA_VERSION,
    PACKAGE_V4_PARTITION_DOMAIN_SCENARIO_QUOTAS,
    PACKAGE_V4_PARTITION_LANGUAGE_SCENARIO_QUOTAS,
    PACKAGE_V4_PARTITION_SCENARIO_QUOTAS,
    READY_CANDIDATE_ROLES,
    ModelCalibrationPackageDatasetError,
    admit_model_calibration_package_dataset_v4,
)

ROOT = Path(__file__).parents[1]


def _candidate(role: str, index: int, label: str) -> dict[str, object]:
    return {
        "candidate_id": CANDIDATE_ROLE_IDS[role],
        "evidence_role": role,
        "expected_relevant": CANDIDATE_ROLE_EXPECTED_RELEVANT[role],
        "text": f"V4 unique {label} {role} candidate text {index}",
    }


def build_v4_dataset() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    reviews: list[dict[str, object]] = []
    index = 0
    for partition, count in PACKAGE_V4_PARTITION_SCENARIO_QUOTAS.items():
        languages = [
            language
            for language, quota in (
                PACKAGE_V4_PARTITION_LANGUAGE_SCENARIO_QUOTAS[partition].items()
            )
            for _ in range(quota)
        ]
        domains = [
            domain
            for domain, quota in (
                PACKAGE_V4_PARTITION_DOMAIN_SCENARIO_QUOTAS[partition].items()
            )
            for _ in range(quota)
        ]
        assert len(languages) == len(domains) == count
        for language, domain in zip(languages, domains, strict=True):
            index += 1
            scenario_id = f"scenario-{index:03d}"
            for label, expected_ready, roles in (
                ("ready", True, READY_CANDIDATE_ROLES),
                ("low-confidence", False, LOW_CONFIDENCE_CANDIDATE_ROLES),
            ):
                cases.append(
                    {
                        "case_id": f"{scenario_id}-{label}",
                        "scenario_id": scenario_id,
                        "partition": partition,
                        "language_profile": language,
                        "domain": domain,
                        "expected_ready": expected_ready,
                        "query": f"V4 unique {label} package query {index}",
                        "candidates": [
                            _candidate(role, index, label) for role in sorted(roles)
                        ],
                    }
                )
            reviews.append(
                {
                    "scenario_id": scenario_id,
                    "author_ref": "calibration-author",
                    "reviewer_ref": "calibration-reviewer",
                    "review_status": "APPROVED",
                    "semantic_near_duplicate_status": "REVIEWED_NO_CONFLICT",
                    "model_score_guided_authoring": False,
                    "mechanical_paraphrase": False,
                }
            )
    return {
        "dataset_schema_version": (
            MODEL_CALIBRATION_PACKAGE_DATASET_V4_SCHEMA_VERSION
        ),
        "dataset_id": MODEL_CALIBRATION_PACKAGE_DATASET_V4_ID,
        "cases": cases,
        "scenario_reviews": reviews,
    }


def test_admits_v4_dataset_and_builds_redacted_manifest() -> None:
    payload = build_v4_dataset()
    admitted = admit_model_calibration_package_dataset_v4(payload)

    assert admitted.manifest["scenario_count"] == 100
    assert admitted.manifest["package_count"] == 200
    assert admitted.manifest["candidate_count"] == 800
    assert admitted.manifest["partition_scenario_counts"] == {
        "CALIBRATION": 80,
        "HOLDOUT": 20,
    }
    assert admitted.manifest["partition_package_counts"] == {
        "CALIBRATION": 160,
        "HOLDOUT": 40,
    }
    assert admitted.manifest["partition_label_counts"] == {
        "CALIBRATION": {"READY": 80, "LOW_CONFIDENCE": 80},
        "HOLDOUT": {"READY": 20, "LOW_CONFIDENCE": 20},
    }
    assert admitted.manifest["scenario_review_count"] == 100
    assert admitted.manifest["independent_review_passed"] is True
    serialized = json.dumps(admitted.manifest)
    assert "package query" not in serialized
    assert "candidate text" not in serialized
    assert "calibration-author" not in serialized
    assert "calibration-reviewer" not in serialized

    replay = build_v4_dataset()
    replay["cases"].reverse()  # type: ignore[union-attr]
    replay["scenario_reviews"].reverse()  # type: ignore[union-attr]
    replayed = admit_model_calibration_package_dataset_v4(replay)
    assert replayed.manifest["dataset_sha256"] == admitted.manifest["dataset_sha256"]


def test_contract_schema_accepts_v4_shape() -> None:
    schema = json.loads(
        (
            ROOT / "contracts/schemas/common/model_calibration_dataset.v4.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(build_v4_dataset())


@pytest.mark.parametrize(
    "mutation,detail",
    [
        (lambda value: value.update(dataset_schema_version="bad"), "schema"),
        (lambda value: value.update(dataset_id="bad"), "dataset_id"),
        (lambda value: value.update(extra=True), "dataset fields"),
        (lambda value: value["cases"].pop(), "exactly 200"),
        (
            lambda value: value["cases"].__setitem__(1, deepcopy(value["cases"][0])),
            "duplicate case_id",
        ),
        (
            lambda value: (
                value["cases"][0].update(partition="HOLDOUT"),
                value["cases"][1].update(partition="HOLDOUT"),
            ),
            "partition scenario quota",
        ),
        (
            lambda value: (
                value["cases"][0].update(language_profile="ENGLISH"),
                value["cases"][1].update(language_profile="ENGLISH"),
            ),
            "partition language_profile scenario quota",
        ),
        (
            lambda value: (
                value["cases"][0].update(domain="FINANCE"),
                value["cases"][1].update(domain="FINANCE"),
            ),
            "partition domain scenario quota",
        ),
    ],
)
def test_rejects_v4_dataset_and_quota_drift(mutation, detail: str) -> None:
    payload = build_v4_dataset()
    mutation(payload)
    with pytest.raises(ModelCalibrationPackageDatasetError, match=detail):
        admit_model_calibration_package_dataset_v4(payload)


@pytest.mark.parametrize(
    "mutation,detail",
    [
        (lambda value: value["scenario_reviews"].pop(), "exactly 100"),
        (
            lambda value: value["scenario_reviews"][0].update(extra=True),
            "scenario_review fields",
        ),
        (
            lambda value: value["scenario_reviews"][0].update(
                reviewer_ref="calibration-author"
            ),
            "must be distinct",
        ),
        (
            lambda value: value["scenario_reviews"][0].update(
                review_status="PENDING"
            ),
            "review_status",
        ),
        (
            lambda value: value["scenario_reviews"][0].update(
                semantic_near_duplicate_status="NOT_REVIEWED"
            ),
            "semantic_near_duplicate_status",
        ),
        (
            lambda value: value["scenario_reviews"][0].update(
                model_score_guided_authoring=True
            ),
            "model_score_guided_authoring",
        ),
        (
            lambda value: value["scenario_reviews"][0].update(
                mechanical_paraphrase=True
            ),
            "mechanical_paraphrase",
        ),
        (
            lambda value: value["scenario_reviews"][0].update(
                scenario_id="scenario-999"
            ),
            "cover every scenario",
        ),
        (
            lambda value: value["scenario_reviews"].__setitem__(
                1, deepcopy(value["scenario_reviews"][0])
            ),
            "duplicate review scenario_id",
        ),
    ],
)
def test_rejects_incomplete_or_unreviewed_scenarios(mutation, detail: str) -> None:
    payload = build_v4_dataset()
    mutation(payload)
    with pytest.raises(ModelCalibrationPackageDatasetError, match=detail):
        admit_model_calibration_package_dataset_v4(payload)
