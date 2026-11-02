from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .semantic_hashes import semantic_sha256_hash_ref, sha256_from_hash_ref

MODEL_CALIBRATION_PACKAGE_DATASET_SCHEMA_VERSION = "model_calibration_dataset.v3"
MODEL_CALIBRATION_PACKAGE_DATASET_ID = "s136-retrieval-package-confidence-public-v3"

PACKAGE_PARTITION_SCENARIO_QUOTAS = {"CALIBRATION": 20, "HOLDOUT": 10}
PACKAGE_LANGUAGE_SCENARIO_QUOTAS = {
    "KOREAN": 18,
    "KOREAN_ENGLISH_MIXED": 6,
    "ENGLISH": 6,
}
PACKAGE_DOMAIN_SCENARIO_QUOTAS = {
    "PROJECT": 6,
    "FINANCE": 8,
    "IDENTITY_AUTHORIZATION": 5,
    "GOVERNANCE_OPERATIONS": 5,
    "AI_RUNTIME": 6,
}

CANDIDATE_ROLE_EXPECTED_RELEVANT = {
    "PRIMARY_ANSWER": True,
    "SUPPORTING_ANSWER": True,
    "HARD_NON_ANSWER": False,
    "RELATED_NON_ANSWER": False,
    "CONTRADICTORY_NON_ANSWER": False,
    "EASY_NON_ANSWER": False,
}
CANDIDATE_ROLE_IDS = {
    role: role.casefold().replace("_", "-") for role in CANDIDATE_ROLE_EXPECTED_RELEVANT
}
READY_CANDIDATE_ROLES = frozenset(
    {
        "PRIMARY_ANSWER",
        "SUPPORTING_ANSWER",
        "HARD_NON_ANSWER",
        "EASY_NON_ANSWER",
    }
)
LOW_CONFIDENCE_CANDIDATE_ROLES = frozenset(
    {
        "HARD_NON_ANSWER",
        "RELATED_NON_ANSWER",
        "CONTRADICTORY_NON_ANSWER",
        "EASY_NON_ANSWER",
    }
)

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class ModelCalibrationPackageDatasetError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AdmittedModelCalibrationPackageDataset:
    dataset: dict[str, Any]
    manifest: dict[str, Any]


def admit_model_calibration_package_dataset_v3(
    payload: Mapping[str, Any],
) -> AdmittedModelCalibrationPackageDataset:
    source = _mapping(payload, "dataset")
    if source.get("dataset_schema_version") != (
        MODEL_CALIBRATION_PACKAGE_DATASET_SCHEMA_VERSION
    ):
        raise _invalid("dataset_schema_version")
    if source.get("dataset_id") != MODEL_CALIBRATION_PACKAGE_DATASET_ID:
        raise _invalid("dataset_id")
    if set(source) != {"dataset_schema_version", "dataset_id", "cases"}:
        raise _invalid("dataset fields")

    raw_cases = _sequence(source.get("cases"), "cases")
    expected_case_count = sum(PACKAGE_PARTITION_SCENARIO_QUOTAS.values()) * 2
    if len(raw_cases) != expected_case_count:
        raise _invalid(f"cases must contain exactly {expected_case_count} entries")

    cases = [_normalize_case(item) for item in raw_cases]
    _require_unique((case["case_id"] for case in cases), "case_id")
    _require_unique((_text_key(case["query"]) for case in cases), "query")
    _require_unique(
        (
            _text_key(candidate["text"])
            for case in cases
            for candidate in case["candidates"]
        ),
        "candidate text",
    )
    scenarios = _scenario_groups(cases)
    _require_scenario_quota(
        scenarios,
        "partition",
        PACKAGE_PARTITION_SCENARIO_QUOTAS,
    )
    _require_scenario_quota(
        scenarios,
        "language_profile",
        PACKAGE_LANGUAGE_SCENARIO_QUOTAS,
    )
    _require_scenario_quota(
        scenarios,
        "domain",
        PACKAGE_DOMAIN_SCENARIO_QUOTAS,
    )

    normalized = {
        "dataset_schema_version": MODEL_CALIBRATION_PACKAGE_DATASET_SCHEMA_VERSION,
        "dataset_id": MODEL_CALIBRATION_PACKAGE_DATASET_ID,
        "cases": sorted(cases, key=lambda item: item["case_id"]),
    }
    dataset_sha256 = sha256_from_hash_ref(semantic_sha256_hash_ref(normalized))
    package_ids = [case["case_id"] for case in normalized["cases"]]
    candidate_ids = [
        f"{case['case_id']}:{candidate['candidate_id']}"
        for case in normalized["cases"]
        for candidate in case["candidates"]
    ]
    partition_package_counts = Counter(
        case["partition"] for case in normalized["cases"]
    )
    partition_label_counts = {
        partition: {
            "READY": sum(
                case["partition"] == partition and case["expected_ready"]
                for case in normalized["cases"]
            ),
            "LOW_CONFIDENCE": sum(
                case["partition"] == partition and not case["expected_ready"]
                for case in normalized["cases"]
            ),
        }
        for partition in PACKAGE_PARTITION_SCENARIO_QUOTAS
    }
    manifest = {
        "dataset_schema_version": MODEL_CALIBRATION_PACKAGE_DATASET_SCHEMA_VERSION,
        "dataset_id": MODEL_CALIBRATION_PACKAGE_DATASET_ID,
        "dataset_sha256": dataset_sha256,
        "scenario_count": len(scenarios),
        "package_count": len(package_ids),
        "candidate_count": len(candidate_ids),
        "ready_package_count": sum(
            case["expected_ready"] for case in normalized["cases"]
        ),
        "low_confidence_package_count": sum(
            not case["expected_ready"] for case in normalized["cases"]
        ),
        "partition_scenario_counts": dict(PACKAGE_PARTITION_SCENARIO_QUOTAS),
        "partition_package_counts": dict(partition_package_counts),
        "partition_label_counts": partition_label_counts,
        "language_scenario_counts": dict(PACKAGE_LANGUAGE_SCENARIO_QUOTAS),
        "domain_scenario_counts": dict(PACKAGE_DOMAIN_SCENARIO_QUOTAS),
        "package_ids": package_ids,
        "candidate_ids": candidate_ids,
    }
    return AdmittedModelCalibrationPackageDataset(
        dataset=json.loads(json.dumps(normalized, ensure_ascii=False)),
        manifest=manifest,
    )


