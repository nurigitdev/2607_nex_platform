from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from nex_runtime.model_artifact_revision import normalize_immutable_model_revision
from nex_runtime.semantic_hashes import (
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

from nex_cx.retrieval_answer_support_signal import (
    ANSWER_SUPPORT_CLASSES,
    ANSWER_SUPPORT_RESPONSE_SCHEMA_VERSION,
    build_answer_support_request,
    normalize_answer_support_response,
    validate_answer_support_signal_design,
)

ANSWER_SUPPORT_REQUEST_PROFILE_SCHEMA_VERSION = (
    "cx_answer_support_generation_request_profile.v1"
)
ANSWER_SUPPORT_COLLECTION_SCHEMA_VERSION = "cx_answer_support_calibration_collection.v1"
ANSWER_SUPPORT_COLLECTION_POLICY_ID = "cx_answer_support_calibration_collection_v1"

_PROFILE_FIELDS = {
    "profile_schema_version",
    "profile_id",
    "status",
    "provider_capability",
    "provider_alias",
    "response_format",
    "reasoning_mode",
    "temperature",
    "max_output_tokens",
    "score_semantics_id",
    "system_instruction",
    "safety",
}
_COLLECTION_FIELDS = {
    "collection_schema_version",
    "policy_id",
    "status",
    "dataset",
    "answer_support_design_hash",
    "request_profile_id",
    "request_profile_hash",
    "provider_binding",
    "artifact_evidence_hash",
    "source_retrieval_evidence_hash",
    "package_evidence",
    "privacy",
    "safety",
    "collection_hash",
}

GenerationEvaluator = Callable[[Mapping[str, Any], str, str], Mapping[str, Any]]


def validate_answer_support_request_profile(
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and hash the frozen generation request profile."""
    _exact_mapping(profile, _PROFILE_FIELDS, "answer support request profile")
    if (
        profile.get("profile_schema_version")
        != ANSWER_SUPPORT_REQUEST_PROFILE_SCHEMA_VERSION
        or profile.get("status") != "FROZEN_CALIBRATION_ONLY"
        or profile.get("provider_capability") != "generation"
        or profile.get("response_format") != {"type": "json_object"}
        or profile.get("reasoning_mode") != "disabled"
        or profile.get("temperature") != 0.0
    ):
        raise ValueError("answer support request profile identity is invalid")
    _required_text(profile.get("profile_id"), "profile_id")
    _required_text(profile.get("provider_alias"), "provider_alias")
    _required_text(profile.get("score_semantics_id"), "score_semantics_id")
    _required_text(profile.get("system_instruction"), "system_instruction")
    max_tokens = profile.get("max_output_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 1024:
        raise ValueError("answer support request profile token limit is invalid")
    safety = _mapping(profile.get("safety"), "answer support request profile safety")
    if dict(safety) != {
        "candidate_text_is_untrusted_data": True,
        "free_form_rationale_permitted": False,
        "candidate_truth_runtime_input_permitted": False,
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }:
        raise ValueError("answer support request profile safety is invalid")
    normalized = dict(profile)
    normalized["profile_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def build_answer_support_generation_payload(
    request: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Translate one private P-H request into the admitted MO generation shape."""
    normalized_profile = validate_answer_support_request_profile(profile)
    query = _mapping(request.get("query"), "answer support request query")
    candidates = request.get("candidates")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise TypeError("answer support request candidates are invalid")
    candidate_payload = []
    for candidate in candidates:
        row = _mapping(candidate, "answer support request candidate")
        candidate_payload.append(
            {
                "candidate_id": _required_text(row.get("candidate_id"), "candidate_id"),
                "text": _required_text(row.get("text"), "candidate text"),
            }
        )
    if not candidate_payload:
        raise ValueError("answer support request candidates are empty")
    user_content = {
        "query": _required_text(query.get("text"), "query text"),
        "candidates": candidate_payload,
        "required_output": {
            "items": [
                {
                    "candidate_id": "exact input candidate_id",
                    "classification": list(ANSWER_SUPPORT_CLASSES),
                    "answer_support_score": "number from 0 through 1",
                    "contradiction_score": "number from 0 through 1",
                }
            ]
        },
    }
    return {
        "alias": normalized_profile["provider_alias"],
        "provider_capability": "generation",
        "messages": [
            {"role": "system", "content": normalized_profile["system_instruction"]},
            {
                "role": "user",
                "content": json.dumps(
                    user_content,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "reasoning_mode": "disabled",
        "temperature": 0.0,
        "max_output_tokens": normalized_profile["max_output_tokens"],
        "stream": False,
    }


def normalize_answer_support_generation_result(
    *,
    request: Mapping[str, Any],
    result: Mapping[str, Any],
    design: Mapping[str, Any],
    profile: Mapping[str, Any],
    artifact_revision: str,
) -> dict[str, Any]:
    """Convert normalized MO generation output into P-H text-free evidence."""
    normalized_profile = validate_answer_support_request_profile(profile)
    revision = normalize_immutable_model_revision(artifact_revision)
    if result.get("finish_reason") != "STOP":
        raise ValueError("answer support generation did not finish cleanly")
    if result.get("model_revision") != revision:
        raise ValueError("answer support generation artifact revision drifted")
    output = _mapping(result.get("output"), "answer support generation output")
    if output.get("type") != "text":
        raise ValueError("answer support generation output type is invalid")
    text = _required_text(output.get("text"), "answer support generation output text")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("answer support generation output is not JSON") from exc
    _exact_mapping(payload, {"items"}, "answer support generation output")
    request_id = _required_text(request.get("request_id"), "request_id")
    binding = {
        "provider_alias": _required_text(result.get("alias"), "provider_alias"),
        "provider_type": _required_text(result.get("provider_type"), "provider_type"),
        "model_revision": revision,
        "deployment_id": _required_text(result.get("deployment_id"), "deployment_id"),
        "request_profile_id": normalized_profile["profile_id"],
        "score_semantics_id": normalized_profile["score_semantics_id"],
    }
    response = {
        "response_schema_version": ANSWER_SUPPORT_RESPONSE_SCHEMA_VERSION,
        "request_id": request_id,
        "provider_binding": binding,
        "items": payload["items"],
    }
    return normalize_answer_support_response(
        request=request,
        response=response,
        expected_provider_binding=binding,
        design=design,
    )


def collect_answer_support_calibration(
    cases: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    design: Mapping[str, Any],
    profile: Mapping[str, Any],
    artifact_revision: str,
    artifact_evidence_hash: str,
    source_retrieval_evidence_hash: str,
    evaluator: GenerationEvaluator,
    maximum_concurrency: int = 1,
    request_namespace: str = "s20qpi",
) -> dict[str, Any]:
    """Collect CALIBRATION-only provider evidence without persisting source text."""
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise TypeError("answer support calibration cases are invalid")
    if not cases:
        raise ValueError("answer support calibration cases are empty")
    if (
        isinstance(maximum_concurrency, bool)
        or not isinstance(maximum_concurrency, int)
        or not 1 <= maximum_concurrency <= 16
    ):
        raise ValueError("answer support calibration concurrency is invalid")
    normalized_design = validate_answer_support_signal_design(design)
    normalized_profile = validate_answer_support_request_profile(profile)
    namespace = _required_text(request_namespace, "request_namespace")
    revision = normalize_immutable_model_revision(artifact_revision)
    artifact_hash = validate_hash_ref(artifact_evidence_hash)
    source_hash = validate_hash_ref(source_retrieval_evidence_hash)
    package_ids: set[str] = set()
    normalized_cases: list[tuple[str, Mapping[str, Any]]] = []
    for case in cases:
        row = _mapping(case, "answer support calibration case")
        if row.get("partition") != "CALIBRATION":
            raise ValueError("answer support collection cannot access HOLDOUT")
        package_id = _required_text(row.get("case_id"), "case_id")
        if package_id in package_ids:
            raise ValueError("answer support calibration package is duplicated")
        package_ids.add(package_id)
        normalized_cases.append((package_id, row))

    def collect_case(
        item: tuple[str, Mapping[str, Any]],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        package_id, row = item
        candidates = _provider_candidates(row.get("candidates"))
        request_id = f"{namespace}-{package_id}"
        request = build_answer_support_request(
            request_id=request_id,
            query_text=_required_text(row.get("query"), "query"),
            candidates=candidates,
            design=design,
            permission_filtered=True,
            owner_scope_enforced=True,
        )
        generation_payload = build_answer_support_generation_payload(
            request,
            profile=profile,
        )
        result = evaluator(
            generation_payload,
            request_id,
            f"{namespace}-trace-{package_id}",
        )
        evidence = normalize_answer_support_generation_result(
            request=request,
            result=result,
            design=design,
            profile=profile,
            artifact_revision=revision,
        )
        return dict(evidence["provider_binding"]), {
            "package_id": package_id,
            "request_id": evidence["request_id"],
            "request_hash": evidence["request_hash"],
            "query_sha256": evidence["query_sha256"],
            "candidate_evidence": evidence["candidate_evidence"],
            "evidence_hash": evidence["evidence_hash"],
        }

    if maximum_concurrency == 1:
        collected = [collect_case(item) for item in normalized_cases]
    else:
        with ThreadPoolExecutor(max_workers=maximum_concurrency) as executor:
            collected = list(executor.map(collect_case, normalized_cases))
    bindings = [binding for binding, _ in collected]
    package_evidence = [evidence for _, evidence in collected]
    provider_binding = bindings[0]
    if any(binding != provider_binding for binding in bindings[1:]):
        raise ValueError("answer support provider binding drifted during collection")
    package_evidence.sort(key=lambda row: row["package_id"])
    candidate_count = sum(len(row["candidate_evidence"]) for row in package_evidence)
    collection: dict[str, Any] = {
        "collection_schema_version": ANSWER_SUPPORT_COLLECTION_SCHEMA_VERSION,
        "policy_id": ANSWER_SUPPORT_COLLECTION_POLICY_ID,
        "status": "CALIBRATION_COLLECTED",
        "dataset": {
            "dataset_id": _required_text(dataset_id, "dataset_id"),
            "dataset_sha256": _required_text(dataset_sha256, "dataset_sha256"),
            "partition": "CALIBRATION",
            "package_count": len(package_evidence),
            "candidate_count": candidate_count,
            "holdout_status": "SEALED_NOT_ACCESSED",
        },
        "answer_support_design_hash": normalized_design["design_hash"],
        "request_profile_id": normalized_profile["profile_id"],
        "request_profile_hash": normalized_profile["profile_hash"],
        "provider_binding": provider_binding,
        "artifact_evidence_hash": artifact_hash,
        "source_retrieval_evidence_hash": source_hash,
        "package_evidence": package_evidence,
        "privacy": {
            "raw_query_persisted": False,
            "raw_candidate_text_persisted": False,
            "candidate_truth_persisted": False,
            "provider_output_text_persisted": False,
        },
        "safety": {
            "calibration_partition_only": True,
            "candidate_truth_runtime_input_permitted": False,
            "holdout_access_permitted": False,
            "profile_selection_permitted": False,
            "threshold_selection_permitted": False,
            "runtime_activation_permitted": False,
        },
    }
    collection["collection_hash"] = semantic_sha256_hash_ref(collection)
    return collection


def validate_answer_support_calibration_collection(
    collection: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify integrity and semantic safety before P-J consumes the evidence."""
    _exact_mapping(collection, _COLLECTION_FIELDS, "answer support collection")
    normalized = dict(collection)
    collection_hash = validate_hash_ref(normalized.pop("collection_hash", None))
    if collection_hash != semantic_sha256_hash_ref(normalized):
        raise ValueError("answer support collection integrity is invalid")
    if (
        normalized.get("collection_schema_version")
        != ANSWER_SUPPORT_COLLECTION_SCHEMA_VERSION
        or normalized.get("policy_id") != ANSWER_SUPPORT_COLLECTION_POLICY_ID
        or normalized.get("status") != "CALIBRATION_COLLECTED"
    ):
        raise ValueError("answer support collection identity is invalid")
    dataset = _mapping(normalized.get("dataset"), "answer support collection dataset")
    if (
        dataset.get("partition") != "CALIBRATION"
        or dataset.get("holdout_status") != "SEALED_NOT_ACCESSED"
    ):
        raise ValueError("answer support collection partition is invalid")
    packages = normalized.get("package_evidence")
    if isinstance(packages, (str, bytes)) or not isinstance(packages, Sequence) or not packages:
        raise ValueError("answer support package evidence is invalid")
    if dataset.get("package_count") != len(packages) or dataset.get(
        "candidate_count"
    ) != sum(len(_mapping(row, "package evidence")["candidate_evidence"]) for row in packages):
        raise ValueError("answer support collection counts are invalid")
    privacy = _mapping(normalized.get("privacy"), "answer support collection privacy")
    if any(value is not False for value in privacy.values()):
        raise ValueError("answer support collection privacy is invalid")
    safety = _mapping(normalized.get("safety"), "answer support collection safety")
    if safety.get("calibration_partition_only") is not True or any(
        safety.get(field) is not False
        for field in (
            "candidate_truth_runtime_input_permitted",
            "holdout_access_permitted",
            "profile_selection_permitted",
            "threshold_selection_permitted",
            "runtime_activation_permitted",
        )
    ):
        raise ValueError("answer support collection safety is invalid")
    normalized["collection_hash"] = collection_hash
    return normalized


def _provider_candidates(value: object) -> list[dict[str, str]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("answer support calibration candidates are invalid")
    rows = []
    for item in value:
        candidate = _mapping(item, "answer support calibration candidate")
        rows.append(
            {
                "candidate_id": _required_text(
                    candidate.get("candidate_id"), "candidate_id"
                ),
                "text": _required_text(candidate.get("text"), "candidate text"),
            }
        )
    return rows


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
