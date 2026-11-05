from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = "cx_answer_support_limited_shadow_review_design.v1"
OPERATOR_DECISION_SCHEMA_VERSION = (
    "cx_answer_support_limited_shadow_operator_decision.v1"
)
MANIFEST_SCHEMA_VERSION = "cx_answer_support_limited_shadow_review_manifest.v1"
DECISION = "CONTINUE_LIMITED_SHADOW_OBSERVATION_APPROVED"
DECISION_STATUS = "APPROVED_NOT_EXECUTED"
APPROVED_SCOPE = "SECOND_BOUNDED_ANSWER_SUPPORT_SHADOW_WINDOW"
NEXT_BOUNDARY = "EXTENDED_LIMITED_SHADOW_RUNTIME_OPERATIONS"
CURRENT_POLICY = "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "review_policy",
    "continuation_boundary",
    "safety",
}
_SOURCE_FIELDS = {
    "activation_bundle_hash",
    "operations_policy_hash",
    "source_evidence_hash",
    "source_report_document_hash",
    "window_id",
}
_REVIEW_POLICY = {
    "required_source_status": "PASS",
    "required_source_decision": "LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED",
    "required_operations_status": "REVIEW_REQUIRED",
    "required_provider_sample_count": 12,
    "required_provider_call_count": 12,
    "required_peak_in_flight": 4,
    "maximum_provider_p95_latency_ms": 15000,
    "maximum_e2e_p95_latency_ms": 20000,
    "required_test_database_residue_rows": 0,
    "operator_decision_required": True,
    "automatic_continuation_permitted": False,
}
_CONTINUATION_BOUNDARY = {
    "approved_scope": APPROVED_SCOPE,
    "decision_status": DECISION_STATUS,
    "next_window_maximum_provider_samples": 30,
    "maximum_concurrency": 4,
    "same_activation_bundle_required": True,
    "fresh_window_policy_required": True,
    "current_policy": CURRENT_POLICY,
    "user_visible_decision_change_permitted": False,
    "next_boundary": NEXT_BOUNDARY,
}
_SAFETY = {
    "provider_call_permitted": False,
    "database_call_permitted": False,
    "holdout_access_permitted": False,
    "runtime_continuation_decision_permitted": True,
    "runtime_continuation_execution_permitted": False,
    "user_visible_decision_change_permitted": False,
    "production_cutover_permitted": False,
}
_REPORT_FIELDS = {
    "activation_bundle_hash",
    "checks",
    "database_profile",
    "decision",
    "evidence_hash",
    "evidence_schema_version",
    "failed_checks",
    "holdout_accessed",
    "live_execution",
    "next_boundary",
    "operations_policy_hash",
    "operations_status",
    "production_cutover_permitted",
    "slice_id",
    "status",
    "test_database_residue_rows",
    "user_visible_decision_change",
    "window",
    "window_id",
}
_REQUIRED_CHECKS = {
    "activation_bundle_binding_verified",
    "all_limited_samples_observed",
    "bounded_c4_profile_preserved",
    "exact_provider_sample_cap_observed",
    "limited_policy_integrity_verified",
    "operator_review_required",
    "primary_policy_unchanged",
    "production_cutover_prohibited",
    "raw_text_projection_prohibited",
    "restart_sample_cap_preserved",
    "thirteenth_request_provider_blocked",
}
_LIVE_FIELDS = {
    "wave_count",
    "wave_concurrency",
    "sample_count",
    "provider_call_count",
    "elapsed_seconds",
    "provider_p95_latency_ms",
    "e2e_p95_latency_ms",
    "peak_in_flight",
}
_WINDOW_FIELDS = {
    "window_id",
    "policy_hash",
    "minimum_operator_review_samples",
    "maximum_provider_samples",
    "provider_sample_count",
    "remaining_provider_samples",
    "sample_cap_reached",
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
    "next_window_maximum_provider_samples",
    "reason_codes",
    "continuation_approved",
    "continuation_executed",
    "production_cutover_approved",
    "decision_hash",
}
_REASON_CODES = (
    "LIMITED_WINDOW_COMPLETE",
    "ZERO_PROVIDER_FAILURES_OBSERVED",
    "PROVIDER_AND_E2E_SLOS_MET",
    "RESTART_SAFE_CAP_VERIFIED",
    "CURRENT_USER_POLICY_UNCHANGED",
    "EXTENDED_WINDOW_REQUIRED_BEFORE_CUTOVER_REVIEW",
)


