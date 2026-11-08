from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

FRESH_CALIBRATION_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_fresh_calibration_design.v1"
)
FRESH_CALIBRATION_DATASET_SCHEMA_VERSION = (
    "cx_answer_support_fresh_calibration_dataset.v1"
)
FRESH_CALIBRATION_DATASET_ID = "s136-answer-support-fresh-calibration-v1"
FRESH_CALIBRATION_GENERATOR_ID = "cx-answer-support-policy-fact-matrix-v1"

DOMAINS = (
    "PROJECT",
    "FINANCE",
    "IDENTITY_AUTHORIZATION",
    "GOVERNANCE_OPERATIONS",
    "AI_RUNTIME",
)
LANGUAGE_COUNTS = {"KOREAN": 60, "KOREAN_ENGLISH_MIXED": 20, "ENGLISH": 20}
DOMAIN_COUNTS = {domain: 20 for domain in DOMAINS}
READY_ROLES = (
    "PRIMARY_ANSWER",
    "SUPPORTING_ANSWER",
    "HARD_NON_ANSWER",
    "EASY_NON_ANSWER",
)
LOW_ROLES = (
    "HARD_NON_ANSWER",
    "RELATED_NON_ANSWER",
    "CONTRADICTORY_NON_ANSWER",
    "EASY_NON_ANSWER",
)
ROLE_RELEVANCE = {
    "PRIMARY_ANSWER": True,
    "SUPPORTING_ANSWER": True,
    "HARD_NON_ANSWER": False,
    "RELATED_NON_ANSWER": False,
    "CONTRADICTORY_NON_ANSWER": False,
    "EASY_NON_ANSWER": False,
}

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "dataset",
    "package_semantics",
    "authoring",
    "safety",
}
_DATASET_FIELDS = {
    "dataset_schema_version",
    "dataset_id",
    "generator_id",
    "source_binding",
    "cases",
}


def validate_fresh_calibration_design(design: Mapping[str, Any]) -> dict[str, Any]:
    _exact_mapping(design, _DESIGN_FIELDS, "fresh calibration design")
    if (
        design.get("design_schema_version")
        != FRESH_CALIBRATION_DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_CALIBRATION_ONLY"
    ):
        raise ValueError("fresh calibration design identity is invalid")
    _required_text(design.get("design_id"), "design_id")
    binding = _mapping(design.get("source_binding"), "source binding")
    _exact_mapping(
        binding,
        {"p_l_design_hash", "p_l_freeze_hash", "canonical_profile_hash"},
        "fresh calibration source binding",
    )
    normalized_binding = {
        key: validate_hash_ref(binding.get(key))
        for key in ("p_l_design_hash", "p_l_freeze_hash", "canonical_profile_hash")
    }
    dataset = _mapping(design.get("dataset"), "fresh calibration dataset design")
    if dict(dataset) != {
        "candidate_count": 800,
        "candidates_per_package": 4,
        "dataset_id": FRESH_CALIBRATION_DATASET_ID,
        "domain_scenario_counts": DOMAIN_COUNTS,
        "language_scenario_counts": LANGUAGE_COUNTS,
        "package_count": 200,
        "packages_per_scenario": 2,
        "partition": "CALIBRATION",
        "scenario_count": 100,
    }:
        raise ValueError("fresh calibration dataset design is invalid")
    semantics = _mapping(design.get("package_semantics"), "package semantics")
    if dict(semantics) != {
        "low_confidence_roles": list(LOW_ROLES),
        "ready_roles": list(READY_ROLES),
    }:
        raise ValueError("fresh calibration package semantics are invalid")
    authoring = _mapping(design.get("authoring"), "fresh calibration authoring")
    if dict(authoring) != {
        "generator_id": FRESH_CALIBRATION_GENERATOR_ID,
        "mode": "CONTROLLED_SYNTHETIC_POLICY_FACT_MATRIX",
        "review_boundary": (
            "CONTRACT_AND_GENERATOR_REVIEWED_HOLDOUT_REMAINS_AUTHORITY"
        ),
        "source_model_scores_used": False,
    }:
        raise ValueError("fresh calibration authoring is invalid")
    safety = _mapping(design.get("safety"), "fresh calibration safety")
    if dict(safety) != {
        "existing_dataset_mutation_permitted": False,
        "holdout_content_permitted": False,
        "provider_execution_permitted": False,
        "runtime_activation_permitted": False,
        "threshold_selection_permitted": False,
    }:
        raise ValueError("fresh calibration safety is invalid")
    normalized = dict(design)
    normalized["source_binding"] = normalized_binding
    normalized["design_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def build_fresh_calibration_dataset(
    design: Mapping[str, Any],
    *,
    p_l_freeze: Mapping[str, Any],
) -> dict[str, Any]:
    """Materialize a deterministic CALIBRATION-only scenario matrix."""
    normalized = validate_fresh_calibration_design(design)
    _validate_p_l_freeze(p_l_freeze, normalized["source_binding"])
    cases = []
    for domain in DOMAINS:
        for index in range(1, 21):
            language = _language_for_index(index)
            scenario_id = f"fresh-{domain.lower().replace('_', '-')}-{index:02d}"
            cases.extend(
                _scenario_pair(
                    scenario_id=scenario_id,
                    domain=domain,
                    language=language,
                    index=index,
                )
            )
    return {
        "dataset_schema_version": FRESH_CALIBRATION_DATASET_SCHEMA_VERSION,
        "dataset_id": FRESH_CALIBRATION_DATASET_ID,
        "generator_id": FRESH_CALIBRATION_GENERATOR_ID,
        "source_binding": {
            **normalized["source_binding"],
            "design_hash": normalized["design_hash"],
        },
        "cases": sorted(cases, key=lambda row: row["case_id"]),
    }


