from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from nex_runtime.semantic_hashes import (
    semantic_sha256_hash_ref,
    sha256_text,
    validate_hash_ref,
    validate_sha256_digest,
)

ANSWER_SUPPORT_DESIGN_SCHEMA_VERSION = "cx_answer_support_signal_design.v1"
ANSWER_SUPPORT_REQUEST_SCHEMA_VERSION = "cx_answer_support_signal_request.v1"
ANSWER_SUPPORT_RESPONSE_SCHEMA_VERSION = "cx_answer_support_signal_response.v1"
ANSWER_SUPPORT_EVIDENCE_SCHEMA_VERSION = "cx_answer_support_signal_evidence.v1"
ANSWER_SUPPORT_FEATURE_SCHEMA_VERSION = "cx_answer_support_package_features.v1"
ANSWER_SUPPORT_POLICY_ID = "cx_provider_neutral_answer_support_signal_v1"
ANSWER_SUPPORT_SCORE_SEMANTICS = "BOUNDED_ORDINAL_NOT_CALIBRATED_PROBABILITY"
ANSWER_SUPPORT_CLASSES = (
    "DIRECT_ANSWER",
    "SUPPORTING_EVIDENCE",
    "TOPICAL_NON_ANSWER",
    "CONTRADICTORY_EVIDENCE",
    "INSUFFICIENT_CONTEXT",
)
PROVIDER_BINDING_FIELDS = (
    "provider_alias",
    "provider_type",
    "model_revision",
    "deployment_id",
    "request_profile_id",
    "score_semantics_id",
)
PACKAGE_FEATURE_FIELDS = (
    "direct_or_support_fraction",
    "second_answer_support_score",
    "top_two_answer_support_mean",
    "maximum_contradiction_score",
    "mean_contradiction_score",
    "support_contradiction_margin",
)
MINIMUM_CANDIDATE_COUNT = 1
MAXIMUM_CANDIDATE_COUNT = 20
MAXIMUM_QUERY_CHARS = 16_000
MAXIMUM_CANDIDATE_CHARS = 64_000

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "policy_id",
    "status",
    "source_audit",
    "classes",
    "score_fields",
    "score_semantics",
    "provider_binding_fields",
    "candidate_count",
    "raw_text_transport",
    "package_feature_fields",
    "safety",
}
_REQUEST_FIELDS = {
    "request_schema_version",
    "request_id",
    "policy_id",
    "design_hash",
    "query",
    "candidates",
    "admission",
    "response_contract",
    "request_hash",
}
_RESPONSE_FIELDS = {
    "response_schema_version",
    "request_id",
    "provider_binding",
    "items",
}
_RESPONSE_ITEM_FIELDS = {
    "candidate_id",
    "classification",
    "answer_support_score",
    "contradiction_score",
}
_EVIDENCE_FIELDS = {
    "evidence_schema_version",
    "policy_id",
    "status",
    "design_hash",
    "request_id",
    "request_hash",
    "query_sha256",
    "provider_binding",
    "score_semantics",
    "candidate_evidence",
    "privacy",
    "safety",
    "evidence_hash",
}


