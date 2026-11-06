from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.retrieval_answer_support_controlled_activation import (
    validate_controlled_activation_bundle,
)
from nex_cx.retrieval_answer_support_extended_review import (
    DECISION as REVIEW_DECISION,
)

DESIGN_SCHEMA_VERSION = "cx_answer_support_policy_cutover_decision_design.v1"
OPERATOR_DECISION_SCHEMA_VERSION = (
    "cx_answer_support_policy_cutover_operator_decision.v1"
)
MANIFEST_SCHEMA_VERSION = "cx_answer_support_policy_cutover_decision_manifest.v1"
DECISION = "CONTROLLED_ANSWER_SUPPORT_POLICY_CUTOVER_APPROVED"
DECISION_STATUS = "APPROVED_NOT_EXECUTED"
APPROVED_SCOPE = "CONTROLLED_ANSWER_SUPPORT_USER_VISIBLE_POLICY_CUTOVER"
NEXT_BOUNDARY = "ANSWER_SUPPORT_POLICY_CUTOVER_AND_ROLLBACK_ACCEPTANCE"
CURRENT_POLICY = "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "decision_policy",
    "cutover_boundary",
    "rollback_policy",
    "safety",
}
_SOURCE_FIELDS = {
    "review_design_hash",
    "review_operator_decision_hash",
    "review_manifest_hash",
    "review_receipt_hash",
    "review_receipt_document_hash",
    "review_report_document_hash",
    "extended_operations_evidence_hash",
    "activation_bundle_hash",
    "activation_bundle_document_hash",
    "selected_policy_hash",
    "provider_binding_hash",
    "readiness_manifest_hash",
}
_DECISION_POLICY = {
    "required_review_status": "PASS",
    "required_review_decision": REVIEW_DECISION,
    "required_review_decision_status": "APPROVED_NOT_EXECUTED",
    "required_review_scope": "ANSWER_SUPPORT_POLICY_CUTOVER_REVIEW_ONLY",
    "required_candidate_status": "ADMITTED_PENDING_SEPARATE_CUTOVER_DECISION",
    "required_extended_sample_count": 30,
    "required_peak_in_flight": 4,
    "maximum_provider_p95_latency_ms": 15000,
    "maximum_e2e_p95_latency_ms": 20000,
    "automatic_cutover_permitted": False,
    "operator_decision_required": True,
}
_CUTOVER_BOUNDARY = {
    "approved_scope": APPROVED_SCOPE,
    "decision_status": DECISION_STATUS,
    "current_policy": CURRENT_POLICY,
    "fallback_policy": CURRENT_POLICY,
    "rollback_target": CURRENT_POLICY,
    "cutover_requires_installed_acceptance": True,
    "cutover_execution_permitted_in_this_slice": False,
    "next_boundary": NEXT_BOUNDARY,
}
_ROLLBACK_POLICY = {
    "source_binding_drift": "IMMEDIATE_ROLLBACK",
    "provider_error": "IMMEDIATE_ROLLBACK",
    "progress_sink_failure": "IMMEDIATE_ROLLBACK",
    "feedback_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "provider_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "interactive_e2e_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "non_retryable_overload": "IMMEDIATE_ROLLBACK",
}
_SAFETY = {
    "provider_call_permitted": False,
    "database_call_permitted": False,
    "holdout_access_permitted": False,
    "runtime_change_permitted": False,
    "cutover_execution_permitted": False,
    "production_cutover_permitted": False,
}
_RECEIPT_FIELDS = {
    "receipt_schema_version",
    "status",
    "decision",
    "decision_status",
    "design_hash",
    "operator_decision_hash",
    "manifest_hash",
    "source_evidence_hash",
    "source_report_document_hash",
    "approved_scope",
    "next_boundary",
    "decided_at",
    "cutover_review_approved",
    "cutover_executed",
    "runtime_changed",
    "user_visible_decision_change_permitted",
    "production_cutover_permitted",
    "receipt_hash",
}
_REPORT_FIELDS = {
    "activation_bundle_hash",
    "approved_scope",
    "candidate_policy_status",
    "checks",
    "current_policy",
    "cutover_execution_permitted",
    "cutover_review_permitted",
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
    "operations_policy_hash",
    "operator_decision_hash",
    "production_cutover_permitted",
    "provider_calls",
    "reason_codes",
    "runtime_change_permitted",
    "slice_id",
    "source_evidence_hash",
    "source_report_document_hash",
    "source_window_id",
    "status",
    "user_visible_decision_change_permitted",
}
_REQUIRED_REVIEW_CHECKS = {
    "source_report_integrity_verified",
    "exact_extended_window_binding_verified",
    "prior_operator_authorization_verified",
    "sample_cap_and_restart_safety_verified",
    "zero_provider_failure_evidence_verified",
    "provider_p95_slo_verified",
    "e2e_p95_slo_verified",
    "bounded_c4_profile_verified",
    "cutover_review_scope_verified",
    "cutover_not_executed",
    "runtime_unchanged",
    "current_user_policy_unchanged",
    "production_cutover_prohibited",
}
_METRIC_FIELDS = {
    "sample_count",
    "provider_call_count",
    "provider_p95_latency_ms",
    "e2e_p95_latency_ms",
    "peak_in_flight",
    "test_database_residue_rows",
}
_OPERATOR_FIELDS = {
    "decision_schema_version",
    "status",
    "decision",
    "operator_id",
    "decided_at",
    "design_hash",
    "source_review_receipt_hash",
    "selected_policy_hash",
    "approved_scope",
    "reason_codes",
    "policy_cutover_approved",
    "policy_cutover_executed",
    "runtime_changed",
    "production_cutover_approved",
    "decision_hash",
}
_REASON_CODES = (
    "ONE_SHOT_HOLDOUT_AND_E2E_ADMISSION_PRESERVED",
    "CONTROLLED_SHADOW_AND_ROLLBACK_ACCEPTED",
    "EXTENDED_THIRTY_SAMPLE_WINDOW_COMPLETE",
    "ZERO_PROVIDER_FAILURES_AND_SLOS_MET",
    "RESTART_SAFE_CAP_AND_ZERO_RESIDUE_VERIFIED",
    "SEPARATE_INSTALLED_CUTOVER_ACCEPTANCE_REQUIRED",
)


