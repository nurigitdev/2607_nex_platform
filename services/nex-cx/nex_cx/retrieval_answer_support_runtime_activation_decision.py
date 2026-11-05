from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.retrieval_answer_support_synchronous_runtime import (
    ACCEPTED_DECISION as E2E_ACCEPTED_DECISION,
)
from nex_cx.retrieval_answer_support_synchronous_runtime import (
    evaluate_synchronous_runtime_e2e_receipt,
    validate_synchronous_runtime_e2e_design,
)

DESIGN_SCHEMA_VERSION = "cx_answer_support_runtime_activation_decision_design.v1"
OPERATOR_DECISION_SCHEMA_VERSION = (
    "cx_answer_support_runtime_activation_operator_decision.v1"
)
MANIFEST_SCHEMA_VERSION = "cx_answer_support_runtime_activation_decision_manifest.v1"
DECISION = "CONTROLLED_SYNCHRONOUS_SHADOW_ACTIVATION_APPROVED"
ACTIVATION_SCOPE = "BOUNDED_SYNCHRONOUS_ANSWER_SUPPORT_SHADOW_OBSERVER"
ACTIVATION_STATUS = "APPROVED_NOT_ACTIVATED"
NEXT_BOUNDARY = "CONTROLLED_RUNTIME_ACTIVATION_AND_ROLLBACK_ACCEPTANCE"
CURRENT_POLICY = "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "activation_policy",
    "activation_boundary",
    "rollback_policy",
    "safety",
}
_SOURCE_FIELDS = {
    "e2e_design_hash",
    "e2e_manifest_hash",
    "e2e_receipt_document_hash",
    "e2e_receipt_hash",
    "e2e_report_document_hash",
    "provider_binding_hash",
    "readiness_manifest_hash",
    "runtime_profile_hash",
    "selected_policy_hash",
}
_ACTIVATION_POLICY = {
    "required_e2e_decision": E2E_ACCEPTED_DECISION,
    "required_sample_count": 30,
    "required_maximum_concurrency": 4,
    "maximum_provider_errors": 0,
    "maximum_admission_rejections": 0,
    "maximum_progress_failures": 0,
    "retryable_overload_required": True,
    "operator_decision_required": True,
    "automatic_activation_permitted": False,
}
_ACTIVATION_BOUNDARY = {
    "approved_scope": ACTIVATION_SCOPE,
    "activation_status": ACTIVATION_STATUS,
    "installed_composition_required": True,
    "user_visible_decision_change_permitted": False,
    "current_policy": CURRENT_POLICY,
    "fallback_policy": CURRENT_POLICY,
    "rollback_target": CURRENT_POLICY,
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
    "runtime_activation_decision_permitted": True,
    "runtime_activation_execution_permitted": False,
    "production_cutover_permitted": False,
}
_OPERATOR_FIELDS = {
    "decision_schema_version",
    "status",
    "decision",
    "operator_id",
    "decided_at",
    "design_hash",
    "source_e2e_receipt_hash",
    "source_e2e_manifest_hash",
    "selected_policy_hash",
    "approved_activation_scope",
    "reason_codes",
    "runtime_activation_approved",
    "runtime_activated",
    "production_cutover_approved",
    "decision_hash",
}
_REPORT_FIELDS = {
    "evidence_schema_version",
    "slice_id",
    "status",
    "decision",
    "design_hash",
    "receipt_hash",
    "manifest_hash",
    "selected_policy_hash",
    "checks",
    "failed_checks",
    "execution",
    "metrics",
    "provider_http_requests",
    "database_calls",
    "holdout_accessed",
    "runtime_activation_permitted",
    "production_cutover_permitted",
    "next_boundary",
}
_REASON_CODES = (
    "SYNCHRONOUS_RUNTIME_E2E_ACCEPTED",
    "BOUNDED_C4_ADMISSION_ENFORCED",
    "FEEDBACK_PROVIDER_AND_E2E_SLOS_MET",
    "ZERO_PROVIDER_AND_PROGRESS_FAILURES",
    "RETRYABLE_OVERLOAD_VERIFIED",
    "FALLBACK_AND_ROLLBACK_PRESERVED",
)