class LimitedShadowReviewError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_limited_shadow_review_design(
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
        "activation_bundle_hash": _hash_ref(
            source.get("activation_bundle_hash"), "activation_bundle_hash"
        ),
        "operations_policy_hash": _hash_ref(
            source.get("operations_policy_hash"), "operations_policy_hash"
        ),
        "source_evidence_hash": _hash_ref(
            source.get("source_evidence_hash"), "source_evidence_hash"
        ),
        "source_report_document_hash": _hash_ref(
            source.get("source_report_document_hash"),
            "source_report_document_hash",
        ),
        "window_id": _required_text(source.get("window_id"), "window_id"),
    }
    for field, expected in (
        ("review_policy", _REVIEW_POLICY),
        ("continuation_boundary", _CONTINUATION_BOUNDARY),
        ("safety", _SAFETY),
    ):
        if dict(_mapping(design.get(field), field)) != expected:
            raise _invalid(field)
    calculated = semantic_sha256_hash_ref(design)
    if supplied_hash is not None and _hash_ref(supplied_hash, "design_hash") != calculated:
        raise _integrity("design")
    design["design_hash"] = calculated
    return design


def build_limited_shadow_operator_decision(
    *,
    operator_id: str,
    decided_at: str,
    design: Mapping[str, Any],
    source_report: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_limited_shadow_review_design(design)
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
        "next_window_maximum_provider_samples": _CONTINUATION_BOUNDARY[
            "next_window_maximum_provider_samples"
        ],
        "reason_codes": list(_REASON_CODES),
        "continuation_approved": True,
        "continuation_executed": False,
        "production_cutover_approved": False,
    }
    decision["decision_hash"] = semantic_sha256_hash_ref(decision)
    return decision


