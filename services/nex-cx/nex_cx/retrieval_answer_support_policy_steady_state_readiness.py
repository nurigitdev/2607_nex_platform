from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = "cx_answer_support_policy_steady_state_readiness_design.v1"
MANIFEST_SCHEMA_VERSION = (
    "cx_answer_support_policy_steady_state_readiness_manifest.v1"
)
PROFILE_SCHEMA_VERSION = "cx_answer_support_policy_steady_state_operations_profile.v1"
READINESS_DECISION = "READY_FOR_ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATOR_DECISION"
ACTIVATION_STATUS = "NOT_ACTIVATED"
NEXT_BOUNDARY = "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_OPERATOR_DECISION"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "readiness_policy",
    "operations_profile",
    "rollout_boundary",
    "safety",
}
_SOURCE_FIELDS = {
    "review_report_hash",
    "review_receipt_document_hash",
    "review_receipt_hash",
    "review_design_hash",
    "operator_decision_hash",
    "review_manifest_hash",
    "source_evidence_hash",
    "sustained_policy_hash",
    "authorization_hash",
    "activation_bundle_hash",
    "selected_policy_hash",
}
_READINESS_POLICY = {
    "required_review_status": "PASS",
    "required_review_decision": (
        "CONTINUE_CONTROLLED_ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS_APPROVED"
    ),
    "required_decision_status": "APPROVED_CONTINUATION_NOT_PRODUCTION",
    "required_provider_sample_count": 12,
    "required_provider_call_count": 12,
    "required_peak_in_flight": 4,
    "minimum_ready_count": 1,
    "maximum_provider_p95_latency_ms": 15000,
    "maximum_e2e_p95_latency_ms": 20000,
    "required_runtime_change_permitted": False,
    "required_steady_state_activation_permitted": False,
    "required_production_cutover_permitted": False,
}
_OPERATIONS_PROFILE = {
    "profile_schema_version": PROFILE_SCHEMA_VERSION,
    "profile_id": "cx-answer-support-policy-steady-state-operations-v1",
    "status": "READY_FOR_OPERATOR_DECISION",
    "current_policy": "ANSWER_SUPPORT_POLICY_CUTOVER_ACTIVE",
    "current_operations_mode": "CONTROLLED_SUSTAINED_OPERATIONS",
    "review_sample_interval": 12,
    "maximum_concurrency": 4,
    "maximum_event_scan": 1000,
    "operational_slo": {
        "maximum_feedback_p95_latency_ms": 2000,
        "maximum_provider_p95_latency_ms": 15000,
        "maximum_e2e_p95_latency_ms": 20000,
        "maximum_provider_failures": 0,
        "maximum_fallback_count": 0,
    },
    "escalation_policy": {
        "cutover_terminal_state": "ROLLBACK_STATE_DOMINANT",
        "provider_failure": "IMMEDIATE_ROLLBACK_REQUIRED",
        "fallback_decision": "IMMEDIATE_ROLLBACK_REQUIRED",
        "provider_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
        "e2e_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
        "review_cadence_reached": "OPERATOR_REVIEW_REQUIRED",
    },
}
_ROLLOUT_BOUNDARY = {
    "steady_state_activation_requires_separate_operator_decision": True,
    "production_release_requires_separate_decision": True,
    "current_runtime_continues_unchanged": True,
    "rollback_contract_remains_authoritative": True,
    "fallback_policy": "CURRENT_ANSWER_SUPPORT_POLICY_FALLBACK",
    "rollback_target": "CURRENT_CONTROLLED_ANSWER_SUPPORT_POLICY",
    "next_boundary": NEXT_BOUNDARY,
}
_SAFETY = {
    "provider_call_permitted": False,
    "database_call_permitted": False,
    "holdout_access_permitted": False,
    "runtime_mutation_permitted": False,
    "steady_state_activation_permitted": False,
    "production_cutover_permitted": False,
    "threshold_or_profile_reselection_permitted": False,
}
_REPORT_FIELDS = {
    "activation_bundle_hash",
    "approved_scope",
    "authorization_hash",
    "checks",
    "continuation_receipt_hash",
    "controlled_continuation_permitted",
    "current_operations_mode",
    "current_policy",
    "database_calls",
    "decision",
    "decision_receipt_hash",
    "decision_status",
    "design_hash",
    "evidence_schema_version",
    "failed_checks",
    "holdout_accessed",
    "manifest_hash",
    "manifest_schema_version",
    "next_boundary",
    "observed_metrics",
    "operator_decision_hash",
    "production_cutover_permitted",
    "provider_calls",
    "reason_codes",
    "rollback_contract_preserved",
    "runtime_change_permitted",
    "selected_policy_hash",
    "slice_id",
    "source_evidence_hash",
    "source_report_document_hash",
    "status",
    "steady_state_activation_permitted",
    "sustained_policy_hash",
}
_RECEIPT_FIELDS = {
    "approved_scope",
    "decided_at",
    "decision",
    "decision_status",
    "design_hash",
    "manifest_hash",
    "next_boundary",
    "operator_decision_hash",
    "production_cutover_permitted",
    "receipt_hash",
    "receipt_schema_version",
    "rollback_contract_preserved",
    "runtime_changed",
    "source_evidence_hash",
    "source_report_document_hash",
    "status",
    "steady_state_activation_permitted",
    "sustained_operations_continuation_approved",
}
_REVIEW_CHECKS = {
    "bounded_c4_profile_verified",
    "controlled_continuation_scope_verified",
    "e2e_p95_slo_verified",
    "exact_continuation_receipt_binding_verified",
    "exact_sustained_policy_binding_verified",
    "permission_and_evidence_preservation_verified",
    "production_cutover_prohibited",
    "provider_p95_slo_verified",
    "restart_recovery_verified",
    "rollback_contract_preserved",
    "runtime_continued_at_review_cadence",
    "runtime_unchanged",
    "source_report_integrity_verified",
    "steady_state_activation_prohibited",
    "sustained_cadence_complete",
    "test_database_zero_residue_verified",
    "zero_provider_failure_or_fallback_verified",
}
_METRIC_FIELDS = {
    "sample_count",
    "provider_call_count",
    "peak_in_flight",
    "ready_count",
    "low_confidence_count",
    "feedback_p95_latency_ms",
    "provider_p95_latency_ms",
    "e2e_p95_latency_ms",
    "elapsed_seconds",
}