def _normalize_case(value: object) -> dict[str, Any]:
    item = _mapping(value, "case")
    required = {
        "case_id",
        "scenario_id",
        "partition",
        "language_profile",
        "domain",
        "expected_ready",
        "query",
        "candidates",
    }
    if set(item) != required:
        raise _invalid("case fields")
    scenario_id = _identifier(item.get("scenario_id"), "scenario_id")
    expected_ready = item.get("expected_ready")
    if type(expected_ready) is not bool:
        raise _invalid("expected_ready must be boolean")
    expected_case_id = (
        f"{scenario_id}-ready" if expected_ready else f"{scenario_id}-low-confidence"
    )
    if _identifier(item.get("case_id"), "case_id") != expected_case_id:
        raise _invalid("case_id must be derived from scenario and label")
    raw_candidates = _sequence(item.get("candidates"), "candidates")
    if len(raw_candidates) != 4:
        raise _invalid("candidates must contain exactly four entries")
    candidates = [_normalize_candidate(candidate) for candidate in raw_candidates]
    roles = {candidate["evidence_role"] for candidate in candidates}
    expected_roles = (
        READY_CANDIDATE_ROLES if expected_ready else LOW_CONFIDENCE_CANDIDATE_ROLES
    )
    if roles != expected_roles:
        raise _invalid("candidate roles must match package label")
    return {
        "case_id": expected_case_id,
        "scenario_id": scenario_id,
        "partition": _enum(
            item.get("partition"),
            PACKAGE_PARTITION_SCENARIO_QUOTAS,
            "partition",
        ),
        "language_profile": _enum(
            item.get("language_profile"),
            PACKAGE_LANGUAGE_SCENARIO_QUOTAS,
            "language_profile",
        ),
        "domain": _enum(item.get("domain"), PACKAGE_DOMAIN_SCENARIO_QUOTAS, "domain"),
        "expected_ready": expected_ready,
        "query": _required_string(item.get("query"), "query"),
        "candidates": sorted(
            candidates,
            key=lambda candidate: candidate["candidate_id"],
        ),
    }


def _normalize_candidate(value: object) -> dict[str, Any]:
    item = _mapping(value, "candidate")
    required = {"candidate_id", "evidence_role", "expected_relevant", "text"}
    if set(item) != required:
        raise _invalid("candidate fields")
    role = _enum(
        item.get("evidence_role"),
        CANDIDATE_ROLE_EXPECTED_RELEVANT,
        "evidence_role",
    )
    expected_relevant = item.get("expected_relevant")
    if type(expected_relevant) is not bool:
        raise _invalid("expected_relevant must be boolean")
    if expected_relevant is not CANDIDATE_ROLE_EXPECTED_RELEVANT[role]:
        raise _invalid("expected_relevant must match evidence_role")
    if (
        _identifier(item.get("candidate_id"), "candidate_id")
        != (CANDIDATE_ROLE_IDS[role])
    ):
        raise _invalid("candidate_id must be derived from evidence_role")
    return {
        "candidate_id": CANDIDATE_ROLE_IDS[role],
        "evidence_role": role,
        "expected_relevant": expected_relevant,
        "text": _required_string(item.get("text"), "text"),
    }


def _scenario_groups(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        grouped.setdefault(str(case["scenario_id"]), []).append(case)
    expected_scenario_count = sum(PACKAGE_PARTITION_SCENARIO_QUOTAS.values())
    if len(grouped) != expected_scenario_count:
        raise _invalid(f"scenario count must be {expected_scenario_count}")
    normalized: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for scenario_id, pair in grouped.items():
        if len(pair) != 2 or {case["expected_ready"] for case in pair} != {
            False,
            True,
        }:
            raise _invalid("each scenario requires READY and LOW_CONFIDENCE cases")
        if any(
            len({case[field] for case in pair}) != 1
            for field in ("partition", "language_profile", "domain")
        ):
            raise _invalid("scenario pair metadata must match")
        ordered = sorted(pair, key=lambda case: not case["expected_ready"])
        normalized[scenario_id] = (ordered[0], ordered[1])
    return normalized


def _require_scenario_quota(
    scenarios: Mapping[str, Sequence[Mapping[str, Any]]],
    field: str,
    expected: Mapping[str, int],
) -> None:
    actual = Counter(pair[0][field] for pair in scenarios.values())
    if dict(actual) != dict(expected):
        raise _invalid(f"{field} scenario quota")


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


def _invalid(field: str) -> ModelCalibrationPackageDatasetError:
    return ModelCalibrationPackageDatasetError(
        "model_calibration_package_dataset.invalid",
        f"Invalid model calibration package dataset: {field}.",
    )
