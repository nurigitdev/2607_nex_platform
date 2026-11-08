from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_policy_steady_state_continuation_closure_design.v1"
)
MANIFEST_SCHEMA_VERSION = (
    "cx_answer_support_policy_steady_state_continuation_closure_manifest.v1"
)
DECISION = "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION_CLOSED"
CLOSURE_STATUS = "CLOSED_CONTROLLED_OPERATIONS_BASELINE"
BASELINE_STATUS = "FROZEN"
RUNTIME_DISPOSITION = "CONTINUE_CONTROLLED_STEADY_STATE_OPERATIONS"
NEXT_BOUNDARY = "ANSWER_SUPPORT_POLICY_CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "closure_policy",
    "safety",
}
_SOURCE_FIELDS = {
    "operator_review_design_hash",
    "operator_decision_hash",
    "operator_review_manifest_hash",
    "operator_review_receipt_hash",
    "operator_review_report_document_hash",
    "operator_review_receipt_document_hash",
    "source_continuation_evidence_hash",
    "source_continuation_report_document_hash",
    "continuation_policy_hash",
    "operations_profile_hash",
    "selected_policy_hash",
    "prior_continuation_receipt_hash",
}
_REOPEN_TRIGGERS = (
    "MODEL_OR_PROVIDER_REVISION_CHANGED",
    "REQUEST_PROFILE_OR_SCORE_SEMANTICS_CHANGED",
    "CALIBRATION_DATASET_OR_SELECTED_POLICY_CHANGED",
    "OPERATIONS_PROFILE_OR_SLO_CHANGED",
    "PERMISSION_OR_TENANT_BOUNDARY_CHANGED",
    "FALLBACK_RESTART_OR_ROLLBACK_GUARANTEE_DRIFTED",
    "EXPLICIT_OPERATOR_REOPEN_DECISION",
)
_CLOSURE_POLICY = {
    "required_source_status": "PASS",
    "required_source_decision": (
        "CONTROLLED_ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_"
        "CONTINUATION_CONFIRMED"
    ),
    "required_decision_status": "APPROVED_CONTINUATION_NOT_PRODUCTION",
    "required_source_next_boundary": (
        "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION_CLOSURE"
    ),
    "closure_status": CLOSURE_STATUS,
    "baseline_status": BASELINE_STATUS,
    "runtime_disposition": RUNTIME_DISPOSITION,
    "corrective_chain_closed": True,
    "automatic_reopen_permitted": False,
    "reopen_triggers": list(_REOPEN_TRIGGERS),
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
    "approved_scope",
    "checks",
    "continuation_policy_hash",
    "controlled_continuation_confirmed",
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
    "operations_profile_hash",
    "operator_decision_hash",
    "prior_continuation_receipt_hash",
    "prior_review_report_document_hash",
    "production_cutover_permitted",
    "provider_calls",
    "reason_codes",
    "rollback_contract_preserved",
    "runtime_change_permitted",
    "selected_policy_hash",
    "slice_id",
    "source_activation_evidence_hash",
    "source_evidence_hash",
    "source_report_document_hash",
    "status",
    "steady_state_authorization_hash",
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
    "prior_continuation_receipt_hash",
    "production_cutover_permitted",
    "receipt_hash",
    "receipt_schema_version",
    "rollback_contract_preserved",
    "runtime_changed",
    "source_evidence_hash",
    "source_report_document_hash",
    "status",
    "steady_state_continuation_confirmed",
}


