from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

RUNTIME_READINESS_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_runtime_activation_readiness_design.v1"
)
RUNTIME_READINESS_MANIFEST_SCHEMA_VERSION = (
    "cx_answer_support_runtime_activation_readiness_manifest.v1"
)
RUNTIME_PROFILE_SCHEMA_VERSION = "cx_answer_support_runtime_profile.v1"
READINESS_DECISION = "READY_FOR_SHADOW_RUNTIME_INTEGRATION"
ACTIVATION_STATUS = "NOT_ACTIVATED"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "runtime_inventory",
    "readiness_policy",
    "rollout_boundary",
    "safety",
}
_SOURCE_FIELDS = {
    "authorization_hash",
    "canonical_profile_hash",
    "dataset_semantic_sha256",
    "evaluation_hash",
    "execution_id",
    "holdout_report_hash",
    "model_revision",
    "profile_id",
    "receipt_document_hash",
    "receipt_hash",
    "request_profile_hash",
    "threshold",
}
_EXPECTED_RUNTIME_INVENTORY = {
    "candidate_profile_schema": RUNTIME_PROFILE_SCHEMA_VERSION,
    "current_confidence_consumer_schema": (
        "cx_retrieval_confidence_calibration_profile.v1"
    ),
    "direct_activation_compatible": False,
    "runtime_answer_support_evaluator_installed": False,
}
_EXPECTED_READINESS_POLICY = {
    "activation_status": ACTIVATION_STATUS,
    "admitted_readiness": READINESS_DECISION,
    "expected_provider_evaluations": 40,
    "expected_provider_http_requests": 40,
    "maximum_false_ready_rate": 0.10,
    "minimum_package_auc": 0.80,
    "minimum_ready_recall": 0.80,
    "required_holdout_status": "HOLDOUT_ADMITTED",
}
_EXPECTED_ROLLOUT_BOUNDARY = {
    "cutover_requires_new_holdout": False,
    "cutover_requires_separate_operator_approval": True,
    "fail_closed_on_binding_drift": True,
    "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
    "first_stage": "SHADOW",
    "rollback_target": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
    "shadow_decision_user_visible": False,
}
_EXPECTED_SAFETY = {
    "candidate_truth_runtime_input_permitted": False,
    "holdout_reexecution_permitted": False,
    "production_cutover_permitted_in_this_slice": False,
    "provider_call_permitted_in_this_slice": False,
    "runtime_activation_permitted_in_this_slice": False,
    "threshold_or_profile_reselection_permitted": False,
}
_REQUIRED_HOLDOUT_CHECKS = {
    "false_ready_rate_within_limit",
    "fixed_threshold_evaluated",
    "package_auc_within_limit",
    "profile_selection_not_performed",
    "ready_recall_within_limit",
    "runtime_activation_prohibited",
    "threshold_selection_not_performed",
}


