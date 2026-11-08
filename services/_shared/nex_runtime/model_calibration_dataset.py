from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
import re
from typing import Any

from .semantic_hashes import semantic_sha256_hash_ref, sha256_from_hash_ref


MODEL_CALIBRATION_DATASET_SCHEMA_VERSION = "model_calibration_dataset.v2"
MODEL_CALIBRATION_DATASET_ID = "s136-reranker-relevance-public-v2"

RELEVANCE_GRADE_EXPECTED_READY = {
    "STRONG_POSITIVE": True,
    "ACCEPTABLE_POSITIVE": True,
    "HARD_NEGATIVE": False,
    "EASY_NEGATIVE": False,
}
RELEVANCE_GRADE_DOCUMENT_IDS = {
    "STRONG_POSITIVE": "strong-positive",
    "ACCEPTABLE_POSITIVE": "acceptable-positive",
    "HARD_NEGATIVE": "hard-negative",
    "EASY_NEGATIVE": "easy-negative",
}
PARTITION_QUERY_QUOTAS = {"CALIBRATION": 20, "HOLDOUT": 10}
LANGUAGE_QUERY_QUOTAS = {
    "KOREAN": 18,
    "KOREAN_ENGLISH_MIXED": 6,
    "ENGLISH": 6,
}
DOMAIN_QUERY_QUOTAS = {
    "PROJECT": 6,
    "FINANCE": 8,
    "IDENTITY_AUTHORIZATION": 5,
    "GOVERNANCE_OPERATIONS": 5,
    "AI_RUNTIME": 6,
}

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class ModelCalibrationDatasetError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AdmittedModelCalibrationDataset:
    dataset: dict[str, Any]
    manifest: dict[str, Any]


def admit_model_calibration_dataset_v2(
    payload: Mapping[str, Any],
) -> AdmittedModelCalibrationDataset:
    source = _mapping(payload, "dataset")
    if source.get("dataset_schema_version") != (
        MODEL_CALIBRATION_DATASET_SCHEMA_VERSION
    ):
        raise _invalid("dataset_schema_version")
    if source.get("dataset_id") != MODEL_CALIBRATION_DATASET_ID:
        raise _invalid("dataset_id")
    if set(source) != {"dataset_schema_version", "dataset_id", "cases"}:
        raise _invalid("dataset fields")

    raw_cases = _sequence(source.get("cases"), "cases")
    expected_case_count = sum(PARTITION_QUERY_QUOTAS.values())
    if len(raw_cases) != expected_case_count:
        raise _invalid(f"cases must contain exactly {expected_case_count} entries")

    cases = [_normalize_case(item) for item in raw_cases]
    _require_unique((case["case_id"] for case in cases), "case_id")
    _require_unique((_text_key(case["query"]) for case in cases), "query")
    _require_unique(
        (
            _text_key(document["text"])
            for case in cases
            for document in case["documents"]
        ),
        "document text",
    )
    _require_quota(cases, "partition", PARTITION_QUERY_QUOTAS)
    _require_quota(cases, "language_profile", LANGUAGE_QUERY_QUOTAS)
    _require_quota(cases, "domain", DOMAIN_QUERY_QUOTAS)

    normalized = {
        "dataset_schema_version": MODEL_CALIBRATION_DATASET_SCHEMA_VERSION,
        "dataset_id": MODEL_CALIBRATION_DATASET_ID,
        "cases": sorted(cases, key=lambda item: item["case_id"]),
    }
    dataset_sha256 = sha256_from_hash_ref(semantic_sha256_hash_ref(normalized))
    pair_ids = [
        f"{case['case_id']}:{document['document_id']}"
        for case in normalized["cases"]
        for document in case["documents"]
    ]
    positive_count = sum(
        document["expected_ready"]
        for case in normalized["cases"]
        for document in case["documents"]
    )
    pair_count = len(pair_ids)

    manifest = {
        "dataset_schema_version": MODEL_CALIBRATION_DATASET_SCHEMA_VERSION,
        "dataset_id": MODEL_CALIBRATION_DATASET_ID,
        "dataset_sha256": dataset_sha256,
        "query_count": len(normalized["cases"]),
        "pair_count": pair_count,
        "positive_count": positive_count,
        "negative_count": pair_count - positive_count,
        "partition_query_counts": dict(PARTITION_QUERY_QUOTAS),
        "language_query_counts": dict(LANGUAGE_QUERY_QUOTAS),
        "domain_query_counts": dict(DOMAIN_QUERY_QUOTAS),
        "pair_ids": pair_ids,
    }
    return AdmittedModelCalibrationDataset(
        dataset=json.loads(json.dumps(normalized, ensure_ascii=False)),
        manifest=manifest,
    )


