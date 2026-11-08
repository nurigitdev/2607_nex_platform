from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

EXTENDED_SHADOW_DESIGN_SCHEMA_VERSION = (
    "cx_answer_support_extended_shadow_slo_design.v1"
)
EXTENDED_SHADOW_MANIFEST_SCHEMA_VERSION = (
    "cx_answer_support_extended_shadow_slo_manifest.v1"
)
BACKGROUND_SLO_MET_DECISION = "BACKGROUND_SLO_MET_ASYNC_ISOLATION_REQUIRED"
BACKGROUND_SLO_MISSED_DECISION = "BACKGROUND_SLO_MISSED_ASYNC_ISOLATION_REQUIRED"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "latency_slo",
    "rollout_boundary",
    "safety",
}
_SOURCE_FIELDS = {
    "cutover_decision_manifest_hash",
    "cutover_decision_receipt_document_hash",
    "cutover_decision_receipt_hash",
    "extended_case_set_hash",
    "extended_shadow_policy_hash",
    "operator_decision_hash",
    "provider_binding_hash",
    "readiness_manifest_hash",
    "runtime_profile_hash",
}
_EXPECTED_LATENCY_SLO = {
    "minimum_completed_shadow_samples": 30,
    "interactive_e2e_p95_latency_ms": 8_000,
    "background_provider_p95_latency_ms": 45_000,
    "provider_timeout_ms": 60_000,
    "synchronous_inline_provider_call_permitted": False,
    "async_isolation_required": True,
}
_EXPECTED_ROLLOUT_BOUNDARY = {
    "candidate_mode": "SHADOW_ONLY",
    "current_runtime_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
    "latency_slo_source": "S149_PROTECTED_LIVE_AND_S20QPT_SHADOW_BUDGET",
    "production_cutover_requires_new_operator_decision": True,
    "next_boundary": "ASYNC_SHADOW_EXECUTION_AND_CAPACITY_HARDENING",
}
_EXPECTED_SAFETY = {
    "holdout_access_permitted": False,
    "database_call_permitted": False,
    "private_text_persistence_permitted": False,
    "disagreement_is_observation_only": True,
    "runtime_activation_permitted": False,
    "production_cutover_permitted": False,
}
_CUTOVER_RECEIPT_FIELDS = {
    "receipt_schema_version",
    "status",
    "decision",
    "operator_decision_hash",
    "manifest_hash",
    "source_receipt_hash",
    "reason_codes",
    "decided_at",
    "runtime_activation_permitted",
    "production_cutover_permitted",
    "receipt_hash",
}
_EXTENDED_RECEIPT_FIELDS = {
    "approval_hash",
    "checks",
    "completed_at",
    "decision",
    "manifest_hash",
    "maximum_provider_calls",
    "policy_hash",
    "production_cutover_permitted",
    "profile_hash",
    "provider_binding_hash",
    "provider_http_requests",
    "receipt_hash",
    "receipt_schema_version",
    "runtime_activation_permitted",
    "snapshot",
    "started_at",
    "status",
}
_REQUIRED_EXTENDED_CHECKS = {
    "holdout_not_accessed",
    "latency_budget_passed",
    "latency_samples_complete",
    "no_provider_failures",
    "one_shot_budget_completed",
    "operator_approval_bound",
    "production_cutover_prohibited",
    "provider_calls_exact",
    "runtime_activation_prohibited",
    "shadow_not_user_visible",
    "token_budget_passed",
}
_SNAPSHOT_FIELDS = {
    "approval_hash",
    "disagreement_count",
    "disagreement_rate",
    "error_rate",
    "failed_count",
    "latency_sample_count",
    "maximum_latency_ms",
    "maximum_provider_calls",
    "observed_count",
    "p95_latency_ms",
    "policy_hash",
    "production_cutover_permitted",
    "provider_calls",
    "runtime_activation_permitted",
    "snapshot_hash",
    "snapshot_schema_version",
    "status",
    "terminal_reason",
    "total_tokens",
    "user_visible",
}