class AnswerSupportRuntimeReadinessError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_runtime_readiness_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the post-HOLDOUT boundary without opening HOLDOUT inputs."""
    _exact_mapping(design, _DESIGN_FIELDS, "runtime readiness design")
    if (
        design.get("design_schema_version")
        != RUNTIME_READINESS_DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_POST_HOLDOUT_DECISION"
    ):
        raise _invalid("design_identity")
    _required_text(design.get("design_id"), "design_id")
    source = _exact_mapping(
        design.get("source_binding"), _SOURCE_FIELDS, "source binding"
    )
    normalized_source = {
        key: (
            _bounded(source.get(key), key)
            if key == "threshold"
            else _required_text(source.get(key), key)
            if key in {"execution_id", "model_revision", "profile_id"}
            else validate_hash_ref(source.get(key))
        )
        for key in sorted(_SOURCE_FIELDS)
    }
    if dict(_mapping(design.get("runtime_inventory"), "runtime inventory")) != (
        _EXPECTED_RUNTIME_INVENTORY
    ):
        raise _invalid("runtime_inventory")
    if dict(_mapping(design.get("readiness_policy"), "readiness policy")) != (
        _EXPECTED_READINESS_POLICY
    ):
        raise _invalid("readiness_policy")
    if dict(_mapping(design.get("rollout_boundary"), "rollout boundary")) != (
        _EXPECTED_ROLLOUT_BOUNDARY
    ):
        raise _invalid("rollout_boundary")
    if dict(_mapping(design.get("safety"), "safety")) != _EXPECTED_SAFETY:
        raise _invalid("safety")
    normalized = dict(design)
    normalized["source_binding"] = normalized_source
    normalized["design_hash"] = semantic_sha256_hash_ref(normalized)
    return normalized


def decide_answer_support_runtime_readiness(
    holdout_report: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Admit shadow integration from the consumed PASS receipt only."""
    normalized_design = validate_runtime_readiness_design(design)
    source = normalized_design["source_binding"]
    report = dict(_mapping(holdout_report, "holdout report"))
    terminal_receipt = dict(_mapping(receipt, "holdout receipt"))

    if semantic_sha256_hash_ref(report) != source["holdout_report_hash"]:
        raise _integrity("holdout_report")
    if semantic_sha256_hash_ref(terminal_receipt) != source["receipt_document_hash"]:
        raise _integrity("receipt_document")
    _validate_report_identity(report)
    _validate_receipt(terminal_receipt, source=source)
    if dict(_mapping(report.get("receipt"), "embedded receipt")) != terminal_receipt:
        raise _integrity("embedded_receipt")

    evaluation = _validate_evaluation(
        _mapping(report.get("evaluation"), "holdout evaluation"), source=source
    )
    _validate_report_counts(report, receipt=terminal_receipt)
    _validate_source_binding(report, evaluation=evaluation, source=source)
    _validate_admission(evaluation, policy=normalized_design["readiness_policy"])

    profile = {
        "profile_schema_version": RUNTIME_PROFILE_SCHEMA_VERSION,
        "profile_id": source["profile_id"],
        "profile_version": "1.0.0",
        "status": "READY_FOR_SHADOW",
        "policy_id": "cx_answer_support_contradiction_aware_ready_v2",
        "score_semantics": "WEIGHTED_BOUNDED_ORDINAL_NOT_PROBABILITY",
        "threshold": source["threshold"],
        "threshold_inclusive": True,
        "provider_binding": dict(evaluation["provider_binding"]),
        "request_profile_hash": source["request_profile_hash"],
        "dataset": {
            "dataset_id": evaluation["dataset"]["dataset_id"],
            "dataset_semantic_sha256": source["dataset_semantic_sha256"],
            "partition": "HOLDOUT",
        },
        "evidence_binding": {
            "execution_id": source["execution_id"],
            "authorization_hash": source["authorization_hash"],
            "receipt_hash": source["receipt_hash"],
            "evaluation_hash": source["evaluation_hash"],
        },
        "fallback_policy": normalized_design["rollout_boundary"][
            "fallback_policy"
        ],
        "runtime_activation_permitted": False,
    }
    profile["profile_hash"] = semantic_sha256_hash_ref(profile)

    checks = {
        "pass_receipt_integrity_verified": True,
        "one_shot_execution_identity_bound": True,
        "fixed_profile_and_threshold_preserved": True,
        "provider_and_dataset_binding_preserved": True,
        "frozen_holdout_constraints_passed": True,
        "holdout_reexecution_not_required": True,
        "direct_activation_blocked_by_runtime_gap": True,
        "shadow_first_and_rollback_boundary_defined": True,
        "current_runtime_behavior_unchanged": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": RUNTIME_READINESS_MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": READINESS_DECISION,
        "activation_status": ACTIVATION_STATUS,
        "design_hash": normalized_design["design_hash"],
        "candidate_profile": profile,
        "source_evidence": {
            "holdout_report_hash": source["holdout_report_hash"],
            "receipt_document_hash": source["receipt_document_hash"],
            "receipt_hash": source["receipt_hash"],
            "evaluation_hash": source["evaluation_hash"],
        },
        "rollout_boundary": dict(normalized_design["rollout_boundary"]),
        "checks": checks,
        "holdout_reexecution_permitted": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": "ANSWER_SUPPORT_SHADOW_EVALUATOR_AND_CANARY",
        "new_provider_calls": 0,
        "new_database_calls": 0,
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _validate_report_identity(report: Mapping[str, Any]) -> None:
    checks = _mapping(report.get("checks"), "holdout runner checks")
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpq_one_shot_holdout.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-Q"
        or report.get("status") != "PASS"
        or report.get("decision")
        != "HOLDOUT_EXECUTED_CANDIDATE_ADMITTED_SEPARATE_ACTIVATION_REQUIRED"
        or report.get("failed_checks") != []
        or report.get("runtime_activation_permitted") is not False
        or set(checks) != {
            "execution_id_preserved",
            "fixed_profile_preserved",
            "fixed_threshold_preserved",
            "holdout_candidate_count_complete",
            "holdout_package_count_complete",
            "one_shot_receipt_terminal",
            "provider_evaluations_exact",
            "provider_http_requests_exact",
            "runtime_activation_prohibited",
        }
        or any(value is not True for value in checks.values())
    ):
        raise _invalid("holdout_report")


