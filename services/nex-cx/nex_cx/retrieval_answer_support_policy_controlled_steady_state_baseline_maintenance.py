from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

POLICY_SCHEMA_VERSION = (
    "cx_answer_support_policy_controlled_steady_state_baseline_maintenance.v1"
)
DECISION = "ANSWER_SUPPORT_POLICY_CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE_ACTIVE"
MAINTENANCE_STATUS = "ACTIVE_CONTROLLED_BASELINE_MAINTENANCE"
NEXT_BOUNDARY = "ANSWER_SUPPORT_POLICY_CONTROLLED_STEADY_STATE_BASELINE_PERIODIC_REVIEW"

_POLICY_FIELDS = {
    "policy_schema_version",
    "policy_id",
    "status",
    "source_binding",
    "maintenance_contract",
    "drift_trigger_map",
    "reopen_triggers",
    "safety",
}
_SOURCE_FIELDS = {
    "source_closure_design_hash",
    "source_closure_hash",
    "source_closure_report_document_hash",
    "continuation_policy_hash",
    "operations_profile_hash",
    "selected_policy_hash",
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
_DRIFT_TRIGGER_MAP = {
    "source_closure_design_hash": "EXPLICIT_OPERATOR_REOPEN_DECISION",
    "source_closure_hash": "EXPLICIT_OPERATOR_REOPEN_DECISION",
    "source_closure_report_document_hash": "EXPLICIT_OPERATOR_REOPEN_DECISION",
    "continuation_policy_hash": "CALIBRATION_DATASET_OR_SELECTED_POLICY_CHANGED",
    "operations_profile_hash": "OPERATIONS_PROFILE_OR_SLO_CHANGED",
    "selected_policy_hash": "CALIBRATION_DATASET_OR_SELECTED_POLICY_CHANGED",
}
_MAINTENANCE_CONTRACT = {
    "maintenance_mode": "PASSIVE_GUARDRAIL",
    "maintenance_status": MAINTENANCE_STATUS,
    "review_mode": "EVENT_DRIVEN_WITH_MAX_INTERVAL",
    "max_review_interval_days": 30,
    "periodic_review_required": True,
    "provider_backed_revalidation_automatic": False,
    "automatic_reopen_permitted": False,
    "reopen_requires_explicit_admission": True,
    "runtime_disposition": "CONTINUE_CONTROLLED_STEADY_STATE_OPERATIONS",
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
_CLOSURE_REPORT_FIELDS = {
    "automatic_reopen_permitted",
    "baseline_status",
    "checks",
    "closure_hash",
    "closure_status",
    "continuation_policy_hash",
    "corrective_chain_closed",
    "database_calls",
    "decision",
    "design_hash",
    "evidence_schema_version",
    "failed_checks",
    "holdout_accessed",
    "manifest_schema_version",
    "next_boundary",
    "observed_metrics",
    "operations_profile_hash",
    "operator_decision_hash",
    "operator_review_design_hash",
    "operator_review_manifest_hash",
    "operator_review_receipt_document_hash",
    "operator_review_receipt_hash",
    "operator_review_report_document_hash",
    "prior_continuation_receipt_hash",
    "production_cutover_permitted",
    "provider_calls",
    "reopen_triggers",
    "rollback_contract_preserved",
    "runtime_changed",
    "runtime_disposition",
    "selected_policy_hash",
    "slice_id",
    "source_continuation_evidence_hash",
    "source_continuation_report_document_hash",
    "status",
}


class ControlledSteadyStateBaselineMaintenanceError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_controlled_steady_state_baseline_maintenance_policy(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    policy = dict(_mapping(value, "policy"))
    supplied_hash = policy.pop("policy_hash", None)
    _exact(policy, _POLICY_FIELDS, "policy")
    if (
        policy.get("policy_schema_version") != POLICY_SCHEMA_VERSION
        or policy.get("status") != "FROZEN_CONTROLLED_BASELINE_MAINTENANCE"
        or not _text(policy.get("policy_id"))
    ):
        raise _invalid("policy_identity")

    source = _exact(policy.get("source_binding"), _SOURCE_FIELDS, "source_binding")
    policy["source_binding"] = {
        name: _hash_ref(source.get(name), name) for name in _SOURCE_FIELDS
    }
    if dict(_mapping(policy.get("maintenance_contract"), "maintenance_contract")) != (
        _MAINTENANCE_CONTRACT
    ):
        raise _invalid("maintenance_contract")
    if dict(_mapping(policy.get("drift_trigger_map"), "drift_trigger_map")) != (
        _DRIFT_TRIGGER_MAP
    ):
        raise _invalid("drift_trigger_map")
    if policy.get("reopen_triggers") != list(_REOPEN_TRIGGERS):
        raise _invalid("reopen_triggers")
    if dict(_mapping(policy.get("safety"), "safety")) != _SAFETY:
        raise _invalid("safety")

    calculated = semantic_sha256_hash_ref(policy)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "policy_hash") != calculated
    ):
        raise _integrity("policy")
    policy["policy_hash"] = calculated
    return policy


def build_controlled_steady_state_baseline_maintenance(
    *,
    policy: Mapping[str, Any],
    closure_report: Mapping[str, Any],
    last_reviewed_at: str,
    evaluated_at: str,
    current_identity: Mapping[str, Any] | None = None,
    observed_reopen_events: Iterable[str] = (),
) -> dict[str, Any]:
    normalized = validate_controlled_steady_state_baseline_maintenance_policy(policy)
    closure_identity = _validate_closure_report(normalized, closure_report)
    observed_identity = _normalize_identity(
        closure_identity if current_identity is None else current_identity
    )
    events = _normalize_events(observed_reopen_events)
    drifted_fields = [
        name
        for name in _SOURCE_FIELDS
        if observed_identity[name] != normalized["source_binding"][name]
    ]
    triggered = {
        *events,
        *(_DRIFT_TRIGGER_MAP[name] for name in drifted_fields),
    }
    triggered_ordered = [name for name in _REOPEN_TRIGGERS if name in triggered]

    reviewed = _timestamp(last_reviewed_at, "last_reviewed_at")
    evaluated = _timestamp(evaluated_at, "evaluated_at")
    if evaluated < reviewed:
        raise _invalid("review_window")
    due_at = reviewed + timedelta(
        days=normalized["maintenance_contract"]["max_review_interval_days"]
    )
    review_due = evaluated > due_at

    if triggered_ordered:
        maintenance_status = "BASELINE_REOPEN_REQUIRED"
        decision = "ANSWER_SUPPORT_POLICY_CONTROLLED_BASELINE_REOPEN_REQUIRED"
        runtime_disposition = "HOLD_CONTROLLED_BASELINE_PENDING_EXPLICIT_REOPEN"
        admission_status = "FAIL_CLOSED_REOPEN_REQUIRED"
    elif review_due:
        maintenance_status = "PERIODIC_REVIEW_DUE"
        decision = "ANSWER_SUPPORT_POLICY_CONTROLLED_BASELINE_REVIEW_REQUIRED"
        runtime_disposition = "HOLD_CONTROLLED_BASELINE_PENDING_OPERATOR_REVIEW"
        admission_status = "FAIL_CLOSED_REVIEW_REQUIRED"
    else:
        maintenance_status = MAINTENANCE_STATUS
        decision = DECISION
        runtime_disposition = normalized["maintenance_contract"]["runtime_disposition"]
        admission_status = "ADMITTED_CONTROLLED_BASELINE"

    checks = {
        "maintenance_policy_integrity_verified": True,
        "closure_report_integrity_verified": True,
        "exact_closure_design_bound": True,
        "exact_closure_manifest_bound": True,
        "exact_closure_report_document_bound": True,
        "continuation_policy_bound": True,
        "operations_profile_bound": True,
        "selected_policy_bound": True,
        "reopen_triggers_frozen": True,
        "review_cadence_enforced": True,
        "automatic_reopen_prohibited": True,
        "provider_revalidation_not_automatic": True,
        "no_external_calls_verified": True,
        "holdout_not_accessed": True,
        "runtime_unchanged": True,
        "rollback_contract_preserved": True,
        "production_cutover_prohibited": True,
    }
    result: dict[str, Any] = {
        "maintenance_schema_version": (
            "cx_answer_support_policy_controlled_steady_state_baseline_"
            "maintenance_snapshot.v1"
        ),
        "status": "PASS",
        "decision": decision,
        "maintenance_status": maintenance_status,
        "admission_status": admission_status,
        "policy_hash": normalized["policy_hash"],
        **normalized["source_binding"],
        "current_identity": observed_identity,
        "last_reviewed_at": _iso(reviewed),
        "evaluated_at": _iso(evaluated),
        "next_review_due_at": _iso(due_at),
        "review_due": review_due,
        "drifted_fields": sorted(drifted_fields),
        "observed_reopen_events": list(events),
        "triggered_reopen_conditions": triggered_ordered,
        "baseline_status": "FROZEN",
        "runtime_disposition": runtime_disposition,
        "corrective_chain_closed": True,
        "new_corrective_chain_opened": False,
        "automatic_reopen_permitted": False,
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_changed": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
        "checks": checks,
        "failed_checks": [],
        "next_boundary": NEXT_BOUNDARY,
    }
    result["maintenance_hash"] = semantic_sha256_hash_ref(result)
    return result


def _validate_closure_report(
    policy: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, str]:
    report = dict(_exact(value, _CLOSURE_REPORT_FIELDS, "closure_report"))
    source = policy["source_binding"]
    report_document_hash = semantic_sha256_hash_ref(report)
    closure_payload = dict(report)
    closure_payload.pop("evidence_schema_version")
    closure_payload.pop("slice_id")
    closure_hash = _hash_ref(closure_payload.pop("closure_hash"), "closure_hash")
    checks = _mapping(report.get("checks"), "closure_checks")
    if (
        report_document_hash != source["source_closure_report_document_hash"]
        or semantic_sha256_hash_ref(closure_payload) != closure_hash
        or closure_hash != source["source_closure_hash"]
        or report.get("design_hash") != source["source_closure_design_hash"]
    ):
        raise _integrity("closure_report")
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpas_answer_support_policy_steady_state_operations_"
        "continuation_closure.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-AS"
        or report.get("manifest_schema_version")
        != "cx_answer_support_policy_steady_state_continuation_closure_manifest.v1"
        or report.get("status") != "PASS"
        or report.get("decision")
        != "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION_CLOSED"
        or report.get("closure_status") != "CLOSED_CONTROLLED_OPERATIONS_BASELINE"
        or report.get("baseline_status") != "FROZEN"
        or report.get("runtime_disposition")
        != "CONTINUE_CONTROLLED_STEADY_STATE_OPERATIONS"
        or report.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE"
        or report.get("continuation_policy_hash") != source["continuation_policy_hash"]
        or report.get("operations_profile_hash") != source["operations_profile_hash"]
        or report.get("selected_policy_hash") != source["selected_policy_hash"]
        or report.get("reopen_triggers") != list(_REOPEN_TRIGGERS)
        or report.get("failed_checks") != []
        or not checks
        or any(value is not True for value in checks.values())
        or report.get("provider_calls") != 0
        or report.get("database_calls") != 0
        or report.get("holdout_accessed") is not False
        or report.get("runtime_changed") is not False
        or report.get("rollback_contract_preserved") is not True
        or report.get("production_cutover_permitted") is not False
        or report.get("corrective_chain_closed") is not True
        or report.get("automatic_reopen_permitted") is not False
    ):
        raise _invalid("closure_boundary")
    return {
        "source_closure_design_hash": report["design_hash"],
        "source_closure_hash": closure_hash,
        "source_closure_report_document_hash": report_document_hash,
        "continuation_policy_hash": report["continuation_policy_hash"],
        "operations_profile_hash": report["operations_profile_hash"],
        "selected_policy_hash": report["selected_policy_hash"],
    }


def _normalize_identity(value: Mapping[str, Any]) -> dict[str, str]:
    identity = _exact(value, _SOURCE_FIELDS, "current_identity")
    return {name: _hash_ref(identity.get(name), name) for name in _SOURCE_FIELDS}


def _normalize_events(values: Iterable[str]) -> tuple[str, ...]:
    events = tuple(dict.fromkeys(values))
    if any(event not in _REOPEN_TRIGGERS for event in events):
        raise _invalid("observed_reopen_events")
    return events


def _timestamp(value: object, name: str) -> datetime:
    if not _text(value):
        raise _invalid(name)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(name) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(name)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _invalid(name: str) -> ControlledSteadyStateBaselineMaintenanceError:
    return ControlledSteadyStateBaselineMaintenanceError(
        "CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE_INVALID",
        f"{name} is invalid",
    )


def _integrity(name: str) -> ControlledSteadyStateBaselineMaintenanceError:
    return ControlledSteadyStateBaselineMaintenanceError(
        "CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE_INTEGRITY",
        f"{name} integrity failed",
    )