class AnswerSupportExtendedShadowError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_extended_shadow_slo_design(
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the SLO contract frozen before extended live observation."""
    normalized = dict(design)
    supplied_hash = normalized.pop("design_hash", None)
    _exact_mapping(normalized, _DESIGN_FIELDS, "design")
    if (
        normalized.get("design_schema_version") != EXTENDED_SHADOW_DESIGN_SCHEMA_VERSION
        or normalized.get("status") != "FROZEN_PRE_OBSERVATION"
    ):
        raise _invalid("design_identity")
    _required_text(normalized.get("design_id"), "design_id")
    source = _exact_mapping(
        normalized.get("source_binding"), _SOURCE_FIELDS, "source_binding"
    )
    normalized["source_binding"] = {
        key: _hash_ref(source.get(key), key) for key in sorted(_SOURCE_FIELDS)
    }
    if dict(_mapping(normalized.get("latency_slo"), "latency_slo")) != (
        _EXPECTED_LATENCY_SLO
    ):
        raise _invalid("latency_slo")
    if dict(_mapping(normalized.get("rollout_boundary"), "rollout_boundary")) != (
        _EXPECTED_ROLLOUT_BOUNDARY
    ):
        raise _invalid("rollout_boundary")
    if dict(_mapping(normalized.get("safety"), "safety")) != _EXPECTED_SAFETY:
        raise _invalid("safety")
    calculated_hash = semantic_sha256_hash_ref(normalized)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated_hash
    ):
        raise _integrity("design")
    normalized["design_hash"] = calculated_hash
    return normalized


def evaluate_extended_shadow_slo(
    cutover_decision_receipt: Mapping[str, Any],
    extended_shadow_receipt: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze latency classes and assess extended shadow evidence."""
    normalized_design = validate_extended_shadow_slo_design(design)
    _validate_cutover_decision_receipt(
        cutover_decision_receipt, source=normalized_design["source_binding"]
    )
    extended = _validate_extended_receipt(
        extended_shadow_receipt,
        source=normalized_design["source_binding"],
        minimum_samples=normalized_design["latency_slo"][
            "minimum_completed_shadow_samples"
        ],
    )
    snapshot = extended["snapshot"]
    latency_slo = normalized_design["latency_slo"]
    background_slo_met = (
        snapshot["p95_latency_ms"] <= latency_slo["background_provider_p95_latency_ms"]
    )
    decision = (
        BACKGROUND_SLO_MET_DECISION
        if background_slo_met
        else BACKGROUND_SLO_MISSED_DECISION
    )
    checks = {
        "prior_operator_deferral_bound": True,
        "extended_sample_count_complete": True,
        "latency_samples_complete": True,
        "provider_failures_zero": True,
        "provider_timeout_separate_from_slo": (
            latency_slo["provider_timeout_ms"]
            > latency_slo["background_provider_p95_latency_ms"]
            > latency_slo["interactive_e2e_p95_latency_ms"]
        ),
        "background_provider_p95_slo_met": background_slo_met,
        "synchronous_inline_provider_prohibited": True,
        "async_isolation_required": True,
        "current_runtime_policy_preserved": True,
        "holdout_not_accessed": True,
        "runtime_activation_prohibited": True,
        "production_cutover_prohibited": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": EXTENDED_SHADOW_MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": decision,
        "background_slo_status": "MET" if background_slo_met else "MISSED",
        "design_hash": normalized_design["design_hash"],
        "source_receipt_hashes": {
            "cutover_decision": cutover_decision_receipt["receipt_hash"],
            "extended_shadow": extended["receipt_hash"],
        },
        "latency_slo": dict(latency_slo),
        "observed_metrics": {
            "sample_count": snapshot["provider_calls"],
            "failed_count": snapshot["failed_count"],
            "latency_sample_count": snapshot["latency_sample_count"],
            "p95_latency_ms": snapshot["p95_latency_ms"],
            "maximum_latency_ms": snapshot["maximum_latency_ms"],
            "disagreement_count": snapshot["disagreement_count"],
            "disagreement_rate": snapshot["disagreement_rate"],
            "total_tokens": snapshot["total_tokens"],
        },
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "fallback_policy": normalized_design["rollout_boundary"][
            "current_runtime_policy"
        ],
        "provider_calls_during_evaluation": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": normalized_design["rollout_boundary"]["next_boundary"],
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def validate_extended_shadow_entry(
    cutover_decision_receipt: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    cases_document: Mapping[str, Any],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed on all pre-observation source and artifact bindings."""
    normalized_design = validate_extended_shadow_slo_design(design)
    source = normalized_design["source_binding"]
    _validate_cutover_decision_receipt(cutover_decision_receipt, source=source)
    if semantic_sha256_hash_ref(dict(policy)) != source["extended_shadow_policy_hash"]:
        raise _integrity("extended_shadow_policy")
    if (
        semantic_sha256_hash_ref(dict(cases_document))
        != source["extended_case_set_hash"]
    ):
        raise _integrity("extended_case_set")
    return normalized_design


def _validate_cutover_decision_receipt(
    receipt: Mapping[str, Any], *, source: Mapping[str, Any]
) -> None:
    normalized = dict(receipt)
    _exact_mapping(normalized, _CUTOVER_RECEIPT_FIELDS, "cutover_receipt")
    receipt_hash = _hash_ref(normalized.pop("receipt_hash", None), "receipt_hash")
    if (
        semantic_sha256_hash_ref(normalized) != receipt_hash
        or receipt_hash != source["cutover_decision_receipt_hash"]
    ):
        raise _integrity("cutover_receipt")
    normalized["receipt_hash"] = receipt_hash
    if (
        semantic_sha256_hash_ref(normalized)
        != source["cutover_decision_receipt_document_hash"]
    ):
        raise _integrity("cutover_receipt_document")
    if (
        normalized.get("receipt_schema_version")
        != "cx_answer_support_runtime_cutover_decision_receipt.v1"
        or normalized.get("status") != "PASS"
        or normalized.get("decision") != "CUTOVER_DEFERRED_CONTINUE_SHADOW"
        or normalized.get("manifest_hash") != source["cutover_decision_manifest_hash"]
        or normalized.get("operator_decision_hash") != source["operator_decision_hash"]
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
    ):
        raise _invalid("cutover_receipt_boundary")


def _validate_extended_receipt(
    receipt: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    minimum_samples: int,
) -> dict[str, Any]:
    normalized = dict(receipt)
    _exact_mapping(normalized, _EXTENDED_RECEIPT_FIELDS, "extended_receipt")
    receipt_hash = _hash_ref(normalized.pop("receipt_hash", None), "receipt_hash")
    if semantic_sha256_hash_ref(normalized) != receipt_hash:
        raise _integrity("extended_receipt")
    normalized["receipt_hash"] = receipt_hash
    checks = _exact_mapping(
        normalized.get("checks"), _REQUIRED_EXTENDED_CHECKS, "extended_checks"
    )
    counts = _exact_mapping(
        normalized.get("provider_http_requests"),
        {"generation", "total"},
        "provider_http_requests",
    )
    snapshot = _validate_snapshot(
        normalized.get("snapshot"),
        policy_hash=source["extended_shadow_policy_hash"],
        approval_hash=normalized.get("approval_hash"),
    )
    if (
        normalized.get("receipt_schema_version")
        != "cx_answer_support_shadow_canary_receipt.v1"
        or normalized.get("status") != "PASS"
        or normalized.get("decision")
        != "SHADOW_CANARY_ACCEPTED_OPERATOR_REVIEW_REQUIRED"
        or normalized.get("policy_hash") != source["extended_shadow_policy_hash"]
        or normalized.get("manifest_hash") != source["readiness_manifest_hash"]
        or normalized.get("profile_hash") != source["runtime_profile_hash"]
        or normalized.get("provider_binding_hash") != source["provider_binding_hash"]
        or normalized.get("maximum_provider_calls") != minimum_samples
        or counts != {"generation": minimum_samples, "total": minimum_samples}
        or any(value is not True for value in checks.values())
        or snapshot["provider_calls"] != minimum_samples
        or snapshot["observed_count"] != minimum_samples
        or snapshot["latency_sample_count"] != minimum_samples
        or snapshot["failed_count"] != 0
        or snapshot["error_rate"] != 0.0
        or normalized.get("runtime_activation_permitted") is not False
        or normalized.get("production_cutover_permitted") is not False
    ):
        raise _invalid("extended_receipt_boundary")
    normalized["snapshot"] = snapshot
    return normalized


def _validate_snapshot(
    value: object, *, policy_hash: str, approval_hash: object
) -> dict[str, Any]:
    snapshot = dict(_exact_mapping(value, _SNAPSHOT_FIELDS, "snapshot"))
    snapshot_hash = _hash_ref(snapshot.pop("snapshot_hash", None), "snapshot_hash")
    if semantic_sha256_hash_ref(snapshot) != snapshot_hash:
        raise _integrity("snapshot")
    snapshot["snapshot_hash"] = snapshot_hash
    integer_fields = (
        "provider_calls",
        "maximum_provider_calls",
        "observed_count",
        "failed_count",
        "disagreement_count",
        "latency_sample_count",
        "total_tokens",
    )
    numeric_fields = (
        "error_rate",
        "disagreement_rate",
        "p95_latency_ms",
        "maximum_latency_ms",
    )
    if any(not _nonnegative_int(snapshot.get(name)) for name in integer_fields):
        raise _invalid("snapshot_counts")
    if any(not _nonnegative_number(snapshot.get(name)) for name in numeric_fields):
        raise _invalid("snapshot_metrics")
    if (
        snapshot.get("snapshot_schema_version")
        != "cx_answer_support_shadow_canary_snapshot.v1"
        or snapshot.get("status") != "COMPLETED"
        or snapshot.get("terminal_reason") is not None
        or snapshot.get("policy_hash") != policy_hash
        or snapshot.get("approval_hash") != approval_hash
        or snapshot.get("user_visible") is not False
        or snapshot.get("runtime_activation_permitted") is not False
        or snapshot.get("production_cutover_permitted") is not False
        or snapshot["maximum_latency_ms"] < snapshot["p95_latency_ms"]
    ):
        raise _invalid("snapshot_boundary")
    return snapshot


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _nonnegative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) >= 0.0
    )


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(name)
    return value.strip()


def _hash_ref(value: object, name: str) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(name) from exc


def _exact_mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    normalized = _mapping(value, name)
    if set(normalized) != fields:
        raise _invalid(name)
    return normalized


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _invalid(name: str) -> AnswerSupportExtendedShadowError:
    return AnswerSupportExtendedShadowError(
        "cx.answer_support_extended_shadow.contract_invalid",
        f"{name} is invalid.",
    )


def _integrity(name: str) -> AnswerSupportExtendedShadowError:
    return AnswerSupportExtendedShadowError(
        "cx.answer_support_extended_shadow.integrity_invalid",
        f"{name} integrity validation failed.",
    )