def _validate_receipt(
    receipt: Mapping[str, Any], *, source: Mapping[str, Any]
) -> None:
    unsigned = dict(receipt)
    receipt_hash = validate_hash_ref(unsigned.pop("receipt_hash", None))
    if (
        semantic_sha256_hash_ref(unsigned) != receipt_hash
        or receipt_hash != source["receipt_hash"]
        or receipt.get("receipt_schema_version")
        != "cx_answer_support_holdout_receipt.v1"
        or receipt.get("status") != "PASS"
        or receipt.get("attempt_number") != 1
        or receipt.get("execution_id") != source["execution_id"]
        or receipt.get("authorization_hash") != source["authorization_hash"]
        or receipt.get("evaluation_hash") != source["evaluation_hash"]
        or receipt.get("provider_evaluation_count") != 40
        or receipt.get("provider_http_request_count") != 40
        or receipt.get("terminal_reason") is not None
    ):
        raise _integrity("receipt")


def _validate_evaluation(
    evaluation: Mapping[str, Any], *, source: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = dict(evaluation)
    evaluation_hash = validate_hash_ref(normalized.pop("evaluation_hash", None))
    checks = _mapping(normalized.get("checks"), "holdout evaluation checks")
    candidate = _mapping(normalized.get("candidate"), "candidate")
    if (
        semantic_sha256_hash_ref(normalized) != evaluation_hash
        or evaluation_hash != source["evaluation_hash"]
        or normalized.get("evaluation_schema_version")
        != "cx_answer_support_holdout_evaluation.v1"
        or normalized.get("status") != "HOLDOUT_ADMITTED"
        or normalized.get("terminal_status") != "PASS"
        or normalized.get("threshold_reselected") is not False
        or normalized.get("profile_reselected") is not False
        or normalized.get("runtime_activation_permitted") is not False
        or set(checks) != _REQUIRED_HOLDOUT_CHECKS
        or any(value is not True for value in checks.values())
        or candidate.get("profile_id") != source["profile_id"]
        or candidate.get("profile_hash") != source["canonical_profile_hash"]
        or _bounded(candidate.get("threshold"), "candidate.threshold")
        != source["threshold"]
    ):
        raise _integrity("evaluation")
    normalized["evaluation_hash"] = evaluation_hash
    return normalized


def _validate_report_counts(
    report: Mapping[str, Any], *, receipt: Mapping[str, Any]
) -> None:
    counts = _mapping(report.get("provider_http_request_counts"), "request counts")
    if (
        report.get("provider_evaluation_count") != 40
        or dict(counts) != {"generation": 40, "total": 40}
        or report.get("provider_evaluation_count")
        != receipt.get("provider_evaluation_count")
        or counts.get("generation") != receipt.get("provider_http_request_count")
    ):
        raise _invalid("provider_counts")


def _validate_source_binding(
    report: Mapping[str, Any],
    *,
    evaluation: Mapping[str, Any],
    source: Mapping[str, Any],
) -> None:
    collection = _mapping(report.get("collection"), "holdout collection")
    dataset = _mapping(evaluation.get("dataset"), "evaluation dataset")
    if (
        report.get("execution_id") != source["execution_id"]
        or report.get("authorization_hash") != source["authorization_hash"]
        or collection.get("request_profile_hash") != source["request_profile_hash"]
        or dataset.get("dataset_sha256") != source["dataset_semantic_sha256"]
        or evaluation.get("provider_binding") != collection.get("provider_binding")
        or _mapping(evaluation.get("provider_binding"), "provider binding").get(
            "model_revision"
        )
        != source["model_revision"]
    ):
        raise _invalid("source_binding")


def _validate_admission(
    evaluation: Mapping[str, Any], *, policy: Mapping[str, Any]
) -> None:
    metrics = _mapping(evaluation.get("metrics"), "holdout metrics")
    if (
        metrics.get("false_ready_rate") > policy["maximum_false_ready_rate"]
        or metrics.get("ready_recall") < policy["minimum_ready_recall"]
        or evaluation.get("package_auc") < policy["minimum_package_auc"]
    ):
        raise AnswerSupportRuntimeReadinessError(
            "cx.answer_support_runtime_readiness.holdout_not_admitted",
            "The frozen HOLDOUT metrics do not satisfy runtime readiness.",
        )


def _exact_mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    normalized = _mapping(value, name)
    if set(normalized) != fields:
        raise _invalid(name)
    return normalized


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(name)
    return value.strip()


def _bounded(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(name)
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise _invalid(name)
    return numeric


def _invalid(name: str) -> AnswerSupportRuntimeReadinessError:
    return AnswerSupportRuntimeReadinessError(
        "cx.answer_support_runtime_readiness.contract_invalid",
        f"{name} is invalid.",
    )


def _integrity(name: str) -> AnswerSupportRuntimeReadinessError:
    return AnswerSupportRuntimeReadinessError(
        "cx.answer_support_runtime_readiness.integrity_invalid",
        f"{name} integrity validation failed.",
    )