class AnswerSupportSignalProvider(Protocol):
    """Provider-neutral boundary; concrete provider admission is a later Slice."""

    def evaluate(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


def validate_answer_support_signal_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and hash the frozen contract-only design."""
    _exact_mapping(design, _DESIGN_FIELDS, "answer support design")
    if (
        design.get("design_schema_version") != ANSWER_SUPPORT_DESIGN_SCHEMA_VERSION
        or design.get("policy_id") != ANSWER_SUPPORT_POLICY_ID
        or design.get("status") != "FROZEN_CONTRACT_ONLY"
    ):
        raise ValueError("answer support design identity is invalid")
    _required_text(design.get("design_id"), "design_id")
    _required_text(design.get("source_audit"), "source_audit")
    if design.get("classes") != list(ANSWER_SUPPORT_CLASSES):
        raise ValueError("answer support design classes are invalid")
    if design.get("score_fields") != [
        "answer_support_score",
        "contradiction_score",
    ]:
        raise ValueError("answer support design score fields are invalid")
    if design.get("score_semantics") != ANSWER_SUPPORT_SCORE_SEMANTICS:
        raise ValueError("answer support design score semantics are invalid")
    if design.get("provider_binding_fields") != list(PROVIDER_BINDING_FIELDS):
        raise ValueError("answer support provider binding fields are invalid")
    if design.get("candidate_count") != {
        "minimum": MINIMUM_CANDIDATE_COUNT,
        "maximum": MAXIMUM_CANDIDATE_COUNT,
    }:
        raise ValueError("answer support candidate count is invalid")
    if design.get("raw_text_transport") != "EPHEMERAL_PRIVATE_NOT_PERSISTED":
        raise ValueError("answer support raw text boundary is invalid")
    if design.get("package_feature_fields") != list(PACKAGE_FEATURE_FIELDS):
        raise ValueError("answer support package feature fields are invalid")
    safety = _mapping(design.get("safety"), "answer support design safety")
    expected_safety = {
        "candidate_truth_runtime_input_permitted": False,
        "permission_signals_as_features_permitted": False,
        "ownership_signals_as_features_permitted": False,
        "provider_selection_permitted": False,
        "holdout_access_permitted": False,
        "profile_selection_permitted": False,
        "threshold_selection_permitted": False,
        "runtime_activation_permitted": False,
    }
    if dict(safety) != expected_safety:
        raise ValueError("answer support design safety is invalid")
    normalized = dict(design)
    normalized["design_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def build_answer_support_request(
    *,
    request_id: str,
    query_text: str,
    candidates: Sequence[Mapping[str, Any]],
    design: Mapping[str, Any],
    permission_filtered: bool,
    owner_scope_enforced: bool,
) -> dict[str, Any]:
    """Build a private ephemeral request after authorization filtering."""
    normalized_design = validate_answer_support_signal_design(design)
    normalized_request_id = _required_text(request_id, "request_id")
    query = _bounded_text(query_text, "query_text", MAXIMUM_QUERY_CHARS)
    rows = _request_candidates(candidates, include_hash=False)
    if permission_filtered is not True or owner_scope_enforced is not True:
        raise ValueError("answer support request authorization admission failed")
    request: dict[str, Any] = {
        "request_schema_version": ANSWER_SUPPORT_REQUEST_SCHEMA_VERSION,
        "request_id": normalized_request_id,
        "policy_id": ANSWER_SUPPORT_POLICY_ID,
        "design_hash": normalized_design["design_hash"],
        "query": {"text": query, "sha256": sha256_text(query)},
        "candidates": rows,
        "admission": {
            "permission_filtered": True,
            "owner_scope_enforced": True,
            "candidate_truth_included": False,
        },
        "response_contract": {
            "response_schema_version": ANSWER_SUPPORT_RESPONSE_SCHEMA_VERSION,
            "classes": list(ANSWER_SUPPORT_CLASSES),
            "score_semantics": ANSWER_SUPPORT_SCORE_SEMANTICS,
            "provider_binding_fields": list(PROVIDER_BINDING_FIELDS),
            "free_form_rationale_permitted": False,
        },
    }
    request["request_hash"] = semantic_sha256_hash_ref(request)
    return request


def normalize_answer_support_response(
    *,
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    expected_provider_binding: Mapping[str, Any],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize provider output into text-free, integrity-bound evidence."""
    normalized_design = validate_answer_support_signal_design(design)
    normalized_request = _verified_request(request, normalized_design["design_hash"])
    _exact_mapping(response, _RESPONSE_FIELDS, "answer support response")
    if response.get("response_schema_version") != ANSWER_SUPPORT_RESPONSE_SCHEMA_VERSION:
        raise ValueError("answer support response identity is invalid")
    if response.get("request_id") != normalized_request["request_id"]:
        raise ValueError("answer support response request binding is invalid")
    binding = _provider_binding(expected_provider_binding)
    if _provider_binding(response.get("provider_binding")) != binding:
        raise ValueError("answer support response provider binding is invalid")
    items = _response_items(
        response.get("items"),
        expected_ids={row["candidate_id"] for row in normalized_request["candidates"]},
    )
    candidate_hashes = {
        row["candidate_id"]: row["text_sha256"]
        for row in normalized_request["candidates"]
    }
    evidence: dict[str, Any] = {
        "evidence_schema_version": ANSWER_SUPPORT_EVIDENCE_SCHEMA_VERSION,
        "policy_id": ANSWER_SUPPORT_POLICY_ID,
        "status": "CONTRACT_EVIDENCE_NORMALIZED",
        "design_hash": normalized_design["design_hash"],
        "request_id": normalized_request["request_id"],
        "request_hash": normalized_request["request_hash"],
        "query_sha256": normalized_request["query"]["sha256"],
        "provider_binding": binding,
        "score_semantics": ANSWER_SUPPORT_SCORE_SEMANTICS,
        "candidate_evidence": [
            {
                **item,
                "candidate_text_sha256": candidate_hashes[item["candidate_id"]],
            }
            for item in items
        ],
        "privacy": {
            "raw_query_persisted": False,
            "raw_candidate_text_persisted": False,
            "free_form_rationale_persisted": False,
        },
        "safety": {
            "candidate_truth_runtime_input_permitted": False,
            "holdout_access_permitted": False,
            "threshold_selected": False,
            "ready_decision_emitted": False,
            "runtime_activation_permitted": False,
        },
    }
    evidence["evidence_hash"] = semantic_sha256_hash_ref(evidence)
    return evidence


def build_answer_support_package_features(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Project diagnostic package features without a READY threshold or decision."""
    normalized = _verified_evidence(evidence)
    items = normalized["candidate_evidence"]
    support_scores = sorted(
        (float(row["answer_support_score"]) for row in items), reverse=True
    )
    contradiction_scores = [float(row["contradiction_score"]) for row in items]
    class_counts = Counter(str(row["classification"]) for row in items)
    candidate_count = len(items)
    second_support = support_scores[1] if candidate_count > 1 else support_scores[0]
    top_two = support_scores[:2]
    support_or_direct = class_counts["DIRECT_ANSWER"] + class_counts[
        "SUPPORTING_EVIDENCE"
    ]
    features = {
        "direct_or_support_fraction": support_or_direct / candidate_count,
        "second_answer_support_score": second_support,
        "top_two_answer_support_mean": sum(top_two) / len(top_two),
        "maximum_contradiction_score": max(contradiction_scores),
        "mean_contradiction_score": sum(contradiction_scores) / candidate_count,
        "support_contradiction_margin": (
            sum(support_scores) / candidate_count
            - sum(contradiction_scores) / candidate_count
        ),
    }
    result: dict[str, Any] = {
        "feature_schema_version": ANSWER_SUPPORT_FEATURE_SCHEMA_VERSION,
        "policy_id": ANSWER_SUPPORT_POLICY_ID,
        "status": "CONTRACT_FEATURES_PROJECTED",
        "source_evidence_hash": normalized["evidence_hash"],
        "provider_binding": normalized["provider_binding"],
        "candidate_count": candidate_count,
        "classification_counts": {
            value: class_counts[value] for value in ANSWER_SUPPORT_CLASSES
        },
        "features": {key: round(value, 12) for key, value in features.items()},
        "semantics": {
            "score_semantics": ANSWER_SUPPORT_SCORE_SEMANTICS,
            "features_are_calibrated_probabilities": False,
            "ready_threshold": None,
            "ready_decision": None,
        },
        "safety": {
            "diagnostic_only": True,
            "holdout_access_permitted": False,
            "profile_selection_permitted": False,
            "threshold_selection_permitted": False,
            "runtime_activation_permitted": False,
        },
    }
    result["feature_hash"] = semantic_sha256_hash_ref(result)
    return result


def _request_candidates(
    value: Sequence[Mapping[str, Any]], *, include_hash: bool
) -> list[dict[str, str]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("answer support candidates are invalid")
    if not MINIMUM_CANDIDATE_COUNT <= len(value) <= MAXIMUM_CANDIDATE_COUNT:
        raise ValueError("answer support candidate count is invalid")
    rows: list[dict[str, str]] = []
    for item in value:
        fields = {"candidate_id", "text", "text_sha256"} if include_hash else {
            "candidate_id",
            "text",
        }
        _exact_mapping(item, fields, "answer support candidate")
        candidate_id = _required_text(item.get("candidate_id"), "candidate_id")
        text = _bounded_text(item.get("text"), "candidate_text", MAXIMUM_CANDIDATE_CHARS)
        digest = sha256_text(text)
        if include_hash and item.get("text_sha256") != digest:
            raise ValueError("answer support candidate integrity is invalid")
        rows.append(
            {"candidate_id": candidate_id, "text": text, "text_sha256": digest}
        )
    if len({row["candidate_id"] for row in rows}) != len(rows):
        raise ValueError("answer support candidate ids are duplicated")
    return rows


def _verified_request(value: Mapping[str, Any], design_hash: str) -> dict[str, Any]:
    _exact_mapping(value, _REQUEST_FIELDS, "answer support request")
    request = dict(value)
    request_hash = validate_hash_ref(request.pop("request_hash", None))
    if request_hash != semantic_sha256_hash_ref(request):
        raise ValueError("answer support request integrity is invalid")
    if (
        request.get("request_schema_version") != ANSWER_SUPPORT_REQUEST_SCHEMA_VERSION
        or request.get("policy_id") != ANSWER_SUPPORT_POLICY_ID
        or request.get("design_hash") != design_hash
    ):
        raise ValueError("answer support request identity is invalid")
    query = _mapping(request.get("query"), "answer support request query")
    _exact_mapping(query, {"text", "sha256"}, "answer support request query")
    query_text = _bounded_text(query.get("text"), "query_text", MAXIMUM_QUERY_CHARS)
    if query.get("sha256") != sha256_text(query_text):
        raise ValueError("answer support request query integrity is invalid")
    candidates = _request_candidates(request.get("candidates"), include_hash=True)
    if candidates != request.get("candidates"):
        raise ValueError("answer support request candidates are invalid")
    admission = _mapping(request.get("admission"), "answer support request admission")
    if dict(admission) != {
        "permission_filtered": True,
        "owner_scope_enforced": True,
        "candidate_truth_included": False,
    }:
        raise ValueError("answer support request admission is invalid")
    response_contract = _mapping(
        request.get("response_contract"), "answer support response contract"
    )
    if response_contract != {
        "response_schema_version": ANSWER_SUPPORT_RESPONSE_SCHEMA_VERSION,
        "classes": list(ANSWER_SUPPORT_CLASSES),
        "score_semantics": ANSWER_SUPPORT_SCORE_SEMANTICS,
        "provider_binding_fields": list(PROVIDER_BINDING_FIELDS),
        "free_form_rationale_permitted": False,
    }:
        raise ValueError("answer support response contract is invalid")
    request["query"] = dict(query)
    request["candidates"] = candidates
    request["request_hash"] = request_hash
    return request


def _response_items(value: object, *, expected_ids: set[str]) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("answer support response items are invalid")
    items: list[dict[str, Any]] = []
    for raw in value:
        _exact_mapping(raw, _RESPONSE_ITEM_FIELDS, "answer support response item")
        candidate_id = _required_text(raw.get("candidate_id"), "candidate_id")
        classification = _required_text(raw.get("classification"), "classification")
        if classification not in ANSWER_SUPPORT_CLASSES:
            raise ValueError("answer support classification is invalid")
        support = _bounded_score(raw.get("answer_support_score"), "answer_support_score")
        contradiction = _bounded_score(
            raw.get("contradiction_score"), "contradiction_score"
        )
        if classification in {"DIRECT_ANSWER", "SUPPORTING_EVIDENCE"} and not (
            support > contradiction
        ):
            raise ValueError("answer support classification score ordering is invalid")
        if classification == "CONTRADICTORY_EVIDENCE" and not (
            contradiction > support
        ):
            raise ValueError("contradiction classification score ordering is invalid")
        items.append(
            {
                "candidate_id": candidate_id,
                "classification": classification,
                "answer_support_score": support,
                "contradiction_score": contradiction,
            }
        )
    ids = [row["candidate_id"] for row in items]
    if len(set(ids)) != len(ids) or set(ids) != expected_ids:
        raise ValueError("answer support response candidate coverage is invalid")
    return sorted(items, key=lambda row: row["candidate_id"])


def _verified_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    _exact_mapping(value, _EVIDENCE_FIELDS, "answer support evidence")
    evidence = dict(value)
    evidence_hash = validate_hash_ref(evidence.pop("evidence_hash", None))
    if evidence_hash != semantic_sha256_hash_ref(evidence):
        raise ValueError("answer support evidence integrity is invalid")
    if (
        evidence.get("evidence_schema_version") != ANSWER_SUPPORT_EVIDENCE_SCHEMA_VERSION
        or evidence.get("policy_id") != ANSWER_SUPPORT_POLICY_ID
        or evidence.get("status") != "CONTRACT_EVIDENCE_NORMALIZED"
        or evidence.get("score_semantics") != ANSWER_SUPPORT_SCORE_SEMANTICS
    ):
        raise ValueError("answer support evidence identity is invalid")
    validate_hash_ref(evidence.get("design_hash"))
    validate_hash_ref(evidence.get("request_hash"))
    try:
        validate_sha256_digest(evidence.get("query_sha256"))
    except ValueError:
        raise ValueError("answer support evidence query hash is invalid") from None
    evidence["provider_binding"] = _provider_binding(evidence.get("provider_binding"))
    items = evidence.get("candidate_evidence")
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence) or not items:
        raise ValueError("answer support candidate evidence is invalid")
    for item in items:
        _exact_mapping(
            item,
            _RESPONSE_ITEM_FIELDS | {"candidate_text_sha256"},
            "answer support candidate evidence",
        )
        _response_items(
            [
                {
                    field: item[field]
                    for field in _RESPONSE_ITEM_FIELDS
                }
            ],
            expected_ids={str(item.get("candidate_id"))},
        )
        try:
            validate_sha256_digest(item.get("candidate_text_sha256"))
        except ValueError:
            raise ValueError("answer support candidate text hash is invalid") from None
    privacy = _mapping(evidence.get("privacy"), "answer support evidence privacy")
    if dict(privacy) != {
        "raw_query_persisted": False,
        "raw_candidate_text_persisted": False,
        "free_form_rationale_persisted": False,
    }:
        raise ValueError("answer support evidence privacy is invalid")
    safety = _mapping(evidence.get("safety"), "answer support evidence safety")
    if dict(safety) != {
        "candidate_truth_runtime_input_permitted": False,
        "holdout_access_permitted": False,
        "threshold_selected": False,
        "ready_decision_emitted": False,
        "runtime_activation_permitted": False,
    }:
        raise ValueError("answer support evidence safety is invalid")
    evidence["candidate_evidence"] = [dict(item) for item in items]
    evidence["evidence_hash"] = evidence_hash
    return evidence


def _provider_binding(value: object) -> dict[str, str]:
    binding = _mapping(value, "answer support provider binding")
    if set(binding) != set(PROVIDER_BINDING_FIELDS):
        raise ValueError("answer support provider binding fields are invalid")
    return {field: _required_text(binding.get(field), field) for field in PROVIDER_BINDING_FIELDS}


def _exact_mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    mapping = _mapping(value, name)
    if set(mapping) != fields:
        raise ValueError(f"{name} fields are invalid")
    return mapping


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _bounded_text(value: object, field: str, maximum: int) -> str:
    text = _required_text(value, field)
    if len(text) > maximum:
        raise ValueError(f"{field} is too long")
    return text


def _bounded_score(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{field} is invalid")
    return round(float(value), 12)
