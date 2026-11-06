from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = "cx_answer_support_policy_steady_state_decision_design.v1"
DECISION_SCHEMA_VERSION = (
    "cx_answer_support_policy_steady_state_operator_decision.v1"
)
MANIFEST_SCHEMA_VERSION = (
    "cx_answer_support_policy_steady_state_decision_manifest.v1"
)
DECISION = "CONTROLLED_ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_APPROVED"
DECISION_STATUS = "APPROVED_NOT_EXECUTED"
APPROVED_SCOPE = "CONTROLLED_ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS"
NEXT_BOUNDARY = (
    "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_"
    "ACTIVATION_AND_ROLLBACK_ACCEPTANCE"
)
CURRENT_POLICY = "ANSWER_SUPPORT_POLICY_CUTOVER_ACTIVE"
CURRENT_OPERATIONS_MODE = "CONTROLLED_SUSTAINED_OPERATIONS"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "decision_policy",
    "activation_boundary",
    "rollback_policy",
    "safety",
}
_SOURCE_FIELDS = {
    "readiness_report_hash",
    "readiness_design_hash",
    "readiness_manifest_hash",
    "operations_profile_hash",
    "source_evidence_hash",
    "selected_policy_hash",
    "sustained_policy_hash",
    "review_receipt_hash",
}
_DECISION_POLICY = {
    "required_readiness_status": "PASS",
    "required_readiness_decision": (
        "READY_FOR_ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATOR_DECISION"
    ),
    "required_activation_status": "NOT_ACTIVATED",
    "required_profile_status": "READY_FOR_OPERATOR_DECISION",
    "required_review_sample_interval": 12,
    "required_maximum_concurrency": 4,
    "required_provider_call_count": 12,
    "maximum_provider_p95_latency_ms": 15000,
    "maximum_e2e_p95_latency_ms": 20000,
    "operator_decision_required": True,
    "automatic_activation_permitted": False,
}
_ACTIVATION_BOUNDARY = {
    "approved_scope": APPROVED_SCOPE,
    "decision_status": DECISION_STATUS,
    "current_policy": CURRENT_POLICY,
    "current_operations_mode": CURRENT_OPERATIONS_MODE,
    "steady_state_activation_requires_installed_acceptance": True,
    "steady_state_activation_permitted_in_this_slice": False,
    "current_runtime_continues_unchanged": True,
    "production_release_requires_separate_decision": True,
    "next_boundary": NEXT_BOUNDARY,
}
_ROLLBACK_POLICY = {
    "fallback_policy": "CURRENT_ANSWER_SUPPORT_POLICY_FALLBACK",
    "rollback_target": "CURRENT_CONTROLLED_ANSWER_SUPPORT_POLICY",
    "cutover_terminal_state": "ROLLBACK_STATE_DOMINANT",
    "provider_failure": "IMMEDIATE_ROLLBACK_REQUIRED",
    "fallback_decision": "IMMEDIATE_ROLLBACK_REQUIRED",
    "provider_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "e2e_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "review_cadence_reached": "OPERATOR_REVIEW_REQUIRED",
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
    "activation_status",
    "checks",
    "database_calls",
    "decision",
    "design_hash",
    "evidence_schema_version",
    "failed_checks",
    "holdout_accessed",
    "manifest_hash",
    "manifest_schema_version",
    "next_boundary",
    "observed_metrics",
    "operations_profile",
    "production_cutover_permitted",
    "provider_calls",
    "rollout_boundary",
    "runtime_change_permitted",
    "slice_id",
    "source_evidence",
    "status",
    "steady_state_activation_permitted",
}
_READINESS_CHECKS = {
    "operator_review_report_integrity_verified",
    "operator_review_receipt_integrity_verified",
    "exact_review_lineage_bound",
    "sustained_cadence_and_slos_verified",
    "restart_and_zero_residue_verified",
    "rollback_contract_preserved",
    "current_runtime_unchanged",
    "holdout_reexecution_prohibited",
    "steady_state_activation_prohibited",
    "production_cutover_prohibited",
    "separate_operator_decision_required",
}
_PROFILE_FIELDS = {
    "profile_schema_version",
    "profile_id",
    "status",
    "current_policy",
    "current_operations_mode",
    "review_sample_interval",
    "maximum_concurrency",
    "maximum_event_scan",
    "operational_slo",
    "escalation_policy",
    "source_binding",
    "runtime_activation_permitted",
    "profile_hash",
}
_PROFILE_SOURCE_FIELDS = {
    "review_report_hash",
    "review_receipt_hash",
    "sustained_policy_hash",
    "selected_policy_hash",
}
_SOURCE_EVIDENCE_FIELDS = {
    "review_report_hash",
    "review_receipt_document_hash",
    "review_receipt_hash",
    "operator_decision_hash",
    "source_evidence_hash",
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
_DECISION_FIELDS = {
    "decision_schema_version",
    "status",
    "decision",
    "operator_id",
    "decided_at",
    "design_hash",
    "source_readiness_manifest_hash",
    "operations_profile_hash",
    "selected_policy_hash",
    "approved_scope",
    "reason_codes",
    "steady_state_operations_approved",
    "steady_state_operations_activated",
    "runtime_changed",
    "production_cutover_approved",
    "decision_hash",
}
_REASON_CODES = (
    "EXACT_STEADY_STATE_READINESS_EVIDENCE_VERIFIED",
    "SUSTAINED_CADENCE_AND_OPERATIONAL_SLOS_ACCEPTED",
    "RESTART_AND_ZERO_RESIDUE_SAFETY_PRESERVED",
    "ROLLBACK_DOMINANT_OPERATIONS_PROFILE_ACCEPTED",
    "SEPARATE_ACTIVATION_AND_ROLLBACK_ACCEPTANCE_REQUIRED",
    "PRODUCTION_RELEASE_REMAINS_SEPARATELY_GOVERNED",
)


class PolicySteadyStateDecisionError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_policy_steady_state_decision_design(
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
        name: _hash_ref(source.get(name), name) for name in _SOURCE_FIELDS
    }
    for field, expected in (
        ("decision_policy", _DECISION_POLICY),
        ("activation_boundary", _ACTIVATION_BOUNDARY),
        ("rollback_policy", _ROLLBACK_POLICY),
        ("safety", _SAFETY),
    ):
        if dict(_mapping(design.get(field), field)) != expected:
            raise _invalid(field)
    calculated = semantic_sha256_hash_ref(design)
    if supplied_hash is not None and _hash_ref(supplied_hash, "design_hash") != calculated:
        raise _integrity("design")
    design["design_hash"] = calculated
    return design


def build_policy_steady_state_operator_decision(
    *,
    operator_id: str,
    decided_at: str,
    design: Mapping[str, Any],
    readiness_report: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_policy_steady_state_decision_design(design)
    evidence = _validate_readiness_report(readiness_report, design=normalized)
    decision: dict[str, Any] = {
        "decision_schema_version": DECISION_SCHEMA_VERSION,
        "status": "DECIDED",
        "decision": DECISION,
        "operator_id": _required_text(operator_id, "operator_id"),
        "decided_at": _timestamp(decided_at, "decided_at"),
        "design_hash": normalized["design_hash"],
        "source_readiness_manifest_hash": evidence["manifest_hash"],
        "operations_profile_hash": evidence["profile_hash"],
        "selected_policy_hash": evidence["selected_policy_hash"],
        "approved_scope": APPROVED_SCOPE,
        "reason_codes": list(_REASON_CODES),
        "steady_state_operations_approved": True,
        "steady_state_operations_activated": False,
        "runtime_changed": False,
        "production_cutover_approved": False,
    }
    decision["decision_hash"] = semantic_sha256_hash_ref(decision)
    return decision


def decide_policy_steady_state_operations(
    *,
    design: Mapping[str, Any],
    readiness_report: Mapping[str, Any],
    operator_decision: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_policy_steady_state_decision_design(design)
    evidence = _validate_readiness_report(readiness_report, design=normalized)
    operator = _validate_operator_decision(
        operator_decision, design=normalized, evidence=evidence
    )
    checks = {
        "readiness_report_integrity_verified": True,
        "readiness_manifest_integrity_verified": True,
        "operations_profile_integrity_verified": True,
        "selected_policy_lineage_verified": True,
        "sustained_operations_lineage_verified": True,
        "operator_scope_verified": True,
        "steady_state_activation_not_executed": True,
        "runtime_unchanged": True,
        "rollback_contract_preserved": True,
        "holdout_reexecution_prohibited": True,
        "production_cutover_prohibited": True,
        "separate_activation_acceptance_required": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": DECISION,
        "decision_status": DECISION_STATUS,
        "design_hash": normalized["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "source_readiness_report_hash": normalized["source_binding"][
            "readiness_report_hash"
        ],
        "source_readiness_manifest_hash": evidence["manifest_hash"],
        "operations_profile_hash": evidence["profile_hash"],
        "source_evidence_hash": evidence["source_evidence_hash"],
        "selected_policy_hash": evidence["selected_policy_hash"],
        "sustained_policy_hash": evidence["sustained_policy_hash"],
        "review_receipt_hash": evidence["review_receipt_hash"],
        "approved_scope": APPROVED_SCOPE,
        "current_policy": CURRENT_POLICY,
        "current_operations_mode": CURRENT_OPERATIONS_MODE,
        "observed_metrics": evidence["metrics"],
        "reason_codes": list(_REASON_CODES),
        "checks": checks,
        "failed_checks": [],
        "rollback_policy": dict(_ROLLBACK_POLICY),
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "steady_state_operations_approved": True,
        "steady_state_operations_activated": False,
        "runtime_change_executed": False,
        "production_cutover_permitted": False,
        "next_boundary": NEXT_BOUNDARY,
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _validate_readiness_report(
    value: Mapping[str, Any], *, design: Mapping[str, Any]
) -> dict[str, Any]:
    report = dict(_exact(value, _REPORT_FIELDS, "readiness_report"))
    source = design["source_binding"]
    if semantic_sha256_hash_ref(report) != source["readiness_report_hash"]:
        raise _integrity("readiness_report")

    manifest = dict(report)
    manifest.pop("evidence_schema_version")
    manifest.pop("slice_id")
    manifest_hash = _hash_ref(manifest.pop("manifest_hash"), "manifest_hash")
    if (
        semantic_sha256_hash_ref(manifest) != manifest_hash
        or manifest_hash != source["readiness_manifest_hash"]
    ):
        raise _integrity("readiness_manifest")

    profile = dict(_exact(report.get("operations_profile"), _PROFILE_FIELDS, "profile"))
    profile_hash = _hash_ref(profile.pop("profile_hash"), "profile_hash")
    profile_source = _exact(
        profile.get("source_binding"), _PROFILE_SOURCE_FIELDS, "profile_source"
    )
    if (
        semantic_sha256_hash_ref(profile) != profile_hash
        or profile_hash != source["operations_profile_hash"]
        or profile_source.get("review_receipt_hash") != source["review_receipt_hash"]
        or profile_source.get("sustained_policy_hash") != source["sustained_policy_hash"]
        or profile_source.get("selected_policy_hash") != source["selected_policy_hash"]
    ):
        raise _integrity("operations_profile")

    evidence = _exact(
        report.get("source_evidence"), _SOURCE_EVIDENCE_FIELDS, "source_evidence"
    )
    checks = _exact(report.get("checks"), _READINESS_CHECKS, "readiness_checks")
    metrics = dict(_exact(report.get("observed_metrics"), _METRIC_FIELDS, "metrics"))
    policy = design["decision_policy"]
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpal_answer_support_policy_steady_state_readiness.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-AL"
        or report.get("manifest_schema_version")
        != "cx_answer_support_policy_steady_state_readiness_manifest.v1"
        or report.get("status") != policy["required_readiness_status"]
        or report.get("decision") != policy["required_readiness_decision"]
        or report.get("activation_status") != policy["required_activation_status"]
        or report.get("design_hash") != source["readiness_design_hash"]
        or profile.get("status") != policy["required_profile_status"]
        or profile.get("current_policy") != CURRENT_POLICY
        or profile.get("current_operations_mode") != CURRENT_OPERATIONS_MODE
        or profile.get("review_sample_interval")
        != policy["required_review_sample_interval"]
        or profile.get("maximum_concurrency")
        != policy["required_maximum_concurrency"]
        or profile.get("runtime_activation_permitted") is not False
        or evidence.get("source_evidence_hash") != source["source_evidence_hash"]
        or report.get("failed_checks") != []
        or any(result is not True for result in checks.values())
        or report.get("provider_calls") != 0
        or report.get("database_calls") != 0
        or report.get("holdout_accessed") is not False
        or report.get("runtime_change_permitted") is not False
        or report.get("steady_state_activation_permitted") is not False
        or report.get("production_cutover_permitted") is not False
        or report.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_OPERATOR_DECISION"
        or metrics.get("provider_call_count")
        != policy["required_provider_call_count"]
        or metrics.get("peak_in_flight") != policy["required_maximum_concurrency"]
        or not _nonnegative_int(metrics.get("sample_count"))
        or not _nonnegative_int(metrics.get("ready_count"))
        or not _nonnegative_int(metrics.get("low_confidence_count"))
        or metrics.get("ready_count") + metrics.get("low_confidence_count")
        != metrics.get("sample_count")
        or not _nonnegative_number(metrics.get("provider_p95_latency_ms"))
        or not _nonnegative_number(metrics.get("e2e_p95_latency_ms"))
        or metrics.get("provider_p95_latency_ms")
        > policy["maximum_provider_p95_latency_ms"]
        or metrics.get("e2e_p95_latency_ms")
        > policy["maximum_e2e_p95_latency_ms"]
    ):
        raise _invalid("readiness_boundary")
    return {
        "manifest_hash": manifest_hash,
        "profile_hash": profile_hash,
        "source_evidence_hash": evidence["source_evidence_hash"],
        "selected_policy_hash": source["selected_policy_hash"],
        "sustained_policy_hash": source["sustained_policy_hash"],
        "review_receipt_hash": source["review_receipt_hash"],
        "metrics": metrics,
    }


def _validate_operator_decision(
    value: Mapping[str, Any], *, design: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    decision = dict(_exact(value, _DECISION_FIELDS, "operator_decision"))
    decision_hash = _hash_ref(decision.pop("decision_hash"), "decision_hash")
    if semantic_sha256_hash_ref(decision) != decision_hash:
        raise _integrity("operator_decision")
    decision["decision_hash"] = decision_hash
    if (
        decision.get("decision_schema_version") != DECISION_SCHEMA_VERSION
        or decision.get("status") != "DECIDED"
        or decision.get("decision") != DECISION
        or not _text(decision.get("operator_id"))
        or decision.get("design_hash") != design["design_hash"]
        or decision.get("source_readiness_manifest_hash")
        != evidence["manifest_hash"]
        or decision.get("operations_profile_hash") != evidence["profile_hash"]
        or decision.get("selected_policy_hash") != evidence["selected_policy_hash"]
        or decision.get("approved_scope") != APPROVED_SCOPE
        or decision.get("reason_codes") != list(_REASON_CODES)
        or decision.get("steady_state_operations_approved") is not True
        or decision.get("steady_state_operations_activated") is not False
        or decision.get("runtime_changed") is not False
        or decision.get("production_cutover_approved") is not False
    ):
        raise _invalid("operator_decision")
    _timestamp(decision.get("decided_at"), "decided_at")
    return decision


def _required_text(value: object, name: str) -> str:
    if not _text(value):
        raise _invalid(name)
    return str(value).strip()


def _timestamp(value: object, name: str) -> str:
    text = _required_text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(name) from exc
    if parsed.tzinfo is None:
        raise _invalid(name)
    return text


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


def _invalid(name: str) -> PolicySteadyStateDecisionError:
    return PolicySteadyStateDecisionError(
        "POLICY_STEADY_STATE_DECISION_INVALID", f"{name} is invalid"
    )


def _integrity(name: str) -> PolicySteadyStateDecisionError:
    return PolicySteadyStateDecisionError(
        "POLICY_STEADY_STATE_DECISION_INTEGRITY", f"{name} integrity failed"
    )