class PolicySteadyStateContinuationClosureError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_policy_steady_state_continuation_closure_design(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    design = dict(_mapping(value, "design"))
    supplied_hash = design.pop("design_hash", None)
    _exact(design, _DESIGN_FIELDS, "design")
    if (
        design.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_CLOSURE"
        or not _text(design.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(design.get("source_binding"), _SOURCE_FIELDS, "source_binding")
    design["source_binding"] = {
        name: _hash_ref(source.get(name), name) for name in _SOURCE_FIELDS
    }
    if dict(_mapping(design.get("closure_policy"), "closure_policy")) != (
        _CLOSURE_POLICY
    ):
        raise _invalid("closure_policy")
    if dict(_mapping(design.get("safety"), "safety")) != _SAFETY:
        raise _invalid("safety")
    calculated = semantic_sha256_hash_ref(design)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated
    ):
        raise _integrity("design")
    design["design_hash"] = calculated
    return design


def build_policy_steady_state_continuation_closure(
    *,
    design: Mapping[str, Any],
    operator_review_report: Mapping[str, Any],
    operator_review_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_policy_steady_state_continuation_closure_design(design)
    evidence = _validate_operator_review_sources(
        normalized,
        operator_review_report,
        operator_review_receipt,
    )
    checks = {
        "operator_review_report_integrity_verified": True,
        "operator_review_receipt_integrity_verified": True,
        "report_receipt_cross_binding_verified": True,
        "exact_operator_review_design_bound": True,
        "exact_operator_decision_bound": True,
        "exact_continuation_evidence_bound": True,
        "exact_continuation_policy_bound": True,
        "exact_operations_profile_bound": True,
        "exact_selected_policy_bound": True,
        "prior_continuation_receipt_bound": True,
        "source_review_checks_complete": True,
        "no_external_calls_verified": True,
        "holdout_not_accessed": True,
        "runtime_unchanged": True,
        "rollback_contract_preserved": True,
        "production_cutover_prohibited": True,
        "corrective_chain_closed": True,
        "controlled_runtime_preserved": True,
        "reopen_triggers_frozen": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": DECISION,
        "closure_status": CLOSURE_STATUS,
        "baseline_status": BASELINE_STATUS,
        "runtime_disposition": RUNTIME_DISPOSITION,
        "design_hash": normalized["design_hash"],
        **normalized["source_binding"],
        "observed_metrics": evidence["observed_metrics"],
        "checks": checks,
        "failed_checks": [],
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_changed": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
        "corrective_chain_closed": True,
        "automatic_reopen_permitted": False,
        "reopen_triggers": list(_REOPEN_TRIGGERS),
        "next_boundary": NEXT_BOUNDARY,
    }
    manifest["closure_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _validate_operator_review_sources(
    design: Mapping[str, Any],
    report_value: Mapping[str, Any],
    receipt_value: Mapping[str, Any],
) -> dict[str, Any]:
    report = dict(_exact(report_value, _REPORT_FIELDS, "operator_review_report"))
    receipt = dict(_exact(receipt_value, _RECEIPT_FIELDS, "operator_review_receipt"))
    source = design["source_binding"]
    report_document_hash = semantic_sha256_hash_ref(report)
    receipt_document_hash = semantic_sha256_hash_ref(receipt)

    manifest_payload = dict(report)
    for field in ("evidence_schema_version", "slice_id", "decision_receipt_hash"):
        manifest_payload.pop(field)
    manifest_hash = _hash_ref(manifest_payload.pop("manifest_hash"), "manifest_hash")
    receipt_payload = dict(receipt)
    receipt_hash = _hash_ref(receipt_payload.pop("receipt_hash"), "receipt_hash")
    report_checks = _mapping(report.get("checks"), "report_checks")

    if (
        report_document_hash != source["operator_review_report_document_hash"]
        or receipt_document_hash != source["operator_review_receipt_document_hash"]
        or semantic_sha256_hash_ref(manifest_payload) != manifest_hash
        or semantic_sha256_hash_ref(receipt_payload) != receipt_hash
        or report.get("design_hash") != source["operator_review_design_hash"]
        or report.get("operator_decision_hash") != source["operator_decision_hash"]
        or manifest_hash != source["operator_review_manifest_hash"]
        or receipt_hash != source["operator_review_receipt_hash"]
        or report.get("decision_receipt_hash") != receipt_hash
        or report.get("source_evidence_hash")
        != source["source_continuation_evidence_hash"]
        or report.get("source_report_document_hash")
        != source["source_continuation_report_document_hash"]
        or report.get("continuation_policy_hash") != source["continuation_policy_hash"]
        or report.get("operations_profile_hash") != source["operations_profile_hash"]
        or report.get("selected_policy_hash") != source["selected_policy_hash"]
        or report.get("prior_continuation_receipt_hash")
        != source["prior_continuation_receipt_hash"]
    ):
        raise _integrity("source_binding")

    policy = design["closure_policy"]
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpar_answer_support_policy_steady_state_operations_"
        "continuation_operator_review.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-AR"
        or report.get("manifest_schema_version")
        != "cx_answer_support_policy_steady_state_continuation_review_manifest.v1"
        or report.get("status") != policy["required_source_status"]
        or report.get("decision") != policy["required_source_decision"]
        or report.get("decision_status") != policy["required_decision_status"]
        or report.get("next_boundary") != policy["required_source_next_boundary"]
        or report.get("failed_checks") != []
        or not report_checks
        or any(value is not True for value in report_checks.values())
        or report.get("provider_calls") != 0
        or report.get("database_calls") != 0
        or report.get("holdout_accessed") is not False
        or report.get("controlled_continuation_confirmed") is not True
        or report.get("runtime_change_permitted") is not False
        or report.get("rollback_contract_preserved") is not True
        or report.get("production_cutover_permitted") is not False
        or receipt.get("receipt_schema_version")
        != "cx_answer_support_policy_steady_state_continuation_"
        "operator_review_receipt.v1"
        or receipt.get("status") != report.get("status")
        or receipt.get("decision") != report.get("decision")
        or receipt.get("decision_status") != report.get("decision_status")
        or receipt.get("design_hash") != report.get("design_hash")
        or receipt.get("operator_decision_hash") != report.get("operator_decision_hash")
        or receipt.get("manifest_hash") != report.get("manifest_hash")
        or receipt.get("source_evidence_hash") != report.get("source_evidence_hash")
        or receipt.get("source_report_document_hash")
        != report.get("source_report_document_hash")
        or receipt.get("prior_continuation_receipt_hash")
        != report.get("prior_continuation_receipt_hash")
        or receipt.get("next_boundary") != report.get("next_boundary")
        or receipt.get("steady_state_continuation_confirmed") is not True
        or receipt.get("runtime_changed") is not False
        or receipt.get("rollback_contract_preserved") is not True
        or receipt.get("production_cutover_permitted") is not False
    ):
        raise _invalid("source_review_boundary")
    metrics = _mapping(report.get("observed_metrics"), "observed_metrics")
    return {"observed_metrics": dict(metrics)}


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


def _invalid(name: str) -> PolicySteadyStateContinuationClosureError:
    return PolicySteadyStateContinuationClosureError(
        "POLICY_STEADY_STATE_CONTINUATION_CLOSURE_INVALID", f"{name} is invalid"
    )


def _integrity(name: str) -> PolicySteadyStateContinuationClosureError:
    return PolicySteadyStateContinuationClosureError(
        "POLICY_STEADY_STATE_CONTINUATION_CLOSURE_INTEGRITY",
        f"{name} integrity failed",
    )
