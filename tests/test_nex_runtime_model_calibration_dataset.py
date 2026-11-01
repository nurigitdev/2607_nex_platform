from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from nex_runtime import (
    DOMAIN_QUERY_QUOTAS,
    LANGUAGE_QUERY_QUOTAS,
    MODEL_CALIBRATION_DATASET_ID,
    MODEL_CALIBRATION_DATASET_SCHEMA_VERSION,
    PARTITION_QUERY_QUOTAS,
    ModelCalibrationDatasetError,
    admit_model_calibration_dataset_v2,
)


ROOT = Path(__file__).parents[1]
GRADES = (
    ("strong-positive", "STRONG_POSITIVE", True),
    ("acceptable-positive", "ACCEPTABLE_POSITIVE", True),
    ("hard-negative", "HARD_NEGATIVE", False),
    ("easy-negative", "EASY_NEGATIVE", False),
)


def _dataset() -> dict:
    partitions = [
        partition
        for partition, count in PARTITION_QUERY_QUOTAS.items()
        for _ in range(count)
    ]
    languages = [
        language
        for language, count in LANGUAGE_QUERY_QUOTAS.items()
        for _ in range(count)
    ]
    domains = [
        domain
        for domain, count in DOMAIN_QUERY_QUOTAS.items()
        for _ in range(count)
    ]
    cases = []
    for index, (partition, language, domain) in enumerate(
        zip(partitions, languages, domains, strict=True), start=1
    ):
        case_id = f"case-{index:02d}"
        cases.append(
            {
                "case_id": case_id,
                "partition": partition,
                "language_profile": language,
                "domain": domain,
                "query": f"Unique calibration query {index}",
                "documents": [
                    {
                        "document_id": document_id,
                        "relevance_grade": grade,
                        "expected_ready": expected_ready,
                        "text": f"Unique {grade} calibration document {index}",
                    }
                    for document_id, grade, expected_ready in GRADES
                ],
            }
        )
    return {
        "dataset_schema_version": MODEL_CALIBRATION_DATASET_SCHEMA_VERSION,
        "dataset_id": MODEL_CALIBRATION_DATASET_ID,
        "cases": cases,
    }


def test_admits_balanced_dataset_and_builds_redacted_manifest() -> None:
    payload = _dataset()
    admitted = admit_model_calibration_dataset_v2(payload)

    assert admitted.manifest["query_count"] == 30
    assert admitted.manifest["pair_count"] == 120
    assert admitted.manifest["positive_count"] == 60
    assert admitted.manifest["negative_count"] == 60
    assert len(admitted.manifest["dataset_sha256"]) == 64
    assert len(admitted.manifest["pair_ids"]) == 120
    assert payload["cases"][0]["query"] not in json.dumps(admitted.manifest)
    assert payload["cases"][0]["documents"][0]["text"] not in json.dumps(
        admitted.manifest
    )
    assert admitted.dataset is not payload

    reversed_payload = _dataset()
    reversed_payload["cases"].reverse()
    reversed_digest = admit_model_calibration_dataset_v2(reversed_payload).manifest[
        "dataset_sha256"
    ]
    assert reversed_digest == admitted.manifest["dataset_sha256"]


def test_contract_schema_accepts_v2_shape() -> None:
    schema = json.loads(
        (
            ROOT
            / "contracts/schemas/common/model_calibration_dataset.v2.schema.json"
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
        (lambda value: value["cases"].pop(), "exactly 30"),
        (
            lambda value: value["cases"][1].update(
                case_id=value["cases"][0]["case_id"]
            ),
            "duplicate case_id",
        ),
        (
            lambda value: value["cases"][1].update(
                query=value["cases"][0]["query"].upper()
            ),
            "duplicate query",
        ),
        (
            lambda value: value["cases"][1]["documents"][0].update(
                text=value["cases"][0]["documents"][0]["text"]
            ),
            "duplicate document text",
        ),
        (
            lambda value: value["cases"][0].update(partition="HOLDOUT"),
            "partition quota",
        ),
        (
            lambda value: value["cases"][0].update(language_profile="ENGLISH"),
            "language_profile quota",
        ),
        (
            lambda value: value["cases"][0].update(domain="FINANCE"),
            "domain quota",
        ),
    ],
)
def test_rejects_invalid_dataset_level_contract(mutation, detail: str) -> None:
    payload = _dataset()
    mutation(payload)
    with pytest.raises(ModelCalibrationDatasetError, match=detail):
        admit_model_calibration_dataset_v2(payload)


@pytest.mark.parametrize(
    "mutation, detail",
    [
        (lambda case: case.update(extra=True), "case fields"),
        (lambda case: case.update(case_id="Not Canonical"), "kebab-case"),
        (lambda case: case.update(query=" "), "non-empty"),
        (lambda case: case.update(query=[]), "non-empty"),
        (lambda case: case.update(partition="OTHER"), "partition"),
        (lambda case: case["documents"].pop(), "exactly four"),
        (lambda case: case.update(documents={}), "array"),
        (lambda case: case.update(documents="documents"), "array"),
        (
            lambda case: case["documents"].__setitem__(
                0, dict(case["documents"][2])
            ),
            "each relevance grade",
        ),
        (
            lambda case: case["documents"][0].update(expected_ready=False),
            "match relevance_grade",
        ),
        (
            lambda case: case["documents"][0].update(expected_ready="yes"),
            "boolean",
        ),
        (
            lambda case: case["documents"][0].update(document_id="positive"),
            "derived",
        ),
        (
            lambda case: case["documents"][0].update(extra=True),
            "document fields",
        ),
        (
            lambda case: case["documents"][0].update(text=""),
            "non-empty",
        ),
    ],
)
def test_rejects_invalid_case_and_document_contract(mutation, detail: str) -> None:
    payload = _dataset()
    mutation(payload["cases"][0])
    with pytest.raises(ModelCalibrationDatasetError, match=detail):
        admit_model_calibration_dataset_v2(payload)


@pytest.mark.parametrize("payload", [None, [], "dataset"])
def test_rejects_non_mapping_dataset(payload: object) -> None:
    with pytest.raises(ModelCalibrationDatasetError, match="object"):
        admit_model_calibration_dataset_v2(payload)  # type: ignore[arg-type]
