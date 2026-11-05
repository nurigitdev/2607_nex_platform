from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from nex_runtime.model_calibration import (
    BinaryCalibrationConstraints,
    evaluate_binary_score_threshold,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx import retrieval_answer_support_nested_selection as answer_support
from nex_cx.retrieval_answer_support_collection import (
    build_answer_support_generation_payload,
    normalize_answer_support_generation_result,
    validate_answer_support_request_profile,
)
from nex_cx.retrieval_answer_support_signal import (
    ANSWER_SUPPORT_EVIDENCE_SCHEMA_VERSION,
    ANSWER_SUPPORT_POLICY_ID,
    ANSWER_SUPPORT_SCORE_SEMANTICS,
    build_answer_support_package_features,
    build_answer_support_request,
    validate_answer_support_signal_design,
)

HOLDOUT_COLLECTION_SCHEMA_VERSION = "cx_answer_support_holdout_collection.v1"
HOLDOUT_EVALUATION_SCHEMA_VERSION = "cx_answer_support_holdout_evaluation.v1"
HOLDOUT_RECEIPT_SCHEMA_VERSION = "cx_answer_support_holdout_receipt.v1"

GenerationEvaluator = Callable[[Mapping[str, Any], str, str], Mapping[str, Any]]


def collect_answer_support_holdout(
    cases: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_sha256: str,
    design: Mapping[str, Any],
    profile: Mapping[str, Any],
    artifact_revision: str,
    artifact_evidence_hash: str,
    evaluator: GenerationEvaluator,
    maximum_concurrency: int,
    request_namespace: str,
) -> dict[str, Any]:
    """Collect one text-free HOLDOUT observation for every admitted package."""
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise TypeError("answer support HOLDOUT cases are invalid")
    if not cases:
        raise ValueError("answer support HOLDOUT cases are empty")
    if (
        isinstance(maximum_concurrency, bool)
        or not isinstance(maximum_concurrency, int)
        or not 1 <= maximum_concurrency <= 16
    ):
        raise ValueError("answer support HOLDOUT concurrency is invalid")
    normalized_design = validate_answer_support_signal_design(design)
    normalized_profile = validate_answer_support_request_profile(profile)
    revision = _required_text(artifact_revision, "artifact_revision")
    artifact_hash = validate_hash_ref(artifact_evidence_hash)
    namespace = _required_text(request_namespace, "request_namespace")
    package_ids: set[str] = set()
    normalized_cases: list[tuple[str, Mapping[str, Any]]] = []
    for raw in cases:
        case = _mapping(raw, "answer support HOLDOUT case")
        if case.get("partition") != "HOLDOUT":
            raise ValueError("answer support HOLDOUT collection requires HOLDOUT only")
        package_id = _required_text(case.get("case_id"), "case_id")
        if package_id in package_ids:
            raise ValueError("answer support HOLDOUT package is duplicated")
        package_ids.add(package_id)
        normalized_cases.append((package_id, case))

    def collect_case(
        item: tuple[str, Mapping[str, Any]],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        package_id, case = item
        candidates = _provider_candidates(case.get("candidates"))
        request_id = f"{namespace}-{package_id}"
        request = build_answer_support_request(
            request_id=request_id,
            query_text=_required_text(case.get("query"), "query"),
            candidates=candidates,
            design=design,
            permission_filtered=True,
            owner_scope_enforced=True,
        )
        payload = build_answer_support_generation_payload(request, profile=profile)
        result = evaluator(payload, request_id, f"{namespace}-trace-{package_id}")
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

    ordered = sorted(normalized_cases, key=lambda item: item[0])
    if maximum_concurrency == 1:
        collected = [collect_case(item) for item in ordered]
    else:
        with ThreadPoolExecutor(max_workers=maximum_concurrency) as executor:
            collected = list(executor.map(collect_case, ordered))
    bindings = [binding for binding, _ in collected]
    provider_binding = bindings[0]
    if any(binding != provider_binding for binding in bindings[1:]):
        raise ValueError("answer support HOLDOUT provider binding drifted")
    packages = sorted((row for _, row in collected), key=lambda row: row["package_id"])
    collection: dict[str, Any] = {
        "collection_schema_version": HOLDOUT_COLLECTION_SCHEMA_VERSION,
        "status": "HOLDOUT_COLLECTED",
        "dataset": {
            "dataset_id": _required_text(dataset_id, "dataset_id"),
            "dataset_sha256": validate_hash_ref(dataset_sha256),
            "partition": "HOLDOUT",
            "package_count": len(packages),
            "candidate_count": sum(len(row["candidate_evidence"]) for row in packages),
        },
        "answer_support_design_hash": normalized_design["design_hash"],
        "request_profile_id": normalized_profile["profile_id"],
        "request_profile_hash": normalized_profile["profile_hash"],
        "provider_binding": provider_binding,
        "artifact_evidence_hash": artifact_hash,
        "package_evidence": packages,
        "privacy": {
            "raw_query_persisted": False,
            "raw_candidate_text_persisted": False,
            "candidate_truth_persisted": False,
            "provider_output_text_persisted": False,
        },
        "safety": {
            "profile_selection_permitted": False,
            "threshold_selection_permitted": False,
            "runtime_activation_permitted": False,
        },
    }
    collection["collection_hash"] = semantic_sha256_hash_ref(collection)
    return collection


def evaluate_answer_support_holdout(
    collection: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    canonical_profile: Mapping[str, Any],
    frozen_candidate: Mapping[str, Any],
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate the frozen profile and threshold without fitting or reselection."""
    normalized = _validate_collection(collection)
    profile = _mapping(canonical_profile, "canonical profile")
    candidate = _mapping(frozen_candidate, "frozen candidate")
    profile_hash = validate_hash_ref(profile.get("profile_hash"))
    if (
        profile.get("profile_id") != candidate.get("profile_id")
        or profile_hash != validate_hash_ref(candidate.get("profile_hash"))
    ):
        raise ValueError("answer support HOLDOUT profile binding drifted")
    threshold = _bounded(candidate.get("threshold"), "threshold")
    constraints = BinaryCalibrationConstraints(
        maximum_false_ready_rate=_bounded(
            admission.get("maximum_false_ready_rate"), "maximum_false_ready_rate"
        ),
        minimum_ready_recall=_bounded(
            admission.get("minimum_ready_recall"), "minimum_ready_recall"
        ),
    )
    minimum_auc = _bounded(admission.get("minimum_package_auc"), "minimum_package_auc")
    samples = _holdout_samples(normalized, cases)
    scores = answer_support._profile_scores(samples, profile=profile)
    evaluation = evaluate_binary_score_threshold(
        scores,
        dataset_id=f"{normalized['dataset']['dataset_id']}:one-shot-holdout",
        threshold=threshold,
        constraints=constraints,
    )
    package_auc = answer_support._auc(scores)
    metrics = _mapping(evaluation.get("metrics"), "HOLDOUT metrics")
    checks = {
        "fixed_threshold_evaluated": evaluation.get("threshold") == threshold,
        "false_ready_rate_within_limit": metrics.get("false_ready_rate")
        <= constraints.maximum_false_ready_rate,
        "ready_recall_within_limit": metrics.get("ready_recall")
        >= constraints.minimum_ready_recall,
        "package_auc_within_limit": package_auc >= minimum_auc,
        "profile_selection_not_performed": True,
        "threshold_selection_not_performed": True,
        "runtime_activation_prohibited": True,
    }
    admitted = all(checks.values())
    result: dict[str, Any] = {
        "evaluation_schema_version": HOLDOUT_EVALUATION_SCHEMA_VERSION,
        "status": "HOLDOUT_ADMITTED" if admitted else "HOLDOUT_REJECTED",
        "terminal_status": "PASS" if admitted else "FAIL",
        "dataset": {
            **dict(normalized["dataset"]),
            "sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(row["sample_hash"]) for row in samples)
            ),
        },
        "candidate": {
            "profile_id": candidate["profile_id"],
            "profile_hash": profile_hash,
            "threshold": threshold,
        },
        "provider_binding": dict(normalized["provider_binding"]),
        "collection_hash": normalized["collection_hash"],
        "metrics": dict(metrics),
        "confidence_intervals": evaluation["confidence_intervals"],
        "package_auc": package_auc,
        "checks": checks,
        "threshold_reselected": False,
        "profile_reselected": False,
        "runtime_activation_permitted": False,
    }
    result["evaluation_hash"] = semantic_sha256_hash_ref(result)
    return result


def build_holdout_receipt_reservation(
    freeze: Mapping[str, Any], *, started_at: str
) -> dict[str, Any]:
    """Create the canonical STARTED receipt payload written with O_EXCL."""
    value = _validated_freeze(freeze)
    authorization = _mapping(value["authorization"], "authorization")
    receipt: dict[str, Any] = {
        "receipt_schema_version": HOLDOUT_RECEIPT_SCHEMA_VERSION,
        "status": "STARTED",
        "execution_id": value["execution_id"],
        "authorization_hash": value["authorization_hash"],
        "freeze_hash": value["freeze_hash"],
        "attempt_number": 1,
        "started_at": _required_text(started_at, "started_at"),
        "completed_at": None,
        "provider_evaluation_count": 0,
        "provider_http_request_count": 0,
        "dataset_file_sha256": authorization["dataset"]["dataset_file_sha256"],
        "dataset_semantic_sha256": authorization["dataset"][
            "dataset_semantic_sha256"
        ],
        "evaluation_hash": None,
        "terminal_reason": None,
    }
    receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
    return receipt


def complete_holdout_receipt(
    reservation: Mapping[str, Any],
    *,
    terminal_status: str,
    completed_at: str,
    provider_evaluation_count: int,
    provider_http_request_count: int,
    evaluation_hash: str | None = None,
    terminal_reason: str | None = None,
) -> dict[str, Any]:
    """Produce one terminal consumed receipt from an intact STARTED receipt."""
    value = dict(_mapping(reservation, "HOLDOUT receipt reservation"))
    receipt_hash = validate_hash_ref(value.pop("receipt_hash", None))
    if semantic_sha256_hash_ref(value) != receipt_hash or value.get("status") != "STARTED":
        raise ValueError("HOLDOUT receipt reservation integrity is invalid")
    if terminal_status not in {"PASS", "FAIL", "INCONCLUSIVE"}:
        raise ValueError("HOLDOUT terminal status is invalid")
    evaluations = _non_negative_int(provider_evaluation_count, "provider_evaluation_count")
    requests = _non_negative_int(provider_http_request_count, "provider_http_request_count")
    if requests > 40 or evaluations > 40:
        raise ValueError("HOLDOUT provider budget exceeded")
    if terminal_status in {"PASS", "FAIL"}:
        terminal_hash = validate_hash_ref(evaluation_hash)
        reason = None
    else:
        if evaluation_hash is not None:
            raise ValueError("inconclusive HOLDOUT cannot have an evaluation hash")
        terminal_hash = None
        reason = _required_text(terminal_reason, "terminal_reason")
    value.update(
        {
            "status": terminal_status,
            "completed_at": _required_text(completed_at, "completed_at"),
            "provider_evaluation_count": evaluations,
            "provider_http_request_count": requests,
            "evaluation_hash": terminal_hash,
            "terminal_reason": reason,
        }
    )
    value["receipt_hash"] = semantic_sha256_hash_ref(value)
    return value


def _validated_freeze(value: Mapping[str, Any]) -> dict[str, Any]:
    freeze = dict(_mapping(value, "HOLDOUT freeze"))
    freeze_hash = validate_hash_ref(freeze.pop("freeze_hash", None))
    if semantic_sha256_hash_ref(freeze) != freeze_hash:
        raise ValueError("HOLDOUT freeze integrity is invalid")
    authorization_hash = validate_hash_ref(freeze.get("authorization_hash"))
    authorization = _mapping(freeze.get("authorization"), "authorization")
    if (
        semantic_sha256_hash_ref(authorization) != authorization_hash
        or freeze.get("status") != "HOLDOUT_ONE_SHOT_EXECUTION_ARMED"
        or freeze.get("execution_id")
        != f"s20qpq-{authorization_hash.removeprefix('sha256:')[:24]}"
        or freeze.get("new_provider_calls") != 0
        or freeze.get("runtime_activation_permitted") is not False
    ):
        raise ValueError("HOLDOUT freeze authorization is invalid")
    freeze["freeze_hash"] = freeze_hash
    return freeze


def _validate_collection(value: Mapping[str, Any]) -> dict[str, Any]:
    collection = dict(_mapping(value, "HOLDOUT collection"))
    collection_hash = validate_hash_ref(collection.pop("collection_hash", None))
    dataset = _mapping(collection.get("dataset"), "HOLDOUT dataset")
    packages = collection.get("package_evidence")
    if (
        semantic_sha256_hash_ref(collection) != collection_hash
        or collection.get("collection_schema_version")
        != HOLDOUT_COLLECTION_SCHEMA_VERSION
        or collection.get("status") != "HOLDOUT_COLLECTED"
        or dataset.get("partition") != "HOLDOUT"
        or not isinstance(packages, list)
        or dataset.get("package_count") != len(packages)
        or dataset.get("candidate_count")
        != sum(len(_mapping(row, "package")["candidate_evidence"]) for row in packages)
        or any(value is not False for value in collection["privacy"].values())
        or any(value is not False for value in collection["safety"].values())
    ):
        raise ValueError("HOLDOUT collection integrity is invalid")
    collection["collection_hash"] = collection_hash
    return collection


def _holdout_samples(
    collection: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    truth: dict[str, Mapping[str, Any]] = {}
    for raw in cases:
        case = _mapping(raw, "HOLDOUT truth case")
        if case.get("partition") != "HOLDOUT":
            raise ValueError("HOLDOUT evaluation received another partition")
        case_id = _required_text(case.get("case_id"), "case_id")
        if case_id in truth:
            raise ValueError("HOLDOUT truth case is duplicated")
        truth[case_id] = case
    packages = {
        str(row["package_id"]): _mapping(row, "HOLDOUT package")
        for row in collection["package_evidence"]
    }
    if set(truth) != set(packages):
        raise ValueError("HOLDOUT package coverage is incomplete")
    samples = []
    for package_id, case in sorted(truth.items()):
        package = packages[package_id]
        evidence = {
            "evidence_schema_version": ANSWER_SUPPORT_EVIDENCE_SCHEMA_VERSION,
            "policy_id": ANSWER_SUPPORT_POLICY_ID,
            "status": "CONTRACT_EVIDENCE_NORMALIZED",
            "design_hash": collection["answer_support_design_hash"],
            "request_id": package["request_id"],
            "request_hash": package["request_hash"],
            "query_sha256": package["query_sha256"],
            "provider_binding": collection["provider_binding"],
            "score_semantics": ANSWER_SUPPORT_SCORE_SEMANTICS,
            "candidate_evidence": package["candidate_evidence"],
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
            "evidence_hash": package["evidence_hash"],
        }
        projection = build_answer_support_package_features(evidence)
        features = answer_support._transformed_features(projection["features"])
        sample: dict[str, Any] = {
            "sample_schema_version": "cx_answer_support_holdout_sample.v1",
            "sample_id": package_id,
            "scenario_id": _required_text(case.get("scenario_id"), "scenario_id"),
            "expected_ready": _required_bool(case.get("expected_ready"), "expected_ready"),
            "features": features,
            "source_feature_hash": projection["feature_hash"],
            "source_evidence_hash": package["evidence_hash"],
        }
        sample["sample_hash"] = semantic_sha256_hash_ref(sample)
        samples.append(sample)
    return samples


def _provider_candidates(value: object) -> list[dict[str, str]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("answer support HOLDOUT candidates are invalid")
    rows = []
    for raw in value:
        candidate = _mapping(raw, "answer support HOLDOUT candidate")
        rows.append(
            {
                "candidate_id": _required_text(candidate.get("candidate_id"), "candidate_id"),
                "text": _required_text(candidate.get("text"), "candidate text"),
            }
        )
    if not rows:
        raise ValueError("answer support HOLDOUT candidates are empty")
    return rows


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _required_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} is invalid")
    return value


def _bounded(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} is invalid")
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{name} is invalid")
    return numeric


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} is invalid")
    return value
