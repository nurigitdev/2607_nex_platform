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
    MODEL_CALIBRATION_PACKAGE_DATASET_ID,
    MODEL_CALIBRATION_PACKAGE_DATASET_SCHEMA_VERSION,
    PACKAGE_DOMAIN_SCENARIO_QUOTAS,
    PACKAGE_LANGUAGE_SCENARIO_QUOTAS,
    PACKAGE_PARTITION_SCENARIO_QUOTAS,
    READY_CANDIDATE_ROLES,
    ModelCalibrationPackageDatasetError,
    admit_model_calibration_package_dataset_v3,
)

ROOT = Path(__file__).parents[1]


def _candidate(role: str, index: int, label: str) -> dict[str, object]:
    return {
        "candidate_id": CANDIDATE_ROLE_IDS[role],
        "evidence_role": role,
        "expected_relevant": CANDIDATE_ROLE_EXPECTED_RELEVANT[role],
        "text": f"Unique {label} {role} candidate text {index}",
    }


def _dataset() -> dict[str, object]:
    partitions = [
        partition
        for partition, count in PACKAGE_PARTITION_SCENARIO_QUOTAS.items()
        for _ in range(count)
    ]
    languages = [
        language
        for language, count in PACKAGE_LANGUAGE_SCENARIO_QUOTAS.items()
        for _ in range(count)
    ]
    domains = [
        domain
        for domain, count in PACKAGE_DOMAIN_SCENARIO_QUOTAS.items()
        for _ in range(count)
    ]
    cases: list[dict[str, object]] = []
    for index, (partition, language, domain) in enumerate(
        zip(partitions, languages, domains, strict=True), start=1
    ):
        scenario_id = f"scenario-{index:02d}"
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
                    "query": f"Unique {label} package query {index}",
                    "candidates": [
                        _candidate(role, index, label) for role in sorted(roles)
                    ],
                }
            )
    return {
        "dataset_schema_version": MODEL_CALIBRATION_PACKAGE_DATASET_SCHEMA_VERSION,
        "dataset_id": MODEL_CALIBRATION_PACKAGE_DATASET_ID,
        "cases": cases,
    }


def test_admits_grouped_package_dataset_and_builds_redacted_manifest() -> None:
    payload = _dataset()
    admitted = admit_model_calibration_package_dataset_v3(payload)

    assert admitted.manifest["scenario_count"] == 30
    assert admitted.manifest["package_count"] == 60
    assert admitted.manifest["candidate_count"] == 240
    assert admitted.manifest["ready_package_count"] == 30
    assert admitted.manifest["low_confidence_package_count"] == 30
    assert admitted.manifest["partition_scenario_counts"] == {
        "CALIBRATION": 20,
        "HOLDOUT": 10,
    }
    assert admitted.manifest["partition_package_counts"] == {
        "CALIBRATION": 40,
        "HOLDOUT": 20,
    }
    assert admitted.manifest["partition_label_counts"] == {
        "CALIBRATION": {"READY": 20, "LOW_CONFIDENCE": 20},
        "HOLDOUT": {"READY": 10, "LOW_CONFIDENCE": 10},
    }
    serialized = json.dumps(admitted.manifest)
    assert "Unique ready package query" not in serialized
    assert "candidate text" not in serialized
    assert admitted.dataset is not payload

    reversed_payload = _dataset()
    reversed_payload["cases"].reverse()  # type: ignore[union-attr]
    replay = admit_model_calibration_package_dataset_v3(reversed_payload)
    assert replay.manifest["dataset_sha256"] == admitted.manifest["dataset_sha256"]


