from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_policy_cutover_operations_review_design.v1"
)
OPERATOR_DECISION_SCHEMA_VERSION = (
    "cx_answer_support_policy_cutover_operations_operator_decision.v1"
)
MANIFEST_SCHEMA_VERSION = (
    "cx_answer_support_policy_cutover_operations_review_manifest.v1"
)
DECISION = "CONTINUE_CONTROLLED_ANSWER_SUPPORT_POLICY_OPERATIONS_APPROVED"
DECISION_STATUS = "APPROVED_CONTINUATION_NOT_PRODUCTION"
APPROVED_SCOPE = "CONTROLLED_ANSWER_SUPPORT_POLICY_OPERATIONS_CONTINUATION_ONLY"
NEXT_BOUNDARY = "ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS"
CURRENT_POLICY = "ANSWER_SUPPORT_POLICY_CUTOVER_ACTIVE"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "review_policy",
    "decision_boundary",
    "safety",
}
_SOURCE_FIELDS = {
    "activation_bundle_hash",
    "authorization_hash",
    "selected_policy_hash",
    "operations_policy_hash",
    "source_evidence_hash",
    "source_report_document_hash",
}
_REVIEW_POLICY = {
    "required_source_status": "PASS",
    "required_source_decision": "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_ACCEPTED",
    "required_operations_status": "REVIEW_REQUIRED",
    "required_provider_sample_count": 12,
    "required_provider_call_count": 12,
    "required_peak_in_flight": 4,
    "minimum_ready_count": 1,
    "maximum_provider_p95_latency_ms": 15000,
    "maximum_e2e_p95_latency_ms": 20000,
    "required_test_database_residue_rows": 0,
    "operator_decision_required": True,
    "automatic_production_cutover_permitted": False,
}
_DECISION_BOUNDARY = {
    "approved_scope": APPROVED_SCOPE,
    "decision_status": DECISION_STATUS,
    "current_policy": CURRENT_POLICY,
    "controlled_continuation_permitted": True,
    "runtime_change_permitted": False,
    "rollback_contract_preserved": True,
    "production_cutover_permitted": False,
    "next_boundary": NEXT_BOUNDARY,
}
_SAFETY = {
    "provider_call_permitted": False,
    "database_call_permitted": False,
    "holdout_access_permitted": False,
    "runtime_mutation_permitted": False,
    "rollback_weakening_permitted": False,
    "production_cutover_permitted": False,
}
_REPORT_FIELDS = {
    "activation_bundle_hash",
    "authorization_hash",
    "checks",
    "database_profile",
    "decision",
    "evidence_hash",
    "evidence_schema_version",
    "failed_checks",
    "holdout_accessed",
    "live_execution",
    "next_boundary",
    "operations_status",
    "policy_hash",
    "production_cutover_permitted",
    "restart_safe",
    "selected_policy_hash",
    "slice_id",
    "status",
    "test_database_residue_rows",
    "user_visible_policy_change",
}
_REQUIRED_CHECKS = {
    "all_decisions_user_visible",
    "bounded_c4_profile_preserved",
    "bounded_observation_window_complete",
    "cutover_remained_active",
    "decision_distribution_complete",
    "exact_cutover_authorization_bound",
    "exact_provider_sample_count",
    "holdout_not_accessed",
    "no_fallback_or_skip",
    "pag_acceptance_bound",
    "permission_and_evidence_preserved",
    "production_cutover_prohibited",
    "progress_completed",
    "restart_state_recovered",
    "restart_window_recovered",
    "slo_checks_passed",
    "test_database_zero_residue",
    "window_cap_is_observational",
}
_LIVE_FIELDS = {
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
_OPERATOR_FIELDS = {
    "decision_schema_version",
    "status",
    "decision",
    "operator_id",
    "decided_at",
    "design_hash",
    "source_evidence_hash",
    "approved_scope",
    "reason_codes",
    "controlled_continuation_approved",
    "runtime_changed",
    "rollback_contract_preserved",
    "production_cutover_approved",
    "decision_hash",
}
_REASON_CODES = (
    "BOUNDED_OPERATIONS_WINDOW_COMPLETE",
    "ZERO_PROVIDER_FAILURES_OR_FALLBACKS",
    "PROVIDER_AND_E2E_SLOS_MET",
    "RESTART_RECOVERY_VERIFIED",
    "PERMISSION_AND_EVIDENCE_PRESERVED",
    "ROLLBACK_CONTRACT_REMAINS_AUTHORITATIVE",
    "SEPARATE_PRODUCTION_RELEASE_DECISION_REQUIRED",
)


class PolicyCutoverOperationsReviewError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_policy_cutover_operations_review_design(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    design = dict(_mapping(value, "design"))
    supplied_hash = design.pop("design_hash", None)
    _exact(design, _DESIGN_FIELDS, "design")
    if (
        design.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_OPERATOR_REVIEW"
        or not _text(design.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(design.get("source_binding"), _SOURCE_FIELDS, "source_binding")
    design["source_binding"] = {
        name: _hash_ref(source.get(name), name) for name in _SOURCE_FIELDS
    }
    for field, expected in (
        ("review_policy", _REVIEW_POLICY),
        ("decision_boundary", _DECISION_BOUNDARY),
        ("safety", _SAFETY),
    ):
        if dict(_mapping(design.get(field), field)) != expected:
            raise _invalid(field)
    calculated = semantic_sha256_hash_ref(design)
    if supplied_hash is not None and _hash_ref(supplied_hash, "design_hash") != calculated:
        raise _integrity("design")
    design["design_hash"] = calculated
    return design


def build_policy_cutover_operations_operator_decision(
    *,
    operator_id: str,
    decided_at: str,
    design: Mapping[str, Any],
    source_report: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_policy_cutover_operations_review_design(design)
    evidence = _assess_source_report(normalized, source_report)
    decision: dict[str, Any] = {
        "decision_schema_version": OPERATOR_DECISION_SCHEMA_VERSION,
        "status": "DECIDED",
        "decision": DECISION,
        "operator_id": _required_text(operator_id, "operator_id"),
        "decided_at": _timestamp(decided_at, "decided_at"),
        "design_hash": normalized["design_hash"],
        "source_evidence_hash": evidence["evidence_hash"],
        "approved_scope": APPROVED_SCOPE,
        "reason_codes": list(_REASON_CODES),
        "controlled_continuation_approved": True,
        "runtime_changed": False,
        "rollback_contract_preserved": True,
        "production_cutover_approved": False,
    }
    decision["decision_hash"] = semantic_sha256_hash_ref(decision)
    return decision


def decide_policy_cutover_operations_review(
    *,
    design: Mapping[str, Any],
    source_report: Mapping[str, Any],
    operator_decision: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_policy_cutover_operations_review_design(design)
    evidence = _assess_source_report(normalized, source_report)
    operator = _validate_operator_decision(
        operator_decision, design=normalized, evidence=evidence
    )
    checks = {
        "source_report_integrity_verified": True,
        "exact_operations_policy_binding_verified": True,
        "bounded_window_complete": True,
        "zero_provider_failure_or_fallback_verified": True,
        "provider_p95_slo_verified": True,
        "e2e_p95_slo_verified": True,
        "bounded_c4_profile_verified": True,
        "restart_recovery_verified": True,
        "permission_and_evidence_preservation_verified": True,
        "test_database_zero_residue_verified": True,
        "controlled_continuation_scope_verified": True,
        "runtime_unchanged": True,
        "rollback_contract_preserved": True,
        "production_cutover_prohibited": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": DECISION,
        "decision_status": DECISION_STATUS,
        "design_hash": normalized["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "source_evidence_hash": evidence["evidence_hash"],
        "source_report_document_hash": evidence["report_document_hash"],
        "operations_policy_hash": evidence["operations_policy_hash"],
        "authorization_hash": evidence["authorization_hash"],
        "activation_bundle_hash": evidence["activation_bundle_hash"],
        "selected_policy_hash": evidence["selected_policy_hash"],
        "approved_scope": APPROVED_SCOPE,
        "current_policy": CURRENT_POLICY,
        "observed_metrics": evidence["metrics"],
        "reason_codes": list(_REASON_CODES),
        "checks": checks,
        "failed_checks": [],
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "controlled_continuation_permitted": True,
        "runtime_change_permitted": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
        "next_boundary": NEXT_BOUNDARY,
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _assess_source_report(
    design: Mapping[str, Any], source_report: Mapping[str, Any]
) -> dict[str, Any]:
    report = dict(_exact(source_report, _REPORT_FIELDS, "source_report"))
    source = design["source_binding"]
    evidence_hash = _hash_ref(report.pop("evidence_hash", None), "evidence_hash")
    if semantic_sha256_hash_ref(report) != evidence_hash:
        raise _integrity("source_evidence")
    report["evidence_hash"] = evidence_hash
    report_document_hash = semantic_sha256_hash_ref(report)
    if (
        evidence_hash != source["source_evidence_hash"]
        or report_document_hash != source["source_report_document_hash"]
        or report.get("activation_bundle_hash") != source["activation_bundle_hash"]
        or report.get("authorization_hash") != source["authorization_hash"]
        or report.get("selected_policy_hash") != source["selected_policy_hash"]
        or report.get("policy_hash") != source["operations_policy_hash"]
    ):
        raise _integrity("source_binding")

    policy = design["review_policy"]
    checks = _exact(report.get("checks"), _REQUIRED_CHECKS, "source_checks")
    live = dict(_exact(report.get("live_execution"), _LIVE_FIELDS, "live_execution"))
    for name in (
        "sample_count",
        "provider_call_count",
        "peak_in_flight",
        "ready_count",
        "low_confidence_count",
    ):
        if not _nonnegative_int(live.get(name)):
            raise _invalid("live_metrics")
    for name in (
        "feedback_p95_latency_ms",
        "provider_p95_latency_ms",
        "e2e_p95_latency_ms",
        "elapsed_seconds",
    ):
        if not _nonnegative_number(live.get(name)):
            raise _invalid("live_metrics")
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpah_answer_support_policy_cutover_operations.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-AH"
        or report.get("status") != policy["required_source_status"]
        or report.get("decision") != policy["required_source_decision"]
        or report.get("operations_status") != policy["required_operations_status"]
        or report.get("failed_checks") != []
        or any(value is not True for value in checks.values())
        or report.get("database_profile") != "test"
        or report.get("test_database_residue_rows")
        != policy["required_test_database_residue_rows"]
        or report.get("holdout_accessed") is not False
        or report.get("user_visible_policy_change") is not True
        or report.get("production_cutover_permitted") is not False
        or report.get("restart_safe") is not True
        or report.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_OPERATOR_REVIEW"
        or live["sample_count"] != policy["required_provider_sample_count"]
        or live["provider_call_count"] != policy["required_provider_call_count"]
        or live["peak_in_flight"] != policy["required_peak_in_flight"]
        or live["ready_count"] < policy["minimum_ready_count"]
        or live["ready_count"] + live["low_confidence_count"]
        != live["sample_count"]
        or live["provider_p95_latency_ms"]
        > policy["maximum_provider_p95_latency_ms"]
        or live["e2e_p95_latency_ms"] > policy["maximum_e2e_p95_latency_ms"]
    ):
        raise _invalid("source_report_boundary")
    return {
        "evidence_hash": evidence_hash,
        "report_document_hash": report_document_hash,
        "operations_policy_hash": source["operations_policy_hash"],
        "authorization_hash": source["authorization_hash"],
        "activation_bundle_hash": source["activation_bundle_hash"],
        "selected_policy_hash": source["selected_policy_hash"],
        "metrics": dict(live),
    }


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
        or decision.get("source_evidence_hash") != evidence["evidence_hash"]
        or decision.get("approved_scope") != APPROVED_SCOPE
        or decision.get("reason_codes") != list(_REASON_CODES)
        or decision.get("controlled_continuation_approved") is not True
        or decision.get("runtime_changed") is not False
        or decision.get("rollback_contract_preserved") is not True
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
    return str(value)


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


def _invalid(name: str) -> PolicyCutoverOperationsReviewError:
    return PolicyCutoverOperationsReviewError(
        "POLICY_CUTOVER_OPERATIONS_REVIEW_INVALID", f"{name} is invalid"
    )


def _integrity(name: str) -> PolicyCutoverOperationsReviewError:
    return PolicyCutoverOperationsReviewError(
        "POLICY_CUTOVER_OPERATIONS_REVIEW_INTEGRITY", f"{name} integrity failed"
    )