def _normalize_case(value: object) -> dict[str, Any]:
    item = _mapping(value, "case")
    required = {
        "case_id",
        "partition",
        "language_profile",
        "domain",
        "query",
        "documents",
    }
    if set(item) != required:
        raise _invalid("case fields")
    case_id = _identifier(item.get("case_id"), "case_id")
    partition = _enum(item.get("partition"), PARTITION_QUERY_QUOTAS, "partition")
    language_profile = _enum(
        item.get("language_profile"), LANGUAGE_QUERY_QUOTAS, "language_profile"
    )
    domain = _enum(item.get("domain"), DOMAIN_QUERY_QUOTAS, "domain")
    query = _required_string(item.get("query"), "query")
    raw_documents = _sequence(item.get("documents"), "documents")
    if len(raw_documents) != len(RELEVANCE_GRADE_EXPECTED_READY):
        raise _invalid("documents must contain exactly four entries")
    documents = [_normalize_document(document) for document in raw_documents]
    grades = {document["relevance_grade"] for document in documents}
    if grades != set(RELEVANCE_GRADE_EXPECTED_READY):
        raise _invalid("documents must contain each relevance grade exactly once")
    return {
        "case_id": case_id,
        "partition": partition,
        "language_profile": language_profile,
        "domain": domain,
        "query": query,
        "documents": sorted(
            documents,
            key=lambda document: tuple(RELEVANCE_GRADE_EXPECTED_READY).index(
                document["relevance_grade"]
            ),
        ),
    }


def _normalize_document(value: object) -> dict[str, Any]:
    item = _mapping(value, "document")
    required = {"document_id", "relevance_grade", "expected_ready", "text"}
    if set(item) != required:
        raise _invalid("document fields")
    grade = _enum(
        item.get("relevance_grade"),
        RELEVANCE_GRADE_EXPECTED_READY,
        "relevance_grade",
    )
    expected_ready = item.get("expected_ready")
    if type(expected_ready) is not bool:
        raise _invalid("expected_ready must be boolean")
    if expected_ready is not RELEVANCE_GRADE_EXPECTED_READY[grade]:
        raise _invalid("expected_ready must match relevance_grade")
    document_id = _identifier(item.get("document_id"), "document_id")
    if document_id != RELEVANCE_GRADE_DOCUMENT_IDS[grade]:
        raise _invalid("document_id must be derived from relevance_grade")
    return {
        "document_id": document_id,
        "relevance_grade": grade,
        "expected_ready": expected_ready,
        "text": _required_string(item.get("text"), "text"),
    }


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _invalid(f"{field} must be an array")
    return value


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string")
    return value.strip()


def _identifier(value: object, field: str) -> str:
    normalized = _required_string(value, field)
    if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise _invalid(f"{field} must be a lowercase kebab-case identifier")
    return normalized


def _enum(value: object, options: Mapping[str, Any], field: str) -> str:
    normalized = _required_string(value, field).upper()
    if normalized not in options:
        raise _invalid(field)
    return normalized


def _text_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _require_unique(values: Iterable[str], field: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise _invalid(f"duplicate {field}")


def _require_quota(
    cases: Sequence[Mapping[str, Any]],
    field: str,
    expected: Mapping[str, int],
) -> None:
    actual = Counter(case[field] for case in cases)
    if dict(actual) != dict(expected):
        raise _invalid(f"{field} quota")


def _invalid(field: str) -> ModelCalibrationDatasetError:
    return ModelCalibrationDatasetError(
        "model_calibration_dataset.invalid",
        f"Invalid model calibration dataset: {field}.",
    )