def decide_limited_shadow_review(
    *,
    design: Mapping[str, Any],
    source_report: Mapping[str, Any],
    operator_decision: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_limited_shadow_review_design(design)
    evidence = _assess_source_report(normalized, source_report)
    operator = _validate_operator_decision(
        operator_decision,
        design=normalized,
        evidence=evidence,
    )
    checks = {
        "source_report_integrity_verified": True,
        "exact_window_binding_verified": True,
        "sample_cap_and_restart_safety_verified": True,
        "zero_provider_failure_evidence_verified": True,
        "provider_p95_slo_verified": True,
        "e2e_p95_slo_verified": True,
        "bounded_c4_profile_verified": True,
        "operator_continuation_scope_verified": True,
        "continuation_not_executed": True,
        "current_user_policy_unchanged": True,
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
        "activation_bundle_hash": evidence["activation_bundle_hash"],
        "source_window_id": evidence["window_id"],
        "approved_scope": APPROVED_SCOPE,
        "next_window": {
            "maximum_provider_samples": _CONTINUATION_BOUNDARY[
                "next_window_maximum_provider_samples"
            ],
            "maximum_concurrency": _CONTINUATION_BOUNDARY[
                "maximum_concurrency"
            ],
            "fresh_window_policy_required": True,
            "execution_permitted": False,
        },
        "observed_metrics": evidence["metrics"],
        "reason_codes": list(_REASON_CODES),
        "checks": checks,
        "failed_checks": [],
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "continuation_decision_permitted": True,
        "continuation_execution_permitted": False,
        "user_visible_decision_change_permitted": False,
        "production_cutover_permitted": False,
        "current_policy": CURRENT_POLICY,
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
        or report.get("operations_policy_hash") != source["operations_policy_hash"]
        or report.get("window_id") != source["window_id"]
    ):
        raise _integrity("source_binding")
    policy = design["review_policy"]
    checks = _exact(report.get("checks"), _REQUIRED_CHECKS, "source_checks")
    live = dict(_exact(report.get("live_execution"), _LIVE_FIELDS, "live_execution"))
    window = dict(_exact(report.get("window"), _WINDOW_FIELDS, "window"))
    numeric = (
        "elapsed_seconds",
        "provider_p95_latency_ms",
        "e2e_p95_latency_ms",
    )
    integers = (
        "wave_count",
        "wave_concurrency",
        "sample_count",
        "provider_call_count",
        "peak_in_flight",
    )
    if any(not _nonnegative_number(live.get(name)) for name in numeric) or any(
        not _nonnegative_int(live.get(name)) for name in integers
    ):
        raise _invalid("live_metrics")
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpab_limited_shadow_operations.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-AB"
        or report.get("status") != policy["required_source_status"]
        or report.get("decision") != policy["required_source_decision"]
        or report.get("operations_status") != policy["required_operations_status"]
        or report.get("failed_checks") != []
        or any(value is not True for value in checks.values())
        or report.get("database_profile") != "test"
        or report.get("test_database_residue_rows")
        != policy["required_test_database_residue_rows"]
        or report.get("holdout_accessed") is not False
        or report.get("user_visible_decision_change") is not False
        or report.get("production_cutover_permitted") is not False
        or report.get("next_boundary") != "LIMITED_SHADOW_OPERATOR_REVIEW_DECISION"
        or live["sample_count"] != policy["required_provider_sample_count"]
        or live["provider_call_count"] != policy["required_provider_call_count"]
        or live["peak_in_flight"] != policy["required_peak_in_flight"]
        or live["wave_concurrency"] != policy["required_peak_in_flight"]
        or live["provider_p95_latency_ms"]
        > policy["maximum_provider_p95_latency_ms"]
        or live["e2e_p95_latency_ms"] > policy["maximum_e2e_p95_latency_ms"]
        or window.get("window_id") != source["window_id"]
        or window.get("policy_hash") != source["operations_policy_hash"]
        or window.get("provider_sample_count")
        != policy["required_provider_sample_count"]
        or window.get("minimum_operator_review_samples")
        != policy["required_provider_sample_count"]
        or window.get("maximum_provider_samples")
        != policy["required_provider_sample_count"]
        or window.get("remaining_provider_samples") != 0
        or window.get("sample_cap_reached") is not True
    ):
        raise _invalid("source_report_boundary")
    return {
        "evidence_hash": evidence_hash,
        "report_document_hash": report_document_hash,
        "operations_policy_hash": source["operations_policy_hash"],
        "activation_bundle_hash": source["activation_bundle_hash"],
        "window_id": source["window_id"],
        "metrics": {
            "sample_count": live["sample_count"],
            "provider_call_count": live["provider_call_count"],
            "provider_p95_latency_ms": live["provider_p95_latency_ms"],
            "e2e_p95_latency_ms": live["e2e_p95_latency_ms"],
            "peak_in_flight": live["peak_in_flight"],
            "test_database_residue_rows": report["test_database_residue_rows"],
        },
    }


def _validate_operator_decision(
    value: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    evidence: Mapping[str, Any],
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
        or decision.get("next_window_maximum_provider_samples")
        != _CONTINUATION_BOUNDARY["next_window_maximum_provider_samples"]
        or decision.get("reason_codes") != list(_REASON_CODES)
        or decision.get("continuation_approved") is not True
        or decision.get("continuation_executed") is not False
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


def _nonnegative_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value >= 0


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _invalid(detail: str) -> LimitedShadowReviewError:
    return LimitedShadowReviewError("CX_LIMITED_SHADOW_REVIEW_INVALID", detail)


def _integrity(detail: str) -> LimitedShadowReviewError:
    return LimitedShadowReviewError("CX_LIMITED_SHADOW_REVIEW_INTEGRITY", detail)