def admit_fresh_calibration_dataset(
    dataset: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    p_l_freeze: Mapping[str, Any],
    predecessor_cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate exact materialization, uniqueness, freshness, and immutable hash."""
    normalized_design = validate_fresh_calibration_design(design)
    expected = build_fresh_calibration_dataset(design, p_l_freeze=p_l_freeze)
    source = dict(_exact_mapping(dataset, _DATASET_FIELDS, "fresh dataset"))
    cases = source["cases"]
    if len(cases) != 200:
        raise ValueError("fresh calibration package count is invalid")
    scenario_counts = Counter(str(row["scenario_id"]) for row in cases)
    if len(scenario_counts) != 100 or set(scenario_counts.values()) != {2}:
        raise ValueError("fresh calibration scenario pairing is invalid")
    language_counts = _scenario_counts(cases, "language_profile")
    domain_counts = _scenario_counts(cases, "domain")
    if language_counts != LANGUAGE_COUNTS or domain_counts != DOMAIN_COUNTS:
        raise ValueError("fresh calibration stratification is invalid")
    if any(row.get("partition") != "CALIBRATION" for row in cases):
        raise ValueError("fresh calibration partition is invalid")
    _require_unique((str(row["case_id"]) for row in cases), "case_id")
    _require_unique((str(row["query"]).casefold() for row in cases), "query")
    texts = [
        str(candidate["text"]).casefold()
        for row in cases
        for candidate in row["candidates"]
    ]
    _require_unique(texts, "candidate text")
    predecessor_values = {
        str(row.get("query", "")).casefold() for row in predecessor_cases
    }
    predecessor_values.update(
        str(candidate.get("text", "")).casefold()
        for row in predecessor_cases
        for candidate in row.get("candidates", [])
        if isinstance(candidate, Mapping)
    )
    if predecessor_values & ({str(row["query"]).casefold() for row in cases} | set(texts)):
        raise ValueError("fresh calibration content overlaps predecessor")
    if source != expected:
        raise ValueError("fresh calibration materialization is invalid")
    dataset_hash = semantic_sha256_hash_ref(source)
    return {
        "status": "ADMITTED_FRESH_CALIBRATION_ONLY",
        "dataset_id": FRESH_CALIBRATION_DATASET_ID,
        "dataset_hash": dataset_hash,
        "design_hash": normalized_design["design_hash"],
        "scenario_count": 100,
        "package_count": 200,
        "candidate_count": 800,
        "language_scenario_counts": language_counts,
        "domain_scenario_counts": domain_counts,
        "holdout_case_count": 0,
        "provider_calls": 0,
        "runtime_activation_permitted": False,
    }


def _validate_p_l_freeze(
    freeze: Mapping[str, Any], binding: Mapping[str, Any]
) -> None:
    value = dict(_mapping(freeze, "P-L freeze"))
    freeze_hash = validate_hash_ref(value.pop("freeze_hash", None))
    profile = _mapping(value.get("canonical_profile"), "P-L canonical profile")
    if (
        semantic_sha256_hash_ref(value) != freeze_hash
        or freeze_hash != binding["p_l_freeze_hash"]
        or value.get("design_hash") != binding["p_l_design_hash"]
        or profile.get("profile_hash") != binding["canonical_profile_hash"]
        or profile.get("threshold") is not None
        or value.get("holdout_access_permitted") is not False
        or value.get("runtime_activation_permitted") is not False
    ):
        raise ValueError("P-L freeze binding is invalid")


def _language_for_index(index: int) -> str:
    if index <= 12:
        return "KOREAN"
    if index <= 16:
        return "KOREAN_ENGLISH_MIXED"
    return "ENGLISH"


def _scenario_pair(
    *, scenario_id: str, domain: str, language: str, index: int
) -> list[dict[str, Any]]:
    code = scenario_id.upper()
    subject, value = _policy_fact(domain, language, index)
    text = _localized_text(language, code=code, subject=subject, value=value, index=index)
    common = {
        "scenario_id": scenario_id,
        "partition": "CALIBRATION",
        "language_profile": language,
        "domain": domain,
    }
    return [
        {
            **common,
            "case_id": f"{scenario_id}-ready",
            "expected_ready": True,
            "query": text["ready_query"],
            "candidates": _candidates(text, READY_ROLES, prefix="ready"),
        },
        {
            **common,
            "case_id": f"{scenario_id}-low-confidence",
            "expected_ready": False,
            "query": text["low_query"],
            "candidates": _candidates(text, LOW_ROLES, prefix="low"),
        },
    ]


def _policy_fact(domain: str, language: str, index: int) -> tuple[str, str]:
    subjects = {
        "PROJECT": ("프로젝트 상태 검토 주기", "project status review interval"),
        "FINANCE": ("전표 증빙 보존 기간", "voucher evidence retention period"),
        "IDENTITY_AUTHORIZATION": ("접근 권한 재검토 주기", "access review interval"),
        "GOVERNANCE_OPERATIONS": ("사고 접수 확인 기한", "incident acknowledgement window"),
        "AI_RUNTIME": ("모델 준비상태 점검 주기", "model readiness probe interval"),
    }
    korean, english = subjects[domain]
    if language == "KOREAN":
        return korean, f"{index + 1}일"
    if language == "KOREAN_ENGLISH_MIXED":
        return f"{korean} ({english})", f"{index + 1} days"
    return english, f"{index + 1} days"


def _localized_text(
    language: str, *, code: str, subject: str, value: str, index: int
) -> dict[str, str]:
    if language == "ENGLISH":
        return {
            "ready_query": f"What is the approved {subject} in policy record {code}?",
            "low_query": f"How long is the automatic exception extension for {subject} in record {code}?",
            "ready_primary": f"Policy record {code} sets the approved {subject} to {value}.",
            "ready_support": f"The control summary for {code} confirms {value} as the current {subject}.",
            "ready_hard": f"Record {code} requires periodic oversight of {subject}, but this note does not state the approved value.",
            "ready_easy": f"Archive label {code} is printed with ink batch {index:02d} and contains no policy timing rule.",
            "low_hard": f"Record {code} says exceptions require manual approval and defines no automatic extension duration.",
            "low_related": f"The baseline {subject} for {code} is {value}, which does not define an exception extension.",
            "low_contradiction": f"An unapproved memo claims record {code} automatically extends every exception by {index + 24} hours.",
            "low_easy": f"Office room {index:02d} has a wall clock unrelated to record {code} or exception handling.",
        }
    return {
        "ready_query": f"정책 기록 {code}에서 승인된 {subject}은 무엇입니까?",
        "low_query": f"정책 기록 {code}에서 {subject} 예외의 자동 연장 시간은 얼마입니까?",
        "ready_primary": f"정책 기록 {code}은 승인된 {subject}을 {value}로 정합니다.",
        "ready_support": f"{code} 통제 요약은 현재 {subject}이 {value}임을 확인합니다.",
        "ready_hard": f"{code}는 {subject}의 주기적 검토를 요구하지만 이 메모에는 승인값이 없습니다.",
        "ready_easy": f"보관 라벨 {code}는 잉크 배치 {index:02d}로 인쇄되었으며 정책 시간 규칙과 무관합니다.",
        "low_hard": f"{code}는 예외에 수동 승인이 필요하다고 명시하며 자동 연장 시간은 정의하지 않습니다.",
        "low_related": f"{code}의 기본 {subject}은 {value}이지만 예외 자동 연장 시간을 뜻하지 않습니다.",
        "low_contradiction": f"승인되지 않은 메모는 {code}의 모든 예외가 {index + 24}시간 자동 연장된다고 주장합니다.",
        "low_easy": f"회의실 {index:02d}의 벽시계는 {code} 또는 예외 처리와 관련이 없습니다.",
    }


def _candidates(
    text: Mapping[str, str], roles: Sequence[str], *, prefix: str
) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": role.casefold().replace("_", "-"),
            "evidence_role": role,
            "expected_relevant": ROLE_RELEVANCE[role],
            "text": text[f"{prefix}_{_role_text_key(role)}"],
        }
        for role in roles
    ]


def _role_text_key(role: str) -> str:
    return {
        "PRIMARY_ANSWER": "primary",
        "SUPPORTING_ANSWER": "support",
        "HARD_NON_ANSWER": "hard",
        "RELATED_NON_ANSWER": "related",
        "CONTRADICTORY_NON_ANSWER": "contradiction",
        "EASY_NON_ANSWER": "easy",
    }[role]


def _scenario_counts(cases: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    values: dict[str, str] = {}
    for row in cases:
        scenario_id = str(row["scenario_id"])
        value = str(row[field])
        if scenario_id in values and values[scenario_id] != value:
            raise ValueError("fresh calibration scenario metadata drifted")
        values[scenario_id] = value
    return dict(Counter(values.values()))


def _require_unique(values: Iterable[str], name: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"fresh calibration {name} is duplicated")


def _exact_mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    item = _mapping(value, name)
    if set(item) != fields:
        raise ValueError(f"{name} fields are invalid")
    return item


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()