def test_contract_schema_accepts_v3_shape() -> None:
    schema = json.loads(
        (
            ROOT / "contracts/schemas/common/model_calibration_dataset.v3.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_dataset())


@pytest.mark.parametrize(
    "mutation, detail",
    [
        (lambda value: value.update(dataset_schema_version="bad"), "schema"),
        (lambda value: value.update(dataset_id="bad"), "dataset_id"),
        (lambda value: value.update(extra=True), "fields"),
        (lambda value: value["cases"].pop(), "exactly 60"),
        (
            lambda value: value["cases"].__setitem__(1, deepcopy(value["cases"][0])),
            "duplicate case_id",
        ),
        (
            lambda value: value["cases"][1].update(
                query=value["cases"][0]["query"].upper()
            ),
            "duplicate query",
        ),
        (
            lambda value: value["cases"][1]["candidates"][0].update(
                text=value["cases"][0]["candidates"][0]["text"]
            ),
            "duplicate candidate text",
        ),
        (
            lambda value: value["cases"][0].update(partition="HOLDOUT"),
            "metadata must match",
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
            "language_profile scenario quota",
        ),
        (
            lambda value: (
                value["cases"][0].update(domain="FINANCE"),
                value["cases"][1].update(domain="FINANCE"),
            ),
            "domain scenario quota",
        ),
    ],
)
def test_rejects_invalid_dataset_and_scenario_contract(mutation, detail: str) -> None:
    payload = _dataset()
    mutation(payload)
    with pytest.raises(ModelCalibrationPackageDatasetError, match=detail):
        admit_model_calibration_package_dataset_v3(payload)


@pytest.mark.parametrize(
    "mutation, detail",
    [
        (lambda case: case.update(extra=True), "case fields"),
        (lambda case: case.update(scenario_id="Not Canonical"), "kebab-case"),
        (lambda case: case.update(case_id="wrong-ready"), "derived"),
        (lambda case: case.update(expected_ready="yes"), "boolean"),
        (lambda case: case.update(query=" "), "non-empty"),
        (lambda case: case.update(partition="OTHER"), "partition"),
        (lambda case: case.update(candidates={}), "array"),
        (lambda case: case["candidates"].pop(), "exactly four"),
        (
            lambda case: case["candidates"][0].update(extra=True),
            "candidate fields",
        ),
        (
            lambda case: case["candidates"][0].update(evidence_role="UNKNOWN"),
            "evidence_role",
        ),
        (
            lambda case: case["candidates"][0].update(expected_relevant="yes"),
            "boolean",
        ),
        (
            lambda case: case["candidates"][0].update(
                expected_relevant=not case["candidates"][0]["expected_relevant"]
            ),
            "match evidence_role",
        ),
        (
            lambda case: case["candidates"][0].update(candidate_id="wrong"),
            "derived",
        ),
        (
            lambda case: case["candidates"][0].update(text=""),
            "non-empty",
        ),
        (
            lambda case: case["candidates"].__setitem__(
                0, deepcopy(case["candidates"][1])
            ),
            "roles must match",
        ),
    ],
)
def test_rejects_invalid_case_and_candidate_contract(mutation, detail: str) -> None:
    payload = _dataset()
    mutation(payload["cases"][0])  # type: ignore[index]
    with pytest.raises(ModelCalibrationPackageDatasetError, match=detail):
        admit_model_calibration_package_dataset_v3(payload)


def test_rejects_missing_or_cross_partition_scenario_pairs() -> None:
    duplicate_label = _dataset()
    second = duplicate_label["cases"][1]  # type: ignore[index]
    second["scenario_id"] = "scenario-31"
    second["case_id"] = "scenario-31-low-confidence"
    with pytest.raises(ModelCalibrationPackageDatasetError, match="scenario count"):
        admit_model_calibration_package_dataset_v3(duplicate_label)

    duplicate_ready = _dataset()
    second = duplicate_ready["cases"][1]  # type: ignore[index]
    second["expected_ready"] = True
    second["case_id"] = "scenario-01-ready"
    second["candidates"] = deepcopy(duplicate_ready["cases"][0]["candidates"])  # type: ignore[index]
    with pytest.raises(ModelCalibrationPackageDatasetError, match="duplicate case_id"):
        admit_model_calibration_package_dataset_v3(duplicate_ready)


@pytest.mark.parametrize("payload", [None, [], "dataset"])
def test_rejects_non_mapping_dataset(payload: object) -> None:
    with pytest.raises(ModelCalibrationPackageDatasetError, match="object"):
        admit_model_calibration_package_dataset_v3(payload)  # type: ignore[arg-type]