class PolicySteadyStateReadinessError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_policy_steady_state_readiness_design(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    design = dict(_mapping(value, "design"))
    supplied_hash = design.pop("design_hash", None)
    _exact(design, _DESIGN_FIELDS, "design")
    if (
        design.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_PRE_ACTIVATION_READINESS"
        or not _text(design.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(design.get("source_binding"), _SOURCE_FIELDS, "source_binding")
    design["source_binding"] = {
        name: _hash_ref(source.get(name), name) for name in _SOURCE_FIELDS
    }
    for field, expected in (
        ("readiness_policy", _READINESS_POLICY),
        ("operations_profile", _OPERATIONS_PROFILE),
        ("rollout_boundary", _ROLLOUT_BOUNDARY),
        ("safety", _SAFETY),
    ):
        if dict(_mapping(design.get(field), field)) != expected:
            raise _invalid(field)
    calculated = semantic_sha256_hash_ref(design)
    if supplied_hash is not None and _hash_ref(supplied_hash, "design_hash") != calculated:
        raise _integrity("design")
    design["design_hash"] = calculated
    return design


def decide_policy_steady_state_operations_readiness(
    review_report: Mapping[str, Any],
    review_receipt: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_policy_steady_state_readiness_design(design)
    report = _validate_review_report(review_report, design=normalized)
    receipt = _validate_review_receipt(review_receipt, design=normalized)
    _validate_cross_binding(report, receipt=receipt, design=normalized)

    profile = dict(normalized["operations_profile"])
    profile["source_binding"] = {
        "review_report_hash": normalized["source_binding"]["review_report_hash"],
        "review_receipt_hash": normalized["source_binding"]["review_receipt_hash"],
        "sustained_policy_hash": normalized["source_binding"][
            "sustained_policy_hash"
        ],
        "selected_policy_hash": normalized["source_binding"]["selected_policy_hash"],
    }
    profile["runtime_activation_permitted"] = False
    profile["profile_hash"] = semantic_sha256_hash_ref(profile)

    checks = {
        "operator_review_report_integrity_verified": True,
        "operator_review_receipt_integrity_verified": True,
        "exact_review_lineage_bound": True,
        "sustained_cadence_and_slos_verified": True,
        "restart_and_zero_residue_verified": True,
        "rollback_contract_preserved": True,
        "current_runtime_unchanged": True,
        "holdout_reexecution_prohibited": True,
        "steady_state_activation_prohibited": True,
        "production_cutover_prohibited": True,
        "separate_operator_decision_required": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": READINESS_DECISION,
        "activation_status": ACTIVATION_STATUS,
        "design_hash": normalized["design_hash"],
        "operations_profile": profile,
        "source_evidence": {
            "review_report_hash": normalized["source_binding"][
                "review_report_hash"
            ],
            "review_receipt_document_hash": normalized["source_binding"][
                "review_receipt_document_hash"
            ],
            "review_receipt_hash": normalized["source_binding"][
                "review_receipt_hash"
            ],
            "operator_decision_hash": normalized["source_binding"][
                "operator_decision_hash"
            ],
            "source_evidence_hash": normalized["source_binding"][
                "source_evidence_hash"
            ],
        },
        "observed_metrics": dict(report["observed_metrics"]),
        "rollout_boundary": dict(normalized["rollout_boundary"]),
        "checks": checks,
        "failed_checks": [],
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_change_permitted": False,
        "steady_state_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": NEXT_BOUNDARY,
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _validate_review_report(
    value: Mapping[str, Any], *, design: Mapping[str, Any]
) -> dict[str, Any]:
    report = dict(_exact(value, _REPORT_FIELDS, "review_report"))
    source = design["source_binding"]
    if semantic_sha256_hash_ref(report) != source["review_report_hash"]:
        raise _integrity("review_report")
    manifest = dict(report)
    manifest.pop("evidence_schema_version")
    manifest.pop("slice_id")
    manifest.pop("decision_receipt_hash")
    manifest_hash = _hash_ref(manifest.pop("manifest_hash"), "manifest_hash")
    if (
        semantic_sha256_hash_ref(manifest) != manifest_hash
        or manifest_hash != source["review_manifest_hash"]
    ):
        raise _integrity("review_manifest")

    checks = _exact(report.get("checks"), _REVIEW_CHECKS, "review_checks")
    metrics = dict(_exact(report.get("observed_metrics"), _METRIC_FIELDS, "metrics"))
    for name in (
        "sample_count",
        "provider_call_count",
        "peak_in_flight",
        "ready_count",
        "low_confidence_count",
    ):
        if not _nonnegative_int(metrics.get(name)):
            raise _invalid("metrics")
    for name in (
        "feedback_p95_latency_ms",
        "provider_p95_latency_ms",
        "e2e_p95_latency_ms",
        "elapsed_seconds",
    ):
        if not _nonnegative_number(metrics.get(name)):
            raise _invalid("metrics")

    policy = design["readiness_policy"]
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpak_answer_support_policy_sustained_operations_operator_review.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-AK"
        or report.get("status") != policy["required_review_status"]
        or report.get("decision") != policy["required_review_decision"]
        or report.get("decision_status") != policy["required_decision_status"]
        or report.get("failed_checks") != []
        or any(result is not True for result in checks.values())
        or report.get("provider_calls") != 0
        or report.get("database_calls") != 0
        or report.get("holdout_accessed") is not False
        or report.get("runtime_change_permitted")
        is not policy["required_runtime_change_permitted"]
        or report.get("steady_state_activation_permitted")
        is not policy["required_steady_state_activation_permitted"]
        or report.get("production_cutover_permitted")
        is not policy["required_production_cutover_permitted"]
        or report.get("rollback_contract_preserved") is not True
        or report.get("controlled_continuation_permitted") is not True
        or report.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_READINESS"
        or metrics["sample_count"] != policy["required_provider_sample_count"]
        or metrics["provider_call_count"] != policy["required_provider_call_count"]
        or metrics["peak_in_flight"] != policy["required_peak_in_flight"]
        or metrics["ready_count"] < policy["minimum_ready_count"]
        or metrics["ready_count"] + metrics["low_confidence_count"]
        != metrics["sample_count"]
        or metrics["provider_p95_latency_ms"]
        > policy["maximum_provider_p95_latency_ms"]
        or metrics["e2e_p95_latency_ms"] > policy["maximum_e2e_p95_latency_ms"]
    ):
        raise _invalid("review_report_boundary")
    return report


def _validate_review_receipt(
    value: Mapping[str, Any], *, design: Mapping[str, Any]
) -> dict[str, Any]:
    receipt = dict(_exact(value, _RECEIPT_FIELDS, "review_receipt"))
    source = design["source_binding"]
    if semantic_sha256_hash_ref(receipt) != source["review_receipt_document_hash"]:
        raise _integrity("review_receipt_document")
    unsigned = dict(receipt)
    receipt_hash = _hash_ref(unsigned.pop("receipt_hash"), "receipt_hash")
    if (
        semantic_sha256_hash_ref(unsigned) != receipt_hash
        or receipt_hash != source["review_receipt_hash"]
        or receipt.get("receipt_schema_version")
        != "cx_answer_support_policy_sustained_operations_operator_review_receipt.v1"
        or receipt.get("status") != "PASS"
        or receipt.get("decision") != _READINESS_POLICY["required_review_decision"]
        or receipt.get("decision_status")
        != _READINESS_POLICY["required_decision_status"]
        or receipt.get("sustained_operations_continuation_approved") is not True
        or receipt.get("runtime_changed") is not False
        or receipt.get("rollback_contract_preserved") is not True
        or receipt.get("steady_state_activation_permitted") is not False
        or receipt.get("production_cutover_permitted") is not False
        or receipt.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_READINESS"
    ):
        raise _integrity("review_receipt")
    return receipt


def _validate_cross_binding(
    report: Mapping[str, Any],
    *,
    receipt: Mapping[str, Any],
    design: Mapping[str, Any],
) -> None:
    source = design["source_binding"]
    if (
        report.get("decision_receipt_hash") != source["review_receipt_hash"]
        or report.get("design_hash") != source["review_design_hash"]
        or report.get("operator_decision_hash") != source["operator_decision_hash"]
        or report.get("manifest_hash") != source["review_manifest_hash"]
        or report.get("source_evidence_hash") != source["source_evidence_hash"]
        or report.get("sustained_policy_hash") != source["sustained_policy_hash"]
        or report.get("authorization_hash") != source["authorization_hash"]
        or report.get("activation_bundle_hash") != source["activation_bundle_hash"]
        or report.get("selected_policy_hash") != source["selected_policy_hash"]
        or receipt.get("design_hash") != report.get("design_hash")
        or receipt.get("operator_decision_hash")
        != report.get("operator_decision_hash")
        or receipt.get("manifest_hash") != report.get("manifest_hash")
        or receipt.get("source_evidence_hash") != report.get("source_evidence_hash")
        or receipt.get("source_report_document_hash")
        != report.get("source_report_document_hash")
    ):
        raise _integrity("review_cross_binding")


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _hash_ref(value: object, name: str) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(name) from exc


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _exact(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    normalized = _mapping(value, name)
    if set(normalized) != fields:
        raise _invalid(name)
    return normalized


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _nonnegative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) >= 0
    )


def _invalid(name: str) -> PolicySteadyStateReadinessError:
    return PolicySteadyStateReadinessError(
        "POLICY_STEADY_STATE_READINESS_INVALID", f"{name} is invalid"
    )


def _integrity(name: str) -> PolicySteadyStateReadinessError:
    return PolicySteadyStateReadinessError(
        "POLICY_STEADY_STATE_READINESS_INTEGRITY", f"{name} integrity failed"
    )