class RuntimeActivationDecisionError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_runtime_activation_decision_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(_mapping(design, "design"))
    supplied_hash = normalized.pop("design_hash", None)
    _exact(normalized, _DESIGN_FIELDS, "design")
    if (
        normalized.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or normalized.get("status") != "FROZEN_OPERATOR_DECISION"
        or not _text(normalized.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(normalized.get("source_binding"), _SOURCE_FIELDS, "source")
    normalized["source_binding"] = {
        key: _hash_ref(source.get(key), key) for key in sorted(_SOURCE_FIELDS)
    }
    for field, expected in (
        ("activation_policy", _ACTIVATION_POLICY),
        ("activation_boundary", _ACTIVATION_BOUNDARY),
        ("rollback_policy", _ROLLBACK_POLICY),
        ("safety", _SAFETY),
    ):
        if dict(_mapping(normalized.get(field), field)) != expected:
            raise _invalid(field)
    calculated = semantic_sha256_hash_ref(normalized)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated
    ):
        raise _integrity("design")
    normalized["design_hash"] = calculated
    return normalized


def build_runtime_activation_operator_decision(
    *,
    operator_id: str,
    decided_at: str,
    design: Mapping[str, Any],
    e2e_report: Mapping[str, Any],
    e2e_receipt: Mapping[str, Any],
    e2e_design: Mapping[str, Any],
    interactive_slo_decision_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_runtime_activation_decision_design(design)
    evidence = _assess_evidence(
        normalized,
        e2e_report=e2e_report,
        e2e_receipt=e2e_receipt,
        e2e_design=e2e_design,
        interactive_slo_decision_receipt=interactive_slo_decision_receipt,
    )
    decision: dict[str, Any] = {
        "decision_schema_version": OPERATOR_DECISION_SCHEMA_VERSION,
        "status": "DECIDED",
        "decision": DECISION,
        "operator_id": _required_text(operator_id, "operator_id"),
        "decided_at": _timestamp(decided_at, "decided_at"),
        "design_hash": normalized["design_hash"],
        "source_e2e_receipt_hash": evidence["receipt_hash"],
        "source_e2e_manifest_hash": evidence["manifest_hash"],
        "selected_policy_hash": evidence["selected_policy_hash"],
        "approved_activation_scope": ACTIVATION_SCOPE,
        "reason_codes": list(_REASON_CODES),
        "runtime_activation_approved": True,
        "runtime_activated": False,
        "production_cutover_approved": False,
    }
    decision["decision_hash"] = semantic_sha256_hash_ref(decision)
    return decision


def decide_runtime_activation(
    *,
    design: Mapping[str, Any],
    e2e_report: Mapping[str, Any],
    e2e_receipt: Mapping[str, Any],
    e2e_design: Mapping[str, Any],
    interactive_slo_decision_receipt: Mapping[str, Any],
    operator_decision: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_runtime_activation_decision_design(design)
    evidence = _assess_evidence(
        normalized,
        e2e_report=e2e_report,
        e2e_receipt=e2e_receipt,
        e2e_design=e2e_design,
        interactive_slo_decision_receipt=interactive_slo_decision_receipt,
    )
    operator = _validate_operator_decision(
        operator_decision, design=normalized, evidence=evidence
    )
    checks = {
        "accepted_e2e_evidence_integrity_verified": True,
        "selected_policy_binding_verified": True,
        "bounded_c4_admission_verified": True,
        "feedback_provider_and_e2e_slos_verified": True,
        "zero_provider_and_progress_failures_verified": True,
        "retryable_overload_verified": True,
        "operator_activation_scope_verified": True,
        "current_user_policy_unchanged": True,
        "fallback_and_rollback_preserved": True,
        "runtime_not_activated_by_decision": True,
        "production_cutover_prohibited": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": DECISION,
        "activation_status": ACTIVATION_STATUS,
        "design_hash": normalized["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "source_e2e_receipt_hash": evidence["receipt_hash"],
        "source_e2e_manifest_hash": evidence["manifest_hash"],
        "selected_policy_hash": evidence["selected_policy_hash"],
        "approved_activation_scope": ACTIVATION_SCOPE,
        "observed_execution": evidence["execution"],
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
        "runtime_activation_permitted": True,
        "runtime_activated": False,
        "user_visible_decision_change_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": NEXT_BOUNDARY,
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _assess_evidence(
    design: Mapping[str, Any],
    *,
    e2e_report: Mapping[str, Any],
    e2e_receipt: Mapping[str, Any],
    e2e_design: Mapping[str, Any],
    interactive_slo_decision_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    source = design["source_binding"]
    normalized_e2e_design = validate_synchronous_runtime_e2e_design(e2e_design)
    receipt = dict(_mapping(e2e_receipt, "e2e_receipt"))
    report = dict(_exact(e2e_report, _REPORT_FIELDS, "e2e_report"))
    if (
        normalized_e2e_design["design_hash"] != source["e2e_design_hash"]
        or semantic_sha256_hash_ref(receipt) != source["e2e_receipt_document_hash"]
        or semantic_sha256_hash_ref(report) != source["e2e_report_document_hash"]
    ):
        raise _integrity("source_document")
    manifest = evaluate_synchronous_runtime_e2e_receipt(
        receipt,
        design=normalized_e2e_design,
        decision_receipt=interactive_slo_decision_receipt,
    )
    _validate_report(report, manifest=manifest)
    receipt_source = _mapping(receipt.get("source_binding"), "receipt_source")
    if (
        receipt.get("receipt_hash") != source["e2e_receipt_hash"]
        or manifest.get("manifest_hash") != source["e2e_manifest_hash"]
        or manifest.get("selected_policy_hash") != source["selected_policy_hash"]
        or receipt_source.get("readiness_manifest_hash")
        != source["readiness_manifest_hash"]
        or receipt_source.get("runtime_profile_hash") != source["runtime_profile_hash"]
        or receipt_source.get("provider_binding_hash")
        != source["provider_binding_hash"]
    ):
        raise _integrity("source_binding")
    execution = _mapping(manifest.get("execution"), "execution")
    metrics = _mapping(manifest.get("metrics"), "metrics")
    policy = design["activation_policy"]
    if (
        manifest.get("decision") != policy["required_e2e_decision"]
        or execution.get("accepted_count") != policy["required_sample_count"]
        or execution.get("maximum_in_flight") != policy["required_maximum_concurrency"]
        or execution.get("peak_in_flight") != policy["required_maximum_concurrency"]
        or execution.get("provider_error_count") > policy["maximum_provider_errors"]
        or execution.get("rejected_count") > policy["maximum_admission_rejections"]
        or execution.get("progress_failure_count") > policy["maximum_progress_failures"]
        or execution.get("overload_probe_retryable")
        is not policy["retryable_overload_required"]
        or manifest.get("failed_checks") != []
    ):
        raise _invalid("e2e_acceptance")
    return {
        "receipt_hash": receipt["receipt_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "selected_policy_hash": manifest["selected_policy_hash"],
        "execution": dict(execution),
        "metrics": dict(metrics),
    }


def _validate_report(report: Mapping[str, Any], *, manifest: Mapping[str, Any]) -> None:
    expected = {
        "status": "PASS",
        "decision": manifest["decision"],
        "design_hash": manifest["design_hash"],
        "receipt_hash": manifest["source_receipt_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "selected_policy_hash": manifest["selected_policy_hash"],
        "checks": manifest["checks"],
        "failed_checks": manifest["failed_checks"],
        "execution": manifest["execution"],
        "metrics": manifest["metrics"],
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": "RUNTIME_ACTIVATION_OPERATOR_DECISION",
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise _integrity("e2e_report")
    if (
        report.get("evidence_schema_version") != "gb2_s20qpy_sync_runtime_e2e.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-Y"
        or report.get("provider_http_requests")
        != manifest["execution"]["provider_call_count"]
    ):
        raise _invalid("e2e_report")


def _validate_operator_decision(
    value: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(_exact(value, _OPERATOR_FIELDS, "operator_decision"))
    decision_hash = _hash_ref(normalized.pop("decision_hash", None), "decision_hash")
    if semantic_sha256_hash_ref(normalized) != decision_hash:
        raise _integrity("operator_decision")
    normalized["decision_hash"] = decision_hash
    if (
        normalized.get("decision_schema_version") != OPERATOR_DECISION_SCHEMA_VERSION
        or normalized.get("status") != "DECIDED"
        or normalized.get("decision") != DECISION
        or normalized.get("design_hash") != design["design_hash"]
        or normalized.get("source_e2e_receipt_hash") != evidence["receipt_hash"]
        or normalized.get("source_e2e_manifest_hash") != evidence["manifest_hash"]
        or normalized.get("selected_policy_hash") != evidence["selected_policy_hash"]
        or normalized.get("approved_activation_scope") != ACTIVATION_SCOPE
        or normalized.get("reason_codes") != list(_REASON_CODES)
        or normalized.get("runtime_activation_approved") is not True
        or normalized.get("runtime_activated") is not False
        or normalized.get("production_cutover_approved") is not False
    ):
        raise _invalid("operator_decision")
    _required_text(normalized.get("operator_id"), "operator_id")
    _timestamp(normalized.get("decided_at"), "decided_at")
    return normalized


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
        validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(name) from exc
    return value


def _invalid(detail: str) -> RuntimeActivationDecisionError:
    return RuntimeActivationDecisionError("RUNTIME_ACTIVATION_DECISION_INVALID", detail)


def _integrity(detail: str) -> RuntimeActivationDecisionError:
    return RuntimeActivationDecisionError(
        "RUNTIME_ACTIVATION_DECISION_INTEGRITY", detail
    )