class PolicyCutoverDecisionError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_policy_cutover_decision_design(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    design = dict(_mapping(value, "design"))
    supplied_hash = design.pop("design_hash", None)
    _exact(design, _DESIGN_FIELDS, "design")
    if (
        design.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_OPERATOR_DECISION"
        or not _text(design.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(design.get("source_binding"), _SOURCE_FIELDS, "source_binding")
    design["source_binding"] = {
        key: _hash_ref(source.get(key), key) for key in sorted(_SOURCE_FIELDS)
    }
    for field, expected in (
        ("decision_policy", _DECISION_POLICY),
        ("cutover_boundary", _CUTOVER_BOUNDARY),
        ("rollback_policy", _ROLLBACK_POLICY),
        ("safety", _SAFETY),
    ):
        if dict(_mapping(design.get(field), field)) != expected:
            raise _invalid(field)
    calculated = semantic_sha256_hash_ref(design)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated
    ):
        raise _integrity("design")
    design["design_hash"] = calculated
    return design


def build_policy_cutover_operator_decision(
    *,
    operator_id: str,
    decided_at: str,
    design: Mapping[str, Any],
    review_receipt: Mapping[str, Any],
    review_report: Mapping[str, Any],
    activation_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_policy_cutover_decision_design(design)
    evidence = _assess_evidence(
        normalized,
        review_receipt=review_receipt,
        review_report=review_report,
        activation_bundle=activation_bundle,
    )
    decision: dict[str, Any] = {
        "decision_schema_version": OPERATOR_DECISION_SCHEMA_VERSION,
        "status": "DECIDED",
        "decision": DECISION,
        "operator_id": _required_text(operator_id, "operator_id"),
        "decided_at": _timestamp(decided_at, "decided_at"),
        "design_hash": normalized["design_hash"],
        "source_review_receipt_hash": evidence["review_receipt_hash"],
        "selected_policy_hash": evidence["selected_policy_hash"],
        "approved_scope": APPROVED_SCOPE,
        "reason_codes": list(_REASON_CODES),
        "policy_cutover_approved": True,
        "policy_cutover_executed": False,
        "runtime_changed": False,
        "production_cutover_approved": False,
    }
    decision["decision_hash"] = semantic_sha256_hash_ref(decision)
    return decision


def decide_policy_cutover(
    *,
    design: Mapping[str, Any],
    review_receipt: Mapping[str, Any],
    review_report: Mapping[str, Any],
    activation_bundle: Mapping[str, Any],
    operator_decision: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_policy_cutover_decision_design(design)
    evidence = _assess_evidence(
        normalized,
        review_receipt=review_receipt,
        review_report=review_report,
        activation_bundle=activation_bundle,
    )
    operator = _validate_operator_decision(
        operator_decision, design=normalized, evidence=evidence
    )
    checks = {
        "review_receipt_integrity_verified": True,
        "review_report_integrity_verified": True,
        "extended_operations_evidence_verified": True,
        "activation_bundle_integrity_verified": True,
        "selected_policy_binding_verified": True,
        "provider_binding_verified": True,
        "readiness_and_holdout_lineage_preserved": True,
        "extended_operational_slos_verified": True,
        "fallback_and_rollback_preserved": True,
        "operator_cutover_scope_verified": True,
        "cutover_not_executed": True,
        "runtime_unchanged": True,
        "production_cutover_prohibited": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": DECISION,
        "decision_status": DECISION_STATUS,
        "design_hash": normalized["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "source_review_receipt_hash": evidence["review_receipt_hash"],
        "source_review_manifest_hash": evidence["review_manifest_hash"],
        "source_extended_operations_evidence_hash": evidence[
            "extended_operations_evidence_hash"
        ],
        "activation_bundle_hash": evidence["activation_bundle_hash"],
        "selected_policy_hash": evidence["selected_policy_hash"],
        "provider_binding_hash": evidence["provider_binding_hash"],
        "approved_scope": APPROVED_SCOPE,
        "observed_metrics": evidence["metrics"],
        "reason_codes": list(_REASON_CODES),
        "checks": checks,
        "failed_checks": [],
        "fallback_policy": CURRENT_POLICY,
        "rollback_target": CURRENT_POLICY,
        "rollback_policy": dict(_ROLLBACK_POLICY),
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "policy_cutover_permitted": True,
        "policy_cutover_executed": False,
        "runtime_change_executed": False,
        "user_visible_policy_change_approved": True,
        "user_visible_policy_change_executed": False,
        "production_cutover_permitted": False,
        "current_policy": CURRENT_POLICY,
        "next_boundary": NEXT_BOUNDARY,
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _assess_evidence(
    design: Mapping[str, Any],
    *,
    review_receipt: Mapping[str, Any],
    review_report: Mapping[str, Any],
    activation_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    source = design["source_binding"]
    receipt = _validate_review_receipt(review_receipt)
    report = _validate_review_report(review_report, receipt=receipt)
    bundle = validate_controlled_activation_bundle(activation_bundle)
    if (
        semantic_sha256_hash_ref(receipt) != source["review_receipt_document_hash"]
        or semantic_sha256_hash_ref(report) != source["review_report_document_hash"]
        or semantic_sha256_hash_ref(bundle) != source["activation_bundle_document_hash"]
        or receipt["design_hash"] != source["review_design_hash"]
        or receipt["operator_decision_hash"] != source["review_operator_decision_hash"]
        or receipt["manifest_hash"] != source["review_manifest_hash"]
        or receipt["receipt_hash"] != source["review_receipt_hash"]
        or receipt["source_evidence_hash"]
        != source["extended_operations_evidence_hash"]
        or bundle["bundle_hash"] != source["activation_bundle_hash"]
        or bundle["selected_policy"]["policy_hash"] != source["selected_policy_hash"]
        or bundle["source_binding"]["provider_binding_hash"]
        != source["provider_binding_hash"]
        or bundle["readiness_manifest"]["manifest_hash"]
        != source["readiness_manifest_hash"]
    ):
        raise _integrity("source_binding")
    metrics = dict(_exact(report.get("observed_metrics"), _METRIC_FIELDS, "metrics"))
    policy = design["decision_policy"]
    if (
        report.get("status") != policy["required_review_status"]
        or report.get("decision") != policy["required_review_decision"]
        or report.get("decision_status") != policy["required_review_decision_status"]
        or report.get("approved_scope") != policy["required_review_scope"]
        or report.get("candidate_policy_status") != policy["required_candidate_status"]
        or metrics.get("sample_count") != policy["required_extended_sample_count"]
        or metrics.get("provider_call_count")
        != policy["required_extended_sample_count"]
        or metrics.get("peak_in_flight") != policy["required_peak_in_flight"]
        or metrics.get("provider_p95_latency_ms")
        > policy["maximum_provider_p95_latency_ms"]
        or metrics.get("e2e_p95_latency_ms") > policy["maximum_e2e_p95_latency_ms"]
        or metrics.get("test_database_residue_rows") != 0
    ):
        raise _invalid("review_evidence")
    return {
        "review_receipt_hash": receipt["receipt_hash"],
        "review_manifest_hash": receipt["manifest_hash"],
        "extended_operations_evidence_hash": receipt["source_evidence_hash"],
        "activation_bundle_hash": bundle["bundle_hash"],
        "selected_policy_hash": bundle["selected_policy"]["policy_hash"],
        "provider_binding_hash": bundle["source_binding"]["provider_binding_hash"],
        "metrics": metrics,
    }


def _validate_review_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    receipt = dict(_exact(value, _RECEIPT_FIELDS, "review_receipt"))
    receipt_hash = _hash_ref(receipt.pop("receipt_hash", None), "receipt_hash")
    if semantic_sha256_hash_ref(receipt) != receipt_hash:
        raise _integrity("review_receipt")
    receipt["receipt_hash"] = receipt_hash
    if (
        receipt.get("receipt_schema_version")
        != "cx_answer_support_extended_shadow_operator_review_receipt.v1"
        or receipt.get("status") != "PASS"
        or receipt.get("decision") != REVIEW_DECISION
        or receipt.get("decision_status") != "APPROVED_NOT_EXECUTED"
        or receipt.get("approved_scope") != "ANSWER_SUPPORT_POLICY_CUTOVER_REVIEW_ONLY"
        or receipt.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATOR_DECISION"
        or receipt.get("cutover_review_approved") is not True
        or receipt.get("cutover_executed") is not False
        or receipt.get("runtime_changed") is not False
        or receipt.get("user_visible_decision_change_permitted") is not False
        or receipt.get("production_cutover_permitted") is not False
    ):
        raise _invalid("review_receipt")
    for field in (
        "design_hash",
        "operator_decision_hash",
        "manifest_hash",
        "source_evidence_hash",
        "source_report_document_hash",
    ):
        _hash_ref(receipt.get(field), field)
    _timestamp(receipt.get("decided_at"), "decided_at")
    return receipt


def _validate_review_report(
    value: Mapping[str, Any], *, receipt: Mapping[str, Any]
) -> dict[str, Any]:
    report = dict(_exact(value, _REPORT_FIELDS, "review_report"))
    checks = _exact(report.get("checks"), _REQUIRED_REVIEW_CHECKS, "review_checks")
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpae_extended_shadow_operator_review.v1"
        or report.get("manifest_schema_version")
        != "cx_answer_support_extended_shadow_review_manifest.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-AE"
        or report.get("decision_receipt_hash") != receipt["receipt_hash"]
        or report.get("design_hash") != receipt["design_hash"]
        or report.get("operator_decision_hash") != receipt["operator_decision_hash"]
        or report.get("manifest_hash") != receipt["manifest_hash"]
        or report.get("source_evidence_hash") != receipt["source_evidence_hash"]
        or report.get("source_report_document_hash")
        != receipt["source_report_document_hash"]
        or report.get("failed_checks") != []
        or any(item is not True for item in checks.values())
        or report.get("provider_calls") != 0
        or report.get("database_calls") != 0
        or report.get("holdout_accessed") is not False
        or report.get("cutover_review_permitted") is not True
        or report.get("cutover_execution_permitted") is not False
        or report.get("runtime_change_permitted") is not False
        or report.get("user_visible_decision_change_permitted") is not False
        or report.get("production_cutover_permitted") is not False
        or report.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATOR_DECISION"
    ):
        raise _invalid("review_report")
    return report


def _validate_operator_decision(
    value: Mapping[str, Any], *, design: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    decision = dict(_exact(value, _OPERATOR_FIELDS, "operator_decision"))
    decision_hash = _hash_ref(decision.pop("decision_hash", None), "decision_hash")
    if semantic_sha256_hash_ref(decision) != decision_hash:
        raise _integrity("operator_decision")
    decision["decision_hash"] = decision_hash
    if (
        decision.get("decision_schema_version") != OPERATOR_DECISION_SCHEMA_VERSION
        or decision.get("status") != "DECIDED"
        or decision.get("decision") != DECISION
        or decision.get("design_hash") != design["design_hash"]
        or decision.get("source_review_receipt_hash") != evidence["review_receipt_hash"]
        or decision.get("selected_policy_hash") != evidence["selected_policy_hash"]
        or decision.get("approved_scope") != APPROVED_SCOPE
        or decision.get("reason_codes") != list(_REASON_CODES)
        or decision.get("policy_cutover_approved") is not True
        or decision.get("policy_cutover_executed") is not False
        or decision.get("runtime_changed") is not False
        or decision.get("production_cutover_approved") is not False
    ):
        raise _invalid("operator_decision")
    _required_text(decision.get("operator_id"), "operator_id")
    _timestamp(decision.get("decided_at"), "decided_at")
    return decision


def _timestamp(value: object, name: str) -> str:
    text = _required_text(value, name)
    if not text.endswith("Z"):
        raise _invalid(name)
    try:
        datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise _invalid(name) from exc
    return text


def _required_text(value: object, name: str) -> str:
    if not _text(value):
        raise _invalid(name)
    return str(value).strip()


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _exact(value: object, expected: set[str], name: str) -> Mapping[str, Any]:
    mapping = _mapping(value, name)
    if set(mapping) != expected:
        raise _invalid(f"{name}_fields")
    return mapping


def _hash_ref(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(name)
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(name) from exc


def _invalid(detail: str) -> PolicyCutoverDecisionError:
    return PolicyCutoverDecisionError("CX_POLICY_CUTOVER_DECISION_INVALID", detail)


def _integrity(detail: str) -> PolicyCutoverDecisionError:
    return PolicyCutoverDecisionError("CX_POLICY_CUTOVER_DECISION_INTEGRITY", detail)
